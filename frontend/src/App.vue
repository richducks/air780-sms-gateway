<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const view = ref('messages')
const navIds = ['messages','devices','contacts','favorites','blacklist','settings']
const navLabels = {messages:'短信',devices:'设备',contacts:'通讯录',favorites:'收藏',blacklist:'黑名单',settings:'设置'}
const navDescriptions = {messages:'查看和发送短信',devices:'管理短信设备和 4G 网络',contacts:'号码与备注',favorites:'保存的重要短信',blacklist:'拦截与归档',settings:'连接与界面偏好'}
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
const selectedConversationKey = ref(null)
const mobileConversationOpen = ref(false)
const deviceFilter = ref('all')
const loading = ref(false)
const error = ref('')
const authRequired = ref(false)
const authTokenDraft = ref('')
const composeOpen = ref(false)
const contactEditorOpen = ref(false)
const contactOriginalPhone = ref('')
const contactDraft = ref({phone:'',name:'',note:''})
const contactError = ref('')
const blacklistEditorOpen = ref(false)
const blacklistOriginalPhone = ref('')
const blacklistDraft = ref({phone:'',label:'',note:''})
const blacklistError = ref('')
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
const apiProfiles = ref(JSON.parse(localStorage.getItem('sms.apiProfiles') || '[]'))
const apiDraft = ref({label:'', apiBase:'', token:''})
const savedNotice = ref('')
const adminPassword = ref('')
const adminSession = ref(sessionStorage.getItem('sms.adminSession') || '')
const adminKeys = ref([])
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
  token: localStorage.getItem('sms.token') || '',
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
  for (const message of messages.value.filter(message => !message.blacklisted)) {
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
  conversationKey(m) === selectedConversationKey.value
))
const activeDeviceOnline = computed(() => devices.value.some(d =>
  d.device_id === activeConversation.value?.device_id && d.status === 'online'
))
const onlineCount = computed(() => devices.value.filter(d => d.status === 'online').length)
const favorites = computed(() => messages.value.filter(m => m.favorite))
const blacklistedMessages = computed(() => messages.value.filter(m => m.blacklisted))
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
  if (settings.value.token) headers.Authorization = `Bearer ${settings.value.token}`
  const response = await fetch(apiUrl(path), { ...options, headers: {...headers, ...(options.headers || {})} })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`)
  return data
}
async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const [m, d, c, b, i, ding, network] = await Promise.all([api('/api/v1/messages?limit=200'), api('/api/v1/devices'), api('/api/v1/contacts'), api('/api/v1/blacklist'), api('/api/v1/integrations/feishu'), api('/api/v1/integrations/dingtalk'), api('/api/v1/network/4g').catch(exc => ({available:false,enabled:false,interfaces:[],error:exc.message}))])
    messages.value = m.messages
    devices.value = d.devices
    contacts.value = c.contacts
    blacklist.value = b.blacklist
    integrations.value = i
    dingtalkIntegrations.value = ding
    fourG.value = network
    if (!conversations.value.some(c => c.key === selectedConversationKey.value))
      selectedConversationKey.value = conversations.value[0]?.key || null
    error.value = ''
    authRequired.value = false
  } catch (e) {
    error.value = e.message
    authRequired.value = e.message === 'invalid bearer token'
  } finally { loading.value = false }
}
async function connectWithToken() {
  const token = authTokenDraft.value.trim()
  if (!token) return
  settings.value.token = token
  localStorage.setItem('sms.token', token)
  authTokenDraft.value = ''
  await refresh()
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
  blacklistDraft.value = {phone:phone || '', label:item?.label || '', note:item?.note || ''}
  blacklistError.value = ''
  blacklistEditorOpen.value = true
}
async function saveBlacklist() {
  const phone = blacklistDraft.value.phone.trim()
  blacklistError.value = ''
  try {
    await api(`/api/v1/blacklist/${encodeURIComponent(phone)}`, {
      method:'PUT', body:JSON.stringify({label:blacklistDraft.value.label, note:blacklistDraft.value.note})
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
async function saveSettings() {
  localStorage.setItem('sms.apiBase', settings.value.apiBase.trim())
  localStorage.setItem('sms.token', settings.value.token.trim())
  localStorage.setItem('sms.theme', settings.value.theme)
  localStorage.setItem('sms.refresh', String(settings.value.refresh))
  savedNotice.value = '设置已保存'
  setTimeout(() => savedNotice.value = '', 2400)
  applyTheme(); schedule(); refresh()
}
async function adminRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), {...options, headers:{'Content-Type':'application/json','X-Admin-Session':adminSession.value}})
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || `请求失败 ${response.status}`)
  return data
}
async function loadAdminKeys() {
  if (!adminSession.value) return
  try { adminKeys.value = (await adminRequest('/api/v1/admin/keys')).keys; adminError.value = '' }
  catch(e) { adminSession.value = ''; sessionStorage.removeItem('sms.adminSession'); adminError.value = e.message }
}
async function loginAdmin() {
  adminError.value = ''
  try {
    const response = await fetch(apiUrl('/api/v1/admin/login'), {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:adminPassword.value})})
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '登录失败')
    adminSession.value = data.session; sessionStorage.setItem('sms.adminSession',data.session)
    adminPassword.value = ''; await loadAdminKeys()
  } catch(e) { adminError.value = e.message }
}
async function changeAdminPassword() {
  passwordError.value = ''; passwordNotice.value = ''
  if (passwordDraft.value.next !== passwordDraft.value.confirm) {
    passwordError.value = '两次输入的新密码不一致'; return
  }
  if (passwordDraft.value.next.length < 12 || passwordDraft.value.next.length > 128) {
    passwordError.value = '新密码须为 12–128 个字符'; return
  }
  passwordBusy.value = true
  try {
    await adminRequest('/api/v1/admin/password', {method:'PUT', body:JSON.stringify({
      current_password:passwordDraft.value.current, new_password:passwordDraft.value.next
    })})
    passwordDraft.value = {current:'', next:'', confirm:''}
    adminSession.value = ''; sessionStorage.removeItem('sms.adminSession')
    createdApiToken.value = ''; passwordNotice.value = '密码已更新，请用新密码重新登录'
  } catch(e) { passwordError.value = e.message }
  finally { passwordBusy.value = false }
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
function persistApiProfiles() { localStorage.setItem('sms.apiProfiles', JSON.stringify(apiProfiles.value)) }
function newProfileId() { return `${Date.now()}-${Math.random().toString(36).slice(2)}` }
function addApiProfile() {
  if (!apiDraft.value.label.trim()) { error.value = '请填写 API 配置备注'; return }
  apiProfiles.value.push({id:newProfileId(), ...apiDraft.value})
  persistApiProfiles(); apiDraft.value = {label:'',apiBase:'',token:''}
}
function useApiProfile(profile) {
  settings.value.apiBase = profile.apiBase
  settings.value.token = profile.token
  saveSettings()
}
function renameApiProfile(profile) {
  const label = prompt('输入 API 配置备注', profile.label)
  if (label === null || !label.trim()) return
  profile.label = label.trim()
  persistApiProfiles()
}
function deleteApiProfile(id) {
  if (!confirm('确认删除这条 API 配置？')) return
  apiProfiles.value = apiProfiles.value.filter(x => x.id !== id); persistApiProfiles()
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
onMounted(() => { applyTheme(); refresh(); schedule(); loadAdminKeys() })
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
          <svg v-else-if="id==='blacklist'" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m6 18 12-12"/></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M10.3 2.9h3.4l.5 2.1c.6.2 1.2.4 1.7.7l1.9-1.1 2.4 2.4-1.1 1.9c.3.5.5 1.1.7 1.7l2.1.5v3.4l-2.1.5c-.2.6-.4 1.2-.7 1.7l1.1 1.9-2.4 2.4-1.9-1.1c-.5.3-1.1.5-1.7.7l-.5 2.1h-3.4l-.5-2.1c-.6-.2-1.2-.4-1.7-.7l-1.9 1.1-2.4-2.4 1.1-1.9c-.3-.5-.5-1.1-.7-1.7l-2.1-.5v-3.4l2.1-.5c.2-.6.4-1.2.7-1.7L3.8 7l2.4-2.4 1.9 1.1c.5-.3 1.1-.5 1.7-.7z"/><circle cx="12" cy="12.8" r="3.1"/></svg>
          <span class="nav-copy"><span>{{ navLabels[id] }}</span><small v-if="view===id">{{ navDescriptions[id] }}</small></span><b v-if="id==='messages'">{{ messages.length-blacklistedMessages.length }}</b><i v-else-if="id==='devices'" :class="onlineCount?'ok':''">{{ onlineCount }}</i><i v-else-if="id==='contacts'">{{ contacts.length }}</i><i v-else-if="id==='favorites'">{{ favorites.length }}</i><i v-else-if="id==='blacklist'">{{ blacklistedMessages.length }}</i><span class="nav-grip" aria-hidden="true">⋮⋮</span>
        </button>
      </nav>
      <div class="sidebar-foot">
        <div class="sidebar-device-list" aria-label="设备信号列表"><div v-for="d in devices" :key="d.device_id" class="sidebar-device-row" :title="`${d.label || d.imei} · ${deviceSignalLabel(d)} · ${deviceDataLabel(d)}`"><span class="sidebar-device-name"><strong>{{ d.label || d.imei }}</strong></span><span class="phone-status" :aria-label="`${deviceSignalLabel(d)}，${deviceDataLabel(d)}`"><span class="signal-bars" :class="{on:deviceSignalBars(d)>0}" aria-hidden="true"><i v-for="bar in 4" :key="bar" :class="{active:deviceSignalBars(d)!==null && bar<=deviceSignalBars(d)}"></i></span><span class="network-mark" :class="{connected:deviceNetworkConnected(d)}" aria-hidden="true">4G</span></span></div><div v-if="!devices.length" class="sidebar-device-empty">暂无设备</div></div>
        <div class="gateway"><span :class="['status-dot', error?'bad':'']"></span>{{ error ? '连接异常' : '服务正常' }}</div>
      </div>
      <div class="sidebar-resizer" role="separator" aria-label="拖动调整菜单栏宽度" aria-orientation="vertical" @pointerdown="startSidebarDrag"></div>
    </aside>

    <main v-if="authRequired && view!=='settings'" class="auth-gate">
      <div class="auth-card"><span class="auth-symbol" aria-hidden="true">✉</span><h1>连接短信网关</h1><p>当前浏览器尚未配置有效的 API Token。每个浏览器需要分别保存一次，才能查看短信和设备。</p><form @submit.prevent="connectWithToken"><label for="gateway-token">API Token</label><input id="gateway-token" v-model="authTokenDraft" type="password" autocomplete="off" placeholder="输入服务器上的 API Token" required><button class="primary" type="submit">连接</button></form><small>Token 保存在当前浏览器。可从 104 服务器的 <code>/home/ubuntu-server/air780/.env.docker</code> 获取。</small></div>
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
          <div class="device-actions"><span :class="['device-status',d.status!=='online'?'offline':'']">{{ d.status==='online'?'在线':'离线' }}</span><button v-if="editingDevice!==d.device_id" class="text-button" type="button" @click="beginRename(d)">{{ d.label?'修改备注':'添加备注' }}</button><button v-if="networkForDevice(d)" type="button" class="primary compact" :disabled="!fourG.available || fourGBusy" @click="toggleFourG(d)">{{ fourGBusy?'切换中…':networkForDevice(d).enabled?'关闭 4G':'开启 4G' }}</button></div>
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
      <section v-else-if="view==='blacklist'" class="blacklist-page">
        <div class="blacklist-notice">黑名单号码发来的新短信会保存在这里，且不会推送到飞书、钉钉或通用 Webhook。移出黑名单不会删除已归档短信。</div>
        <div v-if="!blacklist.length" class="empty">黑名单为空</div>
        <div v-for="item in blacklist" :key="item.phone" class="blacklist-card"><div class="blacklist-head"><span class="conversation-avatar blocked">⊘</span><div class="contact-details"><strong>{{ item.label || item.phone }}</strong><p>{{ item.phone }} · {{ item.message_count || 0 }} 条已拦截短信</p><small v-if="item.note">{{ item.note }}</small></div><button class="text-button" type="button" @click="editBlacklist(item.phone)">编辑</button><button class="text-button danger" type="button" @click="deleteBlacklist(item)">移出</button></div><div class="blacklist-messages"><div v-for="m in blacklistedMessages.filter(message => message.phone===item.phone).slice(0,5)" :key="m.id" class="blacklist-message"><p>{{ m.body }}</p><small>{{ fmt(m.created_at) }} · {{ deviceName(m.device_id) }}</small></div><div v-if="!blacklistedMessages.some(message => message.phone===item.phone)" class="list-empty">尚未收到黑名单短信</div></div></div>
        <button class="page-add-fab" type="button" aria-label="添加黑名单号码" title="添加号码" @click="editBlacklist()">＋</button>
      </section>
      <form v-else class="settings-form" @submit.prevent="saveSettings">
        <fieldset><legend>API 配置</legend><div class="setting-description">保存常用网关连接。备注用于区分环境，Token 只保存在当前浏览器且不会回显。</div><div class="config-list"><div v-for="p in apiProfiles" :key="p.id" class="config-item"><div><strong>{{ p.label }}</strong><p>{{ p.apiBase || '当前地址' }} · Token {{ p.token?'已配置':'未配置' }}</p></div><button type="button" class="text-button" @click="renameApiProfile(p)">改备注</button><button type="button" class="text-button" @click="useApiProfile(p)">使用</button><button type="button" class="text-button danger" @click="deleteApiProfile(p.id)">删除</button></div><div v-if="!apiProfiles.length" class="list-empty">暂无已保存配置</div></div><div class="add-config"><input v-model="apiDraft.label" placeholder="备注，例如：本机网关"><input v-model="apiDraft.apiBase" placeholder="服务地址，留空为当前地址"><input v-model="apiDraft.token" type="password" autocomplete="new-password" placeholder="访问 Token，可留空"><button class="primary" type="button" @click="addApiProfile">保存到列表</button></div><label>刷新间隔<select v-model.number="settings.refresh"><option :value="3">3 秒</option><option :value="5">5 秒</option><option :value="10">10 秒</option><option :value="30">30 秒</option></select></label></fieldset>
        <fieldset><legend>管理员与 API 凭据</legend><div class="setting-description">使用 admin 账号管理分配给其他程序的 API 凭据。每把凭据可单独备注和撤销；密钥只在创建时显示一次。</div>
          <div v-if="!adminSession" class="add-config"><input value="admin" aria-label="管理员账号" disabled><input v-model="adminPassword" type="password" autocomplete="current-password" placeholder="管理员密码"><button class="primary" type="button" @click="loginAdmin">登录管理</button></div>
          <template v-else><div class="config-list"><div v-for="item in adminKeys" :key="item.id" class="config-item"><div><strong>{{ item.label }}</strong><p>{{ item.scope==='read'?'只读':'读写' }} · {{ item.created_at }}</p></div><button type="button" class="text-button" @click="renameAdminKey(item)">改备注</button><button type="button" class="text-button danger" @click="deleteAdminKey(item)">撤销</button></div><div v-if="!adminKeys.length" class="list-empty">暂无已分配凭据</div></div><div class="add-config"><input v-model="adminKeyDraft.label" maxlength="80" placeholder="用途备注，例如：报表系统"><select v-model="adminKeyDraft.scope"><option value="read">只读</option><option value="write">读写</option></select><button type="button" class="primary" @click="createAdminKey">创建 API 凭据</button></div><div v-if="createdApiToken" class="created-token"><strong>新凭据（仅显示一次，请立即保存）</strong><input :value="createdApiToken" readonly aria-label="新 API 凭据"><button type="button" @click="copyAdminKey">复制</button></div><div class="admin-password"><strong>修改 admin 密码</strong><div class="admin-password-fields" @keydown.enter.prevent="changeAdminPassword"><input v-model="passwordDraft.current" type="password" autocomplete="current-password" placeholder="当前密码" aria-label="当前 admin 密码"><input v-model="passwordDraft.next" type="password" autocomplete="new-password" placeholder="新密码（至少 12 个字符）" aria-label="新 admin 密码"><input v-model="passwordDraft.confirm" type="password" autocomplete="new-password" placeholder="再次输入新密码" aria-label="确认新 admin 密码"><button type="button" class="primary" :disabled="passwordBusy || !passwordDraft.current || !passwordDraft.next || !passwordDraft.confirm" @click="changeAdminPassword">{{ passwordBusy?'修改中…':'修改密码' }}</button></div><p v-if="passwordError" class="form-error">{{ passwordError }}</p></div><button type="button" class="text-button" @click="adminSession='';sessionStorage.removeItem('sms.adminSession');createdApiToken=''">退出 admin</button></template><p v-if="passwordNotice" class="saved-notice">{{ passwordNotice }}</p><p v-if="adminError" class="form-error">{{ adminError }}</p>
        </fieldset>
        <fieldset><legend>飞书机器人</legend><div class="setting-description">可配置多个飞书群机器人，网关会向所有已启用项推送短信和设备状态。完整 Hook 作为机密保存在网关本机。</div><div class="config-list"><div v-for="item in integrations.webhooks" :key="item.id" class="config-item"><span :class="['status-dot',!item.enabled?'bad':'']"></span><div><strong>{{ item.label }}</strong><p>{{ item.masked }} · {{ item.enabled?'已启用':'已停用' }}</p></div><button type="button" class="text-button" @click="renameHook(item)">改备注</button><button type="button" class="text-button" @click="toggleHook(item)">{{ item.enabled?'停用':'启用' }}</button><button type="button" class="text-button danger" @click="removeHook(item)">删除</button></div><div v-if="!integrations.webhooks.length" class="list-empty">暂无飞书机器人</div></div><div class="add-config"><input v-model="hookDraft.label" placeholder="备注，例如：客服通知群"><input v-model="hookDraft.webhook_url" type="password" autocomplete="new-password" placeholder="飞书机器人 Hook 地址"><button class="primary" type="button" @click="addHook">添加机器人</button></div></fieldset>
        <fieldset><legend>钉钉机器人</legend><div class="setting-description">可配置多个钉钉群自定义机器人，向所有已启用项推送短信和设备状态。若机器人启用了“加签”，请填写以 SEC 开头的密钥；Webhook 和密钥保存在网关本机。</div><div class="config-list"><div v-for="item in dingtalkIntegrations.webhooks" :key="item.id" class="config-item"><span :class="['status-dot',!item.enabled?'bad':'']"></span><div><strong>{{ item.label }}</strong><p>{{ item.masked }} · {{ item.signed?'已加签':'未加签' }} · {{ item.enabled?'已启用':'已停用' }}</p></div><button type="button" class="text-button" @click="renameDingtalkHook(item)">改备注</button><button type="button" class="text-button" @click="toggleDingtalkHook(item)">{{ item.enabled?'停用':'启用' }}</button><button type="button" class="text-button danger" @click="removeDingtalkHook(item)">删除</button></div><div v-if="!dingtalkIntegrations.webhooks.length" class="list-empty">暂无钉钉机器人</div></div><div class="add-config"><input v-model="dingtalkDraft.label" placeholder="备注，例如：运维通知群"><input v-model="dingtalkDraft.webhook_url" type="password" autocomplete="new-password" placeholder="钉钉机器人 Webhook 地址"><input v-model="dingtalkDraft.secret" type="password" autocomplete="new-password" placeholder="加签密钥（可留空）"><button class="primary" type="button" @click="addDingtalkHook">添加机器人</button></div></fieldset>
        <fieldset><legend>外观</legend><label>主题<select v-model="settings.theme" @change="applyTheme"><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select></label></fieldset>
        <button class="primary" type="submit">保存界面设置</button><span v-if="savedNotice" class="saved-notice">{{ savedNotice }}</span><p class="hint">API 配置保存在当前浏览器；飞书和钉钉机器人列表保存在网关本机。</p>
      </form>
    </main>

    <div v-if="contactEditorOpen" class="modal-backdrop" @click.self="contactEditorOpen=false">
      <form class="compose contact-form" @submit.prevent="saveContact"><header><h2>{{ contactOriginalPhone?'编辑联系人':'添加联系人' }}</h2><button type="button" class="close" @click="contactEditorOpen=false">关闭</button></header><label>电话号码<input v-model.trim="contactDraft.phone" inputmode="tel" autocomplete="tel" pattern="\+?[0-9]{5,20}" maxlength="21" :readonly="!!contactOriginalPhone" required placeholder="例如：13800138000"></label><label>姓名或显示备注<input v-model.trim="contactDraft.name" maxlength="80" required placeholder="例如：张先生、客服、快递"></label><label>详细备注<textarea v-model="contactDraft.note" maxlength="500" placeholder="公司、用途等补充信息（可选）"></textarea><small>{{ contactDraft.note.length }}/500</small></label><p v-if="contactOriginalPhone" class="hint">电话号码是联系人索引；如需改号码，请新建联系人。</p><div v-if="contactError" class="form-error">{{ contactError }}</div><footer><button type="button" @click="contactEditorOpen=false">取消</button><button class="primary" type="submit">保存</button></footer></form>
    </div>
    <div v-if="blacklistEditorOpen" class="modal-backdrop" @click.self="blacklistEditorOpen=false">
      <form class="compose contact-form" @submit.prevent="saveBlacklist"><header><h2>{{ blacklistOriginalPhone?'编辑黑名单':'加入黑名单' }}</h2><button type="button" class="close" @click="blacklistEditorOpen=false">关闭</button></header><label>电话号码<input v-model.trim="blacklistDraft.phone" inputmode="tel" autocomplete="tel" pattern="\+?[0-9]{5,20}" maxlength="21" :readonly="!!blacklistOriginalPhone" required placeholder="例如：10086"></label><label>显示备注<input v-model.trim="blacklistDraft.label" maxlength="80" placeholder="例如：广告短信（可选）"></label><label>详细备注<textarea v-model="blacklistDraft.note" maxlength="500" placeholder="加入原因等补充信息（可选）"></textarea><small>{{ blacklistDraft.note.length }}/500</small></label><div class="blacklist-notice compact-notice">加入后，该号码之后收到的短信只存入黑名单，机器人和通用 Webhook 均不推送。</div><div v-if="blacklistError" class="form-error">{{ blacklistError }}</div><footer><button type="button" @click="blacklistEditorOpen=false">取消</button><button class="primary" type="submit">保存</button></footer></form>
    </div>
  </div>
</template>
