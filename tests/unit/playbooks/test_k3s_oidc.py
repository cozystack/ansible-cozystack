# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Cozystack Contributors
# Apache License 2.0 (see LICENSE file in the repository root)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import base64
import copy
import fnmatch
import json
import os
import shutil
import subprocess

import pytest
import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PLAYBOOK = "playbooks/k3s_oidc.yml"
DROPIN = "/etc/rancher/k3s/config.yaml.d/90-cozystack-oidc.yaml"


def _read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as stream:
        return stream.read()


def _plays():
    return yaml.safe_load(_read(PLAYBOOK))


def _task(name):
    for play in _plays():
        for task in play.get("tasks", []):
            if task.get("name") == name:
                return copy.deepcopy(task)
    raise AssertionError("Task not found: " + name)


def _run(tmp_path, tasks, variables=None, check=False):
    executable = shutil.which("ansible-playbook")
    assert executable, "ansible-playbook is required"
    path = tmp_path / "test.yml"
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "Test OIDC tasks locally",
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": variables or {},
                    "tasks": tasks,
                }
            ]
        ),
        encoding="utf-8",
    )
    command = [
        executable,
        str(path),
        "--inventory",
        "localhost,",
        "--connection",
        "local",
    ]
    if check:
        command.append("--check")
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_opt_in_and_existing_kubernetes_isolation():
    defaults = yaml.safe_load(_read("roles/cozystack/defaults/main.yml"))
    assert defaults["cozystack_oidc_enabled"] is False
    assert "k3s_oidc" not in _read("playbooks/site.yml")
    for distro in ("ubuntu", "rhel", "suse"):
        plays = yaml.safe_load(_read("examples/%s/site.yml" % distro))
        assert (
            plays[-1]["ansible.builtin.import_playbook"] == "cozystack.installer.site"
        )
        assert "k3s_oidc" not in _read("examples/%s/site.yml" % distro)
    for play in _plays():
        assert play["hosts"] == "server"
        assert play["any_errors_fatal"] is True
        assert play["pre_tasks"][0]["ansible.builtin.meta"] == "end_host"
        assert "cozystack_oidc_enabled" in play["pre_tasks"][0]["when"]
    assert _plays()[1]["serial"] == 1
    assert "state: absent" not in _read(PLAYBOOK)


@pytest.mark.parametrize(
    "enabled,expected",
    [(False, False), (True, True), ("false", False), ("true", True)],
)
def test_platform_oidc_is_opt_in(enabled, expected):
    environment = Environment(
        loader=FileSystemLoader(os.path.join(ROOT, "roles/cozystack/templates"))
    )
    environment.filters["to_json"] = json.dumps
    environment.filters["bool"] = to_bool
    variables = dict(
        cozystack_platform_variant="isp-full-generic",
        cozystack_api_server_host="192.0.2.10",
        cozystack_api_server_port="6443",
        _cozystack_master_nodes="192.0.2.10",
        cozystack_pod_cidr="10.42.0.0/16",
        cozystack_pod_gateway="10.42.0.1",
        cozystack_svc_cidr="10.43.0.0/16",
        cozystack_join_cidr="100.64.0.0/16",
        cozystack_root_host="example.org",
        _cozystack_api_endpoint="https://api.example.org",
        cozystack_external_ips=[],
        cozystack_oidc_enabled=enabled,
    )
    template = environment.get_template("platform-package.yml.j2")
    values = yaml.safe_load(template.render(**variables))["spec"]["components"][
        "platform"
    ]["values"]
    if expected:
        assert values["authentication"]["oidc"]["enabled"] is True
    else:
        assert "authentication" not in values


