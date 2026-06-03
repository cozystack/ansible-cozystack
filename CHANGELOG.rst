=================================
cozystack.installer Release Notes
=================================

Unreleased
==========

- CI: new ``hack/check-versions.sh`` invariant check runs in the ``Lint``
  job and fails the build if version strings drift across the three
  tracked dependencies: the ``cozy-installer`` chart version must match
  in ``galaxy.yml``, ``roles/cozystack/defaults/main.yml``, and the three
  ``examples/*/requirements.yml``; the ``k3s_version`` must match across
  all four inventory files; the ``k3s.orchestration`` collection version
  must match across ``tests/requirements.yml`` and the three
  ``examples/*/requirements.yml``. A companion ``hack/test-check-versions.sh``
  self-test runs alongside in the same job and asserts the drift path
  correctly exits nonzero when any single tracked file is perturbed.
- New variable ``cozystack_external_ips`` (list, default ``[]``): external
  IP addresses for ingress-nginx Service ``externalIPs``. Required on
  ``isp-full-generic`` platform variant when nodes lack a native load
  balancer (cloud VMs, bare metal).
- Prepare playbooks now set an LVM ``global_filter`` in
  ``/etc/lvm/lvm.conf`` excluding ``/dev/drbd*``, ``/dev/dm-*``,
  ``/dev/zd*`` and ``/dev/loop*`` so the host LVM does not scan or
  activate volume groups backed by LINSTOR/DRBD volumes or located
  inside loop-mounted images. Mirrors the global_filter shipped in the
  Talos machine config. The filter is overridable from inventory via
  ``cozystack_lvm_global_filter`` for hosts whose own PVs sit on
  device-mapper devices (LVM-on-LUKS, multipath). After writing it the
  playbook verifies the filter with ``lvmconfig`` and fails loudly if it
  did not take effect (for example on an ``lvm.conf`` with no ``devices``
  section), instead of leaving the host silently unfiltered.
- Prepare playbooks now enable
  ``device_ownership_from_security_context`` on the containerd CRI
  plugin (k3s drop-in
  ``config-v3.toml.d/10-cozystack-cri.toml``). KubeVirt's CDI importer
  writes disk images into raw block volumes as a non-root pod, which
  requires containerd to chown the block device to the pod's
  SecurityContext; k3s disables this by default. Without it the
  importer failed with ``blockdev: cannot open /dev/cdi-block-volume:
  Permission denied``, the ``DataVolume`` hung in ``ImportInProgress``,
  and VMs referencing the disk stayed ``Pending``. Gated behind
  ``cozystack_enable_kubevirt``; drop-in directory overridable via
  ``cozystack_k3s_containerd_dropin_dir`` (relocates the file only — the
  content is hardcoded for containerd 2.x / config version 3 as shipped
  by current k3s; a containerd 1.x cluster needs a hand-written
  ``config.toml.d`` drop-in instead).
  Setting ``cozystack_enable_kubevirt`` to ``false`` removes a
  previously written drop-in so the host state matches the toggle, and
  the restart handler only restarts a k3s unit that is actually present
  (a genuine restart failure now fails the play instead of being
  silently ignored).


v1.4.0
======

Synced with Cozystack v1.4.0.

- Bump ``cozystack_chart_version`` to ``1.4.0``.

- **Breaking**: ``cozystack_release_namespace`` default changed from
  ``kube-system`` to ``cozy-system``. Chart 1.4.0 dropped the
  ``Namespace cozy-system`` template and replaced it with a Helm
  ``pre-install,pre-upgrade`` hook (``cozy-system-labeler`` Job) that
  patches PodSecurity labels onto an existing ``cozy-system``
  namespace. The hook assumes the namespace was already created by
  the caller via ``helm install --create-namespace``; with the old
  default of ``kube-system`` the ``--create-namespace`` flag would
  no-op on the already-existing ``kube-system`` and the labeler hook
  would loop on a missing ``cozy-system`` until the helm timeout
  (5 minutes). The role now co-locates the helm release secret with
  the operator namespace and passes ``create_namespace: true`` to
  ``kubernetes.core.helm``, so ``cozy-system`` is born just-in-time
  on a fresh cluster. Upgrade path for existing installations
  pinned to 1.3.x: either uninstall and reinstall the release, or
  move the existing release secret manually with
  ``kubectl --namespace kube-system get secret --selector
  owner=helm,name=cozy-installer --output yaml | sed
  's/namespace: kube-system/namespace: cozy-system/' | kubectl apply
  --filename - && kubectl --namespace kube-system delete secret
  --selector owner=helm,name=cozy-installer``. Inventories that
  override ``cozystack_release_namespace`` to a custom value should
  align it with the namespace the chart's pre-install hook patches
  (``cozy-system``) or accept that the hook will fail until the
  custom namespace is created out of band.

