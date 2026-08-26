"""Aqua Gems Casino — balance, admin economy, leaderboard."""
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
from verification import get_roblox_avatar, get_roblox_user
from utils import (
    is_staff, is_verified, verification_check, normal_embed,
    get_live_profit_embed, send_log, update_milestone_roles,
    game_paused, get_user_rank_mention,
)

@tree.command(name="balance", description="Check your profile and balance.")
async def balance(interaction):
    if not await verification_check(interaction):
        return

    user = ensure_user(interaction.user.id)
    roblox_name = user.get("roblox") or "Not linked"
    roblox_id = user.get("roblox_id")

    embed = discord.Embed(
        title=f"💳 {interaction.user.display_name}'s Profile",
        colour=discord.Colour.from_rgb(43, 34, 85)
    )

    embed.add_field(name="💎 Balance", value=f"**{format_amount(user['balance'])}**", inline=True)
    embed.add_field(name="🎲 Wagered", value=f"**{format_amount(user['wagered'])}**", inline=True)
    embed.add_field(name="📥 Deposited", value=f"**{format_amount(user.get('deposited', 0))}**", inline=True)

    embed.add_field(name="📤 Withdrawn", value=f"**{format_amount(user.get('withdrawn', 0))}**", inline=True)
    embed.add_field(name="🔒 To Wager", value=f"**{format_amount(user.get('to_wager', 0))}**", inline=True)
    
    user_rank = get_user_rank_mention(interaction.guild, user['wagered'])
    embed.add_field(name="🏆 Rank", value=user_rank, inline=True)

    referred_users = user.get("referred_users", [])
    referred_count = len(referred_users)
    if referred_count > 0:
        first_ref = referred_users[0]
        affiliates_value = f"**{referred_count} users (@{first_ref})**"
    else:
        affiliates_value = "**0 users**"

    embed.add_field(name="🚀 Affiliates", value=affiliates_value, inline=False)

    embed.add_field(
        name="🚀 Active Boosts",
        value="Deposit Boost: **1.00x** | Withdraw Boost: **1.00x**",
        inline=False
    )

    embed.set_footer(text=f"Roblox User: {roblox_name} | Aqua")

    if roblox_id:
        avatar_url = await get_roblox_avatar(roblox_id)
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

    await interaction.response.send_message(embed=embed, ephemeral=False)


