# -*- coding: utf-8 -*-
import os
import io
import json
import time
import aiohttp
import asyncio
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageColor, ImageFilter

from core.utils import (
    BASE_DIR, ADD_DIR, DATA_DIR, logger,
    load_json, save_json, FILES,
    get_dc_cache, CONFIG
)

# Пути
FONT_PATH = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
BACKGROUND_URL = "https://cdn.discordapp.com/attachments/1527006158282555412/1537294943805112471/image.png?ex=6a7e84fc&is=6a7d337c&hm=a6713ca389191d2ed4d9bac61250791a22e8afdd7274d92ffde031145359cd13&"
BACKGROUND_PATH = os.path.join(ADD_DIR, "profile_bg.png")

# Цвета ролей
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

def get_next_role(count: int) -> tuple:
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

def draw_gradient_text(draw, text, pos, font, colors, direction="horizontal"):
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    grad_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad_img)
    if direction == "horizontal":
        for i in range(width):
            ratio = i / width
            r = int(int(colors[0][1:3], 16) + (int(colors[1][1:3], 16) - int(colors[0][1:3], 16)) * ratio)
            g = int(int(colors[0][3:5], 16) + (int(colors[1][3:5], 16) - int(colors[0][3:5], 16)) * ratio)
            b = int(int(colors[0][5:7], 16) + (int(colors[1][5:7], 16) - int(colors[0][5:7], 16)) * ratio)
            grad_draw.line([(i, 0), (i, height)], fill=(r, g, b, 255), width=1)
    else:
        for j in range(height):
            ratio = j / height
            r = int(int(colors[0][1:3], 16) + (int(colors[1][1:3], 16) - int(colors[0][1:3], 16)) * ratio)
            g = int(int(colors[0][3:5], 16) + (int(colors[1][3:5], 16) - int(colors[0][3:5], 16)) * ratio)
            b = int(int(colors[0][5:7], 16) + (int(colors[1][5:7], 16) - int(colors[0][5:7], 16)) * ratio)
            grad_draw.line([(0, j), (width, j)], fill=(r, g, b, 255), width=1)
    grad_draw.text((0, 0), text, fill=(255, 255, 255, 255), font=font)
    mask = grad_img.split()[3]
    grad_img = Image.composite(grad_img, Image.new("RGBA", (width, height), (0, 0, 0, 0)), mask)
    draw._image.paste(grad_img, (pos[0], pos[1]), mask)

