"""Aqua Gems Casino — tip command."""
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

@tree.command(name="tip", description="Tip gems to another member.")
@app_commands.describe(user="Member to tip", amount="Amount to tip (e.g., 10m, 1b)")
async def tip(interaction: discord.Interaction, user: discord.Member, amount: str):
    if interaction.channel_id not in TIP_ALLOWED_CHANNEL_IDS:
        allowed_mentions = ", ".join([f"<#{cid}>" for cid in TIP_ALLOWED_CHANNEL_IDS])
        await interaction.response.send_message(f"❌ You can only use `/tip` in one of these channels: {allowed_mentions}.", ephemeral=True)
        return

    if not await verification_check(interaction):
        return

    if user.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't tip yourself.", ephemeral=True)
        return
    if user.bot:
        await interaction.response.send_message("❌ You can't tip a bot.", ephemeral=True)
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed <= 0:
        await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        return

    sender = ensure_user(interaction.user.id)
    if sender["balance"] < parsed:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return

    sender["balance"] -= parsed
    receiver = ensure_user(user.id)
    receiver["balance"] += parsed
    save_data()

    embed = normal_embed(
        "💸 Gem Tip Sent",
        f"{interaction.user.mention} successfully tipped **{format_amount(parsed)} gems** to {user.mention}!",
        discord.Colour.green()
    )
    embed.set_author(name="Aqua Gems Casino")
    await interaction.response.send_message(embed=embed)

    if interaction.guild:
        log_channel = interaction.guild.get_channel(TIP_LOG_CHANNEL_ID)
        if log_channel:
            try:
                log_embed = normal_embed(
                    "💸 Gem Tip Log",
                    f"**Sender:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                    f"**Receiver:** {user.mention} (`{user.id}`)\n"
                    f"**Amount:** **{format_amount(parsed)}**\n"
                    f"**Channel:** <#{interaction.channel_id}>",
                    discord.Colour.green()
                )
                await log_channel.send(embed=log_embed)
            except Exception:
                pass

