#!/usr/bin/env bash
set -euo pipefail

# Automate next tag + GitHub release.
# Default behavior:
# - detects latest vX.Y.Z tag
# - computes next patch version
# - creates annotated tag on current HEAD
# - pushes main + tag
# - creates GitHub release via gh CLI

usage() {
  cat <<'EOF'
Usage:
  ./.local/release_next.sh [--tag vX.Y.Z] [--notes "text"] [--generate-notes]

Options:
  --tag vX.Y.Z       Use an explicit tag instead of auto-incrementing patch.
  --notes "text"     Release notes text (default: "Release <tag>").
  --generate-notes   Ask GitHub to auto-generate release notes.
  -h, --help         Show this help.

Examples:
  ./.local/release_next.sh
  ./.local/release_next.sh --generate-notes
  ./.local/release_next.sh --tag v0.2.0 --notes "Minor improvements"
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: required command not found: $cmd" >&2
    exit 1
  fi
}

latest_semver_tag() {
  git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n 1
}

next_patch_tag() {
  local current="$1"
  if [[ -z "$current" ]]; then
    echo "v0.1.0"
    return
  fi

  local version="${current#v}"
  IFS='.' read -r major minor patch <<<"$version"
  patch=$((patch + 1))
  echo "v${major}.${minor}.${patch}"
}

ensure_clean_tree() {
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Error: working tree is not clean. Commit or stash changes first." >&2
    exit 1
  fi
}

ensure_main_branch() {
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$branch" != "main" ]]; then
    echo "Error: current branch is '$branch'. Switch to 'main' first." >&2
    exit 1
  fi
}

main() {
  require_cmd git
  require_cmd gh

  local explicit_tag=""
  local notes=""
  local generate_notes="false"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --tag)
        explicit_tag="${2:-}"
        shift 2
        ;;
      --notes)
        notes="${2:-}"
        shift 2
        ;;
      --generate-notes)
        generate_notes="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Error: unknown argument '$1'" >&2
        usage
        exit 1
        ;;
    esac
  done

  ensure_clean_tree
  ensure_main_branch

  local tag
  if [[ -n "$explicit_tag" ]]; then
    tag="$explicit_tag"
  else
    tag="$(next_patch_tag "$(latest_semver_tag)")"
  fi

  if git rev-parse "$tag" >/dev/null 2>&1; then
    echo "Error: tag '$tag' already exists locally." >&2
    exit 1
  fi

  if git ls-remote --tags origin "refs/tags/$tag" | grep -q "$tag"; then
    echo "Error: tag '$tag' already exists on origin." >&2
    exit 1
  fi

  if [[ -z "$notes" ]]; then
    notes="Release $tag"
  fi

  echo "Preparing release: $tag"
  git fetch --tags origin
  git tag -a "$tag" -m "$notes"
  git push origin main
  git push origin "$tag"

  if [[ "$generate_notes" == "true" ]]; then
    gh release create "$tag" --title "$tag" --generate-notes
  else
    gh release create "$tag" --title "$tag" --notes "$notes"
  fi

  echo "Done. Release created for $tag"
}

main "$@"