Ubuntu Secure Boot: pre-install drbd-dkms from LINBIT PPA.

- ``examples/ubuntu/prepare-ubuntu.yml`` now installs ``drbd-dkms``
  from the LINBIT PPA on Ubuntu hosts and configures
  ``options drbd usermode_helper=disabled`` via
  ``/etc/modprobe.d/cozystack-drbd.conf``. On hosts where UEFI
  Secure Boot is enabled (most bare-metal installs and Secure-Boot
  cloud SKUs), kernel lockdown rejects the unsigned modules built
  by piraeus-operator's in-cluster compile path
  (``Key was rejected by service``). With drbd-dkms installed,
  dkms+shim signs the module against a per-host MOK key and
  piraeus-operator's loader auto-detects host-loaded DRBD and
  exits cleanly.
- ``drbd-dkms`` Depends on ``drbd-utils (>= 9.28.0)``, so the userspace
  is pulled onto the host as a transitive apt dependency. It is
  unused at runtime — piraeus-operator's satellite container ships
  its own copy and invokes that one. The playbook runs
  ``systemctl mask drbd.service`` on the host so the userspace
  cannot be enabled by accident and race the satellite.
- The ``/etc/modprobe.d/`` drop-in is written BEFORE drbd-dkms is
  installed so any auto-modprobe triggered by a future package
  postinst loads the module with ``usermode_helper=disabled`` —
  without that param, piraeus-operator's loader die()s on the
  host-loaded module.
- The initial ``modprobe drbd`` is tolerated (``ignore_errors: true``)
  because the dkms-generated MOK key is not enrolled until the
  operator confirms it via the shim console on the next reboot.
  Persistence in ``/etc/modules-load.d/`` is gated on a successful
  modprobe so ``systemd-modules-load.service`` does not fail every
  boot before MOK enrollment. A reminder task fires when the modprobe
  is deferred, pointing at the enrollment step.
- New opt-out variable ``cozystack_enable_drbd_dkms`` (default
  ``true``) for Talos hosts or operators who deliberately use the
  in-cluster compile path. New variable ``cozystack_drbd_ppa``
  (default ``ppa:linbit/linbit-drbd9-stack``) for sites that mirror
  the LINBIT archive internally — overridable from inventory (the
  default is in the task's ``| default(...)`` filter, not in
  play-level ``vars:`` where it would outrank inventory).
- Automated only on Ubuntu releases LINBIT keeps current — Jammy
  (22.04) and Noble (24.04) as of 2026. Interim non-LTS releases
  (Oracular 24.10, Plucky 25.04) and the next LTS before LINBIT
  publishes for it are skipped with a notice. Gating is by release
  name (``ansible_distribution_release``), not version number, because
  LINBIT's PPA is keyed by release name and version-based gates
  silently leak interim releases. The supported list is exposed as
  ``cozystack_drbd_supported_releases`` (default ``[jammy, noble]``)
  so operators can extend it from inventory once LINBIT publishes
  for a new series. Debian, RHEL, and SUSE are not automated either —
  LINBIT does not publish a Debian PPA, and the RHEL/SUSE flow needs
  a different repo plus pre-signed kmods.

Fix: tolerated-modprobe pattern previously silenced its own gates.

- The pre-existing ``Load ZFS kernel module now`` and
  ``Enable multipathd service`` tasks used ``failed_when: false`` to
  tolerate failures. Ansible's ``failed_when`` is evaluated after the
  module returns and rewrites the registered variable's ``failed``
  attribute to match — so every downstream gate of the form
  ``when: _cozystack_X.failed | default(false)`` was permanently
  False. The persistence drop-in for ZFS was written even when
  modprobe failed (which then crashed
  ``systemd-modules-load.service`` every boot), and the multipathd
  warn task never fired. Switched to ``ignore_errors: true``, which
  lets the module's outcome through to the registered variable while
  still tolerating the failure for play-execution purposes. Same fix
  applied to the new DRBD modprobe task.

