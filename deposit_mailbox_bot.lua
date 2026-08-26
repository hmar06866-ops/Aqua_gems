--[[
  Aqua Gems — example Mailbox deposit + withdraw bot for Pet Simulator 99

  HOW IT WORKS
  1. Players mail diamonds to THIS account with message = deposit code (DEP-XXXX)
  2. This script claims the mail and POSTs to your website /api/deposit
  3. It also polls /api/pending_withdraws and mails diamonds back

  REQUIREMENTS
  - Run on an executor / dedicated host that can call HttpService
  - Set website URL + TRADEBOT_SECRET to match aqua_website/config.py
  - The bot Roblox account must be the same as BOT_ROBLOX_USERNAME

  WARNING: Use only on accounts you own. Follow Roblox ToS.
]]

local HttpService = game:GetService("HttpService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

-- ========== CONFIG ==========
local WEBSITE = "aqua-gems.com"   -- no trailing slash
local SECRET  = "aqua-discord-website-1010"  -- must match TRADEBOT_SECRET
local POLL_SECONDS = 8
-- ============================

local function request(opts)
    -- Synapse / script-ware / Fluxus style; adapt if your executor differs
    if syn and syn.request then
        return syn.request(opts)
    elseif http_request then
        return http_request(opts)
    elseif request then
        return request(opts)
    else
        error("No HTTP request function available")
    end
end

local function postDeposit(gems, message, robloxId)
    local body = HttpService:JSONEncode({
        secret = SECRET,
        gems = gems,
        message = message,
        code = message,
        roblox_id = tostring(robloxId or ""),
    })
    local ok, res = pcall(function()
        return request({
            Url = WEBSITE .. "/api/deposit",
            Method = "POST",
            Headers = {
                ["Content-Type"] = "application/json",
                ["X-Tradebot-Secret"] = SECRET,
            },
            Body = body,
        })
    end)
    if ok and res then
        print("[Aqua] Deposit API status:", res.StatusCode, res.Body)
        return res.StatusCode == 200
    end
    print("[Aqua] Deposit API failed")
    return false
end

local function getPendingWithdraws()
    local ok, res = pcall(function()
        return request({
            Url = WEBSITE .. "/api/pending_withdraws?secret=" .. SECRET,
            Method = "GET",
            Headers = { ["X-Tradebot-Secret"] = SECRET },
        })
    end)
    if not ok or not res or res.StatusCode ~= 200 then
        return {}
    end
    local data = HttpService:JSONDecode(res.Body)
    return data.withdraws or {}
end

local function markWithdrawComplete(code, success)
    pcall(function()
        request({
            Url = WEBSITE .. "/api/withdraw_complete",
            Method = "POST",
            Headers = {
                ["Content-Type"] = "application/json",
                ["X-Tradebot-Secret"] = SECRET,
            },
            Body = HttpService:JSONEncode({
                secret = SECRET,
                code = code,
                success = success,
            }),
        })
    end)
end

local function getMail()
    local ok, inbox = pcall(function()
        return ReplicatedStorage.Network["Mailbox: Get"]:InvokeServer().Inbox
    end)
    if ok then return inbox or {} end
    return {}
end

local function claimMail(uuids)
    pcall(function()
        ReplicatedStorage.Network["Mailbox: Claim"]:InvokeServer(uuids)
    end)
end

local function sendMail(username, gems, message)
    -- Item id for Diamonds may change; adjust if needed for current PS99 version
    pcall(function()
        ReplicatedStorage.Network["Mailbox: Send"]:InvokeServer(
            username,
            message or "Aqua Withdraw",
            "Currency",
            "Diamonds",  -- or the internal diamond item hash if required
            gems
        )
    end)
end

print("[Aqua] Mailbox deposit/withdraw bot started")
print("[Aqua] Website:", WEBSITE)

while true do
    -- 1) Process incoming deposit mails
    local mail = getMail()
    local toClaim = {}
    for _, gift in pairs(mail) do
        local msg = tostring(gift.Message or "")
        local amount = 0
        if gift.Item and gift.Item.data and gift.Item.data._am then
            amount = tonumber(gift.Item.data._am) or 0
        end
        if amount > 0 and msg ~= "" then
            print("[Aqua] Mail deposit:", amount, "msg=", msg)
            if postDeposit(amount, msg, gift.SenderId) then
                table.insert(toClaim, gift.uuid)
            end
        end
    end
    if #toClaim > 0 then
        claimMail(toClaim)
    end

    -- 2) Fulfil pending withdraws
    local withdraws = getPendingWithdraws()
    for _, w in ipairs(withdraws) do
        print("[Aqua] Sending withdraw", w.amount, "to", w.roblox_username)
        local ok = pcall(function()
            sendMail(w.roblox_username, w.amount, w.code)
        end)
        markWithdrawComplete(w.code, ok)
        task.wait(2)
    end

    task.wait(POLL_SECONDS)
end
