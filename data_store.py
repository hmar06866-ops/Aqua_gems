"""
Shared data layer — reads/writes the same casino_data.json as the Discord bot.
"""
import json
import os
import random
import re
import time
import threading
from pathlib import Path

_lock = threading.RLock()

# Path to shared JSON (parent folder = aqua_casino)
_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = Path(
    os.environ.get("CASINO_DATA_FILE", str(_ROOT / "casino_data.json"))
)

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
        "profit_tracker_message_ids": {},
    },
    "settings": {
        "paused": False,
        "active_deposit_bonus": None,
    },
    "pending_deposits": {},
    "pending_withdraws": {},
    "website_codes": {},
}


def _load():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = DEFAULT_DATA.copy()
        except Exception:
            data = DEFAULT_DATA.copy()
    else:
        data = DEFAULT_DATA.copy()
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    for k, v in DEFAULT_DATA.items():
        if k not in data:
            data[k] = v if not isinstance(v, dict) else v.copy()
    data.setdefault("pending_deposits", {})
    data.setdefault("pending_withdraws", {})
    data.setdefault("website_codes", {})
    data.setdefault("users", {})
    data.setdefault("global_stats", DEFAULT_DATA["global_stats"].copy())
    data.setdefault("settings", DEFAULT_DATA["settings"].copy())
    return data


def save_data(data):
    with _lock:
        tmp = str(DATA_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, DATA_FILE)


def get_data():
    with _lock:
        return _load()


def ensure_user(user_id, data=None):
    if data is None:
        data = get_data()
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
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
            "referred_users": [],
        }
    u = data["users"][uid]
    u.setdefault("deposited", 0)
    u.setdefault("withdrawn", 0)
    u.setdefault("to_wager", 0)
    u.setdefault("referred_users", [])
    u.setdefault("history", [])
    return u


def find_user_by_roblox_id(roblox_id, data=None):
    if data is None:
        data = get_data()
    rid = str(roblox_id)
    for uid, u in data["users"].items():
        if str(u.get("roblox_id") or "") == rid:
            return uid, u
    for uid, v in data.get("verification", {}).items():
        if str(v.get("roblox_id") or "") == rid and v.get("confirmed"):
            return uid, ensure_user(uid, data)
    return None, None


def find_user_by_roblox_name(name, data=None):
    if data is None:
        data = get_data()
    name_l = name.lower().strip()
    for uid, u in data["users"].items():
        if (u.get("roblox") or "").lower() == name_l:
            return uid, u
    for uid, v in data.get("verification", {}).items():
        if (v.get("username") or "").lower() == name_l and v.get("confirmed"):
            return uid, ensure_user(uid, data)
    return None, None


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


def add_history(user_id, game, amount, result, data=None):
    if data is None:
        data = get_data()
    user = ensure_user(user_id, data)
    user["history"].append({
        "game": game,
        "amount": amount,
        "result": result,
        "time": int(time.time()),
    })
    user["history"] = user["history"][-100:]