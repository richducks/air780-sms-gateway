MOBILE_UI = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Air780 短信中心</title><style>
:root{font-family:system-ui,-apple-system,"Noto Sans SC",sans-serif;color:#172033;background:#f3f6fb}*{box-sizing:border-box}body{margin:0}header{background:#183153;color:white;padding:18px 16px}header h1{font-size:21px;margin:0}.wrap{max-width:920px;margin:auto;padding:14px}.card{background:#fff;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 3px 14px #17335b12}h2{font-size:17px;margin:0 0 12px}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}input,select,textarea,button{width:100%;font:inherit;border-radius:9px;border:1px solid #ccd5e2;padding:11px}textarea{min-height:88px;resize:vertical}button{background:#1769e0;color:white;border:0;font-weight:650}.device{padding:10px 0;border-top:1px solid #edf0f5}.device:first-child{border:0}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}.online{background:#18a058}.offline{background:#aaa}.muted{font-size:12px;color:#697386}.msg{border-top:1px solid #edf0f5;padding:11px 0}.msg:first-child{border:0}.body{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}.pill{font-size:11px;background:#edf3ff;border-radius:10px;padding:2px 7px}.error{color:#b42318;margin-top:8px}.toolbar{display:flex;gap:8px;margin-bottom:10px}.toolbar input{flex:1}.toolbar button{width:auto}@media(max-width:600px){.row{grid-template-columns:1fr}.wrap{padding:10px}.card{border-radius:11px}}
</style></head><body><header><h1>Air780 短信中心</h1></header><main class="wrap">
<section class="card"><h2>API 访问</h2><div class="toolbar"><input id="token" type="password" placeholder="Bearer Token（未配置可留空）"><button id="save">保存</button></div><div class="muted">凭证只保存在当前浏览器。</div></section>
<section class="card"><h2>设备</h2><div id="devices">正在读取…</div></section>
<section class="card"><h2>发送短信</h2><div class="row"><select id="device"><option value="">自动选择唯一在线设备</option></select><input id="phone" inputmode="tel" placeholder="手机号"></div><textarea id="body" maxlength="134" placeholder="短信内容（最多 134 个字符）"></textarea><button id="send">发送</button><div id="result" class="error"></div></section>
<section class="card"><h2>统一收件箱</h2><div id="messages">正在读取…</div></section></main>
<script>
const $=id=>document.getElementById(id);$('token').value=localStorage.getItem('smsToken')||'';
$('save').onclick=()=>{localStorage.setItem('smsToken',$('token').value.trim());refresh()};
function headers(json=false){const h={};const t=$('token').value.trim();if(t)h.Authorization='Bearer '+t;if(json)h['Content-Type']='application/json';return h}
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
async function api(path,opt={}){const r=await fetch(path,{...opt,headers:{...headers(!!opt.body),...(opt.headers||{})}});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j}
async function refresh(){try{const [ds,ms]=await Promise.all([api('/api/v1/devices'),api('/api/v1/messages?limit=100')]);renderDevices(ds.devices);renderMessages(ms.messages)}catch(e){$('devices').textContent='读取失败：'+e.message;$('messages').textContent='读取失败：'+e.message}}
function renderDevices(items){const box=$('devices'),sel=$('device'),current=sel.value;box.replaceChildren();sel.replaceChildren(new Option('自动选择唯一在线设备',''));for(const d of items){const div=node('div',undefined,'device');const dot=node('span','', 'dot '+(d.status==='online'?'online':'offline'));div.append(dot,node('strong',d.label||d.device_id),node('div','IMEI '+d.imei+' · '+d.status+(d.serial_port?' · '+d.serial_port:''),'muted'));box.append(div);if(d.status==='online')sel.add(new Option((d.label||d.imei)+' · '+d.serial_port,d.device_id))}if(!items.length)box.textContent='暂无设备';sel.value=current}
function renderMessages(items){const box=$('messages');box.replaceChildren();for(const m of items){const div=node('div',undefined,'msg');const title=node('div');title.append(node('span',m.direction==='inbound'?'收到':'发出','pill'),document.createTextNode(' '+m.phone+' · '+m.status));div.append(title,node('div',m.body,'body'),node('div',(m.device_id||'未关联设备')+' · '+m.created_at,'muted'));box.append(div)}if(!items.length)box.textContent='暂无短信'}
$('send').onclick=async()=>{const out=$('result');out.textContent='发送中…';try{const p={phone:$('phone').value.trim(),body:$('body').value,device_id:$('device').value||undefined};const m=await api('/api/v1/messages',{method:'POST',body:JSON.stringify(p)});out.style.color='#18794e';out.textContent='已进入发送队列，编号 '+m.id;$('body').value='';setTimeout(refresh,1200)}catch(e){out.style.color='#b42318';out.textContent=e.message}};
refresh();setInterval(refresh,5000);
</script></body></html>'''


def openapi_document(base_url: str = "http://127.0.0.1:8787") -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Air780 SMS Gateway API", "version": "2.0.0"},
        "servers": [{"url": base_url}],
        "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
        "security": [{"bearerAuth": []}],
        "paths": {
            "/health": {"get": {"security": [], "summary": "网关和设备状态", "responses": {"200": {"description": "OK"}}}},
            "/api/v1/devices": {"get": {"summary": "列出设备", "responses": {"200": {"description": "设备列表"}}}},
            "/api/v1/devices/{device_id}": {"patch": {"summary": "设置设备名称", "parameters": [{"in": "path", "name": "device_id", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "已更新"}}}},
            "/api/v1/messages": {
                "get": {"summary": "统一收件箱", "parameters": [{"in": "query", "name": "direction", "schema": {"type": "string", "enum": ["inbound", "outbound"]}}, {"in": "query", "name": "device_id", "schema": {"type": "string"}}, {"in": "query", "name": "limit", "schema": {"type": "integer", "default": 50}}], "responses": {"200": {"description": "短信列表"}}},
                "post": {"summary": "指定设备发送短信", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["phone", "body"], "properties": {"device_id": {"type": "string"}, "phone": {"type": "string"}, "body": {"type": "string", "maxLength": 134}}}}}}, "responses": {"202": {"description": "已进入发送队列"}}}
            },
            "/api/v1/messages/{id}": {"get": {"summary": "查询发送状态", "parameters": [{"in": "path", "name": "id", "required": True, "schema": {"type": "integer"}}], "responses": {"200": {"description": "短信详情"}}}}
        }
    }
