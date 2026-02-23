# Ansible Collection: cozystack.installer

Install [Cozystack](https://cozystack.io) on generic Kubernetes clusters (k3s, kubeadm, RKE2).

Tested on:

- **Ubuntu / Debian** — `examples/ubuntu/`
- **RHEL 8+ / CentOS Stream 8+ / Rocky / Alma** — `examples/rhel/`
- **openSUSE / SLE** — `examples/suse/`

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

### Target nodes

The following must be configured on ALL cluster nodes before running the
collection. See the per-distro example playbooks:

- `examples/ubuntu/prepare-ubuntu.yml` (Ubuntu/Debian)
- `examples/rhel/prepare-rhel.yml` (RHEL 8+/CentOS Stream 8+/Rocky/Alma)
- `examples/suse/prepare-suse.yml` (openSUSE/SLE)

#### System packages

| Package (Debian/Ubuntu) | Package (RHEL/CentOS) | Package (openSUSE/SLE) | Purpose |
| --- | --- | --- | --- |
| `nfs-common` | `nfs-utils` | `nfs-client` | NFS storage driver support |
| `open-iscsi` | `iscsi-initiator-utils` | `open-iscsi` | iSCSI storage driver (LINSTOR) |
| `multipath-tools` | `device-mapper-multipath` | `multipath-tools` | Multipath I/O for HA storage |

#### Kernel parameters

| Parameter | Value | Why |
| --- | --- | --- |
| `fs.inotify.max_user_watches` | `524288` | Kubernetes watch events |
| `fs.inotify.max_user_instances` | `8192` | Multiple inotify watchers |
| `fs.inotify.max_queued_events` | `65536` | Event queue depth |
| `fs.file-max` | `2097152` | Open file descriptors limit |
| `fs.aio-max-nr` | `1048576` | Async I/O operations (databases) |
| `net.ipv4.ip_forward` | `1` | Pod-to-pod routing |
| `net.ipv4.conf.all.forwarding` | `1` | Global IP forwarding |
| `vm.swappiness` | `1` | Minimize swap usage |

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
| `cozystack_chart_version` | `1.0.0-rc.1` | Helm chart version |
| `cozystack_release_name` | `cozy-installer` | Helm release name |
| `cozystack_namespace` | `cozy-system` | Namespace for operator and resources |
| `cozystack_release_namespace` | `kube-system` | Namespace for Helm release secret |
| `cozystack_operator_variant` | `generic` | Operator variant: generic, talos, hosted |
| `cozystack_api_server_port` | `6443` | API server port |
| `cozystack_kubeconfig` | `/etc/rancher/k3s/k3s.yaml` | Kubeconfig path on target |
| `cozystack_helm_version` | `3.17.3` | Helm binary version to install |
| `cozystack_helm_binary` | `/usr/local/bin/helm` | Path to Helm binary on target |
| `cozystack_create_platform_package` | `true` | Create Platform Package CR after install |
| `cozystack_platform_variant` | `isp-full-generic` | Platform variant: default, isp-full, isp-hosted, isp-full-generic |
| `cozystack_root_host` | `""` | Domain for Cozystack services (empty = skip publishing) |
| `cozystack_pod_cidr` | `10.42.0.0/16` | Pod CIDR for Platform Package |
| `cozystack_pod_gateway` | `10.42.0.1` | Pod gateway |
| `cozystack_svc_cidr` | `10.43.0.0/16` | Service CIDR |
| `cozystack_join_cidr` | `100.64.0.0/16` | Join CIDR |
| `cozystack_operator_wait_timeout` | `300` | Timeout for operator/CRD readiness (seconds) |

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

### Automatic Helm installation

The role installs Helm and the
[helm-diff](https://github.com/databus23/helm-diff) plugin on the
target node automatically. The `helm-diff` plugin enables true
idempotency — repeated runs report no changes when the release is
already up to date.

### Idempotency

All tasks are idempotent. Running the playbook multiple times produces no changes if the state is already correct. The `--check` mode is supported.

## License

Apache-2.0
