"""Aqua Gems Casino — Slots, Wheel, Mystery Box."""
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

class SlotMachineView(discord.ui.View):
    def __init__(self, owner_id: int, amount: int):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.amount = amount
        self.slot_emojis = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This slot machine is not yours!", ephemeral=True)
            return False
        if await game_paused(interaction):
            return False
        return True

    @discord.ui.button(label="Spin 🎰", style=discord.ButtonStyle.success)
    async def spin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)

        for _ in range(4):
            r1, r2, r3 = random.choices(self.slot_emojis, k=3)
            frame_embed = normal_embed("🎰 Slot Machine", f"Spinning reels...\n\n| {r1} | {r2} | {r3} |", discord.Colour.gold())
            try:
                await interaction.edit_original_response(embed=frame_embed)
            except discord.HTTPException:
                pass
            await asyncio.sleep(0.5)

        res1 = random.choice(self.slot_emojis)
        res2 = random.choice(self.slot_emojis)
        res3 = random.choice(self.slot_emojis)

        user = ensure_user(self.owner_id)
        user["wagered"] += self.amount
        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.amount)

        if random.random() < 0.65:
            res1, res2, res3 = random.sample(self.slot_emojis, 3)
            multiplier = 0.0
        else:
            win_roll = random.random()
            if win_roll < 0.020:
                res1 = res2 = res3 = "7️⃣"
                multiplier = 10.0
            elif win_roll < 0.08:
                res1 = res2 = res3 = "💎"
                multiplier = 5.0
            elif win_roll < 0.35:
                triple = random.choice(["🍒", "🍋", "🍊", "🍇"])
                res1 = res2 = res3 = triple
                multiplier = 3.0
            else:
                pair = random.choice(self.slot_emojis)
                other_choices = [e for e in self.slot_emojis if e != pair]
                other = random.choice(other_choices)
                result = [pair, pair, other]
                random.shuffle(result)
                res1, res2, res3 = result
                multiplier = 1.5

        if multiplier > 0:
            payout = int(self.amount * multiplier)
            net_profit = payout - self.amount
            user["balance"] += payout
            DATA["global_stats"]["bot_game_profit"] -= net_profit
            result_text = f"🏆 **You Won {format_amount(payout)}!** ({multiplier}x)"
            colour = discord.Colour.green()
            result_type = "Win"
        else:
            DATA["global_stats"]["bot_game_profit"] += self.amount
            result_text = f"💀 **You Lost!**"
            colour = discord.Colour.red()
            result_type = "Loss"

        add_history(self.owner_id, "Slots", self.amount, result_type)
        save_data()
        await update_milestone_roles(interaction.user)

        embed = normal_embed(
            "🎰 Slot Machine Results",
            f"| {res1} | {res2} | {res3} |\n\n{result_text}",
            colour
        )
        add_game_stats(embed, self.amount, multiplier, int(self.amount * multiplier) if multiplier > 0 else 0)
        await interaction.edit_original_response(embed=embed, view=None)

        await send_log(
            interaction.guild,
            "🎰 Slot Machine",
            f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nResult: **{result_type}**",
            colour
        )
        self.stop()


@tree.command(name="slots", description="Play the animated slot machine.")
@game_cooldown()
@app_commands.describe(amount="Bet amount (e.g., 10m, 1b)")
async def slots(interaction: discord.Interaction, amount: str):
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

    view = SlotMachineView(interaction.user.id, parsed)
    embed = normal_embed("🎰 Slot Machine", f"| ❓ | ❓ | ❓ |\n\nPress **Spin** to play!", discord.Colour.gold())
    await interaction.response.send_message(embed=embed, view=view)


