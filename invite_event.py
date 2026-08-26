"""
Aqua Gems Casino — Invite Event announcement command.

Slash command: /send_invite_event
Restricted to server administrators + owner ID 1500198665933820004.
"""
from typing import Optional

import discord
from discord import app_commands

from bot_instance import tree
from utils import normal_embed

# Owner / extra allowed user
OWNER_ID = 1500198665933820004


def _can_run(interaction: discord.Interaction) -> bool:
    """Admins or the designated owner ID."""
    if interaction.user.id == OWNER_ID:
        return True
    if isinstance(interaction.user, discord.Member):
        return interaction.user.guild_permissions.administrator
    return False


@tree.command(
    name="send_invite_event",
    description="Announce an Aqua Invite Event (Admins + owner only)",
)
@app_commands.describe(
    channel="Channel to post the announcement in (defaults to current channel)",
    ping_role="Optional role to ping outside the embed",
)
async def send_invite_event(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
    ping_role: Optional[discord.Role] = None,
):
    if not _can_run(interaction):
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.",
            ephemeral=True,
        )
        return

    target = channel or interaction.channel
    if not isinstance(target, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message(
            "❌ Could not resolve a valid text channel.",
            ephemeral=True,
        )
        return

    embed = normal_embed(
        "🌊 Aqua Invite Event!",
        (
            "Bring your friends to **Aqua Gems Casino** and climb the leaderboard together!\n\n"
            "**How it works**\n"
            "• Invite friends using your personal invite link\n"
            "• When they join & verify, you both earn rewards\n"
            "• Stack invites for bigger gem bonuses\n\n"
            "**Rewards**\n"
            "• Gems for every successful invite\n"
            "• Bonus multipliers during the event window\n"
            "• Special recognition for top inviters\n\n"
            "Drop your invite links, grow the community, and stack those **gems** 💎\n"
            "Let's make Aqua the biggest casino on Discord!"
        ),
        discord.Colour.teal(),
    )
    embed.set_footer(text="Aqua Gems Casino • Invite Event")

    content = ping_role.mention if ping_role else None

    try:
        await target.send(content=content, embed=embed)
        await interaction.response.send_message(
            f"✅ Aqua Invite Event announced in {target.mention}",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ I don't have permission to send messages in {target.mention}.",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ Failed to send announcement: {e}",
            ephemeral=True,
        )