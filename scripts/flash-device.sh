#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tool="$project_dir/tools/luatos-tools-v0.3.0/luatos-tools-v0.3.0-x86_64-unknown-linux-gnu/luatos-tools"
firmware="$project_dir/firmware/air780_usb_sms_bridge.soc"

if [[ ! -f "$firmware" ]]; then
    "$project_dir/scripts/build-firmware.sh"
fi

echo "Waiting for Air780 download mode."
echo "Hold BOOT and briefly press RESET. Release BOOT after progress starts."
exec "$tool" burn "$firmware" --port-type usb

