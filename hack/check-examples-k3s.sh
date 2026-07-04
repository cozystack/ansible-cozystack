#!/usr/bin/env bash
# Guard the split-invocation contract for the example clusters.
#
# The Cozystack-tuned k3s configuration must reach the k3s.orchestration role
# on every path the examples support:
#   1. chained: `ansible-playbook examples/<distro>/site.yml -i <inv>`, where
#      site.yml `import_playbook`s k3s.orchestration.site from the collection
#      directory;
#   2. split:   `ansible-playbook prepare-<distro>.yml -i <inv>` followed by a
#      separate `ansible-playbook k3s.orchestration.site -i <inv>` process;
#   3. with an external inventory kept outside examples/<distro>/ (this is
#      exactly how CI runs, via tests/ci-inventory.yml).
#
# That holds only if the flags live at INVENTORY scope. A playbook-adjacent
# group_vars/all.yml is NOT enough: playbook group_vars are scoped to the
# top-level playbook's directory and are not loaded for an imported playbook
# that lives elsewhere (the collection dir), nor for a standalone
# k3s.orchestration.site run against an external inventory. In both cases the
# flags silently vanish and k3s comes up with upstream defaults (traefik,
# servicelb, flannel, kube-proxy, cluster.local, ...) with nothing warning.
#
# This guard fails the build if that invariant regresses. It checks, for the
# three example inventories and tests/ci-inventory.yml:
#   A. the k3s vars are defined in the inventory `vars:` block;
#   B. the tuned constants are byte-identical across all four inventories;
#   C. each example inventory declares the k3s_cluster group statically;
#   D. the composed vars actually resolve to the tuned values inside a play
#      IMPORTED across a directory boundary, with the inventory read from a
#      neutral location (no adjacent group_vars to mask a regression);
#   E. the prepare playbooks do not re-introduce the vars at play scope.
#
# Requires mikefarah/yq and ansible-core (both present in the Lint job).

set -euo pipefail
# Propagate command-substitution failures into the enclosing assignment.
shopt -s inherit_errexit

cd "$(dirname "$0")/.."

for tool in yq ansible-playbook; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "check-examples-k3s.sh: $tool is required but was not found on PATH" >&2
    exit 2
  fi
done

distros=(ubuntu rhel suse)
# The four inventories that must all carry the tuned config.
inventories=(
  examples/ubuntu/inventory.yml
  examples/rhel/inventory.yml
  examples/suse/inventory.yml
  tests/ci-inventory.yml
)
# A representative subset of the flags every inventory must end up passing to
# k3s, plus the config keys — enough to detect a dropped/garbled value.
required_flags=(--disable=traefik --disable-kube-proxy --flannel-backend=none --cluster-domain=cozy.local)
required_config=(cluster-cidr service-cidr)

err=0
fail() {
  printf 'FAIL %s\n' "$*" >&2
  err=1
}

# Scratch space for the import-boundary probe (D). top.yml and imported.yml
# live in *different* directories to mirror examples/<distro>/site.yml
# importing k3s.orchestration.site from the collection directory.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/top" "$tmp/imported"
cat >"$tmp/imported/probe.yml" <<'YAML'
- name: Resolve the tuned k3s vars across an import boundary
  hosts: all
  gather_facts: false
  connection: local
  run_once: true
  tasks:
    - ansible.builtin.debug:
        msg: >-
          PROBE
          extra=[{{ extra_server_args | default('__UNDEF__') }}]
          cfg=[{{ server_config_yaml | default('__UNDEF__') }}]
YAML
cat >"$tmp/top/probe.yml" <<'YAML'
- ansible.builtin.import_playbook: ../imported/probe.yml
YAML

# A. + B.: extract the tuned constants from every inventory `vars:` block and
# require them present and identical across all four files.
ref_args="" ref_cfg=""
for inv in "${inventories[@]}"; do
  for var in cozystack_k3s_server_args cozystack_k3s_server_config_yaml \
             extra_server_args server_config_yaml; do
    if ! yq --exit-status ".cluster.vars.$var" "$inv" >/dev/null 2>&1; then
      fail "$inv: missing inventory-scope variable 'cluster.vars.$var'"
    fi
  done
  args=$(yq '.cluster.vars.cozystack_k3s_server_args' "$inv")
  cfg=$(yq '.cluster.vars.cozystack_k3s_server_config_yaml' "$inv")
  if [ -z "$ref_args" ]; then
    ref_args="$args" ref_cfg="$cfg"
  else
    [ "$args" = "$ref_args" ] || fail "$inv: cozystack_k3s_server_args drifted from the other inventories"
    [ "$cfg" = "$ref_cfg" ] || fail "$inv: cozystack_k3s_server_config_yaml drifted from the other inventories"
  fi
done

# C.: each example inventory declares k3s_cluster statically (children:
# server, agent) so a standalone k3s.orchestration.site run finds the group.
for d in "${distros[@]}"; do
  inv="examples/$d/inventory.yml"
  if ! yq --exit-status \
    '.k3s_cluster.children | (has("server") and has("agent"))' \
    "$inv" >/dev/null 2>&1; then
    fail "$inv: k3s_cluster must be declared statically (children: server, agent)"
  fi
done

# D.: behavioural — the vars resolve inside an imported play, with the
# inventory read from a neutral copy so only inventory-scope definitions can
# satisfy it. This is the exact path that regressed when the flags lived in a
# playbook-adjacent group_vars/all.yml.
for inv in "${inventories[@]}"; do
  cp "$inv" "$tmp/inv.yml"
  rendered=$(ansible-playbook "$tmp/top/probe.yml" --inventory "$tmp/inv.yml" \
    --connection local 2>/dev/null | grep -F 'PROBE' || true)
  for flag in "${required_flags[@]}"; do
    if ! printf '%s' "$rendered" | grep --quiet -- "$flag"; then
      fail "$inv: extra_server_args does not resolve '$flag' inside an imported play"
    fi
  done
  for key in "${required_config[@]}"; do
    if ! printf '%s' "$rendered" | grep --quiet -- "$key"; then
      fail "$inv: server_config_yaml does not resolve '$key' inside an imported play"
    fi
  done
done

# E.: the prepare playbooks must NOT re-introduce these variables at play
# scope (set_fact / play vars): a play var outranks the inventory on the
# chained path while the split path stays broken — the exact bug class this
# fix removed.
for d in "${distros[@]}"; do
  pp="examples/$d/prepare-$d.yml"
  if grep --extended-regexp --quiet 'extra_server_args|server_config_yaml' "$pp"; then
    fail "$pp: must not reference extra_server_args/server_config_yaml (they belong in inventory.yml)"
  fi
done

if [ "$err" -ne 0 ]; then
  printf 'check-examples-k3s.sh: split-invocation contract violated\n' >&2
  exit 1
fi
printf 'OK examples k3s split-invocation contract holds (ubuntu, rhel, suse, ci)\n'
