"""Aqua Gems Casino — deposit & withdraw tickets."""
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
from verification import get_roblox_user
from utils import (
    is_staff, is_verified, verification_check, normal_embed,
    get_live_profit_embed, send_log, update_milestone_roles,
    game_paused, get_user_rank_mention,
)


def sanitize_channel_name(name):
    cleaned = "".join(c for c in name.lower() if c.isalnum() or c in "-_")
    return cleaned[:80] or "user"


async def create_ticket_channel(guild, member, kind):
    category_id = DEPOSIT_CATEGORY_ID if kind == "deposit" else WITHDRAW_CATEGORY_ID
    category = guild.get_channel(category_id)
    staff_role = guild.get_role(STAFF_ROLE_ID)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    channel_name = f"{kind}-{sanitize_channel_name(member.name)}"

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        topic=f"{kind.title()} ticket for {member} ({member.id})",
        reason=f"{kind.title()} ticket opened by {member}"
    )

    return channel


async def send_ticket_log(guild, channel_id, title, ticket, staff_member, colour):
    if not guild:
        return
    channel = guild.get_channel(channel_id)
    if channel is None:
        return
    try:
        await channel.send(
            embed=normal_embed(
                title,
                f"👤 User: <@{ticket['user_id']}>\n"
                f"🎮 Roblox: **{ticket['roblox_username']}**\n"
                f"💎 Amount: **{format_amount(ticket['amount'])}**\n"
                f"🛡️ Handled by: {staff_member.mention}",
                colour
            )
        )
    except Exception:
        pass


async def close_ticket_channel(channel):
    try:
        await channel.send("🔒 **This ticket will close in 10 seconds...**")
        await asyncio.sleep(10)
        await channel.delete()
    except Exception:
        pass


class DepositTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve & Credit", emoji="✅", style=discord.ButtonStyle.success, custom_id="deposit_approve")
    async def approve(self, interaction, button):
        ticket = DATA["tickets"].get(str(interaction.channel.id))
        if not ticket or ticket.get("status") != "open":
            await interaction.response.send_message("❌ This ticket is no longer active.", ephemeral=True)
            return

        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        amount_to_credit = ticket["amount"]
        bonus_msg = ""

        active_bonus = DATA["settings"].get("active_deposit_bonus")
        if active_bonus and time.time() < active_bonus["expires_at"]:
            pct = active_bonus["percentage"]
            bonus_amount = int(amount_to_credit * (pct / 100))
            amount_to_credit += bonus_amount
            bonus_msg = f" (Includes {pct}% deposit bonus: +{format_amount(bonus_amount)})"

        user = ensure_user(ticket["user_id"])
        user["balance"] += amount_to_credit
        user["deposited"] += ticket["amount"]
        user["to_wager"] += amount_to_credit
        DATA["global_stats"]["total_deposits"] += ticket["amount"]
        ticket["status"] = "approved"
        save_data()

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        await interaction.channel.send(
            embed=normal_embed(
                "✅ Deposit Approved",
                f"{interaction.user.mention} credited **💎 {format_amount(amount_to_credit)}** to <@{ticket['user_id']}>{bonus_msg}.",
                discord.Colour.green()
            )
        )

        await send_ticket_log(interaction.guild, DEPOSIT_LOG_CHANNEL_ID, "✅ Deposit Approved", ticket, interaction.user, discord.Colour.green())
        await send_log(interaction.guild, "Deposit Approved", f"Amount: {ticket['amount']}", discord.Colour.green())
        await close_ticket_channel(interaction.channel)

    @discord.ui.button(label="Deny", emoji="❌", style=discord.ButtonStyle.danger, custom_id="deposit_deny")
    async def deny(self, interaction, button):
        ticket = DATA["tickets"].get(str(interaction.channel.id))
        if not ticket or ticket.get("status") != "open":
            await interaction.response.send_message("❌ This ticket is no longer active.", ephemeral=True)
            return

        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        ticket["status"] = "denied"
        save_data()

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        await interaction.channel.send(
            embed=normal_embed("❌ Deposit Denied", f"Denied by {interaction.user.mention}.", discord.Colour.red())
        )

        await send_ticket_log(interaction.guild, DEPOSIT_LOG_CHANNEL_ID, "❌ Deposit Denied", ticket, interaction.user, discord.Colour.red())
        await close_ticket_channel(interaction.channel)


class WithdrawTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Mark Paid", emoji="✅", style=discord.ButtonStyle.success, custom_id="withdraw_paid")
    async def mark_paid(self, interaction, button):
        ticket = DATA["tickets"].get(str(interaction.channel.id))
        if not ticket or ticket.get("status") != "open":
            await interaction.response.send_message("❌ This ticket is no longer active.", ephemeral=True)
            return

        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        user = ensure_user(ticket["user_id"])
        user["withdrawn"] += ticket["amount"]
        DATA["global_stats"]["total_withdraws"] += ticket["amount"]
        ticket["status"] = "paid"
        save_data()

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        await interaction.channel.send(
            embed=normal_embed(
                "✅ Withdrawal Paid",
                f"{interaction.user.mention} confirmed payout of **💎 {format_amount(ticket['amount'])}** to <@{ticket['user_id']}>.",
                discord.Colour.green()
            )
        )

        await send_ticket_log(interaction.guild, WITHDRAW_LOG_CHANNEL_ID, "✅ Withdrawal Paid", ticket, interaction.user, discord.Colour.green())
        await send_log(interaction.guild, "Withdrawal Paid", f"Amount: {ticket['amount']}", discord.Colour.green())
        await close_ticket_channel(interaction.channel)

    @discord.ui.button(label="Deny & Refund", emoji="❌", style=discord.ButtonStyle.danger, custom_id="withdraw_deny")
    async def deny(self, interaction, button):
        ticket = DATA["tickets"].get(str(interaction.channel.id))
        if not ticket or ticket.get("status") != "open":
            await interaction.response.send_message("❌ This ticket is no longer active.", ephemeral=True)
            return

        if not is_staff(interaction.user):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return

        user = ensure_user(ticket["user_id"])
        user["balance"] += ticket["amount"]
        ticket["status"] = "denied"
        save_data()

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

        await interaction.channel.send(
            embed=normal_embed(
                "❌ Withdrawal Denied",
                f"Denied by {interaction.user.mention}. **💎 {format_amount(ticket['amount'])}** refunded to <@{ticket['user_id']}>.",
                discord.Colour.red()
            )
        )

        await send_ticket_log(interaction.guild, WITHDRAW_LOG_CHANNEL_ID, "❌ Withdrawal Denied", ticket, interaction.user, discord.Colour.red())
        await close_ticket_channel(interaction.channel)


@tree.command(name="deposit", description="Open a ticket to deposit gems.")
@app_commands.describe(amount="Example: 10m, 500m, 1b", roblox_username="Your valid Roblox username")
async def deposit(interaction, amount: str, roblox_username: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not await verification_check(interaction):
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed <= 0:
        await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    roblox_check = await get_roblox_user(roblox_username)
    if not roblox_check:
        await interaction.followup.send(f"❌ `{roblox_username}` is not a valid or real Roblox username. Please provide your actual account username.", ephemeral=True)
        return
    
    valid_roblox_name = roblox_check["name"]

    channel = await create_ticket_channel(interaction.guild, interaction.user, "deposit")

    embed = normal_embed(
        "💰 Deposit Ticket",
        f"👤 **User:** {interaction.user.mention}\n"
        f"🎮 **Roblox Username:** `{valid_roblox_name}`\n"
        f"💎 **Amount:** **{format_amount(parsed)}**\n\n"
        f"⏳ Please wait for staff to assist you!",
        discord.Colour.gold()
    )

    view = DepositTicketView()
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    ping = staff_role.mention if staff_role else ""

    ticket_msg = await channel.send(content=f"{interaction.user.mention} {ping}", embed=embed, view=view)

    DATA["tickets"][str(channel.id)] = {
        "type": "deposit",
        "user_id": interaction.user.id,
        "roblox_username": valid_roblox_name,
        "amount": parsed,
        "status": "open",
        "message_id": ticket_msg.id
    }
    save_data()

    await interaction.followup.send(f"✅ Deposit ticket created: {channel.mention}", ephemeral=True)


@tree.command(name="withdraw", description="Open a ticket to withdraw gems.")
@app_commands.describe(amount="Example: 10m, 500m, 1b", roblox_username="Your valid Roblox username")
async def withdraw(interaction, amount: str, roblox_username: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not await verification_check(interaction):
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed <= 0:
        await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return

    if user.get("to_wager", 0) > 0:
        await interaction.response.send_message(
            f"❌ You must wager **{format_amount(user['to_wager'])}** more gems before you can withdraw!",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    roblox_check = await get_roblox_user(roblox_username)
    if not roblox_check:
        await interaction.followup.send(f"❌ `{roblox_username}` is not a valid or real Roblox username. Please provide your actual account username.", ephemeral=True)
        return
    
    valid_roblox_name = roblox_check["name"]

    user["balance"] -= parsed
    save_data()

    channel = await create_ticket_channel(interaction.guild, interaction.user, "withdraw")

    embed = normal_embed(
        "💸 Withdrawal Ticket",
        f"👤 **User:** {interaction.user.mention}\n"
        f"🎮 **Roblox Username:** `{valid_roblox_name}`\n"
        f"💎 **Amount:** **{format_amount(parsed)}** (held from balance)\n\n"
        f"⏳ Please wait for staff to assist you!",
        discord.Colour.gold()
    )

    view = WithdrawTicketView()
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    ping = staff_role.mention if staff_role else ""

    ticket_msg = await channel.send(content=f"{interaction.user.mention} {ping}", embed=embed, view=view)

    DATA["tickets"][str(channel.id)] = {
        "type": "withdraw",
        "user_id": interaction.user.id,
        "roblox_username": valid_roblox_name,
        "amount": parsed,
        "status": "open",
        "message_id": ticket_msg.id
    }
    save_data()

    await interaction.followup.send(f"✅ Withdrawal ticket created: {channel.mention}", ephemeral=True)

