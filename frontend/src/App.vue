<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const view = ref('messages')
const navIds = ['messages','devices','contacts','favorites','ads','blacklist','settings']
const navLabels = {messages:'短信',devices:'设备',contacts:'通讯录',favorites:'收藏',ads:'广告',blacklist:'黑名单',settings:'设置'}
const navDescriptions = {messages:'查看和发送短信',devices:'管理短信设备和 4G 网络',contacts:'号码与备注',favorites:'保存的重要短信',ads:'自动识别的广告短信',blacklist:'拦截与归档',settings:'账号与界面偏好'}
const savedNavOrder = JSON.parse(localStorage.getItem('sms.navOrder') || '[]')
const navOrder = ref([...savedNavOrder.filter(id => navIds.includes(id)), ...navIds.filter(id => !savedNavOrder.includes(id))])
const navDragging = ref('')
const fourG = ref({available:false,enabled:false,interfaces:[]})
const fourGBusy = ref(false)
const fourGError = ref('')
const networkForDevice = device => fourG.value.interfaces?.find(item => item.device_id === device.device_id)
  || (devices.value.length === 1 && fourG.value.interfaces?.length === 1 ? fourG.value.interfaces[0] : null)
const sidebarWidth = ref(localStorage.getItem('sms.sidebarCollapsed') === 'true'
  ? 72
  : Number(localStorage.getItem('sms.sidebarWidth') || 200))
const sidebarCollapsed = computed(() => sidebarWidth.value < 120)
const messages = ref([])
const devices = ref([])
const contacts = ref([])
const blacklist = ref([])
const blacklistSearch = ref('')
const blacklistMatchFilter = ref('all')
const selectedConversationKey = ref(null)
const mobileConversationOpen = ref(false)
const deviceFilter = ref('all')
const loading = ref(false)
const error = ref('')
const userSession = ref(sessionStorage.getItem('sms.userSession') || '')
const currentUser = ref(null)
const isAdmin = computed(() => currentUser.value?.role === 'admin')
const authRequired = ref(!userSession.value)
const loginDraft = ref({username:'admin',password:''})
const loginError = ref('')
const composeOpen = ref(false)
const contactEditorOpen = ref(false)
const contactOriginalPhone = ref('')
const contactDraft = ref({phone:'',name:'',note:''})
const contactError = ref('')
const blacklistEditorOpen = ref(false)
const blacklistOriginalPhone = ref('')
const blacklistDraft = ref({phone:'',match_type:'exact',label:'',note:''})
const blacklistError = ref('')
const adRules = ref([])
const adRuleEditorOpen = ref(false)
const adRuleOriginalId = ref(null)
const adRuleDraft = ref({pattern:'',match_type:'contains',field:'body',label:'',enabled:true})
const adRuleError = ref('')
const adSearch = ref('')
const chatDrafts = ref({})
const chatSending = ref(false)
const chatError = ref('')
const chatHistory = ref(null)
const editingDevice = ref(null)
const deviceLabel = ref('')
const integrations = ref({webhooks:[]})
const hookDraft = ref({label:'', webhook_url:''})
const dingtalkIntegrations = ref({webhooks:[]})
const dingtalkDraft = ref({label:'', webhook_url:'', secret:''})
const savedNotice = ref('')
const settingsSection = ref(localStorage.getItem('sms.settingsSection') || 'general')
const settingsSections = [
  {id:'general', label:'通用', description:'外观与刷新'},
  {id:'connection', label:'连接', description:'网关地址'},
  {id:'account', label:'账号', description:'当前用户与密码'},
  {id:'notifications', label:'通知', description:'飞书与钉钉机器人', admin:true},
  {id:'network', label:'网络', description:'设备与 4G 数据网络', admin:true},
  {id:'security', label:'用户与 API', description:'用户、机器密钥', admin:true}
]
const visibleSettingsSections = computed(() => settingsSections.filter(item => !item.admin || isAdmin.value))
function openSettingsSection(id) {
  settingsSection.value = id
  localStorage.setItem('sms.settingsSection', id)
}
const adminKeys = ref([])
const users = ref([])
const userDraft = ref({username:'',password:''})
const adminKeyDraft = ref({label:'',scope:'read'})
const createdApiToken = ref('')
const adminError = ref('')
const passwordDraft = ref({current:'', next:'', confirm:''})
const passwordError = ref('')
const passwordNotice = ref('')
const passwordBusy = ref(false)
const draft = ref({ device_id: '', phone: '', body: '' })
const settings = ref({
  apiBase: localStorage.getItem('sms.apiBase') || '',
  theme: localStorage.getItem('sms.theme') || 'system',
  refresh: Number(localStorage.getItem('sms.refresh') || 5)
})
let timer
let stopSidebarDrag = null
let navPointer = null
let suppressNavClick = false

function conversationKey(message) { return `${message.device_id || ''}\u0000${message.phone}` }
const conversations = computed(() => {
  const byKey = new Map()
  for (const message of messages.value.filter(message => !message.blacklisted && !message.advertisement)) {
    const key = conversationKey(message)
    if (!byKey.has(key)) byKey.set(key, {key, phone:message.phone, device_id:message.device_id, latest:message})
  }
  return [...byKey.values()]
})
const visibleConversations = computed(() => conversations.value.filter(c =>
  deviceFilter.value === 'all' || c.device_id === deviceFilter.value
))
const activeConversation = computed(() => conversations.value.find(c => c.key === selectedConversationKey.value) || null)
const chatBody = computed({
  get: () => chatDrafts.value[selectedConversationKey.value] || '',
  set: value => { chatDrafts.value = {...chatDrafts.value, [selectedConversationKey.value]: value} }
})
const conversationMessages = computed(() => messages.value.filter(m =>
  !m.blacklisted && !m.advertisement && conversationKey(m) === selectedConversationKey.value
))
const activeDeviceOnline = computed(() => devices.value.some(d =>
  d.device_id === activeConversation.value?.device_id && d.status === 'online'
))
const onlineCount = computed(() => devices.value.filter(d => d.status === 'online').length)
const favorites = computed(() => messages.value.filter(m => m.favorite))
const blacklistedMessages = computed(() => messages.value.filter(m => m.blacklisted))
const advertisementMessages = computed(() => messages.value.filter(m => m.advertisement))
const visibleAdRules = computed(() => {
  const keyword = adSearch.value.trim().toLocaleLowerCase('zh-CN')
  return adRules.value.filter(item => !keyword || [item.pattern,item.label,item.match_type,item.field]
    .some(value => String(value || '').toLocaleLowerCase('zh-CN').includes(keyword)))
})
const blacklistMatchLabels = {exact:'精确匹配',contains:'包含匹配',regex:'正则表达式'}
const visibleBlacklist = computed(() => {
  const keyword = blacklistSearch.value.trim().toLocaleLowerCase('zh-CN')
  return blacklist.value.filter(item => {
    if (blacklistMatchFilter.value !== 'all' && item.match_type !== blacklistMatchFilter.value) return false
    if (!keyword) return true
    return [item.phone,item.label,item.note,blacklistMatchLabels[item.match_type]]
      .some(value => String(value || '').toLocaleLowerCase('zh-CN').includes(keyword))
  })
})
function blacklistMessagesFor(item) {
  const matched = Array.isArray(item.matched_phones) ? item.matched_phones : [item.phone]
  return blacklistedMessages.value.filter(message => matched.includes(message.phone)).slice(0,5)
}
const contactByPhone = phone => contacts.value.find(c => c.phone === phone) || null
const contactName = phone => contactByPhone(phone)?.name || phone
const contactAvatar = phone => (contactByPhone(phone)?.name || phone || '?').slice(0, 2)
const deviceNetworkConnected = device => !!(networkForDevice(device)?.enabled && networkForDevice(device)?.addresses?.length)
const deviceSignalBars = device => {
  if (device.status !== 'online') return null
  const rsrp = device.signal?.rsrp
  if (typeof rsrp === 'number' && rsrp <= -44 && rsrp >= -140)
    return rsrp >= -95 ? 4 : rsrp >= -105 ? 3 : rsrp >= -115 ? 2 : 1
  const csq = device.signal?.csq
  if (typeof csq === 'number' && csq > 0 && csq <= 31)
    return csq >= 25 ? 4 : csq >= 17 ? 3 : csq >= 10 ? 2 : 1
  return null
}
const deviceSignalLabel = device => {
  if (device.status !== 'online') return '设备离线'
  if (deviceSignalBars(device) === null) return '蜂窝信号未读取'
  const rsrp = device.signal?.rsrp
  return typeof rsrp === 'number' && rsrp < 0 ? `蜂窝信号 ${rsrp} dBm` : `蜂窝信号 CSQ ${device.signal.csq}/31`
}
const deviceDataLabel = device => !networkForDevice(device) ? '无 4G 网卡' : !networkForDevice(device).enabled ? '4G 已关闭' : deviceNetworkConnected(device) ? '4G 已连接' : '4G 未连接'

