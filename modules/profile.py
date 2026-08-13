# -*- coding: utf-8 -*-
import os
import io
import json
import random
import time
import asyncio
import aiohttp
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageColor
import disnake

from core.utils import (
    BASE_DIR, ADD_DIR, DATA_DIR, logger,
    load_json, save_json, FILES,
    get_dc_cache, CONFIG
)

# Пути к ресурсам
FONT_PATH = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/1527006158282555412/1537294943805112471/image.png?ex=6a7e84fc&is=6a7d337c&hm=a6713ca389191d2ed4d9bac61250791a22e8afdd7274d92ffde031145359cd13&"
BACKGROUND_PATH = os.path.join(ADD_DIR, "profile_bg.png")

# Цвета ролей (для прогресс-бара)
ROLE_COLORS = {
    "none": "#888888",
    "bronze": "#d15640",
    "silver": "#b0b0b0",
    "gold": "#ae7911",
    "diamond": "#149bd0",
    "emerald": "#3d9e08",
    "amethyst": "#d88edf",
    "legendary": "#c51cb2",
    "pka": "#b3d9ff"
}

# Градиенты ролей (для текста)
ROLE_GRADIENTS = {
    "none": ["#888888", "#555555"],
    "bronze": ["#e78f67", "#d15640"],
    "silver": ["#ffffff", "#979797"],
    "gold": ["#f7c991", "#ae7911"],
    "diamond": ["#ddf0ef", "#149bd0"],
    "emerald": ["#eff3d3", "#3d9e08"],
    "amethyst": ["#9fc1ff", "#d88edf"],
    "legendary": ["#e68585", "#c51cb2"],
    "pka": ["#b3d9ff", "#d4bfff"]
}

ROLE_THRESHOLDS = {
    "none": 0,
    "bronze": 1,
    "silver": 3,
    "gold": 5,
    "diamond": 9,
    "emerald": 13,
    "amethyst": 18,
    "legendary": 24,
    "pka": 26
}

ROLE_NAMES = {
    "none": "НЕТ РОЛИ",
    "bronze": "BRONZE BUYER",
    "silver": "SILVER BUYER",
    "gold": "GOLD BUYER",
    "diamond": "DIAMOND BUYER",
    "emerald": "EMERALD BUYER",
    "amethyst": "AMETHYST BUYER",
    "legendary": "LEGENDARY BUYER",
    "pka": "ПОКУПАТЕЛЬ ВЕКА"
}

def get_role_from_count(count: int) -> str:
    if count >= 26:
        return "pka"
    elif count >= 24:
        return "legendary"
    elif count >= 18:
        return "amethyst"
    elif count >= 13:
        return "emerald"
    elif count >= 9:
        return "diamond"
    elif count >= 5:
        return "gold"
    elif count >= 3:
        return "silver"
    elif count >= 1:
        return "bronze"
    else:
        return "none"

def get_next_role(count: int):
    if count >= 26:
        return None, None, None
    thresholds = sorted([(k, v) for k, v in ROLE_THRESHOLDS.items() if v > count], key=lambda x: x[1])
    if not thresholds:
        return None, None, None
    next_role = thresholds[0][0]
    next_count = thresholds[0][1]
    return next_role, next_count, ROLE_NAMES[next_role]

def get_progress(count: int) -> int:
    current_role = get_role_from_count(count)
    current_threshold = ROLE_THRESHOLDS[current_role]
    next_role, next_count, _ = get_next_role(count)
    if next_role is None:
        return 100
    if next_count == current_threshold:
        return 0
    progress = int((count - current_threshold) / (next_count - current_threshold) * 100)
    return min(progress, 100)

