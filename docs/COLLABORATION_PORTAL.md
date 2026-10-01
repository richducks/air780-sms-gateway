# 钉钉 / 飞书 / 企业微信团队看板接入

Air780 提供独立的只读团队看板：

```text
https://你的域名/portal.html
```

团队看板只展示设备在线状态、最近消息数量、发送成功率、失败/排队数量、最近脱敏动态和通知通道数量。它**不返回手机号、短信正文、IMEI、Webhook 地址、API Token，也不提供发送或修改操作**。

## 部署前提

1. Air780 网关需要有员工终端可访问的 HTTPS 地址。三家平台都更适合使用稳定域名，不建议把 `127.0.0.1`、局域网临时 IP 或带自签名证书的地址作为正式工作台入口。
2. 先在小范围成员中发布应用，确认手机端和桌面端都能访问，再扩大可见范围。
3. 本版团队看板是“应用主页接入”，不依赖平台 App Secret，因此可以先完成页面验证；后续如需识别具体员工，再增加三家平台的端内免登/SSO。

## 钉钉

创建企业内部应用并启用 H5 微应用，将应用首页配置为：

```text
https://你的域名/portal.html?platform=dingtalk
```

钉钉 H5 微应用可以进入工作台。后续需要免登时，可使用钉钉 `requestAuthCode` 获取端内免登授权码，再由服务端换取用户身份。

## 飞书

创建企业自建应用并启用“网页应用”，将移动端主页和桌面端主页配置为：

```text
https://你的域名/portal.html?platform=feishu
```

发布应用并设置可见范围即可从飞书工作台打开。后续如需员工身份识别，可继续配置网页应用重定向 URL，并接入飞书工作台免登。

## 企业微信

在企业微信管理后台创建“自建应用”，设置应用可见范围，并把“应用主页”配置为：

```text
https://你的域名/portal.html?platform=wecom
```

如后续需要 OAuth/JS-SDK，需要在“网页授权及 JS-SDK”里配置可信域名。建议正式上线时同时配置企业可信 IP。

## 验证

浏览器直接访问以下地址可以分别模拟三个入口：

```text
http://127.0.0.1:8787/portal.html?platform=dingtalk
http://127.0.0.1:8787/portal.html?platform=feishu
http://127.0.0.1:8787/portal.html?platform=wecom
```

接口验证：

```bash
curl http://127.0.0.1:8787/api/v1/portal/summary
```

返回结果应该只有脱敏的统计、设备展示名和运行状态，不应包含 `phone`、`body`、`imei`、Webhook URL 或 Token。
