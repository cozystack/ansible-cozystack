# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Cozystack Contributors
# Apache License 2.0 (see LICENSE file in the repository root)

# Structural tests for the nvidia_vgpu_host role. The invariants pinned
# here are the ones whose violation is silent on the hardware where it
# matters: a default that turns the role on, a boot unit that acts on a
# card it was not pointed at, a GPU reset re-entering the script, and
# the stage order that keeps a mode change from tearing down virtual
# functions.

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import re

import yaml


REPO_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

ROLE = "roles/nvidia_vgpu_host"
DEFAULTS = ROLE + "/defaults/main.yml"
TASKS = ROLE + "/tasks/main.yml"
SCRIPT = ROLE + "/templates/cozystack-nvidia-vgpu-restore.sh.j2"
UNIT = ROLE + "/templates/cozystack-nvidia-vgpu-restore.service.j2"

TOGGLE = "cozystack_enable_nvidia_vgpu_host"
DEVICES = "cozystack_nvidia_vgpu_devices"

README_HEADING = "#### Opt-in: NVIDIA vGPU host state across reboots"

PREPARE_PLAYBOOKS = (
    "examples/ubuntu/prepare-ubuntu.yml",
    "examples/rhel/prepare-rhel.yml",
    "examples/suse/prepare-suse.yml",
)


def _read(relpath):
    with open(os.path.join(REPO_ROOT, relpath), "r", encoding="utf-8") as fh:
        return fh.read()


def _load_yaml(relpath):
    return yaml.safe_load(_read(relpath))


def _unit_directive(name):
    # The unit template still carries Jinja, so it is not ini-parseable;
    # read directive values as text.
    values = []
    for line in _read(UNIT).splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            values.append(line[len(name) + 1:])
    return values


# ---- opt-in defaults ----


def test_role_is_disabled_by_default():
    defaults = _load_yaml(DEFAULTS)
    assert defaults[TOGGLE] is False, (
        "%s must default to false. The role installs a boot unit that "
        "changes GPU hardware state; it may only run where an operator "
        "asked for it." % TOGGLE
    )


def test_device_list_is_empty_by_default():
    defaults = _load_yaml(DEFAULTS)
    assert defaults[DEVICES] == [], (
        "%s must default to an empty list. Every action this role takes "
        "is addressed to a GPU named in that list, so an empty list is "
        "what keeps the unit inert even once the role is enabled."
        % DEVICES
    )


def _when_text(entry):
    when = entry.get("when")
    assert when is not None, "every top-level entry must carry a when clause"
    return when if isinstance(when, str) else " ".join(when)


def test_tasks_are_gated_by_blocks_on_both_paths():
    tasks = _load_yaml(TASKS)
    assert len(tasks) == 2, (
        "tasks/main.yml must hold exactly two top-level entries, each "
        "wrapping its tasks in one gated block: the enabled path and the "
        "path that undoes it. A per-task gate can be forgotten on the "
        "next task added; a block gate cannot. Found %d entries."
        % len(tasks)
    )
    gates = []
    for entry in tasks:
        assert "block" in entry, "each top-level entry must be a block"
        when_text = _when_text(entry)
        assert TOGGLE in when_text, (
            "each block's when must reference %s" % TOGGLE
        )
        assert "default(false)" in when_text, (
            "each block's when must read the toggle through "
            "default(false) so an inventory that never sets it leaves the "
            "role off"
        )
        gates.append(when_text)
    negated = [gate for gate in gates if "not " in gate]
    assert len(negated) == 1, (
        "exactly one of the two blocks must gate on the toggle being "
        "false. Got gates %r" % gates
    )


def test_disabling_the_role_undoes_a_previous_run():
    # Without this, a host enabled once keeps the unit enabled and keeps
    # changing GPU state at every boot from whatever device list was
    # current then, so the host stops matching the toggle.
    tasks = _load_yaml(TASKS)
    disabled = [entry for entry in tasks if "not " in _when_text(entry)]
    body = yaml.safe_dump(disabled[0]["block"])
    assert "enabled: false" in body, (
        "the disabled path must disable the unit so it does not run at "
        "the next boot"
    )
    assert "state: absent" in body, (
        "the disabled path must remove the unit file and the script"
    )
    assert "/etc/systemd/system/cozystack-nvidia-vgpu-restore.service" in body
    assert "/usr/local/sbin/cozystack-nvidia-vgpu-restore" in body


