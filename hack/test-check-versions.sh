#!/usr/bin/env bash
# Tests for hack/check-versions.sh.
#
# Copies the repo tree to a tmpdir, runs the script once against the clean
# tree (expect exit 0), then for each invariant perturbs a single file and
# asserts exit 1 with the expected "DRIFT in <group>" label on stderr.
# Ensures a future refactor of check-versions.sh does not silently stop
# detecting drift — it must always detect and exit nonzero.

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

# Positive: clean tree reports no drift.
echo "-- positive: clean tree must exit 0 --"
if ! (cd "$tmpdir" && ./hack/check-versions.sh) >/dev/null; then
  fail "clean tree unexpectedly reported drift"
fi

# Negative helper: mutate a single field in a copy of the repo, run the
# script, expect nonzero exit and the right DRIFT label on stderr.
run_negative() {
  local label="$1" file="$2" yq_expr="$3" new_value="$4"
  echo "-- negative: perturb ${file} (${label}) --"
  cp "$tmpdir/$file" "$tmpdir/$file.bak"
  NEW="$new_value" yq --inplace "$yq_expr" "$tmpdir/$file"
  local stderr_file="$tmpdir/stderr.log"
  local rc=0
  (cd "$tmpdir" && ./hack/check-versions.sh) 2>"$stderr_file" >/dev/null || rc=$?
  mv "$tmpdir/$file.bak" "$tmpdir/$file"
  if [ "$rc" -eq 0 ]; then
    cat "$stderr_file" >&2
    fail "perturbed ${file} but script returned 0 (expected nonzero)"
  fi
  if ! grep --quiet "DRIFT in ${label}" "$stderr_file"; then
    cat "$stderr_file" >&2
    fail "perturbed ${file} but stderr did not contain 'DRIFT in ${label}'"
  fi
}

run_negative "cozy-installer" "galaxy.yml" \
  '.version = strenv(NEW)' "0.0.0-test"

run_negative "k3s" "tests/ci-inventory.yml" \
  '.cluster.vars.k3s_version = strenv(NEW)' "v0.0.0-test"

run_negative "k3s.orchestration" "tests/requirements.yml" \
  '(.collections[] | select(.name == "k3s.orchestration") | .version) = strenv(NEW)' "0.0.0-test"

echo "OK: all check-versions tests passed"
