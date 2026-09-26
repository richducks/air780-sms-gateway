PROJECT = "air780_usb_sms_bridge"
VERSION = "1.2.1"

sys = require "sys"
sysplus = require "sysplus"

log.setLevel("INFO")
log.info("main", PROJECT, VERSION, rtos.bsp())

wdt.init(9000)
sys.timerLoopStart(wdt.feed, 3000)
mobile.setAuto(10000, 300000, 8, true, 120000)

local bridge_uart = uart.VUART_0
local receive_buffer = ""

local function radio_signal()
    return { rsrp = mobile.rsrp(), csq = mobile.csq() }
end

local function bridge_write(frame)
    local ok, encoded = pcall(json.encode, frame)
    if not ok or not encoded then
        log.error("bridge", "json encode failed")
        return false
    end
    uart.write(bridge_uart, encoded .. "\n")
    return true
end

local function handle_command(line)
    local ok, command = pcall(json.decode, line)
    if not ok or type(command) ~= "table" then
        bridge_write({ type = "error", error = "invalid_json" })
        return
    end

    if command.type == "ping" then
        bridge_write({ type = "pong", project = PROJECT, version = VERSION,
            imei = mobile.imei() or "", status = mobile.status(), signal = radio_signal() })
        return
    end

    if command.type == "sms_send" then
        local request_id = tostring(command.id or "")
        local phone = tostring(command.phone or "")
        local body = tostring(command.body or "")
        if not phone:match("^%+?%d%d%d%d%d%d*$") or body == "" then
            bridge_write({ type = "sms_result", id = request_id, ok = false,
                error = "invalid_phone_or_body" })
            return
        end
        sys.taskInit(function()
            local sent = sms.sendLong(phone, body).wait()
            bridge_write({ type = "sms_result", id = request_id,
                ok = sent and true or false, error = sent and nil or "send_failed" })
        end)
        return
    end

    bridge_write({ type = "error", id = command.id, error = "unknown_command" })
end

local setup_result = uart.setup(bridge_uart, 115200, 8, 1, uart.NONE)
log.info("bridge", "VUART setup", bridge_uart, setup_result)
uart.on(bridge_uart, "receive", function(id, len)
    local chunk = uart.read(id, len)
    if not chunk or #chunk == 0 then return end
    receive_buffer = receive_buffer .. chunk
    if #receive_buffer > 16384 then
        receive_buffer = ""
        bridge_write({ type = "error", error = "input_too_large" })
        return
    end
    while true do
        local newline = receive_buffer:find("\n", 1, true)
        if not newline then break end
        local line = receive_buffer:sub(1, newline - 1):gsub("\r$", "")
        receive_buffer = receive_buffer:sub(newline + 1)
        if #line > 0 then handle_command(line) end
    end
end)

sms.setNewSmsCb(function(sender, body, metadata)
    bridge_write({ type = "sms_received", phone = sender, body = body,
        metadata = metadata or {}, received_at = os.date("!%Y-%m-%dT%H:%M:%SZ") })
end)

sys.taskInit(function()
    while true do
        bridge_write({ type = "ready", project = PROJECT, version = VERSION,
            imei = mobile.imei() or "", status = mobile.status(), signal = radio_signal() })
        sys.wait(5000)
    end
end)

-- Keep the host-side 4G route switch independent from module setup. This
-- enables the USB RNDIS DHCP server; the host still chooses whether to use it.
sys.taskInit(function()
    sys.wait(5000)
    mobile.flymode(0, true)
    sys.wait(500)
    local ok = mobile.config(mobile.CONF_USB_ETHERNET, 3)
    log.info("bridge", "RNDIS NAT setup", ok)
    mobile.flymode(0, false)
    pm.power(pm.USB, false)
    pm.power(pm.USB, true)
end)

sys.run()
