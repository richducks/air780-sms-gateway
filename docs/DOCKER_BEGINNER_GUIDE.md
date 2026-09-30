# Air780 短信网关：Docker 小白部署与配置手册

> 目标：即使没有 Docker 使用经验，也能知道“这个项目用了什么、怎么启动、从哪里访问、账号密码在哪、每个配置项怎么改、数据存在哪里、出问题去哪里看”。

## 1. 这套系统到底是什么

Air780 短信网关由 4 个主要部分组成：

1. **网页管理端**：Vue 3 编写，Vite 构建。浏览器访问即可使用。
2. **后端服务**：Python 3.13，负责 HTTP API、管理员登录、短信收发、联系人、黑名单、飞书/钉钉通知等。
3. **串口通信**：Python `pyserial 3.5`，通过 Linux 的 `/dev/ttyACM*` 与 Air780 模块通信。
4. **数据存储**：SQLite，数据库在容器内路径 `/data/sms_gateway.db`，通过 Docker 卷持久化，所以重建容器不会丢数据。

Docker 镜像分两阶段构建：Node.js 22 Alpine 负责生成网页静态文件，最终运行镜像使用 Python 3.13 slim。正常运行时不需要单独启动 Node.js。

## 2. 当前项目目录

项目目录：

```bash
/home/sducks/Documents/CodexProjects/air780-sms-gateway
```

进入项目：

```bash
cd /home/sducks/Documents/CodexProjects/air780-sms-gateway
```

重要文件：

| 文件 | 作用 |
| --- | --- |
| `compose.yaml` | Docker Compose 主配置，定义容器、端口、数据卷和 USB 权限 |
| `Dockerfile` | 构建镜像 |
| `.env.docker` | **当前机器真实运行配置，包含密码和 Token，不提交 Git** |
| `.env.docker.example` | 配置模板，不含真实密码 |
| `LOCAL_DEPLOYMENT.md` | **当前机器的本地账号和密钥清单，不提交 Git** |
| `docs/DOCKER_DEPLOYMENT.md` | 较偏运维的 Docker 部署说明 |
| `docs/DOCKER_BEGINNER_GUIDE.md` | 本文，小白手册 |
| `scripts/docker-deploy.sh` | 一键构建并启动 |
| `scripts/install-host-network-guard.sh` | 防止 Air780 的 RNDIS 网卡抢走服务器默认路由/DNS |

## 3. 当前访问方式和账号

默认服务端口：

```text
8787
```

同一台电脑访问：

```text
http://127.0.0.1:8787/
```

局域网其他电脑访问：

```text
http://这台Ubuntu电脑的IP:8787/
```

管理员用户名固定为：

```text
admin
```

**当前机器实际管理员初始密码、API Token、Webhook Secret 不写入 Git 文档。** 请查看：

```bash
cat /home/sducks/Documents/CodexProjects/air780-sms-gateway/LOCAL_DEPLOYMENT.md
```

也可以只查看管理员密码：

```bash
grep '^SMS_GATEWAY_ADMIN_PASSWORD=' /home/sducks/Documents/CodexProjects/air780-sms-gateway/.env.docker
```

查看 API Token：

```bash
grep '^SMS_GATEWAY_API_TOKEN=' /home/sducks/Documents/CodexProjects/air780-sms-gateway/.env.docker
```

这样设计是故意的：账号密码必须能找到，但不能跟代码一起上传 GitHub。

## 4. 第一次启动

### 4.1 确认 Docker 已安装

```bash
docker --version
docker compose version
```

两条命令都能显示版本号，才算正常。

### 4.2 确认宿主机网络保护

Air780 除短信串口外，还可能出现 RNDIS 4G 网卡。如果 Linux 自动给它获取 DHCP、默认路由或 DNS，可能导致原来的有线/Wi-Fi 网络异常。

第一次部署执行：

```bash
cd /home/sducks/Documents/CodexProjects/air780-sms-gateway
./scripts/install-host-network-guard.sh
```

当前机器已安装过时不需要重复处理。

### 4.3 启动容器

```bash
cd /home/sducks/Documents/CodexProjects/air780-sms-gateway
docker compose up -d --build
```

说明：

- `docker compose`：使用当前目录的 `compose.yaml`。
- `up`：创建并启动服务。
- `-d`：后台运行，不占用终端。
- `--build`：如果代码有变化，先重新构建镜像。

查看状态：

```bash
docker compose ps
```

正常情况应看到 `air780-sms-gateway` 为 `Up`，健康检查最终为 `healthy`。

## 5. 平时最常用的 Docker 命令

启动：

```bash
docker compose up -d
```

停止：

```bash
docker compose down
```

停止但不删除容器：

```bash
docker compose stop
```

重新启动：

```bash
docker compose restart
```

查看状态：

```bash
docker compose ps
```

实时查看日志：

