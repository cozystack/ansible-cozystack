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


def test_role_asserts_cozystack_namespace_is_cozy_system():
    # The cozy-installer chart hardcodes cozy-system in
    # templates/cozystack-operator.yaml — overriding the variable
    # used to silently break the role's wait/patch tasks. The role
    # must fail loud at validation time, not silently mid-run.
    tasks = _load_role_tasks()
    task = _find_role_task(
        tasks, "Validate cozystack_namespace matches chart hardcoded value"
    )
    assert_block = task.get("ansible.builtin.assert", {})
    that = assert_block.get("that") or []
    matched = [
        clause for clause in that
        if "cozystack_namespace" in clause and "cozy-system" in clause
    ]
    assert matched, (
        "assert must check cozystack_namespace == 'cozy-system'; got %r"
        % that
    )
    fail_msg = assert_block.get("fail_msg") or ""
    assert "cozy-system" in fail_msg and "chart" in fail_msg.lower(), (
        "fail_msg must mention 'cozy-system' and the chart constraint; "
        "got %r" % fail_msg
    )


def test_role_refuses_to_overwrite_foreign_helm_owner():
    # Adopting an existing cozy-system namespace is safe ONLY when
    # it carries no helm metadata or is already owned by this role's
    # release. If managed-by=Helm and release-name points at a
    # *different* helm release, the role must fail rather than
    # hijack ownership.
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
    helm_check = [
        c for c in when
        if "managed-by" in c and "Helm" in c
    ]
    assert helm_check, (
        "fail must gate on labels[app.kubernetes.io/managed-by] == "
        "'Helm' so missing-metadata namespaces still get adopted"
    )
    mismatch_check = [
        c for c in when
        if "release_name" in c.replace("-", "_")
        and "cozystack_release_name" in c
    ]
    assert mismatch_check, (
        "fail must gate on release-name annotation differing from "
        "cozystack_release_name"
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
