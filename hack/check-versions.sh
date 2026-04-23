#!/usr/bin/env bash
# Enforce that version strings stay in sync across files that must agree.
# Three independent invariants are checked; any drift fails the run.
#
# 1. cozy-installer chart version:
#    - galaxy.yml:version
#    - roles/cozystack/defaults/main.yml:cozystack_chart_version
#    - examples/{rhel,suse,ubuntu}/requirements.yml: cozystack.installer.version
#      (leading "v" normalised away before comparison so formats can vary)
#
# 2. k3s binary version:
#    - tests/ci-inventory.yml:k3s_version
#    - examples/{rhel,suse,ubuntu}/inventory.yml:k3s_version
#
# 3. k3s.orchestration collection version:
#    - tests/requirements.yml: k3s.orchestration.version
#    - examples/{rhel,suse,ubuntu}/requirements.yml: k3s.orchestration.version
#
# Requires mikefarah/yq (preinstalled on GitHub-hosted ubuntu runners).

set -euo pipefail
# Propagate failures from command substitutions ($(...)) into the outer
# assignment so a yq extraction error is not silently swallowed into an
# empty value. Requires bash 4.4+; ubuntu-latest and macOS brew-bash both
# qualify.
shopt -s inherit_errexit

if ! command -v yq >/dev/null 2>&1; then
  echo "check-versions.sh: yq (mikefarah) is required but was not found on PATH" >&2
  exit 2
fi

cd "$(dirname "$0")/.."

get_collection_version() {
  local file="$1" name="$2"
  NAME="$name" yq --exit-status \
    '(.collections[] | select(.name == strenv(NAME)) | .version)' "$file"
}

strip_v() {
  printf '%s\n' "${1#v}"
}

# Compare an arbitrary number of (label, value) pairs; returns 0 if all
# values are equal, 1 otherwise. Prints OK/DRIFT report.
report() {
  local label="$1"
  shift
  local -a pairs=("$@")
  local first="${pairs[1]}"
  if [ -z "$first" ]; then
    printf 'DRIFT in %s: reference value is empty (yq extraction failed?)\n' \
      "$label" >&2
    return 1
  fi
  local drift=0
  local i
  for ((i = 1; i < ${#pairs[@]}; i += 2)); do
    if [ "${pairs[i]}" != "$first" ]; then
      drift=1
      break
    fi
  done
  if [ "$drift" -eq 1 ]; then
    printf 'DRIFT in %s:\n' "$label" >&2
    for ((i = 0; i < ${#pairs[@]}; i += 2)); do
      printf '  %-48s = %s\n' "${pairs[i]}" "${pairs[i + 1]}" >&2
    done
    return 1
  fi
  printf 'OK %-20s = %s\n' "$label" "$first"
  return 0
}

err=0

# 1. cozy-installer — normalise every value with strip_v so future format
#    choices (e.g. adding a "v" to galaxy.yml) stay equivalent.
cozy_galaxy=$(strip_v "$(yq --exit-status '.version' galaxy.yml)")
cozy_role=$(strip_v "$(yq --exit-status '.cozystack_chart_version' roles/cozystack/defaults/main.yml)")
cozy_rhel=$(strip_v "$(get_collection_version examples/rhel/requirements.yml cozystack.installer)")
cozy_suse=$(strip_v "$(get_collection_version examples/suse/requirements.yml cozystack.installer)")
cozy_ubuntu=$(strip_v "$(get_collection_version examples/ubuntu/requirements.yml cozystack.installer)")

report "cozy-installer" \
  "galaxy.yml:version"                                "$cozy_galaxy" \
  "roles/cozystack/defaults/main.yml:cozystack_chart_version" "$cozy_role" \
  "examples/rhel/requirements.yml"                    "$cozy_rhel" \
  "examples/suse/requirements.yml"                    "$cozy_suse" \
  "examples/ubuntu/requirements.yml"                  "$cozy_ubuntu" \
  || err=1

# 2. k3s binary — no strip_v: every inventory uses the v-prefixed
#    k3s_version form (e.g. "v1.35.3+k3s1"), so values are already
#    directly comparable. Adding a new inventory without the "v" prefix
#    would intentionally fail this check.
k3s_ci=$(yq --exit-status '.cluster.vars.k3s_version' tests/ci-inventory.yml)
k3s_rhel=$(yq --exit-status '.cluster.vars.k3s_version' examples/rhel/inventory.yml)
k3s_suse=$(yq --exit-status '.cluster.vars.k3s_version' examples/suse/inventory.yml)
k3s_ubuntu=$(yq --exit-status '.cluster.vars.k3s_version' examples/ubuntu/inventory.yml)

report "k3s" \
  "tests/ci-inventory.yml"                            "$k3s_ci" \
  "examples/rhel/inventory.yml"                       "$k3s_rhel" \
  "examples/suse/inventory.yml"                       "$k3s_suse" \
  "examples/ubuntu/inventory.yml"                     "$k3s_ubuntu" \
  || err=1

# 3. k3s.orchestration
orch_tests=$(get_collection_version tests/requirements.yml k3s.orchestration)
orch_rhel=$(get_collection_version examples/rhel/requirements.yml k3s.orchestration)
orch_suse=$(get_collection_version examples/suse/requirements.yml k3s.orchestration)
orch_ubuntu=$(get_collection_version examples/ubuntu/requirements.yml k3s.orchestration)

report "k3s.orchestration" \
  "tests/requirements.yml"                            "$orch_tests" \
  "examples/rhel/requirements.yml"                    "$orch_rhel" \
  "examples/suse/requirements.yml"                    "$orch_suse" \
  "examples/ubuntu/requirements.yml"                  "$orch_ubuntu" \
  || err=1

exit "$err"
