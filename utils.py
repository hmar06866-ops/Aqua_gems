"""Aqua Gems Casino — shared helpers (embeds, permissions, logs, milestones)."""
import discord
from datetime import datetime, timezone

from config import (
    ADMIN_USER_IDS,
    STAFF_ROLE_ID,
    VERIFIED_ROLE_ID,
    MILESTONE_ROLES,
    GAME_LOG_CHANNEL_ID,
    PROFIT_TRACKER_CHANNEL_ID,
)
from data import DATA, save_data, ensure_user, format_amount


def get_user_rank_mention(guild: discord.Guild, wagered: int) -> str:
    highest_role_id = None
    highest_amount = None

    for amount, role_id in sorted(MILESTONE_ROLES.items()):
        if wagered >= amount:
            highest_role_id = role_id
            highest_amount = amount

    if highest_role_id and guild:
        role = guild.get_role(highest_role_id)
        if role:
            return f"{role.mention} [{format_amount(highest_amount)}+]"

    return "`None`"


def is_staff(member):
    return isinstance(member, discord.Member) and (
        member.id in ADMIN_USER_IDS or any(role.id == STAFF_ROLE_ID for role in member.roles)
    )


def is_verified(member):
    return isinstance(member, discord.Member) and any(
        role.id == VERIFIED_ROLE_ID for role in member.roles
    )


async def verification_check(interaction):
    if not is_verified(interaction.user):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Please verify first using the verification panel.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Please verify first using the verification panel.",
                ephemeral=True
            )
        return False
    return True


def normal_embed(title, description="", colour=None):
    if colour is None:
        colour = discord.Colour.purple()
    return discord.Embed(
        title=title,
        description=description,
        colour=colour,
        timestamp=datetime.now(timezone.utc)
    )


def get_live_profit_embed():
    deposits = DATA["global_stats"].get("total_deposits", 0)
    withdraws = DATA["global_stats"].get("total_withdraws", 0)
    game_profit = DATA["global_stats"].get("bot_game_profit", 0)

    manual_override = DATA["global_stats"].get("manual_total_net_profit")
    if manual_override is not None:
        total_net_profit = manual_override
    else:
        total_net_profit = (deposits - withdraws) + game_profit

    embed = discord.Embed(
        title="📊 Live Profit Tracker",
        colour=discord.Colour.gold()
    )
    embed.add_field(name="📥 Total Deposits", value=f"**💎 {format_amount(deposits)}**", inline=False)
    embed.add_field(name="📤 Total Withdraws", value=f"**💎 {format_amount(withdraws)}**", inline=False)
    embed.add_field(name="🎲 Net Game Profit", value=f"**💎 {format_amount(game_profit)}**", inline=False)
    embed.add_field(name="📈 Total Net Bot Profit", value=f"**💎 {format_amount(total_net_profit)}**", inline=False)
    embed.set_footer(text="Aqua Gems Casino")
    return embed


async def send_log(guild, title, description, colour=None):
    if not guild:
        return
    game_channel = guild.get_channel(GAME_LOG_CHANNEL_ID)
    if game_channel:
        try:
            log_embed = normal_embed(title, description, colour)
            await game_channel.send(embed=log_embed)
        except Exception:
            pass


async def update_milestone_roles(member):
    if not isinstance(member, discord.Member) or not member.guild:
        return

    user = ensure_user(member.id)
    total = user["wagered"]
    highest_role_id = None

    for amount, role_id in sorted(MILESTONE_ROLES.items(), reverse=True):
        if total >= amount:
            highest_role_id = role_id
            break

    if highest_role_id is None:
        return

    for role_id in MILESTONE_ROLES.values():
        role = member.guild.get_role(role_id)
        if role is None:
            continue

        if role_id == highest_role_id:
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                    try:
                        await member.send(
                            "🎉 **Congratulations!**\n\n"
                            f"You reached **{format_amount(total)}** "
                            f"of total game activity and unlocked {role.mention}!"
                        )
                    except discord.Forbidden:
                        pass
                except discord.Forbidden:
                    pass
        else:
            if role in member.roles:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    pass


async def game_paused(interaction):
    if DATA["settings"]["paused"]:
        msg = "⏸️ **All current games are currently paused.**\nPlease be patient!"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return True
    return False
