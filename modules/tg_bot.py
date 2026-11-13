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
    
    # 1. Пытаемся отправить с HTML
    payload = {
        "chat_id": chat_id, 
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    return
                
                err = await resp.text()
                logger.warning(f"TG HTML parse error, sending as plain text: {err}")
                
                # 2. Если HTML битый — отправляем как обычный текст
                payload_plain = {
                    "chat_id": chat_id, 
                    "text": text, 
                    "disable_web_page_preview": True
                }
                async with session.post(url, json=payload_plain, timeout=10) as resp2:
                    if resp2.status != 200:
                        logger.error(f"TG plain send error: {await resp2.text()}")
    except Exception as e:
        logger.error(f"TG send exception: {e}")

async def send_tg_notification(text: str):
    chat_id = get_saved_chat_id()
    if chat_id:
        await send_tg_message(chat_id, text)

async def clear_webhook():
    if not TG_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/deleteWebhook?drop_pending_updates=true"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("TG Бот: Вебхук успешно сброшен.")
                else:
                    logger.warning(f"TG Бот: Ошибка сброса вебхука {await resp.text()}")
    except Exception as e:
        logger.warning(f"TG Бот: Не удалось сбросить вебхук: {e}")

async def tg_polling_task():
    if not TG_BOT_TOKEN:
        logger.warning("TG_BOT_TOKEN не задан. Telegram-бот отключен.")
        return

    await clear_webhook()
    logger.info("🤖 Telegram-бот для уведомлений запущен.")
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
                        msg = update.get("message")
                        if not msg: continue
                        
                        chat_id = msg["chat"]["id"]
                        text = msg.get("text", "").strip()
                        
                        if text == "/start":
                            await send_tg_message(chat_id, "👋 Привет! Введи код доступа, чтобы получать уведомления о новых тикетах.")
                        elif text == ACCESS_CODE:
                            save_chat_id(chat_id)
                            await send_tg_message(chat_id, "✅ Код верный! Теперь я буду присылать уведомления о новых тикетах сюда.")
                            logger.info(f"✅ TG Бот: авторизован новый Chat ID {chat_id}")
                        else:
                            saved = get_saved_chat_id()
                            if str(chat_id) != saved:
                                await send_tg_message(chat_id, "❌ Неверный код. Попробуй еще раз или нажми /start")
                                
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"❌ TG polling exception: {e}")
            await asyncio.sleep(5)
        
        await asyncio.sleep(1)

def start_tg_bot():
    if TG_BOT_TOKEN:
        asyncio.create_task(tg_polling_task())
