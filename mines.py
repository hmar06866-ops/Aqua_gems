"""Aqua Gems Casino — Mines game."""
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

class MinesTileButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(
            style=discord.ButtonStyle.secondary, 
            label="\u200b", 
            row=index // 5,
            custom_id=f"mines_tile_{index}"
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_click(interaction, self.index)


class MinesGameView(discord.ui.View):
    def __init__(self, owner_id, amount, num_mines):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.amount = amount
        self.num_mines = num_mines
        self.revealed = set()
        self.game_over = False

        # Normal Mines board: place exactly the selected number of mines
        # before the game starts. The existing multiplier table is unchanged.
        self.bomb_positions = set(random.sample(range(25), self.num_mines))
        self.tile_buttons = {}

        for i in range(25):
            btn = MinesTileButton(i)
            self.tile_buttons[i] = btn
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This game is not yours!", ephemeral=True)
            return False
        if await game_paused(interaction):
            return False
        return True

    def get_current_multiplier(self):
        return calculate_mines_multiplier(self.num_mines, len(self.revealed))

    def get_next_multiplier(self):
        return calculate_mines_multiplier(self.num_mines, len(self.revealed) + 1)

    def build_embed(self, status="in_progress"):
        current_mult = self.get_current_multiplier()
        current_winnings = int(self.amount * current_mult)
        next_mult = self.get_next_multiplier()
        next_winnings = int(self.amount * next_mult)

        if status == "cashed_out":
            title = f"{self.num_mines} Mines Cashed Out"
            colour = discord.Colour.green()
            winnings_str = f"💎 **Winnings:** {format_amount(current_winnings)}"
        elif status == "hit_bomb":
            title = f"{self.num_mines} Mines Hit a Bomb"
            colour = discord.Colour.red()
            winnings_str = "💎 **Current winnings:** 0"
        else:
            title = f"{self.num_mines} Mines"
            colour = discord.Colour.purple()
            winnings_str = f"💎 **Current winnings:** {format_amount(current_winnings)}"

        if len(self.revealed) > 0 and not self.game_over:
            cashout_instruction = "\n🟢 **Click any of your revealed diamonds to cash out!**"
        else:
            cashout_instruction = ""

        description = (
            f"**Game Stats**\n"
            f"💎 **Bet:** {format_amount(self.amount)}\n"
            f"✨ **Multiplier:** {current_mult:.2f}x\n"
            f"{winnings_str}\n"
            f"⌛ **Next click:** {format_amount(next_winnings)}\n"
            f"{cashout_instruction}\n\n"
            f"Click hidden tiles to reveal diamonds!"
        )

        embed = discord.Embed(
            title=title,
            description=description,
            colour=colour
        )
        embed.set_author(name="Aqua Gems Casino")
        embed.set_footer(text="Aqua Gems Casino")
        return embed

    async def process_click(self, interaction: discord.Interaction, index: int):
        if self.game_over:
            return

        if index in self.revealed:
            await self.cash_out(interaction)
            return

        # Normal Mines logic: the result comes from the pre-placed board.
        # There is no 50%/55% per-click mine roll.
        if index in self.bomb_positions:
            await self.hit_bomb(interaction, hit_index=index)
            return

        self.revealed.add(index)
        btn = self.tile_buttons[index]
        btn.style = discord.ButtonStyle.success
        btn.emoji = "💎"
        btn.label = None

        if len(self.revealed) >= 24:
            await self.cash_out(interaction)
            return

        await interaction.response.edit_message(
            embed=self.build_embed(status="in_progress"),
            view=self
        )

    async def cash_out(self, interaction: discord.Interaction):
        if len(self.revealed) == 0:
            await interaction.response.send_message("❌ You must reveal at least one tile before cashing out!", ephemeral=True)
            return

        self.game_over = True
        mult = self.get_current_multiplier()
        payout = int(self.amount * mult)
        net_profit = payout - self.amount

        user = ensure_user(self.owner_id)
        user["balance"] += payout
        user["wagered"] += self.amount

        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.amount)

        add_history(self.owner_id, f"Mines ({self.num_mines})", self.amount, "Win")
        
        DATA["global_stats"]["bot_game_profit"] -= net_profit
        save_data()

        await update_milestone_roles(interaction.user)

        for idx, btn in self.tile_buttons.items():
            btn.disabled = True
            if idx in self.bomb_positions:
                btn.style = discord.ButtonStyle.danger
                btn.emoji = "💣"
                btn.label = None
            elif idx in self.revealed:
                btn.style = discord.ButtonStyle.success
                btn.emoji = "💎"
                btn.label = None
            else:
                # Reveal every safe tile as green when the game ends.
                btn.style = discord.ButtonStyle.success
                btn.emoji = "💎"
                btn.label = None

        embed = self.build_embed(status="cashed_out")
        await interaction.response.edit_message(embed=embed, view=self)

        await send_log(
            interaction.guild,
            "💣 Mines Cashed Out",
            f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nMines: **{self.num_mines}**\nPayout: **{format_amount(payout)}** ({mult:.2f}x)",
            discord.Colour.green()
        )
        self.stop()

    async def hit_bomb(self, interaction: discord.Interaction, hit_index: int):
        self.game_over = True

        # The complete mine board was fixed when the game started.
        # Reveal all mines so the player can see the selected mine count.
        for mine_index in self.bomb_positions:
            btn = self.tile_buttons[mine_index]
            btn.style = discord.ButtonStyle.danger
            btn.emoji = "💣"
            btn.label = None
            btn.disabled = True

        user = ensure_user(self.owner_id)
        user["wagered"] += self.amount

        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.amount)

        add_history(self.owner_id, f"Mines ({self.num_mines})", self.amount, "Loss")

        for tile_index, btn in self.tile_buttons.items():
            if tile_index in self.bomb_positions:
                continue
            if tile_index not in self.revealed:
                btn.style = discord.ButtonStyle.secondary
                btn.label = "·"
            btn.disabled = True
        
        DATA["global_stats"]["bot_game_profit"] += self.amount
        save_data()

        await update_milestone_roles(interaction.user)

        for idx, btn in self.tile_buttons.items():
            btn.disabled = True
            if idx == hit_index:
                btn.style = discord.ButtonStyle.danger
                btn.emoji = "💥"
                btn.label = None
            elif idx in self.bomb_positions:
                btn.style = discord.ButtonStyle.danger
                btn.emoji = "💣"
                btn.label = None
            elif idx in self.revealed:
                btn.style = discord.ButtonStyle.success
                btn.emoji = "💎"
                btn.label = None
            else:
                # Reveal every safe tile as green when the game ends.
                btn.style = discord.ButtonStyle.success
                btn.emoji = "💎"
                btn.label = None

        embed = self.build_embed(status="hit_bomb")
        await interaction.response.edit_message(embed=embed, view=self)

        await send_log(
            interaction.guild,
            "💥 Mines Hit a Bomb",
            f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nMines: **{self.num_mines}**",
            discord.Colour.red()
        )
        self.stop()


