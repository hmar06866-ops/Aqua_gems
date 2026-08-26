"""
Aqua Gems Casino — Auto Deposit / Withdraw Website
Imports data_store + biggames_api from THIS folder (Aqua_Website only).
"""
from __future__ import annotations

import os
import sys
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Force local imports from Aqua_Website/ (not aqua_casino root)
# ---------------------------------------------------------------------------
_WEBSITE_DIR = Path(__file__).resolve().parent
if str(_WEBSITE_DIR) not in sys.path:
    sys.path.insert(0, str(_WEBSITE_DIR))

_ROOT = _WEBSITE_DIR.parent  # aqua_casino/
os.environ.setdefault("CASINO_DATA_FILE", str(_ROOT / "casino_data.json"))

# Settings from env only — does NOT use Discord bot config.py
SECRET_KEY = os.environ.get("SECRET_KEY", "aqua-dev-secret-change-me")
TRADEBOT_SECRET = os.environ.get("TRADEBOT_SECRET", "aqua-tradebot-secret")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "aqua-admin-key")
BOT_ROBLOX_USERNAME = os.environ.get("BOT_ROBLOX_USERNAME", "YourBotUsername")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))
MIN_AMOUNT = int(os.environ.get("MIN_AMOUNT", "1000000"))
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DATA_FILE = os.environ.get("CASINO_DATA_FILE", str(_ROOT / "casino_data.json"))

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
)

from data_store import (
    get_data,
    save_data,
    ensure_user,
    find_user_by_roblox_id,
    find_user_by_roblox_name,
    parse_amount,
    format_amount,
    add_history,
)
from biggames_api import lookup_player

app = Flask(
    __name__,
    template_folder=str(_WEBSITE_DIR / "templates"),
    static_folder=str(_WEBSITE_DIR / "static"),
)
app.secret_key = SECRET_KEY


_OFFLINE_FLAG = _WEBSITE_DIR / "OFFLINE.flag"


@app.before_request
def _check_website_offline():
    path = request.path or ""
    if path.startswith("/api/") or path.startswith("/static/"):
        return None

    offline = _OFFLINE_FLAG.is_file()
    if offline:
        return render_template("maintenance.html"), 503
    return None


def _now() -> int:
    return int(time.time())


def _gen_code(prefix: str = "AQ") -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


