#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tool="$project_dir/tools/luatos-tools-v0.3.0/luatos-tools-v0.3.0-x86_64-unknown-linux-gnu/luatos-tools"
firmware="$project_dir/firmware/air780_usb_sms_bridge.soc"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "此包需要 Linux x86_64；当前为 $(uname -s) $(uname -m)。" >&2
  exit 1
fi
command -v lsusb >/dev/null || { echo "缺少 lsusb，请先运行 install-flash-prerequisites.sh" >&2; exit 1; }
ldd "$tool" >/dev/null 2>&1 || { echo "烧录工具依赖不完整，请先运行 install-flash-prerequisites.sh" >&2; exit 1; }
id -nG | tr ' ' '\n' | grep -qx dialout || { echo "当前会话没有 dialout 权限，请重启或重新登录后再试。" >&2; exit 1; }

echo '83e8e726922040066d4c4bb8a8107abde7372981b63093ecb83c160437d9726e  '"$tool" | sha256sum -c -
echo '491abc6bf5be8404d3911b7059e43411b2073de133beb06099af741646edcb20  '"$firmware" | sha256sum -c -

if ! lsusb | grep -qi '19d1:0001'; then
  echo "未检测到 Air780 (19d1:0001)。请使用数据线直连 USB，确认设备已供电。" >&2
  exit 1
fi

if [ -x "$project_dir/scripts/check-host-network.sh" ]; then
  "$project_dir/scripts/check-host-network.sh"
fi

echo
echo "准备烧录：按住设备 BOOT 键，短按 RESET；看到进度开始后松开 BOOT。"
echo "请勿使用不稳定的 USB Hub，烧录期间不要拔线。"
echo
"$tool" burn "$firmware" --port-type usb --chip ec618

echo "烧录命令已完成，等待设备重启并验证短信桥接（最长 45 秒）……"
for _ in $(seq 1 15); do
  if python3 "$project_dir/scripts/verify-bridge-native.py"; then
    echo "成功：固件已烧录，VUART 与设备身份响应正常。"
    exit 0
  fi
  sleep 3
done
echo "烧录完成但未检测到桥接响应。请重新插拔设备后运行 scripts/verify-bridge-native.py。" >&2
exit 1
