"""Aqua Gems Casino — Towers game."""
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
import uuid
from datetime import datetime, timezone

from bot_instance import bot, tree, game_cooldown
from config import *
from data import DATA, save_data, ensure_user, add_history, parse_amount, parse_signed_amount, format_amount
from utils import (
    is_staff, is_verified, verification_check, normal_embed,
    get_live_profit_embed, send_log, update_milestone_roles,
    game_paused, get_user_rank_mention,
)


# Per-tile win chances requested for Towers.
# Easy = 50%, Medium = 25%, Hard = 30%.
TOWER_DIFFICULTIES = {
    "easy": {
        "tiles_per_row": 3,
        "safe_tiles": 2,
        "bomb_tiles": 1,
        "labels": ["Left", "Middle", "Right"]
    },
    "medium": {
        "tiles_per_row": 3,
        "safe_tiles": 1,
        "bomb_tiles": 2,
        "labels": ["Left", "Middle", "Right"]
    },
    "hard": {
        "tiles_per_row": 2,
        "safe_tiles": 1,
        "bomb_tiles": 1,
        "labels": ["Left", "Right"]
    }
}

TOTAL_TOWER_ROWS = 8


# Tower multipliers are fixed per row.
# Easy values match the requested table exactly.
# Medium and Hard are nerfed so the multipliers stay much lower.
TOWER_MULTIPLIERS = {
    "easy": [
        1.08, 1.17, 1.30, 1.43,
        1.52, 1.76, 1.93, 2.21
    ],
    "medium": [
        1.10, 1.22, 1.38, 1.55,
        1.76, 2.02, 2.30, 2.62
    ],
    "hard": [
        1.12, 1.27, 1.45, 1.66,
        1.91, 2.20, 2.55, 2.95
    ]
}


def calculate_towers_multiplier(difficulty: str, current_row: int) -> float:
    if current_row <= 0:
        return 1.00

    multipliers = TOWER_MULTIPLIERS[difficulty]
    row_index = min(current_row, len(multipliers)) - 1
    return multipliers[row_index]


class TowerDirectionButton(discord.ui.Button):
    def __init__(self, col_idx: int, label: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=label,
            row=0
        )
        self.col_idx = col_idx

    async def callback(self, interaction: discord.Interaction):
        await self.view.process_step(interaction, self.col_idx)