def test_role_installs_the_unit_without_starting_it():
    # Enabling MIG mode or creating virtual functions on a live host is a
    # maintenance-window action. The role enables the unit for the next
    # boot and leaves starting it to the operator.
    text = _read(TASKS)
    for forbidden in ("state: started", "state: restarted"):
        assert forbidden not in text, (
            "tasks must not %r the boot unit: applying the role would "
            "then change GPU state immediately, outside any maintenance "
            "window. Enable it and let the next boot apply it."
            % forbidden
        )
    assert "enabled: true" in text, (
        "the unit must be enabled so it runs on the next boot"
    )
    handlers = _read(ROLE + "/handlers/main.yml")
    assert "daemon_reload: true" in handlers, (
        "dropping a unit file requires a daemon-reload to take effect. It "
        "belongs in a handler rather than a task so an unchanged re-run "
        "reports no change."
    )


def _address_patterns():
    # Pulls the real patterns out of the role's assert so this tests the
    # validation rather than the presence of a task that mentions it.
    for entry in _load_yaml(TASKS):
        for task in entry.get("block", []):
            spec = task.get("ansible.builtin.assert")
            if not spec:
                continue
            for clause in spec.get("that") or []:
                if "item.address is match" in clause:
                    return re.findall(r"match\('([^']+)'\)", clause)
    raise AssertionError(
        "no assert in tasks/main.yml validates item.address"
    )


def test_role_validates_device_identifiers():
    patterns = _address_patterns()
    assert patterns, "the address assert must carry at least one pattern"

    def accepted(value):
        # Ansible's `match` test anchors at the start via re.match.
        return any(re.match(p, value) for p in patterns)

    for value in (
        "0000:41:00.0",
        "00000000:41:00.0",
        "41:00.0",
        "GPU-12345678-1234-1234-1234-123456789abc",
    ):
        assert accepted(value), (
            "%r is a valid GPU identifier and must be accepted" % value
        )
    for value in (
        "0",
        "1",
        "gpu0",
        "0000:41:00.8",
        "0000:41:00",
        "0000:41:0.0",
        "GPU-123",
        "",
    ):
        assert not accepted(value), (
            "%r must be rejected. A bare index in particular: indices "
            "shift on PCI, BIOS and kernel re-enumeration, so accepting "
            "one lets a config that named the right card name a "
            "different one after a firmware update." % value
        )


def _duplicate_check_names():
    names = []
    for entry in _load_yaml(TASKS):
        for task in entry.get("block", []):
            spec = task.get("ansible.builtin.assert")
            if not spec:
                continue
            for clause in spec.get("that") or []:
                if "unique" in clause:
                    names.append(task.get("name", ""))
    return names


def test_role_rejects_both_kinds_of_duplicate():
    # Asserting that "unique" appears somewhere passed with either check
    # deleted, because both use it. Name them individually so removing
    # one is a failure.
    names = " | ".join(_duplicate_check_names())
    assert "virtual-function" in names, (
        "a check must reject a virtual function named more than once "
        "across the vgpu_profiles maps. Found: %s" % names
    )
    assert "device addresses" in names, (
        "a check must reject a card named more than once. Found: %s"
        % names
    )


def test_pci_normalisation_is_defined_once():
    # The two duplicate checks previously carried their own regexes and
    # disagreed about the PCI domain: one canonicalised it, the other
    # deleted it, so a valid multi-segment configuration was refused
    # while two cards on different segments aliased onto one key. Both
    # now reference the shared definition, and a new site that hardcodes
    # a pattern instead fails here.
    #
    # Scoped to every YAML in the role, not to tasks/main.yml: splitting
    # validation into a second file is ordinary growth, and a guard that
    # only reads one file would pass while the claim it carries stopped
    # being true.
    role_dir = os.path.join(REPO_ROOT, ROLE)
    offenders = []
    for root, _dirs, files in os.walk(role_dir):
        for name in files:
            if not name.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(root, name)
            if os.path.relpath(path, role_dir) == os.path.join("vars", "main.yml"):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for line in text.splitlines():
                if "regex_replace" not in line:
                    continue
                if "_cozystack_vgpu_bdf_" in line:
                    continue
                offenders.append("%s: %s" % (name, line.strip()))
            if re.search(r"\[0-9a-f(?:A-F)?\]\{2\}:\[0-9a-f(?:A-F)?\]\{2\}",
                         text, re.IGNORECASE):
                if "match(" not in text:
                    offenders.append("%s: hardcoded PCI pattern" % name)
    assert not offenders, (
        "PCI address normalisation must come from vars/main.yml so every "
        "comparison uses one rule. These sites define their own: %s"
        % offenders
    )


