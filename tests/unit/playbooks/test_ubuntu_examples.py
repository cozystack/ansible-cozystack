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