Ubuntu 26.04 LTS support and namespace adoption.

- ``examples/ubuntu/`` now boots end-to-end on Ubuntu 26.04 LTS. Two
  changes were needed:

  - New playbook ``examples/ubuntu/prepare-sudo.yml`` switches the
    ``sudo`` alternative from ``sudo-rs`` (Rust rewrite, default on
    26.04) back to classical sudo at ``/usr/bin/sudo.ws``. ``sudo-rs``
    does not honour ansible's privilege-escalation pseudo-tty and
    every subsequent ``become: true`` task hangs with
    ``Timeout (12s) waiting for privilege escalation prompt``. The
    play uses ``raw`` so it runs before any become-dependent task and
    is a no-op on releases that do not ship ``sudo-rs``.
    ``examples/ubuntu/site.yml`` imports it first.
  - ``Install Ubuntu-only extra kernel modules`` now skips when
    ``cozystack_ubuntu_extra_packages`` is empty. Ubuntu 26.04 ships
    ``openvswitch`` and ``vport-geneve`` in the main
    ``linux-image-generic`` and has no ``linux-modules-extra-*`` for
    kernel 7.x. Override the variable to ``[]`` in inventory on those
    hosts; earlier releases keep the existing default.

- The role now adopts the ``cozy-system`` namespace into the
  cozy-installer helm release on first run if it already exists
  out-of-band. Without this pre-task, ``helm install`` fails with
  ``Namespace "cozy-system" exists and cannot be imported into the
  current release: invalid ownership metadata`` whenever the
  namespace was created manually, by a previous failed install, or
  by a different chart that shares the namespace name. The pre-task
  is a no-op when the namespace is absent or already carries matching
  helm metadata, and refuses to proceed (rather than silently
  hijacking) when the namespace is owned by a *different* helm
  release.

- **Breaking, but rarely set in practice**: the ``cozystack_namespace``
  variable was removed from the role's defaults. The cozy-installer
  chart hardcodes ``name: cozy-system`` in
  ``templates/cozystack-operator.yaml`` and provides no values key
  to override it; the variable was effectively a phantom that
  silently broke the role's wait/patch tasks if changed. The role
  now asserts at validation time that the variable is *unset* — any
  inventory still defining it (even at the old default
  ``cozy-system``) must remove the line. Replace any references in
  custom playbooks with the literal ``cozy-system``.

- New variable ``cozystack_tenant_root_ingress`` (bool, default ``false``):
  when enabled, patches the root Tenant CR to set ``spec.ingress: true``
  after Platform Package apply, creating the ``tenant-root`` IngressClass
  and ingress-nginx controller pods.

Node prerequisites: comprehensive audit and install in examples.

- Example prepare playbooks now install the full set of node prerequisites.
  Base additions: ``lvm2``, ``thin-provisioning-tools`` /
  ``device-mapper-persistent-data``, and kernel headers. Ubuntu and RHEL
  pin headers to the running kernel (``linux-headers-{{ ansible_kernel }}``
  / ``kernel-devel-{{ ansible_kernel }}``). openSUSE installs
  ``kernel-default-devel`` unversioned — SUSE's NVR format differs from
  ``uname -r`` so zypper rejects the version-suffixed form, but zypper
  resolves the unversioned name to the version matching the running
  kernel. On Ubuntu the playbook also installs
  ``linux-modules-extra-{{ ansible_kernel }}`` which provides
  ``openvswitch`` and ``geneve`` on cloud/minimal kernels.
  Debian 12 remains a supported target for ``prepare-ubuntu.yml`` and is
  validated end-to-end, but ZFS automation is Ubuntu-only: on Debian the
  playbook skips the ZFS block (with a visible notice), since ``zfsutils``
  lives in ``contrib`` and the kernel module requires ``zfs-dkms``. Users
  who want ZFS on Debian must enable contrib + install ``zfs-dkms``
  manually, or set ``cozystack_enable_zfs: false``.
- Kernel modules for containerd, Kubernetes bridge networking, and Kube-OVN
  loaded via ``/etc/modules-load.d/cozystack.conf``: ``overlay``,
  ``br_netfilter``, ``openvswitch``, ``geneve``, ``ip_tables``, ``iptable_nat``.
- Additional sysctl parameters: ``net.bridge.bridge-nf-call-iptables``,
  ``net.bridge.bridge-nf-call-ip6tables``, ``net.ipv6.conf.all.forwarding``.
