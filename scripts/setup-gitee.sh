#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SEEDANCE_ASPECT_REPO:-https://gitee.com/bolecodex/seedance-aspect-remake.git}"
INSTALL_DIR="${SEEDANCE_ASPECT_HOME:-$HOME/.local/share/seedance-aspect-remake}"
BIN_DIR="${SEEDANCE_ASPECT_BIN_DIR:-$HOME/.local/bin}"
SKILL_HOME="${CODEX_HOME:-${ARKCLAW_HOME:-$HOME/.codex}}"
SKILLS_DIR="$SKILL_HOME/skills"
SKILL_NAME="seedance-aspect-remake"

log() {
  printf '[seedance-aspect] %s\n' "$*"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '缺少命令：%s\n' "$1" >&2
    return 1
  fi
}

need_cmd git

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  printf '缺少 Python。请在 ArkCLaw 环境中安装 Python 3.9+ 后重试。\n' >&2
  exit 1
fi

mkdir -p "$(dirname "$INSTALL_DIR")" "$BIN_DIR" "$SKILLS_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  log "更新仓库：$INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --depth=1 origin main
  git -C "$INSTALL_DIR" checkout main >/dev/null
  git -C "$INSTALL_DIR" reset --hard origin/main >/dev/null
else
  if [ -e "$INSTALL_DIR" ]; then
    printf '安装目录已存在但不是 git 仓库：%s\n' "$INSTALL_DIR" >&2
    printf '请移走该目录，或设置 SEEDANCE_ASPECT_HOME 指向其他路径。\n' >&2
    exit 1
  fi
  log "克隆仓库到：$INSTALL_DIR"
  git clone --depth=1 "$REPO_URL" "$INSTALL_DIR"
fi

log "创建/更新 Python 虚拟环境"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
# shellcheck disable=SC1091
. "$INSTALL_DIR/.venv/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -e "$INSTALL_DIR"

if [ ! -f "$INSTALL_DIR/.env" ]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"
  log "已生成环境变量模板：$INSTALL_DIR/.env"
fi

ln -sf "$INSTALL_DIR/.venv/bin/seedance-aspect" "$BIN_DIR/seedance-aspect"
log "CLI 已安装：$BIN_DIR/seedance-aspect"

rm -rf "$SKILLS_DIR/$SKILL_NAME"
cp -R "$INSTALL_DIR/skills/$SKILL_NAME" "$SKILLS_DIR/$SKILL_NAME"
log "中文技能已安装：$SKILLS_DIR/$SKILL_NAME"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  cat >&2 <<'EOF'
警告：未检测到 ffmpeg/ffprobe。
请在 ArkCLaw 运行环境中安装 FFmpeg，并确保 ffmpeg 与 ffprobe 位于 PATH。
EOF
fi

cat <<EOF

安装完成。

请自行配置以下环境变量后使用：
  ARK_API_KEY
  SEEDANCE_MODEL=doubao-seedance-2-0-260128
  VOLC_ACCESSKEY
  VOLC_SECRETKEY
  TOS_BUCKET
  TOS_ENDPOINT=tos-cn-beijing.volces.com
  TOS_REGION=cn-beijing

示例：
  seedance-aspect run ./input.mp4 -o ./job --target auto-opposite
EOF
