# -*- coding: utf-8 -*-
import os
import asyncio
import aiohttp
import json
import time
from datetime import datetime
from core.utils import logger, db, cur, CONFIG, get_dc_cache

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
ACCESS_CODE = "stopapupa"

# ============================================================
# БАЗА ДАННЫХ (АВТОРИЗАЦИЯ)
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

def is_tg_admin(chat_id: int) -> bool:
    row = cur.execute("SELECT 1 FROM tg_admins WHERE chat_id=?", (chat_id,)).fetchone()
    return bool(row)

def add_tg_admin(chat_id: int, username: str):
    cur.execute("INSERT OR REPLACE INTO tg_admins (chat_id, username, added_at) VALUES (?, ?, ?)", (chat_id, username, int(time.time())))
    db.commit()

# ============================================================
# УТИЛИТЫ ОТПРАВКИ (HTML ЭКРАНИРОВАНИЕ)
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
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    resp = await tg_api("sendMessage", payload)
    if not resp.get("ok"):
        # Fallback если HTML битый
        payload.pop("parse_mode", None)
        await tg_api("sendMessage", payload)

async def edit_tg_message(chat_id, message_id, text: str, reply_markup: dict = None):
    payload = {
        "chat_id": chat_id, 
        "message_id": message_id,
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await tg_api("editMessageText", payload)

async def send_tg_notification(text: str):
    """Рассылка всем авторизованным админам"""
    rows = cur.execute("SELECT chat_id FROM tg_admins").fetchall()
    for r in rows:
        await send_tg_message(r["chat_id"], text)

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def get_main_menu():
    return {
        "keyboard": [
            [{"text": "🎫 Тикеты"}, {"text": "❓ Вопросы"}],
            [{"text": "📊 Экономика"}, {"text": "⚙️ Действия"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }

def get_back_button(callback_data: str = "menu"):
    return {
        "inline_keyboard": [[{"text": "🔙 Назад в меню", "callback_data": callback_data}]]
    }

# ============================================================
# ЛОГИКА ОБРАБОТКИ СООБЩЕНИЙ И КНОПОК
# ============================================================
async def process_message(chat_id: int, text: str):
    if text == "/start":
        if is_tg_admin(chat_id):
            await send_tg_message(chat_id, "👑 С возвращением, Шеф! Панель управления активирована.", get_main_menu())
        else:
            await send_tg_message(chat_id, "👋 Привет! Введи код доступа, чтобы получить права администратора.")
        return

    if text == ACCESS_CODE:
        if not is_tg_admin(chat_id):
            add_tg_admin(chat_id, "admin")
            await send_tg_message(chat_id, "✅ Код верный! Теперь ты в системе. Используй кнопки ниже.", get_main_menu())
            logger.info(f"TG: Авторизован новый админ {chat_id}")
        else:
            await send_tg_message(chat_id, "Ты уже авторизован.", get_main_menu())
        return

    if not is_tg_admin(chat_id):
        await send_tg_message(chat_id, "⛔ Доступ запрещен. Введи код доступа.")
        return

    if text == "🎫 Тикеты":
        await show_tickets(chat_id)
    elif text == "❓ Вопросы":
        await show_questions(chat_id)
    elif text == "📊 Экономика":
        await show_economy(chat_id)
    elif text == "⚙️ Действия":
        await show_actions(chat_id)

async def process_callback(chat_id: int, message_id: int, data: str):
    if not is_tg_admin(chat_id):
        return
    
    if data == "menu":
        await edit_tg_message(chat_id, message_id, "👑 Главное меню:", get_main_menu())
    
    # ЭКОНОМИКА
    elif data == "econ_basic":
        total_dc = cur.execute("SELECT SUM(balance) FROM dc_cache").fetchone()[0] or 0
        users = cur.execute("SELECT COUNT(*) FROM dc_cache").fetchone()[0]
        text = f"📊 <b>Базовая экономика</b>\n\n💰 Всего DC в обороте: <code>{total_dc:,}</code>\n👥 Кошельков: <code>{users}</code>\n📈 Средний чек: <code>{total_dc // max(users, 1):,}</code>"
        await edit_tg_message(chat_id, message_id, text, get_back_button("econ_menu"))
        
    elif data == "econ_top":
        rows = cur.execute("SELECT user_id, balance FROM dc_cache ORDER BY balance DESC LIMIT 10").fetchall()
        text = "🏆 <b>Топ-10 богачей</b>\n\n"
        for i, r in enumerate(rows, 1):
            text += f"{i}. <a href='tg://user?id={r['user_id']}'>{r['user_id']}</a> — <code>{r['balance']:,} DC</code>\n"
        await edit_tg_message(chat_id, message_id, text, get_back_button("econ_menu"))
        
    elif data == "econ_inflation":
        # Грубый подсчет инфляции из истории
        rows = cur.execute("SELECT history FROM dc_cache").fetchall()
        minted, burned = 0, 0
        for r in rows:
            try:
                hist = json.loads(r["history"] or "[]")
                for h in hist:
                    amt = h.get("amount", 0)
                    if amt > 0: minted += amt
                    else: burned += abs(amt)
            except: pass
        text = f"🔥 <b>Инфляция (Эмиссия/Сжигание)</b>\n\n🟢 Напечатано (Minted): <code>{minted:,} DC</code>\n🔴 Сожжено (Burned): <code>{burned:,} DC</code>\n📉 Чистая эмиссия: <code>{minted - burned:,} DC</code>"
        await edit_tg_message(chat_id, message_id, text, get_back_button("econ_menu"))

    # ТИКЕТЫ
    elif data.startswith("ticket_view_"):
        ch_id = int(data.split("_")[2])
        await show_ticket_history(chat_id, message_id, ch_id)

    elif data.startswith("ticket_close_"):
        ch_id = int(data.split("_")[2])
        try:
            from core.bot import bot
            channel = bot.get_channel(ch_id)
            if channel:
                await channel.delete(reason="Закрыто из TG")
                await edit_tg_message(chat_id, message_id, "✅ Тикет успешно закрыт и удален.")
            else:
                await edit_tg_message(chat_id, message_id, "❌ Канал не найден на сервере.")
        except Exception as e:
            await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {e}")
            
    # ДЕЙСТВИЯ
    elif data == "action_recalc":
        await edit_tg_message(chat_id, message_id, "⏳ Запускаю пересчет ролей...")
        try:
            from modules.commands_staff import recalc_all_roles
            from core.bot import bot
            guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
            if guild:
                await recalc_all_roles(guild)
                await edit_tg_message(chat_id, message_id, "✅ Пересчет ролей завершен.")
        except Exception as e:
            await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {e}")

    elif data == "action_payout":
        await edit_tg_message(chat_id, message_id, "⏳ Запускаю выплату за активность...")
        try:
            from modules.dc import daily_activity_payout
            await daily_activity_payout()
            await edit_tg_message(chat_id, message_id, "✅ Выплата за активность выполнена.")
        except Exception as e:
            await edit_tg_message(chat_id, message_id, f"❌ Ошибка: {e}")

# ============================================================
# ЭКРАНЫ
# ============================================================
async def show_tickets(chat_id: int):
    rows = cur.execute("SELECT channel_id, user_id, category_id FROM ticket_owners").fetchall()
    if not rows:
        await send_tg_message(chat_id, "🎫 Активных тикетов нет.", get_back_button())
        return

    keyboard = []
    text = "🎫 <b>Активные тикеты:</b>\n\n"
    for r in rows[:10]: # Максимум 10 для красоты
        ch_id = r["channel_id"]
        u_id = r["user_id"]
        cat = "Реал" if r["category_id"] == CONFIG["TICKET_CATEGORY_ID"] else "DC"
        text += f"• <code>{u_id}</code> [{cat}]\n"
        keyboard.append([{"text": f"Посмотреть {u_id} ({cat})", "callback_data": f"ticket_view_{ch_id}"}])
    
    keyboard.append([{"text": "🔙 Назад в меню", "callback_data": "menu"}])
    await send_tg_message(chat_id, text, {"inline_keyboard": keyboard})

async def show_ticket_history(chat_id: int, message_id: int, ch_id: int):
    await edit_tg_message(chat_id, message_id, "⏳ Загружаю историю переписки...")
    try:
        from core.bot import bot
        channel = bot.get_channel(ch_id)
        if not channel:
            return await edit_tg_message(chat_id, message_id, "❌ Канал не найден.")

        text = f"📜 <b>История тикета:</b> #{channel.name}\n\n"
        count = 0
        async for msg in channel.history(limit=15, oldest_first=False):
            author = esc(msg.author.display_name)
            content = esc(msg.content or "[Медиа/Эмбед]")
            if len(content) > 150: content = content[:147] + "..."
            text += f"👤 <b>{author}:</b> {content}\n\n"
            count += 1
            
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔴 Закрыть тикет", "callback_data": f"ticket_close_{ch_id}"}],
                [{"text": "🔙 К списку", "callback_data": "ticket_list"}, {"text": "🏠 В меню", "callback_data": "menu"}]
            ]
        }
        await edit_tg_message(chat_id, message_id, text, keyboard)
    except Exception as e:
        await edit_tg_message(chat_id, message_id, f"❌ Ошибка загрузки: {e}")

async def show_questions(chat_id: int):
    # Ищем каналы в категории вопросов
    q_cat = CONFIG.get("QUESTIONS_CATEGORY_ID", 1569979195369725973)
    rows = cur.execute("SELECT channel_id, user_id FROM ticket_owners WHERE category_id=?", (q_cat,)).fetchall()
    
    if not rows:
        await send_tg_message(chat_id, "❓ Вопросов нет.", get_back_button())
        return

    keyboard = []
    for r in rows[:10]:
        keyboard.append([{"text": f"Вопрос от {r['user_id']}", "callback_data": f"ticket_view_{r['channel_id']}"}])
    keyboard.append([{"text": "🔙 Назад в меню", "callback_data": "menu"}])
    
    await send_tg_message(chat_id, "❓ <b>Открытые вопросы:</b>", {"inline_keyboard": keyboard})

async def show_economy(chat_id: int):
    keyboard = {
        "inline_keyboard": [
            [{"text": "💰 Общая сводка", "callback_data": "econ_basic"}],
            [{"text": "🏆 Топ богачей", "callback_data": "econ_top"}],
            [{"text": "🔥 Инфляция (Эмиссия)", "callback_data": "econ_inflation"}],
            [{"text": "🔙 Назад в меню", "callback_data": "menu"}]
        ]
    }
    await send_tg_message(chat_id, "📊 <b>Раздел Экономики</b>\nВыберите параметр:", keyboard)

async def show_actions(chat_id: int):
    keyboard = {
        "inline_keyboard": [
            [{"text": "🔄 Пересчитать роли", "callback_data": "action_recalc"}],
            [{"text": "💸 Выплатить активность", "callback_data": "action_payout"}],
            [{"text": "🔙 Назад в меню", "callback_data": "menu"}]
        ]
    }
    await send_tg_message(chat_id, "⚙️ <b>Ручные действия</b>\nБудь осторожен, это влияет на всех:", keyboard)

# ============================================================
# СЛУШАТЕЛЬ (POLLING)
# ============================================================
async def tg_polling_task():
    if not TG_BOT_TOKEN:
        return

    init_tg_tables()
    
    # Сброс вебхука
    await tg_api("deleteWebhook", {"drop_pending_updates": True})
    logger.info("🤖 TG Admin Panel запущена.")
    
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
                    if not data.get("ok"): continue
                    
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        
                        # Текстовые сообщения
                        if "message" in update:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]
                            text = msg.get("text", "").strip()
                            if text:
                                await process_message(chat_id, text)
                                
                        # Нажатия на inline-кнопки
                        elif "callback_query" in update:
                            cb = update["callback_query"]
                            chat_id = cb["message"]["chat"]["id"]
                            msg_id = cb["message"]["message_id"]
                            data_str = cb["data"]
                            
                            # Отвечаем Telegram, чтобы убрать часики на кнопке
                            await tg_api("answerCallbackQuery", {"callback_query_id": cb["id"]})
                            
                            if data_str == "ticket_list":
                                await show_tickets(chat_id)
                            elif data_str == "econ_menu":
                                await show_economy(chat_id)
                            else:
                                await process_callback(chat_id, msg_id, data_str)
                                
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"TG polling error: {e}")
            await asyncio.sleep(3)

def start_tg_bot():
    if TG_BOT_TOKEN:
        asyncio.create_task(tg_polling_task())
