#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
echo "安装前默认路由："
ip route show default || true
sudo install -m 0644 "$project_dir/deploy/99-air780.rules" /etc/udev/rules.d/99-air780.rules
sudo udevadm control --reload-rules
if systemctl is-active --quiet NetworkManager && command -v nmcli >/dev/null 2>&1; then
  sudo install -m 0644 "$project_dir/deploy/99-air780-networkmanager.conf" /etc/NetworkManager/conf.d/99-air780-networkmanager.conf
  sudo install -m 0755 "$project_dir/deploy/90-air780-network-guard" /etc/NetworkManager/dispatcher.d/90-air780-network-guard
  sudo systemctl reload NetworkManager 2>/dev/null || sudo systemctl restart NetworkManager
  for device_path in /sys/class/net/*; do
    interface=$(basename "$device_path")
    properties=$(udevadm info -q property -p "$device_path" 2>/dev/null || true)
    if grep -q '^ID_VENDOR_ID=19d1$' <<<"$properties" && grep -q '^ID_MODEL_ID=0001$' <<<"$properties"; then
      sudo nmcli device set "$interface" managed no || true
      sudo ip route del default dev "$interface" 2>/dev/null || true
      sudo ip -6 route del default dev "$interface" 2>/dev/null || true
      sudo resolvectl revert "$interface" 2>/dev/null || true
      echo "已隔离 Air780 数据网卡：$interface（短信串口不受影响）"
    fi
  done
elif systemctl is-active --quiet systemd-networkd; then
  sudo install -m 0644 "$project_dir/deploy/05-air780-rndis.network" /etc/systemd/network/05-air780-rndis.network
  sudo networkctl reload
  echo "已安装 systemd-networkd RNDIS 无 DHCP/路由规则。"
else
  echo "未检测到受支持的网络管理器；请先为 Air780 RNDIS 禁用 DHCP 和默认路由。" >&2
  exit 1
fi
# Re-apply the Air780 rules to devices that are already attached. Restart
# ModemManager afterwards so it drops any previously scheduled probe context and
# re-discovers the devices with ID_MM_DEVICE_IGNORE already present.
sudo udevadm trigger --subsystem-match=usb
sudo udevadm trigger --subsystem-match=tty
sudo udevadm trigger --subsystem-match=net
sudo udevadm settle
if systemctl is-active --quiet ModemManager; then
  sudo systemctl restart ModemManager
fi

echo "Air780 USB 电源策略："
for dev in /sys/bus/usb/devices/*; do
  [ -f "$dev/idVendor" ] || continue
  [ "$(cat "$dev/idVendor" 2>/dev/null):$(cat "$dev/idProduct" 2>/dev/null)" = "19d1:0001" ] || continue
  printf "%s control=%s autosuspend=%s\n" "$(basename "$dev")"     "$(cat "$dev/power/control" 2>/dev/null || echo unknown)"     "$(cat "$dev/power/autosuspend" 2>/dev/null || echo unknown)"
done

echo "安装后默认路由："
ip route show default || true
echo "完成。重新插拔 Air780 后运行 ./scripts/check-host-network.sh 验证。"
