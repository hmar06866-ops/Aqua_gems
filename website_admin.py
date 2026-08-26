from pathlib import Path
import discord
from discord import app_commands
from bot_instance import tree

OWNER_ID = 1500198665933820004
FLAG = Path(__file__).resolve().parent / "Aqua_Website" / "OFFLINE.flag"


def _can(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    if isinstance(interaction.user, discord.Member):
        return interaction.user.guild_permissions.administrator
    return False


@tree.command(name="website", description="Turn the website on or off")
@app_commands.describe(state="on or off")
@app_commands.choices(state=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
])
async def website_cmd(interaction: discord.Interaction, state: app_commands.Choice[str]):
    if not _can(interaction):
        await interaction.response.send_message("❌ Owner/admin only.", ephemeral=True)
        return

    FLAG.parent.mkdir(parents=True, exist_ok=True)

    if state.value == "off":
        FLAG.write_text("1", encoding="utf-8")
        msg = "🛠️ Website **OFFLINE** (flag set)"
    else:
        if FLAG.exists():
            FLAG.unlink()
        msg = "✅ Website **ONLINE** (flag removed)"

    await interaction.response.send_message(msg, ephemeral=False)