def _notify_discord(title: str, description: str, colour: int = 0x57F287):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        import requests

        requests.post(
            DISCORD_WEBHOOK_URL,
            json={
                "embeds": [
                    {
                        "title": title,
                        "description": description,
                        "color": colour,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            },
            timeout=5,
        )
    except Exception:
        pass


def _credit_deposit(discord_user_id: str, amount: int, source: str, data: dict) -> dict:
    user = ensure_user(discord_user_id, data)
    amount_to_credit = amount
    bonus_msg = ""
    active_bonus = data.get("settings", {}).get("active_deposit_bonus")
    if active_bonus and time.time() < active_bonus.get("expires_at", 0):
        pct = active_bonus["percentage"]
        bonus = int(amount * (pct / 100))
        amount_to_credit += bonus
        bonus_msg = f" (+{format_amount(bonus)} {pct}% bonus)"

    user["balance"] += amount_to_credit
    user["deposited"] = user.get("deposited", 0) + amount
    user["to_wager"] = user.get("to_wager", 0) + amount_to_credit
    data["global_stats"]["total_deposits"] = (
        data["global_stats"].get("total_deposits", 0) + amount
    )
    add_history(discord_user_id, f"Deposit ({source})", amount, "Approved", data)

    return {
        "credited": amount_to_credit,
        "bonus_msg": bonus_msg,
        "new_balance": user["balance"],
    }


@app.route("/")
def index():
    return render_template(
        "index.html",
        bot_username=BOT_ROBLOX_USERNAME,
        min_amount=format_amount(MIN_AMOUNT),
    )


@app.route("/lookup", methods=["GET", "POST"])
def lookup():
    result = None
    username = ""
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        if username:
            result = lookup_player(username)
            if result.get("ok"):
                data = get_data()
                uid, u = find_user_by_roblox_id(result["roblox_id"], data)
                if not uid:
                    uid, u = find_user_by_roblox_name(result["roblox_name"], data)
                result["casino_user_id"] = uid
                result["casino_balance"] = format_amount(u["balance"]) if u else None
                result["casino_linked"] = uid is not None
    return render_template("lookup.html", result=result, username=username)


@app.route("/deposit", methods=["GET", "POST"])
def deposit_page():
    if request.method == "POST":
        roblox_username = (request.form.get("roblox_username") or "").strip()
        amount_str = (request.form.get("amount") or "").strip()
        discord_id = (request.form.get("discord_id") or "").strip()

        if not roblox_username or not amount_str:
            flash("Roblox username and amount are required.", "error")
            return redirect(url_for("deposit_page"))

        amount = parse_amount(amount_str)
        if amount is None or amount < MIN_AMOUNT:
            flash(f"Invalid amount. Minimum is {format_amount(MIN_AMOUNT)}.", "error")
            return redirect(url_for("deposit_page"))

        info = lookup_player(roblox_username)
        if not info["ok"]:
            flash(info.get("error") or "Could not verify Roblox username.", "error")
            return redirect(url_for("deposit_page"))

        data = get_data()
        uid = None
        if discord_id.isdigit():
            uid = discord_id
            ensure_user(uid, data)
        else:
            uid, _ = find_user_by_roblox_id(info["roblox_id"], data)
            if not uid:
                uid, _ = find_user_by_roblox_name(info["roblox_name"], data)

        if not uid:
            flash(
                "This Roblox account is not linked in Aqua Casino. "
                "Verify in Discord first, or provide your Discord user ID.",
                "error",
            )
            return redirect(url_for("deposit_page"))

        user = ensure_user(uid, data)
        if not user.get("roblox"):
            user["roblox"] = info["roblox_name"]
            user["roblox_id"] = info["roblox_id"]

        code = _gen_code("DEP")
        entry = {
            "type": "deposit",
            "user_id": str(uid),
            "roblox_id": info["roblox_id"],
            "roblox_username": info["roblox_name"],
            "amount": amount,
            "status": "waiting",
            "created_at": _now(),
        }
        data.setdefault("website_codes", {})[code] = entry
        data.setdefault("pending_deposits", {})[code] = entry
        save_data(data)

        return render_template(
            "deposit_created.html",
            code=code,
            amount=format_amount(amount),
            raw_amount=amount,
            roblox_name=info["roblox_name"],
            bot_username=BOT_ROBLOX_USERNAME,
            public_diamonds=info.get("public_diamonds"),
        )

    return render_template(
        "deposit.html",
        bot_username=BOT_ROBLOX_USERNAME,
        min_amount=format_amount(MIN_AMOUNT),
    )


@app.route("/withdraw", methods=["GET", "POST"])
def withdraw_page():
    if request.method == "POST":
        roblox_username = (request.form.get("roblox_username") or "").strip()
        amount_str = (request.form.get("amount") or "").strip()
        discord_id = (request.form.get("discord_id") or "").strip()

        if not roblox_username or not amount_str:
            flash("Roblox username and amount are required.", "error")
            return redirect(url_for("withdraw_page"))

        amount = parse_amount(amount_str)
        if amount is None or amount < MIN_AMOUNT:
            flash(f"Invalid amount. Minimum is {format_amount(MIN_AMOUNT)}.", "error")
            return redirect(url_for("withdraw_page"))

        info = lookup_player(roblox_username)
        if not info["ok"]:
            flash(info.get("error") or "Could not verify Roblox username.", "error")
            return redirect(url_for("withdraw_page"))

        data = get_data()
        uid = None
        if discord_id.isdigit():
            uid = discord_id
        else:
            uid, _ = find_user_by_roblox_id(info["roblox_id"], data)
            if not uid:
                uid, _ = find_user_by_roblox_name(info["roblox_name"], data)

        if not uid:
            flash("Account not linked. Verify in Discord first.", "error")
            return redirect(url_for("withdraw_page"))

        user = ensure_user(uid, data)
        if user["balance"] < amount:
            flash(
                f"Insufficient balance. You have {format_amount(user['balance'])}.",
                "error",
            )
            return redirect(url_for("withdraw_page"))

        if user.get("to_wager", 0) > 0:
            flash(
                f"You must wager {format_amount(user['to_wager'])} more before withdrawing.",
                "error",
            )
            return redirect(url_for("withdraw_page"))

        user["balance"] -= amount
        code = _gen_code("WTH")
        entry = {
            "type": "withdraw",
            "user_id": str(uid),
            "roblox_id": info["roblox_id"],
            "roblox_username": info["roblox_name"],
            "amount": amount,
            "status": "pending",
            "created_at": _now(),
            "code": code,
        }
        data.setdefault("website_codes", {})[code] = entry
        data.setdefault("pending_withdraws", {})[code] = entry
        save_data(data)

        _notify_discord(
            "💸 Withdraw Requested",
            f"**User:** <@{uid}>\n**Roblox:** `{info['roblox_name']}`\n"
            f"**Amount:** {format_amount(amount)}\n**Code:** `{code}`",
            0xFEE75C,
        )

        return render_template(
            "withdraw_created.html",
            code=code,
            amount=format_amount(amount),
            roblox_name=info["roblox_name"],
            bot_username=BOT_ROBLOX_USERNAME,
        )

    return render_template(
        "withdraw.html",
        bot_username=BOT_ROBLOX_USERNAME,
        min_amount=format_amount(MIN_AMOUNT),
    )


@app.route("/status/<code>")
def status(code: str):
    data = get_data()
    entry = data.get("website_codes", {}).get(code.upper())
    if not entry:
        flash("Code not found.", "error")
        return redirect(url_for("index"))
    return render_template(
        "status.html", code=code.upper(), entry=entry, format_amount=format_amount
    )


@app.route("/api/deposit", methods=["POST"])
def api_deposit():
    body = request.get_json(silent=True) or {}
    secret = body.get("secret") or request.headers.get("X-Tradebot-Secret", "")
    if secret != TRADEBOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    gems = int(body.get("gems") or body.get("amount") or 0)
    if gems <= 0:
        return jsonify({"ok": False, "error": "invalid gems amount"}), 400

    data = get_data()
    code = (body.get("code") or body.get("message") or "").strip().upper()
    roblox_id = body.get("roblox_id")

    if code and code in data.get("website_codes", {}):
        entry = data["website_codes"][code]
        if entry.get("type") != "deposit" or entry.get("status") != "waiting":
            return jsonify({"ok": False, "error": "code already used or invalid"}), 400

        expected = entry["amount"]
        if gems < expected * 0.95:
            return jsonify(
                {
                    "ok": False,
                    "error": f"amount too low — expected ~{expected}, got {gems}",
                }
            ), 400

        summary = _credit_deposit(entry["user_id"], gems, "Website Auto", data)
        entry["status"] = "completed"
        entry["completed_at"] = _now()
        entry["actual_gems"] = gems
        data.get("pending_deposits", {}).pop(code, None)
        save_data(data)

        _notify_discord(
            "✅ Auto Deposit Credited",
            f"**User:** <@{entry['user_id']}>\n**Roblox:** `{entry.get('roblox_username')}`\n"
            f"**Amount:** {format_amount(gems)}{summary['bonus_msg']}\n**Code:** `{code}`",
        )
        return jsonify({"ok": True, "credited": summary["credited"], "code": code})

    if roblox_id:
        uid, user = find_user_by_roblox_id(roblox_id, data)
        if not uid:
            return jsonify(
                {
                    "ok": False,
                    "error": "roblox account not linked to any Discord user",
                }
            ), 404

        summary = _credit_deposit(uid, gems, "Tradebot Auto", data)
        save_data(data)
        _notify_discord(
            "✅ Auto Deposit Credited",
            f"**User:** <@{uid}>\n**Roblox ID:** `{roblox_id}`\n"
            f"**Amount:** {format_amount(gems)}{summary['bonus_msg']}",
        )
        return jsonify({"ok": True, "credited": summary["credited"], "user_id": uid})

    return jsonify({"ok": False, "error": "provide code or roblox_id"}), 400


@app.route("/api/pending_withdraws", methods=["GET"])
def api_pending_withdraws():
    secret = request.args.get("secret") or request.headers.get("X-Tradebot-Secret", "")
    if secret != TRADEBOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = get_data()
    pending = []
    for code, entry in list(data.get("pending_withdraws", {}).items()):
        if entry.get("status") == "pending":
            pending.append(
                {
                    "code": code,
                    "roblox_id": entry["roblox_id"],
                    "roblox_username": entry["roblox_username"],
                    "amount": entry["amount"],
                    "user_id": entry["user_id"],
                }
            )
    return jsonify({"ok": True, "withdraws": pending})


@app.route("/api/withdraw_complete", methods=["POST"])
def api_withdraw_complete():
    body = request.get_json(silent=True) or {}
    secret = body.get("secret") or request.headers.get("X-Tradebot-Secret", "")
    if secret != TRADEBOT_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    code = (body.get("code") or "").strip().upper()
    success = body.get("success", True)

    data = get_data()
    entry = data.get("website_codes", {}).get(code)
    if not entry or entry.get("type") != "withdraw":
        return jsonify({"ok": False, "error": "unknown code"}), 404

    if success:
        entry["status"] = "paid"
        entry["completed_at"] = _now()
        user = ensure_user(entry["user_id"], data)
        user["withdrawn"] = user.get("withdrawn", 0) + entry["amount"]
        data["global_stats"]["total_withdraws"] = (
            data["global_stats"].get("total_withdraws", 0) + entry["amount"]
        )
        add_history(entry["user_id"], "Withdraw (Auto)", entry["amount"], "Paid", data)
        data.get("pending_withdraws", {}).pop(code, None)
        save_data(data)
        _notify_discord(
            "✅ Withdraw Paid",
            f"**User:** <@{entry['user_id']}>\n**Roblox:** `{entry['roblox_username']}`\n"
            f"**Amount:** {format_amount(entry['amount'])}\n**Code:** `{code}`",
        )
        return jsonify({"ok": True})

    entry["status"] = "failed"
    user = ensure_user(entry["user_id"], data)
    user["balance"] += entry["amount"]
    data.get("pending_withdraws", {}).pop(code, None)
    save_data(data)
    return jsonify({"ok": True, "refunded": True})


@app.route("/api/simulate_deposit", methods=["POST"])
def api_simulate_deposit():
    key = request.headers.get("X-Admin-Key") or (
        request.get_json(silent=True) or {}
    ).get("admin_key")
    if key != ADMIN_API_KEY:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    data = get_data()

    code = (body.get("code") or "").strip().upper()
    if code and code in data.get("website_codes", {}):
        entry = data["website_codes"][code]
        if entry.get("status") != "waiting":
            return jsonify({"ok": False, "error": "code not waiting"}), 400
        gems = int(body.get("gems") or entry["amount"])
        summary = _credit_deposit(entry["user_id"], gems, "Simulated", data)
        entry["status"] = "completed"
        entry["completed_at"] = _now()
        entry["actual_gems"] = gems
        data.get("pending_deposits", {}).pop(code, None)
        save_data(data)
        return jsonify(
            {
                "ok": True,
                "credited": summary["credited"],
                "balance": summary["new_balance"],
            }
        )

    username = (body.get("roblox_username") or "").strip()
    gems = int(body.get("gems") or 0)
    if not username or gems <= 0:
        return jsonify({"ok": False, "error": "need code or roblox_username+gems"}), 400

    info = lookup_player(username)
    if not info["ok"]:
        return jsonify({"ok": False, "error": info.get("error")}), 400

    uid, _ = find_user_by_roblox_id(info["roblox_id"], data)
    if not uid:
        uid, _ = find_user_by_roblox_name(info["roblox_name"], data)
    if not uid:
        return jsonify({"ok": False, "error": "user not linked in casino"}), 404

    summary = _credit_deposit(uid, gems, "Simulated", data)
    save_data(data)
    return jsonify({"ok": True, "credited": summary["credited"], "user_id": uid})


@app.route("/api/health")
def health():
    data = get_data()
    return jsonify(
        {
            "ok": True,
            "users": len(data.get("users", {})),
            "pending_deposits": len(data.get("pending_deposits", {})),
            "pending_withdraws": len(data.get("pending_withdraws", {})),
            "big_games_api": "https://ps99.biggamesapi.io",
            "website_offline": bool(
                data.get("settings", {}).get("website_offline", False)
            ),
        }
    )


if __name__ == "__main__":
    print("=" * 60)
    print("🌊 Aqua Gems Casino — Deposit / Withdraw Website")
    print(f"   Data file : {DATA_FILE}")
    print(f"   Bot user  : {BOT_ROBLOX_USERNAME}")
    print(f"   Listening : http://{HOST}:{PORT}")
    print("=" * 60)
    app.run(host=HOST, port=PORT, debug=False)