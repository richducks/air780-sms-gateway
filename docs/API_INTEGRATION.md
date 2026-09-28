# 多设备 API 与钉钉/飞书接入

## 1. 获取 API 凭证

在项目目录运行：

```bash
./scripts/generate-api-credentials.sh
```

把输出的两行分别写入 `.env`，不要把 `.env`、Token 或 Webhook Secret 提交到代码仓库。重启网关后，调用方使用请求头：

```text
Authorization: Bearer <SMS_GATEWAY_API_TOKEN>
```

OpenAPI 描述位于 `GET /api/v1/openapi.json`，可直接导入 Postman、Apifox 或后端代码生成器。

## 2. 多设备接口

- `GET /health`：在线数和掉线状态，无需鉴权。
- `GET /api/v1/devices`：设备清单；稳定标识是 `device_id=air780-<IMEI>`。
- `PATCH /api/v1/devices/{device_id}`：设置便于识别的 `label`。
- `GET /api/v1/messages?direction=inbound&device_id=...&limit=100`：统一收件箱，可按设备筛选。
- `POST /api/v1/messages`：发送短信；多台在线时必须传 `device_id`。
- `GET /api/v1/messages/{id}`：轮询 `queued / sent / failed` 状态。
- `GET /api/v1/contacts`：读取网关通讯录。
- `PUT /api/v1/contacts/{phone}`：以号码为索引保存姓名和详细备注，JSON 字段为 `name`、`note`。
- `DELETE /api/v1/contacts/{phone}`：删除联系人资料；历史短信保留。
- `GET /api/v1/blacklist`：读取黑名单及每个号码的已归档短信数量。
- `PUT /api/v1/blacklist/{phone}`：加入或更新黑名单号码，JSON 字段为可选的 `label`、`note`。
- `DELETE /api/v1/blacklist/{phone}`：移出黑名单；已归档的黑名单短信保留。

发送示例：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/messages \
  -H "Authorization: Bearer $SMS_GATEWAY_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"air780-设备IMEI","phone":"目标手机号","body":"测试短信"}'
```

设备收到短信时，网关会向 `SMS_GATEWAY_WEBHOOK_URL` POST `sms.received` 事件；设备上线或掉线时还会发送 `device.online` / `device.offline`。事件包含稳定的 `device_id`。签名请求头是 `X-SMS-Timestamp` 与 `X-SMS-Signature`；算法为 `HMAC-SHA256(secret, timestamp + "." + 原始请求体)`。

## 3. 钉钉或飞书应用架构

推荐让钉钉/飞书应用的服务端调用本 API，不要从小程序或 H5 前端直接携带网关 Token：

```text
钉钉/飞书客户端 -> 应用服务端 -> HTTPS/VPN -> Ubuntu 短信网关 -> Air780
Air780 收信 -> Ubuntu 网关 -> 签名 Webhook -> 应用服务端 -> 钉钉/飞书消息
```

应用服务端需要实现三件事：

1. 保存用户与允许使用的 `device_id` 权限映射。
2. 代理发送、设备列表和收件箱接口；网关 Token 只存在服务端密钥配置中。
3. 接收 Webhook，校验签名及 5 分钟时间窗口，再调用钉钉/飞书开放平台的发消息接口。

钉钉或飞书云端无法访问 `127.0.0.1`。正式接入前，需要为这台 Ubuntu 提供一个受保护的公网 HTTPS 地址，或让应用服务端与 Ubuntu 处在同一 VPN。不要直接把 8787 端口裸露到公网；应使用 HTTPS 反向代理、IP/网络访问限制和独立 Token。

当前 `SMS_GATEWAY_WEBHOOK_URL` 是发给你自己的应用服务端，并不是直接填写群机器人地址：两种平台的机器人消息体格式不同，应由应用服务端完成转换和用户权限校验。

如果只需要把收信、发送结果和设备掉线通知推送到群聊，可以在管理页“设置”中分别添加飞书或钉钉自定义机器人。机器人 Webhook 地址和钉钉加签密钥保存在网关本机数据库中，页面只返回遮盖后的地址。飞书也支持单个环境变量配置：

```env
SMS_GATEWAY_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的Hook
```

机器人启用后会自动发送以下事件：

- `📩 收到短信`：设备、号码、内容和时间；
- `✅/❌ 短信发送成功/失败`：设备、号码、状态和错误；
- `🟢/🔴 设备上线/掉线`：设备标识和掉线原因。

黑名单号码的入站短信是例外：网关仍会把短信写入本地数据库并标记为 `blacklisted`，但不会调用通用 Webhook、飞书机器人或钉钉机器人。

自定义机器人 Hook 是单向入口，不能让网关读取群聊消息。若需要在群里发送命令来代发短信，必须另外创建平台应用和服务端，处理消息事件并校验用户与设备权限。

平台配置可从官方入口开始：[钉钉应用与机器人教程](https://open.dingtalk.com/tutorial/)、[钉钉自定义机器人接入](https://open.dingtalk.com/document/orgapp/custom-robot-access)、[飞书开放平台](https://open.feishu.cn/)。

## 4. 移动端管理页

手机与 Ubuntu 在同一可信网络时，把 `.env` 中的 `SMS_GATEWAY_HOST` 设置为 `0.0.0.0`、配置强 Token 并重启服务，然后浏览器打开 `http://<Ubuntu局域网IP>:8787/`。在“设置 → API 配置”中保存并启用 Token。页面按设备与号码显示短信会话，支持直接回复和指定设备发送。

