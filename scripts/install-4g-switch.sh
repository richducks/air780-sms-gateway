#!/usr/bin/env bash
set -euo pipefail
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! systemctl is-active --quiet systemd-networkd; then
  echo "4G 开关需要 systemd-networkd。" >&2
  exit 1
fi
sudo install -m 0755 "$project_dir/scripts/air780-4g-agent.py" /usr/local/libexec/air780-4g-agent.py
monitor_tool="$project_dir/tools/luatos-tools-v0.3.0/luatos-tools-v0.3.0-x86_64-unknown-linux-gnu/luatos-tools"
if [ ! -x "$monitor_tool" ]; then
  monitor_tool="$project_dir/flash/luatos-tools"
fi
if [ -x "$monitor_tool" ]; then
  sudo install -m 0755 "$monitor_tool" /usr/local/libexec/air780-luatos-tools
fi
sudo install -m 0644 "$project_dir/deploy/air780-4g-agent.service" /etc/systemd/system/air780-4g-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now air780-4g-agent.service
sudo systemctl restart air780-4g-agent.service
sudo systemctl is-active air780-4g-agent.service
