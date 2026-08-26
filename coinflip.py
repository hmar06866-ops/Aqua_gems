"""Aqua Gems Casino — Coinflip PvP / vs bot."""
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


def add_game_stats(embed, bet, multiplier, winnings):
    embed.add_field(
        name="Game Stats",
        value=(
            f"💎 **Bet:** {format_amount(bet)}\n"
            f"✨ **Multiplier:** {multiplier:.2f}x\n"
            f"💎 **Winnings:** {format_amount(winnings)}\n"
            f"⌛ **Next click:** —"
        ),
        inline=False,
    )
    return embed

class CoinflipView(discord.ui.View):
    def __init__(self, creator: discord.Member, amount_str: str, raw_amount: int, side: str = "heads"):
        super().__init__(timeout=None)
        self.creator = creator
        self.amount_str = amount_str
        self.raw_amount = raw_amount
        self.creator_side = side.lower()
        self.opponent = None
        self.game_over = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if DATA["settings"]["paused"]:
            await interaction.response.send_message("⏸️ **Games are paused.**", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Join", style=discord.ButtonStyle.blurple, emoji="👤")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.creator.id:
            await interaction.response.send_message("You cannot join your own coinflip!", ephemeral=True)
            return

        if self.opponent or self.game_over:
            await interaction.response.send_message("This coinflip already has an opponent or is finished!", ephemeral=True)
            return

        opp = ensure_user(interaction.user.id)
        if opp["balance"] < self.raw_amount:
            await interaction.response.send_message("❌ Insufficient balance to join.", ephemeral=True)
            return

        self.opponent = interaction.user
        self.game_over = True

        opp["balance"] -= self.raw_amount
        save_data()

        opponent_side = "tails" if self.creator_side == "heads" else "heads"

        flip_frames = [
            "🪙 Flipping... (🔄 Heads)",
            "🪙 Flipping... (🔄 Tails)",
            "🪙 Flipping... (🔄 Heads)",
            "🪙 Flipping... (✨ Landing...)"
        ]

        for frame in flip_frames:
            await interaction.message.edit(embed=normal_embed("🪙 Coinflip Animation", frame, discord.Colour.blue()))
            await asyncio.sleep(0.4)

        winner = random.choice([self.creator, self.opponent])
        loser = self.opponent if winner == self.creator else self.creator
        winning_side = self.creator_side if winner == self.creator else opponent_side

        creator_user = ensure_user(self.creator.id)
        opponent_user = ensure_user(self.opponent.id)

        # PvP coinflip has a 7% tax on the gross 2x payout.
        payout = int(self.raw_amount * 2 * 0.93)
        winner_user = creator_user if winner == self.creator else opponent_user
        winner_user["balance"] += payout

        creator_user["wagered"] += self.raw_amount
        opponent_user["wagered"] += self.raw_amount

        if creator_user["to_wager"] > 0:
            creator_user["to_wager"] = max(0, creator_user["to_wager"] - self.raw_amount)
        if opponent_user["to_wager"] > 0:
            opponent_user["to_wager"] = max(0, opponent_user["to_wager"] - self.raw_amount)

        add_history(self.creator.id, "Coinflip (PvP)", self.raw_amount, "Win" if winner == self.creator else "Loss")
        add_history(self.opponent.id, "Coinflip (PvP)", self.raw_amount, "Win" if winner == self.opponent else "Loss")
        save_data()

        await update_milestone_roles(self.creator)
        await update_milestone_roles(self.opponent)

        embed = normal_embed("🪙 Coinflip Result", colour=discord.Colour.green())
        embed.add_field(name="Result", value=f"**{winning_side.upper()}**", inline=False)
        embed.add_field(name="", value=f"🟢 **{winner.mention} WON!**", inline=False)
        embed.add_field(name="", value=f"+💎 {format_amount(payout)}", inline=False)
        add_game_stats(embed, self.raw_amount, 1.86, payout)

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

        await send_log(
            interaction.guild,
            "🪙 Coinflip PvP",
            f"Winner: {winner.mention}\nLoser: {loser.mention}\nAmount: **{self.amount_str}**",
            discord.Colour.green()
        )

    @discord.ui.button(label="Call Bot", style=discord.ButtonStyle.secondary, emoji="🤖")
    async def call_bot_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.creator.id:
            await interaction.response.send_message("Only the creator can trigger the bot!", ephemeral=True)
            return

        if self.opponent or self.game_over:
            await interaction.response.send_message("An opponent has already joined or the game is finished!", ephemeral=True)
            return

        self.game_over = True
        
        flip_frames = [
            "🪙 Flipping... (🔄 Heads)",
            "🪙 Flipping... (🔄 Tails)",
            "🪙 Flipping... (🔄 Heads)",
            "🪙 Flipping... (✨ Landing...)"
        ]

        await interaction.response.edit_message(view=self)
        for frame in flip_frames:
            await interaction.message.edit(embed=normal_embed("🪙 Coinflip Animation", frame, discord.Colour.blue()))
            await asyncio.sleep(0.4)

        creator_user = ensure_user(self.creator.id)

        user_won = random.random() < 0.32
        if user_won:
            result = self.creator_side
        else:
            result = "tails" if self.creator_side == "heads" else "heads"

        if user_won:
            payout = int(self.raw_amount * 2 * 0.93)
            creator_user["balance"] += payout
            DATA["global_stats"]["bot_game_profit"] -= (payout - self.raw_amount)
            status_text = "🟢 **YOU WIN!**"
            amount_text = f"+💎 {self.amount_str}"
            colour = discord.Colour.green()
        else:
            DATA["global_stats"]["bot_game_profit"] += self.raw_amount
            status_text = "🔴 **YOU LOST!**"
            amount_text = f"-💎 {self.amount_str}"
            colour = discord.Colour.red()

        creator_user["wagered"] += self.raw_amount

        if creator_user["to_wager"] > 0:
            creator_user["to_wager"] = max(0, creator_user["to_wager"] - self.raw_amount)

        add_history(self.creator.id, "Coinflip (vs Bot)", self.raw_amount, "Win" if user_won else "Loss")
        save_data()

        await update_milestone_roles(self.creator)

        embed = normal_embed("🪙 Coinflip vs Bot — Result", colour=colour)
        embed.add_field(name="Result", value=f"**{result.upper()}**", inline=False)
        embed.add_field(name="", value=status_text, inline=False)
        embed.add_field(name="", value=amount_text, inline=False)

        for child in self.children:
            child.disabled = True

        await interaction.edit_original_response(embed=embed, view=self)

        await send_log(
            interaction.guild,
            "🪙 Coinflip vs Bot",
            f"Player: {self.creator.mention}\nAmount: **{self.amount_str}**\nResult: **{'Win' if user_won else 'Loss'}**",
            colour
        )

    @discord.ui.button(label="Flip", style=discord.ButtonStyle.success, emoji="🪙")
    async def flip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.call_bot_button(interaction, button)


@tree.command(name="coinflip", description="Create a coinflip bet.")
@game_cooldown()
@app_commands.describe(amount="The amount of gems to bet (e.g. 10m, 500m, 1b)", side="Choose heads or tails (default: heads)")
@app_commands.choices(side=[
    app_commands.Choice(name="Heads", value="heads"),
    app_commands.Choice(name="Tails", value="tails")
])
async def coinflip(interaction: discord.Interaction, amount: str, side: app_commands.Choice[str] = None):
    if not await verification_check(interaction) or await game_paused(interaction):
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed < MIN_GAME_AMOUNT:
        await interaction.followup.send("❌ Minimum bet amount is **10M**.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.followup.send("❌ Insufficient balance.", ephemeral=True)
        return

    user["balance"] -= parsed
    save_data()

    chosen_side = side.value if side else "heads"
    formatted_bet = format_amount(parsed)

    await interaction.response.send_message(
        f"✅ {interaction.user.mention} created a coinflip!",
        ephemeral=False
    )

    heads_val = interaction.user.mention if chosen_side == "heads" else "No one"
    tails_val = interaction.user.mention if chosen_side == "tails" else "No one"

    target_channel = interaction.client.get_channel(COINFLIP_CHANNEL_ID)
    if not target_channel:
        try:
            target_channel = await interaction.client.fetch_channel(COINFLIP_CHANNEL_ID)
        except Exception:
            target_channel = interaction.channel

    embed = normal_embed("🪙 Coinflip", "Choose your side!", discord.Colour.blue())
    embed.set_author(name="Aqua Gems Casino", icon_url=interaction.client.user.display_avatar.url)
    embed.add_field(name="Heads", value=heads_val, inline=False)
    embed.add_field(name="Tails", value=tails_val, inline=False)
    embed.add_field(name="Bet Amount", value=f"💎 {formatted_bet}", inline=False)

    view = CoinflipView(
        creator=interaction.user,
        amount_str=formatted_bet,
        raw_amount=parsed,
        side=chosen_side
    )
    
    gui_message = await target_channel.send(embed=embed, view=view)

    is_active = True
    elapsed_time = 0
    timeout_limit = 300

    while is_active:
        await asyncio.sleep(5)
        elapsed_time += 5

        if view.game_over:
            is_active = False

        elif elapsed_time >= timeout_limit:
            is_active = False
            for child in view.children:
                child.disabled = True

            if not view.game_over:
                creator_user = ensure_user(interaction.user.id)
                creator_user["balance"] += parsed
                save_data()

            embed.description = "⏰ **Coinflip expired! Wager refunded.**"
            try:
                await gui_message.edit(embed=embed, view=view)
            except Exception:
                pass

