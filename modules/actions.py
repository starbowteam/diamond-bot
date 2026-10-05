# -*- coding: utf-8 -*-
"""
Казино Diamond: рулетка, блэкджек, монетка.
Всё рисуется Pillow-ом (см. modules/casino_render.py), эмбеды убраны.
Плюс — товар дня (refresh_daily_deal) для витрины.
"""
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
    get_user_balance, remove_dc,
    add_dc, get_user_purchases,
)

from modules.others import (
    apply_casino_win, try_insurance,
)

# 👇 Pillow-рендеры казино
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


# ============================================================
# КОНСТАНТЫ
# ============================================================
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
# ХЕЛПЕРЫ ДЛЯ ОТПРАВКИ PILLOW-КАРТИНОК
# ============================================================
async def _send_game_screen(inter, buf, fname: str, view=None):
    """
    Универсальная отправка Pillow-картинки в текущее сообщение.
    Работает и при response, и после defer — через edit_original_response.
    """
    file = disnake.File(buf, filename=fname)
    embed = disnake.Embed(color=6776679)
    embed.set_image(url=f"attachment://{fname}")
    kwargs = dict(content=None, embed=embed, file=file, attachments=[], view=view)
    try:
        if inter.response.is_done():
            await inter.edit_original_response(**kwargs)
        else:
            await inter.response.edit_message(**kwargs)
    except disnake.InteractionResponded:
        await inter.edit_original_response(**kwargs)


def _suit_code(suit: str) -> int:
    """Юникод FA-иконки для масти."""
    return {
        "♠️": 0xf2f4,
        "♥️": 0xf004,
        "♦️": 0xf219,
        "♣️": 0xf327,
    }.get(suit, 0xf2f4)


def _suit_color(suit: str):
    return (211, 47, 47) if suit in ("♥️", "♦️") else (26, 26, 30)


def _cards_for_render(cards: list) -> list:
    """Превращает список карт в формат рендера."""
    return [
        {"rank": c[0], "suit": _suit_code(c[1]), "color": _suit_color(c[1])}
        for c in cards
    ]


# ============================================================
# ДОСТИЖЕНИЯ КАЗИНО
# ============================================================
async def _check_casino_achievements(user_id: int, bet: int = 0, profit: int = 0):
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        stats = load_roulette_stats()
        games_count = stats.get("rolls", 0)
        await check_and_unlock(user_id, "casino_games", value=games_count, bot=bot)
        if bet >= 1000:
            await check_and_unlock(user_id, "casino_bet", value=bet, bot=bot)
        if profit >= 10000:
            await check_and_unlock(user_id, "casino_lucky", value=profit, bot=bot)
    except Exception as e:
        logger.warning(f"casino ach: {e}")


# ============================================================
# ТОВАР ДНЯ
# ============================================================
def load_daily_deal() -> dict:
    return load_json(DAILY_DEAL_FILE, {})


def save_daily_deal(data: dict):
    save_json(DAILY_DEAL_FILE, data)


def generate_random_deal(discount: int):
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
    original_price = item_data["price"]
    new_price = max(int(original_price * (100 - discount) / 100), 1)

    return {
        "cat_key": cat_key,
        "item_key": item_key,
        "item_data": item_data,
        "original_price": original_price,
        "discount": discount,
        "new_price": new_price,
        "category_label": catalog[cat_key]["label"],
    }


