#!/usr/bin/env bash
set -euo pipefail

BASE_SHA="${1:-}"
HEAD_SHA="$(git rev-parse HEAD)"
ZERO="0000000000000000000000000000000000000000"

echo "check_ws HEAD=${HEAD_SHA} BASE_SHA=${BASE_SHA:-none}"

if [ -n "$BASE_SHA" ] && [ "$BASE_SHA" != "$ZERO" ]; then
  if git cat-file -e "${BASE_SHA}^{commit}" 2>/dev/null \
    && git merge-base "$BASE_SHA" "$HEAD_SHA" >/dev/null 2>&1; then
    echo "check_ws using ${BASE_SHA:0:7}...${HEAD_SHA:0:7}"
    git diff --check "${BASE_SHA}...${HEAD_SHA}"
    echo "check_ws passed"
    exit 0
  fi
  echo "check_ws BASE_SHA unusable; falling back"
fi

if git rev-parse --verify --quiet HEAD^ >/dev/null; then
  echo "check_ws fallback HEAD^ HEAD"
  git diff --check HEAD^ HEAD
  echo "check_ws passed"
  exit 0
fi

echo "check_ws fallback working tree"
git diff --check
echo "check_ws passed"
