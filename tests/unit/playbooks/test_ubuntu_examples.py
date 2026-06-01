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


# prepare-ubuntu.yml — DRBD/Secure Boot invariants


def test_drbd_modprobe_is_tolerated_via_ignore_errors():
    # piraeus-operator's loader needs DRBD host-loaded with
    # usermode_helper=disabled; on Secure Boot hosts the dkms key is not
    # enrolled until the operator confirms MOK at the next reboot, so the
    # initial modprobe must be tolerated. The tolerance MUST be expressed
    # as `ignore_errors: true`, not `failed_when: false`. The latter
    # rewrites the registered variable's `failed` field to False, which
    # silently breaks the persistence and warn tasks that gate on
    # `_cozystack_drbd_modprobe.failed`. ignore_errors preserves the
    # module's actual outcome.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Load DRBD kernel module now")
    assert task.get("ignore_errors") is True, (
        "modprobe drbd must use `ignore_errors: true` so the registered "
        "var preserves .failed for downstream gates; got ignore_errors=%r"
        % task.get("ignore_errors")
    )
    assert "failed_when" not in task, (
        "modprobe drbd must NOT use failed_when — it rewrites .failed "
        "and breaks every downstream gate that consults the registered "
        "variable. Use ignore_errors instead. Got task keys: %r"
        % list(task.keys())
    )
    params = task.get("community.general.modprobe", {}).get("params", "")
    assert "usermode_helper=disabled" in params, (
        "modprobe must pass usermode_helper=disabled — without it "
        "piraeus-operator's loader die()s on the host-loaded module. "
        "Got params=%r" % params
    )


def test_zfs_modprobe_uses_ignore_errors_not_failed_when():
    # Same bug fix applied to the pre-existing ZFS pattern: this PR
    # copied the broken shape from there, so per the project rule it
    # owns fixing both. Without this, the ZFS persistence gate at
    # `Load ZFS kernel module at boot` writes /etc/modules-load.d/
    # even when modprobe failed, which then crashes
    # systemd-modules-load.service on every boot.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Load ZFS kernel module now")
    assert task.get("ignore_errors") is True, (
        "modprobe zfs must use `ignore_errors: true`; got %r"
        % task.get("ignore_errors")
    )
    assert "failed_when" not in task, (
        "modprobe zfs must NOT use failed_when (rewrites .failed). "
        "Got task keys: %r" % list(task.keys())
    )


def test_multipathd_enable_uses_ignore_errors_not_failed_when():
    # `Enable multipathd service` registers _cozystack_multipathd and
    # the warn task downstream gates on `.failed`. failed_when: false
    # would silently always-pass that gate. Same fix as DRBD/ZFS.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Enable multipathd service")
    assert task.get("ignore_errors") is True, (
        "Enable multipathd must use ignore_errors so the warn task "
        "fires on real failure; got %r" % task.get("ignore_errors")
    )
    assert "failed_when" not in task, (
        "Enable multipathd must NOT use failed_when. Got: %r"
        % list(task.keys())
    )


def test_drbd_modules_load_drop_in_gated_on_modprobe_success():
    # Persisting drbd in /etc/modules-load.d/ when modprobe failed (no
    # MOK yet) makes systemd-modules-load.service fail every boot. The
    # write task must be gated on `_cozystack_drbd_modprobe.failed` being
    # false, mirroring the ZFS pattern.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Load DRBD kernel module at boot")
    when = task.get("when") or []
    when_blob = " ".join(when) if isinstance(when, list) else str(when)
    assert "_cozystack_drbd_modprobe" in when_blob, (
        "persistence gate must reference _cozystack_drbd_modprobe so "
        "drbd is not written to modules-load.d when modprobe failed. "
        "Got: %r" % when
    )
    assert "not (_cozystack_drbd_modprobe.failed" in when_blob, (
        "persistence gate must require modprobe success: "
        "`not (_cozystack_drbd_modprobe.failed | default(false))`. "
        "Got: %r" % when
    )


