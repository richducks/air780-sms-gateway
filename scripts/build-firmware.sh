#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tool="$project_dir/tools/luatos-tools-v0.3.0/luatos-tools-v0.3.0-x86_64-unknown-linux-gnu/luatos-tools"
core="$project_dir/tools/LuatOS-SoC_V2044_Air780EPM_106.soc"
source_dir="$project_dir/firmware/bridge"
output="$project_dir/firmware/air780_usb_sms_bridge.soc"

if [[ ! -x "$tool" ]]; then
    echo "Missing Linux flashing tool: $tool" >&2
    exit 1
fi

"$tool" pack "$source_dir" -i "$core" -o "$output"
sha256sum "$output"
echo "Built: $output"