def test_disabled_playbook_makes_no_connections(tmp_path):
    result = subprocess.run(
        [
            shutil.which("ansible-playbook"),
            os.path.join(ROOT, PLAYBOOK),
            "--inventory",
            "server,",
            "--extra-vars",
            '{"cozystack_oidc_enabled": false}',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UNREACHABLE" not in result.stdout
    assert "Read OIDC discovery" not in result.stdout
    assert "Append Kubernetes OIDC arguments" not in result.stdout


@pytest.mark.parametrize(
    "path,config,allowed",
    [
        (
            "/etc/rancher/k3s/config.yaml",
            {"kube-apiserver-arg": ["audit-log-maxage=10"]},
            True,
        ),
        (
            "/etc/rancher/k3s/config.yaml.d/99-extra.yml",
            {"kube-apiserver-arg+": ["audit-log-maxage=10"]},
            True,
        ),
        (
            "/etc/rancher/k3s/config.yaml.d/99-extra.yml",
            {"kube-apiserver-arg": ["audit-log-maxage=10"]},
            False,
        ),
        (
            "/etc/rancher/k3s/config.yaml",
            {"kube-apiserver-arg": ["authentication-config=/etc/auth.yaml"]},
            False,
        ),
        (
            "/etc/rancher/k3s/config.yaml",
            {"kube-apiserver-arg+": ["oidc-client-id=other"]},
            False,
        ),
        (
            "/etc/rancher/k3s/config.yaml",
            {"kube-apiserver-arg": ["--oidc-issuer-url=https://other.example"]},
            False,
        ),
        (
            "/etc/rancher/k3s/config.yaml",
            {"node-label": ["example.org/oidc-enabled=true"]},
            True,
        ),
        (
            "/etc/rancher/k3s/config.yaml",
            {"kube-apiserver-arg": ["audit-log-path=/var/log/oidc-audit.log"]},
            True,
        ),
        (
            "/etc/rancher/k3s/config.yaml",
            {
                "kube-apiserver-arg": "audit-policy-file=/etc/kubernetes/authentication-config-audit.yaml"
            },
            True,
        ),
        ("/etc/rancher/k3s/config.yaml", {"kube-apiserver-arg": None}, True),
        ("/etc/rancher/k3s/config.yaml", {"kube-apiserver-arg+": None}, True),
        ("/etc/rancher/k3s/config.yaml", [], False),
    ],
)
def test_existing_config_guards(tmp_path, path, config, allowed):
    task = _task("Validate existing API-server configuration")
    task.pop("loop")
    task.pop("no_log", None)
    variables = {
        "_cozystack_oidc_config_path": DROPIN,
        "item": {
            "item": path,
            "content": base64.b64encode(yaml.safe_dump(config).encode()).decode(),
        },
    }
    result = _run(tmp_path, [task], variables)
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr


@pytest.mark.parametrize(
    "arguments,environment,allowed",
    [
        ("/usr/local/bin/k3s server --disable=traefik", "PATH=/bin\0", True),
        (
            "/usr/local/bin/k3s server --kube-apiserver-arg=audit-log-maxage=10",
            "",
            False,
        ),
        ("/usr/local/bin/k3s server --config=/etc/rancher/k3s/config.yaml", "", True),
        ("/usr/local/bin/k3s server --config /etc/rancher/k3s/config.yaml", "", True),
        ("/usr/local/bin/k3s server -c /etc/rancher/k3s/config.yaml", "", True),
        ("/usr/local/bin/k3s server -c/etc/rancher/k3s/config.yaml", "", True),
        ("/usr/local/bin/k3s server -c/etc/other.yaml", "", False),
        (
            "/usr/local/bin/k3s server",
            "K3S_CONFIG_FILE=/etc/rancher/k3s/config.yaml\0",
            True,
        ),
        ("/usr/local/bin/k3s server", "K3S_CONFIG_FILE=\0PATH=/bin\0", True),
        ("/usr/local/bin/k3s server --config=", "", False),
        ("/usr/local/bin/k3s server -c=", "", False),
        ("/usr/local/bin/k3s server --config=/etc/other.yaml", "", False),
        ("/usr/local/bin/k3s server -c /etc/other.yaml", "", False),
        (
            "/usr/local/bin/k3s server",
            "K3S_KUBE_APISERVER_ARG=audit-log-maxage=10\0",
            False,
        ),
        ("/usr/local/bin/k3s server", "K3S_CONFIG_FILE=/etc/other.yaml\0", False),
    ],
)
def test_command_line_and_environment_guards(tmp_path, arguments, environment, allowed):
    task = _task("Validate k3s configuration sources")
    task.pop("no_log", None)
    variables = {
        "_cozystack_oidc_service": {"status": {"ExecStart": arguments}},
        "_cozystack_oidc_environment": {
            "content": base64.b64encode(environment.encode()).decode()
        },
    }
    result = _run(tmp_path, [task], variables)
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr


def test_dropin_preserves_base_and_is_idempotent(tmp_path):
    base = tmp_path / "config.yaml"
    base.write_text("kube-apiserver-arg:\n  - audit-log-maxage=10\n", encoding="utf-8")
    before = base.read_bytes()
    task = _task("Append Kubernetes OIDC arguments")
    task["ansible.builtin.copy"]["dest"] = str(tmp_path / "90-oidc.yaml")
    task["ansible.builtin.copy"].pop("owner", None)
    task["ansible.builtin.copy"].pop("group", None)
    task.pop("notify")
    first, second = copy.deepcopy(task), copy.deepcopy(task)
    first["register"] = "first"
    second["register"] = "second"
    result = _run(
        tmp_path,
        [
            first,
            second,
            {
                "name": "Check idempotency",
                "ansible.builtin.assert": {
                    "that": ["first.changed", "not second.changed"]
                },
            },
        ],
        {"_cozystack_oidc_issuer": "https://keycloak.example.org/realms/cozy"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert base.read_bytes() == before
    args = yaml.safe_load((tmp_path / "90-oidc.yaml").read_text())[
        "kube-apiserver-arg+"
    ]
    assert args == [
        "oidc-issuer-url=https://keycloak.example.org/realms/cozy",
        "oidc-client-id=kubernetes",
        "oidc-username-claim=preferred_username",
        "oidc-groups-claim=groups",
    ]
    assert _task("Append Kubernetes OIDC arguments")["notify"] == "Restart k3s for OIDC"


def test_check_mode_does_not_write_the_dropin(tmp_path):
    task = _task("Append Kubernetes OIDC arguments")
    destination = tmp_path / "90-oidc.yaml"
    task["ansible.builtin.copy"]["dest"] = str(destination)
    task["ansible.builtin.copy"].pop("owner", None)
    task["ansible.builtin.copy"].pop("group", None)
    task.pop("notify")
    result = _run(
        tmp_path,
        [task],
        {
            "_cozystack_oidc_issuer": "https://keycloak.example.org/realms/cozy",
        },
        check=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not destination.exists()


def test_role_rejects_oidc_without_publishing_domain(tmp_path):
    tasks = yaml.safe_load(_read("roles/cozystack/tasks/main.yml"))
    task = next(
        task for task in tasks if task.get("name") == "Validate OIDC publishing domain"
    )
    for host, enabled, allowed in (
        ("", True, False),
        ("example.org", True, True),
        ("", False, True),
    ):
        result = _run(
            tmp_path,
            [task],
            {
                "cozystack_oidc_enabled": enabled,
                "cozystack_root_host": host,
            },
        )
        assert (result.returncode == 0) is allowed, result.stdout + result.stderr


@pytest.mark.parametrize(
    "issuer,allowed",
    [
        ("https://keycloak.example.org/realms/cozy", True),
        ("http://keycloak.example.org/realms/cozy", False),
        ("https://user@keycloak.example.org/realms/cozy", False),
        ("https://keycloak.example.org/realms/cozy?query=value", False),
        ("https://keycloak.example.org/realms/cozy#fragment", False),
    ],
)
def test_preflight_validates_issuer(tmp_path, issuer, allowed):
    result = _run(
        tmp_path,
        [_task("Validate OIDC issuer")],
        {"cozystack_root_host": "example.org", "_cozystack_oidc_issuer": issuer},
    )
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr


def test_optional_base_configuration_can_be_absent(tmp_path):
    task = _task("Read existing k3s configuration")
    task.pop("no_log", None)
    result = _run(
        tmp_path,
        [task],
        {
            "_cozystack_oidc_base": {"stat": {"exists": False}},
            "_cozystack_oidc_fragments": {"files": []},
            "_cozystack_oidc_config_path": DROPIN,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_signing_key_readiness_is_retried(tmp_path):
    import http.server
    import threading

    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            keys = [] if len(requests) == 1 else [{"kid": "test"}]
            self.wfile.write(json.dumps({"keys": keys}).encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        task = _task("Read OIDC signing keys from each server")
        assert task.get("retries", 0) >= 2
        assert "until" in task
        task["ansible.builtin.uri"]["url"] = (
            "http://127.0.0.1:%s/keys" % server.server_port
        )
        task["delay"] = 0
        task["retries"] = 3
        result = _run(tmp_path, [task])
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(requests) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_fragment_discovery_matches_k3s_files_and_skips_directories(tmp_path):
    directory = tmp_path / "config.yaml.d"
    directory.mkdir()
    filenames = [
        "10-base.yaml",
        "20-extra.yml",
        "30-upper.YML",
        "40-mixed.YaMl",
        ".hidden.yaml",
    ]
    for filename in filenames:
        (directory / filename).write_text("{}\n", encoding="utf-8")
    (directory / "ignored.txt").write_text("not YAML", encoding="utf-8")
    (directory / "nested.yaml").mkdir()
    (directory / "50-link.yml").symlink_to(directory / "10-base.yaml")
    expected = [str(directory / name) for name in filenames + ["50-link.yml"]]
    find = _task("Find existing k3s configuration fragments")
    find["ansible.builtin.find"]["paths"] = str(directory)
    read = _task("Read existing k3s configuration")
    read.pop("no_log", None)
    result = _run(
        tmp_path,
        [
            find,
            read,
            {
                "name": "Verify all supported fragments were read",
                "ansible.builtin.assert": {
                    "that": "_cozystack_oidc_existing.results | map(attribute='item') | sort == expected | sort",
                },
            },
        ],
        {
            "_cozystack_oidc_config_dir": {"stat": {"exists": True}},
            "_cozystack_oidc_base": {"stat": {"exists": False}},
            "_cozystack_oidc_config_path": DROPIN,
            "expected": expected,
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_preflight_verifies_tls_and_every_supported_fragment_extension():
    find = _task("Find existing k3s configuration fragments")["ansible.builtin.find"]
    for filename in ("10-config.yaml", "99-auth.yml", "95-extra.YaML"):
        assert any(
            fnmatch.fnmatchcase(filename, pattern) for pattern in find["patterns"]
        )
    assert find["hidden"] is True
    assert find["file_type"] == "any"
    for name in (
        "Read OIDC discovery from each server",
        "Read OIDC signing keys from each server",
    ):
        task = _task(name)
        assert task["ansible.builtin.uri"]["validate_certs"] is True
        assert task["check_mode"] is False
    names = [task["name"] for task in _plays()[1]["tasks"]]
    assert names.index("Append Kubernetes OIDC arguments") < names.index(
        "Apply changed OIDC arguments"
    )
    assert names.index("Apply changed OIDC arguments") < names.index(
        "Wait for the local Kubernetes API"
    )
    assert (
        _task("Wait for the local Kubernetes API")["when"] == "not ansible_check_mode"
    )