def test_drbd_modprobe_d_writes_usermode_helper_disabled():
    # piraeus-operator's loader (LINBIT/drbd docker/entry.sh) explicitly
    # die()s on a host-loaded drbd module that does not have
    # usermode_helper=disabled. Document the contract structurally so
    # future edits don't drop the param.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Configure DRBD module parameters")
    content = task.get("ansible.builtin.copy", {}).get("content", "")
    assert "usermode_helper=disabled" in content, (
        "/etc/modprobe.d/cozystack-drbd.conf must set "
        "usermode_helper=disabled; got %r" % content
    )


def test_drbd_tasks_are_ubuntu_only_and_opt_outable():
    # All DRBD install tasks must gate on Ubuntu, on the supported
    # release list (LINBIT PPA is keyed by release name — version
    # gating would let interim releases like Oracular 24.10 / Plucky
    # 25.04 reach the PPA add task and fail mid-playbook on a 404
    # Release file), and on cozystack_enable_drbd_dkms. Talos hosts
    # and any operator who deliberately runs the in-cluster compile
    # path must be able to skip the entire block from inventory.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    drbd_task_names = [
        "Add LINBIT PPA for drbd-dkms",
        "Install drbd-dkms",
        "Configure DRBD module parameters",
        "Load DRBD kernel module now",
        "Load DRBD kernel module at boot",
        "Mask host drbd.service",
    ]
    for name in drbd_task_names:
        task = _find_task(plays, name)
        when = task.get("when") or []
        when_blob = " ".join(when) if isinstance(when, list) else str(when)
        assert "cozystack_enable_drbd_dkms" in when_blob, (
            "%r must gate on cozystack_enable_drbd_dkms for opt-out; "
            "got when=%r" % (name, when)
        )
        assert "ansible_distribution == 'Ubuntu'" in when_blob, (
            "%r must gate on Ubuntu — Debian/RHEL/SUSE need different "
            "DRBD install paths; got when=%r" % (name, when)
        )
        # Gate by release name, not version number — LINBIT's PPA is
        # keyed by release name, and version-based gates miss interim
        # releases between current LTS and the next LTS (24.10 / 25.04
        # would slip through `< 26.04`).
        assert (
            "ansible_distribution_release in cozystack_drbd_supported_releases"
            in when_blob
        ), (
            "%r must gate on the bare "
            "`ansible_distribution_release in cozystack_drbd_supported_releases` "
            "(default is materialized once via set_fact at the top of "
            "the play; per-task `default()` would let drift between "
            "sites slip through). Got when=%r" % (name, when)
        )


def test_drbd_default_release_list_set_via_set_fact():
    # Single source of truth. The default release list is materialized
    # once via set_fact `Default cozystack_drbd_supported_releases when
    # unset` at the top of tasks; every gate downstream reads the bare
    # variable. Spreading `default([...])` across 11 task `when:`
    # clauses risks drift (install vs cleanup vs warn site disagreeing
    # on what the default is). This test pins the single source.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(
        plays,
        "Default cozystack_drbd_supported_releases when unset",
    )
    f = task.get("ansible.builtin.set_fact", {})
    items = f.get("cozystack_drbd_supported_releases")
    assert items == ["jammy", "noble"], (
        "Default release list must be exactly ['jammy', 'noble'] — "
        "those are the only series LINBIT's PPA currently publishes "
        "drbd-dkms for. Adding a release that is not yet in the PPA "
        "would cause apt update to fail on a 404 Release file. "
        "Got: %r" % items
    )
    when = task.get("when")
    assert when == "cozystack_drbd_supported_releases is not defined", (
        "set_fact must only fire when the variable is not already "
        "defined, so inventory overrides win. Got when=%r" % when
    )


