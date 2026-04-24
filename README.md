# Ansible Collection: cozystack.installer

Install [Cozystack](https://cozystack.io) on generic Kubernetes clusters (k3s, kubeadm, RKE2).

Supported targets:

| Example playbook | Distributions | Validated end-to-end |
| --- | --- | --- |
| `examples/ubuntu/` | Ubuntu 22.04, Ubuntu 24.04, Debian 12 | Ubuntu 22.04, Ubuntu 24.04, Debian 12 on OCI: 3-node multi-master, 87/87 HelmReleases Ready |
| `examples/rhel/` | RHEL 8+, CentOS Stream 8+, Rocky 9/10, Alma 9/10 | Rocky 10 on OCI: 3-node multi-master, 87/87 HelmReleases Ready (`cozystack_enable_zfs: false` required — see Known limitations) |
| `examples/suse/` | openSUSE Leap 15.6+, openSUSE Tumbleweed, SLES 15 | — |

Cloud-image users **must** set `cozystack_flush_iptables: true` for multi-master k3s to bootstrap — Ubuntu cloud images ship with `REJECT icmp-host-prohibited` in INPUT that blocks etcd peer port 2380 between nodes. See **Node Prerequisites → Known limitations** below.

Deploys the Cozystack operator and Platform Package using the
`kubernetes.core.helm` module with automatic Helm and helm-diff
installation.

## Prerequisites

### Controller (where you run Ansible)

- Python >= 3.9
- Ansible >= 2.15
- Required collections (install via `requirements.yml` in the repository root):

```bash
ansible-galaxy collection install --requirements-file requirements.yml
```

- SSH access to the target nodes

The role automatically installs Helm and the
[helm-diff](https://github.com/databus23/helm-diff) plugin
on the control-plane node. No manual Helm installation is needed.

### Node Prerequisites

> **Important:** Cozystack components have several non-obvious node requirements that must be configured on ALL cluster nodes. The example prepare playbooks install everything, load required kernel modules, and apply a critical multipath blacklist. Running Cozystack on hand-prepared nodes without these will cause silent failures: LINSTOR volumes inaccessible after reboot, VMs stuck in Pending, OVN tunnels not coming up.

Use the per-distro example playbooks as the authoritative list of what to set up:

- `examples/ubuntu/prepare-ubuntu.yml` (Ubuntu 22.04+, Debian 12)
- `examples/rhel/prepare-rhel.yml` (RHEL 8+/CentOS Stream 8+/Rocky/Alma)
- `examples/suse/prepare-suse.yml` (openSUSE/SLE)

The sections below document each subsystem's requirement so you understand why the prepare playbook installs what it installs. Package names are verified against the current LTS repos (Ubuntu 22.04/24.04, RHEL 9, openSUSE Leap 15.6).

#### Required: Base storage I/O

| Purpose | Ubuntu/Debian | RHEL/CentOS | openSUSE/SLE |
| --- | --- | --- | --- |
| NFS client | `nfs-common` | `nfs-utils` | `nfs-client` |
| iSCSI initiator | `open-iscsi` | `iscsi-initiator-utils` | `open-iscsi` |
| Multipath I/O | `multipath-tools` | `device-mapper-multipath` | `multipath-tools` |

The `iscsid` and `multipathd` services must be enabled and running.

#### Required: LINSTOR LVM/thin provisioning

LINSTOR uses LVM thin pools by default for local block storage.

| Purpose | Ubuntu/Debian | RHEL/CentOS | openSUSE/SLE |
| --- | --- | --- | --- |
| LVM2 | `lvm2` | `lvm2` | `lvm2` |
| Thin provisioning | `thin-provisioning-tools` | `device-mapper-persistent-data` | `thin-provisioning-tools` |

#### Required: Kernel headers (Piraeus DRBD loader)

LINSTOR uses DRBD 9.x for replication. The Piraeus operator's init container compiles the DRBD kernel module from source **against the running kernel** at runtime, so only kernel headers must be installed on the host — **no DRBD host packages are needed**. Pin the headers package to `ansible_kernel` so a staged-but-not-yet-booted kernel update doesn't install headers for the wrong kernel.

| Ubuntu/Debian | RHEL/CentOS | openSUSE/SLE |
| --- | --- | --- |
| `linux-headers-{{ ansible_kernel }}` | `kernel-devel-{{ ansible_kernel }}` plus `kernel-modules-extra-{{ ansible_kernel }}` | `kernel-default-devel` (zypper resolves to running kernel — SUSE's NVR format differs from `uname -r`) |

On Oracle Linux the playbook auto-detects the UEK kernel (`uek` substring in `ansible_kernel`) and installs `kernel-uek-devel-{{ ansible_kernel }}` / `kernel-uek-modules-extra-{{ ansible_kernel }}` instead. Oracle Linux is not on the validated-end-to-end list; this code path is retained best-effort for users who still run the example playbook there. ZFS automation skips on UEK kernels because OpenZFS does not publish kmod builds for UEK.

#### Required: Multipath DRBD blacklist

> **Silent failure if omitted.** `multipathd` defaults to grabbing any device matching common patterns including DRBD's `drbd*`. Once that happens LINSTOR cannot access its own volumes and volumes become unreadable after the next reboot.

The prepare playbooks drop this file into place:

```text
# /etc/multipath/conf.d/cozystack-drbd-blacklist.conf
blacklist {
    devnode "^drbd[0-9]+"
}
```

#### Required: Containerd + Kubernetes kernel modules

Required for containerd's overlay storage driver and standard Kubernetes bridge networking. Loaded via `/etc/modules-load.d/cozystack.conf`:

```text
overlay
br_netfilter
```

Plus the following sysctls:

| Parameter | Value | Why |
| --- | --- | --- |
| `fs.inotify.max_user_watches` | `524288` | Kubernetes watch events |
| `fs.inotify.max_user_instances` | `8192` | Multiple inotify watchers |
| `fs.inotify.max_queued_events` | `65536` | Event queue depth |
| `fs.file-max` | `2097152` | Open file descriptors limit |
| `fs.aio-max-nr` | `1048576` | Async I/O operations (databases) |
| `vm.swappiness` | `1` | Minimize swap usage |
| `net.ipv4.ip_forward` | `1` | Pod-to-pod routing |
| `net.ipv4.conf.all.forwarding` | `1` | Global IP forwarding |
| `net.ipv6.conf.all.forwarding` | `1` | Required for Kube-OVN dual-stack |
| `net.bridge.bridge-nf-call-iptables` | `1` | Bridge traffic visible to iptables |
| `net.bridge.bridge-nf-call-ip6tables` | `1` | Same for IPv6 |

#### Required: Kube-OVN kernel modules

Kube-OVN bundles the OVS userspace daemon in its own DaemonSet — only the kernel modules are needed on the host:

```text
# /etc/modules-load.d/cozystack.conf (same file)
openvswitch
geneve
ip_tables
iptable_nat
```

The `openvswitch` kernel module is in the upstream kernel since 3.3; no OVS userspace package is required on the host.

#### Enabled by default: ZFS backend for LINSTOR

`cozystack_enable_zfs: true` (default) installs ZFS userspace tools and loads the kernel module. Set to `false` to skip.

| Distribution | Package | Repo |
| --- | --- | --- |
| Ubuntu 22.04 / 24.04 | `zfsutils-linux` | Default repos (kernel module ships in `linux-modules-extra-*`) |
| RHEL 8+ / Rocky 8+ / Alma 8+ / CentOS Stream 8+ | `zfs` | OpenZFS release RPM — prepare playbook imports the GPG key and installs it automatically. No release RPM is yet published for EL10; set `cozystack_enable_zfs: false` on Rocky 10 / Alma 10 until upstream ships one. |
| openSUSE Leap 15.6 / SLE 15 | `zfs` | OBS `filesystems` repo — prepare playbook imports the repo key and adds it automatically |

#### Enabled by default: KubeVirt virtualization

`cozystack_enable_kubevirt: true` (default) loads the kernel modules KubeVirt needs. Set to `false` to skip.

> **No host userspace packages are installed.** KubeVirt bundles QEMU and libvirt in its own pods. Only the kernel modules listed below are loaded on the host.

Loaded via `/etc/modules-load.d/cozystack-kubevirt.conf`. The prepare playbook detects the CPU vendor (via `ansible_processor`) and writes only the matching `kvm_*` module so `systemd-modules-load` does not report a failure at boot:

```text
vhost_net
tun
kvm_intel  # or kvm_amd depending on the CPU
```

#### Known limitations

ZFS support depends on the OS ecosystem and kernel flavor. The prepare
playbooks skip ZFS automation gracefully in these cases and emit an
informational notice:

| OS / kernel | ZFS automation | Reason |
| --- | --- | --- |
| Ubuntu 22.04 / 24.04 | Automated | `zfsutils-linux` in main repo; kernel module ships in `linux-modules-extra-*` |
| Debian 12+ | **Not automated** | `zfsutils-linux` lives in `contrib`; kernel module requires `zfs-dkms`. Enable contrib and install manually, or set `cozystack_enable_zfs: false`. |
| RHEL 9 / Rocky 9 / Alma 9 (stock kernel) | Automated | OpenZFS release RPM via `cozystack_zfs_release_rpm_by_major` |
| RHEL 10 (stock kernel) | **Fails fast** when `cozystack_enable_zfs: true` (default). Skipped cleanly when set to `false`. | OpenZFS has not yet published an el10 release RPM. Set `cozystack_enable_zfs: false` for now; once upstream publishes one, supply the URL from inventory via `cozystack_zfs_release_rpm_extra: {"10": "<url>"}`. |
| openSUSE Leap 15.6 / Tumbleweed / SLE | Automated | OBS `filesystems` repo; the playbook auto-detects the path segment |

Other subsystem notes:

- **Cloud providers (Ubuntu on OCI, AWS, GCP):** stock Ubuntu cloud images ship an iptables INPUT chain that ends with `REJECT icmp-host-prohibited`, which blocks k3s ports 2380/6443 between nodes. Set `cozystack_flush_iptables: true` in your inventory so the prepare playbook flushes the INPUT chain before k3s installs. Oracle Linux images on OCI do not have this restriction out of the box.
- **Rocky 10 / Alma 10 (and other RHEL 10 rebuilds):** the `iptables` userspace binary is not installed by default. `examples/rhel/prepare-rhel.yml` installs `iptables-nft` so the `cozystack_flush_iptables` task and k3s kube-proxy replacement have a working `iptables` wrapper over nftables.
- **ARM64 (aarch64):** OpenZFS does not publish aarch64 RPMs for RHEL-family distributions via `zfsonlinux.org/epel`. Cozystack itself targets x86_64.
- **Piraeus DRBD loader + staged kernel updates:** kernel headers must match the *running* kernel. The playbooks pin `linux-headers-{{ ansible_kernel }}` / `kernel-devel-{{ ansible_kernel }}` for this reason. On openSUSE/SLE, zypper rejects the version suffix because SUSE's NVR format differs from `uname -r`; `kernel-default-devel` is used unversioned and zypper resolves it to the installed kernel. Reboot after any kernel update before running the playbook.

#### Recommended: BPF filesystem mount for Cilium

Cilium stores eBPF maps at `/sys/fs/bpf`. The Cilium DaemonSet mounts this path itself when missing, but for production durability across reboots add:

```text
# /etc/fstab
bpffs /sys/fs/bpf bpf defaults 0 0
```

The prepare playbook does not automate this.

#### System services

Enable and start:

- `iscsid` — iSCSI initiator daemon
- `multipathd` — multipath device manager

#### iptables (cloud providers)

Cloud providers (OCI, AWS, GCP) may ship images with restrictive iptables
INPUT rules that block inter-node Kubernetes traffic (API 6443, kubelet 10250,
etcd 2379-2380) even when security groups allow it.

Fix: flush the INPUT chain and set policy to ACCEPT before deploying k3s.

#### k3s configuration

Cozystack replaces several k3s built-in components. Required server flags:

```text
--disable=traefik,servicelb,local-storage,metrics-server
--disable-network-policy --disable-kube-proxy
--flannel-backend=none --cluster-domain=cozy.local
--kubelet-arg=max-pods=220
```

| Flag | Reason |
| --- | --- |
| `--disable=traefik` | Cozystack deploys its own Ingress |
| `--disable=servicelb` | Replaced by MetalLB |
| `--disable=local-storage` | Replaced by LINSTOR |
| `--disable=metrics-server` | Replaced by VictoriaMetrics |
| `--disable-network-policy` | Network policies managed by KubeOVN |
| `--disable-kube-proxy` | Replaced by Cilium/KubeOVN |
| `--flannel-backend=none` | CNI provided by Cozystack (Cilium + KubeOVN) |
| `--cluster-domain=cozy.local` | Required service discovery domain |
| `--kubelet-arg=max-pods=220` | Cozystack runs many pods per node |

Required server config (`/etc/rancher/k3s/config.yaml`):

```yaml
cluster-cidr: 10.42.0.0/16
service-cidr: 10.43.0.0/16
```

These CIDRs are the k3s defaults. The example prepare playbooks
(e.g., `examples/ubuntu/prepare-ubuntu.yml`) set them via the
`server_config_yaml` variable used by `k3s.orchestration`. The role
variables `cozystack_pod_cidr` and `cozystack_svc_cidr` must match —
they default to the same values.

## Installation

```bash
ansible-galaxy collection install git+https://github.com/cozystack/ansible-cozystack.git
```

Or via `requirements.yml`:

```yaml
collections:
  - name: cozystack.installer
    source: https://github.com/cozystack/ansible-cozystack.git
    type: git
    version: main
```

## Quick start

1. Create your environment (pick your distro — see `examples/ubuntu/`,
   `examples/rhel/`, or `examples/suse/`):

```text
my-env/
├── ansible.cfg
├── inventory.yml
├── requirements.yml
├── prepare-<distro>.yml  (copy from examples/<distro>/)
└── site.yml              (copy from examples/<distro>/)
```

2. Install collections:

```bash
ansible-galaxy collection install --requirements-file requirements.yml
```

3. Run the full pipeline:

```bash
ansible-playbook site.yml
```

## How it works

The collection uses a **two-stage installation**:

1. **Stage 1** (Helm install): Deploys the Cozystack operator. The operator starts, installs CRDs via `--install-crds`, and creates the PackageSource.
2. **Stage 2** (Platform Package): Creates the Platform Package CR with variant, networking CIDRs, and optional publishing config.

Both stages are handled automatically by the `cozystack` role.

## Playbooks

| Playbook | Description |
| --- | --- |
| `cozystack.installer.site` | Install Cozystack on `server[0]` |

## Role: cozystack.installer.cozystack

Installs Cozystack via the official `cozy-installer` Helm chart using
the `kubernetes.core.helm` module with automatic Helm and helm-diff
installation.

Runs on `server[0]` only.

### Required variables

| Variable | Description | Example |
| --- | --- | --- |
| `cozystack_api_server_host` | Internal IP of the control-plane node (NOT public/NAT IP) | `10.0.0.10` |

### Optional variables

| Variable | Default | Description |
| --- | --- | --- |
| `cozystack_chart_ref` | `oci://ghcr.io/cozystack/cozystack/cozy-installer` | Helm chart OCI reference |
| `cozystack_chart_version` | `1.3.0` | Helm chart version |
| `cozystack_release_name` | `cozy-installer` | Helm release name |
| `cozystack_namespace` | `cozy-system` | Namespace for operator and resources |
| `cozystack_release_namespace` | `kube-system` | Namespace for Helm release secret |
| `cozystack_operator_variant` | `generic` | Operator variant: generic, talos, hosted |
| `cozystack_api_server_port` | `6443` | API server port |
| `cozystack_kubeconfig` | `/etc/rancher/k3s/k3s.yaml` | Kubeconfig path on target |
| `cozystack_helm_version` | `3.20.0` | Helm binary version to install |
| `cozystack_helm_binary` | `/usr/local/bin/helm` | Path to Helm binary on target |
| `cozystack_create_platform_package` | `true` | Create Platform Package CR after install |
| `cozystack_platform_variant` | `isp-full-generic` | Platform variant: default, isp-full, isp-hosted, isp-full-generic |
| `cozystack_root_host` | `""` | Domain for Cozystack services (empty = skip publishing) |
| `cozystack_external_ips` | `[]` | List of external IPs for ingress-nginx Service. Required on platforms without a native LB (cloud VMs, bare metal). Each entry must be a valid IPv4/IPv6 address. |
| `cozystack_tenant_root_ingress` | `false` | Enable ingress on the root tenant. When `true`, patches the root Tenant CR after Platform Package apply to create IngressClass and ingress-nginx controller. |
| `cozystack_pod_cidr` | `10.42.0.0/16` | Pod CIDR for Platform Package |
| `cozystack_pod_gateway` | `10.42.0.1` | Pod gateway |
| `cozystack_svc_cidr` | `10.43.0.0/16` | Service CIDR |
| `cozystack_join_cidr` | `100.64.0.0/16` | Join CIDR |
| `cozystack_master_nodes` | `""` (auto-detect) | Comma-separated control-plane node IPs for kube-ovn RAFT. Empty = auto-detect from `server` group |
| `cozystack_operator_wait_timeout` | `300` | Timeout for operator/CRD readiness (seconds) |

### Example playbook variables

These variables are consumed only by the example prepare playbooks in
`examples/*/`, not by the role itself. Set them as inventory host/group
vars to opt out of the corresponding prepare step:

| Variable | Default | Description |
| --- | --- | --- |
| `cozystack_enable_zfs` | `true` | Example playbooks: install ZFS userspace and load the module. Set `false` to skip. |
| `cozystack_enable_kubevirt` | `true` | Example playbooks: load KubeVirt kernel modules. Set `false` to skip. |
| `cozystack_flush_iptables` | `false` | Example playbooks: flush the iptables INPUT chain before k3s installs. Set `true` on Ubuntu/Debian cloud images (OCI/AWS/GCP) where the default INPUT chain ends with `REJECT icmp-host-prohibited` and blocks k3s inter-node ports 2380/6443. |
| `cozystack_zfs_release_rpm_extra` | `{}` | `examples/rhel/` only: merged on top of the built-in `cozystack_zfs_release_rpm_by_major` dict, so you can add (or override) a single EL-major → OpenZFS release RPM entry from inventory without wiping the base dict. Example: `{"10": "https://zfsonlinux.org/epel/zfs-release-X-Y.el10.noarch.rpm"}` once upstream ships one. |

## Using with k3s

This collection is designed to work alongside [k3s.orchestration](https://github.com/k3s-io/k3s-ansible). The inventory structure (groups: `cluster`, `server`, `agent`) is fully compatible.

Example full pipeline (`site.yml`) — see `examples/ubuntu/`, `examples/rhel/`,
or `examples/suse/`:

```yaml
- name: Prepare nodes
  ansible.builtin.import_playbook: prepare-<distro>.yml

- name: Deploy k3s cluster
  ansible.builtin.import_playbook: k3s.orchestration.site

- name: Install Cozystack
  ansible.builtin.import_playbook: cozystack.installer.site
```

## Important notes

### apiServerHost must be the internal IP

On cloud providers with NAT (OCI, AWS, GCP), nodes have internal IPs different from public IPs. KubeOVN validates the host IP against `NODE_IPS` and crashes if they don't match. Always use the IP visible on the node's network interface.

### Multi-master setup (kube-ovn RAFT)

Kube-ovn requires `MASTER_NODES` — a comma-separated list of all
control-plane node IPs for OVN RAFT consensus. By default, the role
auto-detects these IPs from the `server` inventory group host keys.

This works when host keys are internal IPs (the recommended inventory
pattern):

```yaml
server:
  hosts:
    10.0.0.10:
      ansible_host: 203.0.113.10
    10.0.0.11:
      ansible_host: 203.0.113.11
```

If your inventory uses hostnames or non-IP host keys, set
`cozystack_master_nodes` explicitly:

```yaml
cozystack_master_nodes: "10.0.0.10,10.0.0.11,10.0.0.12"
```

### Automatic Helm installation

The role installs Helm and the
[helm-diff](https://github.com/databus23/helm-diff) plugin on the
target node automatically. The `helm-diff` plugin enables true
idempotency — repeated runs report no changes when the release is
already up to date.

### Customizing variables

The example prepare playbooks define internal variables (like
`cozystack_k3s_server_args`) in the play `vars` section. User-facing
variables such as `cozystack_k3s_extra_args` and
`cozystack_flush_iptables` should be set **in the inventory**, not in
the playbook. Ansible play `vars` take precedence over inventory
variables, so defining them in both places causes the inventory values
to be silently ignored.

### Idempotency

All tasks are idempotent. Running the playbook multiple times produces no changes if the state is already correct. The `--check` mode is supported.

## License

Apache-2.0