```bash
docker compose logs -f sms-gateway
```

退出日志查看按：

```text
Ctrl + C
```

修改代码后重新构建并启动：

```bash
docker compose up -d --build
```

## 6. `.env.docker` 每一个配置是什么意思

真实配置文件：

```bash
nano /home/sducks/Documents/CodexProjects/air780-sms-gateway/.env.docker
```

保存：`Ctrl + O`，回车；退出：`Ctrl + X`。

配置项说明：

| 配置项 | 当前用途 | 建议 |
| --- | --- | --- |
| `SMS_GATEWAY_HOST` | 后端监听地址 | Docker 中保持 `0.0.0.0` |
| `SMS_GATEWAY_PORT` | 服务端口 | 默认 `8787` |
| `SMS_GATEWAY_API_TOKEN` | HTTP API 的主读写 Token | 必须使用长随机值，不要公开 |
| `SMS_GATEWAY_ADMIN_PASSWORD` | 管理员 `admin` 的初始密码 | 必须使用强密码 |
| `SMS_GATEWAY_WEBHOOK_URL` | 通用 Webhook 地址 | 不需要可留空 |
| `SMS_GATEWAY_WEBHOOK_SECRET` | 通用 Webhook 签名密钥 | 即使暂时不用，也建议保留随机值 |
| `SMS_GATEWAY_FEISHU_WEBHOOK_URL` | 旧版单飞书机器人地址 | 可留空，推荐登录网页后配置多个机器人 |
| `SMS_GATEWAY_DB` | SQLite 文件位置 | Docker 中保持 `/data/sms_gateway.db` |
| `SMS_GATEWAY_SERIAL_PORT` | Air780 串口 | 建议 `auto`，自动识别多设备 |
| `SMS_GATEWAY_SERIAL_BAUDRATE` | 串口波特率 | 默认 `115200` |
| `SMS_GATEWAY_POLL_SECONDS` | 轮询间隔 | 默认 `3` 秒 |
| `SMS_GATEWAY_DELETE_AFTER_RECEIVE` | 从模块读到短信后是否删除模块内副本 | 默认 `true` |

修改 `.env.docker` 后必须重建/重启容器才能使环境变量生效：

```bash
docker compose up -d --force-recreate
```

## 7. “管理员密码”和“API Token”不是一回事

这两个经常被混淆：

- **管理员用户名/密码**：给人登录网页管理功能使用。用户名固定为 `admin`。
- **API Token**：给网页业务请求、脚本、其他系统调用 HTTP API 使用，请求头形式是 `Authorization: Bearer <Token>`。

管理员登录成功后会得到临时管理会话，默认有效 8 小时。

如果在网页中修改管理员密码，新密码会使用 PBKDF2-SHA256 哈希保存到 SQLite，不会明文写回 `.env.docker`。此后数据库中的新密码优先于 `.env.docker` 的初始密码。

因此：**一旦你在网页里改过管理员密码，`.env.docker` 中看到的只能理解为“初始密码”，不再代表当前密码。**

## 8. 数据到底保存在哪里

Compose 定义了一个 Docker 命名卷：

```text
sms-data
```

容器内挂载到：

```text
/data
```

数据库：

```text
/data/sms_gateway.db
```

里面包含短信、联系人、黑名单、设备信息、管理员新密码哈希、API Key、飞书/钉钉配置等。

查看实际卷名：

```bash
docker volume ls | grep sms-data
```

不要执行下面这种带 `-v` 的删除操作，除非你明确要清空数据：

```bash
docker compose down -v
```

`-v` 会删除数据卷，这是危险操作。

## 9. 备份数据库

先停止业务写入：

```bash
docker compose stop sms-gateway
```

找出卷名：

```bash
docker volume ls | grep sms-data
```

假设卷名为 `air780_sms-data`，备份：

```bash
docker run --rm \
  -v air780_sms-data:/data \
  -v "$PWD":/backup \
  alpine \
  cp /data/sms_gateway.db /backup/sms_gateway.backup.db
```

再启动：

```bash
docker compose start sms-gateway
```

项目目录中会出现：

```text
sms_gateway.backup.db
```

它包含真实短信和配置，应当按敏感数据保护。

## 10. USB 和 Air780 设备

默认 `compose.yaml` 使用：

```yaml
privileged: true
```

原因是 Air780 一台设备会生成多个 `/dev/ttyACM*`，并且 USB 热插拔或设备数量变化会导致串口编号变化。

这种配置适合专用、可信的短信网关主机。不要把这个容器随便放在不可信的多租户服务器上。

检查宿主机是否看到串口：

```bash
ls -l /dev/ttyACM*
```

如果什么都没有，说明当前 Linux 没看到 Air780 串口。此时网页服务仍可以正常启动，但“设备”页面不会有在线短信模块，也无法实际收发短信。

检查 USB：

