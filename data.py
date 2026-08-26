"""Aqua Gems Casino — persistent data, user helpers, amount parsing."""
import json
import os
import random
import re
import time

from config import DATA_FILE

DEFAULT_DATA = {
    "users": {},
    "verification": {},
    "tickets": {},
    "affiliates": {},
    "global_stats": {
        "total_deposits": 0,
        "total_withdraws": 0,
        "bot_game_profit": 0,
        "manual_total_net_profit": None,
        "profit_tracker_message_id": None,
        "profit_tracker_message_ids": {}
    },
    "settings": {
        "paused": False,
        "active_deposit_bonus": None
    }
}

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            DATA = json.load(f)
    except Exception:
        DATA = DEFAULT_DATA.copy()
else:
    DATA = DEFAULT_DATA.copy()

if not isinstance(DATA, dict):
    DATA = {}

if not isinstance(DATA.get("users"), dict):
    DATA["users"] = {}

if not isinstance(DATA.get("verification"), dict):
    DATA["verification"] = {}

if not isinstance(DATA.get("tickets"), dict):
    DATA["tickets"] = {}

if not isinstance(DATA.get("affiliates"), dict):
    DATA["affiliates"] = {}

if not isinstance(DATA.get("global_stats"), dict):
    DATA["global_stats"] = {
        "total_deposits": 0,
        "total_withdraws": 0,
        "bot_game_profit": 0,
        "profit_tracker_message_id": None
    }

DATA["global_stats"].setdefault("total_deposits", 0)
DATA["global_stats"].setdefault("total_withdraws", 0)
DATA["global_stats"].setdefault("bot_game_profit", 0)
DATA["global_stats"].setdefault("manual_total_net_profit", None)
DATA["global_stats"].setdefault("profit_tracker_message_id", None)
DATA["global_stats"].setdefault("profit_tracker_message_ids", {})
if not isinstance(DATA["global_stats"]["profit_tracker_message_ids"], dict):
    DATA["global_stats"]["profit_tracker_message_ids"] = {}

if not isinstance(DATA.get("settings"), dict):
    DATA["settings"] = {}

DATA["settings"].setdefault("paused", False)
DATA["settings"].setdefault("active_deposit_bonus", None)

# ============================================================
# ONE-TIME ECONOMY RESET
# ============================================================
ECONOMY_RESET_VERSION = "2026-08-22-zero-start"

if DATA["settings"].get("economy_reset_version") != ECONOMY_RESET_VERSION:
    for uid, user in DATA["users"].items():
        user["balance"] = 0
        user["wagered"] = 0
        user["deposited"] = 0
        user["withdrawn"] = 0
        user["to_wager"] = 0
        user["history"] = []
        user["last_rakeback"] = 0

    DATA["global_stats"]["total_deposits"] = 0
    DATA["global_stats"]["total_withdraws"] = 0
    DATA["global_stats"]["bot_game_profit"] = 0
    DATA["global_stats"]["profit_tracker_message_id"] = None
    DATA["global_stats"]["profit_tracker_message_ids"] = {}
    DATA["settings"]["active_deposit_bonus"] = None
    DATA["settings"]["economy_reset_version"] = ECONOMY_RESET_VERSION


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DATA, f, indent=4)


def ensure_user(user_id):
    uid = str(user_id)

    if uid not in DATA["users"]:
        DATA["users"][uid] = {
            "balance": 0,
            "wagered": 0,
            "deposited": 0,
            "withdrawn": 0,
            "to_wager": 0,
            "history": [],
            "roblox": None,
            "roblox_id": None,
            "last_rakeback": 0,
            "affiliate_code": f"REF-{random.randint(1000, 9999)}",
            "referred_by": None,
            "referred_users": []
        }

    DATA["users"][uid].setdefault("deposited", 0)
    DATA["users"][uid].setdefault("withdrawn", 0)
    DATA["users"][uid].setdefault("to_wager", 0)
    DATA["users"][uid].setdefault("referred_users", [])

    return DATA["users"][uid]


def add_history(user_id, game, amount, result):
    user = ensure_user(user_id)

    user["history"].append({
        "game": game,
        "amount": amount,
        "result": result,
        "time": int(time.time())
    })

    user["history"] = user["history"][-100:]


def parse_amount(amount_str: str):
    if not isinstance(amount_str, str):
        return None
    amount_str = amount_str.lower().strip().replace(",", "").replace(" ", "")
    match = re.match(r"^(\d+(?:\.\d+)?)([kmbt])?$", amount_str)
    if not match:
        return None
    val, mult = match.groups()
    val = float(val)
    if mult == "k":
        val *= 1_000
    elif mult == "m":
        val *= 1_000_000
    elif mult == "b":
        val *= 1_000_000_000
    elif mult == "t":
        val *= 1_000_000_000_000
    return int(val)


def parse_signed_amount(amount_str: str):
    """Same as parse_amount but also accepts a leading + or - sign."""
    if not isinstance(amount_str, str):
        return None
    s = amount_str.strip()
    negative = False
    if s.startswith("-"):
        negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    parsed = parse_amount(s)
    if parsed is None:
        return None
    return -parsed if negative else parsed


def format_amount(amount: int) -> str:
    amount = int(amount)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)

    if amount >= 1_000_000_000_000:
        val = amount / 1_000_000_000_000
        formatted = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{sign}{formatted}T"
    elif amount >= 1_000_000_000:
        val = amount / 1_000_000_000
        formatted = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{sign}{formatted}B"
    elif amount >= 1_000_000:
        val = amount / 1_000_000
        formatted = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{sign}{formatted}M"
    elif amount >= 1_000:
        val = amount / 1_000
        formatted = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{sign}{formatted}K"
    return f"{sign}{amount}"