def generate_profile_image(member) -> bytes:
    counts = load_json(FILES["review_counts"], {})
    count = counts.get(str(member.id), 0)
    balance = get_dc_cache(member.id)["balance"]
    role_key = get_role_from_count(count)
    role_display = ROLE_NAMES[role_key]
    grad_colors = ROLE_GRADIENTS[role_key]
    progress_color = ROLE_COLORS[role_key]
    progress = get_progress(count)
    next_role, next_count, next_role_name = get_next_role(count)
    history = get_dc_cache(member.id).get("history", [])[-5:]
    total_earned = sum(h["amount"] for h in history if h["amount"] > 0)

    img = Image.open(BACKGROUND_PATH).convert("RGBA")
    if img.size != (1200, 700):
        img = img.resize((1200, 700), Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 70))
    img = Image.alpha_composite(img, overlay)

    try:
        font_big = ImageFont.truetype(FONT_PATH, 44)
        font_role = ImageFont.truetype(FONT_PATH, 40)
        font_stats = ImageFont.truetype(FONT_PATH, 28)
        font_small = ImageFont.truetype(FONT_PATH, 24)
        font_progress = ImageFont.truetype(FONT_PATH, 22)
        font_meta = ImageFont.truetype(FONT_PATH, 16)
        font_history = ImageFont.truetype(FONT_PATH, 18)
    except:
        font_big = font_role = font_stats = font_small = font_progress = font_meta = font_history = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # ---- Аватар ----
    avatar_size = 200
    avatar_x = 50
    avatar_y = 70
    try:
        response = requests.get(member.display_avatar.url, timeout=5)
        avatar_img = Image.open(io.BytesIO(response.content)).convert("RGBA")
        avatar_img = avatar_img.resize((avatar_size, avatar_size))
    except:
        avatar_img = Image.new("RGBA", (avatar_size, avatar_size), (50, 50, 80))
    mask = Image.new("L", (avatar_size, avatar_size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, avatar_size-1, avatar_size-1), fill=255)
    avatar_img.putalpha(mask)
    img.paste(avatar_img, (avatar_x, avatar_y), avatar_img)
    draw.ellipse((avatar_x-4, avatar_y-4, avatar_x+avatar_size+4, avatar_y+avatar_size+4), outline="rgba(255,255,255,0.6)", width=4)

    # ---- Имя ----
    username = member.display_name
    draw.text((290, 80), f"@{username}", font=font_big, fill=(255, 255, 255))

    # ---- Роль (градиент) ----
    draw_gradient_text(draw, role_display, (290, 155), font_role, grad_colors)

    # ---- Отзывы и баланс ----
    draw.text((290, 220), f"{count} отзывов", font=font_stats, fill=(200, 200, 200))
    draw.text((520, 220), f"{balance} DC", font=font_stats, fill=(200, 200, 200))

    # ---- Прогресс-бар ----
    progress_x = 290
    progress_y = 285
    bar_width = 480
    bar_height = 30
    draw.rounded_rectangle((progress_x, progress_y, progress_x+bar_width, progress_y+bar_height), fill=(50, 50, 70), radius=15)
    if progress > 0:
        fill_width = int(bar_width * progress / 100)
        color_rgb = ImageColor.getrgb(progress_color)
        draw.rounded_rectangle((progress_x, progress_y, progress_x+fill_width, progress_y+bar_height), fill=color_rgb, radius=15)
    draw.text((progress_x+bar_width//2, progress_y+5), f"{progress}%", font=font_progress, fill=(0,0,0), anchor="mt")
    if next_role:
        label = f"До {next_role_name} ({progress}%)"
    else:
        label = "Максимальная роль"
    draw.text((progress_x, progress_y - 30), label, font=font_progress, fill=(200, 200, 200))

    # ---- Мета-информация ----
    top_role_name = member.top_role.name if member.top_role and member.top_role.name != "@everyone" else "Нет"
    joined_at = member.joined_at.strftime("%d.%m.%Y") if member.joined_at else "Неизвестно"
    meta_text = f"ID: {member.id}  |  Высшая роль: {top_role_name}  |  С: {joined_at}"
    draw.text((50, 660), meta_text, font=font_meta, fill=(180, 180, 180))

    # ---- Правая часть ----
    right_x = 760
    right_y = 70
    block = Image.new("RGBA", (420, 560), (255, 255, 255, 15))
    img.paste(block, (right_x, right_y), block)

    draw.text((right_x+210, 100), "СТАТИСТИКА", font=font_progress, fill=(200, 200, 200), anchor="mt")

    stats_data = [
        ("Баланс DC", str(balance)),
        ("Покупок", str(len(get_dc_cache(member.id).get("purchases", [])))),
        ("Неиспользовано", str(len([p for p in get_dc_cache(member.id).get("purchases", []) if not p.get("used", False)]))),
        ("Отзывов", str(count))
    ]
    x_offsets = [right_x+30, right_x+220]
    y_start = 140
    for i, (label, value) in enumerate(stats_data):
        row = i // 2
        col = i % 2
        x = x_offsets[col]
        y = y_start + row * 85
        draw.rounded_rectangle((x, y, x+160, y+60), fill=(255, 255, 255, 10), radius=12)
        draw.text((x+10, y+8), label, font=font_meta, fill=(150, 150, 150))
        draw.text((x+10, y+32), value, font=font_stats, fill=(255, 255, 255))

    history_title_y = 320
    draw.text((right_x+210, history_title_y), "ИСТОРИЯ ОПЕРАЦИЙ", font=font_progress, fill=(200, 200, 200), anchor="mt")
    y_offset = 360
    for h in history:
        date_str = datetime.fromtimestamp(h["date"]).strftime("%d.%m.%Y")
        amount = h["amount"]
        sign = "+" if amount >= 0 else ""
        color = (100, 200, 100) if amount >= 0 else (200, 100, 100)
        line = f"{date_str}  {sign}{amount} DC"
        draw.text((right_x+40, y_offset), line, font=font_history, fill=color)
        y_offset += 30

    draw.line((right_x+40, y_offset+10, right_x+380, y_offset+10), fill=(255,255,255,20), width=2)
    draw.text((right_x+210, y_offset+30), f"Всего заработано: {total_earned} DC", font=font_meta, fill=(200, 200, 200), anchor="mt")

    with io.BytesIO() as output:
        img.save(output, format="PNG")
        return output.getvalue()

async def get_profile_image(member) -> bytes:
    await download_background()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, generate_profile_image, member)

# Для совместимости с импортом generate_profile_image
generate_profile_image = get_profile_image