def test_shared_normalisation_keeps_the_domain():
    # The rule itself, not just its single definition. Deleting the
    # domain aliases two cards on different PCI segments onto one key,
    # which is how the role came to act on hardware nobody declared.
    shared = _load_yaml(ROLE + "/vars/main.yml")
    substitution = shared["_cozystack_vgpu_bdf_domain_sub"]
    assert "1" in substitution and "2" in substitution, (
        "the domain substitution must carry both capture groups, so the "
        "domain survives canonicalisation. Got %r" % substitution
    )


# ---- the boot unit ----


def test_unit_skips_when_no_host_installed_driver_is_present():
    conditions = _unit_directive("ConditionPathExists")
    assert conditions, (
        "the unit must carry ConditionPathExists on the host driver's "
        "sriov-manage. That path is absent both on a host with no NVIDIA "
        "driver and on one where gpu-operator manages the vGPU Manager "
        "(its driver root lives elsewhere), so the condition is what "
        "makes the unit a no-op there, reported as skipped, not failed."
    )
    assert any("sriov" in value for value in conditions), (
        "the ConditionPathExists must point at sriov-manage, found %r"
        % conditions
    )


def test_unit_runs_after_the_vgpu_manager():
    after = " ".join(_unit_directive("After"))
    for daemon in ("nvidia-vgpud.service", "nvidia-vgpu-mgr.service"):
        assert daemon in after, (
            "the unit must be ordered After=%s. sriov-manage is "
            "documented to fail while the Virtual GPU Manager is still "
            "initialising, so ordering before those daemons guarantees "
            "that failure on the hardware where it is documented." % daemon
        )
    before = " ".join(_unit_directive("Before"))
    for daemon in ("nvidia-vgpud", "nvidia-vgpu-mgr"):
        assert daemon not in before, (
            "the unit must not be ordered Before=%s: on an NVLink system "
            "that orders the script ahead of the daemon it depends on"
            % daemon
        )


def test_script_retries_the_virtual_function_call():
    # Naming the constant is not enough: it is also declared at the top
    # of the file and used by the profile-stage wait, so an assertion on
    # the name alone passes with the retry loop collapsed to one attempt.
    text = _read(SCRIPT)
    body = text[text.find("ensure_vfs() {"):text.find("# ---- STAGE 3")]
    assert 'for attempt in $(seq 1 "$SRIOV_RETRIES")' in body, (
        "the virtual-function call must sit inside a retry loop. The "
        "vendor documents it failing while the Virtual GPU Manager is "
        "still initialising, and the retry is what closes that race."
    )
    assert "SRIOV_RETRIES" in text, (
        "enabling virtual functions must be retried, not attempted once. "
        "The vendor documents the call failing while the Virtual GPU "
        "Manager initialises, and NVIDIA's own driver container retries "
        "it for that reason; the retry is what closes the boot race that "
        "unit ordering alone cannot."
    )


def test_unit_is_a_oneshot_that_does_not_block_boot():
    text = _read(UNIT)
    assert "Type=oneshot" in text
    assert "multi-user.target" in " ".join(_unit_directive("WantedBy"))
    assert "Requires=" not in text, (
        "no Requires= on this unit: a failure must degrade GPU VMs, not "
        "take a target down with it"
    )


# ---- the restore script ----