def test_drbd_warn_on_unsupported_ubuntu_release():
    # The warn task must fire on every Ubuntu release LINBIT does
    # NOT publish for — that includes 24.10 (Oracular), 25.04
    # (Plucky), 26.04 (Resolute), and any future series until the
    # operator extends cozystack_drbd_supported_releases. Mirrors
    # the Debian warn-task pattern.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(
        plays,
        "Warn that DRBD via LINBIT PPA is unavailable on this Ubuntu release",
    )
    when = task.get("when") or []
    when_blob = " ".join(when) if isinstance(when, list) else str(when)
    assert "ansible_distribution == 'Ubuntu'" in when_blob, (
        "Ubuntu-release warn task must gate on Ubuntu; got %r" % when
    )
    assert (
        "ansible_distribution_release not in" in when_blob
        and "cozystack_drbd_supported_releases" in when_blob
    ), (
        "Ubuntu-release warn task must fire when the host's release "
        "is NOT in cozystack_drbd_supported_releases (interim + new "
        "LTS pre-publication). Got: %r" % when
    )
    assert "cozystack_enable_drbd_dkms" in when_blob, (
        "Ubuntu-release warn task must respect the opt-out toggle; "
        "got %r" % when
    )


def _task_index(plays, task_name):
    # Find the index of a task within its play.tasks list.
    for play in plays:
        tasks = play.get("tasks", []) or []
        for i, task in enumerate(tasks):
            if task.get("name") == task_name:
                return i
    raise AssertionError("task %r not found" % task_name)


def test_gnupg_is_in_required_packages():
    # ansible.builtin.apt_repository with a `ppa:` URI needs `gpg` to
    # process Launchpad's signing-key fingerprint. Ubuntu 24.04+
    # removed apt-key, so gpg (from gnupg) is the only available
    # path. Stock cloud images ship it but minimal/container images
    # may not — add it explicitly to cozystack_packages so the
    # PPA add task does not blow up with "Either apt-key or gpg
    # binary is required, but neither could be found." in the wild.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    play = plays[0]
    pkgs = play.get("vars", {}).get("cozystack_packages") or []
    assert "gnupg" in pkgs, (
        "cozystack_packages must include 'gnupg' so apt_repository's "
        "PPA flow has gpg available on minimal Ubuntu images. "
        "Got: %r" % pkgs
    )


def test_drbd_modprobe_d_written_before_apt_install():
    # The /etc/modprobe.d/cozystack-drbd.conf drop-in must exist BEFORE
    # drbd-dkms is installed. dkms postinst hooks have historically
    # changed across distro versions; if a future drbd-dkms postinst
    # auto-modprobes drbd, the module must already be configured with
    # usermode_helper=disabled or piraeus-operator's loader die()s on
    # the host-loaded module.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    modprobe_d_idx = _task_index(plays, "Configure DRBD module parameters")
    install_idx = _task_index(plays, "Install drbd-dkms")
    assert modprobe_d_idx < install_idx, (
        "Configure DRBD module parameters (idx %d) must run BEFORE "
        "Install drbd-dkms (idx %d) so any package-side modprobe "
        "respects usermode_helper=disabled"
        % (modprobe_d_idx, install_idx)
    )


def test_readme_does_not_cite_launchpadlib():
    # ansible.builtin.apt_repository does NOT use python3-launchpadlib
    # for PPA key resolution — it hits Launchpad's REST API directly
    # via fetch_url. README must not cite launchpadlib as the
    # mechanism, otherwise readers facing a non-PPA mirror will
    # install an unused dependency or chase a phantom break.
    readme_path = os.path.join(REPO_ROOT, "README.md")
    with open(readme_path, "r", encoding="utf-8") as fh:
        readme = fh.read()
    assert "python3-launchpadlib" not in readme, (
        "README must not mention python3-launchpadlib as a PPA "
        "key-resolution mechanism — apt_repository uses Launchpad's "
        "REST API directly via fetch_url. Naming launchpadlib will "
        "send readers down a dead-end install path."
    )
    assert "launchpadlib" not in readme, (
        "Same as above: 'launchpadlib' is not part of the PPA flow "
        "this collection uses."
    )


