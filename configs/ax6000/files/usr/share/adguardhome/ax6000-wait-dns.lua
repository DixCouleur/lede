#!/usr/bin/lua
-- Check the local DNS handler without depending on WAN or the later Mihomo boot.
local nixio = require "nixio"
local host = arg[1] or "127.0.0.1"
local port = tonumber(arg[2] or "5335")
local budget = tonumber(arg[3] or "15")
assert(host == "127.0.0.1", "readiness must use loopback")
assert(port and port >= 1 and port <= 65535 and port % 1 == 0, "invalid port")
assert(budget and budget >= 0.1 and budget <= 60, "invalid wait budget")

local function clock()
    -- Boot may change the wall clock when NTP starts; uptime stays monotonic.
    local file = assert(io.open("/proc/uptime", "r"))
    local value = assert(file:read("*n"))
    file:close()
    return value
end

local function u16(value)
    return string.char(math.floor(value / 256) % 256, value % 256)
end

local function from_u16(value, offset)
    return value:byte(offset) * 256 + value:byte(offset + 1)
end

-- This profile answers AAAA locally with empty NOERROR, before any forwarding.
local question = "\16ax6000-readiness\7invalid\0" .. u16(28) .. u16(1)
local txid = nixio.getpid() % 65536
local started = clock()
local deadline = started + budget

local function wait_for(socket, event, until_time)
    local remaining = until_time - clock()
    if remaining <= 0 then return false end
    local count = nixio.poll({{fd = socket, events = nixio.poll_flags(event)}},
        math.max(1, math.floor(remaining * 1000)))
    return count and count > 0
end

local function valid_reply(reply, request)
    if not reply or #reply < #request then return false end
    local high, low = reply:byte(3, 4)
    return reply:sub(1, 2) == request:sub(1, 2)
        and math.floor(high / 8) == 16 -- response, opcode QUERY
        and high % 4 < 2 -- not truncated
        and (low % 16 == 0 or low % 16 == 3)
        and from_u16(reply, 5) == 1
        and reply:sub(13, 12 + #question) == question
end

local function recv_exact(socket, length, until_time)
    local parts, size = {}, 0
    while size < length do
        if not wait_for(socket, "in", until_time) then return nil end
        local data = socket:recv(length - size)
        if not data or #data == 0 then return nil end
        size = size + #data
        parts[#parts + 1] = data
    end
    return table.concat(parts)
end

local function exchange(protocol)
    local socket = nixio.socket("inet", protocol == "udp" and "dgram" or "stream")
    if not socket then return false end
    socket:setblocking(false)
    local until_time = math.min(deadline, clock() + 0.3)
    local connected, errno = socket:connect(host, port)
    if not connected and errno ~= nixio.const.EINPROGRESS then
        socket:close()
        return false
    end
    if protocol == "tcp" and (not wait_for(socket, "out", until_time)
        or socket:getopt("socket", "error") ~= 0) then
        socket:close()
        return false
    end
    txid = (txid + 1) % 65536
    local request = u16(txid) .. "\1\0\0\1\0\0\0\0\0\0" .. question
    local wire = protocol == "tcp" and u16(#request) .. request or request
    local offset = 0
    while offset < #wire do
        if not wait_for(socket, "out", until_time) then break end
        local count = socket:send(wire:sub(offset + 1))
        if not count or count <= 0 then break end
        offset = offset + count
    end
    local reply
    if offset == #wire then
        if protocol == "tcp" then
            local prefix = recv_exact(socket, 2, until_time)
            local length = prefix and from_u16(prefix, 1)
            if length and length >= #request and length <= 4096 then
                reply = recv_exact(socket, length, until_time)
            end
        elseif wait_for(socket, "in", until_time) then
            reply = socket:recv(4096)
        end
    end
    socket:close()
    return valid_reply(reply, request)
end

local attempts = 0
repeat
    attempts = attempts + 1
    local udp_ready = exchange("udp")
    local tcp_ready = exchange("tcp")
    if udp_ready and tcp_ready then
        print(string.format("MosDNS ready on %s:%d (UDP/TCP, %.2fs, %d attempts)",
            host, port, clock() - started, attempts))
        os.exit(0)
    end
    local remaining = deadline - clock()
    if remaining > 0 then nixio.poll({}, math.min(200, math.floor(remaining * 1000))) end
until clock() >= deadline

io.stderr:write(string.format("MosDNS not ready on %s:%d after %.2fs (%d attempts)\n",
    host, port, clock() - started, attempts))
os.exit(1)