@tree.command(name="add-gems", description="Add balance to a user.")
@app_commands.describe(user="User", amount="Example: 10m, 500m, 1b")
async def add_gems(interaction, user: discord.Member, amount: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed <= 0:
        await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        return

    target = ensure_user(user.id)
    target["balance"] += parsed
    save_data()

    await interaction.response.send_message(f"✅ Added **{format_amount(parsed)}** to {user.mention}.")


@tree.command(name="remove-gems", description="Remove balance from a user.")
@app_commands.describe(user="User", amount="Example: 10m, 500m, 1b")
async def remove_gems(interaction, user: discord.Member, amount: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed <= 0:
        await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        return

    target = ensure_user(user.id)
    target["balance"] = max(0, target["balance"] - parsed)
    save_data()

    await interaction.response.send_message(f"✅ Removed **{format_amount(parsed)}** from {user.mention}.")


@tree.command(name="editprofit", description="Manually overwrite the profit tracker stats.")
@app_commands.describe(
    total_deposits="e.g. 10m, 500m, 1b",
    total_withdraws="e.g. 10m, 500m, 1b",
    net_game_profit="e.g. 10m, -500m (can be negative)",
    total_net_bot_profit="e.g. 10m, -500m (can be negative)"
)
async def editprofit(
    interaction: discord.Interaction,
    total_deposits: str,
    total_withdraws: str,
    net_game_profit: str,
    total_net_bot_profit: str
):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    deposits = parse_signed_amount(total_deposits)
    withdraws = parse_signed_amount(total_withdraws)
    game_profit = parse_signed_amount(net_game_profit)
    net_bot_profit = parse_signed_amount(total_net_bot_profit)

    if None in (deposits, withdraws, game_profit, net_bot_profit):
        await interaction.response.send_message(
            "❌ Invalid amount(s). Use formats like `10m`, `500m`, `1.2b`, or `-250m`.",
            ephemeral=True
        )
        return

    DATA["global_stats"]["total_deposits"] = deposits
    DATA["global_stats"]["total_withdraws"] = withdraws
    DATA["global_stats"]["bot_game_profit"] = game_profit
    DATA["global_stats"]["manual_total_net_profit"] = net_bot_profit
    save_data()

    embed = normal_embed("✏️ Profit Tracker Updated", colour=discord.Colour.gold())
    embed.add_field(name="📥 Total Deposits", value=f"**💎 {format_amount(deposits)}**", inline=False)
    embed.add_field(name="📤 Total Withdraws", value=f"**💎 {format_amount(withdraws)}**", inline=False)
    embed.add_field(name="🎲 Net Game Profit", value=f"**💎 {format_amount(game_profit)}**", inline=False)
    embed.add_field(name="📈 Total Net Bot Profit", value=f"**💎 {format_amount(net_bot_profit)}**", inline=False)
    embed.set_footer(text="Aqua Gems Casino")

    await interaction.response.send_message(embed=embed)

    # Push the change to the live profit tracker message right away instead
    # of waiting for the next 5s background loop tick.
    try:
        await update_profit_trackers()
    except Exception:
        pass


# ============================================================
# NEW DEPOSIT BONUS COMMAND
# ============================================================

@tree.command(name="deposit-bonus", description="Set a temporary deposit bonus percentage and duration.")
@app_commands.describe(percentage="Bonus percentage (e.g., 15 for 15%)", duration="Duration string (e.g., 1h, 30m)")
async def deposit_bonus(interaction: discord.Interaction, percentage: int, duration: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    match = re.match(r"^(\d+)([mhd])$", duration.lower().strip())
    if not match:
        await interaction.response.send_message("❌ Invalid time format. Use something like `30m`, `1h`, or `2d`.", ephemeral=True)
        return

    val, unit = match.groups()
    val = int(val)
    multiplier = {"m": 60, "h": 3600, "d": 86400}[unit]
    duration_seconds = val * multiplier

    expires_at = int(time.time()) + duration_seconds
    DATA["settings"]["active_deposit_bonus"] = {
        "percentage": percentage,
        "expires_at": expires_at
    }
    save_data()

    embed = normal_embed(
        "🎁 Active Deposit Bonus Set!",
        f"A **{percentage}% deposit bonus** is now active for the next **{duration}**!\n"
        f"Example: If someone deposits **1B**, they will receive **{format_amount(int(1_000_000_000 * (1 + percentage / 100)))}**!",
        discord.Colour.gold()
    )
    await interaction.response.send_message(embed=embed)


# ============================================================
# OTHER MANAGEMENT COMMANDS (/viewbalance, /setwagerlock, /leaderboard, /manual verify)
# ============================================================

@tree.command(name="viewbalance", description="Check someone's balance.")
@app_commands.describe(user="The user to check balance for")
async def viewbalance(interaction: discord.Interaction, user: discord.Member):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    udata = ensure_user(user.id)
    roblox_name = udata.get("roblox") or "Not linked"
    roblox_id = udata.get("roblox_id")

    embed = discord.Embed(
        title=f"💳 {user.display_name}'s Profile (Staff View)",
        colour=discord.Colour.from_rgb(43, 34, 85)
    )

    embed.add_field(name="💎 Balance", value=f"**{format_amount(udata['balance'])}**", inline=True)
    embed.add_field(name="🎲 Wagered", value=f"**{format_amount(udata['wagered'])}**", inline=True)
    embed.add_field(name="📥 Deposited", value=f"**{format_amount(udata.get('deposited', 0))}**", inline=True)
    embed.add_field(name="📤 Withdrawn", value=f"**{format_amount(udata.get('withdrawn', 0))}**", inline=True)
    embed.add_field(name="🔒 To Wager", value=f"**{format_amount(udata.get('to_wager', 0))}**", inline=True)
    
    user_rank = get_user_rank_mention(interaction.guild, udata['wagered'])
    embed.add_field(name="🏆 Rank", value=user_rank, inline=True)

    embed.set_footer(text=f"Roblox User: {roblox_name} | Aqua")

    if roblox_id:
        avatar_url = await get_roblox_avatar(roblox_id)
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="setwagerlock", description="Set a user's required wager amount before withdrawal.")
@app_commands.describe(amount="Amount required to wager (e.g., 10m, 1b)", user="The user")
async def setwagerlock(interaction: discord.Interaction, amount: str, user: discord.Member):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed < 0:
        await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        return

    target = ensure_user(user.id)
    target["to_wager"] = parsed
    save_data()

    await interaction.response.send_message(
        f"✅ Set wager lock for {user.mention} to **{format_amount(parsed)}**.",
        ephemeral=True
    )


class LeaderboardView(discord.ui.View):
    def __init__(self, guild, sorted_users, lb_type):
        super().__init__(timeout=180)
        self.guild = guild
        self.sorted_users = sorted_users
        self.lb_type = lb_type
        self.current_page = 0
        self.items_per_page = 10
        self.max_pages = max(1, (len(sorted_users) - 1) // self.items_per_page + 1)
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.max_pages - 1

    def build_embed(self):
        embed = normal_embed(
            f"🏆 Aqua Gems Casino Leaderboard — {self.lb_type.title()}",
            colour=discord.Colour.gold()
        )
        
        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_users = self.sorted_users[start_idx:end_idx]

        desc_lines = []
        for idx, (uid, udata) in enumerate(page_users, start=start_idx + 1):
            val = udata.get(self.lb_type, 0)
            member_obj = self.guild.get_member(int(uid)) if self.guild else None
            name = member_obj.display_name if member_obj else f"User <@{uid}>"
            
            medal = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"`#{idx}`"))
            desc_lines.append(f"{medal} **{name}** — 💎 {format_amount(val)}")

        embed.description = "\n".join(desc_lines) if desc_lines else "No entries yet."
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages} | Aqua Gems Casino")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        else:
            await interaction.response.defer()