def test_script_never_resets_a_gpu():
    # Two checks with opposite blind spots, kept together because neither
    # is the property. The substring scan reads the whole file, so it
    # survives a line continuation, an invocation through a variable, and
    # a direct sysfs write, all of which a same-line match loses. The
    # same-line flag match catches `-r`, nvidia-smi's short form of
    # `--gpu-reset`, which no substring in the first list contains.
    # Replacing one with the other traded three kills for one; the
    # behavioural check in tests/test-nvidia-vgpu-host-stages.yml covers
    # what both miss, on the paths the suite actually drives.
    text = _read(SCRIPT)
    for forbidden in ("--gpu-reset", "gpu_reset", "-r ALL"):
        assert forbidden not in text, (
            "the script must never reset a GPU (%r found). A reset "
            "destroys every consumer of the card, which on a vGPU host "
            "is the tenants' running VMs." % forbidden
        )
    offenders = [
        line.strip()
        for line in _read(SCRIPT).splitlines()
        if "nvidia-smi" in line
        and re.search(r"(?:^|\s)(?:-r|--gpu-reset)(?:\s|$)", line)
    ]
    assert not offenders, (
        "the script must never reset a GPU. MIG mode is persistent on "
        "Ampere, where setting it would need a reset, and needs no reset "
        "on Hopper and later, where it is not persistent, so boot-time "
        "restoration never requires one. A reset destroys every consumer "
        "of the card, which on a vGPU host is the tenants' running VMs. "
        "Offending lines: %r" % offenders
    )


def test_script_stages_mig_mode_before_virtual_functions():
    # Pins the order of the generated calls, not of the comments that
    # label them: the comments could stay put while the calls moved.
    text = _read(SCRIPT)
    mig = text.find("\nensure_mig_mode {{")
    sriov = text.find("\nensure_vfs {{")
    profiles = text.find("\nensure_vf_profiles {{")
    assert -1 not in (mig, sriov, profiles), (
        "the script must emit one call per declared GPU for each stage, "
        "found offsets mig=%d sriov=%d profiles=%d" % (mig, sriov, profiles)
    )
    assert mig < sriov < profiles, (
        "call order must be MIG mode, then virtual functions, then "
        "per-VF profiles. MIG mode is a whole-GPU property and settles "
        "before the GPU is subdivided, and a profile cannot be written "
        "to a function that does not exist yet."
    )


def test_script_addresses_virtual_functions_per_device_never_all():
    # Independent of how the command is spelled: it is invoked through a
    # variable, so a check anchored on the binary's name would not see
    # the argument change.
    text = _read(SCRIPT)
    assert not re.search(r"-e[ \t]+ALL", text), (
        "the script must never pass -e ALL. Every action is addressed to "
        "a GPU the operator named; ALL would act on cards that were "
        "never declared, which is the failure mode that sank the "
        "auto-detecting approach."
    )
    assert not re.search(r"-d[ \t]+ALL", text), (
        "the script must never pass -d ALL either: tearing down every "
        "card's virtual functions is not something it is asked to do."
    )


def test_script_exits_before_touching_hardware_when_nothing_is_declared():
    # The driver wait is a hard failure, so an inert configuration must
    # never reach it. Rendering order is what guarantees that.
    text = _read(SCRIPT)
    no_work = text.find("no GPUs declared")
    preconditions = text.find("# ---- preconditions ----")
    assert no_work != -1, (
        "the script must log that nothing was declared"
    )
    assert preconditions != -1, "the preconditions section must be marked"
    assert no_work < preconditions, (
        "the no-work exit must be rendered before the preconditions. "
        "Otherwise a host with the role enabled but no GPUs declared "
        "waits for a driver it was never asked to touch and then fails."
    )


def test_script_logs_the_raw_virtualization_mode_it_declined():
    text = _read(SCRIPT)
    assert "unrecognised" in text or "unrecognized" in text, (
        "the script must have an explicit branch for a virtualization "
        "mode string it does not recognise"
    )
    assert re.search(r"(observed|raw)[^\n]*mode", text, re.IGNORECASE), (
        "when the script declines because it did not recognise the "
        "driver's reported mode, it must log the observed string "
        "verbatim. Skipping silently on an unanticipated spelling looks "
        "exactly like working correctly."
    )


def test_script_documents_why_the_driver_wait_is_the_only_hard_failure():
    text = _read(SCRIPT)
    assert re.search(
        r"#[^\n]*(only|unlike)[^\n]*(exit|fail)", text, re.IGNORECASE
    ), (
        "the non-zero exit on the driver wait needs a comment saying why "
        "it is the one precondition that fails loudly while every other "
        "exits zero. That reasoning is a constraint the code cannot show."
    )