def test_no_launchpadlib_install_task():
    # ansible.builtin.apt_repository with a `ppa:` URI does NOT need
    # python3-launchpadlib — the module hits Launchpad's REST API
    # directly via fetch_url (urllib-based) since at least
    # ansible-core 2.10. Installing launchpadlib pulls a 6MB+
    # transitive dependency chain (lazr.restfulclient, oauth,
    # httplib2, keyring, ...) for no functional gain. Lock the
    # absence in so the task does not creep back in.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    for play in plays:
        for task in play.get("tasks", []) or []:
            apt = task.get("ansible.builtin.apt", {}) or {}
            name = apt.get("name")
            names = name if isinstance(name, list) else [name]
            for n in names:
                assert n != "python3-launchpadlib", (
                    "Do not install python3-launchpadlib — "
                    "ansible.builtin.apt_repository with a ppa: URI "
                    "uses Launchpad's REST API directly via fetch_url, "
                    "no launchpadlib import. The package adds a 6MB+ "
                    "transitive dependency chain for no functional "
                    "gain. Found in task %r." % task.get("name")
                )


def test_drbd_ppa_var_overridable_from_inventory():
    # cozystack_drbd_ppa must NOT be defined in play-level vars: —
    # play-level vars outrank inventory, which would silently break
    # the documented "override to point at a local mirror" use case.
    # The default belongs in the task's `| default(...)` filter so
    # inventory wins.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    for play in plays:
        play_vars = play.get("vars", {}) or {}
        assert "cozystack_drbd_ppa" not in play_vars, (
            "cozystack_drbd_ppa must not be set in play-level `vars:` — "
            "play vars outrank inventory and break the override path. "
            "Move the default to `| default(...)` in the task using it."
        )

    task = _find_task(plays, "Add LINBIT PPA for drbd-dkms")
    repo = task.get("ansible.builtin.apt_repository", {}).get("repo", "")
    assert "default(" in repo and "linbit-drbd9-stack" in repo, (
        "Add LINBIT PPA repo expression must use `| default('ppa:...')` "
        "so the value comes from inventory if set; got %r" % repo
    )


def test_drbd_warn_task_fires_only_on_modprobe_failure():
    # The warn-on-failure debug task must gate on the modprobe failure
    # so it is silent on hosts where DRBD loaded fine. Without that
    # gate, the reminder fires every run on every host and trains
    # operators to ignore it.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Warn if DRBD module failed to load")
    when = task.get("when") or []
    when_blob = " ".join(when) if isinstance(when, list) else str(when)
    assert "_cozystack_drbd_modprobe.failed" in when_blob, (
        "warn task must gate on _cozystack_drbd_modprobe.failed so it "
        "is silent on healthy hosts; got when=%r" % when
    )


def test_drbd_modprobe_d_cleanup_on_optout():
    # Symmetric cleanup with modules-load.d: when the operator opts out,
    # runs on a non-Ubuntu host, or runs on an Ubuntu release LINBIT's
    # PPA does not publish for, /etc/modprobe.d/cozystack-drbd.conf
    # should be removed too. Modprobe-failure case is intentionally
    # excluded from this cleanup (param is needed once MOK is enrolled
    # and the module loads at the next reboot).
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Remove DRBD modprobe.d drop-in when not active")
    f = task.get("ansible.builtin.file", {})
    assert f.get("state") == "absent", (
        "modprobe.d cleanup must use state=absent; got %r" % f.get("state")
    )
    assert f.get("path") == "/etc/modprobe.d/cozystack-drbd.conf", (
        "modprobe.d cleanup must remove the cozystack-drbd.conf drop-in; "
        "got %r" % f.get("path")
    )
    when = task.get("when")
    when_blob = " ".join(when) if isinstance(when, list) else str(when)
    for marker in (
        "cozystack_enable_drbd_dkms",
        "ansible_distribution",
        "cozystack_drbd_supported_releases",
    ):
        assert marker in when_blob, (
            "modprobe.d cleanup `when:` must reference %r so opt-out, "
            "non-Ubuntu, and unsupported-release cases are handled. "
            "Got: %r" % (marker, when)
        )
    # And must NOT trigger on modprobe failure (param is still wanted).
    assert "_cozystack_drbd_modprobe" not in when_blob, (
        "modprobe.d cleanup must NOT trigger on modprobe failure — the "
        "param is still needed once the module loads after MOK enrollment. "
        "Got: %r" % when
    )


