"""
Aqua Gems Casino — main entry point.

This file only wires everything together. Game logic lives in:
  mines.py, towers.py, colordice.py, blackjack.py, coinflip.py,
  slots.py, deposit.py, verification.py, economy.py, tip.py,
  affiliates.py, admin.py, invite_event.py, plus shared
  config/data/utils/bot_instance.
"""
import asyncio
import random
import string

import discord
from discord import app_commands
from discord.ext import tasks

from bot_instance import bot, tree
from config import TOKEN, config
from data import DATA, save_data, ensure_user
from utils import normal_embed, get_live_profit_embed

# Register all slash commands by importing feature modules
import admin          # noqa: F401
import verification   # noqa: F401
import tip            # noqa: F401
import economy        # noqa: F401
import mines          # noqa: F401
import towers         # noqa: F401
import colordice      # noqa: F401
import affiliates     # noqa: F401
import slots          # noqa: F401
import deposit        # noqa: F401
import blackjack      # noqa: F401
import coinflip       # noqa: F401
import invite_event   # noqa: F401
import website_admin  # noqa: F401

from verification import VerificationPanelView
from deposit import DepositTicketView, WithdrawTicketView


# ============================================================
# LIVE PROFIT TRACKER
# ============================================================

@tasks.loop(seconds=5)
async def update_profit_trackers():
    """Edits the live profit tracker message in every guild every 5 seconds."""
    profit_embed = get_live_profit_embed()
    ids_map = DATA["global_stats"].setdefault("profit_tracker_message_ids", {})
    changed = False

    for guild in bot.guilds:
        stats_channel = guild.get_channel(
            __import__("config", fromlist=["PROFIT_TRACKER_CHANNEL_ID"]).PROFIT_TRACKER_CHANNEL_ID
        )
        if not stats_channel:
            continue

        guild_key = str(guild.id)
        msg_id = ids_map.get(guild_key)

        try:
            if msg_id:
                try:
                    msg = await stats_channel.fetch_message(msg_id)
                    await msg.edit(embed=profit_embed)
                    continue
                except discord.NotFound:
                    pass

            new_msg = await stats_channel.send(embed=profit_embed)
            ids_map[guild_key] = new_msg.id
            changed = True
        except Exception as e:
            print(f"Profit tracker update error in guild {guild.id}: {e}")

    if changed:
        save_data()


# Make update_profit_trackers available to economy.editprofit
import economy as _economy
_economy.update_profit_trackers = update_profit_trackers


# ============================================================
# TRIVIA / CHALLENGES
# ============================================================

OWNER_ID = 1500198665933820004

TRIVIA_REWARD_NORMAL = 15_000_000
TRIVIA_REWARD_BOOSTED = 5_000_000
TRIVIA_ROLE_PING = "<@&1541412570043519076>"
TRIVIA_TIMEOUT = 60.0

# Boost state
trivia_boosted = False
trivia_boosted_by = None  # mention string


def _current_reward() -> int:
    return TRIVIA_REWARD_BOOSTED if trivia_boosted else TRIVIA_REWARD_NORMAL


def _format_reward(amount: int) -> str:
    if amount >= 1_000_000:
        return f"{amount // 1_000_000}m"
    return str(amount)


def _reward_text() -> str:
    return f"**{_format_reward(_current_reward())} gems**"


def _boost_footer():
    if trivia_boosted and trivia_boosted_by:
        return (
            f"⚡ Trivia boosted by {trivia_boosted_by} — "
            f"rounds every 1 min • prize {_format_reward(TRIVIA_REWARD_BOOSTED)} gems"
        )
    return None


# --- Challenge banks ---

