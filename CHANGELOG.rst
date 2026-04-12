============================
cozystack.installer Release Notes
============================

v1.3.0
======

Node prerequisites: comprehensive audit and install in examples.

- Example prepare playbooks now install the full set of node prerequisites.
  Base additions: ``lvm2``, ``thin-provisioning-tools`` /
  ``device-mapper-persistent-data``, and kernel headers
  (``linux-headers-generic`` / ``kernel-devel`` / ``kernel-default-devel``).
- Kernel modules for containerd, Kubernetes bridge networking, and Kube-OVN
  loaded via ``/etc/modules-load.d/cozystack.conf``: ``overlay``,
  ``br_netfilter``, ``openvswitch``, ``geneve``, ``ip_tables``, ``iptable_nat``.
- Additional sysctl parameters: ``net.bridge.bridge-nf-call-iptables``,
  ``net.bridge.bridge-nf-call-ip6tables``, ``net.ipv6.conf.all.forwarding``.
- Critical fix: ``multipathd`` DRBD device blacklist at
  ``/etc/multipath/conf.d/cozystack-drbd-blacklist.conf``. Without it
  LINSTOR volumes become inaccessible after node reboot.
- New opt-out variable ``cozystack_enable_zfs`` (default ``true``) installs
  ``zfsutils-linux`` on Ubuntu. RHEL prepare playbook auto-adds the OpenZFS
  release RPM; openSUSE prepare playbook auto-adds the OBS ``filesystems``
  repo.
- New opt-out variable ``cozystack_enable_kubevirt`` (default ``true``) loads
  ``vhost_net``, ``tun``, and ``kvm_intel``/``kvm_amd`` kernel modules.
  QEMU and libvirt are bundled in KubeVirt pods; no host userspace packages
  are installed.
- README now documents every node prerequisite per subsystem with exact
  package names for Ubuntu 22.04/24.04, RHEL 9, and openSUSE Leap 15.6.

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
