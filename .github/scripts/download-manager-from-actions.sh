#!/usr/bin/env bash
set -euo pipefail

REPO="${1:?repo owner/name required}"
KSU_SHA="${2:?commit SHA required}"
VARIANT_DIR="${3:?output dir required}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=resolve-ksu-ref.sh
source "${SCRIPT_DIR}/resolve-ksu-ref.sh"

# Known names are also used if public artifact metadata is temporarily unavailable.
manager_artifact_names() {
  case "$REPO" in
    ReSukiSU/ReSukiSU) printf '%s\n' "Manager-release" ;;
    SukiSU-Ultra/SukiSU-Ultra) printf '%s\n' "Manager" "manager" ;;
    tiann/KernelSU) printf '%s\n' "manager" ;;
    *)
      echo "::error::Unknown repo for nightly.link manager download: ${REPO}" >&2
      return 1
      ;;
  esac
}

resolve_manager_artifact() {
  local run_id="$1"
  local names artifacts_json artifact
  MANAGER_ARTIFACT_ID=""
  MANAGER_ARTIFACT_NAME=""
  names="$(manager_artifact_names)" || return 1
  KSU_API_REPO="$REPO"
  if ! artifacts_json="$(ksu_github_api_curl \
    "https://api.github.com/repos/${REPO}/actions/runs/${run_id}/artifacts?per_page=100")"; then
    echo "::warning::Could not list manager artifacts on run ${run_id}; trying known nightly.link names for the same run" >&2
    return 0
  fi

  # Match only the normal APK artifact, not mappings, Gradle or spoofed variants.
  # Preserve the actual name's case because nightly.link URLs are case-sensitive.
  if ! artifact="$(printf '%s' "$artifacts_json" | jq -c --arg names "$names" '
    ($names | split("\n") | map(ascii_downcase)) as $allowed |
    first(.artifacts[] | select(.expired != true) |
      select((.name | ascii_downcase) as $name | $allowed | index($name))) // empty')"; then
    echo "::warning::Invalid artifact metadata on run ${run_id}; trying known nightly.link names for the same run" >&2
    return 0
  fi
  if [ -z "$artifact" ]; then
    echo "::error::No unexpired manager APK artifact on run ${run_id} for ${REPO}" >&2
    return 1
  fi
  MANAGER_ARTIFACT_ID="$(printf '%s' "$artifact" | jq -r '.id')"
  MANAGER_ARTIFACT_NAME="$(printf '%s' "$artifact" | jq -r '.name')"
  echo "Manager artifact on run ${run_id}: ${MANAGER_ARTIFACT_NAME} (id ${MANAGER_ARTIFACT_ID})"
}

extract_apk_from_zip() {
  local tmp_zip="$1"
  local tmp_dir
  tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/manager-XXXXXX")"
  if ! unzip -o "$tmp_zip" -d "$tmp_dir"; then
    rm -f "$tmp_zip"
    rm -rf "$tmp_dir"
    return 1
  fi
  rm -f "$tmp_zip"
  if ! find "$tmp_dir" -type f -name '*.apk' -print -quit | grep -q .; then
    echo "::error::Downloaded artifact did not contain an APK" >&2
    find "$tmp_dir" -type f | head -20 >&2 || true
    rm -rf "$tmp_dir"
    return 1
  fi
  if ! cp -a "$tmp_dir/." "$VARIANT_DIR/"; then
    rm -rf "$tmp_dir"
    return 1
  fi
  rm -rf "$tmp_dir"
}

try_download_artifact_api() {
  local run_id="$1"
  local tmp_zip

  # The workflow token cannot download another repository's artifact zip.
  if [ -z "${GITHUB_TOKEN:-}" ] || [ "$REPO" != "$GITHUB_REPOSITORY" ] || [ -z "$MANAGER_ARTIFACT_ID" ]; then
    return 1
  fi

  KSU_API_REPO="$REPO"
  mkdir -p "$VARIANT_DIR"
  tmp_zip="$(mktemp "${TMPDIR:-/tmp}/manager-XXXXXX.zip")"
  if ! ksu_github_api_curl -L \
    "https://api.github.com/repos/${REPO}/actions/artifacts/${MANAGER_ARTIFACT_ID}/zip" \
    -o "$tmp_zip"; then
    rm -f "$tmp_zip"
    return 1
  fi
  extract_apk_from_zip "$tmp_zip" || return 1
  echo "Downloaded manager from ${REPO}@${KSU_SHA} (run ${run_id}, source ${MANAGER_RUN_SOURCE}) via Actions API"
}

try_download_nightly_run() {
  local run_id="$1"
  local names artifact_name url tmp_zip
  names="${MANAGER_ARTIFACT_NAME:-$(manager_artifact_names)}"
  mkdir -p "$VARIANT_DIR"

  while IFS= read -r artifact_name; do
    url="https://nightly.link/${REPO}/actions/runs/${run_id}/${artifact_name}.zip"
    tmp_zip="$(mktemp "${TMPDIR:-/tmp}/manager-XXXXXX.zip")"
    echo "Downloading manager via nightly.link (run ${run_id}, sha ${KSU_SHA}, source ${MANAGER_RUN_SOURCE}): ${url}"
    if ! curl -fsSL -o "$tmp_zip" "$url"; then
      rm -f "$tmp_zip"
      continue
    fi
    if extract_apk_from_zip "$tmp_zip"; then
      echo "Downloaded manager from ${REPO}@${KSU_SHA} (run ${run_id}, source ${MANAGER_RUN_SOURCE}) via nightly.link"
      return 0
    fi
  done <<< "$names"
  return 1
}

if ! ksu_find_manager_run_id "$REPO" "$KSU_SHA"; then
  exit 1
fi
run_id="${KSU_MANAGER_RUN_ID}"
if [ "${MANAGER_RUN_FALLBACK_MAIN:-0}" = "1" ]; then
  echo "::notice::Manager APK from latest successful build-manager on main (KSU ref was ${KSU_SHA})" >&2
fi
echo "Manager workflow run for ${REPO}@${KSU_SHA} (source=${MANAGER_RUN_SOURCE}): https://github.com/${REPO}/actions/runs/${run_id}"
resolve_manager_artifact "$run_id" || exit 1

if [ -n "${GITHUB_REPOSITORY:-}" ] && [ "$REPO" = "$GITHUB_REPOSITORY" ]; then
  if try_download_artifact_api "$run_id"; then
    exit 0
  fi
  echo "::warning::Actions artifact API failed; trying nightly.link for the same run..." >&2
else
  if try_download_artifact_api "$run_id"; then
    exit 0
  fi
  echo "Fork/cross-repo: Actions artifact zip not available; trying nightly.link for the same run..." >&2
fi

if try_download_nightly_run "$run_id"; then
  exit 0
fi

echo "::error::Failed to download manager for ${REPO}@${KSU_SHA} (run ${run_id}, source ${MANAGER_RUN_SOURCE}) via API and nightly.link" >&2
exit 1
