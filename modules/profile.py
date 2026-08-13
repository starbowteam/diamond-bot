# -*- coding: utf-8 -*-
import os
import io
import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from datetime import datetime
import disnake
from core.utils import ADD_DIR, DATA_DIR, logger, get_dc_cache, load_json, FILES, CONFIG

# ============================================================
# Константы для профиля
# ============================================================
PROFILE_WIDTH = 1200
PROFILE_HEIGHT = 700
BG_PATH = os.path.join(ADD_DIR, "profile_bg.png")
FONT_PATH = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")

# Цвета для ролей (основной цвет для текста и прогресс-бара)
ROLE_COLORS = {
    "none": (136, 136, 136),
    "bronze": (209, 86, 64),
    "silver": (176, 176, 176),
    "gold": (174, 121, 17),
    "diamond": (20, 155, 208),
    "emerald": (61, 158, 8),
    "amethyst": (216, 142, 223),
    "legendary": (197, 28, 178),
    "pka": (179, 217, 255)
}

# Отображение роли в текст
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

# Пороги ролей
ROLE_THRESHOLDS = {
    "bronze": 1,
    "silver": 3,
    "gold": 5,
    "diamond": 9,
    "emerald": 13,
    "amethyst": 18,
    "legendary": 24,
    "pka": 26
}

# ============================================================
# Вспомогательные функции
# ============================================================
def get_role_key(count: int) -> str:
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
    """Возвращает (название следующей роли, порог, прогресс в %)."""
    if count >= 26:
        return ("Максимальная роль", 26, 100)
    thresholds = [
        (1, "Бронзовый покупатель"),
        (3, "Серебряный покупатель"),
        (5, "Золотой покупатель"),
        (9, "Алмазный покупатель"),
        (13, "Изумрудный покупатель"),
        (18, "Аметистовый покупатель"),
        (24, "Легендарный покупатель"),
        (26, "Покупатель Века")
    ]
    for thresh, name in thresholds:
        if count < thresh:
            progress = int((count / thresh) * 100)
            if progress > 100:
                progress = 100
            return (name, thresh, progress)
    return ("Максимальная роль", 26, 100)

def get_role_color(role_key: str) -> tuple:
    return ROLE_COLORS.get(role_key, (255, 255, 255))