function dropNav(target, event) {
  event.preventDefault()
  const source = navDragging.value || event.dataTransfer?.getData('text/plain')
  navDragging.value = ''
  moveNav(source, target)
}
function moveNav(source, target) {
  if (!source || source === target || !navOrder.value.includes(source)) return
  const movingDown = navOrder.value.indexOf(source) < navOrder.value.indexOf(target)
  const next = navOrder.value.filter(id => id !== source)
  next.splice(next.indexOf(target) + (movingDown ? 1 : 0), 0, source)
  navOrder.value = next
  localStorage.setItem('sms.navOrder', JSON.stringify(next))
}
function stepNav(id, offset) {
  const index = navOrder.value.indexOf(id)
  const target = navOrder.value[index + offset]
  if (target) moveNav(id, target)
}
function startNavPointer(event, id) {
  if (event.button !== 0) return
  navPointer = {id, x:event.clientX, y:event.clientY, moved:false}
  window.addEventListener('pointermove', moveNavPointer)
  window.addEventListener('pointerup', stopNavPointer, {once:true})
}
function moveNavPointer(event) {
  if (!navPointer) return
  if (Math.abs(event.clientY-navPointer.y) > 6 || Math.abs(event.clientX-navPointer.x) > 6) {
    navPointer.moved = true
    navDragging.value = navPointer.id
  }
}
function stopNavPointer(event) {
  window.removeEventListener('pointermove', moveNavPointer)
  if (navPointer?.moved) {
    const target = document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-nav-id]')?.dataset.navId
    if (target) moveNav(navPointer.id, target)
    suppressNavClick = true
    setTimeout(() => { suppressNavClick = false }, 0)
  }
  navPointer = null
  navDragging.value = ''
}
function clickNav(id, event) {
  if (suppressNavClick) { event.preventDefault(); return }
  view.value = id
}
async function toggleFavorite(message) {
  try {
    const updated = await api(`/api/v1/messages/${message.id}/favorite`, {
      method:'PATCH', body:JSON.stringify({favorite:!message.favorite})
    })
    messages.value = messages.value.map(m => m.id === updated.id ? updated : m)
  } catch (exc) { error.value = exc.message }
}
function openFavorite(message) {
  view.value = 'messages'
  selectConversation(conversationKey(message))
  nextTick(() => document.querySelector(`[data-message-id="${message.id}"]`)?.scrollIntoView({block:'center'}))
}
async function toggleFourG(device) {
  const network = networkForDevice(device)
  if (!network) return
  fourGBusy.value = true
  fourGError.value = ''
  try {
    fourG.value = await api('/api/v1/network/4g', {
      method:'PUT', body:JSON.stringify({enabled:!network.enabled, interface:network.name})
    })
  } catch (exc) { fourGError.value = exc.message }
  finally { fourGBusy.value = false }
}