TRIVIA_QUESTIONS = [
    ("What is the capital of France?", "paris"),
    ("What is the capital of Japan?", "tokyo"),
    ("What is the capital of Italy?", "rome"),
    ("What is the capital of Spain?", "madrid"),
    ("What is the capital of Germany?", "berlin"),
    ("What is the capital of Canada?", "ottawa"),
    ("What is the capital of Australia?", "canberra"),
    ("How many continents are there?", "7"),
    ("How many planets are in our solar system?", "8"),
    ("What is H2O commonly known as?", "water"),
    ("What gas do plants absorb from the air?", "carbon dioxide"),
    ("What is the largest ocean on Earth?", "pacific"),
    ("What is the tallest mountain in the world?", "everest"),
    ("How many sides does a hexagon have?", "6"),
    ("How many sides does an octagon have?", "8"),
    ("What is 12 × 12?", "144"),
    ("What colour do you get mixing red and blue?", "purple"),
    ("What is the freezing point of water in Celsius?", "0"),
    ("What is the boiling point of water in Celsius?", "100"),
    ("Who painted the Mona Lisa?", "leonardo da vinci"),
    ("What year did World War 2 end?", "1945"),
    ("What is the chemical symbol for gold?", "au"),
    ("What is the chemical symbol for silver?", "ag"),
    ("How many hours are in a day?", "24"),
    ("How many minutes are in an hour?", "60"),
    ("What is the square root of 81?", "9"),
    ("What is the square root of 144?", "12"),
    ("Which planet is known as the Red Planet?", "mars"),
    ("Which planet is closest to the Sun?", "mercury"),
    ("What is the largest mammal?", "blue whale"),
    ("How many legs does a spider have?", "8"),
    ("How many legs does an insect have?", "6"),
    ("What do bees make?", "honey"),
    ("What is the main language spoken in Brazil?", "portuguese"),
    ("What currency is used in Japan?", "yen"),
    ("What currency is used in the UK?", "pound"),
    ("What is the opposite of hot?", "cold"),
    ("What is the opposite of up?", "down"),
    ("How many days are in a leap year?", "366"),
    ("How many days are in a normal year?", "365"),
    ("What casino game uses a round wheel and a ball?", "roulette"),
    ("In blackjack, what is the best possible hand?", "21"),
    ("What do you call two identical cards in poker?", "pair"),
    ("What colour is the highest value chip often associated with?", "black"),
    ("What is 2 to the power of 10?", "1024"),
]

TYPING_PHRASES = [
    "aqua gems casino",
    "stack those gems",
    "jackpot winner",
    "lucky streak",
    "high roller",
    "all in",
    "double or nothing",
    "spin to win",
    "diamond hands",
    "big win energy",
    "casino royal",
    "fortune favors the bold",
    "type this fast",
    "quick fingers win",
    "gems on gems",
    "aqua is life",
    "never fold early",
    "hit or stand",
    "roll the dice",
    "flip the coin",
]

UNSCRAMBLE_WORDS = [
    "casino", "jackpot", "diamond", "fortune", "winner", "streak",
    "roulette", "blackjack", "slots", "poker", "gems", "aqua",
    "lucky", "riches", "bonus", "payout", "dealer", "chip",
    "spin", "bet", "vault", "treasure", "reward", "prize",
]

REVERSE_WORDS = [
    "aqua", "gems", "casino", "lucky", "winner", "jackpot",
    "diamond", "fortune", "bonus", "streak", "chips", "spin",
]

EMOJI_SEQUENCES = [
    ("💎🔥💎", "💎🔥💎"),
    ("🌊💎🌊", "🌊💎🌊"),
    ("🎰7️⃣🎰", "🎰7️⃣🎰"),
    ("🍀💰🍀", "🍀💰🍀"),
    ("🎲🎲🎲", "🎲🎲🎲"),
    ("👑💎👑", "👑💎👑"),
    ("⚡💎⚡", "⚡💎⚡"),
]


def _math_challenge():
    op = random.choice(["+", "-", "*", "add", "sub", "mul"])
    if op in ("+", "add"):
        a, b = random.randint(10, 300), random.randint(10, 300)
        ans = str(a + b)
        prompt = f"**{a} + {b}**"
    elif op in ("-", "sub"):
        a, b = random.randint(50, 400), random.randint(10, 200)
        if b > a:
            a, b = b, a
        ans = str(a - b)
        prompt = f"**{a} − {b}**"
    else:
        a, b = random.randint(4, 25), random.randint(3, 16)
        ans = str(a * b)
        prompt = f"**{a} × {b}**"
    return (
        "🧮 Math Challenge!",
        f"First to type the correct answer to {prompt} wins {_reward_text()}!",
        ans,
        False,
        discord.Colour.blue(),
    )


