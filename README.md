# Aqua Gems — Auto Deposit / Withdraw Website

Quick test website for **Pet Simulator 99** diamond deposits & withdraws, integrated with your existing Discord casino bot data.

## Important reality check

The **official Big Games PS99 API** (`https://ps99.biggamesapi.io`) is **read-only**.  
It can look up public profiles, inventories, and diamond balances — it **cannot** transfer diamonds.

Real auto-deposit systems always use an in-game **trade bot** or **mailbox bot** (Lua) that:

1. Receives diamonds from the player  
2. Calls your website `POST /api/deposit`  
3. Your site credits the Discord-linked balance  

This package gives you:

- A working website with Deposit / Withdraw buttons  
- Official Big Games + Roblox API player lookup  
- Exact API endpoints a Lua bot expects  
- Shared `casino_data.json` with your Discord bot  
- A sample mailbox Lua script  
- Admin simulate endpoint for testing **without** a live Roblox bot  

---

## Folder layout

```
aqua_casino/
  main.py                 ← your Discord bot
  casino_data.json
  config.py
  ...
  aqua_website/           ← THIS folder
    main.py               ← run the website
    config.py
    data_store.py
    biggames_api.py
    requirements.txt
    templates/
    lua/
      deposit_mailbox_bot.lua
    README.md
```

---

## Setup

```bash
cd aqua_website
pip install -r requirements.txt
```

Edit `config.py` (or set env vars):

| Setting | Purpose |
|---------|---------|
| `BOT_ROBLOX_USERNAME` | Your deposit bot’s Roblox name (shown to players) |
| `TRADEBOT_SECRET` | Shared secret the Lua bot must send |
| `ADMIN_API_KEY` | For `/api/simulate_deposit` testing |
| `CASINO_DATA_FILE` | Path to `casino_data.json` (default: `../casino_data.json`) |
| `DISCORD_WEBHOOK_URL` | Optional notifications |

```bash
python main.py
# → http://0.0.0.0:8080
```

---

## Testing without a Roblox bot

1. Open http://localhost:8080/deposit  
2. Enter a **Roblox username that is already verified** in your Discord casino  
3. Create a deposit → you get a code like `DEP-A1B2C3D4`  
4. Simulate the credit:

```bash
curl -X POST http://localhost:8080/api/simulate_deposit \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: aqua-admin-key-change-me" \
  -d '{"code":"DEP-A1B2C3D4"}'
```

Balance is updated in the same `casino_data.json` the Discord bot uses.

---

## Going live with auto deposits

1. Host the website (same machine or public IP / tunnel).  
2. Put a dedicated Roblox account in PS99 Trading Plaza / with Mailbox access.  
3. Run `lua/deposit_mailbox_bot.lua` (or a trade-bot script) on that account.  
4. Set `WEBSITE` + `SECRET` in the Lua file to match your config.  
5. Players create a deposit on the site → trade/mail diamonds with the code → Lua calls `/api/deposit` → balance credited.

### API reference (for Lua)

**Deposit callback**
```
POST /api/deposit
Header: X-Tradebot-Secret: <TRADEBOT_SECRET>
Body: {
  "secret": "...",
  "gems": 100000000,
  "code": "DEP-XXXX",          // or "message"
  "roblox_id": "123456789"     // optional
}
```

**Pending withdraws (poll)**
```
GET /api/pending_withdraws?secret=...
→ { "ok": true, "withdraws": [ { "code", "roblox_username", "amount", ... } ] }
```

**Mark withdraw done**
```
POST /api/withdraw_complete
Body: { "secret": "...", "code": "WTH-XXXX", "success": true }
```

---

## Big Games API usage

| Feature | Endpoint used |
|---------|----------------|
| Username → ID | Roblox `users.roblox.com/v1/usernames/users` |
| Public profile / diamonds | `ps99.biggamesapi.io/v1/players/{slug}?include=profile,inventory` |
| Lookup page | Same |

No write / transfer endpoints exist on the official API.

---

## Sync with Discord bot

- Same `ensure_user` shape, same `balance` / `deposited` / `to_wager` / `history` fields  
- Deposit bonus from `DATA["settings"]["active_deposit_bonus"]` is applied automatically  
- Global stats `total_deposits` / `total_withdraws` are updated  

After a successful auto-deposit, players can immediately use `/balance` and games in Discord.
