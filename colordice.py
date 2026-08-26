"""Aqua Gems Casino — Color Dice game (6 dice)."""
import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import math
import os
import random
import re
import time
from datetime import datetime, timezone

from bot_instance import bot, tree, game_cooldown
from config import *
from data import DATA, save_data, ensure_user, add_history, parse_amount, parse_signed_amount, format_amount
from utils import (
    is_staff, is_verified, verification_check, normal_embed,
    get_live_profit_embed, send_log, update_milestone_roles,
    game_paused, get_user_rank_mention,
)


# Every Unicode square colour emoji is available as a pick.
COLOR_DICE_OPTIONS = {
    "red":    {"label": "Red",    "emoji": "🟥"},
    "orange": {"label": "Orange", "emoji": "🟧"},
    "yellow": {"label": "Yellow", "emoji": "🟨"},
    "green":  {"label": "Green",  "emoji": "🟩"},
    "blue":   {"label": "Blue",   "emoji": "🟦"},
    "purple": {"label": "Purple", "emoji": "🟪"},
    "brown":  {"label": "Brown",  "emoji": "🟫"},
    "black":  {"label": "Black",  "emoji": "⬛"},
    "white":  {"label": "White",  "emoji": "⬜"},
}

# 6 dice are rolled. Payout is based on how many land on the
# colour the player picked. Multipliers are deliberately soft
# so the house keeps a healthy edge (9 colours × 6 dice).
# Maximum Color Dice payout is capped at 3x as requested.
COLOR_DICE_MULTIPLIERS = {
    1: 0.45,
    2: 0.95,
    3: 1.85,
    4: 2.30,
    5: 3.00,
    6: 3.00,
}

COLOR_DICE_COUNT = 6


def _format_dice_row(rolls):
    """Pretty two-row display of the six colour dice."""
    if not rolls:
        return "🎲 🎲 🎲\n🎲 🎲 🎲"
    emojis = [COLOR_DICE_OPTIONS[c]["emoji"] for c in rolls]
    return f"{' '.join(emojis[:3])}\n{' '.join(emojis[3:])}"


def build_colordice_embed(
    player,
    bet,
    picked,
    rolls,
    hits,
    multiplier=None,
    winnings=0,
    shuffling=False,
    spin_frame=0,
):
    picked_data = COLOR_DICE_OPTIONS[picked]
    board = _format_dice_row(rolls)

    if shuffling:
        spin_emojis = ["🌀", "✨", "💫", "⚡", "🔮", "🌟"]
        spinner = spin_emojis[spin_frame % len(spin_emojis)]
        title = f"{spinner} Color Dice  •  ROLLING..."
        description = (
            f"{board}\n\n"
            f"🎯 **Your Pick**\n"
            f"{picked_data['emoji']} **{picked_data['label']}**\n\n"
            f"*The colours are spinning...*"
        )
        colour = discord.Colour.gold()

    elif hits == 0:
        title = "💥 Color Dice  •  BUST"
        description = (
            f"{board}\n\n"
            f"🎯 **Your Pick**\n"
            f"{picked_data['emoji']} **{picked_data['label']}**"
        )
        colour = discord.Colour.red()

    else:
        stars = "⭐" * min(hits, 6)
        title = f"🎉 Color Dice  •  WIN  {stars}"
        description = (
            f"{board}\n\n"
            f"🎯 **Your Pick**\n"
            f"{picked_data['emoji']} **{picked_data['label']}**"
        )
        colour = discord.Colour.green()

    embed = discord.Embed(title=title, description=description, colour=colour)

    if not shuffling:
        shown_mult = float(multiplier or 0.0)
        # Classic layout: keep all stats together in one Game Stats section.
        # No duplicate top stats, no "Next click", and no extra dice/house-edge panel.
        embed.add_field(
            name="Game Stats",
            value=(
                f"💎 **Bet:** {format_amount(bet)}\n"
                f"✨ **Multiplier:** {shown_mult:.2f}x\n"
                f"💎 **Winnings:** {format_amount(winnings)}\n"
                f"✨ **Matches:** {hits} / {COLOR_DICE_COUNT}"
            ),
            inline=False,
        )

    embed.set_author(name="Aqua Gems Casino  •  Color Dice")
    embed.set_footer(text="Aqua Gems Casino  •  6 Dice")
    return embed


