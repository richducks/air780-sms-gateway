#!/usr/bin/env bash
set -euo pipefail
failed=0
echo "默认路由："
ip route show default || true
for device_path in /sys/class/net/*; do
  interface=$(basename "$device_path")
  properties=$(udevadm info -q property -p "$device_path" 2>/dev/null || true)
  if grep -q '^ID_VENDOR_ID=19d1$' <<<"$properties" && grep -q '^ID_MODEL_ID=0001$' <<<"$properties"; then
    state=$(nmcli -g GENERAL.STATE device show "$interface" 2>/dev/null || true)
    routes=$(ip route show dev "$interface" || true)
    echo "Air780 网卡：$interface；NetworkManager 状态：${state:-未知}"
    if grep -q '^default ' <<<"$routes"; then
      echo "错误：Air780 网卡仍持有默认路由。" >&2
      failed=1
    else
      echo "正常：该网卡没有默认路由。"
    fi
  fi
done
primary=$(ip route show default | grep -vE 'dev (enx|usb)' | head -n1 || true)
if [ -z "$primary" ]; then
  echo "警告：未确认到非 USB 的主默认路由，请检查服务器有线或 Wi-Fi。" >&2
  failed=1
else
  echo "主网络路由：$primary"
fi
exit "$failed"
