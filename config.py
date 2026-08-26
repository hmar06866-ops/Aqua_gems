"""
Aqua Website — configuration.
Place this folder as aqua_website/ inside your aqua_casino project.
It shares the same casino_data.json as the Discord bot.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

# When running from aqua_website/ inside aqua_casino/, the data file lives one level up.
# Override with env CASINO_DATA_FILE if needed.
DEFAULT_DATA = BASE_DIR.parent / "casino_data.json"
DATA_FILE = Path(os.environ.get("CASINO_DATA_FILE", str(DEFAULT_DATA)))

# ---------------------------------------------------------------------------
# Secrets (CHANGE THESE)
# ---------------------------------------------------------------------------
# Secret key for Flask sessions
SECRET_KEY = os.environ.get("WEBSITE_SECRET_KEY", "change-me-aqua-gems-casino-2026")

# Shared secret that the Roblox trade/mailbox Lua bot must send with every deposit POST.
# Put the same value in your Lua script.
TRADEBOT_SECRET = os.environ.get("TRADEBOT_SECRET", "aqua-tradebot-secret-change-me")

# Admin key for /api/simulate_deposit and staff actions (keep private)
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "aqua-admin-key-change-me")

# ---------------------------------------------------------------------------
# Big Games / PS99 official API
# ---------------------------------------------------------------------------
BIG_GAMES_BASE = "https://ps99.biggamesapi.io"
BIG_GAMES_V1 = f"{BIG_GAMES_BASE}/v1"

# Roblox users API (username → id)
ROBLOX_USERS_API = "https://users.roblox.com/v1/usernames/users"

# ---------------------------------------------------------------------------
# Casino / bot settings (keep in sync with Discord bot config.py)
# ---------------------------------------------------------------------------
# The Roblox username of YOUR deposit bot account (shown to players)
BOT_ROBLOX_USERNAME = os.environ.get("BOT_ROBLOX_USERNAME", "YourBotUsernameHere")

# Minimum deposit / withdraw (same scale as Discord bot — 10M gems)
MIN_AMOUNT = 10_000_000

# Host / port
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

# Optional: Discord webhook for deposit/withdraw notifications
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