@tree.command(name="colordice", description="Play Color Dice — pick a colour and roll 6 dice!")
@game_cooldown()
@app_commands.describe(
    bet="Bet amount (e.g., 10m, 500m, 1b)",
    color="Choose your colour"
)
@app_commands.choices(color=[
    app_commands.Choice(name="🟥 Red", value="red"),
    app_commands.Choice(name="🟧 Orange", value="orange"),
    app_commands.Choice(name="🟨 Yellow", value="yellow"),
    app_commands.Choice(name="🟩 Green", value="green"),
    app_commands.Choice(name="🟦 Blue", value="blue"),
    app_commands.Choice(name="🟪 Purple", value="purple"),
    app_commands.Choice(name="🟫 Brown", value="brown"),
    app_commands.Choice(name="⬛ Black", value="black"),
    app_commands.Choice(name="⬜ White", value="white"),
])
async def colordice(interaction: discord.Interaction, bet: str, color: app_commands.Choice[str]):
    if not await verification_check(interaction) or await game_paused(interaction):
        return

    parsed = parse_amount(bet)
    if parsed is None or parsed < MIN_GAME_AMOUNT:
        await interaction.response.send_message("❌ Minimum bet amount is **10M**.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return

    user["balance"] -= parsed
    save_data()

    picked = color.value
    colour_keys = list(COLOR_DICE_OPTIONS.keys())

    start_embed = build_colordice_embed(
        interaction.user, parsed, picked, [], 0, shuffling=True, spin_frame=0
    )
    await interaction.response.send_message(embed=start_embed)

    # Multi-frame roll animation
    for frame in range(1, 7):
        temp_rolls = [random.choice(colour_keys) for _ in range(COLOR_DICE_COUNT)]
        frame_embed = build_colordice_embed(
            interaction.user,
            parsed,
            picked,
            temp_rolls,
            0,
            shuffling=True,
            spin_frame=frame,
        )
        try:
            await interaction.edit_original_response(embed=frame_embed)
        except discord.HTTPException:
            pass
        await asyncio.sleep(0.40)

    rolls = [random.choice(colour_keys) for _ in range(COLOR_DICE_COUNT)]
    hits = rolls.count(picked)
    multiplier = COLOR_DICE_MULTIPLIERS.get(hits, 0.0)
    winnings = int(parsed * multiplier) if hits else 0

    if winnings > 0:
        user["balance"] += winnings
        user["wagered"] += parsed
        user["to_wager"] = max(0, user["to_wager"] - parsed)
        add_history(interaction.user.id, "Color Dice", parsed, "Win")
        DATA["global_stats"]["bot_game_profit"] -= (winnings - parsed)
        status_colour = discord.Colour.green()
    else:
        user["wagered"] += parsed
        user["to_wager"] = max(0, user["to_wager"] - parsed)
        add_history(interaction.user.id, "Color Dice", parsed, "Loss")
        DATA["global_stats"]["bot_game_profit"] += parsed
        status_colour = discord.Colour.red()

    save_data()
    await update_milestone_roles(interaction.user)

    result_embed = build_colordice_embed(
        interaction.user, parsed, picked, rolls, hits, multiplier, winnings
    )
    await interaction.edit_original_response(embed=result_embed)

    if hits == 0:
        log_title = "🎲 Color Dice Lost"
    else:
        log_title = "🎲 Color Dice Won"

    result_emojis = " ".join(COLOR_DICE_OPTIONS[c]["emoji"] for c in rolls)
    await send_log(
        interaction.guild,
        log_title,
        f"Player: {interaction.user.mention}\n"
        f"Amount: **{format_amount(parsed)}**\n"
        f"Pick: **{COLOR_DICE_OPTIONS[picked]['emoji']} {COLOR_DICE_OPTIONS[picked]['label']}**\n"
        f"Result: **{result_emojis}**\n"
        f"Matches: **{hits}/{COLOR_DICE_COUNT}**\n"
        f"Multiplier: **{multiplier:.2f}x**\n"
        f"Payout: **{format_amount(winnings)}**",
        status_colour
    )