def test_drbd_cleanup_removes_drop_in_when_inactive():
    # When the toggle is off, distro is not Ubuntu, the release is not
    # in the supported list, or modprobe failed, the modules-load
    # drop-in must be removed (otherwise systemd-modules-load.service
    # tries an absent module every boot). Same shape as the ZFS cleanup
    # task.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Remove DRBD modules-load drop-in when not active")
    f = task.get("ansible.builtin.file", {})
    assert f.get("state") == "absent", (
        "cleanup task must use state=absent; got %r" % f.get("state")
    )
    assert f.get("path") == "/etc/modules-load.d/cozystack-drbd.conf", (
        "cleanup must remove cozystack-drbd.conf; got %r" % f.get("path")
    )
    when = task.get("when")
    when_blob = " ".join(when) if isinstance(when, list) else str(when)
    for marker in (
        "cozystack_enable_drbd_dkms",
        "ansible_distribution",
        "cozystack_drbd_supported_releases",
        "_cozystack_drbd_modprobe",
    ):
        assert marker in when_blob, (
            "cleanup `when:` must reference %r so all four inactive "
            "cases (opt-out / non-Ubuntu / unsupported-release / "
            "modprobe-failed) are covered. Got: %r" % (marker, when)
        )


def test_drbd_debian_warning_present():
    # Debian users hit the same Secure Boot failure as Ubuntu but
    # LINBIT does not publish a Debian PPA. A warn task must fire so
    # Debian users know they need a manual flow rather than discover
    # it via piraeus-operator crash-loop.
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Warn that DRBD on Debian needs manual setup")
    when = task.get("when") or []
    when_blob = " ".join(when) if isinstance(when, list) else str(when)
    assert "ansible_distribution == 'Debian'" in when_blob, (
        "Debian-warn task must fire only on Debian; got when=%r" % when
    )
    assert "cozystack_enable_drbd_dkms" in when_blob, (
        "Debian-warn task must respect the opt-out toggle; got when=%r"
        % when
    )


def test_drbd_service_masked_after_install():
    # drbd-dkms pulls drbd-utils transitively which ships a drbd.service
    # systemd unit. Although the unit is delivered disabled, a future
    # `systemctl enable drbd` on the host would race piraeus-operator's
    # satellite container. Mask the unit explicitly under the same gates
    # as the install. (The release-list gate is asserted by
    # test_drbd_tasks_are_ubuntu_only_and_opt_outable; here we just
    # assert the systemd action is correct.)
    plays = _load_playbook("examples/ubuntu/prepare-ubuntu.yml")
    task = _find_task(plays, "Mask host drbd.service")
    s = task.get("ansible.builtin.systemd", {})
    assert s.get("name") == "drbd.service", (
        "mask task must target drbd.service; got %r" % s.get("name")
    )
    assert s.get("masked") is True, (
        "mask task must use masked: true; got %r" % s.get("masked")
    )


# Documentation drift guards


def test_readme_documents_drbd_dkms_toggle():
    # If the toggle exists in the playbook, README must mention it.
    # Catches doc drift when someone renames or removes the var.
    readme_path = os.path.join(REPO_ROOT, "README.md")
    with open(readme_path, "r", encoding="utf-8") as fh:
        readme = fh.read()
    for token in ("cozystack_enable_drbd_dkms", "cozystack_drbd_ppa"):
        assert token in readme, (
            "README.md must document the %r variable so operators "
            "know how to opt out / override it." % token
        )
    # The flat "no DRBD host packages are needed" claim is no longer
    # universally true — guard against it being silently reintroduced.
    assert "no DRBD host packages are needed" not in readme, (
        "README must not state 'no DRBD host packages are needed' as "
        "an absolute — drbd-dkms is now installed on Secure Boot hosts."
    )


