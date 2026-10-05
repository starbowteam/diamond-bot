# -*- coding: utf-8 -*-
"""Казино Diamond: рулетка, блэкджек, монетка. Pillow-рендер через casino_render."""
import os
import time
import random
import asyncio
from datetime import datetime, timezone

import disnake
from disnake import PartialEmoji
from disnake.ui import View, Button, Modal, TextInput
from disnake import ButtonStyle

from core.utils import (
    BASE_DIR, DATA_DIR, CONFIG, logger, log_discord,
    load_json, save_json,
)
from modules.dc import (
    load_shop_catalog,
    get_user_balance, remove_dc, add_dc, get_user_purchases,
)
from modules.others import apply_casino_win, try_insurance
from modules.casino_render import (
    render_roulette_spin, render_roulette_win, render_roulette_lose,
    render_blackjack_table, render_blackjack_result,
    render_coinflip_choice, render_coinflip_win, render_coinflip_lose,
)

try:
    from clan.quests import on_casino_quest_hook, on_casino_win_hook
except Exception:
    on_casino_quest_hook = None
    on_casino_win_hook = None


ACTIONS_DIR = os.path.join(BASE_DIR, "actions")
DAILY_DEAL_FILE = os.path.join(DATA_DIR, "daily_deal.json")
ROULETTE_STATS_FILE = os.path.join(DATA_DIR, "roulette_stats.json")

DAILY_DEAL_REFRESH_HOURS = 5
DAILY_DEAL_DISCOUNT = 30
DAILY_DEALS_PER_CYCLE = 5

CASINO_MIN_BET = 20
CASINO_MAX_BET = 4000

P = "\u3164"


# ============================================================
# УНИВЕРСАЛЬНЫЙ EDIT (чинит InteractionResponded)
# ============================================================
async def _edit_msg(inter, **kwargs):
    try:
        if inter.response.is_done():
            await inter.edit_original_response(**kwargs)
        else:
            await inter.response.edit_message(**kwargs)
    except disnake.InteractionResponded:
        try:
            await inter.edit_original_response(**kwargs)
        except Exception as e:
            logger.warning(f"_edit_msg fallback: {e}")
    except disnake.NotFound:
        logger.warning("_edit_msg: interaction expired")


async def _send_game_screen(inter, buf, fname, view=None):
    file = disnake.File(buf, filename=fname)
    e = disnake.Embed(color=6776679)
    e.set_image(url=f"attachment://{fname}")
    await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=view)


def _suit_code(suit: str) -> int:
    return {"♠️": 0xf2f4, "♥️": 0xf004, "♦️": 0xf219, "♣️": 0xf327}.get(suit, 0xf2f4)


def _suit_color(suit: str):
    return (211, 47, 47) if suit in ("♥️", "♦️") else (26, 26, 30)


def _cards_for_render(cards):
    return [{"rank": c[0], "suit": _suit_code(c[1]), "color": _suit_color(c[1])} for c in cards]


# ============================================================
# ДОСТИЖЕНИЯ
# ============================================================
async def _check_casino_achievements(user_id, bet=0, profit=0):
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        stats = load_roulette_stats()
        await check_and_unlock(user_id, "casino_games", value=stats.get("rolls", 0), bot=bot)
        if bet >= 1000:
            await check_and_unlock(user_id, "casino_bet", value=bet, bot=bot)
        if profit >= 10000:
            await check_and_unlock(user_id, "casino_lucky", value=profit, bot=bot)
    except Exception as e:
        logger.warning(f"casino ach: {e}")


# ============================================================
# ТОВАР ДНЯ
# ============================================================
def load_daily_deal(): return load_json(DAILY_DEAL_FILE, {})
def save_daily_deal(d): save_json(DAILY_DEAL_FILE, d)


def generate_random_deal(discount):
    catalog = load_shop_catalog()
    items = []
    for cat_key, cat_data in catalog.items():
        if cat_key in ("boosts", "casino", "gifts"):
            continue
        for item_key, item_data in cat_data.get("items", {}).items():
            items.append((cat_key, item_key, item_data))
    if not items:
        return None
    cat_key, item_key, item_data = random.choice(items)
    orig = item_data["price"]
    new = max(int(orig * (100 - discount) / 100), 1)
    return {
        "cat_key": cat_key, "item_key": item_key, "item_data": item_data,
        "original_price": orig, "discount": discount, "new_price": new,
        "category_label": catalog[cat_key]["label"],
    }