@tree.command(name="leaderboard", description="View the casino leaderboard with pages.")
@app_commands.describe(type="Leaderboard category (balance or wagered)")
@app_commands.choices(type=[
    app_commands.Choice(name="Balance", value="balance"),
    app_commands.Choice(name="Wagered", value="wagered")
])
async def leaderboard(interaction: discord.Interaction, type: app_commands.Choice[str] = None):
    lb_type = type.value if type else "balance"
    
    users_data = DATA.get("users", {})
    if not users_data:
        await interaction.response.send_message("❌ No user data found for leaderboard.", ephemeral=True)
        return

    sorted_users = sorted(
        users_data.items(),
        key=lambda item: item[1].get(lb_type, 0),
        reverse=True
    )

    view = LeaderboardView(interaction.guild, sorted_users, lb_type)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


manual_group = app_commands.Group(name="manual", description="Manual staff moderation commands")

@manual_group.command(name="verify", description="Force verify a member with a Roblox username.")
@app_commands.describe(user="The Discord member to verify", roblox_username="The Roblox username")
async def manual_verify(interaction: discord.Interaction, user: discord.Member, roblox_username: str):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    roblox = await get_roblox_user(roblox_username)
    if not roblox:
        await interaction.followup.send("❌ Roblox username not found.", ephemeral=True)
        return

    if interaction.guild:
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try:
                await user.add_roles(role)
            except discord.Forbidden:
                pass

    udata = ensure_user(user.id)
    udata["roblox"] = roblox["name"]
    udata["roblox_id"] = roblox["id"]
    
    DATA["verification"][str(user.id)] = {
        "username": roblox["name"],
        "roblox_id": roblox["id"],
        "code": "MANUAL-VERIFIED",
        "confirmed": True
    }
    save_data()

    await interaction.followup.send(
        f"✅ Successfully force verified {user.mention} as **{roblox['name']}**!",
        ephemeral=True
    )

bot.tree.add_command(manual_group)