def test_readme_variables_table_lists_drbd_vars():
    # The "Example playbook variables" table is the canonical reference
    # operators consult — both drbd vars must appear there, not only
    # buried inline in the prose section above.
    readme_path = os.path.join(REPO_ROOT, "README.md")
    with open(readme_path, "r", encoding="utf-8") as fh:
        readme = fh.read()
    marker = "### Example playbook variables"
    assert marker in readme, (
        "README must keep the '%s' anchor so this test can scope to it"
        % marker
    )
    section_start = readme.index(marker)
    # Section ends at the next ## or ### heading, whichever comes first.
    rest = readme[section_start + len(marker):]
    next_h2 = rest.find("\n## ")
    next_h3 = rest.find("\n### ")
    candidates = [i for i in (next_h2, next_h3) if i != -1]
    section_end = section_start + len(marker) + (
        min(candidates) if candidates else len(rest)
    )
    section = readme[section_start:section_end]
    for token in ("cozystack_enable_drbd_dkms", "cozystack_drbd_ppa"):
        assert token in section, (
            "%r must appear in the Example playbook variables table, "
            "not only inline elsewhere — operators look up overrides "
            "via the table." % token
        )


def test_readme_known_limitations_covers_26_04_drbd():
    # The README's Ubuntu 26.04 LTS bullet must mention the DRBD/Secure
    # Boot gap so operators don't read 'best-effort 26.04 supported'
    # then run into a piraeus crash-loop they can't connect to anything
    # in the docs.
    readme_path = os.path.join(REPO_ROOT, "README.md")
    with open(readme_path, "r", encoding="utf-8") as fh:
        readme = fh.read()
    # Find the Ubuntu 26.04 LTS bullet.
    anchor = "**Ubuntu 26.04 LTS:**"
    assert anchor in readme, (
        "README Known Limitations must keep the '%s' anchor" % anchor
    )
    # Slice from anchor to the next limitation bullet (line starting "- **").
    start = readme.index(anchor)
    rest = readme[start:]
    next_bullet = rest.find("\n- **", 1)
    end = start + (next_bullet if next_bullet != -1 else len(rest))
    bullet = readme[start:end]
    for token in ("drbd-dkms", "26.04", "Secure Boot"):
        assert token in bullet, (
            "Ubuntu 26.04 limitations bullet must mention %r so the "
            "PPA-not-published gap is visible to operators. Got: %r"
            % (token, bullet[:200])
        )


def test_claude_md_failed_when_guidance_updated():
    # CLAUDE.md guides future contributors and AI agents; if it still
    # says 'use failed_when: false for tolerated modprobe', the bug
    # this PR fixes will reappear. The guidance must call out that
    # failed_when: false rewrites .failed and direct readers to use
    # ignore_errors when the registered var is consulted downstream.
    claude_path = os.path.join(REPO_ROOT, "CLAUDE.md")
    if not os.path.exists(claude_path):
        return
    with open(claude_path, "r", encoding="utf-8") as fh:
        claude = fh.read()
    assert "ignore_errors" in claude, (
        "CLAUDE.md must mention ignore_errors as the right tool when "
        "the registered variable is consulted downstream"
    )
    # Either spelling of the explanation is acceptable.
    explained = (
        "rewrites" in claude
        or "ignore_errors: true" in claude
    )
    assert explained, (
        "CLAUDE.md must explain WHY failed_when: false is wrong "
        "(rewrites the registered .failed) — otherwise readers will "
        "drop ignore_errors back to failed_when in future PRs."
    )


def test_claude_md_dkms_exception_documented():
    # CLAUDE.md is the project-level guide for AI agents; if the rule
    # there contradicts what the playbook does, agents will revert
    # the change in future PRs. The exception must be spelled out.
    claude_path = os.path.join(REPO_ROOT, "CLAUDE.md")
    if not os.path.exists(claude_path):
        return  # CLAUDE.md is optional; skip silently if absent
    with open(claude_path, "r", encoding="utf-8") as fh:
        claude = fh.read()
    # Must mention the exception so the rule is no longer absolute.
    assert "cozystack_enable_drbd_dkms" in claude or (
        "drbd-dkms" in claude and "Secure Boot" in claude
    ), (
        "CLAUDE.md must document the drbd-dkms exception (Secure Boot "
        "hosts) so the 'do NOT install' rule is no longer absolute."
    )


# containerd device_ownership_from_security_context drop-in (CDI block
# imports) — cross-distro invariant on BOTH the task and the handler.


