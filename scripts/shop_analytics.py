# -*- coding: utf-8 -*-
"""HTML-аналитика магазина (без внешних зависимостей).

Источник данных — SQLite `data/diamond.db`, таблица `ai_manager_sessions`:
  · `invoice_amount > 0`  — счёт выставлен;
  · `receipt_url <> ''`   — клиент прислал чек, оплата принята.

Отчёт — один самодостаточный HTML-файл: CSS и SVG внутри, ни CDN, ни JS.
Его можно открыть локально, положить на хостинг или отправить документом в Telegram.

Запуск:
    python scripts/shop_analytics.py                    # реальная БД → data/reports/shop_report.html
    python scripts/shop_analytics.py --demo --open      # демо-данные и открыть в браузере
    python scripts/shop_analytics.py --months 6 --out report.html
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "diamond.db"
DEFAULT_OUT = ROOT / "data" / "reports" / "shop_report.html"
DEMO_OUT = ROOT / "data" / "reports" / "shop_report_demo.html"

MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_FULL_RU = ["январь", "февраль", "март", "апрель", "май", "июнь",
                  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


# ============================================================
# ФОРМАТИРОВАНИЕ
# ============================================================
def money(value: float, sign: bool = False) -> str:
    """1 234 ₽"""
    v = float(value or 0)
    prefix = "+" if sign and v > 0 else ""
    return f"{prefix}{_group(int(round(v)))} ₽"


def compact(value: float) -> str:
    """12,4 тыс ₽"""
    v = float(value or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",") + " млн ₽"
    if abs(v) >= 10_000:
        return f"{v / 1_000:.1f}".replace(".", ",") + " тыс ₽"
    return money(v)


def _group(n: int) -> str:
    return f"{n:,}".replace(",", "\u202f")


def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def mmoney(value: float) -> str:
    """Компактно для подписей на графиках."""
    v = float(value or 0)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}м".replace(".", ",")
    if abs(v) >= 1_000:
        return f"{v / 1_000:.0f}к"
    return str(int(round(v)))


def esc(text) -> str:
    return (str(text)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# ============================================================
# ДАТЫ
# ============================================================
def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_shift(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def month_sequence(end: date, count: int) -> List[date]:
    end = date(end.year, end.month, 1)
    return [month_shift(end, -(count - 1 - i)) for i in range(count)]


# ============================================================
# МОДЕЛЬ ДАННЫХ
# ============================================================
@dataclass
class Order:
    user_id: int
    amount: float
    items: List[str]
    ts: int
    paid: bool
    source: str = "ai"          # ai | import | demo
    key: str = ""               # уникальный ключ, чтобы не задваивать


@dataclass
class TicketMonth:
    key: str
    label: str
    opened: int = 0
    closed: int = 0
    purchased: int = 0   # старые покупки из dc_cache.purchases


@dataclass
class MonthStat:
    key: str
    label: str
    revenue: float = 0.0
    orders: int = 0
    issued: int = 0
    buyers: int = 0
    new_buyers: int = 0
    returning: int = 0
    churned: int = 0
    items: int = 0

    @property
    def avg_cheque(self) -> float:
        return self.revenue / self.orders if self.orders else 0.0

    @property
    def avg_item_price(self) -> float:
        return self.revenue / self.items if self.items else 0.0

    @property
    def net(self) -> int:
        return self.new_buyers - self.churned


@dataclass
class ItemStat:
    name: str
    orders: int = 0
    units: int = 0
    revenue: float = 0.0
    first_price: float = 0.0
    last_price: float = 0.0

    @property
    def change(self) -> float:
        if self.first_price <= 0:
            return 0.0
        return self.last_price / self.first_price - 1


@dataclass
class Report:
    path: str
    html: str
    summary: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def warning(self) -> str:
        return "; ".join(self.warnings)

    def as_text(self) -> str:
        s = self.summary
        parts = []
        if s.get("orders"):
            parts.append(
                f"Выручка: {money(s['revenue'])} · заказов: {int(s['orders'])} · "
                f"средний чек: {money(s['avg_cheque'])} · покупателей: {int(s['buyers'])}"
            )
        else:
            parts.append("Оплаченных счетов пока нет — данные собраны из БД.")
        if s.get("imported_orders"):
            parts.append(f"Старых заказов (импорт): {int(s['imported_orders'])} на {money(s['imported_revenue'])}")
        if s.get("tickets_closed_total") or s.get("old_purchases"):
            parts.append(
                f"Тикетов закрыто: {int(s['tickets_closed_total'])} · открыто сейчас: "
                f"{int(s.get('tickets_open_now', 0))} · старых покупок: {int(s.get('old_purchases', 0))}"
            )
        return "\n".join(parts)


# ============================================================
# ЗАГРУЗКА
# ============================================================
def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=15)


def parse_items(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [chunk.strip() for chunk in str(raw).replace(";", ",").split(",") if chunk.strip()]


def table_columns(conn: sqlite3.Connection, table: str) -> set:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


SNOWFLAKE_EPOCH_MS = 1420070400000


def snowflake_ts(value) -> int:
    """Время создания Discord-канала/сообщения по snowflake ID."""
    try:
        return ((int(value) >> 22) + SNOWFLAKE_EPOCH_MS) // 1000
    except Exception:
        return 0


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def load_ai_orders(conn: sqlite3.Connection, warnings: List[str]) -> List[Order]:
    cols = table_columns(conn, "ai_manager_sessions")
    if not cols:
        warnings.append("Нет таблицы ai_manager_sessions — новые счета AI-менеджера не учтены.")
        return []
    if not {"invoice_amount", "invoice_created_at"} <= cols:
        warnings.append("В ai_manager_sessions нет invoice_amount/invoice_created_at — "
                        "счета AI-менеджера не учтены (обновите ai_manager.py).")
        return []

    items_expr = "COALESCE(invoice_items, '')" if "invoice_items" in cols else "''"
    receipt_expr = "COALESCE(receipt_url, '')" if "receipt_url" in cols else "''"
    has_sent = "invoice_sent" in cols
    sent_expr = "COALESCE(invoice_sent, 0)" if has_sent else "0"

    try:
        rows = conn.execute(f"""
            SELECT user_id, invoice_amount, {items_expr}, invoice_created_at,
                   {receipt_expr}, {sent_expr}
            FROM ai_manager_sessions
            WHERE invoice_amount > 0 AND invoice_created_at > 0
            ORDER BY invoice_created_at
        """).fetchall()
    except Exception as exc:
        warnings.append(f"Не удалось прочитать счета AI-менеджера: {exc}")
        return []

    now = int(datetime.now().timestamp())
    orders: List[Order] = []
    for user_id, amount, items, ts, receipt, sent in rows:
        amount = float(amount or 0)
        ts = _safe_int(ts)
        if amount <= 0 or ts <= 0 or ts > now + 86400:
            continue
        paid = bool((receipt or "").strip())
        # invoice_sent=1 значит выставлен новый счёт: старый чек к нему уже не относится
        if has_sent and sent:
            paid = False
        orders.append(Order(
            user_id=_safe_int(user_id),
            amount=amount,
            items=parse_items(items),
            ts=ts,
            paid=paid,
            source="ai",
            key=f"ai:{user_id}:{ts}:{amount:.0f}",
        ))
    return orders


def load_imported_orders(conn: sqlite3.Connection, warnings: List[str]) -> List[Order]:
    """Старые продажи, импортированные из логов Discord (таблица shop_sales)."""
    cols = table_columns(conn, "shop_sales")
    if not cols:
        return []

    buyer_map: Dict[int, int] = {}
    for table in ("ticket_reviews", "ticket_owners"):
        if not table_columns(conn, table):
            continue
        try:
            for channel_id, user_id in conn.execute(f"SELECT channel_id, user_id FROM {table}"):
                if channel_id and user_id:
                    buyer_map.setdefault(int(channel_id), int(user_id))
        except Exception:
            pass

    try:
        rows = conn.execute("""
            SELECT id, external_id, channel_id, user_id, amount, items, created_at
            FROM shop_sales
            WHERE amount > 0 AND created_at > 0
            ORDER BY created_at
        """).fetchall()
    except Exception as exc:
        warnings.append(f"Не удалось прочитать shop_sales: {exc}")
        return []

    now = int(datetime.now().timestamp())
    orders: List[Order] = []
    for row_id, external_id, channel_id, user_id, amount, items, ts in rows:
        ts = _safe_int(ts)
        amount = float(amount or 0)
        if amount <= 0 or ts <= 0 or ts > now + 86400:
            continue
        channel_id = _safe_int(channel_id)
        buyer = _safe_int(user_id) or buyer_map.get(channel_id) or -abs(channel_id or row_id)
        orders.append(Order(
            user_id=buyer,
            amount=amount,
            items=parse_items(items),
            ts=ts,
            paid=True,
            source="import",
            key=f"import:{external_id or row_id}",
        ))
    return orders


def load_ticket_stats(conn: sqlite3.Connection, months: int,
                      today: Optional[date], warnings: List[str]) -> dict:
    """Открытые/закрытые тикеты по месяцам из closed_orders и ticket_owners."""
    today = today or date.today()
    grid = month_sequence(today, months)
    keys = [month_key(m) for m in grid]
    index = {k: i for i, k in enumerate(keys)}
    stats = {k: TicketMonth(key=k, label=MONTHS_RU[grid[i].month - 1]) for i, k in enumerate(keys)}

    opened = 0
    hours_sum = 0.0
    hours_n = 0
    closed_total = 0
    first_ts = 0
    last_ts = 0

    cols = table_columns(conn, "closed_orders")
    if cols and {"channel_id", "closed_at"} <= cols:
        try:
            rows = conn.execute(
                "SELECT channel_id, closed_at FROM closed_orders WHERE closed_at > 0"
            ).fetchall()
        except Exception as exc:
            rows = []
            warnings.append(f"Не удалось прочитать closed_orders: {exc}")

        for channel_id, closed_at in rows:
            closed_at = _safe_int(closed_at)
            if closed_at <= 0:
                continue
            closed_total += 1
            created = snowflake_ts(channel_id)
            ck = month_key(datetime.fromtimestamp(closed_at).date())
            if ck in index:
                stats[ck].closed += 1
            if created > 0:
                opened += 1
                first_ts = min(first_ts or created, created)
                last_ts = max(last_ts, created)
                ok = month_key(datetime.fromtimestamp(created).date())
                if ok in index:
                    stats[ok].opened += 1
                lifetime = closed_at - created
                if 0 < lifetime < 90 * 86400:
                    hours_sum += lifetime / 3600
                    hours_n += 1

    open_now = 0
    if table_columns(conn, "ticket_owners"):
        try:
            open_now = int(conn.execute("SELECT COUNT(*) FROM ticket_owners").fetchone()[0] or 0)
        except Exception:
            pass

    # старые оплаты AI-менеджера: чек есть, суммы в БД уже нет
    old_bought = 0
    ai_cols = table_columns(conn, "ai_manager_sessions")
    if ai_cols and {"receipt_url", "created_at"} <= ai_cols:
        ts_col = "invoice_created_at" if "invoice_created_at" in ai_cols else "created_at"
        amount_filter = ("AND COALESCE(invoice_amount, 0) = 0"
                         if "invoice_amount" in ai_cols else "")
        try:
            rows = conn.execute(
                f"SELECT {ts_col} FROM ai_manager_sessions "
                f"WHERE receipt_url IS NOT NULL AND receipt_url != '' {amount_filter}"
            ).fetchall()
            for (ts_val,) in rows:
                ts = _safe_int(ts_val)
                if ts <= 0:
                    continue
                rk = month_key(datetime.fromtimestamp(ts).date())
                if rk in index:
                    stats[rk].purchased += 1
                    old_bought += 1
        except Exception as exc:
            warnings.append(f"Не удалось прочитать старые чеки AI: {exc}")

    # старые покупки из dc_cache.purchases (до появления AI-менеджера)
    if table_columns(conn, "dc_cache"):
        try:
            for (raw,) in conn.execute("SELECT purchases FROM dc_cache"):
                if not raw:
                    continue
                try:
                    items = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(items, list):
                    continue
                for p in items:
                    if not isinstance(p, dict):
                        continue
                    ts = _safe_int(p.get("date"))
                    if ts <= 0:
                        continue
                    pk = month_key(datetime.fromtimestamp(ts).date())
                    if pk in index:
                        stats[pk].purchased += 1
                        old_bought += 1
        except Exception as exc:
            warnings.append(f"Не удалось прочитать старые покупки: {exc}")

    return {
        "stats": [stats[k] for k in keys],
        "open_now": open_now,
        "avg_hours": hours_sum / hours_n if hours_n else 0.0,
        "closed_total": closed_total,
        "opened_total": opened,
        "old_purchases": old_bought,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def load_data(db_path: Path, months: int = 12) -> Tuple[List[Order], dict, List[str], dict]:
    """Читает все источники. Никогда не бросает исключение наружу."""
    warnings: List[str] = []
    info: dict = {"db": str(db_path), "tables": {}, "ai_paid": 0, "imported": 0}
    tickets: dict = {"stats": [], "open_now": 0, "avg_hours": 0.0, "closed_total": 0,
                     "opened_total": 0, "first_ts": 0, "last_ts": 0}

    if not db_path.exists():
        warnings.append(f"База не найдена: {db_path}")
        return [], tickets, warnings, info

    try:
        conn = connect_readonly(db_path)
    except Exception as exc:
        warnings.append(f"Не удалось открыть базу: {exc}")
        return [], tickets, warnings, info

    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        info["tables"] = {t: _safe_int(conn.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0])
                          for t in tables}
        info["columns"] = {t: sorted(table_columns(conn, t))
                           for t in ("ai_manager_sessions", "shop_sales", "closed_orders",
                                     "ticket_owners", "ticket_reviews")
                           if t in tables}

        ai_orders = load_ai_orders(conn, warnings)
        imported = load_imported_orders(conn, warnings)
        tickets = load_ticket_stats(conn, months, None, warnings)
    except Exception as exc:
        warnings.append(f"Ошибка чтения базы: {exc}")
        ai_orders, imported = [], []
    finally:
        conn.close()

    orders = ai_orders + imported
    info["ai_paid"] = sum(1 for o in ai_orders if o.paid)
    info["imported"] = len(imported)
    info["revenue"] = sum(o.amount for o in orders if o.paid)
    info["range"] = (
        datetime.fromtimestamp(min(o.ts for o in orders)).strftime("%d.%m.%Y")
        if orders else "—",
        datetime.fromtimestamp(max(o.ts for o in orders)).strftime("%d.%m.%Y")
        if orders else "—",
    )
    return orders, tickets, warnings, info


def load_orders(db_path: Path) -> Tuple[List[Order], str]:
    """Совместимость: только заказы + строка предупреждений."""
    orders, _, warnings, _ = load_data(db_path)
    return orders, "; ".join(warnings)


# ============================================================
# АГРЕГАЦИЯ
# ============================================================
def aggregate(orders: Sequence[Order], months: int, today: Optional[date] = None,
              tickets: Optional[dict] = None):
    today = today or date.today()
    grid = month_sequence(today, months)
    keys = [month_key(m) for m in grid]
    index = {k: i for i, k in enumerate(keys)}

    paid = [o for o in orders if o.paid]
    seen_keys = set()
    unique_paid: List[Order] = []
    for o in paid:
        if o.key and o.key in seen_keys:
            continue
        if o.key:
            seen_keys.add(o.key)
        unique_paid.append(o)
    paid = unique_paid

    first_seen: Dict[int, str] = {}
    for o in sorted(paid, key=lambda x: x.ts):
        k = month_key(datetime.fromtimestamp(o.ts).date())
        first_seen.setdefault(o.user_id, k)

    stats = {k: MonthStat(key=k, label=MONTHS_RU[grid[i].month - 1]) for i, k in enumerate(keys)}
    buyers_by_month: Dict[str, set] = {k: set() for k in keys}
    items_by_month: Dict[str, Dict[str, List[float]]] = {k: {} for k in keys}

    for o in orders:
        k = month_key(datetime.fromtimestamp(o.ts).date())
        if k not in index:
            continue
        if o.paid:
            st = stats[k]
            st.orders += 1
            st.revenue += o.amount
            st.items += max(1, len(o.items))
            buyers_by_month[k].add(o.user_id)
            line_price = o.amount / max(1, len(o.items))
            for name in o.items:
                items_by_month[k].setdefault(name, []).append(line_price)
        st = stats[k]
        st.issued += 1

    # покупатели, новые/возвращающиеся, отток
    for k in keys:
        st = stats[k]
        buyers = buyers_by_month[k]
        st.buyers = len(buyers)
        st.new_buyers = sum(1 for u in buyers if first_seen.get(u) == k)
        st.returning = st.buyers - st.new_buyers
    for i, k in enumerate(keys):
        if i == 0:
            continue
        prev = buyers_by_month[keys[i - 1]]
        st = stats[k]
        st.churned = sum(1 for u in prev if u not in buyers_by_month[k] and first_seen.get(u) != k)

    # позиции: средняя цена в первой и второй половине периода
    half = max(1, len(keys) // 2)
    early_keys = set(keys[:half])
    late_keys = set(keys[half:])
    items: Dict[str, ItemStat] = {}
    early_sum: Dict[str, List[float]] = {}
    late_sum: Dict[str, List[float]] = {}
    for k in keys:
        for name, prices in items_by_month[k].items():
            it = items.setdefault(name, ItemStat(name=name))
            it.orders += len(prices)
            it.units += len(prices)
            it.revenue += sum(prices)
            target = early_sum if k in early_keys else (late_sum if k in late_keys else None)
            if target is not None:
                acc = target.setdefault(name, [0.0, 0])
                acc[0] += sum(prices)
                acc[1] += len(prices)
    for name, it in items.items():
        e = early_sum.get(name)
        l = late_sum.get(name)
        if e and e[1]:
            it.first_price = e[0] / e[1]
        if l and l[1]:
            it.last_price = l[0] / l[1]

    # дневная активность для heatmap
    days: Dict[date, List[float]] = {}
    for o in paid:
        d = datetime.fromtimestamp(o.ts).date()
        if d >= today - timedelta(days=364):
            bucket = days.setdefault(d, [0, 0.0])
            bucket[0] += 1
            bucket[1] += o.amount

    total_revenue = sum(st.revenue for st in stats.values())
    total_orders = sum(st.orders for st in stats.values())
    total_buyers = len({o.user_id for o in paid
                        if month_key(datetime.fromtimestamp(o.ts).date()) in index})
    total_issued = sum(st.issued for st in stats.values())
    repeat_buyers = 0
    per_user: Dict[int, int] = {}
    for o in paid:
        if month_key(datetime.fromtimestamp(o.ts).date()) in index:
            per_user[o.user_id] = per_user.get(o.user_id, 0) + 1
    if per_user:
        repeat_buyers = sum(1 for n in per_user.values() if n >= 2)

    prev_month_revenue = stats[keys[-2]].revenue if len(keys) >= 2 else 0
    growth = (stats[keys[-1]].revenue / prev_month_revenue - 1) if prev_month_revenue else 0.0

    imported_orders = sum(1 for o in paid if getattr(o, "source", "") == "import"
                          and month_key(datetime.fromtimestamp(o.ts).date()) in index)
    imported_revenue = sum(o.amount for o in paid if getattr(o, "source", "") == "import"
                           and month_key(datetime.fromtimestamp(o.ts).date()) in index)
    ai_orders = sum(1 for o in paid if getattr(o, "source", "") == "ai"
                    and month_key(datetime.fromtimestamp(o.ts).date()) in index)

    tickets = tickets or {}
    ticket_stats = tickets.get("stats") or []
    # подрезаем тикеты под выбранный период
    ticket_by_key = {getattr(t, "key", ""): t for t in ticket_stats}
    ticket_months = [ticket_by_key.get(k, TicketMonth(key=k, label=MONTHS_RU[grid[i].month - 1]))
                     for i, k in enumerate(keys)]

    summary = {
        "revenue": total_revenue,
        "orders": total_orders,
        "avg_cheque": total_revenue / total_orders if total_orders else 0.0,
        "buyers": total_buyers,
        "repeat_rate": repeat_buyers / total_buyers if total_buyers else 0.0,
        "conversion": total_orders / total_issued if total_issued else 0.0,
        "growth": growth,
        "items_per_order": (sum(st.items for st in stats.values()) / total_orders) if total_orders else 0.0,
        "imported_orders": imported_orders,
        "imported_revenue": imported_revenue,
        "ai_orders": ai_orders,
        "tickets_open_now": int(tickets.get("open_now", 0) or 0),
        "tickets_closed_total": int(tickets.get("closed_total", 0) or 0),
        "tickets_opened_total": int(tickets.get("opened_total", 0) or 0),
        "tickets_avg_hours": float(tickets.get("avg_hours", 0.0) or 0.0),
        "old_purchases": int(tickets.get("old_purchases", 0) or 0),
    }

    return {
        "stats": [stats[k] for k in keys],
        "items": sorted(items.values(), key=lambda x: x.revenue, reverse=True),
        "days": days,
        "summary": summary,
        "grid": grid,
        "today": today,
        "tickets": ticket_months,
        "ticket_info": tickets,
    }


# ============================================================
# SVG-ГРАФИКИ
# ============================================================
C_ACCENT = "#7c5cff"
C_GREEN = "#38d39f"
C_RED = "#ff5c7a"
C_GOLD = "#f2c14e"
C_GRID = "rgba(255,255,255,.07)"
C_TEXT = "#9aa3b8"


def _nice_max(value: float) -> float:
    value = float(value or 0)
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = 10 ** exp
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        if value <= m * base:
            return m * base
    return 10 * base


def _svg(width: int, height: int, body: str) -> str:
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" '
            f'role="img" xmlns="http://www.w3.org/2000/svg">{body}</svg>')


def bar_chart(points: Sequence[Tuple[str, float]], *, color: str = C_ACCENT,
              height: int = 250, fmt=money, show_values: bool = True,
              value_color: str = "#e7e9ee", w: int = 860) -> str:
    """Вертикальные столбцы с подписями месяцев."""
    left, right, top, bottom = 54, 14, 22, 34
    plot_w, plot_h = w - left - right, height - top - bottom
    maxv = _nice_max(max((v for _, v in points), default=0))
    step = plot_w / max(1, len(points))
    bw = min(46, step * 0.62)

    body = []
    for i in range(5):
        y = top + plot_h - plot_h * i / 4
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{C_GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                    f'fill="{C_TEXT}">{mmoney(maxv * i / 4)}</text>')

    for i, (label, value) in enumerate(points):
        cx = left + step * (i + 0.5)
        h = plot_h * (value / maxv) if maxv else 0
        y = top + plot_h - h
        body.append(f'<rect x="{cx - bw / 2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(h, 0):.1f}" '
                    f'rx="3" fill="{color}" opacity=".9"><title>{esc(label)}: {esc(fmt(value))}</title></rect>')
        body.append(f'<text x="{cx:.1f}" y="{height - 12}" text-anchor="middle" font-size="11" '
                    f'fill="{C_TEXT}">{esc(label)}</text>')
        if show_values and value > 0:
            body.append(f'<text x="{cx:.1f}" y="{y - 7:.1f}" text-anchor="middle" font-size="10.5" '
                        f'fill="{value_color}">{esc(mmoney(value))}</text>')

    return _svg(w, height, "".join(body))


def line_chart(series: Sequence[Tuple[str, Sequence[float], str]],
               labels: Sequence[str], *, height: int = 250,
               fmt=money, area: bool = True, w: int = 860) -> str:
    """Несколько линий. series = [(имя, значения, цвет)]."""
    left, right, top, bottom = 54, 16, 22, 34
    plot_w, plot_h = w - left - right, height - top - bottom
    maxv = _nice_max(max((max(vals) if vals else 0) for _, vals, _ in series))
    n = max(1, len(labels))
    step = plot_w / max(1, n - 1) if n > 1 else plot_w

    body = []
    for i in range(5):
        y = top + plot_h - plot_h * i / 4
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{C_GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                    f'fill="{C_TEXT}">{mmoney(maxv * i / 4)}</text>')

    def px(i): return left + step * i
    def py(v): return top + plot_h - plot_h * (v / maxv if maxv else 0)

    for name, values, color in series:
        pts = [(px(i), py(v)) for i, v in enumerate(values)]
        if not pts:
            continue
        if area and len(pts) > 1:
            path = (f"M {pts[0][0]:.1f} {top + plot_h:.1f} "
                    + " ".join(f"L {x:.1f} {y:.1f}" for x, y in pts)
                    + f" L {pts[-1][0]:.1f} {top + plot_h:.1f} Z")
            body.append(f'<path d="{path}" fill="{color}" opacity=".10"/>')
        body.append('<polyline fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round" '
                    'points="%s"/>' % (color, " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)))
        for i, (x, y) in enumerate(pts):
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}">'
                        f'<title>{esc(name)} · {esc(labels[i])}: {esc(fmt(values[i]))}</title></circle>')

    for i, label in enumerate(labels):
        body.append(f'<text x="{px(i):.1f}" y="{height - 12}" text-anchor="middle" font-size="11" '
                    f'fill="{C_TEXT}">{esc(label)}</text>')
    return _svg(w, height, "".join(body))


def grouped_bars(points: Sequence[Tuple[str, float, float]],
                 *, color_a: str = C_ACCENT, color_b: str = C_GREEN,
                 name_a: str = "A", name_b: str = "B", height: int = 250,
                 w: int = 860) -> str:
    left, right, top, bottom = 54, 16, 22, 34
    plot_w, plot_h = w - left - right, height - top - bottom
    maxv = _nice_max(max((max(a, b) for _, a, b in points), default=0))
    step = plot_w / max(1, len(points))
    bw = min(18, step * 0.3)

    body = []
    for i in range(5):
        y = top + plot_h - plot_h * i / 4
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{C_GRID}"/>')
        body.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
                    f'fill="{C_TEXT}">{mmoney(maxv * i / 4)}</text>')
    for i, (label, a, b) in enumerate(points):
        cx = left + step * (i + 0.5)
        for value, color, dx, name in ((a, color_a, -bw - 1, name_a), (b, color_b, 1, name_b)):
            h = plot_h * (value / maxv) if maxv else 0
            body.append(f'<rect x="{cx + dx:.1f}" y="{top + plot_h - h:.1f}" width="{bw:.1f}" '
                        f'height="{max(h, 0):.1f}" rx="2" fill="{color}" opacity=".9">'
                        f'<title>{esc(name)} · {esc(label)}: {int(value)}</title></rect>')
        body.append(f'<text x="{cx:.1f}" y="{height - 12}" text-anchor="middle" font-size="11" '
                    f'fill="{C_TEXT}">{esc(label)}</text>')
    return _svg(w, height, "".join(body))


def diverging_bars(points: Sequence[Tuple[str, float, float]], height: int = 250,
                   w: int = 860) -> str:
    """Приток (вверх, зелёный) / отток (вниз, красный)."""
    left, right, top, bottom = 54, 16, 22, 34
    plot_w, plot_h = w - left - right, height - top - bottom
    maxv = _nice_max(max((max(a, b) for _, a, b in points), default=0))
    zero = top + plot_h / 2
    step = plot_w / max(1, len(points))
    bw = min(26, step * 0.5)

    body = [f'<line x1="{left}" y1="{zero:.1f}" x2="{w - right}" y2="{zero:.1f}" stroke="{C_GRID}"/>']
    for i, (label, inflow, outflow) in enumerate(points):
        cx = left + step * (i + 0.5)
        for value, color, sign in ((inflow, C_GREEN, 1), (outflow, C_RED, -1)):
            h = (plot_h / 2) * (value / maxv) if maxv else 0
            body.append(f'<rect x="{cx - bw / 2:.1f}" y="{(zero - h) if sign > 0 else zero:.1f}" '
                        f'width="{bw:.1f}" height="{max(h, 0):.1f}" rx="2" fill="{color}" opacity=".85">'
                        f'<title>{esc(label)}: {"+" if sign > 0 else "−"}{int(value)}</title></rect>')
        body.append(f'<text x="{cx:.1f}" y="{height - 12}" text-anchor="middle" font-size="11" '
                    f'fill="{C_TEXT}">{esc(label)}</text>')
    return _svg(w, height, "".join(body))


def heatmap(days: Dict[date, List[float]], today: date) -> str:
    """GitHub-style календарь за 53 недели."""
    cell, gap = 12, 3
    left, top = 30, 26
    start = today - timedelta(days=364)
    start -= timedelta(days=start.weekday())
    weeks = math.ceil(((today - start).days + 1) / 7)
    w = left + weeks * (cell + gap) + 10
    h = top + 7 * (cell + gap) + 26

    levels = [("#161b26", "нет заказов"),
              ("#2c2a5e", "1 заказ"),
              ("#4b3ea8", "2 заказа"),
              ("#6f56ff", "3–4 заказа"),
              ("#a394ff", "5+ заказов")]

    body = []
    last_month = None
    for week in range(weeks):
        for wd in range(7):
            d = start + timedelta(days=week * 7 + wd)
            if d > today:
                continue
            x = left + week * (cell + gap)
            y = top + wd * (cell + gap)
            count, revenue = (days.get(d) or [0, 0.0])[:2]
            if count >= 5:
                lvl = 4
            elif count >= 3:
                lvl = 3
            elif count == 2:
                lvl = 2
            elif count == 1:
                lvl = 1
            else:
                lvl = 0
            body.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" '
                        f'fill="{levels[lvl][0]}"><title>{d.strftime("%d.%m.%Y")}: '
                        f'{int(count)} заказ(ов), {money(revenue)}</title></rect>')
        label_date = start + timedelta(days=week * 7)
        if label_date.month != last_month and label_date.day <= 7:
            last_month = label_date.month
            body.append(f'<text x="{left + week * (cell + gap)}" y="{top - 8}" font-size="10" '
                        f'fill="{C_TEXT}">{MONTHS_RU[label_date.month - 1]}</text>')

    for wd, name in ((0, "Пн"), (2, "Ср"), (4, "Пт")):
        body.append(f'<text x="{left - 6}" y="{top + wd * (cell + gap) + 10}" text-anchor="end" '
                    f'font-size="9.5" fill="{C_TEXT}">{name}</text>')

    legend_x = w - 10 - 5 * (cell + gap) - 92
    body.append(f'<text x="{legend_x - 8}" y="{top + 7 * (cell + gap) + 14}" text-anchor="end" '
                f'font-size="10" fill="{C_TEXT}">меньше</text>')
    for i, (color, _) in enumerate(levels):
        body.append(f'<rect x="{legend_x + i * (cell + gap)}" y="{top + 7 * (cell + gap) + 4}" '
                    f'width="{cell}" height="{cell}" rx="2.5" fill="{color}"/>')
    body.append(f'<text x="{legend_x + 5 * (cell + gap) + 6}" y="{top + 7 * (cell + gap) + 14}" '
                f'font-size="10" fill="{C_TEXT}">больше</text>')
    return _svg(w, h, "".join(body))


# ============================================================
# ВЁРСТКА
# ============================================================
CSS = """
:root{
  --bg:#0a0c12; --card:#12161f; --card2:#161b26; --line:rgba(255,255,255,.07);
  --text:#e8eaf0; --muted:#9aa3b8; --accent:#7c5cff; --green:#38d39f;
  --red:#ff5c7a; --gold:#f2c14e;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#1a1640 0%,transparent 60%),var(--bg);
  color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 48px}