def _current_deal_slot() -> int:
    return int(time.time() // (DAILY_DEAL_REFRESH_HOURS * 3600))


def refresh_daily_deal(force: bool = False):
    current_slot = _current_deal_slot()
    data = load_daily_deal()
    saved_item = data.get("item")

    if saved_item and saved_item.get("discount") != DAILY_DEAL_DISCOUNT:
        force = True

    if not force and data.get("slot") == current_slot:
        return saved_item

    counter = data.get("counter", 0)
    old_item = data.get("item")

    if counter >= DAILY_DEALS_PER_CYCLE:
        save_daily_deal({
            "slot": current_slot,
            "item": old_item,
            "counter": 0,
            "updated_at": int(time.time()),
        })
        return old_item

    counter += 1
    deal = generate_random_deal(discount=DAILY_DEAL_DISCOUNT)
    if not deal:
        return None

    save_daily_deal({
        "slot": current_slot,
        "item": deal,
        "counter": counter,
        "updated_at": int(time.time()),
    })
    return deal


# ============================================================
# СТАТИСТИКА РУЛЕТКИ
# ============================================================
def load_roulette_stats() -> dict:
    return load_json(ROULETTE_STATS_FILE, {
        "total_bets": 0, "total_won": 0, "total_lost": 0, "rolls": 0,
    })


def save_roulette_stats(data: dict):
    save_json(ROULETTE_STATS_FILE, data)


# ============================================================
# РУЛЕТКА
# ============================================================
ROULETTE_ROLLS = [
    {"name": "Проигрыш",        "mult": -1.0, "chance": 55.0, "color": 0xed4245, "emoji": "🎲", "desc": "Ты потерял ставку"},
    {"name": "Малый выигрыш",   "mult":  0.2, "chance": 20.0, "color": 0x95a5a6, "emoji": "🔹", "desc": "+20% от ставки"},
    {"name": "Средний выигрыш", "mult":  0.5, "chance": 12.0, "color": 0x149bd0, "emoji": "🔸", "desc": "+50% от ставки"},
    {"name": "Двойной",         "mult":  1.0, "chance":  8.0, "color": 0x2ecc71, "emoji": "💎", "desc": "х2 — удвоение ставки"},
    {"name": "Тройной",         "mult":  2.0, "chance":  3.0, "color": 0xf7c991, "emoji": "👑", "desc": "х3 — тройная ставка"},
    {"name": "JACKPOT",         "mult":  4.0, "chance":  1.5, "color": 0xffaa00, "emoji": "🎰", "desc": "х5 — джекпот!"},
    {"name": "MEGA JACKPOT",    "mult":  9.0, "chance":  0.5, "color": 0xff00aa, "emoji": "⭐", "desc": "х10 — мега-джекпот!!!"},
]


def roll_roulette() -> dict:
    total = sum(r["chance"] for r in ROULETTE_ROLLS)
    r = random.uniform(0, total)
    cur_v = 0
    for roll in ROULETTE_ROLLS:
        cur_v += roll["chance"]
        if r <= cur_v:
            return roll
    return ROULETTE_ROLLS[0]


async def _roulette_play(inter, bet: int, reason: str = "Ставка в рулетке монет"):
    user_id = inter.author.id

    if bet < CASINO_MIN_BET:
        return await inter.response.send_message(
            f"❌ Минимальная ставка — **{CASINO_MIN_BET} DC**.", ephemeral=True
        )
    if bet > CASINO_MAX_BET:
        return await inter.response.send_message(
            f"❌ Максимальная ставка — **{CASINO_MAX_BET} DC**.", ephemeral=True
        )

    balance = await get_user_balance(user_id)
    if bet > balance:
        return await inter.response.send_message(
            f"❌ Недостаточно DC.\n> **Твой баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`",
            ephemeral=True,
        )

    if not inter.response.is_done():
        await inter.response.defer(ephemeral=True)

    success = await remove_dc(user_id, bet, reason)
    if not success:
        return await inter.edit_original_response(content="❌ Не удалось списать DC. Попробуй позже.")

    # Спин
    try:
        buf = render_roulette_spin(user_id, balance, bet)
        await _send_game_screen(inter, buf, f"roulette_spin_{user_id}.png")
    except Exception as e:
        logger.exception(f"render_roulette_spin: {e}")
        await inter.edit_original_response(content="🎰 Крутим барабан...")

    await asyncio.sleep(2.2)

    result = roll_roulette()
    mult = result["mult"]

    if on_casino_quest_hook:
        try:
            await on_casino_quest_hook(user_id)
        except Exception as e:
            logger.warning(f"casino_quest_hook roulette: {e}")

    await _check_casino_achievements(user_id, bet=bet)

    if mult > 0:
        payout = bet + int(bet * mult)
        payout, used = apply_casino_win(user_id, payout)
        net = payout - bet
        r_reason = f"Выигрыш в рулетке: {result['name']}"
        if used:
            r_reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, r_reason, to_clan_pool=True)
        if on_casino_win_hook:
            try:
                await on_casino_win_hook(user_id, payout, bet)
            except Exception as e:
                logger.warning(f"casino_win_hook roulette: {e}")

        new_balance = await get_user_balance(user_id)
        view = RouletteRetryView(bet)

        try:
            buf = render_roulette_win(user_id, new_balance, bet, result["name"], mult, net, payout)
            await _send_game_screen(inter, buf, f"roulette_win_{user_id}.png", view=view)
        except Exception as e:
            logger.exception(f"render_roulette_win: {e}")

        if net >= 10000:
            await _check_casino_achievements(user_id, profit=net)

        stats = load_roulette_stats()
        stats["total_bets"] = stats.get("total_bets", 0) + bet
        stats["total_won"] = stats.get("total_won", 0) + net
        stats["rolls"] = stats.get("rolls", 0) + 1
        save_roulette_stats(stats)

        asyncio.create_task(log_discord(
            title=f"🎰 Рулетка: {result['name']}",
            description=(
                f"> **Пользователь:** {inter.author.mention}\n"
                f"> **Ставка:** `{bet} DC`\n"
                f"> **Результат:** `x{1 + mult:.1f}`\n"
                f"> **Чистый профит:** `+{net} DC`\n"
                f"> **Новый баланс:** `{new_balance} DC`"
            ),
            color=result["color"],
        ))
    else:
        refund = try_insurance(user_id, bet)
        if refund > 0:
            await add_dc(user_id, refund, "Страховка ставки (рулетка)")

        new_balance = await get_user_balance(user_id)
        view = RouletteRetryView(bet)

        try:
            buf = render_roulette_lose(user_id, new_balance, bet, refund, result["name"])
            await _send_game_screen(inter, buf, f"roulette_lose_{user_id}.png", view=view)
        except Exception as e:
            logger.exception(f"render_roulette_lose: {e}")

        stats = load_roulette_stats()
        stats["total_bets"] = stats.get("total_bets", 0) + bet
        stats["total_lost"] = stats.get("total_lost", 0) + (bet - refund)
        stats["rolls"] = stats.get("rolls", 0) + 1
        save_roulette_stats(stats)

        asyncio.create_task(log_discord(
            title="🎰 Рулетка: проигрыш",
            description=(
                f"> **Пользователь:** {inter.author.mention}\n"
                f"> **Ставка:** `{bet} DC`\n"
                f"> **Результат:** `x0`\n"
                f"> **Страховка:** `+{refund} DC`\n"
                f"> **Новый баланс:** `{new_balance} DC`"
            ),
            color=0xed4245,
        ))


class RouletteModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label=f"Ставка ({CASINO_MIN_BET}-{CASINO_MAX_BET} DC)",
                placeholder=f"От {CASINO_MIN_BET} до {CASINO_MAX_BET}",
                custom_id="bet",
                min_length=1,
                max_length=10,
            )
        ]
        super().__init__(title="🎰 Рулетка монет", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        bet_str = inter.text_values["bet"].strip()
        if not bet_str.isdigit():
            return await inter.response.send_message(
                "❌ Ставка должна быть целым числом.", ephemeral=True
            )
        bet = int(bet_str)
        await _roulette_play(inter, bet, reason="Ставка в рулетке монет")


class RouletteRetryView(View):
    def __init__(self, last_bet: int):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        btn_replay = Button(
            label="Играть ещё",
            style=ButtonStyle.gray,
            custom_id="roulette_retry",
            emoji=PartialEmoji(name="image", id=1555994370933653544),
            row=0,
        )
        btn_replay.callback = self.replay_callback
        self.add_item(btn_replay)

        btn_repeat = Button(
            label="Повтор ставки",
            style=ButtonStyle.gray,
            custom_id="roulette_repeat",
            emoji=PartialEmoji(name="povtor", id=1555993533629071360),
            row=0,
        )
        btn_repeat.callback = self.repeat_callback
        self.add_item(btn_repeat)

        btn_double = Button(
            label="Двойная ставка",
            style=ButtonStyle.danger,
            custom_id="roulette_double",
            emoji=PartialEmoji(name="flas", id=1551289202279325756),
            row=0,
        )
        btn_double.callback = self.double_callback
        self.add_item(btn_double)

    async def replay_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(RouletteModal())

    async def repeat_callback(self, inter: disnake.MessageInteraction):
        await _roulette_play(inter, self.last_bet, reason="Повтор ставки в рулетке")

    async def double_callback(self, inter: disnake.MessageInteraction):
        new_bet = self.last_bet * 2
        if new_bet > CASINO_MAX_BET:
            return await inter.response.send_message(
                f"❌ Двойная ставка превышает лимит ({CASINO_MAX_BET} DC).",
                ephemeral=True,
            )
        await _roulette_play(inter, new_bet, reason="Двойная ставка в рулетке")


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


def _new_deck() -> list:
    deck = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


def _hand_value(hand: list) -> int:
    total = 0
    aces = 0
    for r, s in hand:
        if r == "A":
            aces += 1
            total += 11
        elif r in ("J", "Q", "K"):
            total += 10
        else:
            total += int(r)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def _dealer_play(game: dict):
    while _hand_value(game["dealer"]) < BLACKJACK_DEALER_STAND:
        game["dealer"].append(game["deck"].pop())


async def _bj_settle(user_id: int, game: dict, outcome: str) -> dict:
    """
    Начисляет выплату, пишет лог, возвращает {payout, net, new_balance, total_bet}.
    НЕ трогает UI — рендер делает вызывающий код.
    """
    bet = game["bet"]
    total_bet = bet * 2 if game.get("doubled") else bet

    if outcome == "blackjack":
        payout = int(total_bet * BLACKJACK_BLACKJACK_MULT)
        reason = "Блэкджек (x2.5)"
    elif outcome == "win":
        payout = int(total_bet * BLACKJACK_WIN_MULT)
        reason = "Победа в блэкджеке (x2)"
    elif outcome == "push":
        payout = total_bet
        reason = "Ничья в блэкджеке (возврат)"
    else:
        payout = 0
        reason = "Проигрыш в блэкджеке"

    refund = 0
    if payout > 0:
        payout, used = apply_casino_win(user_id, payout)
        if used:
            reason += f" ({', '.join(used)})"
        await add_dc(user_id, payout, reason, to_clan_pool=True)
        if on_casino_win_hook:
            try:
                await on_casino_win_hook(user_id, payout, total_bet)
            except Exception as e:
                logger.warning(f"casino_win_hook bj: {e}")

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
        description=(
            f"> **Пользователь:** <@{user_id}>\n"
            f"> **Ставка:** `{total_bet} DC`\n"
            f"> **Выплата:** `{payout} DC`\n"
            f"> **Профит:** `{'+' if net >= 0 else ''}{net} DC`\n"
            f"> **Баланс:** `{new_balance} DC`"
        ),
        color=0x2ecc71 if payout > 0 else 0xed4245,
    ))

    return {
        "payout": payout,
        "net": net,
        "new_balance": new_balance,
        "total_bet": total_bet,
    }