_PREPARE_PLAYBOOKS = (
    "examples/ubuntu/prepare-ubuntu.yml",
    "examples/rhel/prepare-rhel.yml",
    "examples/suse/prepare-suse.yml",
)


def _find_handler(plays, name):
    for play in plays:
        for handler in play.get("handlers", []) or []:
            if handler.get("name") == name:
                return handler
    raise AssertionError(
        "handler %r not found in %r"
        % (name, [p.get("name") for p in plays])
    )


def test_device_ownership_dropin_enabled_for_cdi_on_all_distros():
    # KubeVirt's CDI importer is a non-root pod that streams VM disk
    # images into raw block volumes; containerd only chowns the block
    # device to the pod's SecurityContext when
    # device_ownership_from_security_context is true on the CRI plugin,
    # and k3s ships it disabled. Without it the importer dies with
    # "Permission denied", the DataVolume hangs in ImportInProgress, and
    # every VM referencing the disk stays Pending. The prepare playbooks
    # drop in a CRI config that enables it. Pin the drop-in, its KubeVirt
    # gate, and the restart handler across all three distros so the
    # mechanism cannot silently regress or drift.
    for relpath in _PREPARE_PLAYBOOKS:
        plays = _load_playbook(relpath)

        drop = _find_task(
            plays,
            "Enable device_ownership_from_security_context for CDI block imports",
        )
        copy = drop.get("ansible.builtin.copy", {}) or {}
        dest = copy.get("dest", "")
        assert dest.endswith("/10-cozystack-cri.toml"), (
            "%s: drop-in must be written to a 10-cozystack-cri.toml file "
            "under the containerd config-dir glob; got dest=%r"
            % (relpath, dest)
        )
        content = copy.get("content", "")
        assert "device_ownership_from_security_context = true" in content, (
            "%s: drop-in content must set "
            "device_ownership_from_security_context = true; got %r"
            % (relpath, content)
        )
        # The containerd 2.x (config v3) CRI runtime table is the path
        # shipped by the pinned k3s. Pin it so a regression to the v2
        # io.containerd.grpc.v1.cri table (which current k3s ignores) is
        # caught.
        assert "io.containerd.cri.v1.runtime" in content, (
            "%s: drop-in must target the containerd v3 CRI runtime table "
            "io.containerd.cri.v1.runtime; got %r" % (relpath, content)
        )

        # Gated on the KubeVirt toggle — no virt, no drop-in.
        assert "cozystack_enable_kubevirt" in str(drop.get("when", "")), (
            "%s: drop-in task must gate on cozystack_enable_kubevirt so "
            "non-virt clusters skip it; got when=%r"
            % (relpath, drop.get("when"))
        )

        # Must notify the restart handler so a re-run against a running
        # cluster actually applies the change (the drop-in alone is only
        # read at containerd start otherwise).
        notify = drop.get("notify")
        notify_list = notify if isinstance(notify, list) else [notify]
        assert "Restart k3s to apply containerd config" in notify_list, (
            "%s: drop-in task must notify 'Restart k3s to apply containerd "
            "config' so the setting takes effect on a running cluster; "
            "got notify=%r" % (relpath, notify)
        )

        # The drop-in directory task shares the dest dir and the gate.
        mkdir = _find_task(
            plays, "Ensure k3s containerd config drop-in directory exists"
        )
        f = mkdir.get("ansible.builtin.file", {}) or {}
        assert f.get("state") == "directory", (
            "%s: drop-in dir task must create a directory; got state=%r"
            % (relpath, f.get("state"))
        )
        assert "cozystack_k3s_containerd_dropin_dir" in str(f.get("path", "")), (
            "%s: drop-in dir path must be overridable via "
            "cozystack_k3s_containerd_dropin_dir (for containerd 1.x); "
            "got path=%r" % (relpath, f.get("path"))
        )
        assert "cozystack_enable_kubevirt" in str(mkdir.get("when", "")), (
            "%s: drop-in dir task must share the KubeVirt gate; got when=%r"
            % (relpath, mkdir.get("when"))
        )

        # The restart handler applies the drop-in on running clusters and
        # must tolerate a missing unit: only the server OR agent unit
        # exists on a node, and on the full pipeline k3s is not installed
        # yet when prepare runs.
        handler = _find_handler(
            plays, "Restart k3s to apply containerd config"
        )
        systemd = handler.get("ansible.builtin.systemd", {}) or {}
        assert systemd.get("state") == "restarted", (
            "%s: restart handler must restart the unit; got state=%r"
            % (relpath, systemd.get("state"))
        )
        loop = handler.get("loop") or []
        assert "k3s" in loop and "k3s-agent" in loop, (
            "%s: restart handler must cover both k3s and k3s-agent units "
            "(server vs agent role); got loop=%r" % (relpath, loop)
        )
        assert handler.get("failed_when") is False, (
            "%s: restart handler must tolerate a missing unit "
            "(failed_when: false) — only one of k3s/k3s-agent exists, and "
            "on the full pipeline k3s is not installed when prepare runs; "
            "got failed_when=%r" % (relpath, handler.get("failed_when"))
        )


