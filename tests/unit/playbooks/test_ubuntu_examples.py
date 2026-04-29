# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Cozystack Contributors
# Apache License 2.0 (see LICENSE file in the repository root)

# Structural tests for examples/ubuntu/ playbooks. These lock in the
# 26.04-related invariants that earlier review iterations got wrong:
# password leakage on raw commands, dependence on sudo-rs CLI flags,
# and silent breakage on linux-modules-extra-* for kernel 7.x.

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os

import yaml


REPO_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)


def _load_playbook(relpath):
    with open(os.path.join(REPO_ROOT, relpath), "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _find_task(plays, task_name):
    for play in plays:
        for task in play.get("tasks", []) or []:
            if task.get("name") == task_name:
                return task
    raise AssertionError(
        "task %r not found in %r"
        % (task_name, [p.get("name") for p in plays])
    )


# prepare-sudo.yml — secret-handling and sudo-binary invariants


def test_prepare_sudo_password_task_has_no_log():
    plays = _load_playbook("examples/ubuntu/prepare-sudo.yml")
    task = _find_task(plays, "Switch sudo alternative to /usr/bin/sudo.ws")
    assert task.get("no_log") is True, (
        "Switch sudo alternative task interpolates ansible_become_password "
        "into a raw shell command. no_log: true must be set so the "
        "password does not leak into ansible output on failure or with "
        "increased verbosity."
    )


def test_prepare_sudo_invokes_classical_binary_directly():
    plays = _load_playbook("examples/ubuntu/prepare-sudo.yml")
    task = _find_task(plays, "Switch sudo alternative to /usr/bin/sudo.ws")
    raw = task["ansible.builtin.raw"]
    # Both branches (password and passwordless) must call /usr/bin/sudo.ws
    # directly, never the `sudo` symlink — the symlink points at sudo-rs
    # on 26.04, which is the very binary the workaround exists to avoid.
    assert "/usr/bin/sudo.ws --stdin" in raw, (
        "password branch must invoke /usr/bin/sudo.ws --stdin directly"
    )
    assert "/usr/bin/sudo.ws --non-interactive" in raw, (
        "passwordless branch must invoke /usr/bin/sudo.ws --non-interactive "
        "directly"
    )
    # Guard against accidental reintroduction of the sudo-rs path.
    forbidden_lines = [
        line for line in raw.splitlines()
        if line.strip().startswith("sudo ")
        or line.strip().startswith("| sudo ")
    ]
    assert not forbidden_lines, (
        "raw command must not call bare `sudo` — that resolves to sudo-rs "
        "on 26.04 and re-introduces the bug. Offending lines: %r"
        % forbidden_lines
    )


# roles/cozystack/tasks/main.yml — namespace foot-gun protections


def _load_role_tasks():
    with open(
        os.path.join(REPO_ROOT, "roles/cozystack/tasks/main.yml"),
        "r",
        encoding="utf-8",
    ) as fh:
        return yaml.safe_load(fh)


def _find_role_task(tasks, name):
    for task in tasks:
        if task.get("name") == name:
            return task
    raise AssertionError(
        "task %r not found among %r"
        % (name, [t.get("name") for t in tasks])
    )


def test_role_rejects_removed_cozystack_namespace_variable():
    # cozystack_namespace was removed from defaults because the chart
    # hardcodes 'cozy-system' in templates/cozystack-operator.yaml. The
    # role must fail loud if a stale inventory still sets it, with a
    # message pointing at the chart constraint and telling the user
    # what to remove. Without this, an inventory carried over from an
    # older role version would silently re-introduce the foot-gun the
    # variable removal was meant to eliminate.
    tasks = _load_role_tasks()
    task = _find_role_task(tasks, "Reject removed cozystack_namespace variable")
    assert_block = task.get("ansible.builtin.assert", {})
    that = assert_block.get("that") or []
    matched = [
        clause for clause in that
        if "cozystack_namespace" in clause and "is not defined" in clause
    ]
    assert matched, (
        "assert must check `cozystack_namespace is not defined`; got %r"
        % that
    )
    fail_msg = assert_block.get("fail_msg") or ""
    for token in ("cozystack_namespace", "removed", "cozy-system"):
        assert token in fail_msg, (
            "fail_msg must mention %r so users get an actionable upgrade "
            "signal; got %r" % (token, fail_msg)
        )


def test_role_does_not_reference_removed_cozystack_namespace():
    # Once the variable is removed from defaults, leaving any
    # `{{ cozystack_namespace }}` reference in tasks or templates
    # causes an undefined-variable failure mid-run. Lock down the
    # invariant: the only places the identifier may appear are the
    # rejection assert task above and ansible/markdown comments.
    import re

    role_files = [
        "roles/cozystack/tasks/main.yml",
        "roles/cozystack/tasks/compute-master-nodes.yml",
        "roles/cozystack/tasks/validate-external-ips.yml",
        "roles/cozystack/templates/platform-package.yml.j2",
        "roles/cozystack/defaults/main.yml",
    ]
    offenders = []
    for relpath in role_files:
        full = os.path.join(REPO_ROOT, relpath)
        if not os.path.exists(full):
            continue
        with open(full, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue  # ansible comment
                # Allow the rejection-assert lines that name the
                # variable as a string identifier, not a Jinja ref.
                if "is not defined" in line or "cozystack_namespace was removed" in line:
                    continue
                if "Remove cozystack_namespace" in line or "Reject removed cozystack_namespace" in line:
                    continue
                if re.search(r"{{\s*cozystack_namespace", line):
                    offenders.append("%s:%d: %s" % (relpath, lineno, stripped))
    assert not offenders, (
        "cozystack_namespace was removed from defaults; remaining "
        "Jinja references will fail mid-run. Replace with literal "
        "'cozy-system' to match the chart. Offenders:\n%s"
        % "\n".join(offenders)
    )


def test_role_refuses_to_overwrite_foreign_helm_owner():
    # Adopting an existing cozy-system namespace is safe ONLY when
    # it carries no helm metadata or is already owned by this role's
    # release. If any helm-ownership indicator (managed-by label OR
    # release-name annotation OR release-namespace annotation) points
    # at a different helm release, the role must fail rather than
    # hijack ownership. Gating purely on managed-by would miss the
    # rare partial-write state.
    tasks = _load_role_tasks()
    task = _find_role_task(
        tasks,
        "Refuse to overwrite cozy-system if owned by another helm release",
    )
    assert "ansible.builtin.fail" in task, (
        "ownership-conflict task must use ansible.builtin.fail, "
        "not patch — overwriting another release's ownership is "
        "data-loss-class"
    )
    when = task.get("when") or []
    if isinstance(when, str):
        when = [when]
    # Flatten the conditions to a single string for substring checks
    when_blob = " ".join(when)
    # The strengthened check must reference all three indicators.
    for marker in ("managed-by", "release_name", "release_namespace"):
        assert marker in when_blob, (
            "fail `when:` must reference %r so a partial-write state "
            "(annotations set but label missing, or vice versa) is "
            "still detected. Got: %r" % (marker, when)
        )
    # And must compare against this role's release identity.
    for var in ("cozystack_release_name", "cozystack_release_namespace"):
        assert var in when_blob, (
            "fail `when:` must compare against %r" % var
        )


# prepare-ubuntu.yml — auto-skip on 26.04+


def test_linux_modules_extra_auto_skips_on_26_04():
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Install Ubuntu-only extra kernel modules")
    when = task.get("when")
    assert isinstance(when, list), (
        "expected list-form `when:` for clarity, got %r" % type(when)
    )
    # The version check must be present so users on 26.04+ do not have
    # to learn about the cozystack_ubuntu_extra_packages override.
    version_clauses = [
        c for c in when if "ansible_distribution_version" in c
        and "26.04" in c
    ]
    assert version_clauses, (
        "`when:` clause must auto-skip on Ubuntu 26.04+: "
        "linux-modules-extra-* does not exist for kernel 7.x. "
        "Got: %r" % when
    )
