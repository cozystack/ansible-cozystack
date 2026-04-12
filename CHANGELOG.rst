============================
cozystack.installer Release Notes
============================

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
