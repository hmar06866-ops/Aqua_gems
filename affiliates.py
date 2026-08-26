"""Aqua Gems Casino — affiliates & rain."""
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

@tree.command(name="create-affiliate", description="Create a custom affiliate code.")
@app_commands.describe(code="Your desired affiliate code (alphanumeric, max 16 chars)")
async def create_affiliate(interaction: discord.Interaction, code: str):
    if not await verification_check(interaction):
        return

    code = code.upper().strip()
    if not code.isalnum() or len(code) > 16:
        await interaction.response.send_message("❌ Affiliate code must be alphanumeric and up to 16 characters long.", ephemeral=True)
        return

    for owner_id, udata in DATA["users"].items():
        if udata.get("affiliate_code") == code:
            await interaction.response.send_message("❌ This affiliate code is already taken.", ephemeral=True)
            return

    user = ensure_user(interaction.user.id)
    user["affiliate_code"] = code
    save_data()

    await interaction.response.send_message(f"✅ Your custom affiliate code has been set to **`{code}`**!", ephemeral=True)


@tree.command(name="affiliates", description="View or claim affiliate referrals.")
@app_commands.describe(code="Affiliate Code to redeem (optional)")
async def affiliates(interaction, code: str = None):
    if not await verification_check(interaction):
        return

    user = ensure_user(interaction.user.id)

    if code:
        if user["referred_by"]:
            await interaction.response.send_message("❌ You have already redeemed an affiliate code.", ephemeral=True)
            return

        for owner_id, udata in DATA["users"].items():
            if udata.get("affiliate_code") == code.upper():
                if owner_id == str(interaction.user.id):
                    await interaction.response.send_message("❌ You cannot use your own code.", ephemeral=True)
                    return

                user["referred_by"] = code.upper()
                udata.setdefault("referred_users", [])
                if interaction.user.name not in udata["referred_users"]:
                    udata["referred_users"].append(interaction.user.name)

                save_data()
                await interaction.response.send_message(f"✅ Successfully linked to affiliate code `{code.upper()}`!", ephemeral=True)
                return

        await interaction.response.send_message("❌ Invalid affiliate code.", ephemeral=True)
        return

    embed = normal_embed(
        "🤝 Affiliate Program",
        f"Your Affiliate Code: `{user['affiliate_code']}`\n"
        f"Referred Users: `{len(user.get('referred_users', []))}`\n\n"
        f"Share your code with friends to earn bonuses on their games!"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="rain", description="Start a balance rain in the server.")
@app_commands.describe(amount="Amount to throw", duration="Duration in minutes")
async def rain(interaction, amount: str, duration: int = 5):
    if not await verification_check(interaction):
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed < 1_000_000:
        await interaction.response.send_message("❌ Minimum rain amount is 1M.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return

    user["balance"] -= parsed
    save_data()

    participants = set()

    class RainView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=duration * 60)

        @discord.ui.button(label="Join Rain 🌧️", style=discord.ButtonStyle.primary)
        async def join(self, idx, button):
            participants.add(idx.user.id)
            await idx.response.send_message("✅ You joined the rain!", ephemeral=True)

    embed = normal_embed(
        "🌧️ Rain Event Started!",
        f"{interaction.user.mention} is raining **💎 {format_amount(parsed)}**!\n"
        f"Ends in **{duration} minutes**. Click below to participate!"
    )

    msg = await interaction.channel.send(embed=embed, view=RainView())
    await interaction.response.send_message("🌧️ Rain started!", ephemeral=True)

    await asyncio.sleep(duration * 60)

    if not participants:
        user["balance"] += parsed
        save_data()
        await interaction.channel.send("🌧️ Rain ended, but no one joined! Amount refunded.")
        return

    share = parsed // len(participants)
    for p_id in participants:
        p_user = ensure_user(p_id)
        p_user["balance"] += share

    save_data()
    await interaction.channel.send(
        f"🌧️ **Rain Ended!**\n"
        f"Distributed **💎 {format_amount(parsed)}** among **{len(participants)}** players "
        f"(**💎 {format_amount(share)}** each)!"
    )