def _current_deal_slot():
    return int(time.time() // (DAILY_DEAL_REFRESH_HOURS * 3600))


def refresh_daily_deal(force=False):
    slot = _current_deal_slot()
    data = load_daily_deal()
    saved = data.get("item")
    if saved and saved.get("discount") != DAILY_DEAL_DISCOUNT:
        force = True
    if not force and data.get("slot") == slot:
        return saved
    counter = data.get("counter", 0)
    old = data.get("item")
    if counter >= DAILY_DEALS_PER_CYCLE:
        save_daily_deal({"slot": slot, "item": old, "counter": 0, "updated_at": int(time.time())})
        return old
    counter += 1
    deal = generate_random_deal(DAILY_DEAL_DISCOUNT)
    if not deal:
        return None
    save_daily_deal({"slot": slot, "item": deal, "counter": counter, "updated_at": int(time.time())})
    return deal


# ============================================================
# СТАТИСТИКА
# ============================================================
def load_roulette_stats():
    return load_json(ROULETTE_STATS_FILE, {"total_bets": 0, "total_won": 0, "total_lost": 0, "rolls": 0})


def save_roulette_stats(data):
    save_json(ROULETTE_STATS_FILE, data)


# ============================================================
# РУЛЕТКА
# ============================================================
ROULETTE_ROLLS = [
    {"name": "Проигрыш",        "mult": -1.0, "chance": 55.0, "color": 0xed4245},
    {"name": "Малый выигрыш",   "mult":  0.2, "chance": 20.0, "color": 0x95a5a6},
    {"name": "Средний выигрыш", "mult":  0.5, "chance": 12.0, "color": 0x149bd0},
    {"name": "Двойной",         "mult":  1.0, "chance":  8.0, "color": 0x2ecc71},
    {"name": "Тройной",         "mult":  2.0, "chance":  3.0, "color": 0xf7c991},
    {"name": "JACKPOT",         "mult":  4.0, "chance":  1.5, "color": 0xffaa00},
    {"name": "MEGA JACKPOT",    "mult":  9.0, "chance":  0.5, "color": 0xff00aa},
]


def roll_roulette():
    total = sum(r["chance"] for r in ROULETTE_ROLLS)
    r = random.uniform(0, total)
    cur = 0
    for roll in ROULETTE_ROLLS:
        cur += roll["chance"]
        if r <= cur:
            return roll
    return ROULETTE_ROLLS[0]


async def _roulette_play(inter, bet, reason="Ставка в рулетке монет"):
    user_id = inter.author.id
    if bet < CASINO_MIN_BET:
        return await inter.response.send_message(f"❌ Минимум — **{CASINO_MIN_BET} DC**.", ephemeral=True)
    if bet > CASINO_MAX_BET:
        return await inter.response.send_message(f"❌ Максимум — **{CASINO_MAX_BET} DC**.", ephemeral=True)

    balance = await get_user_balance(user_id)
    if bet > balance:
        return await inter.response.send_message(
            f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`", ephemeral=True)

    if not inter.response.is_done():
        await inter.response.defer(ephemeral=True)

    if not await remove_dc(user_id, bet, reason):
        return await inter.edit_original_response(content="❌ Не удалось списать DC.")

    try:
        await _send_game_screen(inter, render_roulette_spin(user_id, balance, bet),
                                f"roulette_spin_{user_id}.png")
    except Exception as e:
        logger.exception(f"roulette spin: {e}")
        await inter.edit_original_response(content="🎰 Крутим барабан...")

    await asyncio.sleep(2.2)

    result = roll_roulette()
    mult = result["mult"]

    if on_casino_quest_hook:
        try: await on_casino_quest_hook(user_id)
        except Exception: pass

    await _check_casino_achievements(user_id, bet=bet)

    if mult > 0:
        payout = bet + int(bet * mult)
        payout, used = apply_casino_win(user_id, payout)
        net = payout - bet
        r_reason = f"Выигрыш в рулетке: {result['name']}"
        if used: r_reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, r_reason, to_clan_pool=True)
        if on_casino_win_hook:
            try: await on_casino_win_hook(user_id, payout, bet)
            except Exception as e: logger.warning(f"casino_win_hook roulette: {e}")

        new_balance = await get_user_balance(user_id)
        try:
            await _send_game_screen(
                inter,
                render_roulette_win(user_id, new_balance, bet, result["name"], mult, net, payout),
                f"roulette_win_{user_id}.png",
                view=RouletteRetryView(bet),
            )
        except Exception as e:
            logger.exception(f"render_roulette_win: {e}")

        if net >= 10000:
            await _check_casino_achievements(user_id, profit=net)

        st = load_roulette_stats()
        st["total_bets"] += bet
        st["total_won"] += net
        st["rolls"] += 1
        save_roulette_stats(st)

        asyncio.create_task(log_discord(
            title=f"🎰 Рулетка: {result['name']}",
            description=(f"> **Юзер:** {inter.author.mention}\n"
                         f"> **Ставка:** `{bet} DC`\n"
                         f"> **Множитель:** `x{1 + mult:.1f}`\n"
                         f"> **Профит:** `+{net} DC`\n"
                         f"> **Баланс:** `{new_balance} DC`"),
            color=result["color"]))
    else:
        refund = try_insurance(user_id, bet)
        if refund > 0:
            await add_dc(user_id, refund, "Страховка ставки (рулетка)")

        new_balance = await get_user_balance(user_id)
        try:
            await _send_game_screen(
                inter,
                render_roulette_lose(user_id, new_balance, bet, refund, result["name"]),
                f"roulette_lose_{user_id}.png",
                view=RouletteRetryView(bet),
            )
        except Exception as e:
            logger.exception(f"render_roulette_lose: {e}")

        st = load_roulette_stats()
        st["total_bets"] += bet
        st["total_lost"] += (bet - refund)
        st["rolls"] += 1
        save_roulette_stats(st)

        asyncio.create_task(log_discord(
            title="🎰 Рулетка: проигрыш",
            description=(f"> **Юзер:** {inter.author.mention}\n"
                         f"> **Ставка:** `{bet} DC`\n"
                         f"> **Страховка:** `+{refund} DC`\n"
                         f"> **Баланс:** `{new_balance} DC`"),
            color=0xed4245))


class RouletteModal(Modal):
    def __init__(self):
        super().__init__(title="🎰 Рулетка монет", components=[
            TextInput(label=f"Ставка ({CASINO_MIN_BET}-{CASINO_MAX_BET} DC)",
                      placeholder=f"От {CASINO_MIN_BET} до {CASINO_MAX_BET}",
                      custom_id="bet", min_length=1, max_length=10)])

    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit():
            return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _roulette_play(inter, int(s), reason="Ставка в рулетке монет")


class RouletteRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        for label, cid, emoji_data, style, cb in [
            ("Играть ещё", "roulette_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay),
            ("Повтор ставки", "roulette_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat),
            ("Двойная ставка", "roulette_double", ("flas", 1551289202279325756), ButtonStyle.danger, self.double),
        ]:
            b = Button(label=label, style=style, custom_id=cid,
                       emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0)
            b.callback = cb
            self.add_item(b)

    async def replay(self, inter):
        await inter.response.send_modal(RouletteModal())

    async def repeat(self, inter):
        await _roulette_play(inter, self.last_bet, reason="Повтор ставки в рулетке")

    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET:
            return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _roulette_play(inter, nb, reason="Двойная ставка в рулетке")


# ============================================================
# БЛЭКДЖЕК
# ============================================================
BLACKJACK_MIN_BET        = CASINO_MIN_BET
BLACKJACK_MAX_BET        = CASINO_MAX_BET
BLACKJACK_BLACKJACK_MULT = 2.5
BLACKJACK_WIN_MULT       = 2.0
BLACKJACK_DEALER_STAND   = 17

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["♠️", "♥️", "♦️", "♣️"]


def _new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(d)
    return d


def _hand_value(hand):
    total = 0; aces = 0
    for r, s in hand:
        if r == "A": aces += 1; total += 11
        elif r in ("J", "Q", "K"): total += 10
        else: total += int(r)
    while total > 21 and aces > 0:
        total -= 10; aces -= 1
    return total


def _dealer_play(game):
    while _hand_value(game["dealer"]) < BLACKJACK_DEALER_STAND:
        game["dealer"].append(game["deck"].pop())


async def _bj_finalize(inter, game, outcome):
    """Считает выплату, рендерит финал, редактирует сообщение."""
    user_id = game["user_id"]
    bet = game["bet"]
    total_bet = bet * 2 if game.get("doubled") else bet

    if outcome == "blackjack":
        payout = int(total_bet * BLACKJACK_BLACKJACK_MULT); reason = "Блэкджек (x2.5)"
    elif outcome == "win":
        payout = int(total_bet * BLACKJACK_WIN_MULT); reason = "Победа в блэкджеке (x2)"
    elif outcome == "push":
        payout = total_bet; reason = "Ничья в блэкджеке (возврат)"
    else:
        payout = 0; reason = "Проигрыш в блэкджеке"

    if payout > 0:
        payout, used = apply_casino_win(user_id, payout)
        if used: reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, reason, to_clan_pool=True)
        if on_casino_win_hook:
            try: await on_casino_win_hook(user_id, payout, total_bet)
            except Exception as e: logger.warning(f"casino_win_hook bj: {e}")
        if outcome == "blackjack":
            try:
                from clan.achievements import unlock_achievement
                from core.bot import bot
                await unlock_achievement(user_id, "casino_bj21", bot=bot)
            except Exception as e:
                logger.warning(f"bj21 ach: {e}")
        net = payout - total_bet
        if net >= 10000:
            await _check_casino_achievements(user_id, profit=net)
    else:
        refund = try_insurance(user_id, total_bet)
        if refund > 0:
            await add_dc(user_id, refund, "Страховка ставки (блэкджек)")
            payout = refund

    new_balance = await get_user_balance(user_id)
    net = payout - total_bet

    asyncio.create_task(log_discord(
        title=f"🃏 Блэкджек: {outcome}",
        description=(f"> **Юзер:** <@{user_id}>\n"
                     f"> **Ставка:** `{total_bet} DC`\n"
                     f"> **Выплата:** `{payout} DC`\n"
                     f"> **Профит:** `{'+' if net >= 0 else ''}{net} DC`\n"
                     f"> **Баланс:** `{new_balance} DC`"),
        color=0x2ecc71 if payout > 0 else 0xed4245))

    dealer_cards = _cards_for_render(game["dealer"])
    player_cards = _cards_for_render(game["player"])

    try:
        buf = render_blackjack_result(
            user_id, new_balance, bet, total_bet, payout, net,
            dealer_cards, player_cards,
            _hand_value(game["dealer"]), _hand_value(game["player"]),
            outcome,
        )
        file = disnake.File(buf, filename=f"bj_res_{user_id}.png")
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{file.filename}")
        await _edit_msg(inter, content=None, embed=e, file=file, attachments=[],
                        view=BlackjackRetryView(bet))
    except Exception as e:
        logger.exception(f"render_blackjack_result: {e}")


async def _blackjack_play(inter, bet, reason="Ставка в блэкджеке"):
    user_id = inter.author.id
    if bet < BLACKJACK_MIN_BET:
        return await inter.response.send_message(f"❌ Минимум — **{BLACKJACK_MIN_BET} DC**.", ephemeral=True)
    if bet > BLACKJACK_MAX_BET:
        return await inter.response.send_message(f"❌ Максимум — **{BLACKJACK_MAX_BET} DC**.", ephemeral=True)

    balance = await get_user_balance(user_id)
    if bet > balance:
        return await inter.response.send_message(
            f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`", ephemeral=True)

    if not inter.response.is_done():
        await inter.response.defer(ephemeral=True)

    if not await remove_dc(user_id, bet, reason):
        return await inter.edit_original_response(content="❌ Не удалось списать DC.")

    deck = _new_deck()
    game = {
        "user_id": user_id, "bet": bet, "deck": deck,
        "player": [deck.pop(), deck.pop()],
        "dealer": [deck.pop(), deck.pop()],
        "doubled": False, "finished": False,
    }

    if on_casino_quest_hook:
        try: await on_casino_quest_hook(user_id)
        except Exception: pass

    await _check_casino_achievements(user_id, bet=bet)

    dealer_first = game["dealer"][0]
    dealer_cards = [
        {"rank": dealer_first[0], "suit": _suit_code(dealer_first[1]),
         "color": _suit_color(dealer_first[1])},
        {"back": True},
    ]
    player_cards = _cards_for_render(game["player"])

    try:
        buf = render_blackjack_table(user_id, balance - bet, bet,
                                     dealer_cards, player_cards,
                                     _hand_value(game["player"]), dealer_first)
        await _send_game_screen(inter, buf, f"bj_{user_id}.png", view=BlackjackView(game))
    except Exception as e:
        logger.exception(f"render_blackjack_table: {e}")
        await inter.edit_original_response(content="🃏 Раздача карт...")

    if _hand_value(game["player"]) == 21:
        _dealer_play(game)
        game["finished"] = True
        dealer_val = _hand_value(game["dealer"])
        outcome = "push" if (dealer_val == 21 and len(game["dealer"]) == 2) else "blackjack"
        await _bj_finalize(inter, game, outcome)


class BlackjackBetModal(Modal):
    def __init__(self):
        super().__init__(title="Блэкджек — ставка", components=[
            TextInput(label=f"Ставка ({BLACKJACK_MIN_BET}-{BLACKJACK_MAX_BET} DC)",
                      placeholder=f"От {BLACKJACK_MIN_BET} до {BLACKJACK_MAX_BET}",
                      custom_id="bet", min_length=1, max_length=10)])

    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit():
            return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _blackjack_play(inter, int(s), reason="Ставка в блэкджеке")


class BlackjackView(View):
    def __init__(self, game):
        super().__init__(timeout=300)
        self.game = game

        b1 = Button(label=f"{P}{P}Взять{P}{P}", style=ButtonStyle.gray,
                    custom_id="bj_hit", emoji=PartialEmoji(name="adde", id=1551288309240696954), row=0)
        b1.callback = self.hit
        self.add_item(b1)

        b2 = Button(label=f"{P}{P}Хватит{P}{P}", style=ButtonStyle.gray,
                    custom_id="bj_stand", emoji=PartialEmoji(name="PAM", id=1551288362822795434), row=0)
        b2.callback = self.stand
        self.add_item(b2)

        b3 = Button(label=f"{P}{P}Удвоить{P}{P}", style=ButtonStyle.danger,
                    custom_id="bj_double", emoji=PartialEmoji(name="flas", id=1551289202279325756), row=0)
        b3.callback = self.double
        self.add_item(b3)

    async def _check(self, inter):
        if inter.author.id != self.game["user_id"]:
            await inter.response.send_message("⛔ Не ваша игра.", ephemeral=True); return False
        if self.game["finished"]:
            await inter.response.send_message("⛔ Завершена.", ephemeral=True); return False
        return True

    async def _redraw(self, inter):
        dealer_first = self.game["dealer"][0]
        dealer_cards = [
            {"rank": dealer_first[0], "suit": _suit_code(dealer_first[1]),
             "color": _suit_color(dealer_first[1])},
            {"back": True},
        ]
        player_cards = _cards_for_render(self.game["player"])
        try:
            buf = render_blackjack_table(self.game["user_id"], 0, self.game["bet"],
                                         dealer_cards, player_cards,
                                         _hand_value(self.game["player"]), dealer_first)
            file = disnake.File(buf, filename=f"bj_{self.game['user_id']}.png")
            e = disnake.Embed(color=6776679)
            e.set_image(url=f"attachment://{file.filename}")
            await _edit_msg(inter, content=None, embed=e, file=file, attachments=[], view=self)
        except Exception as e:
            logger.exception(f"bj redraw: {e}")

    async def hit(self, inter):
        if not await self._check(inter): return
        self.game["player"].append(self.game["deck"].pop())
        v = _hand_value(self.game["player"])
        if v > 21:
            self.game["finished"] = True
            await _bj_finalize(inter, self.game, "bust")
        elif v == 21:
            await self._stand_logic(inter)
        else:
            await self._redraw(inter)

    async def stand(self, inter):
        if not await self._check(inter): return
        await self._stand_logic(inter)

    async def _stand_logic(self, inter):
        _dealer_play(self.game)
        self.game["finished"] = True
        pv = _hand_value(self.game["player"])
        dv = _hand_value(self.game["dealer"])
        if dv > 21 or pv > dv: outcome = "win"
        elif pv == dv: outcome = "push"
        else: outcome = "lose"
        await _bj_finalize(inter, self.game, outcome)

    async def double(self, inter):
        if not await self._check(inter): return
        if self.game.get("doubled"):
            return await inter.response.send_message("⛔ Уже удвоено.", ephemeral=True)
        if len(self.game["player"]) != 2:
            return await inter.response.send_message("⛔ Только на первых двух.", ephemeral=True)

        uid = self.game["user_id"]
        bet = self.game["bet"]
        if bet * 2 > CASINO_MAX_BET:
            return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET}.", ephemeral=True)
        if (await get_user_balance(uid)) < bet:
            return await inter.response.send_message(f"❌ Нужно ещё `{bet} DC`.", ephemeral=True)
        if not await remove_dc(uid, bet, "Удвоение в блэкджеке"):
            return await inter.response.send_message("❌ Ошибка списания.", ephemeral=True)
        self.game["doubled"] = True
        self.game["player"].append(self.game["deck"].pop())
        await self._stand_logic(inter)


class BlackjackRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        for label, cid, emoji_data, style, cb in [
            ("Играть ещё", "bj_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay),
            ("Повтор ставки", "bj_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat),
            ("Двойная ставка", "bj_double_next", ("flas", 1551289202279325756), ButtonStyle.danger, self.double),
        ]:
            b = Button(label=label, style=style, custom_id=cid,
                       emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0)
            b.callback = cb
            self.add_item(b)

    async def replay(self, inter): await inter.response.send_modal(BlackjackBetModal())
    async def repeat(self, inter): await _blackjack_play(inter, self.last_bet, reason="Повтор в блэкджеке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET:
            return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _blackjack_play(inter, nb, reason="Двойная в блэкджеке")


# ============================================================
# МОНЕТКА
# ============================================================
COINFLIP_MIN_BET = CASINO_MIN_BET
COINFLIP_MAX_BET = CASINO_MAX_BET
COINFLIP_WIN_MULT = 1.9


async def _coinflip_play(inter, bet, reason="Ставка в монетке"):
    user_id = inter.author.id
    if bet < COINFLIP_MIN_BET:
        return await inter.response.send_message(f"❌ Минимум — **{COINFLIP_MIN_BET} DC**.", ephemeral=True)
    if bet > COINFLIP_MAX_BET:
        return await inter.response.send_message(f"❌ Максимум — **{COINFLIP_MAX_BET} DC**.", ephemeral=True)

    balance = await get_user_balance(user_id)
    if bet > balance:
        return await inter.response.send_message(
            f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`", ephemeral=True)

    if not inter.response.is_done():
        await inter.response.defer(ephemeral=True)

    if not await remove_dc(user_id, bet, reason):
        return await inter.edit_original_response(content="❌ Не удалось списать DC.")

    await _check_casino_achievements(user_id, bet=bet)

    try:
        await _send_game_screen(inter, render_coinflip_choice(user_id, balance, bet),
                                f"coin_choice_{user_id}.png", view=CoinflipChoiceView(bet))
    except Exception as e:
        logger.exception(f"render_coinflip_choice: {e}")


class CoinflipBetModal(Modal):
    def __init__(self):
        super().__init__(title="Монетка — ставка", components=[
            TextInput(label=f"Ставка ({COINFLIP_MIN_BET}-{COINFLIP_MAX_BET} DC)",
                      placeholder=f"От {COINFLIP_MIN_BET} до {COINFLIP_MAX_BET}",
                      custom_id="bet", min_length=1, max_length=10)])

    async def callback(self, inter):
        s = inter.text_values["bet"].strip()
        if not s.isdigit():
            return await inter.response.send_message("❌ Целое число.", ephemeral=True)
        await _coinflip_play(inter, int(s), reason="Ставка в монетке")


class CoinflipChoiceView(View):
    def __init__(self, bet):
        super().__init__(timeout=60)
        self.bet = bet

        b1 = Button(label=f"{P}{P}{P}{P}Орёл{P}{P}{P}{P}", style=ButtonStyle.gray,
                    custom_id="coin_heads", emoji=PartialEmoji(name="image", id=1551296060729725019), row=0)
        b1.callback = self.heads
        self.add_item(b1)

        b2 = Button(label=f"{P}{P}{P}{P}Решка{P}{P}{P}{P}", style=ButtonStyle.gray,
                    custom_id="coin_tails", emoji=PartialEmoji(name="2313", id=1551296094468575366), row=0)
        b2.callback = self.tails
        self.add_item(b2)

    async def _play(self, inter, user_choice):
        result_side = random.choice(["heads", "tails"])
        won = (result_side == user_choice)
        user_id = inter.author.id
        bet = self.bet

        payout = 0
        refund = 0

        if on_casino_quest_hook:
            try: await on_casino_quest_hook(user_id)
            except Exception: pass

        if won:
            payout = int(bet * COINFLIP_WIN_MULT)
            payout, used = apply_casino_win(user_id, payout)
            reason = f"Монетка ({result_side})"
            if used: reason += f" ({', '.join(used)})"
            await add_dc(user_id, payout, reason, to_clan_pool=True)
            if on_casino_win_hook:
                try: await on_casino_win_hook(user_id, payout, bet)
                except Exception as e: logger.warning(f"casino_win_hook coin: {e}")
            net = payout - bet
            if net >= 10000:
                await _check_casino_achievements(user_id, profit=net)
        else:
            refund = try_insurance(user_id, bet)
            if refund > 0:
                await add_dc(user_id, refund, "Страховка (монетка)")
            net = -bet + refund

        new_balance = await get_user_balance(user_id)
        side_ru = "Орёл" if result_side == "heads" else "Решка"
        choice_ru = "Орёл" if user_choice == "heads" else "Решка"

        try:
            if won:
                buf = render_coinflip_win(user_id, new_balance, bet, payout, payout - bet,
                                          side_ru, choice_ru)
            else:
                buf = render_coinflip_lose(user_id, new_balance, bet, refund,
                                           side_ru, choice_ru)
            file = disnake.File(buf, filename=f"coin_res_{user_id}.png")
            e = disnake.Embed(color=6776679)
            e.set_image(url=f"attachment://{file.filename}")
            await _edit_msg(inter, content=None, embed=e, file=file, attachments=[],
                            view=CoinflipRetryView(bet))
        except Exception as e:
            logger.exception(f"coin result: {e}")

        asyncio.create_task(log_discord(
            title=f"🪙 Монетка: {'победа' if won else 'проигрыш'}",
            description=(f"> **Юзер:** <@{user_id}>\n"
                         f"> **Ставка:** `{bet} DC`\n"
                         f"> **Выбор:** `{user_choice}` → `{result_side}`\n"
                         f"> **Выплата:** `{payout} DC`\n"
                         f"> **Страховка:** `{refund} DC`\n"
                         f"> **Баланс:** `{new_balance} DC`"),
            color=0x2ecc71 if won else 0xed4245))

    async def heads(self, inter): await self._play(inter, "heads")
    async def tails(self, inter): await self._play(inter, "tails")


class CoinflipRetryView(View):
    def __init__(self, last_bet):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        for label, cid, emoji_data, style, cb in [
            ("Играть ещё", "coin_retry", ("image", 1555994370933653544), ButtonStyle.gray, self.replay),
            ("Повтор ставки", "coin_repeat", ("povtor", 1555993533629071360), ButtonStyle.gray, self.repeat),
            ("Двойная ставка", "coin_double", ("flas", 1551289202279325756), ButtonStyle.danger, self.double),
        ]:
            b = Button(label=label, style=style, custom_id=cid,
                       emoji=PartialEmoji(name=emoji_data[0], id=emoji_data[1]), row=0)
            b.callback = cb
            self.add_item(b)

    async def replay(self, inter): await inter.response.send_modal(CoinflipBetModal())
    async def repeat(self, inter): await _coinflip_play(inter, self.last_bet, reason="Повтор в монетке")
    async def double(self, inter):
        nb = self.last_bet * 2
        if nb > CASINO_MAX_BET:
            return await inter.response.send_message(f"❌ Лимит {CASINO_MAX_BET} DC.", ephemeral=True)
        await _coinflip_play(inter, nb, reason="Двойная в монетке")
