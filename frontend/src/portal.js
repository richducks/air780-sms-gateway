import './portal.css'

const root = document.querySelector('#portal')
const params = new URLSearchParams(location.search)
const explicitPlatform = params.get('platform')
const ua = navigator.userAgent.toLowerCase()

function detectPlatform() {
  if (explicitPlatform) return explicitPlatform
  if (ua.includes('dingtalk')) return 'dingtalk'
  if (ua.includes('lark') || ua.includes('feishu')) return 'feishu'
  if (ua.includes('wxwork')) return 'wecom'
  return 'web'
}

const platform = detectPlatform()
const platformNames = { dingtalk: '钉钉', feishu: '飞书', wecom: '企业微信', web: '浏览器' }
const fmt = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const statusLabel = value => ({ sent:'已发送', delivered:'已通知', received:'已接收', failed:'发送失败', webhook_failed:'通知失败', queued:'排队中', blacklisted:'已拦截' }[value] || value || '未知')

function renderLoading() {
  root.innerHTML = `<section class="shell"><header><div><span class="eyebrow">AIR780 · ${platformNames[platform] || '工作台'}</span><h1>团队运行看板</h1><p>只读 · 已脱敏</p></div><span class="live muted">正在读取…</span></header><div class="loading">加载网关状态…</div></section>`
}

function render(data) {
  const m = data.messages || {}
  const devices = data.devices || []
  const recent = data.recent || []
  root.innerHTML = `<section class="shell">
    <header>
      <div><span class="eyebrow">AIR780 · ${platformNames[platform] || '工作台'}</span><h1>团队运行看板</h1><p>只读 · 不展示手机号、短信正文和密钥</p></div>
      <button id="refresh" class="refresh">刷新</button>
    </header>
    <div class="hero ${data.ok ? 'ok' : 'bad'}"><span class="dot"></span><div><strong>${data.ok ? '网关运行正常' : '网关状态异常'}</strong><small>版本 ${data.version || '-'}</small></div><b>${data.online_devices || 0}/${data.total_devices || 0} 在线</b></div>
    <div class="metrics">
      <article><small>最近消息</small><strong>${m.total ?? 0}</strong><span>最多统计 500 条</span></article>
      <article><small>发送成功率</small><strong>${m.success_rate ?? 100}%</strong><span>${m.outbound ?? 0} 条发送</span></article>
      <article><small>待处理</small><strong>${m.queued ?? 0}</strong><span>当前排队</span></article>
      <article><small>异常</small><strong class="${(m.failed || 0) ? 'danger' : ''}">${m.failed ?? 0}</strong><span>发送/通知失败</span></article>
    </div>
    <section class="panel"><div class="panel-head"><h2>设备</h2><span>${data.online_devices || 0} 台在线</span></div>
      <div class="device-list">${devices.length ? devices.map(item => `<div class="device"><span class="device-dot ${item.status === 'online' ? '' : 'off'}"></span><div><strong>${escapeHtml(item.label)}</strong><small>${item.firmware_version ? `固件 ${escapeHtml(item.firmware_version)} · ` : ''}${fmt(item.last_seen_at)}</small></div><span class="state ${item.has_error ? 'warn' : ''}">${item.has_error ? '有异常' : item.status === 'online' ? '在线' : '离线'}</span></div>`).join('') : '<div class="empty">暂无已登记设备</div>'}</div>
    </section>
    <section class="panel"><div class="panel-head"><h2>最近动态</h2><span>已脱敏</span></div>
      <div class="event-list">${recent.length ? recent.map(item => `<div class="event"><span class="event-icon">${item.direction === 'inbound' ? '↓' : '↑'}</span><div><strong>${item.direction === 'inbound' ? '收到短信' : '发送短信'}</strong><small>${escapeHtml(item.device)} · ${fmt(item.created_at)}</small></div><span class="state ${['failed','webhook_failed'].includes(item.status) ? 'warn' : ''}">${statusLabel(item.status)}</span></div>`).join('') : '<div class="empty">暂无消息记录</div>'}</div>
    </section>
    <section class="panel compact"><div class="panel-head"><h2>通知通道</h2></div><div class="integrations"><span>飞书 <b>${data.integrations?.feishu || 0}</b></span><span>钉钉 <b>${data.integrations?.dingtalk || 0}</b></span><span>企业微信 <b>应用入口</b></span></div></section>
    <footer>Air780 团队看板 · 页面每 30 秒自动刷新</footer>
  </section>`
  document.querySelector('#refresh')?.addEventListener('click', load)
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]))
}

async function load() {
  try {
    const response = await fetch('/api/v1/portal/summary', { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    render(await response.json())
  } catch (error) {
    root.innerHTML = `<section class="shell"><header><div><span class="eyebrow">AIR780</span><h1>团队运行看板</h1></div></header><div class="error"><strong>暂时无法读取网关</strong><span>${escapeHtml(error.message)}</span><button id="retry" class="refresh">重新加载</button></div></section>`
    document.querySelector('#retry')?.addEventListener('click', load)
  }
}

renderLoading()
load()
setInterval(load, 30000)