class TowersGameView(discord.ui.View):
    def __init__(self, owner_id: int, user_name: str, amount: int, difficulty: str):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.user_name = user_name
        self.amount = amount
        self.difficulty = difficulty
        self.current_row = 0
        self.game_over = False
        self.hit_row = None
        self.hit_col = None
        self.game_id = str(uuid.uuid4())

        cfg = TOWER_DIFFICULTIES[difficulty]
        self.tiles_per_row = cfg["tiles_per_row"]
        self.safe_tiles = cfg["safe_tiles"]
        self.bomb_tiles = cfg["bomb_tiles"]
        self.win_chance = cfg["win_chance"]
        self.labels = cfg["labels"]

        self.choices = [None] * TOTAL_TOWER_ROWS
        self.row_results = [None] * TOTAL_TOWER_ROWS

        # Generate the complete hidden board at the start.
        # Every tile independently uses the configured win chance.
        # This keeps the requested percentage exact over many plays while
        # allowing the classic 3/3/2 tile layouts.        self.tile_is_bomb = []
        for _ in range(TOTAL_TOWER_ROWS):
            # Exact row composition:
            # Easy: 3 tiles = 2 safe + 1 bomb
            # Medium: 3 tiles = 1 safe + 2 bombs
            # Hard: 2 tiles = 1 safe + 1 bomb
            row_bombs = [True] * self.bomb_tiles + [False] * self.safe_tiles
            random.shuffle(row_bombs)
            self.tile_is_bomb.append(row_bombs)

        for col_idx, label in enumerate(self.labels):
            self.add_item(TowerDirectionButton(col_idx, label))

        # Cash out is available after at least one safe floor.
        self.cash_out_btn = discord.ui.Button(
            label="💰 CASH OUT",
            style=discord.ButtonStyle.success,
            row=1
        )
        self.cash_out_btn.callback = self.cash_out_callback
        self.add_item(self.cash_out_btn)


    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This game is not yours!", ephemeral=True)
            return False
        if await game_paused(interaction):
            return False
        return True

    def get_current_mult(self) -> float:
        return calculate_towers_multiplier(self.difficulty, self.current_row)

    def get_next_mult(self) -> float:
        if self.current_row >= TOTAL_TOWER_ROWS:
            return self.get_current_mult()
        return calculate_towers_multiplier(self.difficulty, self.current_row + 1)

    def render_board(self, reveal_all=False) -> str:
        # Classic compact Towers board.
        # On a finished game every tile is shown, but only the bomb the
        # player actually touched is exploded.
        rows = []

        for r in range(TOTAL_TOWER_ROWS - 1, -1, -1):
            tiles = []

            for c in range(self.tiles_per_row):
                is_bomb = self.tile_is_bomb[r][c]
                is_chosen = self.choices[r] == c

                if reveal_all:
                    if is_bomb:
                        # Only the bomb that ended the game explodes.
                        tile = "💥" if (r == self.hit_row and c == self.hit_col) else "💣"
                    else:
                        tile = "☑️"
                elif r < self.current_row:
                    if is_chosen:
                        tile = "💣" if is_bomb else "☑️"
                    else:
                        tile = "⬛"
                elif r == self.current_row:
                    tile = "🔷"
                else:
                    tile = "⬛"

                tiles.append(tile)

            rows.append("".join(tiles))

        return "\n".join(rows)

    def build_embed(self, status="in_progress"):
        curr_m = self.get_current_mult()
        next_m = self.get_next_mult()

        winnings = int(self.amount * curr_m)
        next_click = int(self.amount * next_m)

        board_display = self.render_board(reveal_all=self.game_over)

        # Classic purple Towers card. Keep the multiplier system, but use
        # the simple layout from the reference rather than the revamped UI.
        desc = (
            "**Game Stats**\n"
            f"💎 **Bet:** {format_amount(self.amount)}\n"
            f"✨ **Multiplier:** {curr_m:.2f}x\n"
            f"💎 **Winnings:** {format_amount(winnings)}\n"
            f"⌛ **Next click:** {format_amount(next_click)}\n\n"
            f"{board_display}"
        )

        embed = discord.Embed(
            title=f"Towers | {self.user_name}",
            description=desc,
            colour=discord.Colour.purple()
        )
        embed.set_author(name="Aqua Gems Casino • Towers")
        return embed

    async def process_step(self, interaction: discord.Interaction, col_idx: int):
        if self.game_over:
            return

        row = self.current_row
        self.choices[row] = col_idx

        # Use the pre-generated tile result so the revealed board matches
        # exactly what the player encountered during the game.
        is_bomb = self.tile_is_bomb[row][col_idx]
        self.row_results[row] = is_bomb

        if is_bomb:
            self.game_over = True
            self.hit_row = row
            self.hit_col = col_idx

            for item in self.children:
                item.disabled = True

            user = ensure_user(self.owner_id)
            user["wagered"] += self.amount

            if user["to_wager"] > 0:
                user["to_wager"] = max(0, user["to_wager"] - self.amount)

            add_history(self.owner_id, f"Towers ({self.difficulty})", self.amount, "Loss")
            
            DATA["global_stats"]["bot_game_profit"] += self.amount
            save_data()

            await update_milestone_roles(interaction.user)

            embed = self.build_embed(status="lost")
            await interaction.response.edit_message(embed=embed, view=self)

            await send_log(
                interaction.guild,
                "🏰 Towers Game Lost",
                f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nDifficulty: **{self.difficulty.title()}**\nReached Level: **{self.current_row}**",
                discord.Colour.red()
            )
            self.stop()
        else:
            self.current_row += 1

            if self.current_row >= TOTAL_TOWER_ROWS:
                await self.execute_cashout(interaction)
                return

            embed = self.build_embed(status="in_progress")
            await interaction.response.edit_message(embed=embed, view=self)

    async def cash_out_callback(self, interaction: discord.Interaction):
        if self.current_row == 0:
            await interaction.response.send_message("❌ You must complete at least 1 row to cash out!", ephemeral=True)
            return
        await self.execute_cashout(interaction)

    async def execute_cashout(self, interaction: discord.Interaction):
        self.game_over = True
        mult = self.get_current_mult()
        payout = int(self.amount * mult)
        net_profit = payout - self.amount

        user = ensure_user(self.owner_id)
        user["balance"] += payout
        user["wagered"] += self.amount

        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.amount)

        add_history(self.owner_id, f"Towers ({self.difficulty})", self.amount, "Win")

        DATA["global_stats"]["bot_game_profit"] -= net_profit
        save_data()

        await update_milestone_roles(interaction.user)

        for item in self.children:
            item.disabled = True

        embed = self.build_embed(status="cashed_out")
        
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

        await send_log(
            interaction.guild,
            "🏰 Towers Cashed Out",
            f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nDifficulty: **{self.difficulty.title()}**\nPayout: **{format_amount(payout)}** ({mult:.2f}x)",
            discord.Colour.green()
        )
        self.stop()


@tree.command(name="towers", description="Play Aqua Gems Casino Towers game.")
@game_cooldown()
@app_commands.describe(
    difficulty="Select difficulty mode",
    bet="Bet amount (e.g., 10m, 500m, 1b)"
)
@app_commands.choices(difficulty=[
    app_commands.Choice(name="Easy (3 tiles, 2 safe)", value="easy"),
    app_commands.Choice(name="Medium (3 tiles, 1 safe)", value="medium"),
    app_commands.Choice(name="Hard (2 tiles, 1 safe)", value="hard")
])
async def towers(interaction: discord.Interaction, difficulty: app_commands.Choice[str], bet: str):
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

    view = TowersGameView(interaction.user.id, interaction.user.display_name, parsed, difficulty.value)
    embed = view.build_embed(status="in_progress")

    await interaction.response.send_message(embed=embed, view=view)

