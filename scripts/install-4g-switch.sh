#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! systemctl is-active --quiet systemd-networkd && ! systemctl is-active --quiet NetworkManager; then
  echo "4G 开关需要 NetworkManager 或 systemd-networkd。" >&2
  exit 1
fi
sudo install -m 0755 "$project_dir/scripts/air780-4g-agent.py" /usr/local/libexec/air780-4g-agent.py
sudo install -m 0644 "$project_dir/deploy/99-air780.rules" /etc/udev/rules.d/99-air780.rules
sudo udevadm control --reload-rules
sudo install -m 0644 "$project_dir/deploy/air780-4g-agent.service" /etc/systemd/system/air780-4g-agent.service
if systemctl is-active --quiet NetworkManager; then
  sudo install -m 0644 "$project_dir/deploy/99-air780-networkmanager.conf" /etc/NetworkManager/conf.d/99-air780-networkmanager.conf
  sudo install -m 0755 "$project_dir/deploy/90-air780-network-guard" /etc/NetworkManager/dispatcher.d/90-air780-network-guard
fi
sudo systemctl daemon-reload
sudo systemctl enable --now air780-4g-agent.service
sudo systemctl restart air780-4g-agent.service
sudo systemctl is-active air780-4g-agent.service