header{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:12px;margin-bottom:24px}
h1{margin:0;font-size:26px;letter-spacing:-.02em}
h1 span{color:var(--accent)}
.sub{color:var(--muted);font-size:12.5px;margin-top:6px}
.badge{display:inline-flex;align-items:center;gap:7px;padding:7px 12px;border:1px solid var(--line);
  border-radius:999px;background:rgba(124,92,255,.08);color:#cfc6ff;font-size:12px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 10px var(--green)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin-bottom:14px}
.kpi{background:linear-gradient(180deg,rgba(255,255,255,.03),transparent),var(--card);
  border:1px solid var(--line);border-radius:14px;padding:14px 15px 10px}
.kpi .label{font-size:11.5px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.kpi .value{font-size:23px;font-weight:650;margin-top:6px;letter-spacing:-.02em}
.kpi .hint{font-size:11.5px;color:var(--muted);margin-top:2px}
.up{color:var(--green)} .down{color:var(--red)} .neu{color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 16px 10px;margin-bottom:14px}
.card h2{margin:0 0 2px;font-size:14.5px;font-weight:600}
.card .cap{color:var(--muted);font-size:11.5px;margin-bottom:10px}
.card.wide{grid-column:1/-1}
.chart{width:100%;height:auto;display:block}
.spark{width:100%;height:34px;display:block;opacity:.75}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:11.5px;margin:2px 0 8px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px;vertical-align:1px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;
  letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid rgba(255,255,255,.04)}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{height:6px;border-radius:99px;background:var(--accent);opacity:.8;min-width:3px}
.empty{padding:34px 10px;text-align:center;color:var(--muted)}
.note{color:var(--muted);font-size:11.5px;line-height:1.6;margin-top:6px}
footer{color:var(--muted);font-size:11px;margin-top:26px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
@media(max-width:820px){.grid{grid-template-columns:1fr}h1{font-size:21px}}
"""


def _kpi(label: str, value: str, hint: str = "", cls: str = "") -> str:
    hint_html = f'<div class="hint {cls}">{hint}</div>' if hint else ""
    return (f'<div class="kpi"><div class="label">{esc(label)}</div>'
            f'<div class="value">{esc(value)}</div>{hint_html}</div>')


def _sign_cls(value: float) -> str:
    return "up" if value > 0 else ("down" if value < 0 else "neu")


def _arrow(value: float) -> str:
    return "▲" if value > 0 else ("▼" if value < 0 else "•")


def _fmt_hours(h: float) -> str:
    if h <= 0:
        return "—"
    if h < 24:
        return f"{h:.1f}".replace(".", ",") + " ч"
    d = h / 24
    return f"{d:.1f}".replace(".", ",") + " дн"


def render_html(data: dict, months: int, source_note: str,
                warnings: Optional[List[str]] = None, info: Optional[dict] = None) -> str:
    warnings = list(warnings or [])
    if isinstance(warnings, str):  # совместимость
        warnings = [warnings] if warnings else []
    warning = "; ".join(w for w in warnings if w)
    info = info or {}
    stats: List[MonthStat] = data["stats"]
    summary = data["summary"]
    items: List[ItemStat] = data["items"]
    labels = [s.label for s in stats]

    revenue_vals = [s.revenue for s in stats]
    order_vals = [float(s.orders) for s in stats]
    buyer_vals = [float(s.buyers) for s in stats]
    cheque_vals = [s.avg_cheque for s in stats]
    price_vals = [s.avg_item_price for s in stats]
    inflow_vals = [float(s.new_buyers) for s in stats]
    outflow_vals = [float(s.churned) for s in stats]

    price_index = []
    base_price = next((p for p in price_vals if p > 0), 0)
    for p in price_vals:
        price_index.append(p / base_price * 100 if base_price and p else 0)

    # KPI
    kpis = [
        _kpi("Выручка", money(summary["revenue"]),
             f'{_arrow(summary["growth"])} {abs(summary["growth"]) * 100:.0f}% к прошлому месяцу'
             if summary["growth"] else "за период", _sign_cls(summary["growth"])),
        _kpi("Заказов", _group(int(summary["orders"])),
             f'конверсия счетов {pct(summary["conversion"])}'),
        _kpi("Средний чек", money(summary["avg_cheque"]),
             f'{str(round(summary["items_per_order"], 1)).replace(".", ",")} позиции в заказе'),
        _kpi("Покупателей", _group(int(summary["buyers"])),
             f'повторных {pct(summary["repeat_rate"])}'),
        _kpi("Последний месяц", money(stats[-1].revenue) if stats else "—",
             f"{stats[-1].orders if stats else 0} заказов · чек {money(stats[-1].avg_cheque) if stats else '—'}"),
        _kpi("Цена позиции", money(stats[-1].avg_item_price) if stats else "—",
             "средняя по счетам"),
        _kpi("Закрыто тикетов", _group(int(summary.get("tickets_closed_total", 0))),
              f'открыто сейчас: {int(summary.get("tickets_open_now", 0))}'),
        _kpi("Старых покупок", _group(int(summary.get("old_purchases", 0))),
              "из dc_cache.purchases"),
    ]

    # тепловая карта
    heat = heatmap(data["days"], data["today"])
    total_paid_days = len([1 for v in data["days"].values() if v[0] > 0])
    heat_note = (f"За год: {sum(int(v[0]) for v in data['days'].values())} заказов "
                 f"в {total_paid_days} днях. Наведите курсор на клетку — дата, число заказов и сумма.")

    # таблица позиций
    max_item_rev = max((it.revenue for it in items), default=0) or 1
    rows = []
    for it in items[:12]:
        try:
            change = it.change
            change_html = (f'<span class="{_sign_cls(change)}">{_arrow(change)} {abs(change) * 100:.0f}%</span>'
                           if it.first_price and it.last_price else '<span class="neu">—</span>')
            rows.append(
                f'<tr><td>{esc(it.name)}</td>'
                f'<td class="num">{it.orders}</td>'
                f'<td class="num">{money(it.revenue)}</td>'
                f'<td class="num">{money(it.revenue / it.orders) if it.orders else "—"}</td>'
                f'<td class="num">{change_html}</td>'
                f'<td style="width:120px"><div class="bar" style="width:{it.revenue / max_item_rev * 100:.0f}%">'
                f'</div></td></tr>'
            )
        except Exception:
            continue
    items_table = ("".join(rows) if rows else
                   '<tr><td colspan="6" class="empty">Нет данных по позициям</td></tr>')

    # тикеты и старые покупки
    ticket_months = data.get("tickets") or []
    t_labels = [t.label for t in ticket_months]
    t_opened = [float(t.opened) for t in ticket_months]
    t_closed = [float(t.closed) for t in ticket_months]
    t_purchased = [float(t.purchased) for t in ticket_months]
    t_any = any(t_opened) or any(t_closed) or any(t_purchased)
    ticket_chart = ""
    if t_any:
        ticket_rows = "".join(
            f'<tr><td>{MONTHS_FULL_RU[int(tm.key[5:7]) - 1]} {tm.key[:4]}</td>'
            f'<td class="num">{tm.opened}</td>'
            f'<td class="num">{tm.closed}</td>'
            f'<td class="num">{tm.purchased}</td></tr>'
            for tm in reversed(ticket_months)
        )
        ticket_chart = f"""<div class="card">
    <h2>Тикеты и старые покупки</h2>
    <div class="cap">Данные из БД: закрытые заказы, открытые тикеты и покупки до AI-менеджера.
    Среднее время закрытия: {_fmt_hours(summary.get("tickets_avg_hours", 0))} ·
    открыто сейчас: <b>{int(summary.get("tickets_open_now", 0))}</b></div>
    <div class="legend">
      <span><i style="background:{C_ACCENT}"></i>открыто тикетов</span>
      <span><i style="background:{C_GREEN}"></i>закрыто тикетов</span>
      <span><i style="background:{C_GOLD}"></i>старых покупок</span>
    </div>
    {grouped_bars(list(zip(t_labels, t_opened, t_closed)),
                  name_a="Открыто", name_b="Закрыто", color_a=C_ACCENT, color_b=C_GREEN)}
    <div class="note">Старых покупок за период: <b>{int(summary.get("old_purchases", 0))}</b>
    (старые чеки AI и покупки из dc_cache; сумма не сохранялась). Закрыто тикетов всего: <b>{int(summary.get("tickets_closed_total", 0))}</b>.</div>
    <table style="margin-top:10px">
      <thead><tr><th>Месяц</th><th class="num">Открыто тикетов</th>
      <th class="num">Закрыто тикетов</th><th class="num">Старых покупок</th></tr></thead>
      <tbody>{ticket_rows}</tbody>
    </table>
  </div>"""

    # месячная таблица
    month_rows = []
    for s in reversed(stats):
        month_rows.append(
            f'<tr><td>{MONTHS_FULL_RU[int(s.key[5:7]) - 1]} {s.key[:4]}</td>'
            f'<td class="num">{money(s.revenue)}</td>'
            f'<td class="num">{s.orders}</td>'
            f'<td class="num">{s.buyers}</td>'
            f'<td class="num">{money(s.avg_cheque)}</td>'
            f'<td class="num"><span class="{_sign_cls(s.net)}">{s.net:+d}</span></td></tr>'
        )

    if not summary["orders"] and not warning:
        empty_note = ('<div class="card"><div class="empty">Оплаченных счетов пока нет. '
                      'Данные по тикетам и старым покупкам собраны из БД.</div></div>')
    else:
        empty_note = ""

    warning_html = ""
    if warnings:
        items_html = "".join(f"<li>{esc(w)}</li>" for w in warnings if w)
        warning_html = (f'<div class="card" style="border-color:rgba(255,92,122,.35);'
                        f'background:rgba(255,92,122,.06)"><b>Замечания по данным:</b>'
                        f'<ul style="margin:6px 0 0;padding-left:18px">{items_html}</ul></div>')

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Аналитика магазина · Diamond</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Аналитика <span>магазина</span></h1>
      <div class="sub">{esc(source_note)} · период: {esc(labels[0])} — {esc(labels[-1])} {stats[-1].key[:4] if stats else ""}</div>
    </div>
    <div class="badge"><span class="dot"></span> отчёт от {datetime.now().strftime('%d.%m.%Y %H:%M')}</div>
  </header>

  {warning_html}

  <div class="kpis">{''.join(kpis)}</div>

  {empty_note}

  <div class="card">
    <h2>Активность по дням</h2>
    <div class="cap">{esc(heat_note)}</div>
    {heat}
  </div>

  <div class="grid">
    <div class="card">
      <h2>Выручка по месяцам</h2>
      <div class="cap">Сумма оплаченных счетов</div>
      {bar_chart(list(zip(labels, revenue_vals)), w=560)}
    </div>
    <div class="card">
      <h2>Средний чек</h2>
      <div class="cap">Выручка ÷ число заказов</div>
      {line_chart([("Средний чек", cheque_vals, C_GOLD)], labels, w=560)}
    </div>
  </div>

  <div class="card">
    <h2>Заказы и покупатели</h2>
    <div class="legend">
      <span><i style="background:{C_ACCENT}"></i>заказы</span>
      <span><i style="background:{C_GREEN}"></i>уникальные покупатели</span>
    </div>
    {grouped_bars(list(zip(labels, order_vals, buyer_vals)), name_a="Заказы", name_b="Покупатели")}
  </div>

  {ticket_chart}

  <div class="grid">
    <div class="card">
      <h2>Приток и отток клиентов</h2>
      <div class="legend">
        <span><i style="background:{C_GREEN}"></i>новые</span>
        <span><i style="background:{C_RED}"></i>ушедшие (не купили в этом месяце)</span>
      </div>
      {diverging_bars(list(zip(labels, inflow_vals, outflow_vals)), w=560)}
    </div>
    <div class="card">
      <h2>Покупательская способность</h2>
      <div class="cap">Средняя цена одной позиции в счёте (индекс, первый месяц = 100)</div>
      {line_chart([("Индекс цены", price_index, C_ACCENT)], labels, fmt=lambda v: f"{v:.0f}", area=True, w=560)}
      <div class="note">Позиций в среднем заказе: <b>{str(round(summary['items_per_order'], 1)).replace('.', ',')}</b> · 
      средняя цена позиции сейчас: <b>{money(stats[-1].avg_item_price) if stats else '—'}</b>.
      Если индекс растёт быстрее выручки — чек растёт из-за цен, а не из-за объёма покупок.</div>
    </div>
  </div>

  <div class="card">
    <h2>Товары и изменение цены</h2>
    <div class="cap">Цена позиции = сумма счёта ÷ количество позиций. Сравнение первой и второй половины периода.</div>
    <table>
      <thead><tr><th>Позиция</th><th class="num">Заказов</th><th class="num">Выручка*</th>
      <th class="num">Ср. цена</th><th class="num">Δ цены</th><th>Доля</th></tr></thead>
      <tbody>{items_table}</tbody>
    </table>
    <div class="note">* Выручка по позиции распределена пропорционально между строками счёта.</div>
  </div>

  <div class="card">
    <h2>Месяцы</h2>
    <table>
      <thead><tr><th>Месяц</th><th class="num">Выручка</th><th class="num">Заказы</th>
      <th class="num">Покупатели</th><th class="num">Средний чек</th><th class="num">Нетто клиентов</th></tr></thead>
      <tbody>{''.join(month_rows)}</tbody>
    </table>
  </div>

  <footer>
    <span>Источник: счета/чеки AI-менеджера + тикеты и старые покупки из БД</span>
    <span>Сгенерировано scripts/shop_analytics.py</span>
  </footer>
</div>
</body>
</html>
"""


# ============================================================
# ДЕМО-ДАННЫЕ
# ============================================================
DEMO_PRODUCTS = [
    ("Nitro 1 Month", 460), ("Nitro 12 Month", 4410), ("Nitro Basic 1 Month", 300),
    ("Nitro Gift Full", 790), ("Boosts 1 Month", 45), ("Пополнение Steam (RUB)", 1100),
    ("Смена региона Steam", 200), ("Звёзды Telegram", 790), ("Аккаунт (без спама)", 250),
    ("Robux", 820), ("Roblox Plus +500", 1300), ("Spotify Individual", 270),
    ("Украшение профиля", 200), ("Бейджики Discord", 200), ("Наборы Discord", 420),
]


def demo_orders(today: Optional[date] = None, months: int = 14) -> List[Order]:
    """Правдоподобный поток заказов за `months` месяцев."""
    today = today or date.today()
    rnd = random.Random(20260317)
    start = month_shift(today, -(months - 1))
    end = datetime.combine(today, datetime.max.time()).timestamp()

    users: List[dict] = []
    orders: List[Order] = []
    next_uid = 100_000

    def new_user(now_ts: float) -> dict:
        nonlocal next_uid
        next_uid += 1
        return {
            "id": next_uid,
            "born": now_ts,
            "loyalty": rnd.betavariate(2, 5),      # 0..1, больше = чаще покупает
            "lifetime_days": rnd.choice([20, 45, 90, 180, 365, 900]),
            "last": now_ts,
        }

    for i in range(months):
        mstart = month_shift(start, i)
        mend = month_shift(start, i + 1)
        days_in_month = (mend - mstart).days
        base = 18 + i * 3.2
        seasonal = 1.25 if mstart.month in (11, 12) else (0.85 if mstart.month in (1, 2) else 1.0)
        n_orders = max(6, int(base * seasonal * rnd.uniform(0.85, 1.15)))

        for _ in range(n_orders):
            day = mstart + timedelta(days=rnd.randrange(days_in_month))
            if day > today:
                continue
            ts = datetime.combine(day, datetime.min.time()).timestamp() + rnd.uniform(9 * 3600, 22 * 3600)
            if ts > end:
                continue

            alive = [u for u in users if (ts - u["born"]) / 86400 <= u["lifetime_days"]]
            weights = [1 + 10 * u["loyalty"] for u in alive]
            if alive and rnd.random() < 0.62:
                user = rnd.choices(alive, weights=weights, k=1)[0]
            else:
                user = new_user(ts)
                users.append(user)

            user["last"] = ts
            n_items = rnd.choices([1, 1, 1, 2, 2, 3], k=1)[0]
            picked = rnd.sample(DEMO_PRODUCTS, k=n_items)
            drift = 1 + 0.015 * i          # цены понемногу растут
            amount = 0.0
            names = []
            for name, price in picked:
                qty = 1
                if name in ("Boosts 1 Month", "Robux", "Звёзды Telegram"):
                    qty = rnd.choice([1, 2, 3, 5])
                amount += price * drift * qty
                names.append(name)
            if rnd.random() < 0.18:
                amount *= 0.95
            amount = round(amount)

            paid = rnd.random() < 0.91
            orders.append(Order(user["id"], amount, names, int(ts), paid))
            if not paid:
                # повторная попытка оплаты в тот же день
                if rnd.random() < 0.45:
                    orders.append(Order(user["id"], amount, names, int(ts) + 3600, True))
    return orders


def demo_ticket_stats(today: Optional[date] = None, months: int = 14) -> dict:
    """Демо-статистика тикетов, чтобы предпросмотр показывал все блоки."""
    today = today or date.today()
    rnd = random.Random(424242)
    grid = month_sequence(today, months)
    stats: List[TicketMonth] = []
    for i, m in enumerate(grid):
        base = 20 + i * 2
        opened = max(4, int(base * rnd.uniform(0.8, 1.3)))
        closed = max(3, int(opened * rnd.uniform(0.75, 1.05)))
        purchased = max(2, int(base * 0.35 * rnd.uniform(0.7, 1.4)))
        stats.append(TicketMonth(
            key=month_key(m), label=MONTHS_RU[m.month - 1],
            opened=opened, closed=closed, purchased=purchased,
        ))
    return {
        "stats": stats,
        "open_now": rnd.randint(2, 9),
        "avg_hours": rnd.uniform(6, 30),
        "closed_total": sum(s.closed for s in stats),
        "opened_total": sum(s.opened for s in stats),
        "old_purchases": sum(s.purchased for s in stats),
    }


# ============================================================
# СБОРКА ОТЧЁТА
# ============================================================
def build_report(db_path: Optional[str] = None,
                 out_path: Optional[str] = None,
                 months: int = 12,
                 demo: bool = False,
                 today: Optional[date] = None) -> Report:
    months = max(2, min(24, int(months)))
    today = today or date.today()
    warnings: List[str] = []
    info: dict = {}

    if demo:
        orders = demo_orders(today, max(months, 14))
        tickets = demo_ticket_stats(today, max(months, 14))
        source = "Демо-данные (синтетика для предпросмотра)"
    else:
        db = Path(db_path) if db_path else DEFAULT_DB
        try:
            orders, tickets, warnings, info = load_data(db, months)
        except Exception as exc:  # последний рубеж: отчёт обязан собраться
            warnings.append(f"Ошибка чтения базы: {exc}")
            orders, tickets = [], {}
        source = f"База: {db.name}"

    try:
        data = aggregate(orders, months, today, tickets)
        html = render_html(data, months, source, warnings, info)
    except Exception as exc:
        # если что-то пошло не так, всё равно отдаём валидный HTML
        warnings.append(f"Часть графиков недоступна: {exc}")
        data = aggregate([], months, today, tickets)
        html = render_html(data, months, source, warnings, info)

    out = Path(out_path) if out_path else (DEMO_OUT if demo else DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    return Report(path=str(out.resolve()), html=html,
                  summary=data["summary"], warnings=warnings)



# ============================================================
# CLI
# ============================================================
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HTML-аналитика магазина")
    parser.add_argument("--db", help="путь к diamond.db (по умолчанию data/diamond.db)")
    parser.add_argument("--out", help="куда сохранить HTML")
    parser.add_argument("--months", type=int, default=12, help="сколько месяцев показать (2–24)")
    parser.add_argument("--demo", action="store_true", help="сгенерировать демо-данные")
    parser.add_argument("--open", action="store_true", help="открыть отчёт в браузере")
    args = parser.parse_args(argv)

    try:
        report = build_report(args.db, args.out, args.months, args.demo)
    except Exception as exc:
        print(f"❌ {exc}")
        return 1

    print(f"✅ Отчёт: {report.path}")
    print(f"   {report.as_text()}")
    if report.warning:
        print(f"   ⚠️ {report.warning}")

    if args.open:
        try:
            os.startfile(report.path)  # type: ignore[attr-defined]
        except Exception:
            import webbrowser
            webbrowser.open(Path(report.path).as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
