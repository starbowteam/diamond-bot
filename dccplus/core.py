# -*- coding: utf-8 -*-
"""
DCC+ · Diamond Coin Crypto+.
Инвестиционная система: плавающий курс + стейкинг.
"""
import os
import time
import math
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple

from disnake.ext import tasks

from core.utils import (
    CONFIG, logger, db, cur, log_discord,
    get_dc_cache,
)


MSK = timezone(timedelta(hours=3))

# ─────────────── КОНСТАНТЫ ───────────────
BASE_PRICE          = 100.0
MIN_PRICE           = 30.0
MAX_PRICE           = 300.0
MAX_SUPPLY          = 100_000.0
PRICE_MAX_DELTA     = 0.08
PRICE_UPDATE_MIN    = 15

SELL_COMMISSION     = 0.03
EARLY_UNSTAKE_PEN   = 0.10

MIN_BUY_DC          = 100
MAX_BUY_DC_DAY      = 50_000
MAX_SELL_DCC_HOUR   = 500.0
TRADE_COOLDOWN      = 60

STAKE_MIN           = 50.0
STAKE_MAX_ONE       = 10_000.0
STAKE_MAX_ACTIVE    = 3

STAKE_PLANS = {
    7:  0.05,
    14: 0.14,
    30: 0.35,
}

TOP_EXCLUDED_USERS = {796293832751972352}