def test_readme_documents_dropin_rationale_and_restart():
    # Two things a maintainer/operator must learn from the README section
    # describing the drop-in, pinned against doc drift:
    #   1. k3s has a native --nonroot-devices flag that sets the same
    #      option; the section must acknowledge it and say why the drop-in
    #      is used instead (uniform server+agent coverage, applies to a
    #      running cluster) — otherwise a future maintainer rediscovers the
    #      flag and assumes the drop-in was chosen out of ignorance.
    #   2. the restart handler bounces k3s on a live re-run, which is
    #      disruptive — operators must be warned to run it in a window.
    readme_path = os.path.join(REPO_ROOT, "README.md")
    with open(readme_path, "r", encoding="utf-8") as fh:
        readme = fh.read()
    marker = "#### Enabled by default: containerd device ownership for CDI"
    assert marker in readme, (
        "README must keep the '%s...' anchor so this test can scope to it"
        % marker
    )
    start = readme.index(marker)
    rest = readme[start + len(marker):]
    nxt = rest.find("\n#### ")
    nxt_h3 = rest.find("\n### ")
    candidates = [i for i in (nxt, nxt_h3) if i != -1]
    end = start + len(marker) + (min(candidates) if candidates else len(rest))
    section = readme[start:end]

    assert "--nonroot-devices" in section, (
        "README drop-in section must mention the native k3s "
        "--nonroot-devices flag as the alternative, and why the drop-in "
        "is used instead, so the design choice is documented. Section: %r"
        % section
    )
    lowered = section.lower()
    assert "restart" in lowered and (
        "maintenance window" in lowered or "mid-day" in lowered
    ), (
        "README drop-in section must warn that a re-run against a live "
        "cluster restarts k3s and should be done in a maintenance window. "
        "Section: %r" % section
    )


def test_claude_md_documents_cdi_device_ownership_trap():
    # This change adds a fourth silent-failure trap of the same class as
    # the ones CLAUDE.md already enumerates (multipath DRBD blacklist,
    # vhost_net, br_netfilter). The canonical "Critical silent-failure
    # traps" list must include the containerd device-ownership trap so
    # the project guidance does not go stale and a future contributor
    # does not reintroduce the gap. Mirrors
    # test_claude_md_dkms_exception_documented.
    claude_path = os.path.join(REPO_ROOT, "CLAUDE.md")
    if not os.path.exists(claude_path):
        return  # CLAUDE.md is optional; skip silently if absent
    with open(claude_path, "r", encoding="utf-8") as fh:
        claude = fh.read()
    assert "device_ownership_from_security_context" in claude, (
        "CLAUDE.md must list the containerd "
        "device_ownership_from_security_context trap alongside the "
        "multipath/vhost_net/br_netfilter traps so the CDI block-import "
        "failure mode is part of the canonical silent-failure list."
    )
    # The entry must be actionable — name the symptom so a reader can
    # match it to what they observe.
    assert "ImportInProgress" in claude or "cdi-block-volume" in claude, (
        "CLAUDE.md device-ownership trap entry must name the observable "
        "symptom (CDI importer Permission denied / DataVolume "
        "ImportInProgress) so it is actionable, not just a flag name."
    )
