# -*- coding: utf-8 -*-
import os
import asyncio
import aiohttp
import json
import time
from datetime import datetime
from core.utils import logger, db, cur, CONFIG, get_dc_cache, BASE_DIR

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
ACCESS_CODE = "stopapupa"

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
def init_tg_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS tg_admins (
        chat_id INTEGER PRIMARY KEY,
        username TEXT,
        added_at INTEGER
    );
    """)
    db.commit()

init_tg_tables()
PENDING_BC = {}

def is_tg_admin(chat_id: int) -> bool:
    row = cur.execute("SELECT 1 FROM tg_admins WHERE chat_id=?", (chat_id,)).fetchone()
    return bool(row)

def add_tg_admin(chat_id: int, username: str):
    cur.execute("INSERT OR REPLACE INTO tg_admins (chat_id, username, added_at) VALUES (?, ?, ?)", (chat_id, username, int(time.time())))
    db.commit()

def remove_tg_admin(chat_id: int):
    cur.execute("DELETE FROM tg_admins WHERE chat_id=?", (chat_id,))
    db.commit()

def get_all_admins():
    return cur.execute("SELECT chat_id FROM tg_admins").fetchall()

# ============================================================
# УТИЛИТЫ
# ============================================================
def esc(text: str) -> str:
    if not text: return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

async def tg_api(method: str, payload: dict = None) -> dict:
    if not TG_BOT_TOKEN: return {}
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=15) as resp:
                return await resp.json()
    except Exception as e:
        logger.error(f"TG API error {method}: {e}")
        return {}

async def send_tg_message(chat_id, text: str, reply_markup: dict = None):
    payload = {
        "chat_id": chat_id, 
        "text": text[:4000], 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    resp = await tg_api("sendMessage", payload)
    if not resp.get("ok"):
        payload.pop("parse_mode", None)
        await tg_api("sendMessage", payload)

async def edit_tg_message(chat_id, message_id, text: str, reply_markup: dict = None):
    payload = {
        "chat_id": chat_id, 
        "message_id": message_id,
        "text": text[:4000], 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await tg_api("editMessageText", payload)

async def send_tg_notification(text: str):
    for r in get_all_admins():
        await send_tg_message(r["chat_id"], text)

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def get_main_menu():
    return {
        "keyboard": [
            [{"text": "🎫 Тикеты"}, {"text": "❓ Вопросы"}],
            [{"text": "📊 Экономика"}, {"text": "🏰 Кланы"}],
            [{"text": "👥 Юзеры"}, {"text": "⚙️ Действия"}],
            [{"text": "🔧 Утилиты"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }

def btn(text, data):
    return {"text": text, "callback_data": data}

def back_btn(data="menu", text="🔙 Назад"):
    return {"inline_keyboard": [[btn(text, data)]]}

# ============================================================
# ОБРАБОТКА ТЕКСТА
# ============================================================
async def process_message(chat_id: int, text: str, username: str = ""):
    if text == "/start":
        if is_tg_admin(chat_id):
            await send_tg_message(chat_id, "👑 <b>С возвращением, Шеф!</b>\n\nВыбери раздел:", get_main_menu())
        else:
            await send_tg_message(chat_id, "👋 Привет! Это приватная админ-панель.\n\nВведи кодовое слово для доступа:")
        return

    if text == ACCESS_CODE:
        if not is_tg_admin(chat_id):
            add_tg_admin(chat_id, username or "admin")
            await send_tg_message(chat_id, "✅ <b>Доступ разрешен!</b>\n\nДобро пожаловать, Шеф. Используй меню ниже:", get_main_menu())
            logger.info(f"TG: авторизован админ {chat_id} ({username})")
        else:
            await send_tg_message(chat_id, "Ты уже авторизован.", get_main_menu())
        return

    if text == "/logout":
        remove_tg_admin(chat_id)
        await send_tg_message(chat_id, "👋 Ты вышел из системы.")
        return

    if not is_tg_admin(chat_id):
        await send_tg_message(chat_id, "⛔ Доступ запрещён. Введи кодовое слово.")
        return

    if text.startswith("/give "):
        parts = text.split(maxsplit=3)
        if len(parts) >= 3:
            try:
                uid = int(parts[1])
                amount = int(parts[2])
                reason = parts[3] if len(parts) > 3 else "Выдано администратором"
                from modules.dc import add_dc
                await add_dc(uid, amount, reason, notify=True, log=True)
                await send_tg_message(chat_id, f"✅ Выдано <code>{amount} DC</code> юзеру <code>{uid}</code>")
            except ValueError:
                await send_tg_message(chat_id, "❌ Формат: <code>/give id amount reason</code>")
        return

    if text.startswith("/take "):
        parts = text.split(maxsplit=3)
        if len(parts) >= 3:
            try:
                uid = int(parts[1])
                amount = int(parts[2])
                reason = parts[3] if len(parts) > 3 else "Списано администратором"
                from modules.dc import remove_dc
                ok = await remove_dc(uid, amount, reason, notify=True, log=True)
                if ok: await send_tg_message(chat_id, f"✅ Списано <code>{amount} DC</code> у <code>{uid}</code>")
                else: await send_tg_message(chat_id, f"❌ Недостаточно DC у <code>{uid}</code>")
            except ValueError:
                await send_tg_message(chat_id, "❌ Формат: <code>/take id amount reason</code>")
        return

    if text.startswith("/user "):
        try:
            uid = int(text.split()[1])
            await show_user_info(chat_id, uid)
        except: await send_tg_message(chat_id, "❌ Формат: <code>/user id</code>")
        return

    if text.startswith("/close "):
        try:
            ch_id = int(text.split()[1])
            await close_ticket_by_id(chat_id, ch_id)
        except: await send_tg_message(chat_id, "❌ Формат: <code>/close channel_id</code>")
        return

    if text.startswith("/bc "):
        msg = text[4:].strip()
        if msg:
            PENDING_BC[chat_id] = msg
            keyboard = {"inline_keyboard": [[btn("✅ Отправить", "bc_send"), btn("❌ Отмена", "bc_cancel")]]}
            await send_tg_message(chat_id, f"📢 <b>Предпросмотр:</b>\n\n{esc(msg)}\n\nОтправить в Discord?", keyboard)
        return

    if text == "🎫 Тикеты": await show_tickets(chat_id, "real")
    elif text == "❓ Вопросы": await show_tickets(chat_id, "questions")
    elif text == "📊 Экономика": await show_economy_menu(chat_id)
    elif text == "🏰 Кланы": await show_clans(chat_id)
    elif text == "👥 Юзеры": await show_users_help(chat_id)
    elif text == "⚙️ Действия": await show_actions_menu(chat_id)
    elif text == "🔧 Утилиты": await show_utils_menu(chat_id)
    else: await send_tg_message(chat_id, "Используй кнопки меню ниже.", get_main_menu())

# ============================================================
# ЭКРАНЫ
# ============================================================
async def show_tickets(chat_id: int, kind: str = "real", page: int = 0):
    try:
        from core.bot import bot
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    except: guild = None

    if kind == "real":
        title = "🎫 <b>Тикеты (Реал)</b>"
        rows = cur.execute("SELECT channel_id, user_id FROM ticket_owners WHERE category_id=?", (CONFIG.get("TICKET_CATEGORY_ID"),)).fetchall()
    elif kind == "coins":
        title = "🎫 <b>Тикеты (DC)</b>"
        rows = cur.execute("SELECT channel_id, user_id FROM ticket_owners WHERE category_id=?", (CONFIG.get("COINS_CATEGORY_ID"),)).fetchall()
    else:
        title = "❓ <b>Вопросы</b>"
        rows = []
        if guild:
            cat = guild.get_channel(1569979195369725973)
            if cat:
                for ch in cat.text_channels:
                    rows.append({"channel_id": ch.id, "user_id": 0})
    
    if not rows:
        await send_tg_message(chat_id, f"{title}\n\n<i>Активных нет.</i>", back_btn("menu"))
        return

    per_page = 8
    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    chunk = rows[start:start + per_page]

    keyboard = []
    for r in chunk:
        keyboard.append([btn(f"👤 {r['user_id']} (ID: {r['channel_id']})", f"tview_{r['channel_id']}")])
    
    nav = []
    if page > 0: nav.append(btn("◀ Назад", f"tlist_{kind}_{page-1}"))
    if page < total_pages - 1: nav.append(btn("Вперёд ▶", f"tlist_{kind}_{page+1}"))
    if nav: keyboard.append(nav)
    keyboard.append([btn("🔙 В меню", "menu")])
    
    text = f"{title}\n\nВсего: <b>{len(rows)}</b> | Стр. {page+1}/{total_pages}"
    await send_tg_message(chat_id, text, {"inline_keyboard": keyboard})

async def show_ticket_history(chat_id: int, message_id: int, ch_id: int):
    try:
        from core.bot import bot
        channel = bot.get_channel(ch_id)
    except: channel = None

    if not channel:
        await edit_tg_message(chat_id, message_id, "❌ Канал не найден.", back_btn("menu"))
        return

    text = f"📜 <b>#{esc(channel.name)}</b>\n\n"
    try:
        async for msg in channel.history(limit=12, oldest_first=False):
            author = esc(msg.author.display_name)
            content = esc(msg.content or "[Медиа]")
            if len(content) > 100: content = content[:97] + "..."
            text += f"<b>{author}:</b> {content}\n\n"
    except Exception as e:
        text += f"<i>Ошибка: {esc(str(e))}</i>"

    keyboard = {
        "inline_keyboard": [
            [btn("🔴 Закрыть тикет", f"tclose_{ch_id}")],
            [btn("🔙 В меню", "menu")]
        ]
    }
    await edit_tg_message(chat_id, message_id, text, keyboard)

async def close_ticket_by_id(chat_id: int, ch_id: int):
    try:
        from core.bot import bot
        channel = bot.get_channel(ch_id)
        if not channel:
            await send_tg_message(chat_id, f"❌ Канал <code>{ch_id}</code> не найден.")
            return
        name = channel.name
        await channel.delete(reason="Закрыто через Telegram")
        await send_tg_message(chat_id, f"✅ Тикет <b>#{esc(name)}</b> закрыт.")
    except Exception as e:
        await send_tg_message(chat_id, f"❌ Ошибка: {esc(str(e))}")

async def show_economy_menu(chat_id: int):
    keyboard = {
        "inline_keyboard": [
            [btn("💰 Общая сводка", "econ_basic")],
            [btn("🏆 Топ-10 богачей", "econ_top")],
            [btn("🔥 Инфляция", "econ_infl")],
            [btn("🔙 В меню", "menu")]
        ]
    }
    await send_tg_message(chat_id, "📊 <b>Экономика</b>\n\nВыбери раздел:", keyboard)

async def show_econ_basic(chat_id: int, message_id: int):
    total = cur.execute("SELECT SUM(balance) FROM dc_cache").fetchone()[0] or 0
    users = cur.execute("SELECT COUNT(*) FROM dc_cache").fetchone()[0]
    today = int(time.time()) - 86400
    active = cur.execute("SELECT COUNT(*) FROM dc_cache WHERE last_active_ts > ?", (today,)).fetchone()[0]
    
    text = (
        f"📊 <b>Общая экономика</b>\n\n"
        f"💰 Всего DC: <code>{total:,}</code>\n"
        f"👥 Кошельков: <code>{users:,}</code>\n"
        f"📈 Средний чек: <code>{total // max(users, 1):,} DC</code>\n"
        f"🟢 Активных за 24ч: <code>{active}</code>"
    )
    await edit_tg_message(chat_id, message_id, text, {
        "inline_keyboard": [[btn("🔙 Назад", "econ_menu"), btn("🏠 В меню", "menu")]]
    })

async def show_econ_top(chat_id: int, message_id: int):
    rows = cur.execute("SELECT user_id, balance FROM dc_cache ORDER BY balance DESC LIMIT 10").fetchall()
    text = "🏆 <b>Топ-10 богачей</b>\n\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}. <code>{r['user_id']}</code> — <b>{r['balance']:,} DC</b>\n"
    await edit_tg_message(chat_id, message_id, text, {
        "inline_keyboard": [[btn("🔙 Назад", "econ_menu"), btn("🏠 В меню", "menu")]]
    })

async def show_econ_inflation(chat_id: int, message_id: int):
    rows = cur.execute("SELECT history FROM dc_cache").fetchall()
    minted, burned = 0, 0
    for r in rows:
        try:
            hist = json.loads(r["history"] or "[]")
            for h in hist:
                amt = h.get("amount", 0)
                if amt > 0: minted += amt
                elif amt < 0: burned += abs(amt)
        except: pass
    net = minted - burned
    text = (
        f"🔥 <b>Инфляция</b>\n\n"
        f"🟢 Напечатано: <code>{minted:,} DC</code>\n"
        f"🔴 Сожжено: <code>{burned:,} DC</code>\n"
        f"📉 Эмиссия: <code>{net:,} DC</code>"
    )
    await edit_tg_message(chat_id, message_id, text, {
        "inline_keyboard": [[btn("🔙 Назад", "econ_menu"), btn("🏠 В меню", "menu")]]
    })

async def show_clans(chat_id: int):
    try:
        from clan.core import get_all_clans, get_clan_bank, get_clan_members_count
        clans = get_all_clans()
        text = "🏰 <b>Кланы</b>\n\n"
        for c in clans:
            bank = get_clan_bank(c["id"])
            members = get_clan_members_count(c["id"])
            text += f"{c['emoji']} <b>{esc(c['name'])}</b>\n"
            text += f"   💰 Банк: <code>{bank:,} DC</code>\n"
            text += f"   👥 Людей: <code>{members}</code>\n\n"
        await send_tg_message(chat_id, text, back_btn("menu"))
    except Exception as e:
        await send_tg_message(chat_id, f"❌ Ошибка: {esc(str(e))}")

async def show_users_help(chat_id: int):
    text = (
        "👥 <b>Работа с юзерами</b>\n\n"
        "Команды:\n"
        "<code>/user id</code> — профиль юзера\n"
        "<code>/give id amount [reason]</code> — выдать DC\n"
        "<code>/take id amount [reason]</code> — списать DC\n"
    )
    await send_tg_message(chat_id, text, back_btn("menu"))

async def show_user_info(chat_id: int, uid: int):
    try:
        dc = get_dc_cache(uid)
        balance = dc.get("balance", 0)
        purchases = dc.get("purchases", [])
        unused = [p for p in purchases if not p.get("used")]
        
        text = f"👤 <b>Юзер</b> <code>{uid}</code>\n\n"
        text += f"💰 Баланс: <b>{balance:,} DC</b>\n"
        text += f"📦 Покупок: {len(purchases)} (не исп.: {len(unused)})\n"
        
        try:
            from clan.core import get_user_clan, get_user_contribution
            clan = get_user_clan(uid)
            if clan:
                contrib = get_user_contribution(uid)
                text += f"🏰 Клан: {esc(clan['name'])} (вклад: {contrib:,})\n"
        except: pass
        
        await send_tg_message(chat_id, text, back_btn("menu"))
    except Exception as e:
        await send_tg_message(chat_id, f"❌ Ошибка: {esc(str(e))}")

async def show_actions_menu(chat_id: int):
    keyboard = {
        "inline_keyboard": [
            [btn("🔄 Пересчёт ролей", "act_recalc")],
            [btn("💸 Выплата за активность", "act_payout")],
            [btn("🖼 Обновить панели", "act_panels")],
            [btn("🔁 Перезапустить таски", "act_tasks")],
            [btn("🔙 В меню", "menu")]
        ]
    }
    await send_tg_message(chat_id, "⚙️ <b>Действия</b>\n\nБудь осторожен:", keyboard)

async def show_utils_menu(chat_id: int):
    keyboard = {
        "inline_keyboard": [
            [btn("📜 Показать логи (20 строк)", "util_logs")],
            [btn("📢 Рассылка в Discord", "util_bc")],
            [btn("👋 Выйти из системы", "util_logout")],
            [btn("🔙 В меню", "menu")]
        ]
    }
    await send_tg_message(chat_id, "🔧 <b>Утилиты</b>", keyboard)

async def run_recalc_roles(chat_id: int, message_id: int):
    await edit_tg_message(chat_id, message_id, "⏳ Пересчитываю роли...")
    try:
        from core.bot import bot
        from core.utils import load_json, FILES, update_user_roles
        import asyncio as _asyncio
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild: return await edit_tg_message(chat_id, message_id, "❌ Guild не найден.")
        
        counts = load_json(FILES["review_counts"], {})
        ok, err = 0, 0
        for member in guild.members:
            if member.bot: continue
            try:
                await update_user_roles(member, int(counts.get(str(member.id), 0) or 0), keep_pka=True)
                ok += 1
                await _asyncio.sleep(0.05)
            except: err += 1
        
        await edit_tg_message(chat_id, message_id, f"✅ Готово!\n\nОбновлено: <b>{ok}</b>\nОшибок: <b>{err}</b>", back_btn("menu"))
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {esc(str(e))}", back_btn("menu"))

async def run_payout(chat_id: int, message_id: int):
    await edit_tg_message(chat_id, message_id, "⏳ Выплачиваю за активность...")
    try:
        from modules.dc import daily_activity_payout
        await daily_activity_payout()
        await edit_tg_message(chat_id, message_id, "✅ Выплата за активность выполнена!", back_btn("menu"))
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {esc(str(e))}", back_btn("menu"))

async def run_update_panels(chat_id: int, message_id: int):
    await edit_tg_message(chat_id, message_id, "⏳ Обновляю панели...")
    try:
        from core.bot import bot
        from clan.panels import update_clan_pool_embed
        await update_clan_pool_embed(bot)
        await edit_tg_message(chat_id, message_id, "✅ Панели обновлены!", back_btn("menu"))
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {esc(str(e))}", back_btn("menu"))

async def run_restart_tasks(chat_id: int, message_id: int):
    await edit_tg_message(chat_id, message_id, "⏳ Перезапускаю таски...")
    try:
        from core.bot import restart_all_tasks
        n = await restart_all_tasks()
        await edit_tg_message(chat_id, message_id, f"✅ Перезапущено {n} тасков.", back_btn("menu"))
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {esc(str(e))}", back_btn("menu"))

async def show_logs(chat_id: int, message_id: int):
    try:
        log_path = os.path.join(BASE_DIR, "bot.log")
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-20:]
        text = "<b>📜 Последние 20 строк:</b>\n\n<pre>" + esc("".join(lines)) + "</pre>"
        await edit_tg_message(chat_id, message_id, text[:4000], back_btn("utils_menu"))
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ {esc(str(e))}", back_btn("utils_menu"))

async def send_broadcast(chat_id, message_id, text_msg):
    try:
        from core.bot import bot
        import disnake
        channel = bot.get_channel(CONFIG["LOG_CHANNEL_ID"])
        if not channel: return await edit_tg_message(chat_id, message_id, "❌ Канал не найден.")
        
        embed = disnake.Embed(title="📢 Объявление от администрации", description=text_msg, color=0x2b2d31)
        await channel.send(embed=embed)
        await edit_tg_message(chat_id, message_id, "✅ Рассылка отправлена в #логи.")
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {esc(str(e))}")

# ============================================================
# ОБРАБОТКА CALLBACK
# ============================================================
async def process_callback(chat_id: int, message_id: int, data: str):
    if not is_tg_admin(chat_id): return
    
    if data == "menu": await edit_tg_message(chat_id, message_id, "👑 <b>Главное меню</b>", get_main_menu())
    elif data == "econ_menu": await show_economy_menu(chat_id)
    elif data == "econ_basic": await show_econ_basic(chat_id, message_id)
    elif data == "econ_top": await show_econ_top(chat_id, message_id)
    elif data == "econ_infl": await show_econ_inflation(chat_id, message_id)
    elif data.startswith("tlist_"):
        _, kind, page = data.split("_", 2)
        await tg_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        await show_tickets(chat_id, kind, int(page))
    elif data.startswith("tview_"):
        await show_ticket_history(chat_id, message_id, int(data.split("_")[1]))
    elif data.startswith("tclose_"):
        await close_ticket_by_id(chat_id, int(data.split("_")[1]))
        await edit_tg_message(chat_id, message_id, "✅ Тикет закрыт.", back_btn("menu"))
    elif data == "act_recalc": await run_recalc_roles(chat_id, message_id)
    elif data == "act_payout": await run_payout(chat_id, message_id)
    elif data == "act_panels": await run_update_panels(chat_id, message_id)
    elif data == "act_tasks": await run_restart_tasks(chat_id, message_id)
    elif data == "utils_menu": await show_utils_menu(chat_id)
    elif data == "util_logs": await show_logs(chat_id, message_id)
    elif data == "util_bc": await edit_tg_message(chat_id, message_id, "📢 Введи текст рассылки командой:\n<code>/bc твой текст</code>", back_btn("utils_menu"))
    elif data == "util_logout":
        remove_tg_admin(chat_id)
        await edit_tg_message(chat_id, message_id, "👋 Ты вышел из системы.")
    elif data == "bc_send":
        text = PENDING_BC.pop(chat_id, None)
        if text: await send_broadcast(chat_id, message_id, text)
    elif data == "bc_cancel":
        PENDING_BC.pop(chat_id, None)
        await edit_tg_message(chat_id, message_id, "❌ Рассылка отменена.", back_btn("menu"))

# ============================================================
# POLLING
# ============================================================
async def tg_polling_task():
    if not TG_BOT_TOKEN: return
    await tg_api("deleteWebhook", {"drop_pending_updates": True})
    logger.info("🤖 TG Command Center запущен.")
    
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=35) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(5)
                        continue
                    data = await resp.json()
                    if not data.get("ok"): 
                        await asyncio.sleep(5)
                        continue
                    
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        
                        if "message" in update:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]
                            text = msg.get("text", "").strip()
                            username = msg["from"].get("username", "") or msg["from"].get("first_name", "")
                            if text: await process_message(chat_id, text, username)
                                
                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            chat_id = cb["message"]["chat"]["id"]
                            msg_id = cb["message"]["message_id"]
                            data_str = cb["data"]
                            
                            await tg_api("answerCallbackQuery", {"callback_query_id": cb["id"]})
                            await process_callback(chat_id, msg_id, data_str)
                                
        except asyncio.TimeoutError: pass
        except Exception as e:
            logger.error(f"TG polling error: {e}")
            await asyncio.sleep(3)

def start_tg_bot():
    if TG_BOT_TOKEN:
        asyncio.create_task(tg_polling_task())