```bash
lsusb
```

如果是 PVE 虚拟机，必须先把 Air780 USB 设备直通给运行 Docker 的 Ubuntu 虚拟机。

## 11. 健康检查

浏览器访问：

```text
http://服务器IP:8787/health
```

或者：

```bash
curl http://127.0.0.1:8787/health
```

返回 JSON 且包含：

```json
{"ok": true}
```

表示 Web 服务正常。

注意：`ok: true` 只表示网关程序存活，不代表 Air780 一定在线。还要看 `online_devices` 和 `modem_connected`。

## 12. API 怎么调用

先读取 Token：

```bash
TOKEN=$(grep '^SMS_GATEWAY_API_TOKEN=' .env.docker | cut -d= -f2-)
```

查看设备：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8787/api/v1/devices
```

查看最近短信：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8787/api/v1/messages?limit=50'
```

OpenAPI 定义：

```text
http://服务器IP:8787/api/v1/openapi.json
```

更完整说明见 `docs/API_INTEGRATION.md`。

## 13. 修改管理员密码

建议首次登录后在网页设置中修改。

规则：

- 12 到 128 个字符；
- 不能与当前密码完全相同。

新密码存入 SQLite。忘记网页中修改后的密码时，仅修改 `.env.docker` **不会覆盖数据库里已经保存的密码哈希**。这种情况需要按恢复流程处理数据库中的 `admin_password_hash`，不要直接删除整个数据库，否则短信和联系人也会丢失。

## 14. 升级项目

升级前先备份数据库。

### 14.1 以后在别的电脑上升级：推荐方式

本项目会把 `main` 分支构建成 Docker 镜像：

```text
ghcr.io/richducks/air780-sms-gateway:latest
```

目标电脑只要已经完成过首次部署，以后不需要安装 Node.js、Python，也不需要重新编译代码。进入项目目录执行：

```bash
cd /你的目录/air780-sms-gateway
docker compose pull sms-gateway
docker compose up -d --no-build sms-gateway
```

为了更省事，可以直接执行：

```bash
bash scripts/docker-update.sh
```

这个脚本等价于“拉取最新版 → 替换旧容器 → 检查健康状态”。短信、联系人和网页设置都保存在 `sms-data` 数据卷里，不会因为升级容器而清空。

检查：

```bash
docker compose ps
docker compose logs --tail=100 sms-gateway
curl http://127.0.0.1:8787/health
```

### 14.2 当前开发电脑修改源码后升级

如果是你在当前电脑上改了项目代码，还没有发布远程镜像，则继续使用本地构建：

```bash
cd /home/sducks/Documents/CodexProjects/air780-sms-gateway
docker compose build --pull
docker compose up -d
```

确认正常后，可清理不再使用的旧镜像：

```bash
docker image prune
```

系统会再次确认，输入 `y` 才删除。

## 15. 最常见的故障判断

### 网页打不开

先看：

```bash
docker compose ps
```

再看日志：

```bash
docker compose logs --tail=200 sms-gateway
```

检查端口：

```bash
ss -lntp | grep 8787
```

### 容器一直 unhealthy

检查：

```bash
docker inspect --format '{{json .State.Health}}' air780-sms-gateway
```

再看容器日志。

### 网页能打开但没有 Air780 设备

宿主机执行：

```bash
ls -l /dev/ttyACM*
lsusb
```

如果没有 `/dev/ttyACM*`，问题发生在 USB 识别、直通、线材、供电或固件层，不是网页层。

### 插上 Air780 后服务器网络异常

执行：

```bash
./scripts/check-host-network.sh
ip route
```

主默认路由应继续走服务器原有有线/Wi-Fi，而不是 Air780 RNDIS 网卡。

## 16. 安全底线

1. 不要把 `.env.docker` 和 `LOCAL_DEPLOYMENT.md` 发到公开仓库。
2. 不要长期使用 `admin/admin`。
3. 8787 端口不要裸露到公网；远程访问优先 VPN，或至少使用 HTTPS 反向代理并配防火墙。
4. `privileged: true` 只用于可信的专用宿主机。
5. 定期备份 `sms_gateway.db`。
6. API Token 泄露后应立即更换 `.env.docker` 中的 Token，并重建容器。

## 17. 最短日常操作清单

以后正常使用基本只需要记住：

```bash
cd /home/sducks/Documents/CodexProjects/air780-sms-gateway

docker compose ps                         # 看状态
docker compose up -d                      # 启动
docker compose restart                    # 重启
docker compose logs -f sms-gateway        # 看实时日志
curl http://127.0.0.1:8787/health         # 看程序是否存活
cat LOCAL_DEPLOYMENT.md                    # 查本机账号和密钥
```

如果网页正常但不能收发短信，第一件事不是重装 Docker，而是检查 `/dev/ttyACM*` 是否存在。