class WheelOfFortuneView(discord.ui.View):
    def __init__(self, owner_id: int, amount: int):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.amount = amount

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This wheel is not yours!", ephemeral=True)
            return False
        if await game_paused(interaction):
            return False
        return True

    @discord.ui.button(label="Spin Wheel 🎡", style=discord.ButtonStyle.blurple)
    async def spin_wheel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=normal_embed("🎡 Wheel of Fortune", "Spinning the wheel... 🔄", discord.Colour.purple()),
            view=self
        )
        await asyncio.sleep(2)

        # Wheel: exactly 35% of rolls are winning outcomes (>1x).
        outcomes = [0.0, 0.5, 1.0, 1.25, 2.0, 3.0, 5.0, 10.0]
        weights = [40, 15, 10, 10, 8, 7, 6, 4]
        mult = random.choices(outcomes, weights=weights, k=1)[0]

        user = ensure_user(self.owner_id)
        user["wagered"] += self.amount
        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.amount)

        payout = int(self.amount * mult)
        if mult > 0:
            net_profit = payout - self.amount
            user["balance"] += payout
            DATA["global_stats"]["bot_game_profit"] -= net_profit
            colour = discord.Colour.green()
            result_type = "Win" if mult > 1.0 else ("Push" if mult == 1.0 else "Partial Loss")
            res_desc = f"🎉 **Hit {mult}x multiplier!**\nPayout: **{format_amount(payout)}**"
        else:
            DATA["global_stats"]["bot_game_profit"] += self.amount
            colour = discord.Colour.red()
            result_type = "Loss"
            res_desc = f"💀 **Hit 0x (Bankrupt)!** You lost your bet."

        add_history(self.owner_id, "Wheel of Fortune", self.amount, result_type)
        save_data()
        await update_milestone_roles(interaction.user)

        embed = normal_embed("🎡 Wheel of Fortune Result", res_desc, colour)
        add_game_stats(embed, self.amount, mult, payout)
        await interaction.edit_original_response(embed=embed, view=None)

        await send_log(
            interaction.guild,
            "🎡 Wheel of Fortune",
            f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nMultiplier: **{mult}x**",
            colour
        )
        self.stop()


@tree.command(name="wheel", description="Spin the Wheel of Fortune.")
@game_cooldown()
@app_commands.describe(amount="Bet amount (e.g., 10m, 1b)")
async def wheel(interaction: discord.Interaction, amount: str):
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

    view = WheelOfFortuneView(interaction.user.id, parsed)
    embed = normal_embed("🎡 Wheel of Fortune", "Click below to spin the wheel!", discord.Colour.purple())
    await interaction.response.send_message(embed=embed, view=view)


class MysteryBoxView(discord.ui.View):
    def __init__(self, owner_id: int, cost: int):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.cost = cost

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This mystery box isn't yours!", ephemeral=True)
            return False
        if await game_paused(interaction):
            return False
        return True

    @discord.ui.button(label="Open Mystery Box 🎁", style=discord.ButtonStyle.success)
    async def open_box(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            embed=normal_embed("🎁 Mystery Box", "Unwrapping mystery box... ✨", discord.Colour.gold()),
            view=self
        )
        await asyncio.sleep(1.5)

        # Mystery Box maximum reward is capped at 3x.
        multipliers = [0.25, 0.5, 0.8, 1.2, 2.0, 2.5, 3.0]
        weights = [33, 27, 20, 13, 5, 1.5, 0.5]
        mult = random.choices(multipliers, weights=weights, k=1)[0]

        user = ensure_user(self.owner_id)
        user["wagered"] += self.cost
        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.cost)

        payout = int(self.cost * mult)
        net_profit = payout - self.cost
        user["balance"] += payout
        DATA["global_stats"]["bot_game_profit"] -= net_profit

        colour = discord.Colour.green() if mult >= 1.0 else discord.Colour.red()
        result_type = "Win" if mult >= 1.0 else "Loss"

        add_history(self.owner_id, "Mystery Box", self.cost, result_type)
        save_data()
        await update_milestone_roles(interaction.user)

        embed = normal_embed(
            "🎁 Mystery Box Opened",
            f"You found a **{mult}x reward box**!\n💎 **Payout:** {format_amount(payout)}",
            colour
        )
        add_game_stats(embed, self.cost, mult, payout)
        await interaction.edit_original_response(embed=embed, view=None)

        await send_log(
            interaction.guild,
            "🎁 Mystery Box",
            f"Player: {interaction.user.mention}\nCost: **{format_amount(self.cost)}**\nMultiplier: **{mult}x**",
            colour
        )
        self.stop()


@tree.command(name="mysterybox", description="Purchase and open a mystery box.")
@game_cooldown()
@app_commands.describe(amount="Box cost / bid amount (e.g., 10m, 1b)")
async def mysterybox(interaction: discord.Interaction, amount: str):
    if not await verification_check(interaction) or await game_paused(interaction):
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed < MIN_GAME_AMOUNT:
        await interaction.followup.send("❌ Minimum amount is **10M**.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.followup.send("❌ Insufficient balance.", ephemeral=True)
        return

    user["balance"] -= parsed
    save_data()

    view = MysteryBoxView(interaction.user.id, parsed)
    embed = normal_embed("🎁 Mystery Box Auction", "A mysterious box is ready to be opened. Click below!", discord.Colour.gold())
    await interaction.response.send_message(embed=embed, view=view)