# ─────────────── БД ───────────────
def init_dccplus_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS dccplus_state (
        id              INTEGER PRIMARY KEY CHECK(id=1),
        current_price   REAL DEFAULT 100.0,
        current_supply  REAL DEFAULT 0.0,
        burn_fund       REAL DEFAULT 0.0,
        last_update     INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS dccplus_wallet (
        user_id         INTEGER PRIMARY KEY,
        balance         REAL DEFAULT 0,
        total_bought    REAL DEFAULT 0,
        total_sold      REAL DEFAULT 0,
        total_invested  REAL DEFAULT 0,
        total_returned  REAL DEFAULT 0,
        first_buy_ts    INTEGER DEFAULT 0,
        last_trade_ts   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS dccplus_stakes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER,
        amount          REAL,
        days            INTEGER,
        profit_pct      REAL,
        started_at      INTEGER,
        unlock_at       INTEGER,
        claimed         INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_dcc_stakes_user
        ON dccplus_stakes(user_id);
    CREATE INDEX IF NOT EXISTS idx_dcc_stakes_unlock
        ON dccplus_stakes(unlock_at, claimed);

    CREATE TABLE IF NOT EXISTS dccplus_price_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        price           REAL,
        supply          REAL,
        net_flow        REAL DEFAULT 0,
        ts              INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_dcc_price_ts
        ON dccplus_price_history(ts);

    CREATE TABLE IF NOT EXISTS dccplus_transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER,
        type            TEXT,
        amount          REAL,
        price           REAL,
        dc_amount       REAL,
        fee             REAL DEFAULT 0,
        ts              INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_dcc_tx_user
        ON dccplus_transactions(user_id);
    CREATE INDEX IF NOT EXISTS idx_dcc_tx_ts
        ON dccplus_transactions(ts);
    """)
    db.commit()

    cur.execute("""
        INSERT OR IGNORE INTO dccplus_state
        (id, current_price, current_supply, burn_fund, last_update)
        VALUES (1, ?, 0.0, 0.0, ?)
    """, (BASE_PRICE, int(time.time())))
    db.commit()


# ─────────────── STATE ───────────────
def get_state() -> dict:
    row = cur.execute("SELECT * FROM dccplus_state WHERE id=1").fetchone()
    if not row:
        init_dccplus_tables()
        row = cur.execute("SELECT * FROM dccplus_state WHERE id=1").fetchone()
    return dict(row)


def get_price() -> float:
    return float(get_state()["current_price"])


def get_supply() -> float:
    return float(get_state()["current_supply"])


def get_burn_fund() -> float:
    return float(get_state()["burn_fund"])


# ─────────────── РАСЧЁТ КУРСА ───────────────
def calc_new_price() -> float:
    state = get_state()
    cur_price = float(state["current_price"])
    supply = float(state["current_supply"])

    now = int(time.time())
    hour_ago = now - 3600

    row = cur.execute(
        "SELECT "
        "  COALESCE(SUM(CASE WHEN type='buy' THEN amount ELSE 0 END), 0) AS buys, "
        "  COALESCE(SUM(CASE WHEN type='sell' THEN amount ELSE 0 END), 0) AS sells "
        "FROM dccplus_transactions WHERE ts >= ?",
        (hour_ago,)
    ).fetchone()
    buys = float(row["buys"] or 0)
    sells = float(row["sells"] or 0)
    net_flow = buys - sells

    active_row = cur.execute(
        "SELECT COUNT(*) AS c FROM dc_cache WHERE last_active_ts >= ?",
        (hour_ago,)
    ).fetchone()
    active_users = int(active_row["c"] or 0)

    supply_factor = 1.0 - (supply / MAX_SUPPLY) * 0.4
    supply_factor = max(0.5, min(1.0, supply_factor))

    volume_factor = 1.0 + max(-0.30, min(0.30, net_flow / 20_000.0))

    activity_factor = 0.95 + min(active_users / 500.0, 1.0) * 0.20

    event_factor = 1.0

    new_price = BASE_PRICE * supply_factor * volume_factor * activity_factor * event_factor

    delta_cap = cur_price * PRICE_MAX_DELTA
    new_price = max(cur_price - delta_cap, min(cur_price + delta_cap, new_price))
    new_price = max(MIN_PRICE, min(MAX_PRICE, new_price))

    return new_price


def update_price() -> dict:
    old = get_price()
    new = calc_new_price()
    now = int(time.time())
    supply = get_supply()

    net_flow = 0.0
    try:
        hour_ago = now - 3600
        r = cur.execute(
            "SELECT "
            "  COALESCE(SUM(CASE WHEN type='buy' THEN amount ELSE 0 END), 0) - "
            "  COALESCE(SUM(CASE WHEN type='sell' THEN amount ELSE 0 END), 0) AS nf "
            "FROM dccplus_transactions WHERE ts >= ?",
            (hour_ago,)
        ).fetchone()
        net_flow = float(r["nf"] or 0)
    except Exception:
        pass

    cur.execute(
        "UPDATE dccplus_state SET current_price=?, last_update=? WHERE id=1",
        (new, now)
    )
    cur.execute(
        "INSERT INTO dccplus_price_history (price, supply, net_flow, ts) VALUES (?, ?, ?, ?)",
        (new, supply, net_flow, now)
    )
    db.commit()

    return {"old": old, "new": new, "delta_pct": ((new - old) / old * 100) if old else 0}


# ─────────────── WALLET ───────────────
def get_wallet(user_id: int) -> dict:
    row = cur.execute(
        "SELECT * FROM dccplus_wallet WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        return {
            "user_id": user_id,
            "balance": 0.0,
            "total_bought": 0.0,
            "total_sold": 0.0,
            "total_invested": 0.0,
            "total_returned": 0.0,
            "first_buy_ts": 0,
            "last_trade_ts": 0,
        }
    return dict(row)


def get_user_dcc_balance(user_id: int) -> float:
    return float(get_wallet(user_id)["balance"])


def _ensure_wallet(user_id: int):
    cur.execute(
        "INSERT OR IGNORE INTO dccplus_wallet (user_id) VALUES (?)",
        (user_id,)
    )
    db.commit()


# ─────────────── ЛИМИТЫ ───────────────
def _check_trade_cooldown(user_id: int) -> Optional[str]:
    wallet = get_wallet(user_id)
    last = wallet.get("last_trade_ts") or 0
    if not last:
        return None
    left = TRADE_COOLDOWN - (int(time.time()) - last)
    if left > 0:
        return f"Кулдаун между сделками: {left} сек"
    return None


def _check_buy_daily_limit(user_id: int, dc_amount: int) -> Optional[str]:
    day_ago = int(time.time()) - 86400
    row = cur.execute(
        "SELECT COALESCE(SUM(dc_amount), 0) AS s FROM dccplus_transactions "
        "WHERE user_id=? AND type='buy' AND ts >= ?",
        (user_id, day_ago)
    ).fetchone()
    today = float(row["s"] or 0)
    if today + dc_amount > MAX_BUY_DC_DAY:
        left = int(MAX_BUY_DC_DAY - today)
        return f"Дневной лимит покупки. Осталось {left} DC"
    return None


def _check_sell_hour_limit(user_id: int, dcc_amount: float) -> Optional[str]:
    hour_ago = int(time.time()) - 3600
    row = cur.execute(
        "SELECT COALESCE(SUM(amount), 0) AS s FROM dccplus_transactions "
        "WHERE user_id=? AND type='sell' AND ts >= ?",
        (user_id, hour_ago)
    ).fetchone()
    last_hour = float(row["s"] or 0)
    if last_hour + dcc_amount > MAX_SELL_DCC_HOUR:
        left = max(MAX_SELL_DCC_HOUR - last_hour, 0)
        return f"Максимум продажи в час: 500 DCC+. Осталось {left:.2f}"
    return None


# ─────────────── BUY ───────────────
async def buy_dccplus(user_id: int, dc_amount: int) -> dict:
    if dc_amount < MIN_BUY_DC:
        return {"ok": False, "error": f"Минимум покупки: {MIN_BUY_DC} DC"}

    cd = _check_trade_cooldown(user_id)
    if cd:
        return {"ok": False, "error": cd}

    lim = _check_buy_daily_limit(user_id, dc_amount)
    if lim:
        return {"ok": False, "error": lim}

    balance = get_dc_cache(user_id).get("balance", 0)
    if balance < dc_amount:
        return {"ok": False, "error": f"Не хватает {dc_amount - balance} DC"}

    state = get_state()
    price = float(state["current_price"])
    supply = float(state["current_supply"])

    dcc_amount = dc_amount / price

    if supply + dcc_amount > MAX_SUPPLY:
        left_dcc = MAX_SUPPLY - supply
        if left_dcc <= 0:
            return {"ok": False, "error": "Кэп эмиссии достигнут"}
        max_dc = int(left_dcc * price)
        return {"ok": False, "error": f"До кэпа можно купить {max_dc} DC"}

    from modules.dc import remove_dc
    ok = await remove_dc(user_id, dc_amount, f"Покупка DCC+ по курсу {price:.2f}")
    if not ok:
        return {"ok": False, "error": "Не удалось списать DC"}

    now = int(time.time())
    _ensure_wallet(user_id)

    cur.execute("""
        UPDATE dccplus_wallet SET
            balance = balance + ?,
            total_bought = total_bought + ?,
            total_invested = total_invested + ?,
            first_buy_ts = CASE WHEN first_buy_ts=0 THEN ? ELSE first_buy_ts END,
            last_trade_ts = ?
        WHERE user_id=?
    """, (dcc_amount, dcc_amount, dc_amount, now, now, user_id))

    cur.execute(
        "UPDATE dccplus_state SET current_supply = current_supply + ? WHERE id=1",
        (dcc_amount,)
    )

    cur.execute("""
        INSERT INTO dccplus_transactions
        (user_id, type, amount, price, dc_amount, fee, ts)
        VALUES (?, 'buy', ?, ?, ?, 0, ?)
    """, (user_id, dcc_amount, price, dc_amount, now))
    db.commit()

    await log_discord(
        title="💠 DCC+ Куплено",
        description=(
            f"> **Юзер:** <@{user_id}>\n"
            f"> **Куплено:** `{dcc_amount:.4f} DCC+`\n"
            f"> **Потрачено:** `{dc_amount} DC`\n"
            f"> **Курс:** `{price:.2f} DC`"
        ),
        color=0x4dd0e1,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {"ok": True, "dcc_amount": dcc_amount, "price": price}


# ─────────────── SELL ───────────────
async def sell_dccplus(user_id: int, dcc_amount: float) -> dict:
    if dcc_amount <= 0:
        return {"ok": False, "error": "Некорректная сумма"}

    wallet = get_wallet(user_id)
    if wallet["balance"] < dcc_amount:
        return {"ok": False, "error": f"У тебя только {wallet['balance']:.4f} DCC+"}

    cd = _check_trade_cooldown(user_id)
    if cd:
        return {"ok": False, "error": cd}

    lim = _check_sell_hour_limit(user_id, dcc_amount)
    if lim:
        return {"ok": False, "error": lim}

    state = get_state()
    price = float(state["current_price"])

    gross_dc = dcc_amount * price
    fee = gross_dc * SELL_COMMISSION
    net_dc = int(gross_dc - fee)

    if net_dc <= 0:
        return {"ok": False, "error": "Слишком маленькая сумма для продажи"}

    now = int(time.time())

    cur.execute("""
        UPDATE dccplus_wallet SET
            balance = balance - ?,
            total_sold = total_sold + ?,
            total_returned = total_returned + ?,
            last_trade_ts = ?
        WHERE user_id=?
    """, (dcc_amount, dcc_amount, net_dc, now, user_id))

    cur.execute(
        "UPDATE dccplus_state SET current_supply = MAX(current_supply - ?, 0) WHERE id=1",
        (dcc_amount,)
    )

    burn_half = fee * 0.5
    cur.execute(
        "UPDATE dccplus_state SET burn_fund = burn_fund + ? WHERE id=1",
        (burn_half,)
    )

    cur.execute("""
        INSERT INTO dccplus_transactions
        (user_id, type, amount, price, dc_amount, fee, ts)
        VALUES (?, 'sell', ?, ?, ?, ?, ?)
    """, (user_id, dcc_amount, price, net_dc, fee, now))
    db.commit()

    from modules.dc import add_dc
    await add_dc(user_id, net_dc, f"Продажа {dcc_amount:.4f} DCC+ по {price:.2f}",
                 notify=False, log=False)

    await log_discord(
        title="💰 DCC+ Продано",
        description=(
            f"> **Юзер:** <@{user_id}>\n"
            f"> **Продано:** `{dcc_amount:.4f} DCC+`\n"
            f"> **Получено:** `{net_dc} DC` (комиссия `{fee:.0f}`)\n"
            f"> **Курс:** `{price:.2f} DC`"
        ),
        color=0xff6b6b,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {
        "ok": True,
        "dcc_amount": dcc_amount,
        "gross_dc": int(gross_dc),
        "fee": int(fee),
        "net_dc": net_dc,
        "price": price,
    }


# ─────────────── STAKE ───────────────
def get_user_stakes(user_id: int) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM dccplus_stakes WHERE user_id=? ORDER BY started_at DESC",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_stakes(user_id: int) -> List[dict]:
    rows = cur.execute(
        "SELECT * FROM dccplus_stakes WHERE user_id=? AND claimed=0 "
        "ORDER BY unlock_at ASC",
        (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


async def create_stake(user_id: int, amount: float, days: int) -> dict:
    if days not in STAKE_PLANS:
        return {"ok": False, "error": "Такого срока нет"}

    if amount < STAKE_MIN:
        return {"ok": False, "error": f"Минимум {STAKE_MIN} DCC+"}
    if amount > STAKE_MAX_ONE:
        return {"ok": False, "error": f"Максимум {STAKE_MAX_ONE} DCC+ на один стейк"}

    active = get_active_stakes(user_id)
    if len(active) >= STAKE_MAX_ACTIVE:
        return {"ok": False, "error": f"Максимум {STAKE_MAX_ACTIVE} активных стейков"}

    wallet = get_wallet(user_id)
    if wallet["balance"] < amount:
        return {"ok": False, "error": f"В кошельке только {wallet['balance']:.4f} DCC+"}

    profit_pct = STAKE_PLANS[days]
    now = int(time.time())
    unlock_at = now + days * 86400

    cur.execute("""
        UPDATE dccplus_wallet SET balance = balance - ?, last_trade_ts = ?
        WHERE user_id=?
    """, (amount, now, user_id))

    cur.execute("""
        INSERT INTO dccplus_stakes
        (user_id, amount, days, profit_pct, started_at, unlock_at, claimed)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (user_id, amount, days, profit_pct, now, unlock_at))
    stake_id = cur.lastrowid

    cur.execute("""
        INSERT INTO dccplus_transactions
        (user_id, type, amount, price, dc_amount, fee, ts)
        VALUES (?, 'stake', ?, ?, 0, 0, ?)
    """, (user_id, amount, get_price(), now))
    db.commit()

    await log_discord(
        title="🔒 DCC+ Стейк создан",
        description=(
            f"> **Юзер:** <@{user_id}>\n"
            f"> **Сумма:** `{amount:.4f} DCC+`\n"
            f"> **Срок:** `{days} дней` · +{profit_pct*100:.0f}%\n"
            f"> **Разлок:** <t:{unlock_at}:F>"
        ),
        color=0x4dd0e1,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {
        "ok": True,
        "stake_id": stake_id,
        "amount": amount,
        "days": days,
        "profit_pct": profit_pct,
        "unlock_at": unlock_at,
    }


async def claim_stake(user_id: int, stake_id: int, early: bool = False) -> dict:
    row = cur.execute(
        "SELECT * FROM dccplus_stakes WHERE id=? AND user_id=?",
        (stake_id, user_id)
    ).fetchone()
    if not row:
        return {"ok": False, "error": "Стейк не найден"}
    if row["claimed"]:
        return {"ok": False, "error": "Уже забрал"}

    now = int(time.time())
    amount = float(row["amount"])
    profit_pct = float(row["profit_pct"])
    unlock_at = int(row["unlock_at"])

    is_early = now < unlock_at
    if is_early and not early:
        left = unlock_at - now
        h = left // 3600
        m = (left % 3600) // 60
        return {"ok": False, "error": f"Разлок через {h}ч {m}м"}

    if is_early:
        # Штраф 10% от тела, награда не начисляется
        penalty = amount * EARLY_UNSTAKE_PEN
        payout = amount - penalty
        profit_amount = 0.0
    else:
        profit_amount = amount * profit_pct
        payout = amount + profit_amount
        penalty = 0.0

    cur.execute("UPDATE dccplus_stakes SET claimed=1 WHERE id=?", (stake_id,))

    cur.execute("""
        UPDATE dccplus_wallet SET
            balance = balance + ?,
            last_trade_ts = ?
        WHERE user_id=?
    """, (payout, now, user_id))

    cur.execute("""
        INSERT INTO dccplus_transactions
        (user_id, type, amount, price, dc_amount, fee, ts)
        VALUES (?, 'unstake', ?, ?, 0, ?, ?)
    """, (user_id, payout, get_price(), penalty, now))
    db.commit()

    await log_discord(
        title="🔓 DCC+ Стейк завершён",
        description=(
            f"> **Юзер:** <@{user_id}>\n"
            f"> **Тело:** `{amount:.4f} DCC+`\n"
            f"> **Профит:** `+{profit_amount:.4f} DCC+`\n"
            f"> **{'⚠️ Досрочно' if is_early else '✅ По плану'}**"
            + (f"\n> **Штраф:** `−{penalty:.4f} DCC+`" if penalty > 0 else "")
        ),
        color=0x2ecc71 if not is_early else 0xff6b6b,
        channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]
    )

    return {
        "ok": True,
        "payout": payout,
        "profit": profit_amount,
        "penalty": penalty,
        "early": is_early,
    }


# ─────────────── ТОП ХОЛДЕРОВ ───────────────
def get_top_holders(limit: int = 10) -> List[dict]:
    rows = cur.execute("""
        SELECT user_id, balance, total_invested, total_returned, first_buy_ts
        FROM dccplus_wallet
        WHERE balance > 0
        ORDER BY balance DESC
    """).fetchall()

    result = []
    for r in rows:
        uid = r["user_id"]
        if uid in TOP_EXCLUDED_USERS:
            continue
        invested = float(r["total_invested"] or 0)
        current_val = float(r["balance"] or 0) * get_price()
        pnl_pct = ((current_val - invested) / invested * 100) if invested > 0 else 0.0
        result.append({
            "user_id": uid,
            "balance": float(r["balance"] or 0),
            "invested": invested,
            "current_value": current_val,
            "pnl_pct": pnl_pct,
        })
        if len(result) >= limit:
            break
    return result


def get_user_place(user_id: int) -> Optional[int]:
    if user_id in TOP_EXCLUDED_USERS:
        return None
    top = get_top_holders(limit=10000)
    for i, t in enumerate(top, 1):
        if t["user_id"] == user_id:
            return i
    return None


# ─────────────── ИСТОРИЯ ───────────────
def get_price_history(hours: int = 24, points: int = 60) -> List[float]:
    since = int(time.time()) - hours * 3600
    rows = cur.execute(
        "SELECT price FROM dccplus_price_history WHERE ts >= ? ORDER BY ts ASC",
        (since,)
    ).fetchall()
    prices = [float(r["price"]) for r in rows]

    if not prices:
        cur_p = get_price()
        return [cur_p] * points

    if len(prices) <= points:
        return prices

    step = len(prices) / points
    result = []
    for i in range(points):
        idx = int(i * step)
        result.append(prices[min(idx, len(prices) - 1)])
    return result


def get_recent_transactions(limit: int = 5) -> List[dict]:
    rows = cur.execute("""
        SELECT user_id, type, amount, price, dc_amount, ts
        FROM dccplus_transactions
        WHERE type IN ('buy', 'sell', 'stake')
        ORDER BY ts DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_stats_24h() -> dict:
    day_ago = int(time.time()) - 86400
    row = cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN type='buy' THEN amount ELSE 0 END), 0) AS buys,
            COALESCE(SUM(CASE WHEN type='sell' THEN amount ELSE 0 END), 0) AS sells,
            COALESCE(SUM(CASE WHEN type='buy' THEN dc_amount ELSE 0 END), 0) AS buy_dc,
            COALESCE(SUM(fee), 0) AS fee_total
        FROM dccplus_transactions WHERE ts >= ?
    """, (day_ago,)).fetchone()

    buys = float(row["buys"] or 0)
    sells = float(row["sells"] or 0)
    buy_dc = float(row["buy_dc"] or 0)
    fee_total = float(row["fee"] or 0)

    return {
        "buys": buys,
        "sells": sells,
        "net_flow": buys - sells,
        "volume_dc": buy_dc,
        "fee_burned": fee_total * 0.5,
    }


def get_holders_count() -> int:
    row = cur.execute(
        "SELECT COUNT(*) AS c FROM dccplus_wallet WHERE balance > 0"
    ).fetchone()
    return int(row["c"] or 0)


# ─────────────── TASKS ───────────────
@tasks.loop(minutes=PRICE_UPDATE_MIN)
async def dcc_price_task(bot):
    await bot.wait_until_ready()
    try:
        r = update_price()
        logger.info(
            f"💠 DCC+ курс: {r['old']:.2f} → {r['new']:.2f} "
            f"({r['delta_pct']:+.2f}%)"
        )
    except Exception as e:
        logger.exception(f"dcc_price_task: {e}")


@tasks.loop(minutes=5)
async def dcc_stake_unlock_task(bot):
    await bot.wait_until_ready()
    try:
        now = int(time.time())
        rows = cur.execute(
            "SELECT id, user_id, amount, profit_pct FROM dccplus_stakes "
            "WHERE claimed=0 AND unlock_at <= ?",
            (now,)
        ).fetchall()

        for r in rows:
            try:
                await claim_stake(r["user_id"], r["id"], early=False)
                user = bot.get_user(r["user_id"])
                if not user:
                    try:
                        user = await bot.fetch_user(r["user_id"])
                    except Exception:
                        user = None
                if user:
                    try:
                        profit = float(r["amount"]) * float(r["profit_pct"])
                        await user.send(
                            f"🔓 **Твой стейк DCC+ разблокирован!**\n"
                            f"> Тело: `{float(r['amount']):.4f} DCC+`\n"
                            f"> Профит: `+{profit:.4f} DCC+`\n"
                            f"> Зачислено на кошелёк DCC+"
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"stake unlock {r['id']}: {e}")
    except Exception as e:
        logger.exception(f"dcc_stake_unlock_task: {e}")


@tasks.loop(hours=24)
async def dcc_history_cleanup_task(bot):
    await bot.wait_until_ready()
    try:
        cutoff = int(time.time()) - 30 * 86400
        cur.execute(
            "DELETE FROM dccplus_price_history WHERE ts < ?", (cutoff,)
        )
        db.commit()
        logger.info("💠 DCC+: история курса старше 30 дней очищена")
    except Exception as e:
        logger.exception(f"dcc_history_cleanup_task: {e}")


def start_dcc_tasks(bot):
    if not dcc_price_task.is_running():
        dcc_price_task.start(bot)
    if not dcc_stake_unlock_task.is_running():
        dcc_stake_unlock_task.start(bot)
    if not dcc_history_cleanup_task.is_running():
        dcc_history_cleanup_task.start(bot)
