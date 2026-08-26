"""Aqua Gems Casino — pause/resume bets."""
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

async def game_paused(interaction):
    if DATA["settings"]["paused"]:
        if interaction.response.is_done():
            await interaction.followup.send(
                "⏸️ **All current games are currently paused.**\nPlease be patient!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "⏸️ **All current games are currently paused.**\n"
                "Please be patient!",
                ephemeral=True
            )
        return True
    return False


@tree.command(name="pausebets", description="Pause all active games.")
async def pausebets(interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    DATA["settings"]["paused"] = True
    save_data()

    await interaction.response.send_message("⏸️ **All games are now paused.**")


@tree.command(name="resumebets", description="Resume all games.")
async def resumebets(interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    DATA["settings"]["paused"] = False
    save_data()

    await interaction.response.send_message("▶️ **All games have been resumed!**")