async def _bj_show_table(inter, game: dict, edit_response: bool = False):
    """Перерисовывает текущий стол."""
    user_id = game["user_id"]
    balance = game.get("balance", 0)

    dealer_cards = [
        {"rank": game["dealer"][0][0],
         "suit": _suit_code(game["dealer"][0][1]),
         "color": _suit_color(game["dealer"][0][1])},
        {"back": True},
    ]
    player_cards = _cards_for_render(game["player"])

    try:
        buf = render_blackjack_table(
            user_id, balance, game["bet"],
            dealer_cards, player_cards,
            _hand_value(game["player"]), game["dealer"][0],
        )
        file = disnake.File(buf, filename=f"bj_{user_id}.png")
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{file.filename}")
        await inter.response.edit_message(
            content=None, embed=e, file=file, attachments=[],
            view=BlackjackView(game),
        )
    except Exception as e:
        logger.exception(f"_bj_show_table: {e}")


async def _bj_show_result(inter, game: dict, outcome: str):
    """Считает выплату и показывает финальную картинку с картами."""
    user_id = game["user_id"]

    settle = await _bj_settle(user_id, game, outcome)

    dealer_cards = _cards_for_render(game["dealer"])
    player_cards = _cards_for_render(game["player"])

    try:
        buf = render_blackjack_result(
            user_id,
            settle["new_balance"],
            game["bet"],
            settle["total_bet"],
            settle["payout"],
            settle["net"],
            dealer_cards, player_cards,
            _hand_value(game["dealer"]),
            _hand_value(game["player"]),
            outcome,
        )
        file = disnake.File(buf, filename=f"bj_res_{user_id}.png")
        e = disnake.Embed(color=6776679)
        e.set_image(url=f"attachment://{file.filename}")
        await inter.response.edit_message(
            content=None, embed=e, file=file, attachments=[],
            view=BlackjackRetryView(game["bet"]),
        )
    except Exception as e:
        logger.exception(f"render_blackjack_result: {e}")


