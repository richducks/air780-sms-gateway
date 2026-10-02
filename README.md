# Air780 USB 短信网关

当前开发验收版本：**v1.3.0-rc2**（桥接固件仍为 v1.2.1；本次主要增强网关可靠性和可验证性）。

Air780 / YN076 USB 模块的自托管短信网关。设备端使用 LuatOS 短信接口和 USB VUART 与 Python 服务通信；服务通过 Vue 网页和 HTTP API 管理短信。支持多设备、会话式回复、通讯录、收藏、黑名单、设备备注、管理员分配 API 凭据、飞书与钉钉机器人，以及可手动开启的 4G 备用数据网络。

黑名单号码发来的新短信会单独归档，不出现在普通会话中，也不会发送到飞书、钉钉或通用 Webhook。移出黑名单后，已经归档的历史短信仍保留。

## 快速部署

在实际连接 Air780 的 Linux 主机上安装 Docker 和 Compose，先阅读 [Docker 部署说明](docs/DOCKER_DEPLOYMENT.md)，尤其是插入模块前的网络保护步骤。PVE 虚拟机部署需要把 USB 模块直通给运行容器的虚拟机。

```bash
cp .env.docker.example .env.docker
./scripts/generate-api-credentials.sh
# 把新生成的凭据填入 .env.docker，并为 admin 设置独立强密码
./scripts/install-host-network-guard.sh
./scripts/docker-deploy.sh
```

打开 `http://服务器IP:8787/`，在设置页填入 `.env.docker` 中的 API Token。管理员初始用户名和密码均为 `admin`；首次登录后请立即在设置页改为独立的强密码。服务使用 SQLite 保存短信、联系人及配置，Docker 卷用于持久化。备份方法见部署说明。

**请勿将 `.env`、`.env.docker`、短信数据库、真实手机号或机器人 Hook 提交到 GitHub。** 默认 Compose 使用 `privileged: true` 支持 USB 热插拔，只适合可信的专用主机；固定设备可按部署文档缩小权限。公网使用时应通过 HTTPS 反向代理或 VPN 访问。

## 一键升级

本项目已经支持通过 GitHub Container Registry（GHCR）直接拉取最新 Docker 镜像。目标服务器正常情况下不需要重新安装 Python、Node.js，也不需要手工重新编译前后端。

默认镜像：

```text
ghcr.io/richducks/air780-sms-gateway:latest
```

### 1. 日常升级：只需要一条命令

如果这台服务器已经使用当前版本的项目文件部署过，进入项目目录后执行：

```bash
bash scripts/docker-update.sh
```

例如项目目录是：

```text
/home/ubuntu/air780-sms-gateway
```

则执行：

```bash
cd /home/ubuntu/air780-sms-gateway
bash scripts/docker-update.sh
```

升级脚本会自动完成：

1. 检查 Docker 是否已经安装；
2. 检查 `docker compose` 是否可用；
3. 检查 `.env.docker` 是否存在；
4. 从 GHCR 拉取最新 `air780-sms-gateway` 镜像；
5. 使用新镜像重新创建并启动容器；
6. 等待容器健康检查；
7. 成功后显示当前容器状态；
8. 如果启动失败或变成 `unhealthy`，自动输出最近的容器日志。

正常完成时会看到类似：

```text
准备升级 Air780 短信网关
镜像: ghcr.io/richducks/air780-sms-gateway:latest
数据卷 sms-data 不会被删除。
升级完成，容器状态: healthy
```

### 2. 老版本第一次切换到一键升级

如果服务器是在加入远程 Docker 镜像升级功能之前部署的，旧机器上的 `compose.yaml` 和 `scripts/docker-update.sh` 可能还是旧版本，甚至没有升级脚本。

这种情况下第一次要先同步项目文件：

```bash
cd /你的目录/air780-sms-gateway
git pull --ff-only
bash scripts/docker-update.sh
```

例如：

```bash
cd /home/ubuntu/air780-sms-gateway
git pull --ff-only
bash scripts/docker-update.sh
```

第一次切换成功以后，日常升级通常只需要：

```bash
bash scripts/docker-update.sh
```

> `docker-update.sh` 负责升级 Docker 镜像和容器，本身不会执行 `git pull`。如果以后仓库里的 `compose.yaml`、升级脚本或宿主机部署配置发生变化，应先执行一次 `git pull --ff-only`，再运行升级脚本。

### 3. 不使用脚本，直接用 Docker 命令升级

如果希望完全使用 Docker 命令，也可以执行：

```bash
cd /你的目录/air780-sms-gateway
docker compose pull sms-gateway
docker compose up -d --no-build --force-recreate sms-gateway
```

其过程是：

```text
docker compose pull
        ↓
从 GHCR 下载最新镜像
        ↓
docker compose up -d --no-build --force-recreate
        ↓
使用新镜像替换旧容器并后台启动
```

这里使用 `--no-build` 很重要，它表示直接使用已经发布到 GHCR 的镜像，不在目标服务器重新执行 Dockerfile 构建。