function startSidebarDrag(event) {
  if (window.innerWidth <= 620) return
  event.preventDefault()
  const move = e => { sidebarWidth.value = Math.max(64, Math.min(280, e.clientX)) }
  const stop = () => {
    localStorage.setItem('sms.sidebarWidth', String(sidebarWidth.value))
    localStorage.removeItem('sms.sidebarCollapsed')
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    stopSidebarDrag = null
  }
  stopSidebarDrag = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
}
function apiUrl(path) { return settings.value.apiBase.replace(/\/$/, '') + path }
async function api(path, options = {}) {
  const headers = { ...(options.body ? {'Content-Type':'application/json'} : {}) }
  if (userSession.value) headers['X-User-Session'] = userSession.value
  const response = await fetch(apiUrl(path), { ...options, headers: {...headers, ...(options.headers || {})} })
  const data = await response.json()
  if (!response.ok) {
    const exc = new Error(data.error || `请求失败 ${response.status}`)
    exc.status = response.status
    throw exc
  }
  return data
}
async function refresh() {
  if (loading.value || !userSession.value) return
  loading.value = true
  try {
    const [m, d, c, b, ads, i, ding, network] = await Promise.all([
      api('/api/v1/messages?limit=200'), api('/api/v1/devices'), api('/api/v1/contacts'),
      api('/api/v1/blacklist'), api('/api/v1/ad-rules'), api('/api/v1/integrations/feishu'),
      api('/api/v1/integrations/dingtalk'),
      api('/api/v1/network/4g').catch(exc => ({available:false,enabled:false,interfaces:[],error:exc.message}))
    ])
    messages.value = m.messages
    devices.value = d.devices
    contacts.value = c.contacts
    blacklist.value = b.blacklist
    adRules.value = ads.rules
    integrations.value = i
    dingtalkIntegrations.value = ding
    fourG.value = network
    if (!conversations.value.some(c => c.key === selectedConversationKey.value))
      selectedConversationKey.value = conversations.value[0]?.key || null
    error.value = ''
    authRequired.value = false
  } catch (e) {
    error.value = e.message
    if (e.status === 401) {
      authRequired.value = true
      currentUser.value = null
      userSession.value = ''
      sessionStorage.removeItem('sms.userSession')
    }
  } finally { loading.value = false }
}
async function loginUser() {
  loginError.value = ''
  try {
    const response = await fetch(apiUrl('/api/v1/auth/login'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(loginDraft.value)})
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '登录失败')
    userSession.value = data.session
    currentUser.value = data.user
    sessionStorage.setItem('sms.userSession', data.session)
    loginDraft.value.password = ''
    authRequired.value = false
    if (!isAdmin.value && ['notifications','network','security'].includes(settingsSection.value)) settingsSection.value = 'account'
    await refresh()
    await loadAdminData()
  } catch (e) { loginError.value = e.message }
}
async function logoutUser() {
  try { if (userSession.value) await api('/api/v1/auth/logout', {method:'POST'}) } catch (_) {}
  userSession.value = ''
  currentUser.value = null
  users.value = []
  adminKeys.value = []
  sessionStorage.removeItem('sms.userSession')
  authRequired.value = true
}
function scrollChatToBottom() {
  nextTick(() => { if (chatHistory.value) chatHistory.value.scrollTop = 0 })
}
function selectConversation(key) {
  composeOpen.value = false
  selectedConversationKey.value = key
  mobileConversationOpen.value = true
  chatError.value = ''
  scrollChatToBottom()
}
function openNewMessage() {
  draft.value = {device_id:deviceFilter.value === 'all' ? '' : deviceFilter.value, phone:'', body:''}
  error.value = ''
  composeOpen.value = true
  mobileConversationOpen.value = true
}
function editContact(phone = '') {
  const contact = contactByPhone(phone)
  contactOriginalPhone.value = contact?.phone || ''
  contactDraft.value = {phone:phone || '', name:contact?.name || '', note:contact?.note || ''}
  contactError.value = ''
  contactEditorOpen.value = true
}
async function saveContact() {
  const phone = contactDraft.value.phone.trim()
  contactError.value = ''
  try {
    const saved = await api(`/api/v1/contacts/${encodeURIComponent(phone)}`, {
      method:'PUT', body:JSON.stringify({name:contactDraft.value.name, note:contactDraft.value.note})
    })
    contacts.value = [...contacts.value.filter(c => c.phone !== saved.phone), saved]
      .sort((a,b) => a.name.localeCompare(b.name,'zh-CN'))
    contactEditorOpen.value = false
  } catch (e) { contactError.value = e.message }
}
async function deleteContact(contact) {
  if (!confirm(`确认删除“${contact.name}”的通讯录资料？历史短信不会删除。`)) return
  try {
    await api(`/api/v1/contacts/${encodeURIComponent(contact.phone)}`, {method:'DELETE'})
    contacts.value = contacts.value.filter(c => c.phone !== contact.phone)
  } catch (e) { error.value = e.message }
}
function editBlacklist(phone = '') {
  const item = blacklist.value.find(entry => entry.phone === phone)
  blacklistOriginalPhone.value = item?.phone || ''
  blacklistDraft.value = {phone:phone || '', match_type:item?.match_type || 'exact', label:item?.label || '', note:item?.note || ''}
  blacklistError.value = ''
  blacklistEditorOpen.value = true
}
async function saveBlacklist() {
  const phone = blacklistDraft.value.phone.trim()
  blacklistError.value = ''
  try {
    await api(`/api/v1/blacklist/${encodeURIComponent(phone)}`, {
      method:'PUT', body:JSON.stringify({match_type:blacklistDraft.value.match_type, label:blacklistDraft.value.label, note:blacklistDraft.value.note})
    })
    blacklistEditorOpen.value = false
    await refresh()
  } catch (e) { blacklistError.value = e.message }
}
async function deleteBlacklist(item) {
  if (!confirm(`确认将“${item.label || item.phone}”移出黑名单？已归档的黑名单短信仍会保留。`)) return
  try {
    await api(`/api/v1/blacklist/${encodeURIComponent(item.phone)}`, {method:'DELETE'})
    await refresh()
  } catch (e) { error.value = e.message }
}
function editAdRule(item = null) {
  adRuleOriginalId.value = item?.id || null
  adRuleDraft.value = item ? {pattern:item.pattern,match_type:item.match_type,field:item.field,label:item.label || '',enabled:!!item.enabled}
    : {pattern:'',match_type:'contains',field:'body',label:'',enabled:true}
  adRuleError.value = ''
  adRuleEditorOpen.value = true
}
async function saveAdRule() {
  adRuleError.value = ''
  try {
    if (adRuleOriginalId.value) await api(`/api/v1/ad-rules/${adRuleOriginalId.value}`, {method:'PATCH',body:JSON.stringify(adRuleDraft.value)})
    else await api('/api/v1/ad-rules', {method:'POST',body:JSON.stringify(adRuleDraft.value)})
    adRuleEditorOpen.value = false
    await refresh()
  } catch (e) { adRuleError.value = e.message }
}
async function toggleAdRule(item) {
  try { await api(`/api/v1/ad-rules/${item.id}`, {method:'PATCH',body:JSON.stringify({...item,enabled:!item.enabled})}); await refresh() }
  catch (e) { error.value = e.message }
}
async function deleteAdRule(item) {
  if (!confirm(`确认删除广告规则“${item.label || item.pattern}”？`)) return
  try { await api(`/api/v1/ad-rules/${item.id}`, {method:'DELETE'}); await refresh() }
  catch (e) { error.value = e.message }
}
function fmt(value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value))
}
function deviceName(id) {
  const d = devices.value.find(x => x.device_id === id)
  return d?.label || d?.imei || id || '历史记录'
}
async function send() {
  error.value = ''
  try {
    const message = await api('/api/v1/messages', {method:'POST', body:JSON.stringify(draft.value)})
    messages.value = [message, ...messages.value.filter(m => m.id !== message.id)]
    composeOpen.value = false
    draft.value = {device_id:'', phone:'', body:''}
    await refresh()
    selectConversation(conversationKey(message))
  } catch (e) { error.value = e.message }
}
async function sendChat() {
  const conversation = activeConversation.value
  const body = chatBody.value.trim()
  if (!conversation || !activeDeviceOnline.value || !body || chatSending.value) return
  chatSending.value = true
  chatError.value = ''
  try {
    const message = await api('/api/v1/messages', {method:'POST', body:JSON.stringify({
      device_id:conversation.device_id, phone:conversation.phone, body
    })})
    messages.value = [message, ...messages.value.filter(m => m.id !== message.id)]
    chatBody.value = ''
    await refresh()
    scrollChatToBottom()
  } catch (e) { chatError.value = e.message }
  finally { chatSending.value = false }
}
function chatKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    sendChat()
  }
}
function beginRename(device) {
  editingDevice.value = device.device_id
  deviceLabel.value = device.label || ''
}
async function saveDeviceLabel(device) {
  try {
    await api(`/api/v1/devices/${encodeURIComponent(device.device_id)}`, {
      method: 'PATCH', body: JSON.stringify({label: deviceLabel.value.trim()})
    })
    editingDevice.value = null
    await refresh()
  } catch (e) { error.value = e.message }
}
async function deleteDevice(device) {
  if (device.status === 'online') { error.value = '在线设备不能删除，请先断开设备'; return }
  if (!confirm(`确认删除设备“${device.label || device.imei}”的登记记录？历史短信不会删除。`)) return
  try { await api(`/api/v1/devices/${encodeURIComponent(device.device_id)}`, {method:'DELETE'}); await refresh() }
  catch (e) { error.value = e.message }
}
async function saveSettings() {
  localStorage.setItem('sms.apiBase', settings.value.apiBase.trim())
  localStorage.setItem('sms.theme', settings.value.theme)
  localStorage.setItem('sms.refresh', String(settings.value.refresh))
  savedNotice.value = '设置已保存'
  setTimeout(() => savedNotice.value = '', 2400)
  applyTheme(); schedule(); refresh()
}
async function adminRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {...options, headers:{'Content-Type':'application/json','X-User-Session':userSession.value}})
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`)
  return data
}
async function loadAdminData() {
  if (!isAdmin.value) { adminKeys.value = []; users.value = []; return }
  try {
    const [keyResult,userResult] = await Promise.all([adminRequest('/api/v1/admin/keys'),adminRequest('/api/v1/admin/users')])
    adminKeys.value = keyResult.keys
    users.value = userResult.users
    adminError.value = ''
  } catch(e) { adminError.value = e.message }
}
async function changeAdminPassword() {
  passwordError.value = ''; passwordNotice.value = ''
  if (passwordDraft.value.next !== passwordDraft.value.confirm) {
    passwordError.value = '两次输入的新密码不一致'; return
  }
  if (passwordDraft.value.next.length < 8 || passwordDraft.value.next.length > 128) {
    passwordError.value = '新密码须为 8–128 个字符'; return
  }
  passwordBusy.value = true
  try {
    await api('/api/v1/auth/password', {method:'PUT', body:JSON.stringify({
      current_password:passwordDraft.value.current, new_password:passwordDraft.value.next
    })})
    passwordDraft.value = {current:'', next:'', confirm:''}
    passwordNotice.value = '密码已更新，请重新登录'
    await logoutUser()
  } catch(e) { passwordError.value = e.message }
  finally { passwordBusy.value = false }
}
async function createUser() {
  adminError.value = ''
  try {
    const result = await adminRequest('/api/v1/admin/users', {method:'POST',body:JSON.stringify(userDraft.value)})
    users.value = result.users
    userDraft.value = {username:'',password:''}
  } catch(e) { adminError.value = e.message }
}
async function toggleUser(item) {
  try { users.value = (await adminRequest(`/api/v1/admin/users/${encodeURIComponent(item.username)}`, {method:'PATCH',body:JSON.stringify({enabled:!item.enabled})})).users }
  catch(e) { adminError.value = e.message }
}
async function resetUserPassword(item) {
  const password = prompt(`为 ${item.username} 设置新密码（至少 8 个字符）`)
  if (password === null) return
  try { await adminRequest(`/api/v1/admin/users/${encodeURIComponent(item.username)}/password`, {method:'PUT',body:JSON.stringify({password})}); savedNotice.value = '用户密码已重置' }
  catch(e) { adminError.value = e.message }
}
async function deleteUser(item) {
  if (!confirm(`确认删除用户“${item.username}”？`)) return
  try { users.value = (await adminRequest(`/api/v1/admin/users/${encodeURIComponent(item.username)}`, {method:'DELETE'})).users }
  catch(e) { adminError.value = e.message }
}
async function createAdminKey() {
  adminError.value = ''; createdApiToken.value = ''
  try {
    const result = await adminRequest('/api/v1/admin/keys', {method:'POST',body:JSON.stringify(adminKeyDraft.value)})
    adminKeys.value.unshift(result.key); createdApiToken.value = result.token
    adminKeyDraft.value = {label:'',scope:'read'}
  } catch(e) { adminError.value = e.message }
}
async function copyAdminKey() {
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(createdApiToken.value)
    else {
      const field = document.createElement('textarea')
      field.value = createdApiToken.value
      field.style.position = 'fixed'; field.style.opacity = '0'
      document.body.appendChild(field); field.select()
      const copied = document.execCommand('copy')
      field.remove()
      if (!copied) throw new Error('copy failed')
    }
    savedNotice.value = '已复制 API 凭据'
  } catch(e) { adminError.value = '复制失败，请手动选中密钥' }
}
async function renameAdminKey(item) {
  const label = prompt('输入 API 凭据备注', item.label)
  if (label === null) return
  try { adminKeys.value = (await adminRequest(`/api/v1/admin/keys/${item.id}`, {method:'PATCH',body:JSON.stringify({label})})).keys }
  catch(e) { adminError.value = e.message }
}
async function deleteAdminKey(item) {
  if (!confirm(`确认撤销“${item.label}”？使用它的程序将立即失去访问权限。`)) return
  try { adminKeys.value = (await adminRequest(`/api/v1/admin/keys/${item.id}`, {method:'DELETE'})).keys }
  catch(e) { adminError.value = e.message }
}
async function addHook() {
  integrations.value = await api('/api/v1/integrations/feishu', {
    method:'POST', body:JSON.stringify(hookDraft.value)
  })
  hookDraft.value = {label:'',webhook_url:''}
}
async function toggleHook(item) {
  integrations.value = await api(`/api/v1/integrations/feishu/${item.id}`, {
    method:'PATCH', body:JSON.stringify({enabled:!item.enabled})
  })
}
async function renameHook(item) {
  const label = prompt('输入机器人备注', item.label)
  if (label === null || !label.trim()) return
  integrations.value = await api(`/api/v1/integrations/feishu/${item.id}`, {
    method:'PATCH', body:JSON.stringify({label:label.trim()})
  })
}
async function removeHook(item) {
  if (!confirm(`确认删除“${item.label}”？删除后该群将停止接收通知。`)) return
  integrations.value = await api(`/api/v1/integrations/feishu/${item.id}`, {method:'DELETE'})
}
async function addDingtalkHook() {
  try {
    dingtalkIntegrations.value = await api('/api/v1/integrations/dingtalk', {
      method:'POST', body:JSON.stringify(dingtalkDraft.value)
    })
    dingtalkDraft.value = {label:'',webhook_url:'',secret:''}
    error.value = ''
  } catch (e) { error.value = e.message }
}
async function toggleDingtalkHook(item) {
  try { dingtalkIntegrations.value = await api(`/api/v1/integrations/dingtalk/${item.id}`, {
    method:'PATCH', body:JSON.stringify({enabled:!item.enabled})
  }) } catch (e) { error.value = e.message }
}
async function renameDingtalkHook(item) {
  const label = prompt('输入机器人备注', item.label)
  if (label === null || !label.trim()) return
  try { dingtalkIntegrations.value = await api(`/api/v1/integrations/dingtalk/${item.id}`, {
    method:'PATCH', body:JSON.stringify({label:label.trim()})
  }) } catch (e) { error.value = e.message }
}
async function removeDingtalkHook(item) {
  if (!confirm(`确认删除“${item.label}”？删除后该群将停止接收通知。`)) return
  try { dingtalkIntegrations.value = await api(`/api/v1/integrations/dingtalk/${item.id}`, {method:'DELETE'}) }
  catch (e) { error.value = e.message }
}
function applyTheme() { document.documentElement.dataset.theme = settings.value.theme }
function schedule() { clearInterval(timer); timer = setInterval(refresh, Math.max(3, settings.value.refresh) * 1000) }
watch([selectedConversationKey, () => conversationMessages.value[0]?.id], scrollChatToBottom, {flush:'post', immediate:true})
watch(deviceFilter, () => { if (!visibleConversations.value.some(c => c.key === selectedConversationKey.value)) selectedConversationKey.value = visibleConversations.value[0]?.key || null })
onMounted(async () => {
  applyTheme(); schedule()
  if (!userSession.value) return
  try {
    currentUser.value = (await api('/api/v1/auth/me')).user
    authRequired.value = false
    if (!isAdmin.value && ['notifications','network','security'].includes(settingsSection.value)) {
      settingsSection.value = 'account'
      localStorage.setItem('sms.settingsSection', 'account')
    }
    await refresh()
    await loadAdminData()
  } catch (_) {
    userSession.value = ''
    currentUser.value = null
    sessionStorage.removeItem('sms.userSession')
    authRequired.value = true
  }
})
onBeforeUnmount(() => { clearInterval(timer); stopSidebarDrag?.(); window.removeEventListener('pointermove', moveNavPointer); window.removeEventListener('pointerup', stopNavPointer) })
</script>

<template>
  <div class="shell" :class="{'chat-open':view==='messages' && mobileConversationOpen, 'sidebar-collapsed':sidebarCollapsed}" :style="{'--sidebar-width':`${sidebarWidth}px`}">
    <aside class="sidebar" aria-label="主菜单">
      <nav aria-label="主导航">
        <button v-for="id in navOrder" :key="id" :data-nav-id="id" :class="{active:view===id,dragging:navDragging===id}" :title="`${navLabels[id]} · 拖动排序；Alt+↑/↓ 调整`" :aria-label="navLabels[id]" draggable="true" @pointerdown="startNavPointer($event,id)" @dragstart="navDragging=id; $event.dataTransfer.setData('text/plain',id)" @dragend="navDragging=''" @dragenter.prevent="moveNav(navDragging,id)" @dragover.prevent @drop="dropNav(id,$event)" @keydown.alt.up.prevent="stepNav(id,-1)" @keydown.alt.down.prevent="stepNav(id,1)" @click="clickNav(id,$event)">
          <svg v-if="id==='messages'" viewBox="0 0 24 24" aria-hidden="true"><path d="M5.3 5.3h13.4a2.3 2.3 0 0 1 2.3 2.3v8.1a2.3 2.3 0 0 1-2.3 2.3H9.5L4 21v-3.4a2.3 2.3 0 0 1-1-1.9V7.6a2.3 2.3 0 0 1 2.3-2.3z"/><path d="M7.5 10h9M7.5 13.5H14"/></svg>
          <svg v-else-if="id==='devices'" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="2.5" width="12" height="19" rx="2.8"/><path d="M10 5.5h4M10 18.3h4"/><circle cx="12" cy="12" r="2.2"/></svg>
          <svg v-else-if="id==='contacts'" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="15" height="18" rx="2.5"/><path d="M5 7H3M5 12H3M5 17H3"/><circle cx="12.5" cy="9" r="2"/><path d="M8.8 16.5c.5-1.9 1.7-2.8 3.7-2.8s3.2.9 3.7 2.8"/></svg>
          <svg v-else-if="id==='favorites'" viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 3.1 6.4 7.1 1-5.1 5 .9 7-6-3.3-6 3.3.9-7-5.1-5 7.1-1z"/></svg>
          <svg v-else-if="id==='ads'" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7.5h16v10H4z"/><path d="M7 4.5v3M17 4.5v3M7 12h4M7 15h7"/></svg>
          <svg v-else-if="id==='blacklist'" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m6 18 12-12"/></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 2.9h3.4l.5 2.1c.6.2 1.2.4 1.7.7l1.9-1.1 2.4 2.4-1.1 1.9c.3.5.5 1.1.7 1.7l2.1.5v3.4l-2.1.5c-.2.6-.4 1.2-.7 1.7l1.1 1.9-2.4 2.4-1.9-1.1c-.5.3-1.1.5-1.7.7l-.5 2.1h-3.4l-.5-2.1c-.6-.2-1.2-.4-1.7-.7l-1.9 1.1-2.4-2.4 1.1-1.9c-.3-.5-.5-1.1-.7-1.7l-2.1-.5v-3.4l2.1-.5c.2-.6.4-1.2.7-1.7L3.8 7l2.4-2.4 1.9 1.1c.5-.3 1.1-.5 1.7-.7z"/><circle cx="12" cy="12.8" r="3.1"/></svg>
          <span class="nav-copy"><span>{{ navLabels[id] }}</span><small v-if="view===id">{{ navDescriptions[id] }}</small></span><b v-if="id==='messages'">{{ messages.length-blacklistedMessages.length-advertisementMessages.length }}</b><i v-else-if="id==='devices'" :class="onlineCount?'ok':''">{{ onlineCount }}</i><i v-else-if="id==='contacts'">{{ contacts.length }}</i><i v-else-if="id==='favorites'">{{ favorites.length }}</i><i v-else-if="id==='ads'">{{ advertisementMessages.length }}</i><i v-else-if="id==='blacklist'">{{ blacklistedMessages.length }}</i><span class="nav-grip" aria-hidden="true">⋮⋮</span>
        </button>
      </nav>
      <div class="sidebar-foot">
        <div class="sidebar-device-list" aria-label="设备信号列表"><div v-for="d in devices" :key="d.device_id" class="sidebar-device-row" :title="`${d.label || d.imei} · ${deviceSignalLabel(d)} · ${deviceDataLabel(d)}`"><span class="sidebar-device-name"><strong>{{ d.label || d.imei }}</strong></span><span class="phone-status" :aria-label="`${deviceSignalLabel(d)}，${deviceDataLabel(d)}`"><span class="signal-bars" :class="{on:deviceSignalBars(d)>0}" aria-hidden="true"><i v-for="bar in 4" :key="bar" :class="{active:deviceSignalBars(d)!==null && bar<=deviceSignalBars(d)}"></i></span><span class="network-mark" :class="{connected:deviceNetworkConnected(d)}" aria-hidden="true">4G</span></span></div><div v-if="!devices.length" class="sidebar-device-empty">暂无设备</div></div>
        <div class="gateway"><span :class="['status-dot', error?'bad':'']"></span>{{ error ? '连接异常' : '服务正常' }}</div>
      </div>
      <div class="sidebar-resizer" role="separator" aria-label="拖动调整菜单栏宽度" aria-orientation="vertical" @pointerdown="startSidebarDrag"></div>
    </aside>

    <main v-if="authRequired" class="auth-gate">
      <div class="auth-card"><span class="auth-symbol" aria-hidden="true">✉</span><h1>登录短信中心</h1><p>使用管理员分配的账号和密码登录。管理员可在“设置 → 用户与 API”中管理普通用户。</p><form @submit.prevent="loginUser"><label for="login-user">账号</label><input id="login-user" v-model.trim="loginDraft.username" autocomplete="username" required placeholder="用户名"><label for="login-password">密码</label><input id="login-password" v-model="loginDraft.password" type="password" autocomplete="current-password" required placeholder="密码"><button class="primary" type="submit">登录</button></form><p v-if="loginError" class="form-error">{{ loginError }}</p><small>首次安装默认管理员为 <code>admin</code>；上线后应立即修改管理员密码。</small></div>
    </main>
    <template v-else-if="view==='messages'">
      <section class="list-pane">
        <div class="device-filters" aria-label="按设备筛选">
          <button :class="{active:deviceFilter==='all'}" @click="deviceFilter='all'">全部</button>
          <button v-for="d in devices" :key="d.device_id" :class="{active:deviceFilter===d.device_id}" @click="deviceFilter=d.device_id">{{ d.label || '未备注设备' }}</button>
        </div>
        <div class="message-list conversation-list">
          <button v-if="composeOpen" type="button" class="conversation-row selected draft-conversation-row" @click="mobileConversationOpen=true">
            <span class="conversation-avatar">＋</span><span class="conversation-summary"><span class="row-top"><strong>{{ draft.phone || '新短信' }}</strong><time>草稿</time></span></span>
          </button>
          <button v-for="c in visibleConversations" :key="c.key" class="conversation-row" :class="{selected:c.key===selectedConversationKey}" @click="selectConversation(c.key)">
            <span class="conversation-avatar">{{ contactAvatar(c.phone) }}</span>
            <span class="conversation-summary"><span class="row-top"><strong>{{ contactName(c.phone) }}</strong><time>{{ fmt(c.latest.created_at) }}</time></span><span class="conversation-preview">{{ c.latest.direction==='outbound'?'我：':'' }}{{ c.latest.body }}</span><span class="conversation-device">{{ contactByPhone(c.phone) ? `${c.phone} · ` : '' }}{{ deviceName(c.device_id) }}</span></span>
          </button>
          <div v-if="!visibleConversations.length && !composeOpen" class="empty">暂无会话</div>
        </div>
        <button v-if="!composeOpen" type="button" class="new-message-fab" aria-label="新短信" title="新短信" @click="openNewMessage">＋</button>
      </section>
      <main class="detail-pane chat-pane">
        <template v-if="composeOpen">
          <form class="new-chat" @submit.prevent="send">
            <header class="chat-header new-chat-header"><button type="button" class="chat-back" aria-label="返回会话列表" @click="mobileConversationOpen=false">‹</button><span class="conversation-avatar">＋</span><span class="new-recipient"><strong>新短信</strong><input v-model.trim="draft.phone" inputmode="tel" list="contact-numbers" required autofocus placeholder="输入手机号码或选择联系人" aria-label="手机号码"><small v-if="contactByPhone(draft.phone)">{{ contactName(draft.phone) }}</small></span><label class="new-device-select"><span>发送设备</span><select v-model="draft.device_id"><option value="">自动选择</option><option v-for="d in devices" :key="d.device_id" :value="d.device_id">{{ d.label || d.imei }}{{ d.status==='online'?'':'（离线）' }}</option></select></label><button type="button" class="contact-edit" @click="composeOpen=false;mobileConversationOpen=false">取消</button></header>
            <datalist id="contact-numbers"><option v-for="contact in contacts" :key="contact.phone" :value="contact.phone" :label="contact.name"/></datalist>
            <div class="chat-history new-chat-empty"><p>填写收件号码和短信内容后发送</p></div>
            <div class="chat-compose"><div v-if="draft.device_id && !devices.some(d=>d.device_id===draft.device_id && d.status==='online')" class="chat-warning">该设备当前离线，请等待上线或选择其他在线设备。</div><div v-if="error" class="chat-warning">{{ error }}</div><div class="chat-compose-row"><textarea v-model="draft.body" maxlength="134" rows="2" required placeholder="输入短信…" aria-label="短信内容"></textarea><button class="chat-send" type="submit" aria-label="发送短信" :disabled="!draft.phone.trim() || !draft.body.trim() || (!!draft.device_id && !devices.some(d=>d.device_id===draft.device_id && d.status==='online'))">➤</button></div><small><span class="desktop-send-hint">填写完成后发送 · </span>{{ draft.body.length }}/134</small></div>
          </form>
        </template>
        <template v-else-if="activeConversation">
          <header class="chat-header"><button type="button" class="chat-back" aria-label="返回会话列表" @click="mobileConversationOpen=false">‹</button><span class="conversation-avatar">{{ contactAvatar(activeConversation.phone) }}</span><span class="chat-contact"><strong>{{ contactName(activeConversation.phone) }}</strong><small>{{ activeConversation.phone }} · {{ deviceName(activeConversation.device_id) }} · {{ activeDeviceOnline?'设备在线':'设备离线' }}</small></span><button type="button" class="contact-edit danger" @click="editBlacklist(activeConversation.phone)">加入黑名单</button><button type="button" class="contact-edit" @click="editContact(activeConversation.phone)">{{ contactByPhone(activeConversation.phone)?'编辑资料':'存为联系人' }}</button></header>
          <div ref="chatHistory" class="chat-history" role="log" aria-label="短信对话记录">
            <div v-for="m in conversationMessages" :key="m.id" :data-message-id="m.id" class="chat-line" :class="m.direction==='outbound'?'outbound':'inbound'">
              <div class="chat-bubble"><div class="chat-text">{{ m.body }}</div><div class="chat-meta"><button type="button" class="favorite-toggle" :class="{saved:m.favorite}" :aria-label="m.favorite?'取消收藏短信':'收藏短信'" :title="m.favorite?'取消收藏':'收藏短信'" @click="toggleFavorite(m)">{{ m.favorite?'★':'☆' }}</button><time>{{ fmt(m.created_at) }}</time><span v-if="m.direction==='outbound'">{{ m.status==='failed'?'发送失败':m.status==='queued'?'发送中':'已发送' }}</span></div><div v-if="m.error" class="chat-error">{{ m.error }}</div></div>
            </div>
          </div>
          <form class="chat-compose" @submit.prevent="sendChat"><div v-if="!activeDeviceOnline" class="chat-warning">该设备当前离线，恢复上线后才能回复。</div><div v-if="chatError" class="chat-warning">{{ chatError }}</div><div class="chat-compose-row"><textarea v-model="chatBody" maxlength="134" rows="1" :disabled="!activeDeviceOnline" placeholder="输入短信…" aria-label="短信内容" @keydown="chatKeydown"></textarea><button class="chat-send" type="submit" aria-label="发送短信" :disabled="!chatBody.trim() || !activeDeviceOnline || chatSending">➤</button></div><small><span class="desktop-send-hint">Enter 发送 · Shift+Enter 换行 · </span>{{ chatBody.length }}/134</small></form>
        </template>
        <div v-else class="empty detail-empty">选择会话开始聊天</div>
      </main>
    </template>

    <main v-else class="page-pane">
      <section v-if="view==='devices'" class="device-table" aria-label="设备列表">
        <div v-for="d in devices" :key="d.device_id" class="device-line">
          <div class="device-identity"><span :class="['status-dot',d.status!=='online'?'bad':'']" aria-hidden="true"></span><div class="device-main">
            <form v-if="editingDevice===d.device_id" class="rename-form" @submit.prevent="saveDeviceLabel(d)"><input v-model="deviceLabel" maxlength="60" autofocus placeholder="例如：客服一号卡"><button class="primary" type="submit">保存</button><button type="button" @click="editingDevice=null">取消</button></form>
            <template v-else><strong>{{ d.label || '未备注设备' }}</strong><p>IMEI {{ d.imei }}</p><p>{{ d.serial_port || '未连接' }}</p></template>
          </div></div>
          <div class="device-network" :aria-label="`${d.label || d.imei} 的信号和数据网络`">
            <span class="phone-status large" :aria-label="`${deviceSignalLabel(d)}，${deviceDataLabel(d)}`"><span class="signal-bars large" :class="{on:deviceSignalBars(d)>0}" aria-hidden="true"><i v-for="bar in 4" :key="bar" :class="{active:deviceSignalBars(d)!==null && bar<=deviceSignalBars(d)}"></i></span><span class="network-mark" :class="{connected:deviceNetworkConnected(d)}" aria-hidden="true">4G</span></span>
            <div><strong>{{ deviceDataLabel(d) }}</strong><p>{{ deviceSignalLabel(d) }}</p><p v-if="networkForDevice(d)">{{ networkForDevice(d).addresses?.join(', ') || '等待获取地址' }}</p></div>
          </div>
          <div class="device-actions"><span :class="['device-status',d.status!=='online'?'offline':'']">{{ d.status==='online'?'在线':'离线' }}</span><button v-if="editingDevice!==d.device_id" class="text-button" type="button" @click="beginRename(d)">{{ d.label?'修改备注':'添加备注' }}</button><button v-if="isAdmin && d.status!=='online'" type="button" class="text-button danger" @click="deleteDevice(d)">删除设备</button><button v-if="isAdmin && networkForDevice(d)" type="button" class="primary compact" :disabled="!fourG.available || fourGBusy" @click="toggleFourG(d)">{{ fourGBusy?'切换中…':networkForDevice(d).enabled?'关闭 4G':'开启 4G' }}</button></div>
        </div>
        <p v-if="!devices.length" class="empty">暂无设备</p><p v-if="fourGError" class="form-error">{{ fourGError }}</p>
      </section>
      <section v-else-if="view==='contacts'" class="contacts-page">
        <div v-if="!contacts.length" class="empty">暂无联系人</div>
        <div v-for="contact in contacts" :key="contact.phone" class="contact-row"><span class="conversation-avatar">{{ contact.name.slice(0,2) }}</span><div class="contact-details"><strong>{{ contact.name }}</strong><p>{{ contact.phone }}</p><small v-if="contact.note">{{ contact.note }}</small></div><button class="text-button" type="button" @click="editContact(contact.phone)">编辑</button><button class="text-button danger" type="button" @click="deleteContact(contact)">删除</button></div>
        <button class="page-add-fab" type="button" aria-label="添加联系人" title="添加联系人" @click="editContact()">＋</button>
      </section>
      <section v-else-if="view==='favorites'" class="favorites-page">
        <div v-if="!favorites.length" class="empty">暂无收藏。在短信气泡下方点击 ☆ 即可收藏。</div>
        <div v-for="m in favorites" :key="m.id" class="favorite-row"><button type="button" class="favorite-open" @click="openFavorite(m)"><strong>{{ contactName(m.phone) }}</strong><time>{{ fmt(m.created_at) }}</time><p>{{ m.body }}</p><small>{{ m.phone }} · {{ deviceName(m.device_id) }}</small></button><button type="button" class="favorite-toggle saved" aria-label="取消收藏短信" title="取消收藏" @click="toggleFavorite(m)">★</button></div>
      </section>
      <section v-else-if="view==='ads'" class="ads-page">
        <div class="blacklist-notice">广告过滤器先检查黑名单，再按启用的广告规则匹配短信内容或发送号码。命中后只归档到这里，不进入普通会话，也不推送机器人或 Webhook。</div>
        <div class="blacklist-tools"><input v-model="adSearch" type="search" placeholder="搜索广告规则…"><span>{{ visibleAdRules.length }} 条规则 · {{ advertisementMessages.length }} 条广告</span></div>
        <div class="ad-rule-list"><div v-for="item in visibleAdRules" :key="item.id" class="config-item"><span :class="['status-dot',!item.enabled?'bad':'']"></span><div><strong>{{ item.label || item.pattern }}</strong><p>{{ item.pattern }} · {{ item.match_type==='regex'?'正则':'包含' }} · {{ item.field==='body'?'短信内容':item.field==='phone'?'发送号码':'号码+内容' }} · {{ item.enabled?'已启用':'已停用' }}</p></div><button class="text-button" type="button" @click="toggleAdRule(item)">{{ item.enabled?'停用':'启用' }}</button><button class="text-button" type="button" @click="editAdRule(item)">编辑</button><button class="text-button danger" type="button" @click="deleteAdRule(item)">删除</button></div><div v-if="!visibleAdRules.length" class="list-empty">暂无符合条件的广告规则</div></div>
        <div class="ads-messages"><h3>已过滤广告</h3><div v-for="m in advertisementMessages" :key="m.id" class="blacklist-message"><strong>{{ m.phone }}</strong><p>{{ m.body }}</p><small>{{ fmt(m.created_at) }} · {{ deviceName(m.device_id) }}</small></div><div v-if="!advertisementMessages.length" class="empty">暂无广告短信</div></div>
        <button class="page-add-fab" type="button" aria-label="添加广告规则" title="添加广告规则" @click="editAdRule()">＋</button>
      </section>
      <section v-else-if="view==='blacklist'" class="blacklist-page">
        <div class="blacklist-notice">黑名单支持精确号码、包含匹配和正则表达式。命中的新短信会保存归档，但不会推送到飞书、钉钉或通用 Webhook。</div>
        <div class="blacklist-tools"><input v-model="blacklistSearch" type="search" placeholder="搜索规则、备注…" aria-label="搜索黑名单"><select v-model="blacklistMatchFilter" aria-label="按匹配方式筛选"><option value="all">全部匹配方式</option><option value="exact">精确匹配</option><option value="contains">包含匹配</option><option value="regex">正则表达式</option></select><span>{{ visibleBlacklist.length }}/{{ blacklist.length }}</span></div>
        <div v-if="!blacklist.length" class="empty">黑名单为空</div>
        <div v-else-if="!visibleBlacklist.length" class="empty">没有符合当前搜索条件的黑名单规则</div>
        <div v-for="item in visibleBlacklist" :key="item.phone" class="blacklist-card"><div class="blacklist-head"><span class="conversation-avatar blocked">⊘</span><div class="contact-details"><strong>{{ item.label || item.phone }}</strong><p><span class="blacklist-match-badge">{{ blacklistMatchLabels[item.match_type] || '精确匹配' }}</span>{{ item.phone }} · {{ item.message_count || 0 }} 条已拦截短信</p><small v-if="item.note">{{ item.note }}</small></div><button class="text-button" type="button" @click="editBlacklist(item.phone)">编辑</button><button class="text-button danger" type="button" @click="deleteBlacklist(item)">移出</button></div><div class="blacklist-messages"><div v-for="m in blacklistMessagesFor(item)" :key="m.id" class="blacklist-message"><p>{{ m.body }}</p><small>{{ fmt(m.created_at) }} · {{ deviceName(m.device_id) }}</small></div><div v-if="!blacklistMessagesFor(item).length" class="list-empty">尚未收到命中此规则的黑名单短信</div></div></div>
        <button class="page-add-fab" type="button" aria-label="添加黑名单规则" title="添加规则" @click="editBlacklist()">＋</button>
      </section>
      <section v-else class="settings-page" aria-label="设置">
        <header class="settings-title"><div><h1>设置</h1><p>只显示当前类别，减少无关配置干扰。</p></div></header>
        <div class="settings-layout">
          <nav class="settings-nav" aria-label="设置分类">
            <button v-for="item in visibleSettingsSections" :key="item.id" type="button" :class="{active:settingsSection===item.id}" @click="openSettingsSection(item.id)"><strong>{{ item.label }}</strong><small>{{ item.description }}</small></button>
          </nav>
          <div class="settings-content">
            <template v-if="settingsSection==='general'">
              <div class="settings-section-head"><h2>通用</h2><p>只影响当前浏览器的显示和自动刷新。</p></div>
              <div class="settings-group">
                <div class="setting-row"><div><strong>主题</strong><p>选择浅色、深色或跟随操作系统。</p></div><select v-model="settings.theme" @change="applyTheme"><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></div>
                <div class="setting-row"><div><strong>刷新间隔</strong><p>短信、设备和通知状态的自动刷新频率。</p></div><select v-model.number="settings.refresh"><option :value="3">3 秒</option><option :value="5">5 秒</option><option :value="10">10 秒</option><option :value="30">30 秒</option></select></div>
              </div>
              <div class="settings-actions"><button class="primary" type="button" @click="saveSettings">保存通用设置</button><span v-if="savedNotice" class="saved-notice">{{ savedNotice }}</span></div>
            </template>

            <template v-else-if="settingsSection==='connection'">
              <div class="settings-section-head"><h2>连接</h2><p>网页登录使用账号密码，不再要求用户管理 API Token。</p></div>
              <div class="settings-group"><div class="setting-row wide"><div><strong>服务地址</strong><p>留空表示使用当前网页所在地址。</p></div><input v-model="settings.apiBase" placeholder="例如：http://192.168.100.7:8787"></div></div>
              <div class="settings-actions"><button class="primary" type="button" @click="saveSettings">保存连接地址</button><span v-if="savedNotice" class="saved-notice">{{ savedNotice }}</span></div>
            </template>

            <template v-else-if="settingsSection==='account'">
              <div class="settings-section-head"><h2>账号</h2><p>当前登录：{{ currentUser?.username }} · {{ isAdmin?'管理员':'普通用户' }}</p></div>
              <div class="settings-group"><div class="setting-row"><div><strong>退出登录</strong><p>清除当前浏览器会话。</p></div><button type="button" class="contact-edit" @click="logoutUser">退出</button></div></div>
              <div class="settings-subsection"><div class="settings-section-head compact-head"><h3>修改密码</h3><p>修改后当前会话会失效，需要重新登录。</p></div><div class="admin-password-fields" @keydown.enter.prevent="changeAdminPassword"><input v-model="passwordDraft.current" type="password" autocomplete="current-password" placeholder="当前密码"><input v-model="passwordDraft.next" type="password" autocomplete="new-password" placeholder="新密码（至少 8 个字符）"><input v-model="passwordDraft.confirm" type="password" autocomplete="new-password" placeholder="再次输入新密码"><button type="button" class="primary" :disabled="passwordBusy || !passwordDraft.current || !passwordDraft.next || !passwordDraft.confirm" @click="changeAdminPassword">{{ passwordBusy?'修改中…':'修改密码' }}</button></div><p v-if="passwordError" class="form-error">{{ passwordError }}</p><p v-if="passwordNotice" class="saved-notice">{{ passwordNotice }}</p></div>
            </template>

            <template v-else-if="settingsSection==='notifications'">
              <div class="settings-section-head"><h2>通知</h2><p>短信和设备状态可同时推送到多个群。机器人密钥保存在网关本机。</p></div>
              <div class="settings-subsection first"><div class="integration-heading"><div><strong>飞书机器人</strong><p>适合短信提醒、设备上下线和异常通知。</p></div><span>{{ integrations.webhooks.filter(x=>x.enabled).length }}/{{ integrations.webhooks.length }} 已启用</span></div><div class="config-list"><div v-for="item in integrations.webhooks" :key="item.id" class="config-item"><span :class="['status-dot',!item.enabled?'bad':'']"></span><div><strong>{{ item.label }}</strong><p>{{ item.masked }} · {{ item.enabled?'已启用':'已停用' }}</p></div><button type="button" class="text-button" @click="toggleHook(item)">{{ item.enabled?'停用':'启用' }}</button><button type="button" class="text-button" @click="renameHook(item)">改备注</button><button type="button" class="text-button danger" @click="removeHook(item)">删除</button></div><div v-if="!integrations.webhooks.length" class="list-empty">暂无飞书机器人</div></div><div class="add-config settings-add two-plus"><input v-model="hookDraft.label" placeholder="备注，例如：客服通知群"><input v-model="hookDraft.webhook_url" type="password" autocomplete="new-password" placeholder="飞书机器人 Hook 地址"><button class="primary" type="button" @click="addHook">添加</button></div></div>
              <div class="settings-subsection"><div class="integration-heading"><div><strong>钉钉机器人</strong><p>支持自定义机器人加签，密钥可留空。</p></div><span>{{ dingtalkIntegrations.webhooks.filter(x=>x.enabled).length }}/{{ dingtalkIntegrations.webhooks.length }} 已启用</span></div><div class="config-list"><div v-for="item in dingtalkIntegrations.webhooks" :key="item.id" class="config-item"><span :class="['status-dot',!item.enabled?'bad':'']"></span><div><strong>{{ item.label }}</strong><p>{{ item.masked }} · {{ item.signed?'已加签':'未加签' }} · {{ item.enabled?'已启用':'已停用' }}</p></div><button type="button" class="text-button" @click="toggleDingtalkHook(item)">{{ item.enabled?'停用':'启用' }}</button><button type="button" class="text-button" @click="renameDingtalkHook(item)">改备注</button><button type="button" class="text-button danger" @click="removeDingtalkHook(item)">删除</button></div><div v-if="!dingtalkIntegrations.webhooks.length" class="list-empty">暂无钉钉机器人</div></div><div class="add-config settings-add"><input v-model="dingtalkDraft.label" placeholder="备注，例如：运维通知群"><input v-model="dingtalkDraft.webhook_url" type="password" autocomplete="new-password" placeholder="钉钉机器人 Webhook 地址"><input v-model="dingtalkDraft.secret" type="password" autocomplete="new-password" placeholder="加签密钥（可留空）"><button class="primary" type="button" @click="addDingtalkHook">添加</button></div></div>
            </template>

            <template v-else-if="settingsSection==='network'">
              <div class="settings-section-head"><h2>网络</h2><p>4G 是设备能力，不在设置页重复提供危险开关；这里只展示状态并跳转到设备管理。</p></div>
              <div class="settings-group"><div class="setting-row"><div><strong>4G 控制服务</strong><p>{{ fourG.available ? '宿主机 4G 控制服务可用' : '当前未安装或不可用' }}</p></div><span :class="['settings-status',fourG.available?'ok':'']">{{ fourG.available?'可用':'不可用' }}</span></div><div class="setting-row"><div><strong>已登记设备</strong><p>在线 {{ onlineCount }} 台，共 {{ devices.length }} 台。</p></div><button type="button" class="contact-edit" @click="view='devices'">前往设备管理</button></div></div>
              <div v-if="fourG.interfaces?.length" class="network-summary"><div v-for="item in fourG.interfaces" :key="item.interface" class="network-summary-row"><div><strong>{{ deviceName(item.device_id) }}</strong><p>{{ item.interface }} · {{ item.addresses?.join(', ') || '无地址' }}</p></div><span :class="['settings-status',item.enabled&&item.addresses?.length?'ok':'']">{{ item.enabled ? (item.addresses?.length?'已连接':'已开启') : '已关闭' }}</span></div></div>
            </template>

            <template v-else-if="settingsSection==='security' && isAdmin">
              <div class="settings-section-head"><h2>用户与 API</h2><p>网页用户用账号密码；API 凭据只留给外部程序和自动化，不用于网页登录。</p></div>
              <div class="settings-subsection first"><div class="integration-heading"><div><strong>用户</strong><p>管理员账号受保护；普通 user 可停用、重置密码或删除。</p></div><span>{{ users.filter(x=>x.enabled).length }}/{{ users.length }} 已启用</span></div><div class="config-list"><div v-for="item in users" :key="item.username" class="config-item"><span :class="['status-dot',!item.enabled?'bad':'']"></span><div><strong>{{ item.username }}</strong><p>{{ item.role==='admin'?'管理员':'普通用户' }} · {{ item.enabled?'已启用':'已停用' }}</p></div><button v-if="item.role!=='admin'" type="button" class="text-button" @click="toggleUser(item)">{{ item.enabled?'停用':'启用' }}</button><button type="button" class="text-button" @click="resetUserPassword(item)">重置密码</button><button v-if="item.role!=='admin'" type="button" class="text-button danger" @click="deleteUser(item)">删除</button></div></div><div class="add-config settings-add two-plus"><input v-model.trim="userDraft.username" maxlength="32" placeholder="新用户名"><input v-model="userDraft.password" type="password" autocomplete="new-password" placeholder="初始密码（至少 8 位）"><button class="primary" type="button" @click="createUser">创建 user</button></div></div>
              <div class="settings-subsection"><div class="integration-heading"><div><strong>机器 API 凭据</strong><p>仅供 ERP、Webhook 调用方或自动化脚本使用。</p></div></div><div class="config-list"><div v-for="item in adminKeys" :key="item.id" class="config-item"><div><strong>{{ item.label }}</strong><p>{{ item.scope==='read'?'只读':'读写' }} · {{ item.created_at }}</p></div><button type="button" class="text-button" @click="renameAdminKey(item)">改备注</button><button type="button" class="text-button danger" @click="deleteAdminKey(item)">撤销</button></div><div v-if="!adminKeys.length" class="list-empty">暂无机器 API 凭据</div></div><div class="add-config settings-add two-plus"><input v-model="adminKeyDraft.label" maxlength="80" placeholder="用途备注，例如：ERP接口"><select v-model="adminKeyDraft.scope"><option value="read">只读</option><option value="write">读写</option></select><button type="button" class="primary" @click="createAdminKey">创建凭据</button></div><div v-if="createdApiToken" class="created-token"><strong>新凭据仅显示一次，请立即保存</strong><input :value="createdApiToken" readonly aria-label="新 API 凭据"><button type="button" @click="copyAdminKey">复制</button></div></div><p v-if="adminError" class="form-error">{{ adminError }}</p>
            </template>
          </div>
        </div>
      </section>
    </main>

    <div v-if="contactEditorOpen" class="modal-backdrop" @click.self="contactEditorOpen=false">
      <form class="compose contact-form" @submit.prevent="saveContact"><header><h2>{{ contactOriginalPhone?'编辑联系人':'添加联系人' }}</h2><button type="button" class="close" @click="contactEditorOpen=false">关闭</button></header><label>电话号码<input v-model.trim="contactDraft.phone" inputmode="tel" autocomplete="tel" pattern="\+?[0-9]{5,20}" maxlength="21" :readonly="!!contactOriginalPhone" required placeholder="例如：13800138000"></label><label>姓名或显示备注<input v-model.trim="contactDraft.name" maxlength="80" required placeholder="例如：张先生、客服、快递"></label><label>详细备注<textarea v-model="contactDraft.note" maxlength="500" placeholder="公司、用途等补充信息（可选）"></textarea><small>{{ contactDraft.note.length }}/500</small></label><p v-if="contactOriginalPhone" class="hint">电话号码是联系人索引；如需改号码，请新建联系人。</p><div v-if="contactError" class="form-error">{{ contactError }}</div><footer><button type="button" @click="contactEditorOpen=false">取消</button><button class="primary" type="submit">保存</button></footer></form>
    </div>
    <div v-if="blacklistEditorOpen" class="modal-backdrop" @click.self="blacklistEditorOpen=false">
      <form class="compose contact-form" @submit.prevent="saveBlacklist"><header><h2>{{ blacklistOriginalPhone?'编辑黑名单规则':'添加黑名单规则' }}</h2><button type="button" class="close" @click="blacklistEditorOpen=false">关闭</button></header><label>匹配方式<select v-model="blacklistDraft.match_type"><option value="exact">精确匹配</option><option value="contains">包含匹配</option><option value="regex">正则表达式</option></select></label><label>{{ blacklistDraft.match_type==='exact'?'电话号码':'匹配规则' }}<input v-model.trim="blacklistDraft.phone" :inputmode="blacklistDraft.match_type==='exact'?'tel':'text'" autocomplete="off" :pattern="blacklistDraft.match_type==='exact'?'\\+?[0-9]{5,20}':undefined" :maxlength="blacklistDraft.match_type==='exact'?21:160" :readonly="!!blacklistOriginalPhone" required :placeholder="blacklistDraft.match_type==='exact'?'例如：10086':blacklistDraft.match_type==='contains'?'例如：1069':'例如：^95\\d{3}$'"></label><p v-if="blacklistDraft.match_type==='contains'" class="hint">发送方号码中只要包含该文本就会命中。</p><p v-if="blacklistDraft.match_type==='regex'" class="hint">使用正则搜索发送方号码；保存时会校验表达式是否合法。</p><label>显示备注<input v-model.trim="blacklistDraft.label" maxlength="80" placeholder="例如：广告短信（可选）"></label><label>详细备注<textarea v-model="blacklistDraft.note" maxlength="500" placeholder="加入原因等补充信息（可选）"></textarea><small>{{ blacklistDraft.note.length }}/500</small></label><div class="blacklist-notice compact-notice">命中规则的短信只存入黑名单，机器人和通用 Webhook 均不推送。</div><div v-if="blacklistError" class="form-error">{{ blacklistError }}</div><footer><button type="button" @click="blacklistEditorOpen=false">取消</button><button class="primary" type="submit">保存</button></footer></form>
    </div>
    <div v-if="adRuleEditorOpen" class="modal-backdrop" @click.self="adRuleEditorOpen=false">
      <form class="compose contact-form" @submit.prevent="saveAdRule">
        <header><h2>{{ adRuleOriginalId?'编辑广告规则':'添加广告规则' }}</h2><button type="button" class="close" @click="adRuleEditorOpen=false">关闭</button></header>
        <label>匹配范围<select v-model="adRuleDraft.field"><option value="body">短信内容</option><option value="phone">发送号码</option><option value="both">号码 + 内容</option></select></label>
        <label>匹配方式<select v-model="adRuleDraft.match_type"><option value="contains">包含匹配</option><option value="regex">正则表达式</option></select></label>
        <label>过滤规则<input v-model.trim="adRuleDraft.pattern" maxlength="160" required :placeholder="adRuleDraft.match_type==='regex'?'例如：(退订|拒收请回复)$':'例如：退订'"></label>
        <p class="hint">广告规则只负责归档广告，不会加入黑名单；黑名单优先级高于广告过滤。</p>
        <label>规则备注<input v-model.trim="adRuleDraft.label" maxlength="80" placeholder="例如：营销退订短信"></label>
        <label class="toggle-label"><input v-model="adRuleDraft.enabled" type="checkbox">启用此规则</label>
        <div v-if="adRuleError" class="form-error">{{ adRuleError }}</div>
        <footer><button type="button" @click="adRuleEditorOpen=false">取消</button><button class="primary" type="submit">保存</button></footer>
      </form>
    </div>
  </div>
</template>
