#!/usr/bin/env bash
# GitHub(리눅스, 대소문자 구분)에 맞게 object PNG 파일명을 object_defs.json과 일치시킵니다.
# Windows에서 파일만 rename 하면 Git이 변경을 못 잡는 경우가 많아 git mv 2단계가 필요합니다.
#
# 사용법 (저장소 루트에서):
#   bash tools/git_fix_object_asset_case.sh
#   git status
#   git commit -m "Fix object asset filename case for Android/Linux"
#   git push

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OBJ="$ROOT/assets/images/object"
cd "$OBJ"

renames=(
  "Tree1.png tree1.png"
  "Tree2.png tree2.png"
  "Tree3.png tree3.png"
  "Tree4.png tree4.png"
  "Tree5.png tree5.png"
  "Tree6.png tree6.png"
  "Tree7.png tree7.png"
  "Bush1.png bush1.png"
  "Bush2.png bush2.png"
  "Plant1.png plant1.png"
  "Plant2.png plant2.png"
  "Plant3.png plant3.png"
  "Plant4.png plant4.png"
  "Plant5.png plant5.png"
  "tv.png TV.png"
)

git_mv_case() {
  local src="$1" dst="$2"
  if git ls-files --error-unmatch "$src" >/dev/null 2>&1; then
    if [[ "$src" == "$dst" ]]; then
      return 0
    fi
    local tmp="__case_tmp_${RANDOM}_${src}"
    git mv "$src" "$tmp"
    git mv "$tmp" "$dst"
    echo "git mv: $src -> $dst"
    return 0
  fi
  if git ls-files --error-unmatch "$dst" >/dev/null 2>&1; then
    echo "already tracked: $dst"
    return 0
  fi
  if [[ -f "$src" ]]; then
    mv "$src" "$dst"
    git add "$dst"
    echo "add: $dst (was untracked $src)"
    return 0
  fi
  if [[ -f "$dst" ]]; then
    echo "skip missing in index, file exists: $dst"
    return 0
  fi
  echo "missing: $src / $dst"
}

for pair in "${renames[@]}"; do
  set -- $pair
  git_mv_case "$1" "$2"
done

echo "Done. Run 'git status' then commit and push."
