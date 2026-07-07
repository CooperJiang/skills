#!/usr/bin/env bash
# 无 Node 时的兜底安装器:把 skills/ 下每个 skill 软链接到 ~/.claude/skills/
# 用法:bash scripts/install.sh [skill名... | all]   默认 all
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/skills"
DEST="$HOME/.claude/skills"
mkdir -p "$DEST"

targets=("$@")
[ ${#targets[@]} -eq 0 ] && targets=("all")

install_one() {
  local name="$1"
  local s="$SRC/$name"
  [ -f "$s/SKILL.md" ] || { echo "✗ 跳过 $name(无 SKILL.md)"; return; }
  local d="$DEST/$name"
  if [ -e "$d" ] || [ -L "$d" ]; then
    if [ -L "$d" ]; then rm "$d";
    else mv "$d" "$d.bak-$(date +%s)"; echo "  备份原目录 → $d.bak-*"; fi
  fi
  ln -s "$s" "$d"
  echo "✓ 链接 $name → $s"
}

if [ "${targets[0]}" = "all" ]; then
  for dir in "$SRC"/*/; do install_one "$(basename "$dir")"; done
else
  for t in "${targets[@]}"; do install_one "$t"; done
fi
echo "完成。新开对话即可用;已开会话需重启。"
