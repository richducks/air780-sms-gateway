#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "此烧录包仅支持 Linux x86_64；当前为 $(uname -s) $(uname -m)。" >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y libudev1 usbutils python3
elif ! ldconfig -p 2>/dev/null | grep -q 'libudev.so.1'; then
  echo "缺少 libudev.so.1，请使用目标系统包管理器安装 libudev。" >&2
  exit 1
fi

sudo usermod -aG dialout "$USER"
"$project_dir/scripts/install-host-network-guard.sh"

echo "依赖和规则已安装。"
if ! id -nG | tr ' ' '\n' | grep -qx dialout; then
  echo "当前登录会话尚未获得 dialout 权限，请重启电脑或注销后重新登录，再运行烧录。"
fi
