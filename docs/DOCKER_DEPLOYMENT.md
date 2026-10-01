# Air780 短信网关 Docker 部署

Docker 镜像包含 Vue 3 管理页面、Python 多设备网关、SQLite 存储和飞书通知支持。固件烧录及宿主机网络规则不在容器内完成。

## 1. 宿主机准备

目标服务器需要是实际插入 Air780 USB 设备的 Linux 主机。先安装宿主机规则：

在插入 Air780 之前执行网络保护安装脚本：

```bash
./scripts/install-host-network-guard.sh
```

Air780 除串口外还会暴露 RNDIS 数据网卡。如果不隔离，NetworkManager 可能为它获取 DHCP、默认路由和 DNS，使服务器原有有线/Wi-Fi网络或代理失效。保护方案按 USB ID `19d1:0001` 和 `rndis_host` 驱动识别，不依赖当前机器的 `enx...` 网卡名，换 USB 口和接入多台设备仍然有效。

如需在网页“设备”中手动开启 4G 备用网络，在使用 NetworkManager 或 `systemd-networkd` 的宿主机上执行 `./scripts/install-4g-switch.sh`，然后重新运行 `docker compose up -d`。开关默认关闭；使用 NetworkManager 时可独立控制每台 Air780 的数据网卡。开启后使用 DHCP，但路由优先级低于主网络，并且不接管 DNS；关闭后恢复无 DHCP 的隔离配置。该开关由宿主机上的受限 Unix socket 服务执行，容器不能直接修改宿主机网络配置。

4G 信号格优先使用宿主机上的 LuatOS 只读监测工具从模块日志口取得 CSQ（0–31）。若安装包中没有监测工具，`install-4g-switch.sh` 会保留开关功能，但页面会显示“正在读取模块信号”。短信桥固件 v1.2.1 会在飞行模式下配置模块的 USB RNDIS NAT 数据共享，否则主机网卡可能出现“等待获取地址”；该固件也可直接上报 RSRP/CSQ。固件升级需在设备旁按 BOOT/RESET，见 `scripts/flash-device.sh` 和 `REPEATABLE_DEPLOYMENT.md`。升级固件不会自动开启宿主机的 4G 数据开关；有线网络仍为优先出口。

若页面显示“已开启 · 未连接”，先确认宿主机 `networkctl status <Air780网卡>` 是否正在请求 DHCP 地址。若日志中有 `DHCPv4 client: DISCOVER` 却始终无地址，说明主机已发出请求但模块未提供地址；本项目的 1.0.0 短信固件仅提供短信桥接，需要升级为带 RNDIS NAT 配置的固件。烧录时如果在 0% 报 `Serial write failed` 或 `Operation timed out`，先停止重试，检查 USB 数据线、供电和主机直连端口。若已自行下载匹配的 SOC 且 `luatos-tools` 仍超时，可使用合宙的 `luatos-cli` 仅更新脚本：`luatos-cli flash script --soc firmware/air780_usb_sms_bridge.soc --port auto --script firmware/bridge`。PVE 直通场景应在宿主机烧录，临时移除 VM 的 USB 直通，完成后按物理 USB 口重新直通。升级后验证 `/health` 的模块版本、4G 网卡地址、默认路由仍走原有网络，并从 4G 网卡访问公网。

若 Docker Hub 暂时不可用，而宿主机已有旧版 `air780-sms-gateway:local` 镜像，可在本地先执行 `cd frontend && npm ci && npm run build`，将更新后的项目文件（含 `frontend/dist`）复制到宿主机，再执行 `./scripts/offline-repackage.sh`。脚本会以现有镜像为基础封装新代码，无需访问 Docker Hub。

安装后插入设备并验证：

```bash
./scripts/check-host-network.sh
nmcli device
ip route
```

检查结果必须满足：主默认路由仍指向服务器原有的有线或 Wi-Fi；所有 Air780 RNDIS 接口为 `unmanaged`，且没有 `default` 路由。短信串口 `/dev/ttyACM*` 不受影响。

确认能看到 `/dev/ttyACM*`。设备仍需提前刷入本项目的桥接固件，参见 `REPEATABLE_DEPLOYMENT.md`。

安装脚本同时支持 NetworkManager 和 `systemd-networkd`。后者会安装 `deploy/05-air780-rndis.network`，禁止 RNDIS 获取 DHCP、IPv6 RA 和默认路由。若目标主机使用其他网络管理器，须先为 Air780 RNDIS 禁用 DHCP 和默认路由，再插入或直通设备。