def _typing_challenge():
    phrase = random.choice(TYPING_PHRASES)
    return (
        "⌨️ Typing Race!",
        f"First person to type this **exactly** wins {_reward_text()}:\n\n`{phrase}`",
        phrase,
        True,
        discord.Colour.orange(),
    )


def _trivia_challenge():
    q, a = random.choice(TRIVIA_QUESTIONS)
    return (
        "🧠 Trivia Time!",
        f"**{q}**\n\nFirst correct answer wins {_reward_text()}!",
        a,
        False,
        discord.Colour.purple(),
    )


def _unscramble_challenge():
    word = random.choice(UNSCRAMBLE_WORDS)
    letters = list(word)
    random.shuffle(letters)
    scrambled = "".join(letters)
    if scrambled == word:
        letters = list(word)
        random.shuffle(letters)
        scrambled = "".join(letters)
    return (
        "🔀 Unscramble!",
        f"Unscramble this word: **`{scrambled}`**\n\nFirst correct answer wins {_reward_text()}!",
        word,
        False,
        discord.Colour.green(),
    )


def _reverse_challenge():
    word = random.choice(REVERSE_WORDS)
    return (
        "🔄 Reverse It!",
        f"Type this word **backwards**: **`{word}`**\n\nFirst correct answer wins {_reward_text()}!",
        word[::-1],
        False,
        discord.Colour.teal(),
    )


def _emoji_challenge():
    shown, ans = random.choice(EMOJI_SEQUENCES)
    return (
        "😎 Emoji Race!",
        f"First to type this exact emoji sequence wins {_reward_text()}:\n\n{shown}",
        ans,
        True,
        discord.Colour.gold(),
    )


def _count_letters_challenge():
    word = random.choice(UNSCRAMBLE_WORDS + TYPING_PHRASES)
    letter = random.choice(list(set(word.replace(" ", ""))))
    count = word.count(letter)
    return (
        "🔢 Count Them!",
        f"How many times does the letter **`{letter}`** appear in:\n**`{word}`**?\n\nFirst correct number wins {_reward_text()}!",
        str(count),
        False,
        discord.Colour.dark_blue(),
    )


def _sequence_challenge():
    start = random.randint(2, 12)
    step = random.randint(2, 7)
    seq = [start + i * step for i in range(4)]
    ans = str(seq[-1] + step)
    shown = ", ".join(str(x) for x in seq) + ", ?"
    return (
        "🔢 Next Number!",
        f"What comes next in the sequence?\n**{shown}**\n\nFirst correct answer wins {_reward_text()}!",
        ans,
        False,
        discord.Colour.dark_purple(),
    )


def _random_string_challenge():
    length = random.randint(5, 8)
    chars = string.ascii_lowercase + string.digits
    code = "".join(random.choice(chars) for _ in range(length))
    return (
        "⚡ Code Race!",
        f"First to type this code **exactly** wins {_reward_text()}:\n\n`{code}`",
        code,
        True,
        discord.Colour.red(),
    )


def _first_to_type_challenge():
    targets = [
        ("AQUA", "AQUA"),
        ("GEMS", "GEMS"),
        ("WIN", "WIN"),
        ("GG", "GG"),
        ("EZ", "EZ"),
        ("LFG", "LFG"),
        ("100", "100"),
        ("777", "777"),
    ]
    shown, ans = random.choice(targets)
    return (
        "🏁 First to Type!",
        f"First person to type **`{shown}`** wins {_reward_text()}!",
        ans,
        True,
        discord.Colour.magenta(),
    )


CHALLENGE_MAKERS = [
    _math_challenge,
    _math_challenge,
    _typing_challenge,
    _typing_challenge,
    _trivia_challenge,
    _trivia_challenge,
    _trivia_challenge,
    _unscramble_challenge,
    _reverse_challenge,
    _emoji_challenge,
    _count_letters_challenge,
    _sequence_challenge,
    _random_string_challenge,
    _first_to_type_challenge,
]