def draw_gradient_text(draw, text, pos, font, colors):
    """Рисует текст с линейным градиентом (горизонтальный)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    grad_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad_img)
    # Горизонтальный градиент
    for i in range(width):
        ratio = i / width
        r = int(int(colors[0][1:3], 16) + (int(colors[1][1:3], 16) - int(colors[0][1:3], 16)) * ratio)
        g = int(int(colors[0][3:5], 16) + (int(colors[1][3:5], 16) - int(colors[0][3:5], 16)) * ratio)
        b = int(int(colors[0][5:7], 16) + (int(colors[1][5:7], 16) - int(colors[0][5:7], 16)) * ratio)
        grad_draw.line([(i, 0), (i, height)], fill=(r, g, b, 255), width=1)
    grad_draw.text((0, 0), text, fill=(255, 255, 255, 255), font=font)
    mask = grad_img.split()[3]
    grad_img = Image.composite(grad_img, Image.new("RGBA", (width, height), (0, 0, 0, 0)), mask)
    draw._image.paste(grad_img, (pos[0], pos[1]), mask)

async def download_background():
    if os.path.exists(BACKGROUND_PATH):
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(BACKGROUND_URL, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(BACKGROUND_PATH, "wb") as f:
                        f.write(data)
                    logger.info("Profile background downloaded.")
                else:
                    logger.error("Failed to download background: %s", resp.status)
    except Exception as e:
        logger.exception("Failed to download background: %s", e)

def create_profile_image(member: disnake.Member) -> bytes:
    counts = load_json(FILES["review_counts"], {})
    count = counts.get(str(member.id), 0)
    role_key = get_role_from_count(count)
    role_display = ROLE_NAMES[role_key]
    gradients = ROLE_GRADIENTS[role_key]
    progress_color = ROLE_COLORS[role_key]
    progress = get_progress(count)
    next_role, next_count, next_role_name = get_next_role(count)

    # Загружаем фон
    img = Image.open(BACKGROUND_PATH).convert("RGBA")
    if img.size != (1200, 700):
        img = img.resize((1200, 700), Image.Resampling.LANCZOS)

    # Затемнение
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 100))
    img = Image.alpha_composite(img, overlay)

    # Шрифты
    try:
        font = ImageFont.truetype(FONT_PATH, 44)
        font_small = ImageFont.truetype(FONT_PATH, 24)
        font_stats = ImageFont.truetype(FONT_PATH, 36)
        font_progress = ImageFont.truetype(FONT_PATH, 28)
    except:
        font = ImageFont.load_default()
        font_small = font
        font_stats = font
        font_progress = font

    draw = ImageDraw.Draw(img)

    # Аватар
    avatar_url = member.display_avatar.url
    avatar_img = None
    try:
        # Для синхронности используем стандартную заглушку, но можно добавить кеш
        avatar_img = Image.new("RGB", (200, 200), (50, 50, 80))
    except:
        avatar_img = Image.new("RGB", (200, 200), (50, 50, 80))

    if avatar_img:
        mask = Image.new("L", avatar_img.size, 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 200, 200), fill=255)
        avatar_img = avatar_img.resize((200, 200))
        avatar_img.putalpha(mask)
        img.paste(avatar_img, (50, 50), avatar_img)

    # Никнейм
    username = member.display_name
    draw.text((300, 60), f"@{username}", font=font, fill=(255, 255, 255))

    # Роль покупателя (градиент)
    draw_gradient_text(draw, role_display, (300, 140), font, gradients)

    # Отзывы и DC
    balance = get_dc_cache(member.id)["balance"]
    draw.text((300, 200), f"{count} отзывов", font=font_stats, fill=(200, 200, 200))
    draw.text((600, 200), f"{balance} DC", font=font_stats, fill=(200, 200, 200))

    # Прогресс-бар
    progress_x = 300
    progress_y = 280
    bar_width = 480
    bar_height = 26
    draw.rounded_rectangle((progress_x, progress_y, progress_x+bar_width, progress_y+bar_height), fill=(50, 50, 70), radius=13)
    if progress > 0:
        fill_width = int(bar_width * progress / 100)
        color_rgb = ImageColor.getrgb(progress_color)
        draw.rounded_rectangle((progress_x, progress_y, progress_x+fill_width, progress_y+bar_height), fill=color_rgb, radius=13)

    label = f"{next_role_name} ({progress}%)" if next_role else "Максимальная роль"
    draw.text((progress_x, progress_y - 30), label, font=font_progress, fill=(200, 200, 200))

    # Мета-информация
    top_role = member.top_role.name if member.top_role and member.top_role.name != "@everyone" else "Нет"
    joined_at = member.joined_at.strftime("%d.%m.%Y") if member.joined_at else "Неизвестно"
    meta_text = f"ID: {member.id}  |  Высшая роль: {top_role}  |  С: {joined_at}"
    draw.text((50, 650), meta_text, font=font_small, fill=(180, 180, 180))

    # Правая часть – статистика
    stats_bg = Image.new("RGBA", (400, 500), (255, 255, 255, 20))
    img.paste(stats_bg, (750, 70), stats_bg)

    draw.text((770, 90), "СТАТИСТИКА", font=font_progress, fill=(200, 200, 200))

    # Статистика (заглушки)
    purchases = get_dc_cache(member.id).get("purchases", [])
    total_purchases = len(purchases)
    unused = sum(1 for p in purchases if not p.get("used", False))

    stats_items = [
        ("Баланс DC", str(balance)),
        ("Покупок", str(total_purchases)),
        ("Неиспользовано", str(unused)),
        ("Отзывов", str(count))
    ]
    x_offsets = [770, 960]
    y_start = 140
    for i, (label, value) in enumerate(stats_items):
        row = i // 2
        col = i % 2
        x = x_offsets[col]
        y = y_start + row * 80
        cell_bg = Image.new("RGBA", (160, 60), (255, 255, 255, 10))
        img.paste(cell_bg, (x, y), cell_bg)
        draw.text((x+10, y+5), label, font=font_small, fill=(150, 150, 150))
        draw.text((x+10, y+30), value, font=font_progress, fill=(255, 255, 255))

    # История операций
    history = get_dc_cache(member.id).get("history", [])[-5:]
    draw.text((770, 300), "ИСТОРИЯ ОПЕРАЦИЙ", font=font_progress, fill=(200, 200, 200))

    y_offset = 340
    for h in history:
        date_str = datetime.fromtimestamp(h["date"]).strftime("%d.%m.%Y")
        amount = h["amount"]
        sign = "+" if amount >= 0 else ""
        color = (100, 200, 100) if amount >= 0 else (200, 100, 100)
        line = f"{date_str}  {sign}{amount} DC"
        draw.text((770, y_offset), line, font=font_small, fill=color)
        y_offset += 30

    total_earned = sum(h["amount"] for h in history if h["amount"] > 0)
    draw.text((770, y_offset + 20), f"Всего заработано: {total_earned} DC", font=font_small, fill=(200, 200, 200))

    with io.BytesIO() as output:
        img.save(output, format="PNG")
        return output.getvalue()

async def generate_profile_image(member: disnake.Member) -> bytes:
    """Асинхронная обёртка для создания изображения профиля."""
    await download_background()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, create_profile_image, member)
