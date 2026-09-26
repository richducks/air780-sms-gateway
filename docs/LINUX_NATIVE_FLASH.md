# Linux 原生命令行烧录

本方案不使用 Wine 或 Luatools 图形界面。烧录包固定携带经过本机实测的 `luatos-tools` Linux x86-64 原生程序、已验证固件、基础 Core、Lua 源码和 SHA-256 校验值。脚本按二进制哈希锁定工具，不依赖文件夹中的版本名称。

## 支持环境

- Linux x86-64（Ubuntu 22.04/24.04、Debian 系发行版优先）；
- 具有数据传输能力的 USB 线；
- 普通用户具有 `dialout` 权限；
- 系统包含 `libudev.so.1`、Python 3 和 `lsusb`。

ARM64、Windows 和 macOS 不可使用本压缩包中的 x86-64 二进制。

## 首次准备

解压后先运行：

```bash
./scripts/install-flash-prerequisites.sh
```

脚本会安装运行依赖、加入 `dialout`、安装串口规则，并阻止 Air780 RNDIS 网卡抢占服务器默认路由。完成后重启电脑或注销并重新登录。

## 烧录

```bash
./scripts/flash-portable.sh
```

按提示操作设备：按住 BOOT，短按 RESET，看到烧录进度后松开 BOOT。脚本会先校验工具和固件哈希，再执行完整烧录，最后自动扫描串口、发送 JSON `ping` 并验证项目标识与 IMEI 响应。

## 单独验证

验证程序仅使用 Python 标准库，不需要安装 pyserial：

```bash
python3 scripts/verify-bridge-native.py
./scripts/check-host-network.sh
```

成功结果应包含 `"ok": true`、VUART 串口和 `air780_usb_sms_bridge`。

## 重新构建固件

包内包含基础 Core 与 Lua 源码。修改 `firmware/bridge/main.lua` 后运行：

```bash
./scripts/build-firmware.sh
```

注意：重新构建后固件哈希会变化，`flash-portable.sh` 的发布哈希保护会拒绝烧录。开发阶段可使用原 `flash-device.sh`；正式分发前应重新确认固件并更新发布脚本中的 SHA-256。

## 常见问题

- 找不到设备：更换支持数据的 USB 线，直接连接电脑 USB 口，避免 Hub。
- 没有权限：确认重新登录后 `groups` 包含 `dialout`。
- 串口被占用：停止短信网关容器、ModemManager 或其他串口软件后重试。
- 烧录中断：保持稳定供电，重新进入 BOOT 下载模式后再次完整烧录。
- 烧录成功但验证失败：等待 20 秒后重新插拔，再运行验证脚本；同时检查是否刷错 Air780 型号。