## 2. 创建容器配置

```bash
cp .env.docker.example .env.docker
./scripts/generate-api-credentials.sh
chmod 600 .env.docker
```

把生成的 API Token 和 Webhook Secret 写入 `.env.docker`。不要把真实密钥提交到代码仓库。飞书 Hook 可以留空，启动后在网页“设置 → 飞书机器人”中维护多个带备注的机器人。

## 3. 构建和启动

可以直接使用一键部署脚本：

```bash
./scripts/docker-deploy.sh
```

也可以手动执行：

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f sms-gateway
```

浏览器访问 `http://服务器IP:8787/`，在设置页填入 `.env.docker` 中的 API Token。

短信页按设备与号码显示会话，可在底部直接回复；支持 Enter 发送、Shift+Enter 换行。通讯录可保存号码、姓名和详细备注，历史短信会立即显示联系人名称。设置页可配置多个飞书和钉钉群机器人。钉钉自定义机器人可选填以 `SEC` 开头的加签密钥。

SQLite 数据及网页保存的飞书机器人配置位于 Docker 命名卷 `sms-data`，重新构建或升级容器不会丢失。

## 4. USB 权限模式

默认 `compose.yaml` 使用 `privileged: true`，这是为了支持多套 Air780 动态增加、串口编号变化和运行时热插拔。只应在专用、可信的短信网关主机上使用。

若设备数量与端口固定，可删除 `privileged: true`，改为逐一映射实际使用的串口：

```yaml
devices:
  - /dev/ttyACM0:/dev/ttyACM0
  - /dev/ttyACM1:/dev/ttyACM1
  - /dev/ttyACM2:/dev/ttyACM2
group_add:
  - "20" # Ubuntu 的 dialout GID；用 getent group dialout 确认
```

固定映射模式增加设备或串口编号变化时，需要修改 Compose 并重建容器。

## 5. 迁移和备份

备份数据库：

```bash
docker compose stop sms-gateway
docker run --rm -v air780_sms-data:/data -v "$PWD":/backup alpine \
  cp /data/sms_gateway.db /backup/sms_gateway.backup.db
docker compose start sms-gateway
```

项目目录名不同会导致卷名前缀不同，可用 `docker volume ls` 查找以 `_sms-data` 结尾的卷。

在另一台服务器恢复时，先启动一次容器创建卷，再停止服务，并把备份复制到卷中的 `/data/sms_gateway.db`。数据库内包含短信、设备备注和飞书 Hook，应按敏感数据保护备份。

## 6. 升级

项目现在支持两种升级方式。

### 6.1 推荐：其他电脑直接拉取已发布镜像

默认镜像为：

```text
ghcr.io/richducks/air780-sms-gateway:latest
```

目标机已经完成首次部署后，以后升级只需要：

```bash
cd air780-sms-gateway
docker compose pull sms-gateway
docker compose up -d --no-build sms-gateway
```

也可以直接运行项目内的一键升级脚本：

```bash
bash scripts/docker-update.sh
```

脚本会拉取远程 `latest` 镜像、重建容器并检查健康状态。`sms-data` 命名卷不会被删除。

网关对单条短信的临时发送失败默认会自动重试 3 次。生产环境可在 `.env.docker` 中设置 `SMS_GATEWAY_SEND_ATTEMPTS=3` 调整次数；建议保持 2–3 次，不要设置过大，以免真实故障时长时间占用发送队列。

如需固定到某个版本，可先指定镜像标签，例如：

```bash
AIR780_IMAGE=ghcr.io/richducks/air780-sms-gateway:v1.2.3 bash scripts/docker-update.sh
```

### 6.2 本机源码开发/测试后重新构建

如果你改的是当前电脑上的源码，而不是使用 GitHub 发布镜像：

```bash
docker compose build --pull
docker compose up -d
```

GitHub `main` 分支更新后，`.github/workflows/docker-publish.yml` 会自动构建并发布 `latest`、Git 标签和提交 SHA 镜像。升级前仍建议先备份数据库。

## 7. 发布前验收

源码仓库新增统一验收入口：

```bash
./scripts/verify-release.sh
```

它会依次执行 Python 单元测试、前端锁定依赖构建、Docker Compose 配置解析，以及关键部署脚本的 Bash 语法检查。只有这些基础检查全部通过，才适合作为发布候选版本继续做真机短信收发验收。