def test_script_documents_that_the_numvfs_read_is_not_capability_inference():
    text = _read(SCRIPT)
    marker = text.find("sriov_numvfs")
    assert marker != -1, (
        "the already-satisfied check reads sriov_numvfs from sysfs; "
        "sriov-manage has no query form, so there is no alternative"
    )
    window = text[max(0, marker - 1200):marker]
    assert re.search(
        r"#[^\n]*(not|never)[^\n]*(infer|capab)", window, re.IGNORECASE
    ), (
        "the sriov_numvfs read must carry a comment stating that it only "
        "suppresses a redundant write and never concludes that virtual "
        "functions are missing and must be created. Deriving 'VFs are "
        "missing' from sysfs counts misreads hardware that advertises "
        "virtual functions but never creates them, and a reader who does "
        "not know that will re-introduce it."
    )


# ---- wiring into the example playbooks ----


def test_examples_include_the_role_unconditionally():
    # The role gates both of its own paths on the toggle. Gating the
    # include as well would make the teardown unreachable through the
    # documented entry point, so a host enabled once would keep
    # restoring GPU state at every boot no matter how the toggle was
    # set afterwards.
    for relpath in PREPARE_PLAYBOOKS:
        plays = _load_yaml(relpath)
        includes = [
            task
            for play in plays
            for task in (play.get("tasks") or [])
            if "ansible.builtin.include_role" in task
            and task["ansible.builtin.include_role"].get("name")
            == "cozystack.installer.nvidia_vgpu_host"
        ]
        assert len(includes) == 1, (
            "%s must include the role exactly once by its "
            "collection-qualified name, found %d"
            % (relpath, len(includes))
        )
        assert "when" not in includes[0], (
            "%s must not gate the include: the role decides for itself, "
            "and a gate here makes turning the toggle back off a no-op"
            % relpath
        )


def test_default_driver_paths_are_the_real_ones():
    # The test playbooks point these at a temporary tree so they never
    # write to a real driver install, which means nothing else would
    # notice if the shipped defaults drifted.
    defaults = _load_yaml(DEFAULTS)
    assert defaults["cozystack_nvidia_vgpu_sriov_manage"] == (
        "/usr/lib/nvidia/sriov-manage"
    )
    assert defaults["cozystack_nvidia_vgpu_operator_driver_root"] == (
        "/run/nvidia/driver"
    )
    assert defaults["cozystack_nvidia_vgpu_pci_root"] == (
        "/sys/bus/pci/devices"
    )


# ---- documentation drift guards ----


def test_readme_documents_the_role_and_the_profile_precedence():
    text = _read("README.md")
    assert "nvidia_vgpu_host" in text, "README must document the new role"
    assert DEVICES in text, (
        "README must document %s, the variable that names which GPUs the "
        "unit may touch" % DEVICES
    )
    assert "vgpu_profiles" in text and "vgpu_profile" in text, (
        "README must document both the per-VF map and the per-PF "
        "shorthand for vGPU profile assignment"
    )
    assert re.search(
        r"vgpu_profiles[^.\n]*(win|precede|override)", text, re.IGNORECASE
    ), (
        "README must state which form wins when a VF is covered by both "
        "the per-PF shorthand and the per-VF map"
    )


def _readme_section(heading):
    text = _read("README.md")
    start = text.find(heading)
    assert start != -1, "README is missing the heading %r" % heading
    rest = text[start + len(heading):]
    end = rest.find("\n#")
    return rest if end == -1 else rest[:end]


def test_readme_names_a_daemonset_as_the_operator_managed_answer():
    # Scoped to the role's own section: "DaemonSet" appears elsewhere in
    # this README, so an unscoped search would pass without the sentence
    # that matters ever being written.
    section = _readme_section(README_HEADING)
    assert "DaemonSet" in section, (
        "the role's README section must say that a DaemonSet remains the "
        "right mechanism for operator-managed clusters. This role covers "
        "the host-installed, ansible-managed path only and must not be "
        "presented as the general answer to per-VF profile assignment."
    )


def test_changelog_documents_the_role():
    sections = _read("CHANGELOG.rst").split("Unreleased", 1)
    assert len(sections) == 2, "CHANGELOG must carry an Unreleased section"
    assert "nvidia_vgpu_host" in sections[1], (
        "the Unreleased section must document the new role"
    )
