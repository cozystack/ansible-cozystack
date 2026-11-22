#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
scratch="$(mktemp --directory "${TMPDIR:-/tmp}/cozystack-oidc-compat.XXXXXXXX")"
printf 'Compatibility test artifacts: %s\n' "$scratch"

export ANSIBLE_COLLECTIONS_SCAN_SYS_PATH=false
export ANSIBLE_COLLECTIONS_PATH="$scratch/stable"
ansible-galaxy collection install \
  --requirements-file "$root/examples/ubuntu/requirements.yml" \
  --collections-path "$ANSIBLE_COLLECTIONS_PATH"

stable="$ANSIBLE_COLLECTIONS_PATH/ansible_collections/cozystack/installer"
if [[ -e "$stable/playbooks/k3s_oidc.yml" ]]; then
  printf 'Expected the pinned release without the unreleased OIDC playbook\n' >&2
  exit 1
fi
for distro in ubuntu rhel suse; do
  ansible-playbook "$root/examples/$distro/site.yml" \
    --inventory "$root/examples/$distro/inventory.yml" --syntax-check
done

mkdir "$scratch/artifact"
ansible-galaxy collection build "$root" --output-path "$scratch/artifact"
export ANSIBLE_COLLECTIONS_PATH="$scratch/current"
ansible-galaxy collection install "$scratch"/artifact/cozystack-installer-*.tar.gz \
  --collections-path "$ANSIBLE_COLLECTIONS_PATH" --no-deps
ansible-playbook cozystack.installer.k3s_oidc --inventory server, --syntax-check
ansible-playbook cozystack.installer.k3s_oidc --inventory server, --check
