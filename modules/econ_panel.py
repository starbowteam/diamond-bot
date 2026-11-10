# -*- coding: utf-8 -*-
"""
ВРЕМЕННЫЙ СКРИПТ: Мега-панель экономической аналитики.
Считает инфляцию, покрытие фиатом, распределение богатства и многое другое.
Исключает админов из расчетов.
"""
import disnake
from disnake import ui
import json
import re
import time
from collections import Counter
from core.utils import logger, db, cur, CONFIG

STAFF_PANEL_CHANNEL_ID = 1551276116679860314
EXCLUDED_USERS = (796293832751972352, 1124040555240898631)
DC_TO_RUB = 0.1  # 1 DC = 0.1 Рубля (10 DC = 1 ₽)

def _fmt(n):
    return f"{int(n):,}".replace(",", " ")

def get_full_econ_stats():
    """Собирает ВСЮ экономику в один словарь."""
    placeholders = ','.join('?' * len(EXCLUDED_USERS))
    
    # 1. Базовая статистика
    row = cur.execute(f"SELECT SUM(balance) as total, COUNT(user_id) as users FROM dc_cache WHERE user_id NOT IN ({placeholders})", EXCLUDED_USERS).fetchone()
    total_dc = row["total"] or 0
    total_users = row["users"] or 0
    avg_dc = total_dc / total_users if total_users > 0 else 0
    
    # 2. Парсинг истории
    rows = cur.execute(f"SELECT user_id, balance, history FROM dc_cache WHERE user_id NOT IN ({placeholders})", EXCLUDED_USERS).fetchall()
    
    minted = 0
    burned = 0
    income_sources = Counter()
    expense_sources = Counter()
    large_tx = [] # (amount, reason, user_id)
    
    for r in rows:
        try:
            hist = json.loads(r["history"])
            for h in hist:
                amt = h.get("amount", 0)
                reason = h.get("reason", "Неизвестно")
                
                if amt > 0:
                    minted += amt
                    # Парсим источник дохода
                    if "казино" in reason.lower() or "рулетк" in reason.lower() or "блэкджек" in reason.lower(): income_sources["Казино"] += amt
                    elif "отзыв" in reason.lower(): income_sources["Отзывы"] += amt
                    elif "клан" in reason.lower() or "копилк" in reason.lower(): income_sources["Кланы"] += amt
                    elif "подарок" in reason.lower() or "ежеднев" in reason.lower(): income_sources["Подарки/Бонусы"] += amt
                    elif "реф" in reason.lower() or "приглаш" in reason.lower(): income_sources["Рефералы"] += amt
                    else: income_sources["Активность/Прочее"] += amt
                    
                    if amt >= 5000: large_tx.append((amt, reason, r["user_id"], "+"))
                elif amt < 0:
                    burned += abs(amt)
                    # Парсим траты
                    if "покупка" in reason.lower() or "товар" in reason.lower(): expense_sources["Магазин"] += abs(amt)
                    elif "казино" in reason.lower() or "ставк" in reason.lower(): expense_sources["Казино"] += abs(amt)
                    elif "кейс" in reason.lower(): expense_sources["Кейсы"] += abs(amt)
                    else: expense_sources["Прочее"] += abs(amt)
                    
                    if abs(amt) >= 5000: large_tx.append((abs(amt), reason, r["user_id"], "-"))
        except Exception:
            pass
            
    # 3. Распределение богатства
    wealth_dist = {"<1k": 0, "1k-10k": 0, "10k-50k": 0, "50k-100k": 0, "100k+": 0}
    whales = []
    for r in rows:
        b = r["balance"] or 0
        if b < 1000: wealth_dist["<1k"] += 1
        elif b < 10000: wealth_dist["1k-10k"] += 1
        elif b < 50000: wealth_dist["10k-50k"] += 1
        elif b < 100000: wealth_dist["50k-100k"] += 1
        else: 
            wealth_dist["100k+"] += 1
            whales.append((r["user_id"], b))
            
    # 4. Топ игроков
    top_users = cur.execute(f"""
        SELECT user_id, balance FROM dc_cache 
        WHERE user_id NOT IN ({placeholders}) AND balance > 0
        ORDER BY balance DESC LIMIT 10
    """, EXCLUDED_USERS).fetchall()
    
    # 5. Топ транзакций
    large_tx.sort(key=lambda x: x[0], reverse=True)
    
    return {
        "total_dc": total_dc,
        "total_users": total_users,
        "avg_dc": avg_dc,
        "minted": minted,
        "burned": burned,
        "income_sources": income_sources,
        "expense_sources": expense_sources,
        "wealth_dist": wealth_dist,
        "whales": whales,
        "top_users": top_users,
        "large_tx": large_tx[:10]
    }

