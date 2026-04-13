============================
cozystack.installer Release Notes
============================

Unreleased
==========

Node prerequisites: comprehensive audit and install in examples.

- Example prepare playbooks now install the full set of node prerequisites.
  Base additions: ``lvm2``, ``thin-provisioning-tools`` /
  ``device-mapper-persistent-data``, and kernel headers pinned to the
  running kernel (``linux-headers-{{ ansible_kernel }}`` on Ubuntu,
  ``kernel-devel-{{ ansible_kernel }}`` on RHEL,
  ``kernel-default-devel-{{ ansible_kernel }}`` on openSUSE). On Ubuntu
  the playbook also installs ``linux-modules-extra-{{ ansible_kernel }}``
  which provides ``openvswitch`` and ``geneve`` on cloud/minimal kernels.
  ``prepare-ubuntu.yml`` is now Ubuntu-only — Debian requires contrib +
  ``zfs-dkms`` for ZFS and is no longer claimed as a supported target
  for this example.
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
  Ubuntu 24.04, Debian 12, Rocky Linux 10.

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