### 4. 固定到指定版本

如果生产环境不希望跟随 `latest`，可以明确指定版本。

例如升级并固定为 `v1.2.1`：

```bash
AIR780_IMAGE=ghcr.io/richducks/air780-sms-gateway:v1.2.1 \
  bash scripts/docker-update.sh
```

这样即使以后 `latest` 已经升级到更高版本，本次运行仍会使用 `v1.2.1`。

正式发布版本可以在本仓库的 GitHub Releases 页面查看。

### 5. 升级后确认是否成功

先看容器状态：

```bash
docker compose ps
```

正常情况下 `air780-sms-gateway` 应为 `Up`，健康状态最终应为 `healthy`。

然后检查健康接口：

```bash
curl http://127.0.0.1:8787/health
```

当前版本正常会返回类似：

```json
{
  "ok": true,
  "version": "1.3.0-rc2",
  "online_devices": 2,
  "modem_connected": true
}
```

字段含义：

- `ok: true`：网关 Web 服务本身正常；
- `version`：当前实际运行的网关版本；
- `online_devices`：当前在线 Air780 设备数量；
- `modem_connected`：是否至少有一台 Air780 已连接。

两块 Air780 的当前生产验收标准是：Linux 能看到 2 个 `19d1:0001` USB 设备、通常出现 6 个 `ttyACM`，并且 `/health` 返回 `online_devices: 2`。v1.3.0-rc2 起，多设备发现按物理 USB 分组，只打开每块模块的短信 VUART，改善 USB 重连后的双设备自动恢复。

只看到 `ok: true` 不代表 USB 模块一定在线，还要同时检查 `online_devices` 和 `modem_connected`。

### 5.1 v1.3.0-rc1 起提供的发送重试

借鉴成熟短信网关常见的失败重试设计，网关现在会在一次短信发送发生临时串口/模块错误时自动重试，默认最多 **3 次**。可通过环境变量调整：

```bash
SMS_GATEWAY_SEND_ATTEMPTS=3
```

该机制只处理一次已入队消息的短暂发送失败，不会无限重试；达到上限后消息仍会明确标记为 `failed` 并记录最后一次错误，便于排查。

### 6. 升级异常时怎么看日志

先查看容器状态：

```bash
docker compose ps
```

查看最近 100 行日志：

```bash
docker compose logs --tail=100 sms-gateway
```

持续观察日志：

```bash
docker compose logs -f sms-gateway
```

退出实时日志：

```text
Ctrl + C
```

### 7. 升级会不会丢短信和配置

正常升级不会删除短信数据库。

Compose 使用 Docker 命名卷：

```text
sms-data
```

数据库在容器内保存为：

```text
/data/sms_gateway.db
```

其中包含短信、联系人、黑名单、设备信息、管理员密码哈希、API 凭据和飞书/钉钉配置等数据。重新拉取镜像、删除旧容器并重新创建容器，不会自动删除该数据卷。

**不要为了升级执行：**

```bash
docker compose down -v
```

其中 `-v` 会删除 Docker 数据卷，可能导致短信和配置丢失。

重要服务器仍建议升级前先备份数据库，完整备份步骤见 [Docker 部署说明](docs/DOCKER_DEPLOYMENT.md)。

### 8. 最后只记住这两条

普通日常升级：

```bash
cd /你的目录/air780-sms-gateway && bash scripts/docker-update.sh
```

项目文件也需要同步时：

```bash
cd /你的目录/air780-sms-gateway && git pull --ff-only && bash scripts/docker-update.sh
```

## 固件与硬件

本仓库提供 `firmware/bridge/main.lua` 桥接脚本，不再分发第三方 LuatOS Core、烧录工具或包含 Core 的 `.soc` 固件。请从合宙官方渠道获取与 Air780EPM 匹配的 Core 和烧录工具，并按 [设备烧录说明](docs/REPEATABLE_DEPLOYMENT.md) 构建和烧录。烧录需要接触设备的 BOOT/RESET 按键。4G 开关默认关闭；即使关闭数据网络，蜂窝信号仍应独立显示。有线网络保持优先，4G 不接管 DNS。

## API 与开发

接口定义在运行中的 `/api/v1/openapi.json`，健康检查为 `/health`。管理员可在设置页创建只读或读写 API 凭据、修改备注和撤销凭据，并可自行修改密码。详见 [API 接入说明](docs/API_INTEGRATION.md)。

```bash
python3 -m unittest discover -v
cd frontend && npm ci && npm run build
./scripts/verify-release.sh
```

## 文档

- [Docker 部署](docs/DOCKER_DEPLOYMENT.md)
- [Docker 小白部署与配置手册](docs/DOCKER_BEGINNER_GUIDE.md)
- [设备烧录与重复部署](docs/REPEATABLE_DEPLOYMENT.md)
- [API 接入](docs/API_INTEGRATION.md)
- [Linux 原生烧录](docs/LINUX_NATIVE_FLASH.md)

## 许可

见 `LICENSE`。