# ============================================================
# СЕЛЕКТ СО ВСЕМИ ПУНКТАМИ
# ============================================================
class EconSelect(ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="1. Общая сводка", description="Баланс, юзеры, средний чек", value="overview", emoji="📊"),
            disnake.SelectOption(label="2. Инфляция (Эмиссия/Сжигание)", description="Сколько бот напечатал и сколько сожгли игроки", value="inflation", emoji="🔥"),
            disnake.SelectOption(label="3. Покрытие фиатом (₽)", description="Сколько денег нужно на выкуп всей экономики", value="fiat", emoji="💱"),
            disnake.SelectOption(label="4. Распределение богатства", description="Сколько людей в каких диапазонах баланса", value="wealth", emoji="⚖️"),
            disnake.SelectOption(label="5. Топ-10 богачей", description="Кто реально держит экономику (без админов)", value="top", emoji="👑"),
            disnake.SelectOption(label="6. Крупнейшие транзакции", description="Самые большие вливания и траты (от 5000 DC)", value="large_tx", emoji="💸"),
            disnake.SelectOption(label="7. Источники дохода", description="Откуда игроки получают больше всего DC", value="income", emoji="💰"),
            disnake.SelectOption(label="8. Категории трат", description="Куда игроки больше всего сливают DC", value="expense", emoji="🛒"),
            disnake.SelectOption(label="9. Кит-лист (>100k DC)", description="Игроки, которые могут обрушить рынок", value="whales", emoji="🐋"),
            disnake.SelectOption(label="10. Здоровье экономики", description="Общий вердикт по инфляции", value="health", emoji="🩺"),
        ]
        super().__init__(placeholder="Выберите раздел экономической аналитики...", min_values=1, max_values=1, options=options, custom_id="econ_panel_select")

    async def callback(self, inter: disnake.MessageInteraction):
        await inter.response.defer(ephemeral=True)
        val = self.values[0]
        stats = get_full_econ_stats()
        
        e = disnake.Embed(color=0x2b2d31)
        
        if val == "overview":
            e.title = "📊 1. Общая сводка"
            e.color = 0x00ff00
            e.description = (
                f"> **Всего DC в обороте:** `{_fmt(stats['total_dc'])} DC`\n"
                f"> **Активных кошельков:** `{stats['total_users']} чел.`\n"
                f"> **Средний баланс на юзера:** `{_fmt(stats['avg_dc'])} DC`\n\n"
                f"*Админы исключены из расчетов.*"
            )
            
        elif val == "inflation":
            e.title = "🔥 2. Инфляция (Эмиссия/Сжигание)"
            e.color = 0xff6600
            net = stats['minted'] - stats['burned']
            e.description = (
                f"> **Всего напечатано (Minted):** `{_fmt(stats['minted'])} DC`\n"
                f"> **Всего сожжено (Burned):** `{_fmt(stats['burned'])} DC`\n"
                f"> **Чистая эмиссия:** `{_fmt(net)} DC`\n\n"
                f"> *Сейчас в обороте:* `{_fmt(stats['total_dc'])} DC`\n"
                f"> *Проверка: Напечатано - Сожжено = В обороте*"
            )
            
        elif val == "fiat":
            fiat_value = stats["total_dc"] * DC_TO_RUB
            e.title = "💱 3. Покрытие фиатом"
            e.color = 0x2ecc71
            e.description = (
                f"> **Условный курс:** `1 DC = {DC_TO_RUB} ₽`\n"
                f"> **Обратный курс:** `{int(1/DC_TO_RUB)} DC = 1 ₽`\n\n"
                f"> **Покрытие 100% экономики:** **{fiat_value:,.2f} ₽**\n"
                f"> *Столько реальных денег нужно, чтобы выкупить все DC у игроков.*\n\n"
                f"> **Покрытие без Китов (без 100k+):** **{(stats['total_dc'] - sum(w[1] for w in stats['whales'])) * DC_TO_RUB:,.2f} ₽**"
            )
            
        elif val == "wealth":
            e.title = "⚖️ 4. Распределение богатства"
            e.color = 0x5865f2
            dist = stats["wealth_dist"]
            e.description = (
                f"> **< 1 000 DC:** `{dist['<1k']} чел.` (Новички)\n"
                f"> **1 000 - 10 000 DC:** `{dist['1k-10k']} чел.` (Активные)\n"
                f"> **10 000 - 50 000 DC:** `{dist['10k-50k']} чел.` (Середняки)\n"
                f"> **50 000 - 100 000 DC:** `{dist['50k-100k']} чел.` (Богачи)\n"
                f"> **100 000+ DC:** `{dist['100k+']} чел.` (Киты)\n\n"
                f"*Если >50% людей в категории <1k, экономика здорова, деньги не задерживаются.*"
            )
            
        elif val == "top":
            e.title = "👑 5. Топ-10 богачей"
            e.color = 0xffaa00
            lines = []
            for i, u in enumerate(stats["top_users"], 1):
                lines.append(f"> **#{i}** <@{u['user_id']}> — `{_fmt(u['balance'])} DC`")
            e.description = "\n".join(lines) if lines else "Пусто."
            e.set_footer(text="Меценаты и Админы скрыты из списка")
            
        elif val == "large_tx":
            e.title = "💸 6. Крупнейшие транзакции"
            e.color = 0xf1c40f
            lines = []
            for amt, reason, uid, sign in stats["large_tx"]:
                lines.append(f"> `{sign}{_fmt(amt)} DC` — <@{uid}> ({reason[:30]})")
            e.description = "\n".join(lines) if lines else "Крупных транзакций не было."
            
        elif val == "income":
            e.title = "💰 7. Источники дохода"
            e.color = 0x2ecc71
            lines = []
            for src, amt in stats["income_sources"].most_common():
                lines.append(f"> **{src}:** `{_fmt(amt)} DC`")
            e.description = "\n".join(lines) if lines else "Пусто."
            e.set_footer(text="Откуда берется валюта в системе")
            
        elif val == "expense":
            e.title = "🛒 8. Категории трат"
            e.color = 0xe74c3c
            lines = []
            for dst, amt in stats["expense_sources"].most_common():
                lines.append(f"> **{dst}:** `{_fmt(amt)} DC`")
            e.description = "\n".join(lines) if lines else "Пусто."
            e.set_footer(text="Куда игроки сливают валюту (сжигание)")
            
        elif val == "whales":
            e.title = "🐋 9. Кит-лист (>100k DC)"
            e.color = 0x9b59b6
            lines = []
            if stats["whales"]:
                for uid, b in sorted(stats["whales"], key=lambda x: -x[1]):
                    lines.append(f"> <@{uid}> — `{_fmt(b)} DC`")
            else:
                lines.append("Нет игроков с таким балансом.")
            e.description = "\n".join(lines)
            e.set_footer(text="Эти люди держат рынок. Если они сольют все - будет обвал.")
            
        elif val == "health":
            e.title = "🩺 10. Здоровье экономики"
            e.color = 0x3498db
            
            total_minted = stats["minted"] or 1
            burn_rate = (stats["burned"] / total_minted) * 100
            
            health_text = ""
            if burn_rate > 80: health_text = "🟢 Идеально. Игроки тратят почти всё, что зарабатывают."
            elif burn_rate > 50: health_text = "🟡 Нормально. Есть небольшой накопленный капитал."
            elif burn_rate > 20: health_text = "🟠 Инфляция. Игроки копят больше, чем тратят."
            else: health_text = "🔴 КРИТИЧНО. Огромная инфляция. Нужен денежный сток (sink)."
            
            e.description = (
                f"> **Burn Rate (Сжигание/Эмиссия):** `{burn_rate:.1f}%`\n"
                f"> **Вердикт:** {health_text}\n\n"
                f"> *Рекомендация:* Если инфляция высокая, нужно добавить дорогие товары или поднять цены в казино."
            )
            
        await inter.followup.send(embed=e, ephemeral=True)

class EconPanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(EconSelect())

# ============================================================
# ЗАПУСК ПАНЕЛИ
# ============================================================
async def _send_panel(bot):
    ch = bot.get_channel(STAFF_PANEL_CHANNEL_ID)
    if not ch:
        logger.warning("Канал для эконом-панели не найден")
        return

    # Чистим старые панели
    try:
        async for msg in ch.history(limit=50):
            if msg.author == bot.user and msg.components:
                for comp in msg.components:
                    if comp.components[0].custom_id == "econ_panel_select":
                        await msg.delete()
                        break
    except Exception:
        pass

    e1 = disnake.Embed(
        title="💼 Экономический Аналитик (Временный)",
        description=(
            "Панель для отслеживания инфляции и покрытия валюты.\n"
            "**Исключены из расчетов:** <@796293832751972352> и <@1124040555240898631>.\n\n"
            "> Выберите нужный параметр в меню ниже, чтобы увидеть подробные цифры."
        ),
        color=0x2b2d31
    )
    e1.set_image(url="https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6aba8d23&is=6ab93ba3&hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&")
    
    await ch.send(embed=e1, view=EconPanelView())
    logger.info("📊 Экономическая панель отправлена в стафф-канал")

def init_econ_panel(bot):
    """Функция для запуска из bot.py"""
    bot.loop.create_task(_send_panel(bot))