- Critical fix: ``multipathd`` DRBD device blacklist at
  ``/etc/multipath/conf.d/cozystack-drbd-blacklist.conf``. Without it
  LINSTOR volumes become inaccessible after node reboot.
- New opt-out variable ``cozystack_enable_zfs`` (default ``true``).
  Ubuntu installs ``zfsutils-linux`` from the main repo. RHEL imports the
  OpenZFS GPG key and installs the release RPM before installing ``zfs``.
  openSUSE adds the OBS ``filesystems`` repo with a distro-detected path
  segment (Leap / Tumbleweed / SLE). Debian is not automated — contrib +
  zfs-dkms must be installed manually. Persists the ``zfs`` module via
  ``/etc/modules-load.d/``.
- New opt-out variable ``cozystack_enable_kubevirt`` (default ``true``) loads
  ``vhost_net``, ``tun``, and ``kvm_intel``/``kvm_amd`` kernel modules.
  QEMU and libvirt are bundled in KubeVirt pods; no host userspace packages
  are installed.
- README now documents every node prerequisite per subsystem with exact
  package names for Ubuntu 22.04/24.04, RHEL 9, and openSUSE Leap 15.6.
- ``prepare-rhel.yml`` now installs ``iptables-nft``. Rocky 10 / Alma 10 (and
  other RHEL 10 rebuilds) do not ship the ``iptables`` userspace binary by
  default, which made the ``cozystack_flush_iptables`` task fail on cloud
  images. ``iptables-nft`` provides an ``iptables`` wrapper over nftables
  and is also required for k3s kube-proxy replacement.
- Validation matrix extended. End-to-end tested on OCI with 3-node
  multi-master k3s + 87/87 Cozystack HelmReleases Ready: Ubuntu 22.04,
  Ubuntu 24.04, Debian 12, Rocky Linux 10. For Rocky 10 / Alma 10 (and
  other RHEL 10 rebuilds) ``cozystack_enable_zfs: false`` is currently
  required because OpenZFS has not yet published an el10 release RPM;
  ``prepare-rhel.yml`` fails fast with a clear message until an entry is
  added to ``cozystack_zfs_release_rpm_by_major``.

v1.2.3
======

- Drop ``ansible.utils`` collection dependency and ``netaddr`` Python
  package requirement. Master node IP validation now uses a bundled
  ``cozystack.installer.is_ip_address`` Jinja2 test backed by the
  Python standard library ``ipaddress`` module.
- Add IPv6 inventory fixture and CI coverage for IPv6 host keys.

v1.2.2
======

Synced with Cozystack v1.2.2.

- Bump ``cozystack_chart_version`` to ``1.2.2``

v1.2.1
======

Synced with Cozystack v1.2.1.

- Bump ``cozystack_chart_version`` to ``1.2.1``
- Derive ``MASTER_NODES`` for kube-ovn from the ``server`` inventory
  group; add ``cozystack_master_nodes`` override for multi-master setups
- Validate master node entries are valid IP addresses, not hostnames

v1.1.3
======

Synced with Cozystack v1.1.3.

- Bump ``cozystack_chart_version`` to ``1.1.3``

v1.1.2
======

Synced with Cozystack v1.1.2.

- Bump ``cozystack_chart_version`` to ``1.1.2``

v1.0.2
======

Synced with Cozystack v1.0.2.

- Bump ``cozystack_chart_version`` to ``1.0.2``
- Bump ``cozystack_helm_version`` to ``3.20.0``

v1.0.0-rc.1
============

First release as a standalone collection. Synced with Cozystack v1.0.0-rc.1.

Breaking changes from pre-release development:

- Switched from custom chart (``lexfrei/cozystack-installer``) to official
  Cozystack installer chart (``ghcr.io/cozystack/cozystack/cozy-installer``)
- Two-stage install: Helm chart deploys operator, Platform Package CR
  is applied separately via ``kubectl apply``
- Role ``prepare`` removed from collection — moved to per-distro examples
  (``examples/ubuntu/``, ``examples/rhel/``, ``examples/suse/``)
- ``k3s.orchestration`` removed from dependencies — users compose their own pipeline
- New variables: ``cozystack_operator_variant``, ``cozystack_platform_variant``,
  ``cozystack_create_platform_package``, ``cozystack_pod_cidr``, etc.
- ``cozystack_root_host`` is no longer required for chart install
  (used in Platform Package CR)