async def _blackjack_play(inter, bet: int, reason: str = "Ставка в блэкджеке"):
    user_id = inter.author.id

    if bet < BLACKJACK_MIN_BET:
        return await inter.response.send_message(
            f"❌ Минимальная ставка — **{BLACKJACK_MIN_BET} DC**.", ephemeral=True
        )
    if bet > BLACKJACK_MAX_BET:
        return await inter.response.send_message(
            f"❌ Максимальная ставка — **{BLACKJACK_MAX_BET} DC**.", ephemeral=True
        )

    balance = await get_user_balance(user_id)
    if bet > balance:
        return await inter.response.send_message(
            f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`",
            ephemeral=True,
        )

    if not inter.response.is_done():
        await inter.response.defer(ephemeral=True)

    ok = await remove_dc(user_id, bet, reason)
    if not ok:
        return await inter.edit_original_response(content="❌ Не удалось списать DC. Попробуй позже.")

    deck = _new_deck()
    game = {
        "user_id": user_id,
        "bet": bet,
        "deck": deck,
        "player": [deck.pop(), deck.pop()],
        "dealer": [deck.pop(), deck.pop()],
        "doubled": False,
        "finished": False,
        "balance": balance - bet,  # для рендера — сразу после списания
    }

    if on_casino_quest_hook:
        try:
            await on_casino_quest_hook(user_id)
        except Exception:
            pass

    await _check_casino_achievements(user_id, bet=bet)

    # Показываем начальный стол
    try:
        dealer_cards = [
            {"rank": game["dealer"][0][0],
             "suit": _suit_code(game["dealer"][0][1]),
             "color": _suit_color(game["dealer"][0][1])},
            {"back": True},
        ]
        player_cards = _cards_for_render(game["player"])
        buf = render_blackjack_table(
            user_id, game["balance"], bet,
            dealer_cards, player_cards,
            _hand_value(game["player"]), game["dealer"][0],
        )
        await _send_game_screen(
            inter, buf, f"bj_{user_id}.png", view=BlackjackView(game)
        )
    except Exception as e:
        logger.exception(f"render_blackjack_table (start): {e}")
        await inter.edit_original_response(content="🃏 Раздача карт...")

    # Блэкджек сразу
    if _hand_value(game["player"]) == 21:
        await _bj_finish(inter, game)


class BlackjackBetModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label=f"Ставка ({BLACKJACK_MIN_BET}-{BLACKJACK_MAX_BET} DC)",
                placeholder=f"От {BLACKJACK_MIN_BET} до {BLACKJACK_MAX_BET}",
                custom_id="bet",
                min_length=1,
                max_length=10,
            )
        ]
        super().__init__(title="Блэкджек — ставка", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        bet_str = inter.text_values["bet"].strip()
        if not bet_str.isdigit():
            return await inter.response.send_message(
                "❌ Ставка должна быть целым числом.", ephemeral=True
            )
        bet = int(bet_str)
        await _blackjack_play(inter, bet, reason="Ставка в блэкджеке")


class BlackjackView(View):
    def __init__(self, game: dict):
        super().__init__(timeout=300)
        self.game = game

        btn_hit = Button(
            label=f"{P}{P}Взять{P}{P}",
            style=ButtonStyle.gray,
            custom_id="bj_hit",
            emoji=PartialEmoji(name="adde", id=1551288309240696954),
            row=0,
        )
        btn_hit.callback = self.hit_callback
        self.add_item(btn_hit)

        btn_stand = Button(
            label=f"{P}{P}Хватит{P}{P}",
            style=ButtonStyle.gray,
            custom_id="bj_stand",
            emoji=PartialEmoji(name="PAM", id=1551288362822795434),
            row=0,
        )
        btn_stand.callback = self.stand_callback
        self.add_item(btn_stand)

        btn_double = Button(
            label=f"{P}{P}Удвоить{P}{P}",
            style=ButtonStyle.danger,
            custom_id="bj_double",
            emoji=PartialEmoji(name="flas", id=1551289202279325756),
            row=0,
        )
        btn_double.callback = self.double_callback
        self.add_item(btn_double)

    async def _check_owner(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.game["user_id"]:
            await inter.response.send_message("⛔ Это не ваша игра.", ephemeral=True)
            return False
        if self.game["finished"]:
            await inter.response.send_message("⛔ Игра уже завершена.", ephemeral=True)
            return False
        return True

    async def hit_callback(self, inter: disnake.MessageInteraction):
        if not await self._check_owner(inter):
            return
        self.game["player"].append(self.game["deck"].pop())
        value = _hand_value(self.game["player"])

        if value > 21:
            self.game["finished"] = True
            await _bj_show_result(inter, self.game, "bust")
        elif value == 21:
            await self._stand_logic(inter)
        else:
            await _bj_show_table(inter, self.game)

    async def stand_callback(self, inter: disnake.MessageInteraction):
        if not await self._check_owner(inter):
            return
        await self._stand_logic(inter)

    async def _stand_logic(self, inter: disnake.MessageInteraction):
        _dealer_play(self.game)
        self.game["finished"] = True
        player_val = _hand_value(self.game["player"])
        dealer_val = _hand_value(self.game["dealer"])

        if dealer_val > 21 or player_val > dealer_val:
            outcome = "win"
        elif player_val == dealer_val:
            outcome = "push"
        else:
            outcome = "lose"

        await _bj_show_result(inter, self.game, outcome)

    async def double_callback(self, inter: disnake.MessageInteraction):
        if not await self._check_owner(inter):
            return
        if self.game.get("doubled"):
            return await inter.response.send_message("⛔ Уже удвоено.", ephemeral=True)
        if len(self.game["player"]) != 2:
            return await inter.response.send_message(
                "⛔ Удвоить можно только на первых двух картах.", ephemeral=True
            )

        user_id = self.game["user_id"]
        bet = self.game["bet"]
        new_total = bet * 2
        if new_total > CASINO_MAX_BET:
            return await inter.response.send_message(
                f"❌ Удвоение превышает лимит ({CASINO_MAX_BET} DC).", ephemeral=True
            )
        balance = await get_user_balance(user_id)
        if balance < bet:
            return await inter.response.send_message(
                f"❌ Недостаточно DC для удвоения.\n> Нужно ещё: `{bet} DC`", ephemeral=True
            )
        ok = await remove_dc(user_id, bet, "Удвоение в блэкджеке")
        if not ok:
            return await inter.response.send_message("❌ Ошибка списания.", ephemeral=True)
        self.game["doubled"] = True
        self.game["player"].append(self.game["deck"].pop())
        await self._stand_logic(inter)


async def _bj_finish(inter: disnake.MessageInteraction, game: dict):
    """Блэкджек с раздачи — сразу финал."""
    _dealer_play(game)
    game["finished"] = True
    dealer_val = _hand_value(game["dealer"])

    if dealer_val == 21 and len(game["dealer"]) == 2:
        outcome = "push"
    else:
        outcome = "blackjack"

    await _bj_show_result(inter, game, outcome)


class BlackjackRetryView(View):
    def __init__(self, last_bet: int):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        btn_replay = Button(
            label=f"{P}Играть ещё{P}",
            style=ButtonStyle.gray,
            custom_id="bj_retry",
            emoji=PartialEmoji(name="image", id=1555994370933653544),
            row=0,
        )
        btn_replay.callback = self.replay_callback
        self.add_item(btn_replay)

        btn_repeat = Button(
            label=f"{P}Повтор ставки{P}",
            style=ButtonStyle.gray,
            custom_id="bj_repeat",
            emoji=PartialEmoji(name="povtor", id=1555993533629071360),
            row=0,
        )
        btn_repeat.callback = self.repeat_callback
        self.add_item(btn_repeat)

        btn_double = Button(
            label=f"{P}Двойная ставка{P}",
            style=ButtonStyle.danger,
            custom_id="bj_double_next",
            emoji=PartialEmoji(name="flas", id=1551289202279325756),
            row=0,
        )
        btn_double.callback = self.double_callback
        self.add_item(btn_double)

    async def replay_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(BlackjackBetModal())

    async def repeat_callback(self, inter: disnake.MessageInteraction):
        await _blackjack_play(inter, self.last_bet, reason="Повтор ставки в блэкджеке")

    async def double_callback(self, inter: disnake.MessageInteraction):
        new_bet = self.last_bet * 2
        if new_bet > CASINO_MAX_BET:
            return await inter.response.send_message(
                f"❌ Двойная ставка превышает лимит ({CASINO_MAX_BET} DC).",
                ephemeral=True,
            )
        await _blackjack_play(inter, new_bet, reason="Двойная ставка в блэкджеке")


# ============================================================
# МОНЕТКА
# ============================================================
COINFLIP_MIN_BET = CASINO_MIN_BET
COINFLIP_MAX_BET = CASINO_MAX_BET
COINFLIP_WIN_MULT = 1.9


async def _coinflip_play(inter, bet: int, reason: str = "Ставка в монетке"):
    user_id = inter.author.id

    if bet < COINFLIP_MIN_BET:
        return await inter.response.send_message(
            f"❌ Минимальная ставка — **{COINFLIP_MIN_BET} DC**.", ephemeral=True
        )
    if bet > COINFLIP_MAX_BET:
        return await inter.response.send_message(
            f"❌ Максимальная ставка — **{COINFLIP_MAX_BET} DC**.", ephemeral=True
        )

    balance = await get_user_balance(user_id)
    if bet > balance:
        return await inter.response.send_message(
            f"❌ Недостаточно DC.\n> **Баланс:** `{balance} DC`\n> **Ставка:** `{bet} DC`",
            ephemeral=True,
        )

    if not inter.response.is_done():
        await inter.response.defer(ephemeral=True)

    ok = await remove_dc(user_id, bet, reason)
    if not ok:
        return await inter.edit_original_response(content="❌ Не удалось списать DC.")

    await _check_casino_achievements(user_id, bet=bet)

    try:
        buf = render_coinflip_choice(user_id, balance, bet)
        await _send_game_screen(
            inter, buf, f"coin_choice_{user_id}.png",
            view=CoinflipChoiceView(bet),
        )
    except Exception as e:
        logger.exception(f"render_coinflip_choice: {e}")


class CoinflipBetModal(Modal):
    def __init__(self):
        components = [
            TextInput(
                label=f"Ставка ({COINFLIP_MIN_BET}-{COINFLIP_MAX_BET} DC)",
                placeholder=f"От {COINFLIP_MIN_BET} до {COINFLIP_MAX_BET}",
                custom_id="bet",
                min_length=1,
                max_length=10,
            )
        ]
        super().__init__(title="Монетка — ставка", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        bet_str = inter.text_values["bet"].strip()
        if not bet_str.isdigit():
            return await inter.response.send_message(
                "❌ Ставка должна быть целым числом.", ephemeral=True
            )
        bet = int(bet_str)
        await _coinflip_play(inter, bet, reason="Ставка в монетке")


class CoinflipChoiceView(View):
    def __init__(self, bet: int):
        super().__init__(timeout=60)
        self.bet = bet

        btn_heads = Button(
            label=f"{P}{P}{P}{P}Орёл{P}{P}{P}{P}",
            style=ButtonStyle.gray,
            custom_id="coin_heads",
            emoji=PartialEmoji(name="image", id=1551296060729725019),
            row=0,
        )
        btn_heads.callback = self.heads_callback
        self.add_item(btn_heads)

        btn_tails = Button(
            label=f"{P}{P}{P}{P}Решка{P}{P}{P}{P}",
            style=ButtonStyle.gray,
            custom_id="coin_tails",
            emoji=PartialEmoji(name="2313", id=1551296094468575366),
            row=0,
        )
        btn_tails.callback = self.tails_callback
        self.add_item(btn_tails)

    async def _play(self, inter: disnake.MessageInteraction, user_choice: str):
        # короткая пауза, покажем «крутится»
        try:
            await inter.response.edit_message(
                content="🪙 Монетка крутится...", embed=None, view=None,
                attachments=[],
            )
        except Exception:
            pass
        await asyncio.sleep(1.8)

        result_side = random.choice(["heads", "tails"])
        won = (result_side == user_choice)
        user_id = inter.author.id
        bet = self.bet

        payout = 0
        refund = 0

        if on_casino_quest_hook:
            try:
                await on_casino_quest_hook(user_id)
            except Exception:
                pass

        if won:
            payout = int(bet * COINFLIP_WIN_MULT)
            payout, used = apply_casino_win(user_id, payout)
            reason = f"Монетка ({result_side})"
            if used:
                reason += f" ({', '.join(used)})"
            await add_dc(user_id, payout, reason, to_clan_pool=True)
            if on_casino_win_hook:
                try:
                    await on_casino_win_hook(user_id, payout, bet)
                except Exception as e:
                    logger.warning(f"casino_win_hook coin: {e}")
            net = payout - bet
            if net >= 10000:
                await _check_casino_achievements(user_id, profit=net)
        else:
            refund = try_insurance(user_id, bet)
            if refund > 0:
                await add_dc(user_id, refund, "Страховка ставки (монетка)")
            net = -bet + refund

        new_balance = await get_user_balance(user_id)

        result_side_ru = "Орёл" if result_side == "heads" else "Решка"
        user_choice_ru = "Орёл" if user_choice == "heads" else "Решка"

        try:
            if won:
                buf = render_coinflip_win(
                    user_id, new_balance, bet, payout, payout - bet,
                    result_side_ru, user_choice_ru,
                )
            else:
                buf = render_coinflip_lose(
                    user_id, new_balance, bet, refund,
                    result_side_ru, user_choice_ru,
                )
            file = disnake.File(buf, filename=f"coin_res_{user_id}.png")
            e = disnake.Embed(color=6776679)
            e.set_image(url=f"attachment://{file.filename}")
            await inter.edit_original_response(
                content=None, embed=e, file=file, attachments=[],
                view=CoinflipRetryView(bet),
            )
        except Exception as e:
            logger.exception(f"render coinflip result: {e}")

        asyncio.create_task(log_discord(
            title=f"🪙 Монетка: {'победа' if won else 'проигрыш'}",
            description=(
                f"> **Пользователь:** <@{user_id}>\n"
                f"> **Ставка:** `{bet} DC`\n"
                f"> **Выбор:** `{user_choice}` → выпало `{result_side}`\n"
                f"> **Выплата:** `{payout} DC`\n"
                f"> **Страховка:** `{refund} DC`\n"
                f"> **Баланс:** `{new_balance} DC`"
            ),
            color=0x2ecc71 if won else 0xed4245,
        ))

    async def heads_callback(self, inter: disnake.MessageInteraction):
        await self._play(inter, "heads")

    async def tails_callback(self, inter: disnake.MessageInteraction):
        await self._play(inter, "tails")


class CoinflipRetryView(View):
    def __init__(self, last_bet: int):
        super().__init__(timeout=300)
        self.last_bet = last_bet

        btn_replay = Button(
            label=f"{P}Играть ещё{P}",
            style=ButtonStyle.gray,
            custom_id="coin_retry",
            emoji=PartialEmoji(name="image", id=1555994370933653544),
            row=0,
        )
        btn_replay.callback = self.replay_callback
        self.add_item(btn_replay)

        btn_repeat = Button(
            label=f"{P}Повтор ставки{P}",
            style=ButtonStyle.gray,
            custom_id="coin_repeat",
            emoji=PartialEmoji(name="povtor", id=1555993533629071360),
            row=0,
        )
        btn_repeat.callback = self.repeat_callback
        self.add_item(btn_repeat)

        btn_double = Button(
            label=f"{P}Двойная ставка{P}",
            style=ButtonStyle.danger,
            custom_id="coin_double",
            emoji=PartialEmoji(name="flas", id=1551289202279325756),
            row=0,
        )
        btn_double.callback = self.double_callback
        self.add_item(btn_double)

    async def replay_callback(self, inter: disnake.MessageInteraction):
        await inter.response.send_modal(CoinflipBetModal())

    async def repeat_callback(self, inter: disnake.MessageInteraction):
        await _coinflip_play(inter, self.last_bet, reason="Повтор ставки в монетке")

    async def double_callback(self, inter: disnake.MessageInteraction):
        new_bet = self.last_bet * 2
        if new_bet > CASINO_MAX_BET:
            return await inter.response.send_message(
                f"❌ Двойная ставка превышает лимит ({CASINO_MAX_BET} DC).",
                ephemeral=True,
            )
        await _coinflip_play(inter, new_bet, reason="Двойная ставка в монетке")
