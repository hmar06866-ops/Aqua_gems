"""Aqua Gems Casino — Roblox verification system."""
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

async def get_roblox_user(username):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": False}
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if not data.get("data"):
                    return None
                return data["data"][0]
        except Exception:
            return None


async def get_roblox_avatar(user_id):
    async with aiohttp.ClientSession() as session:
        try:
            url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false"
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                if data.get("data"):
                    return data["data"][0].get("imageUrl")
        except Exception:
            pass
    return None


class RobloxUsernameModal(discord.ui.Modal, title="Roblox Account Verification"):
    username_input = discord.ui.TextInput(
        label="Roblox Username",
        placeholder="Enter your exact Roblox username...",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        if is_verified(interaction.user):
            await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        roblox_username = self.username_input.value.strip()
        roblox_data = await get_roblox_user(roblox_username)

        if not roblox_data:
            await interaction.followup.send(f"❌ Could not find Roblox account `{roblox_username}`. Please check the spelling.", ephemeral=True)
            return

        roblox_id = roblox_data["id"]
        canonical_name = roblox_data["name"]
        avatar_url = await get_roblox_avatar(roblox_id)

        code = f"PS99-{random.randint(100000, 999999)}"
        DATA["verification"][str(interaction.user.id)] = {
            "username": canonical_name,
            "roblox_id": roblox_id,
            "code": code,
            "confirmed": False
        }
        save_data()

        embed = discord.Embed(
            title="🔗 Connect Roblox Account",
            description=(
                f"We found **{canonical_name}**!\n\n"
                f"1. Copy this unique verification code:\n```{code}```\n"
                f"2. Paste it into your **Roblox profile About / Bio** section.\n"
                f"3. Click **Check Verification** below once you've saved it."
            ),
            colour=discord.Colour.blurple()
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await interaction.followup.send(embed=embed, view=VerifyCheckView(canonical_name, roblox_id, code), ephemeral=True)


class VerifyCheckView(discord.ui.View):
    def __init__(self, username, roblox_id, code):
        super().__init__(timeout=300)
        self.username = username
        self.roblox_id = roblox_id
        self.code = code

    @discord.ui.button(label="Check Verification", style=discord.ButtonStyle.success, emoji="✅")
    async def check_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"https://users.roblox.com/v1/users/{self.roblox_id}") as response:
                    if response.status != 200:
                        await interaction.followup.send("❌ Failed to reach Roblox API. Please try again later.", ephemeral=True)
                        return
                    data = await response.json()
                    bio = data.get("description", "")
            except Exception:
                await interaction.followup.send("❌ Error connecting to Roblox services.", ephemeral=True)
                return

        if self.code not in bio:
            await interaction.followup.send(
                f"❌ Verification code `{self.code}` was not found in your Roblox profile Bio.\nMake sure you added it and saved your profile changes, then try again.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        if guild:
            role = guild.get_role(VERIFIED_ROLE_ID)
            if role:
                try:
                    await interaction.user.add_roles(role)
                except discord.Forbidden:
                    await interaction.followup.send("⚠️ Code matched, but I lack permissions to assign the verified role. Please contact a server administrator.", ephemeral=True)
                    return

        user_data = ensure_user(interaction.user.id)
        user_data["roblox"] = self.username
        user_data["roblox_id"] = self.roblox_id
        
        if str(interaction.user.id) in DATA["verification"]:
            DATA["verification"][str(interaction.user.id)]["confirmed"] = True
        save_data()

        await interaction.followup.send(f"🎉 **Successfully verified as Roblox user `{self.username}`!**", ephemeral=True)


class VerificationPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="🛡️", custom_id="persistent_verify_button")
    async def verify_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if is_verified(interaction.user):
            await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
            return
        await interaction.response.send_modal(RobloxUsernameModal())


@tree.command(name="verificationpanel", description="Sends the professional Roblox verification panel.")
async def verificationpanel(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
        return

    if interaction.channel_id != VERIFICATION_CHANNEL_ID:
        await interaction.response.send_message(f"❌ This command can only be used in <#{VERIFICATION_CHANNEL_ID}>.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🔒 Server Verification",
        description=(
            "Welcome to the server! To access the casino games, tips, and features, "
            "you must verify your Roblox account.\n\n"
            "**How to verify:**\n"
            "1️⃣ Click the **Verify** button below.\n"
            "2️⃣ Enter your Roblox username when prompted.\n"
            "3️⃣ Place the generated code into your Roblox profile bio and confirm!\n\n"
            "*Click the button below to start your verification process.*"
        ),
        colour=discord.Colour.from_rgb(43, 34, 85)
    )
    embed.set_footer(text="Aqua Gems Casino Verification")

    await interaction.channel.send(embed=embed, view=VerificationPanelView())
    await interaction.response.send_message("✅ Verification panel deployed successfully.", ephemeral=True)


# Keep legacy /verify command functioning seamlessly
@tree.command(name="verify", description="Verify your Roblox account.")
@app_commands.describe(username="Your Roblox username")
async def verify(interaction: discord.Interaction, username: str):
    if is_verified(interaction.user):
        await interaction.response.send_message("✅ You are already verified!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    roblox = await get_roblox_user(username)
    if not roblox:
        await interaction.followup.send("❌ Roblox username not found.", ephemeral=True)
        return

    avatar = await get_roblox_avatar(roblox["id"])
    code = f"PS99-{random.randint(100000, 999999)}"
    
    DATA["verification"][str(interaction.user.id)] = {
        "username": roblox["name"],
        "roblox_id": roblox["id"],
        "code": code,
        "confirmed": False
    }
    save_data()

    embed = normal_embed(
        "📝 Roblox Verification",
        f"**Username:** {roblox['name']}\n\nPut this exact code in your Roblox profile About/bio:\n\n```{code}```\n\nOnce added, press **Verify Now**.",
        discord.Colour.orange()
    )
    if avatar:
        embed.set_thumbnail(url=avatar)

    await interaction.followup.send(
        embed=embed,
        view=VerifyCheckView(roblox["name"], roblox["id"], code),
        ephemeral=True
    )

