#!/usr/bin/env bash
# Enforce that version strings stay in sync across files that must agree.
# Three independent invariants are checked; any drift fails the run.
#
# 1. cozy-installer chart version:
#    - galaxy.yml:version
#    - roles/cozystack/defaults/main.yml:cozystack_chart_version
#    - examples/{rhel,suse,ubuntu}/requirements.yml: cozystack.installer.version
#      (compared without the leading "v")
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

cd "$(dirname "$0")/.."

err=0

get_collection_version() {
  local file="$1" name="$2"
  yq --exit-status "(.collections[] | select(.name == \"${name}\") | .version)" "$file"
}

strip_v() {
  printf '%s\n' "${1#v}"
}

report() {
  local label="$1"
  shift
  local -a pairs=("$@")
  local first="${pairs[1]}"
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
      printf '  %-60s = %s\n' "${pairs[i]}" "${pairs[i + 1]}" >&2
    done
    err=1
  else
    printf 'OK %-20s = %s\n' "$label" "$first"
  fi
}

# 1. cozy-installer
cozy_galaxy=$(yq --exit-status '.version' galaxy.yml)
cozy_role=$(yq --exit-status '.cozystack_chart_version' roles/cozystack/defaults/main.yml)
cozy_rhel=$(strip_v "$(get_collection_version examples/rhel/requirements.yml cozystack.installer)")
cozy_suse=$(strip_v "$(get_collection_version examples/suse/requirements.yml cozystack.installer)")
cozy_ubuntu=$(strip_v "$(get_collection_version examples/ubuntu/requirements.yml cozystack.installer)")

report "cozy-installer" \
  "galaxy.yml:version"                                 "$cozy_galaxy" \
  "roles/cozystack/defaults/main.yml:chart_version"    "$cozy_role" \
  "examples/rhel/requirements.yml"                     "$cozy_rhel" \
  "examples/suse/requirements.yml"                     "$cozy_suse" \
  "examples/ubuntu/requirements.yml"                   "$cozy_ubuntu"

# 2. k3s binary
k3s_ci=$(yq --exit-status '.cluster.vars.k3s_version' tests/ci-inventory.yml)
k3s_rhel=$(yq --exit-status '.cluster.vars.k3s_version' examples/rhel/inventory.yml)
k3s_suse=$(yq --exit-status '.cluster.vars.k3s_version' examples/suse/inventory.yml)
k3s_ubuntu=$(yq --exit-status '.cluster.vars.k3s_version' examples/ubuntu/inventory.yml)

report "k3s" \
  "tests/ci-inventory.yml"                             "$k3s_ci" \
  "examples/rhel/inventory.yml"                        "$k3s_rhel" \
  "examples/suse/inventory.yml"                        "$k3s_suse" \
  "examples/ubuntu/inventory.yml"                      "$k3s_ubuntu"

# 3. k3s.orchestration
orch_tests=$(get_collection_version tests/requirements.yml k3s.orchestration)
orch_rhel=$(get_collection_version examples/rhel/requirements.yml k3s.orchestration)
orch_suse=$(get_collection_version examples/suse/requirements.yml k3s.orchestration)
orch_ubuntu=$(get_collection_version examples/ubuntu/requirements.yml k3s.orchestration)

report "k3s.orchestration" \
  "tests/requirements.yml"                             "$orch_tests" \
  "examples/rhel/requirements.yml"                     "$orch_rhel" \
  "examples/suse/requirements.yml"                     "$orch_suse" \
  "examples/ubuntu/requirements.yml"                   "$orch_ubuntu"

exit "$err"