# ============================================================
# Основная функция генерации
# ============================================================
async def generate_profile_image(member: disnake.Member, avatar_bytes: bytes) -> io.BytesIO:
    """Генерирует изображение профиля и возвращает BytesIO."""
    # Загружаем фон
    try:
        bg = Image.open(BG_PATH).convert("RGBA")
        bg = bg.resize((PROFILE_WIDTH, PROFILE_HEIGHT), Image.LANCZOS)
    except Exception:
        # Фон не найден – создаём чёрный
        bg = Image.new("RGBA", (PROFILE_WIDTH, PROFILE_HEIGHT), (20, 20, 30, 255))

    # Накладываем полупрозрачный оверлей
    overlay = Image.new("RGBA", (PROFILE_WIDTH, PROFILE_HEIGHT), (0, 0, 0, 180))
    bg = Image.alpha_composite(bg, overlay)

    draw = ImageDraw.Draw(bg)

    # Загружаем шрифт
    try:
        font_big = ImageFont.truetype(FONT_PATH, 44)
        font_medium = ImageFont.truetype(FONT_PATH, 36)
        font_small = ImageFont.truetype(FONT_PATH, 26)
        font_stats = ImageFont.truetype(FONT_PATH, 28)
        font_progress = ImageFont.truetype(FONT_PATH, 18)
    except:
        font_big = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_stats = ImageFont.load_default()
        font_progress = ImageFont.load_default()

    # Получаем данные пользователя
    user_id = member.id
    dc_data = get_dc_cache(user_id)
    balance = dc_data.get("balance", 0)
    history = dc_data.get("history", [])
    purchases = dc_data.get("purchases", [])
    unused = [p for p in purchases if not p.get("used", False)]

    # Количество отзывов
    counts = load_json(FILES["review_counts"], {})
    reviews = counts.get(str(user_id), 0)

    # Определяем роль
    role_key = get_role_key(reviews)
    role_color = get_role_color(role_key)
    role_text = ROLE_NAMES.get(role_key, "НЕТ РОЛИ")

    # Следующая роль и прогресс
    next_role_name, next_threshold, progress = get_next_role(reviews)
    if progress > 100:
        progress = 100

    # Левая часть (профиль)
    # Аватар
    try:
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        avatar_img = avatar_img.resize((180, 180), Image.LANCZOS)
        # Делаем круглую маску
        mask = Image.new("L", (180, 180), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 180, 180), fill=255)
        avatar_img.putalpha(mask)
        # Позиция: центр по горизонтали, сверху отступ ~50
        avatar_x = 150 - 90  # центр левой части примерно 150
        avatar_y = 70
        bg.paste(avatar_img, (avatar_x, avatar_y), avatar_img)
    except Exception as e:
        logger.error(f"Не удалось обработать аватар: {e}")

    # Никнейм
    username = member.display_name
    if len(username) > 20:
        username = username[:18] + "…"
    draw.text((150, 270), f"@{username}", font=font_big, fill=(255, 255, 255), anchor="mt")

    # Роль
    role_display = role_text
    draw.text((150, 320), role_display, font=font_medium, fill=role_color, anchor="mt")

    # Отзывы и баланс
    draw.text((150, 375), f"{reviews} отзывов", font=font_small, fill=(200, 200, 200), anchor="mt")
    draw.text((150, 415), f"{balance} DC", font=font_small, fill=(200, 200, 200), anchor="mt")

    # Прогресс-бар
    bar_x = 50
    bar_y = 470
    bar_width = 200
    bar_height = 26
    # Фон бара
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_width, bar_y + bar_height), radius=13, fill=(60, 60, 80), outline=(255,255,255,100), width=2)
    # Заполнение
    fill_width = int(bar_width * progress / 100)
    if fill_width > 0:
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_width, bar_y + bar_height), radius=13, fill=role_color, outline=(255,255,255,50), width=1)

    # Подпись прогресса
    draw.text((bar_x + bar_width // 2, bar_y + bar_height + 10), f"{progress}%", font=font_progress, fill=(200, 200, 200), anchor="mt")
    draw.text((bar_x + bar_width // 2, bar_y - 20), f"До {next_role_name}", font=font_progress, fill=(200, 200, 200), anchor="mt")

    # Правая часть (статистика)
    # Правая колонка начинается с x = 550, ширина 500
    right_x = 550
    right_y = 70
    # Заголовок
    draw.text((right_x + 250, right_y), "СТАТИСТИКА", font=font_medium, fill=(220, 220, 220), anchor="mt")
    right_y += 45

    # Сетка 2x2
    stats = [
        ("Баланс DC", str(balance)),
        ("Покупок", str(len(purchases))),
        ("Неиспользовано", str(len(unused))),
        ("Отзывов", str(reviews))
    ]
    grid_x = right_x
    grid_y = right_y
    for i, (label, value) in enumerate(stats):
        col = i % 2
        row = i // 2
        bx = grid_x + col * 250
        by = grid_y + row * 80
        # Рамка
        draw.rounded_rectangle((bx, by, bx + 220, by + 70), radius=16, fill=(255, 255, 255, 20), outline=(255,255,255,30), width=1)
        draw.text((bx + 110, by + 25), label, font=font_progress, fill=(180, 180, 180), anchor="mt")
        draw.text((bx + 110, by + 50), value, font=font_stats, fill=(255, 255, 255), anchor="mt")
    right_y += 170

    # История операций
    draw.text((right_x + 250, right_y), "ИСТОРИЯ ОПЕРАЦИЙ", font=font_small, fill=(220, 220, 220), anchor="mt")
    right_y += 35
    history_items = history[-5:] if history else []
    history_y = right_y
    for item in reversed(history_items):
        date_str = datetime.fromtimestamp(item["date"]).strftime("%d.%m.%Y")
        amount = item["amount"]
        sign = "+" if amount > 0 else ""
        color = (125, 235, 160) if amount > 0 else (255, 110, 110)
        line = f"{date_str}  {sign}{amount} DC"
        draw.text((right_x + 20, history_y), line, font=font_progress, fill=color)
        history_y += 30

    # Итого заработано
    total_earned = sum(h["amount"] for h in history if h["amount"] > 0)
    draw.text((right_x + 250, history_y + 20), f"Всего заработано: {total_earned} DC", font=font_progress, fill=(200, 200, 200), anchor="mt")

    # Сохраняем в BytesIO
    img_bytes = io.BytesIO()
    bg.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes
