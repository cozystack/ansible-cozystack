#!/usr/bin/env bash
# Tests for hack/check-examples-k3s.sh.
#
# Copies the repo tree to a tmpdir, runs the script once against the clean
# tree (expect exit 0), then perturbs a single invariant at a time and
# asserts a nonzero exit. Ensures a future refactor of the guard does not
# silently stop detecting a broken split-invocation contract.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

rsync --archive --exclude='.git' --exclude='*.bak' "$REPO_ROOT"/ "$tmpdir"/

fail() {
  echo "TEST FAIL: $*" >&2
  exit 1
}

# Positive: clean tree reports no violation.
echo "-- positive: clean tree must exit 0 --"
if ! (cd "$tmpdir" && ./hack/check-examples-k3s.sh) >/dev/null; then
  fail "clean tree unexpectedly reported a contract violation"
fi

# Negative helper: mutate a single file with yq, run the guard, expect a
# nonzero exit, then restore the file for the next case.
run_negative() {
  local label="$1" file="$2" yq_expr="$3"
  echo "-- negative: ${label} (${file}) --"
  cp "$tmpdir/$file" "$tmpdir/$file.bak"
  yq --inplace "$yq_expr" "$tmpdir/$file"
  local rc=0
  (cd "$tmpdir" && ./hack/check-examples-k3s.sh) >/dev/null 2>&1 || rc=$?
  mv "$tmpdir/$file.bak" "$tmpdir/$file"
  if [ "$rc" -eq 0 ]; then
    fail "${label}: guard returned 0 (expected nonzero)"
  fi
}

# Static group dropped — split invocation would hit the empty-group crash.
run_negative "k3s_cluster group removed" \
  "examples/suse/inventory.yml" 'del(.k3s_cluster)'

# Inventory-scope variable deleted — a fresh process / imported play cannot
# resolve it.
run_negative "extra_server_args missing from inventory vars" \
  "examples/ubuntu/inventory.yml" 'del(.cluster.vars.extra_server_args)'

# Variable present but garbled — structural check passes, the import-boundary
# behavioural check must catch the dropped flags.
run_negative "extra_server_args garbled (flags dropped)" \
  "examples/rhel/inventory.yml" '.cluster.vars.extra_server_args = "nonsense"'

# CIDR config blanked — behavioural check must catch the dropped CIDRs.
run_negative "server_config_yaml blanked" \
  "examples/ubuntu/inventory.yml" '.cluster.vars.server_config_yaml = ""'

# Tuned constant drifted in one inventory while still carrying the required
# flags — the cross-inventory consistency check must catch it even though the
# behavioural check still passes for that file.
run_negative "cozystack_k3s_server_args drifted in one inventory" \
  "tests/ci-inventory.yml" \
  '.cluster.vars.cozystack_k3s_server_args = "--disable=traefik --disable=servicelb --disable=local-storage --disable=metrics-server --disable-network-policy --disable-kube-proxy --flannel-backend=none --cluster-domain=cozy.local --kubelet-arg=max-pods=999"'

# Variable re-introduced into a prepare playbook (set_fact / play-vars
# regression) — must be rejected even while the inventory stays correct.
echo "-- negative: extra_server_args reintroduced in a prepare playbook --"
pp="$tmpdir/examples/ubuntu/prepare-ubuntu.yml"
cp "$pp" "$pp.bak"
printf '\n# regression: extra_server_args reintroduced at play scope\n' >>"$pp"
rc=0
(cd "$tmpdir" && ./hack/check-examples-k3s.sh) >/dev/null 2>&1 || rc=$?
mv "$pp.bak" "$pp"
if [ "$rc" -eq 0 ]; then
  fail "reintroduced extra_server_args in a prepare playbook but guard returned 0"
fi

echo "OK: all check-examples-k3s tests passed"
