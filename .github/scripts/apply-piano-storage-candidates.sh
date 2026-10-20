#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <common-kernel-root>" >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
patch_dir="$script_dir/../../patches/piano"
expected_base=339c7c85511e9c6df8d67e7e06ff111a246a40b8

# Match the custom-option step's last-assignment-wins behavior, including
# explicit "is not set" lines. Never evaluate configuration text as shell code.
config_enabled() {
  local symbol=$1 line enabled=0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line//$'\r'/}
    if [[ "$line" =~ ^[[:space:]]*${symbol}=(.*)$ ]]; then
      if [[ "${BASH_REMATCH[1]}" =~ ^[[:space:]]*[yY][[:space:]]*$ ]]; then
        enabled=1
      else
        enabled=0
      fi
    elif [[ "$line" =~ ^[[:space:]]*#[[:space:]]*${symbol}[[:space:]]+is[[:space:]]+not[[:space:]]+set[[:space:]]*$ ]]; then
      enabled=0
    fi
  done <<< "${CUSTOM_KERNEL_OPTIONS:-}"
  [ "$enabled" -eq 1 ]
}

shopt -s nocasematch
patches=()
hashes=()
if config_enabled CONFIG_F2FS_VIP_FILE; then
  patches+=("$patch_dir/0001-f2fs-vip-functional-candidate.patch")
  hashes+=(95fd6d16a730950dede24498d15d798f46fe99f56c225fd0f3c8a03b9ac8433e)
fi
if config_enabled CONFIG_SCSI_BATCH_UNMAP; then
  patches+=("$patch_dir/0001-scsi-sd-bounded-generic-batch-unmap.patch")
  hashes+=(794a3f324966e7bbb00587758c81400ca0e73756857a1bfc255fc37477c72e65)
fi

if [ "${#patches[@]}" -eq 0 ]; then
  echo "No piano storage candidate selected."
  exit 0
fi

common_root=$(cd -- "$1" && pwd -P)
git_root=$(git -C "$common_root" rev-parse --show-toplevel)
if [ "$git_root" != "$common_root" ]; then
  echo "::error::The common kernel path must be its Git repository root." >&2
  exit 1
fi
actual_base=$(git -C "$common_root" rev-parse --verify 'HEAD^{commit}')
if [ "$actual_base" != "$expected_base" ]; then
  echo "::error::Piano storage candidates require common HEAD $expected_base; got $actual_base." >&2
  exit 1
fi

for i in "${!patches[@]}"; do
  patch=${patches[$i]}
  if [ ! -f "$patch" ]; then
    echo "::error::Missing piano storage candidate: $patch" >&2
    exit 1
  fi
  actual_hash=$(sha256sum -- "$patch")
  actual_hash=${actual_hash%% *}
  if [ "$actual_hash" != "${hashes[$i]}" ]; then
    echo "::error::Piano storage candidate SHA256 mismatch: $patch" >&2
    exit 1
  fi
done

# Check every selected patch together before changing any source. Deliberately
# use normal git apply context matching, without fuzz, whitespace relaxation,
# reject files, or three-way application.
git -C "$common_root" apply --check -- "${patches[@]}"
git -C "$common_root" apply -- "${patches[@]}"
printf 'Applied piano storage candidates at common HEAD %s:\n' "$actual_base"
printf '  %s\n' "${patches[@]}"
