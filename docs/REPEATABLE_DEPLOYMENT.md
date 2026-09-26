# Air780 短信网关可复制部署方案

本文档是本项目的长期部署基线。新采购的 YN076 / Air780EPM 设备按本文操作，不依赖 Windows 或 Wine Luatools。

## 验证记录

- 验证日期：2026-09-23
- 设备：YN076 / Air780EPM，USB ID `19d1:0001`
- 固件：当时验证使用 `air780_usb_sms_bridge` v1.0.0；当前桥接源码已更新
- Ubuntu 接口：`/dev/ttyACM2`（实际编号可变，以握手探测为准）
- 入站短信：实机验证成功
- 出站中文短信：实机验证成功，设备约 3 秒返回发送成功
- 网络隔离：插入设备后默认路由仍为 Wi-Fi，OpenClash 不受影响
- 结论：单设备收发短信闭环验收通过

## 1. 已验证架构

```text
移动/联通/电信网络
        │
Air780EPM + SIM
  LuatOS sms API
        │ JSON Lines
  USB VUART (/dev/ttyACM*)
        │
Ubuntu sms_gateway
        ├── SQLite 短信记录
        ├── HTTP 发送/查询 API
        └── HMAC 签名 Webhook → 移动端/业务系统
```

设备固件不开放标准 `AT+CMGF/CMGL/CMGS`，因此不能使用传统 USB Modem AT 方案。正确方案是 LuatOS `sms` API + `uart.VUART_0`。

## 2. 固定版本

- 硬件：YN076 USB Dongle / Air780EPM
- USB ID：`19d1:0001`
- LuatOS Core：从合宙官方渠道获取与硬件匹配的版本
- 设备脚本：`firmware/bridge/main.lua`
- Linux 工具：`luatos-tools v0.3.0`
- 协议：UTF-8 JSON Lines，设备项目标识 `air780_usb_sms_bridge`

升级任何一项前，应保留当前可工作的固件并重新执行完整验收。

## 3. 新设备烧录

插入设备前关闭 Wine Luatools、ModemManager 探测程序和其他串口工具。

生成固件：

```bash
cd air780-sms-gateway
./scripts/build-firmware.sh
```

开始烧录：

```bash
./scripts/flash-device.sh
```

看到等待提示后：

1. 按住设备 BOOT；
2. 短按 RESET；
3. 进度开始后松开 BOOT；
4. 保持 USB 与供电稳定，直至所有区域显示 100%。

验证 VUART：

```bash
./scripts/check-device.sh
```

成功结果包含设备 IMEI、固件版本和实际串口。

## 4. Ubuntu 主机初始化

安装规则：

```bash
sudo cp deploy/99-air780.rules /etc/udev/rules.d/
sudo cp deploy/99-air780-networkmanager.conf /etc/NetworkManager/conf.d/
sudo udevadm control --reload-rules
sudo systemctl restart ModemManager NetworkManager
```

规则实现三件事：

1. 串口属于 `dialout`；
2. ModemManager 不探测和占用 Air780；
3. RNDIS 网卡不获取默认路由/DNS，不影响 Wi-Fi/OpenClash。

用户首次部署还需加入 `dialout`：

```bash
sudo usermod -aG dialout "$USER"
```

重启或重新登录后生效。

## 5. 网关配置与启动

```bash
cp .env.example .env
```

必须为生产环境设置：

- `SMS_GATEWAY_API_TOKEN`：HTTP API Bearer Token；
- `SMS_GATEWAY_WEBHOOK_URL`：业务系统收件回调；
- `SMS_GATEWAY_WEBHOOK_SECRET`：Webhook HMAC 密钥；
- `SMS_GATEWAY_DB`：持久化数据库绝对路径。

前台验收：

```bash
set -a
. ./.env
set +a
python3 -m sms_gateway
```

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

必须满足：`modem_connected=true`、设备项目为 `air780_usb_sms_bridge`、`last_error=null`。

## 6. 新设备验收清单

- `lsusb` 显示 `19d1:0001`；
- `./scripts/check-device.sh` 返回 `ok=true`；
- `ip route` 默认路由仍指向 Wi-Fi；
- 从手机向 SIM 发送 `AIR780_TEST`，API 能查询到正文与号码；
- API 向该号码回复，手机能收到；
- 拔插设备后网关可自动重连；
- 重启 Ubuntu 后 systemd 服务自动恢复；
- Webhook 签名在业务端验证成功。

## 7. 多设备扩展

单台主机接入多只 Air780 时，不要依赖易变化的 `/dev/ttyACM2` 编号。设备握手会返回 IMEI，应以 IMEI 作为永久设备 ID。

推荐生产模型：

- 一个主机守护进程扫描全部 ACM/USB 串口；
- 通过 JSON `ping/pong` 获取每台设备 IMEI；
- 数据表为每条短信记录 `device_id/imei`；
- 发送 API 必须指定 `device_id`；
- 每台设备独立发送队列、速率限制和健康状态；
- Webhook 携带 `device_id`，业务系统可识别 SIM/设备；
- 设备掉线不影响其他设备。

当前版本已支持多设备管理；增加设备后仍应分别完成收发、热插拔与重启验收。

## 8. 恢复与备份

- 第三方 LuatOS Core 与工具：请从合宙官方渠道下载
- 自定义桥接源码：`firmware/bridge/main.lua`
- 可烧录成品：由本地构建生成，不在本仓库分发
- 固件构建脚本：`scripts/build-firmware.sh`
- Linux 烧录脚本：`scripts/flash-device.sh`

禁止把真实 API Token、Webhook Secret 或短信数据库提交到代码仓库。
