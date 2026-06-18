#!/usr/bin/env bash
# Guard the split-invocation contract for the example clusters.
#
# The Cozystack-tuned k3s configuration must live at inventory scope so it
# survives across separate `ansible-playbook` processes: running
# prepare-<distro>.yml and k3s.orchestration.site as two commands must
# yield the same k3s flags as the chained site.yml. That holds only if
#   1. each examples/<distro>/inventory.yml declares the k3s_cluster group
#      statically (children: server, agent), and
#   2. each examples/<distro>/group_vars/all.yml defines extra_server_args
#      and server_config_yaml at inventory scope (not via set_fact in a
#      prepare playbook, which would vanish in a second process).
# This fails the build if either invariant regresses; the failure mode is
# otherwise silent (k3s comes up with upstream defaults and nothing warns).
#
# Requires mikefarah/yq and ansible-core (both present in the Lint job).

set -euo pipefail
# Propagate command-substitution failures into the enclosing assignment.
shopt -s inherit_errexit

cd "$(dirname "$0")/.."

for tool in yq ansible; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "check-examples-k3s.sh: $tool is required but was not found on PATH" >&2
    exit 2
  fi
done

distros=(ubuntu rhel suse)
# A representative subset of the flags every example must end up passing to
# k3s, plus the config keys — enough to detect a dropped/garbled value.
required_flags=(--disable=traefik --disable-kube-proxy --flannel-backend=none --cluster-domain=cozy.local)
required_config=(cluster-cidr service-cidr)

err=0
fail() {
  printf 'FAIL %s\n' "$*" >&2
  err=1
}

# Render a group_vars variable for the k3s_cluster group in a FRESH process
# (no prepare playbook, no set_fact) — exactly the split-invocation path.
render_var() {
  local inv="$1" var="$2"
  ansible --inventory "$inv" k3s_cluster --connection local \
    --module-name debug --args "var=$var" 2>/dev/null || true
}

for d in "${distros[@]}"; do
  inv="examples/$d/inventory.yml"
  gv="examples/$d/group_vars/all.yml"

  # 1. Static k3s_cluster group with server + agent children.
  if ! yq --exit-status \
    '.k3s_cluster.children | (has("server") and has("agent"))' \
    "$inv" >/dev/null 2>&1; then
    fail "$inv: k3s_cluster must be declared statically (children: server, agent)"
  fi

  # 2. group_vars defines the variables the k3s.orchestration role reads.
  for var in extra_server_args server_config_yaml; do
    if ! yq --exit-status ".$var" "$gv" >/dev/null 2>&1; then
      fail "$gv: missing required variable '$var'"
    fi
  done

  # 3. Behavioural: the composed variables resolve to the tuned values for
  #    every host in the k3s_cluster group across a standalone invocation.
  rendered_args=$(render_var "$inv" extra_server_args)
  for flag in "${required_flags[@]}"; do
    if ! printf '%s' "$rendered_args" | grep --quiet -- "$flag"; then
      fail "$d: extra_server_args does not resolve '$flag' in a standalone invocation"
    fi
  done

  rendered_cfg=$(render_var "$inv" server_config_yaml)
  for key in "${required_config[@]}"; do
    if ! printf '%s' "$rendered_cfg" | grep --quiet -- "$key"; then
      fail "$d: server_config_yaml does not resolve '$key' in a standalone invocation"
    fi
  done

  # 4. The prepare playbook must NOT re-introduce these variables at play
  #    scope (set_fact / play vars): a play var outranks group_vars on the
  #    chained path while the split path stays broken — the exact bug class
  #    this fix removed.
  pp="examples/$d/prepare-$d.yml"
  if grep --extended-regexp --quiet 'extra_server_args|server_config_yaml' "$pp"; then
    fail "$pp: must not reference extra_server_args/server_config_yaml (they belong in group_vars/all.yml)"
  fi
done

if [ "$err" -ne 0 ]; then
  printf 'check-examples-k3s.sh: split-invocation contract violated\n' >&2
  exit 1
fi
printf 'OK examples k3s split-invocation contract holds (ubuntu, rhel, suse)\n'