@tasks.loop(minutes=15)
async def trivia_loop():
    channel_id = config.get("channels", {}).get("general")
    if not channel_id:
        return

    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

    maker = random.choice(CHALLENGE_MAKERS)
    title, description, answer, case_sensitive, colour = maker()

    if trivia_boosted and trivia_boosted_by:
        description = (
            f"⚡ **Trivia boosted by {trivia_boosted_by}**\n"
            f"*Faster rounds (every 1 min) • smaller prizes ({_format_reward(TRIVIA_REWARD_BOOSTED)} gems)*\n\n"
            + description
        )

    embed = normal_embed(title, description, colour)
    footer = _boost_footer()
    if footer:
        embed.set_footer(text=footer)

    await channel.send(content=TRIVIA_ROLE_PING, embed=embed)

    def check(message):
        if message.channel != channel or message.author.bot:
            return False
        content = message.content.strip()
        if case_sensitive:
            return content == answer
        return content.lower() == answer.lower()

    reward = _current_reward()
    try:
        message = await bot.wait_for("message", check=check, timeout=TRIVIA_TIMEOUT)
        winner = ensure_user(message.author.id)
        winner["balance"] += reward
        save_data()

        await channel.send(
            f"🎉 {message.author.mention} got it and won **{_format_reward(reward)} gems**!"
        )
    except asyncio.TimeoutError:
        await channel.send(
            f"⏳ Time's up! The answer was **`{answer}`**. Nobody won this round."
        )
    except Exception as e:
        print(f"Trivia loop error: {e}")


@trivia_loop.before_loop
async def before_trivia_loop():
    await bot.wait_until_ready()


def _can_boost(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    if isinstance(interaction.user, discord.Member):
        return interaction.user.guild_permissions.administrator
    return False


@tree.command(
    name="trivia_boost",
    description="Boost trivia to every 1 minute with 2m gem prizes (Admins + owner)",
)
@app_commands.describe(
    enable="Turn boost on or off (default: on)",
)
async def trivia_boost_cmd(
    interaction: discord.Interaction,
    enable: bool = True,
):
    global trivia_boosted, trivia_boosted_by

    if not _can_boost(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
        return

    if enable:
        trivia_boosted = True
        trivia_boosted_by = interaction.user.mention
        trivia_loop.change_interval(minutes=1)

        await interaction.response.send_message(
            f"⚡ **Trivia boosted by {interaction.user.mention}!**\n"
            f"Rounds now run **every 1 minute** with a **2m gem** prize.\n"
            f"Use `/trivia_boost enable:False` to turn it off.",
            ephemeral=False,
        )
    else:
        trivia_boosted = False
        trivia_boosted_by = None
        trivia_loop.change_interval(minutes=15)

        await interaction.response.send_message(
            "✅ Trivia boost disabled. Back to **every 15 minutes** with **15m gem** prizes.",
            ephemeral=False,
        )


# ============================================================
# STARTUP
# ============================================================

STARTUP_COMPLETE = False


@bot.event
async def on_ready():
    global STARTUP_COMPLETE

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    if STARTUP_COMPLETE:
        return

    STARTUP_COMPLETE = True

    bot.add_view(DepositTicketView())
    bot.add_view(WithdrawTicketView())
    bot.add_view(VerificationPanelView())

    if not update_profit_trackers.is_running():
        update_profit_trackers.start()
    if not trivia_loop.is_running():
        trivia_loop.start()

    try:
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)

        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} global slash command(s).")
    except Exception as e:
        STARTUP_COMPLETE = False
        print(f"Failed to sync slash commands: {e}")


def _start_aqua_website():
    import os
    import sys
    from pathlib import Path

    try:
        root = Path(__file__).resolve().parent
        website_dir = root / "Aqua_Website"
        if not website_dir.is_dir():
            website_dir = root / "aqua_website"
        if not website_dir.is_dir():
            print("❌ Aqua_Website folder not found")
            return

        os.environ.setdefault("CASINO_DATA_FILE", str(root / "casino_data.json"))
        os.environ.setdefault("HOST", "0.0.0.0")
        os.environ.setdefault("PORT", "8080")

        sys.path.insert(0, str(website_dir))
        from main import app

        port = int(os.environ.get("PORT", "8080"))
        print(f"🌐 Aqua website starting on port {port}")
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except Exception as e:
        print(f"❌ Website error: {e}")


if __name__ == "__main__":
    if not TOKEN:
        print("❌ ERROR: DISCORD_TOKEN environment variable is missing or empty!")
    else:
        import threading
        threading.Thread(target=_start_aqua_website, daemon=True).start()
        print("🚀 Starting Aqua Gems Casino (modular)...")
        bot.run(TOKEN)