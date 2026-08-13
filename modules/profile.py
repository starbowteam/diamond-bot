# -*- coding: utf-8 -*-
import os
import io
import json
import requests
import textwrap
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import disnake
from core.utils import CONFIG, DATA_DIR, ADD_DIR, logger, FILES, load_json, get_roles_for_count
from modules.dc import get_user_dc_data, get_user_balance

# ============================================================
# Конфигурация ролей (цвета для текста и прогресс-бара)
# ============================================================
ROLE_CONFIG = {
    "none": {
        "label": "НЕТ РОЛИ",
        "text_color": "#888888",
        "progress_color": "#888888",
        "threshold": 0
    },
    "bronze": {
        "label": "BRONZE BUYER",
        "text_color": "#d15640",
        "progress_color": "#d15640",
        "threshold": 1
    },
    "silver": {
        "label": "SILVER BUYER",
        "text_color": "#b0b0b0",
        "progress_color": "#b0b0b0",
        "threshold": 3
    },
    "gold": {
        "label": "GOLD BUYER",
        "text_color": "#ae7911",
        "progress_color": "#ae7911",
        "threshold": 5
    },
    "diamond": {
        "label": "DIAMOND BUYER",
        "text_color": "#149bd0",
        "progress_color": "#149bd0",
        "threshold": 9
    },
    "emerald": {
        "label": "EMERALD BUYER",
        "text_color": "#3d9e08",
        "progress_color": "#3d9e08",
        "threshold": 13
    },
    "amethyst": {
        "label": "AMETHYST BUYER",
        "text_color": "#d88edf",
        "progress_color": "#d88edf",
        "threshold": 18
    },
    "legendary": {
        "label": "LEGENDARY BUYER",
        "text_color": "#c51cb2",
        "progress_color": "#c51cb2",
        "threshold": 24
    },
    "pka": {
        "label": "ПОКУПАТЕЛЬ ВЕКА",
        "text_color": "#b3d9ff",
        "progress_color": "#b3d9ff",
        "threshold": 26
    }
}

# Пороги для прогресса (список в порядке возрастания)
THRESHOLDS = [0, 1, 3, 5, 9, 13, 18, 24, 26]
ROLE_KEYS = ["none", "bronze", "silver", "gold", "diamond", "emerald", "amethyst", "legendary", "pka"]

def get_role_info(count: int):
    """Возвращает ключ роли, название и цвет на основе количества отзывов."""
    for i, th in enumerate(THRESHOLDS):
        if count < th:
            idx = i - 1 if i > 0 else 0
            key = ROLE_KEYS[idx]
            return key, ROLE_CONFIG[key]
    # Если больше максимального порога
    key = "pka"
    return key, ROLE_CONFIG[key]

def get_progress(count: int):
    """Возвращает прогресс в процентах (0-100) до следующей роли."""
    if count >= 26:
        return 100
    for i, th in enumerate(THRESHOLDS):
        if count < th:
            prev = THRESHOLDS[i-1] if i > 0 else 0
            next_th = th
            if next_th == prev:
                return 0
            progress = (count - prev) / (next_th - prev) * 100
            return min(int(progress), 100)
    return 100

def get_next_role_label(count: int):
    """Возвращает текст для блока 'До следующей роли'."""
    if count >= 26:
        return "Максимальная роль"
    for i, th in enumerate(THRESHOLDS):
        if count < th:
            remaining = th - count
            if remaining == 1:
                return f"Осталось {remaining} отзыв"
            return f"Осталось {remaining} отзыва"
    return ""

# ============================================================
# Загрузка фонового изображения
# ============================================================
BG_URL = "https://cdn.discordapp.com/attachments/1527006158282555412/1537294943805112471/image.png?ex=6a7e84fc&is=6a7d337c&hm=a6713ca389191d2ed4d9bac61250791a22e8afdd7274d92ffde031145359cd13&"
BG_PATH = os.path.join(ADD_DIR, "profile_bg.png")

