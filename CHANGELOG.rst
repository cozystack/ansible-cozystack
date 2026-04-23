=================================
cozystack.installer Release Notes
=================================


Unreleased
==========

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

- CI: new ``hack/check-versions.sh`` invariant check runs in the ``Lint``
  job and fails the build if version strings drift across the three
  tracked dependencies: the ``cozy-installer`` chart version must match
  in ``galaxy.yml``, ``roles/cozystack/defaults/main.yml``, and the three
  ``examples/*/requirements.yml``; the ``k3s_version`` must match across
  all four inventory files; the ``k3s.orchestration`` collection version
  must match across ``tests/requirements.yml`` and the three
  ``examples/*/requirements.yml``.
- New variable ``cozystack_external_ips`` (list, default ``[]``): external
  IP addresses for ingress-nginx Service ``externalIPs``. Required on
  ``isp-full-generic`` platform variant when nodes lack a native load
  balancer (cloud VMs, bare metal).
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