跨互联网使用该页面时同样必须启用 HTTPS。生产环境建议由你的钉钉/飞书应用服务端提供页面和登录态，只把本页面作为局域网运维入口。
# 网页功能

- `PATCH /api/v1/messages/{id}/favorite`：请求体 `{"favorite": true|false}`，收藏或取消收藏单条短信。
- `GET /api/v1/network/4g`：读取 Air780 数据网卡开关和地址状态。
- `PUT /api/v1/network/4g`：请求体 `{"enabled": true|false, "interface": "eth0"}`，通过宿主机控制服务切换指定 Air780 的 4G 备用网络；省略 `interface` 时切换全部。支持 NetworkManager 和 `systemd-networkd`；首次安装需运行 `scripts/install-4g-switch.sh`。

## 管理员与独立 API 凭据

在 `.env.docker` 设置 `SMS_GATEWAY_ADMIN_PASSWORD` 后，使用设置页的 `admin` 账号登录。
管理员可为不同程序创建带备注的独立 Bearer 凭据，选择“只读”或“读写”，并随时改备注、撤销。
新凭据仅在创建时显示一次，服务器只保存其 SHA-256 摘要。原有 `SMS_GATEWAY_API_TOKEN` 仍可继续使用。
只读凭据允许 GET 查询；写操作（发送短信、管理联系人或机器人、切换 4G 等）返回 HTTP 403。

管理员接口：
- `POST /api/v1/admin/login`：提交 `{"username":"admin","password":"..."}`，获取 8 小时会话。
- `GET /api/v1/admin/keys`：列出凭据及备注，不返回密钥。
- `POST /api/v1/admin/keys`：提交 `{"label":"用途","scope":"read"}` 或 `write`，仅在响应中返回一次 `token`。
- `PATCH /api/v1/admin/keys/{id}`：修改备注。
- `DELETE /api/v1/admin/keys/{id}`：立即撤销凭据。
- `PUT /api/v1/admin/password`：使用管理员会话提交 `{"current_password":"...","new_password":"..."}`；新密码为 12–128 个字符。修改后所有管理员会话立即失效，需重新登录。密码摘要保存在网关数据库，优先于初始环境变量。

除登录外，管理员接口使用 `X-Admin-Session` 请求头；普通 API 仍使用 `Authorization: Bearer <token>`。
