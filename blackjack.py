"""Aqua Gems Casino — Animated Blackjack."""
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


def card():
    return random.randint(2, 11)


def blackjack_total(cards):
    total = sum(cards)
    aces = cards.count(11)

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


class AnimatedBlackjackView(discord.ui.View):
    def __init__(self, owner_id, amount):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.amount = amount

        self.player = []
        self.dealer = []
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ This blackjack game isn't yours.", ephemeral=True)
            return False

        if await game_paused(interaction):
            return False

        return True

    def build_embed(self, title="🃏 Blackjack Table", description="", reveal_dealer=False, status=None, status_colour=None):
        embed = normal_embed(title, description, status_colour or discord.Colour.blurple())

        p_cards = " ".join(f"[{x}]" for x in self.player) if self.player else "—"
        embed.add_field(
            name="👤 Your Hand",
            value=f"Cards: {p_cards}\nTotal Value: **{blackjack_total(self.player)}**",
            inline=True
        )

        if reveal_dealer or self.finished:
            d_cards = " ".join(f"[{x}]" for x in self.dealer) if self.dealer else "—"
            embed.add_field(
                name="🤖 Dealer Hand",
                value=f"Cards: {d_cards}\nTotal Value: **{blackjack_total(self.dealer)}**",
                inline=True
            )
        elif self.dealer:
            embed.add_field(
                name="🤖 Dealer Hand",
                value=f"Cards: [{self.dealer[0]}] [❓]\nTotal Value: **?**",
                inline=True
            )
        else:
            embed.add_field(name="🤖 Dealer Hand", value="Cards: —\nTotal Value: **?**", inline=True)

        embed.add_field(name="💰 Wager", value=f"{format_amount(self.amount)}", inline=False)

        if status:
            embed.add_field(name="🎰 Status", value=status, inline=False)

        embed.set_footer(text="Aqua Gems")
        return embed

    @discord.ui.button(label="Hit", emoji="🃏", style=discord.ButtonStyle.primary)
    async def hit(self, interaction, button):
        await interaction.response.edit_message(
            embed=self.build_embed(description="🎴 Drawing a card..."),
            view=None
        )
        await asyncio.sleep(0.8)

        self.player.append(card())

        if blackjack_total(self.player) > 21:
            await self.finish(interaction, "loss")
            return

        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Stand", emoji="✋", style=discord.ButtonStyle.success)
    async def stand(self, interaction, button):
        await self.finish(interaction, None)

    @discord.ui.button(label="Double Down", emoji="💵", style=discord.ButtonStyle.secondary)
    async def double_down(self, interaction, button):
        if len(self.player) != 2:
            await interaction.response.send_message("❌ You can only double down before hitting.", ephemeral=True)
            return

        user = ensure_user(self.owner_id)
        if user["balance"] < self.amount:
            await interaction.response.send_message("❌ Insufficient balance to double down.", ephemeral=True)
            return

        user["balance"] -= self.amount
        self.amount *= 2

        await interaction.response.edit_message(
            embed=self.build_embed(description="💵 Doubling down — drawing your final card..."),
            view=None
        )
        await asyncio.sleep(0.8)

        self.player.append(card())

        if blackjack_total(self.player) > 21:
            await self.finish(interaction, "loss")
            return

        await self.finish(interaction, None)

    async def finish(self, interaction, forced_result):
        self.finished = True

        if not interaction.response.is_done():
            await interaction.response.edit_message(
                embed=self.build_embed(description="🎴 Dealer is revealing their hidden card...", reveal_dealer=True),
                view=None
            )
        else:
            await interaction.edit_original_response(
                embed=self.build_embed(description="🎴 Dealer is revealing their hidden card...", reveal_dealer=True),
                view=None
            )

        await asyncio.sleep(1.0)

        while blackjack_total(self.dealer) < 18 and forced_result != "loss":
            self.dealer.append(card())
            await interaction.edit_original_response(
                embed=self.build_embed(description="🎴 Dealer hits another card...", reveal_dealer=True),
                view=None
            )
            await asyncio.sleep(1.0)

        player_total = blackjack_total(self.player)
        dealer_total = blackjack_total(self.dealer)
        user = ensure_user(self.owner_id)

        if forced_result == "loss" or player_total > 21:
            result = "Loss"
        elif dealer_total > 21 or player_total > dealer_total:
            result = "Win"
        elif player_total == dealer_total:
            result = "Push"
        else:
            result = "Loss"

        if result == "Win":
            payout = int(self.amount * 1.95)
            user["balance"] += payout
            DATA["global_stats"]["bot_game_profit"] -= self.amount
            status = f"🏆 **You Win!** ({player_total} vs {dealer_total})\nPayout: **{format_amount(payout)}**"
            colour = discord.Colour.green()
        elif result == "Loss":
            DATA["global_stats"]["bot_game_profit"] += self.amount
            status = f"💀 **You Lost!** ({player_total} vs {dealer_total})\nLost: **{format_amount(self.amount)}**"
            colour = discord.Colour.red()
        else:
            user["balance"] += self.amount
            status = f"🟡 **Push!** ({player_total} vs {dealer_total})\nWager returned."
            colour = discord.Colour.orange()

        user["wagered"] += self.amount

        if user["to_wager"] > 0:
            user["to_wager"] = max(0, user["to_wager"] - self.amount)

        add_history(self.owner_id, "Blackjack", self.amount, result)
        save_data()

        await update_milestone_roles(interaction.user)

        final_embed = self.build_embed(reveal_dealer=True, status=status, status_colour=colour)

        await interaction.edit_original_response(embed=final_embed, view=None)

        await send_log(
            interaction.guild,
            "🃏 Blackjack Finished",
            f"Player: {interaction.user.mention}\nAmount: **{format_amount(self.amount)}**\nResult: **{result}**",
            colour
        )
        self.stop()


@tree.command(name="blackjack", description="Play animated Blackjack.")
@game_cooldown()
@app_commands.describe(amount="Example: 10m or 1b")
async def blackjack(interaction, amount: str):
    if not await verification_check(interaction):
        return

    if await game_paused(interaction):
        return

    parsed = parse_amount(amount)
    if parsed is None or parsed < MIN_GAME_AMOUNT:
        await interaction.response.send_message("❌ Minimum amount is **10M**.", ephemeral=True)
        return

    user = ensure_user(interaction.user.id)
    if user["balance"] < parsed:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return

    user["balance"] -= parsed
    save_data()

    view = AnimatedBlackjackView(interaction.user.id, parsed)

    await interaction.response.send_message(
        embed=normal_embed("🃏 Blackjack Table", "🎰 Shuffling & dealing...", discord.Colour.blurple())
    )

    try:
        await asyncio.sleep(3)

        view.player = [card(), card()]
        view.dealer = [card(), card()]

        if blackjack_total(view.player) == 21:
            await view.finish(interaction, None)
            return

        await interaction.edit_original_response(
            embed=view.build_embed(description="Choose your move!"),
            view=view
        )
    except Exception as e:
        print(f"Blackjack deal error: {e}")
        user["balance"] += parsed
        save_data()
        try:
            await interaction.edit_original_response(
                embed=normal_embed(
                    "❌ Blackjack Error",
                    "Something went wrong starting the game. Your balance was refunded.",
                    discord.Colour.red()
                ),
                view=None
            )
        except Exception:
            pass