def ensure_background():
    """Скачивает фон, если его нет локально."""
    if not os.path.exists(BG_PATH):
        try:
            r = requests.get(BG_URL, timeout=10)
            with open(BG_PATH, "wb") as f:
                f.write(r.content)
            logger.info("Фон профиля скачан")
        except Exception as e:
            logger.error(f"Не удалось скачать фон профиля: {e}")
            # Создаём заглушку – тёмный фон
            img = Image.new("RGB", (1200, 700), color="#1a1a2e")
            img.save(BG_PATH)

# ============================================================
# Основная функция генерации изображения
# ============================================================
async def generate_profile_image(member: disnake.Member, review_count: int, balance: int, purchases: list, history: list):
    """
    Генерирует изображение профиля и возвращает путь к файлу.
    """
    ensure_background()

    # Размеры
    W, H = 1200, 700
    # Загружаем фон
    bg = Image.open(BG_PATH).convert("RGBA")
    bg = bg.resize((W, H), Image.Resampling.LANCZOS)

    # Создаём оверлей с прозрачностью и размытием
    # Делаем копию фона, размываем, затем накладываем полупрозрачный слой
    overlay = bg.copy()
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=3))
    # Накладываем полупрозрачный чёрный слой
    mask = Image.new("RGBA", (W, H), (0, 0, 0, 180))  # альфа 180
    overlay = Image.alpha_composite(overlay, mask)
    # Теперь overlay – это финальный фон

    # Загружаем шрифт
    font_path = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
    if not os.path.exists(font_path):
        # fallback шрифт
        font_path = None

    def get_font(size):
        try:
            return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
        except:
            return ImageFont.load_default()

    # Рисуем на overlay
    draw = ImageDraw.Draw(overlay)

    # ========== ЛЕВАЯ ЧАСТЬ ==========
    # Аватар
    avatar_size = 180
    try:
        avatar_url = member.display_avatar.replace(format="png", size=256).url
        resp = requests.get(avatar_url, timeout=5)
        avatar_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
        # Обрезаем в круг
        mask_avatar = Image.new("L", (avatar_size, avatar_size), 0)
        draw_mask = ImageDraw.Draw(mask_avatar)
        draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img = Image.composite(avatar_img, Image.new("RGBA", (avatar_size, avatar_size), (0,0,0,0)), mask_avatar)
        # Позиция аватара: левая часть, центрируем по вертикали, x=100
        avatar_x = 100
        avatar_y = (H - avatar_size) // 2 - 20  # сдвинем вверх
        overlay.paste(avatar_img, (avatar_x, avatar_y), avatar_img)
    except Exception as e:
        logger.error(f"Не удалось загрузить аватар: {e}")

    # Никнейм
    username = member.display_name
    username_font = get_font(44)
    # рисуем текст с тенью для читаемости
    draw.text((avatar_x + avatar_size//2 - len(username)*12, avatar_y + avatar_size + 10),
              username, font=username_font, fill=(255,255,255,255), anchor="mt")

    # Роль покупателя
    role_key, role_info = get_role_info(review_count)
    role_label = role_info["label"]
    role_color = role_info["text_color"]
    role_font = get_font(36)
    draw.text((avatar_x + avatar_size//2, avatar_y + avatar_size + 70),
              role_label, font=role_font, fill=role_color, anchor="mt")

    # Отзывы и баланс (строка)
    stats_text = f"{review_count} отзывов    {balance} DC"
    stats_font = get_font(24)
    draw.text((avatar_x + avatar_size//2, avatar_y + avatar_size + 120),
              stats_text, font=stats_font, fill=(220,220,220,255), anchor="mt")

    # Прогресс-бар
    progress = get_progress(review_count)
    progress_label = get_next_role_label(review_count)
    # Рисуем полосу
    bar_x = avatar_x
    bar_y = avatar_y + avatar_size + 170
    bar_w = 480
    bar_h = 26

    # Фон полосы
    draw.rounded_rectangle((bar_x, bar_y, bar_x+bar_w, bar_y+bar_h), radius=40, fill=(50,50,50,180), outline=(255,255,255,60), width=1)
    # Заполнение
    fill_w = int(bar_w * progress / 100)
    if fill_w > 0:
        prog_color = role_info["progress_color"]
        # конвертируем hex в RGB
        prog_color_rgb = tuple(int(prog_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
        draw.rounded_rectangle((bar_x, bar_y, bar_x+fill_w, bar_y+bar_h), radius=40, fill=prog_color_rgb, outline=None)

    # Текст процента
    percent_text = f"{progress}%"
    draw.text((bar_x + bar_w - 40, bar_y + bar_h//2), percent_text, font=get_font(18), fill=(0,0,0,200), anchor="rm")

    # Подпись прогресса
    draw.text((bar_x, bar_y + bar_h + 10), progress_label, font=get_font(16), fill=(200,200,200,255), anchor="la")

    # Meta-info (ID, высшая роль, дата)
    meta_y = bar_y + bar_h + 60
    meta_text = f"ID: {member.id}   Высшая роль: {member.top_role.name}   С: {member.joined_at.strftime('%d.%m.%Y')}"
    meta_font = get_font(14)
    draw.text((avatar_x, meta_y), meta_text, font=meta_font, fill=(180,180,180,255), anchor="la")

    # ========== ПРАВАЯ ЧАСТЬ ==========
    right_x = 750
    right_y = 50
    right_w = 400
    right_h = 600
    # Прямоугольник с прозрачностью и размытием
    # Используем отдельный слой
    right_bg = Image.new("RGBA", (right_w, right_h), (255,255,255,20))
    right_bg = right_bg.filter(ImageFilter.GaussianBlur(radius=2))
    overlay.paste(right_bg, (right_x, right_y), right_bg)

    # Заголовок "СТАТИСТИКА"
    draw.text((right_x + right_w//2, right_y + 30), "СТАТИСТИКА", font=get_font(26), fill=(220,220,220,255), anchor="mt")

    # Сетка 2x2
    grid_x = right_x + 20
    grid_y = right_y + 80
    cell_w = (right_w - 60) // 2
    cell_h = 70
    stats_data = [
        ("Баланс DC", f"{balance}"),
        ("Покупок", str(len(purchases))),
        ("Неиспользовано", str(sum(1 for p in purchases if not p.get("used", False)))),
        ("Отзывов", str(review_count))
    ]
    for i, (label, value) in enumerate(stats_data):
        cx = grid_x + (i % 2) * (cell_w + 20)
        cy = grid_y + (i // 2) * (cell_h + 15)
        # Фон ячейки
        draw.rounded_rectangle((cx, cy, cx+cell_w, cy+cell_h), radius=16, fill=(255,255,255,20), outline=(255,255,255,30), width=1)
        # Лейбл
        draw.text((cx + cell_w//2, cy + 10), label, font=get_font(13), fill=(170,170,170,255), anchor="mt")
        # Значение
        draw.text((cx + cell_w//2, cy + 35), value, font=get_font(28), fill=(255,255,255,255), anchor="mt")

    # История операций
    history_y = grid_y + 2 * (cell_h + 15) + 30
    draw.text((right_x + right_w//2, history_y), "ИСТОРИЯ ОПЕРАЦИЙ", font=get_font(22), fill=(220,220,220,255), anchor="mt")

    history_start_y = history_y + 40
    history_data = history[-5:] if history else []
    for idx, entry in enumerate(history_data):
        y = history_start_y + idx * 35
        date_str = datetime.fromtimestamp(entry["date"]).strftime("%d.%m.%Y")
        amount = entry["amount"]
        sign = "+" if amount > 0 else ""
        color = (125, 237, 159) if amount > 0 else (255, 107, 107)
        draw.text((right_x + 20, y), date_str, font=get_font(16), fill=(200,200,200,255), anchor="la")
        draw.text((right_x + right_w - 20, y), f"{sign}{amount} DC", font=get_font(16), fill=color, anchor="ra")

    # Всего заработано
    total_earned = sum(entry["amount"] for entry in history_data if entry["amount"] > 0)
    total_y = history_start_y + len(history_data) * 35 + 20
    draw.text((right_x + right_w//2, total_y), f"Всего заработано: {total_earned} DC", font=get_font(18), fill=(200,200,200,255), anchor="mt")

    # Сохраняем изображение
    output_path = os.path.join(DATA_DIR, f"profile_{member.id}.png")
    overlay.save(output_path, "PNG")
    logger.info(f"Профиль сохранён: {output_path}")
    return output_path
