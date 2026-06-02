# Project conventions: cozystack/ansible-cozystack

This file captures project-specific working conventions that aren't obvious
from the code.

## Release strategy

- Collection version is **inherited from `cozystack/cozystack`** — it
  tracks the upstream Cozystack chart version (the value in
  `roles/cozystack/defaults/main.yml:cozystack_chart_version`).
- Do **NOT** bump the collection version just because a PR adds features
  or fixes bugs. The collection version moves only when upstream
  `cozystack/cozystack` releases a new chart version.
- Between upstream releases, changes accumulate on `main`. Users pin to
  git tags for stable installs; they reference `main` if they want the
  current feature set.
- Release workflow (`.github/workflows/release.yml`) triggers on
  `galaxy.yml` changes and creates a tag named `v<version>`. Never edit
  `galaxy.yml` version to force a release — the upstream Cozystack version
  is the trigger.
- Git tags are **`v`-prefixed** (`v1.2.2`), but `galaxy.yml` and
  `requirements.yml` version fields **omit the `v`** for Ansible Galaxy.
  Example requirements files that use `type: git` reference tags and must
  include the `v` prefix.

## CHANGELOG discipline

- `CHANGELOG.rst` uses per-version sections in reverse chronological order.
- For changes on `main` without a version bump, use an `Unreleased`
  section at the top. Rename it to the new version when upstream bumps
  and the release workflow fires.
- Never attribute new changes to an already-tagged version — releases are
  immutable.

## Review workflow for pull requests

Every PR must receive at least two independent review passes before
merging — one from a second LLM (run in parallel, in the background, so
it does not block the main review) and one from a branch-diff-focused
reviewer. Iterate on any blocking findings until both pass. False
positives must be explicitly justified before dismissing.

Only then enable auto-merge:

```bash
gh pr merge --auto --squash --delete-branch
```

## Planning discipline

When the user invokes plan mode (or the task is non-trivial):

- Research must be **exhaustive, not summary-level**. For anything touching
  OS packages, kernel modules, or upstream components:
  - Verify each package name against the **latest LTS** repos (Ubuntu
    22.04/24.04, RHEL 9, openSUSE Leap 15.6).
  - Follow the dependency chain: e.g., LINSTOR needs DRBD, DRBD needs
    headers, Piraeus compiles DRBD at runtime, multipathd grabs DRBD
    devices, etc.
  - Cover every Cozystack subsystem (storage, networking, virtualization,
    observability) even if the immediate issue touches only one.
- Produce per-OS tables when cross-distro work is involved.
- Cite upstream documentation URLs in research output.

Shallow "looks right" research will be rejected in plan review.

## Ansible collection conventions

- Node-side work lives in `examples/*/prepare-*.yml`, not in the role.
  The role handles only the Cozystack chart and Platform Package install.
- Kernel modules on nodes:
  - Drop a file in `/etc/modules-load.d/cozystack*.conf` for persistence.
  - `community.general.modprobe` for immediate load.
  - **`failed_when: false` rewrites the registered variable's `failed`
    field to `False`.** That breaks every downstream gate of the form
    `when: _var.failed | default(false)`. Use `failed_when: false`
    ONLY when nothing reads the registered variable (e.g., handler
    tasks, or modprobe tasks gated by a follow-up `stat` on
    `/sys/module/<name>` instead of by `.failed`). When the registered
    variable IS consulted by a downstream `when:`, use
    `ignore_errors: true` instead — it preserves the module's actual
    `failed` flag while still tolerating the failure for play
    execution.
- Kernel headers: Piraeus builds DRBD against the running kernel, not
  the staged one, so pin to the running kernel when the distro allows.
  - Ubuntu/Debian: `linux-headers-{{ ansible_kernel }}` works.
  - RHEL: `kernel-devel-{{ ansible_kernel }}` works.
  - openSUSE/SLE: zypper rejects `kernel-default-devel-{{ ansible_kernel }}`
    because SUSE package names use a different NVR format than `uname -r`.
    Use the plain `kernel-default-devel` metapackage — zypper resolves
    it to the version matching the installed kernel. Note: if a kernel
    update is staged but not yet booted, this pulls headers for the
    newer installed kernel, not the running one; the user should reboot
    before running the playbook in that case.
- External repos (OpenZFS release RPM, OBS `filesystems`):
  - Import the GPG key explicitly; **never** `disable_gpg_check: true`.
  - OBS path segments are canonical distro names (e.g.
    `openSUSE_Leap_15.6`, `SLE_15_SP6`), not bare version numbers.

## What NOT to install on hosts

KubeVirt, Kube-OVN, and Piraeus all bundle their userspace components in
their own pods. Do **not** install on the host:

- `qemu-kvm`, `libvirt*` — KubeVirt bundles these.
- `openvswitch-switch` / `openvswitch` userspace — Kube-OVN bundles OVS.
- `drbd-utils` userspace (`drbdadm`, `drbdmeta`, `drbdsetup`) — Piraeus
  ships these in the satellite container.

**Exception**: `drbd-dkms` IS installed on Ubuntu LTS hosts (22.04 /
24.04) where the in-cluster Piraeus compile path is unavailable —
UEFI Secure Boot enabled, kernel lockdown rejects the unsigned
modules built by the in-cluster compiler with `Key was rejected by
service`. See `cozystack_enable_drbd_dkms` in
`examples/ubuntu/prepare-ubuntu.yml`. `drbd-dkms` Depends on
`drbd-utils (>= 9.28.0)`, so `drbdadm`/`drbdmeta`/`drbdsetup`
land on the host as a transitive apt dependency. They are
unused — the satellite container ships its own copy. The
playbook `systemctl mask`s `drbd.service` so the host-side
userspace cannot be enabled accidentally and race the satellite.
Talos ships pre-signed DRBD modules in extensions and does not
need this.

The collection does not automate the equivalent flow on RHEL/SUSE
(LINBIT-managed RPM repo + pre-signed kmods). Operators on those
distros either build and sign drbd-dkms manually or disable Secure
Boot. LINBIT's PPA is keyed by Ubuntu release name and currently
publishes for jammy + noble; interim releases (oracular, plucky)
and the next LTS pre-publication fall back to the same manual
path. The supported list is exposed as
``cozystack_drbd_supported_releases`` so operators can extend it
from inventory once LINBIT publishes for a new series.

The host only needs the kernel modules and, for KVM, a working `/dev/kvm`.

## Critical silent-failure traps

- **Multipath DRBD blacklist**: without
  `/etc/multipath/conf.d/cozystack-drbd-blacklist.conf` blocking
  `^drbd[0-9]+`, `multipathd` grabs DRBD devices and LINSTOR volumes
  become inaccessible after reboot. Always apply.
- **`vhost_net` not loaded by default**: KubeVirt VMIs stay Pending until
  it's present.
- **`br_netfilter` missing**: `net.bridge.bridge-nf-call-*` sysctls fail
  with "No such file or directory". Load the module before applying the
  sysctl.
