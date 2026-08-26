"""Official Big Games PS99 API + Roblox username lookup."""
from __future__ import annotations

import os
import requests

BIG_GAMES_BASE = os.environ.get(
    "BIG_GAMES_BASE",
    "https://ps99.biggamesapi.io",
)
ROBLOX_USERS_URL = "https://users.roblox.com/v1/usernames/users"


def roblox_username_to_id(username: str) -> dict:
    try:
        r = requests.post(
            ROBLOX_USERS_URL,
            json={"usernames": [username], "excludeBannedUsers": True},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data") or []
        if not data:
            return {"ok": False, "error": f"Roblox user '{username}' not found"}
        u = data[0]
        return {
            "ok": True,
            "roblox_id": str(u["id"]),
            "roblox_name": u.get("name") or username,
            "display_name": u.get("displayName") or u.get("name") or username,
        }
    except Exception as e:
        return {"ok": False, "error": f"Roblox API error: {e}"}


def lookup_player(username: str) -> dict:
    base = roblox_username_to_id(username)
    if not base["ok"]:
        return base

    public_diamonds = None
    try:
        slug = base["roblox_name"].lower()
        r = requests.get(f"{BIG_GAMES_BASE}/v1/players/{slug}", timeout=10)
        if r.status_code == 200:
            payload = r.json()
            data = payload.get("data") or payload
            if isinstance(data, dict):
                public_diamonds = (
                    data.get("diamonds")
                    or data.get("Diamonds")
                    or data.get("currency")
                    or data.get("value")
                )
                if isinstance(public_diamonds, dict):
                    public_diamonds = public_diamonds.get("diamonds") or public_diamonds.get("value")
    except Exception:
        pass

    return {
        "ok": True,
        "roblox_id": base["roblox_id"],
        "roblox_name": base["roblox_name"],
        "display_name": base["display_name"],
        "public_diamonds": public_diamonds,
    }