# ============================================================
# MINES GAME MULTIPLIERS
# ============================================================
#
# 1 mine uses the exact multiplier sequence requested.
# 2 mines is intentionally only a little better.
# Other mine counts keep the existing odds-based curve.

MINES_1_MULTIPLIERS = [
    0.62, 0.68, 0.75, 0.78, 0.84,
    0.97, 1.03, 1.09, 1.21, 1.24,
    1.34, 1.40, 1.47
]

# Small +0.02 improvement over the 1-mine curve.
MINES_2_MULTIPLIERS = [
    0.63, 0.70, 0.77, 0.80, 0.86,
    0.99, 1.05, 1.11, 1.22, 1.26,
    1.36, 1.42, 1.49
]

MINES_START_MULTIPLIER = 1.10
MINES_GROWTH_SOFTEN = 0.55


def _floor_2(x: float) -> float:
    return math.floor(x * 100) / 100


def _fair_multiplier(mines_count: int, revealed_count: int) -> float:
    total_tiles = 25
    safe_tiles = total_tiles - mines_count
    revealed_count = min(revealed_count, safe_tiles)

    mult = 1.0
    for i in range(revealed_count):
        mult *= (total_tiles - i) / (safe_tiles - i)
    return mult


def calculate_mines_multiplier(mines_count: int, revealed_count: int) -> float:
    if revealed_count <= 0:
        return 1.00

    if mines_count == 1:
        index = revealed_count - 1
        if index < len(MINES_1_MULTIPLIERS):
            return MINES_1_MULTIPLIERS[index]

    if mines_count == 2:
        index = revealed_count - 1
        if index < len(MINES_2_MULTIPLIERS):
            return MINES_2_MULTIPLIERS[index]

    total_tiles = 25
    safe_tiles = total_tiles - mines_count
    revealed_count = min(revealed_count, safe_tiles)

    fair = _fair_multiplier(mines_count, revealed_count)
    softened = fair ** MINES_GROWTH_SOFTEN

    first_click_softened = _fair_multiplier(mines_count, 1) ** MINES_GROWTH_SOFTEN
    scale = MINES_START_MULTIPLIER / first_click_softened

    return _floor_2(softened * scale)


@tree.command(name="mines", description="Play Aqua Gems Casino Mines game.")
@game_cooldown()
@app_commands.describe(
    mines="Number of mines (1-24)",
    bet="Bet amount (e.g., 10m, 500m, 1b)"
)
async def mines(interaction: discord.Interaction, mines: app_commands.Range[int, 1, 24], bet: str):
    if not await verification_check(interaction) or await game_paused(interaction):
        return

    parsed = parse_amount(bet)
    if parsed is None or parsed < MIN_GAME_AMOUNT:
        await interaction.response.send_message("❌ Minimum bet amount is **10M**.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return

    user["balance"] -= parsed
    save_data()

    view = MinesGameView(interaction.user.id, parsed, mines)
    embed = view.build_embed(status="in_progress")

    await interaction.response.send_message(embed=embed, view=view)

