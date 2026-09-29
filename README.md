# Air780 USB 短信网关

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

## 固件与硬件

本仓库提供 `firmware/bridge/main.lua` 桥接脚本，不再分发第三方 LuatOS Core、烧录工具或包含 Core 的 `.soc` 固件。请从合宙官方渠道获取与 Air780EPM 匹配的 Core 和烧录工具，并按 [设备烧录说明](docs/REPEATABLE_DEPLOYMENT.md) 构建和烧录。烧录需要接触设备的 BOOT/RESET 按键。4G 开关默认关闭；即使关闭数据网络，蜂窝信号仍应独立显示。有线网络保持优先，4G 不接管 DNS。

## API 与开发

接口定义在运行中的 `/api/v1/openapi.json`，健康检查为 `/health`。管理员可在设置页创建只读或读写 API 凭据、修改备注和撤销凭据，并可自行修改密码。详见 [API 接入说明](docs/API_INTEGRATION.md)。

```bash
python3 -m unittest discover -v
cd frontend && npm ci && npm run build
```

## 文档

- [Docker 部署](docs/DOCKER_DEPLOYMENT.md)
- [Docker 小白部署与配置手册](docs/DOCKER_BEGINNER_GUIDE.md)
- [设备烧录与重复部署](docs/REPEATABLE_DEPLOYMENT.md)
- [API 接入](docs/API_INTEGRATION.md)
- [Linux 原生烧录](docs/LINUX_NATIVE_FLASH.md)

## 许可

见 `LICENSE`。
