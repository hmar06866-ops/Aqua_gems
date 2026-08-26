"""Aqua Gems Casino — bot instance, cooldown, error handler."""
import discord
from discord.ext import commands
from discord import app_commands

from config import GAME_COOLDOWN_SECONDS

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

tree = bot.tree


def game_cooldown():
    """Shared 5s-per-user cooldown decorator for every game command."""
    return app_commands.checks.cooldown(
        1, GAME_COOLDOWN_SECONDS, key=lambda i: i.user.id
    )


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Slow down! You can play again in **{error.retry_after:.1f}s**."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception:
            pass
        return

    print(f"Unhandled app command error: {error}")
    try:
        message = "❌ Something went wrong running that command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass
