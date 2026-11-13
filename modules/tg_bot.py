# -*- coding: utf-8 -*-
import os
import asyncio
import aiohttp
from core.utils import logger, db, cur, CONFIG

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
ACCESS_CODE = "stopapupa"

def get_saved_chat_id() -> str:
    row = cur.execute("SELECT value FROM settings WHERE key='tg_notify_chat_id'").fetchone()
    return row["value"] if row else None

def save_chat_id(chat_id: int):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('tg_notify_chat_id', ?)", (str(chat_id),))
    db.commit()

async def send_tg_message(chat_id, text: str):
    if not TG_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(f"TG send error: {await resp.text()}")
    except Exception as e:
        logger.error(f"TG send exception: {e}")

async def send_tg_notification(text: str):
    """Отправляет уведомление сохраненному админу"""
    chat_id = get_saved_chat_id()
    if chat_id:
        await send_tg_message(chat_id, text)

async def tg_polling_task():
    if not TG_BOT_TOKEN:
        logger.warning("TG_BOT_TOKEN не задан. Telegram-бот отключен.")
        return

    logger.info("🤖 Telegram-бот для уведомлений запущен.")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        await asyncio.sleep(5)
                        continue
                    data = await resp.json()
                    if data.get("ok"):
                        for update in data["result"]:
                            offset = update["update_id"] + 1
                            msg = update.get("message")
                            if not msg: continue
                            
                            chat_id = msg["chat"]["id"]
                            text = msg.get("text", "").strip()
                            
                            if text == "/start":
                                await send_tg_message(chat_id, "👋 Привет! Введи код доступа, чтобы получать уведомления о новых тикетах.")
                            elif text == ACCESS_CODE:
                                save_chat_id(chat_id)
                                await send_tg_message(chat_id, "✅ Код верный! Теперь я буду присылать уведомления о новых тикетах сюда.")
                                logger.info(f"TG Бот: авторизован новый Chat ID {chat_id}")
                            else:
                                saved = get_saved_chat_id()
                                if str(chat_id) != saved:
                                    await send_tg_message(chat_id, "❌ Неверный код. Попробуй еще раз или нажми /start")
        except Exception as e:
            logger.error(f"TG polling error: {e}")
        
        await asyncio.sleep(2)

def start_tg_bot():
    if TG_BOT_TOKEN:
        asyncio.create_task(tg_polling_task())
