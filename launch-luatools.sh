#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LANG=zh_CN.UTF-8
export LC_ALL=zh_CN.UTF-8
export WINEDEBUG=-all

exec wine "$project_dir/tools/Luatools_v3.exe"
