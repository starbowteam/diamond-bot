# -*- coding: utf-8 -*-
import os
import io
import json
import textwrap
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import disnake
from core.utils import CONFIG, DATA_DIR, ADD_DIR, logger, FILES, load_json

# ============================================================
# Конфигурация ролей
# ============================================================
ROLE_CONFIG = {
    "none": {"label": "НЕТ РОЛИ", "text_color": (136,136,136), "progress_color": (136,136,136)},
    "bronze": {"label": "BRONZE BUYER", "text_color": (209,86,64), "progress_color": (209,86,64)},
    "silver": {"label": "SILVER BUYER", "text_color": (176,176,176), "progress_color": (176,176,176)},
    "gold": {"label": "GOLD BUYER", "text_color": (174,121,17), "progress_color": (174,121,17)},
    "diamond": {"label": "DIAMOND BUYER", "text_color": (20,155,208), "progress_color": (20,155,208)},
    "emerald": {"label": "EMERALD BUYER", "text_color": (61,158,8), "progress_color": (61,158,8)},
    "amethyst": {"label": "AMETHYST BUYER", "text_color": (216,142,223), "progress_color": (216,142,223)},
    "legendary": {"label": "LEGENDARY BUYER", "text_color": (197,28,178), "progress_color": (197,28,178)},
    "pka": {"label": "ПОКУПАТЕЛЬ ВЕКА", "text_color": (179,217,255), "progress_color": (179,217,255)}
}

THRESHOLDS = [0, 1, 3, 5, 9, 13, 18, 24, 26]
ROLE_KEYS = ["none", "bronze", "silver", "gold", "diamond", "emerald", "amethyst", "legendary", "pka"]

def get_role_info(count):
    for i, th in enumerate(THRESHOLDS):
        if count < th:
            idx = i - 1 if i > 0 else 0
            key = ROLE_KEYS[idx]
            return key, ROLE_CONFIG[key]
    return "pka", ROLE_CONFIG["pka"]

def get_progress(count):
    if count >= 26: return 100
    for i, th in enumerate(THRESHOLDS):
        if count < th:
            prev = THRESHOLDS[i-1] if i > 0 else 0
            next_th = th
            if next_th == prev: return 0
            return min(int((count - prev) / (next_th - prev) * 100), 100)
    return 100

def get_next_label(count):
    if count >= 26: return "Максимальная роль"
    for i, th in enumerate(THRESHOLDS):
        if count < th:
            rem = th - count
            return f"Осталось {rem} отзыв" + ("а" if rem > 1 else "")
    return ""

# ============================================================
# Загрузка фона
# ============================================================
BG_URL = "https://cdn.discordapp.com/attachments/1527006158282555412/1537294943805112471/image.png?ex=6a7e84fc&is=6a7d337c&hm=a6713ca389191d2ed4d9bac61250791a22e8afdd7274d92ffde031145359cd13&"
BG_PATH = os.path.join(ADD_DIR, "profile_bg.png")

def ensure_background():
    if not os.path.exists(BG_PATH):
        try:
            r = requests.get(BG_URL, timeout=10)
            with open(BG_PATH, "wb") as f:
                f.write(r.content)
            logger.info("Фон профиля скачан")
        except Exception as e:
            logger.error(f"Не удалось скачать фон: {e}")
            img = Image.new("RGB", (1200, 700), color="#1a1a2e")
            img.save(BG_PATH)

# ============================================================
# Генерация профиля
# ============================================================
async def generate_profile_image(member: disnake.Member, review_count: int, balance: int, purchases: list, history: list):
    ensure_background()
    W, H = 1200, 700
    bg = Image.open(BG_PATH).convert("RGBA").resize((W, H), Image.Resampling.LANCZOS)

    # Оверлей с blur
    overlay = bg.copy().filter(ImageFilter.GaussianBlur(radius=3))
    mask = Image.new("RGBA", (W, H), (0, 0, 0, 180))
    overlay = Image.alpha_composite(overlay, mask)

    draw = ImageDraw.Draw(overlay)
    font_path = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")
    font_default = os.path.join(ADD_DIR, "ProximaNova-ExtraBold.ttf")  # fallback

    def get_font(size):
        try:
            return ImageFont.truetype(font_path, size) if os.path.exists(font_path) else ImageFont.load_default()
        except:
            return ImageFont.load_default()

    # ---- Аватар ----
    avatar_size = 180
    try:
        avatar_url = member.display_avatar.replace(format="png", size=256).url
        resp = requests.get(avatar_url, timeout=5)
        avatar_img = Image.open(io.BytesIO(resp.content)).convert("RGBA").resize((avatar_size, avatar_size))
        mask_avatar = Image.new("L", (avatar_size, avatar_size), 0)
        draw_mask = ImageDraw.Draw(mask_avatar)
        draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img = Image.composite(avatar_img, Image.new("RGBA", (avatar_size, avatar_size), (0,0,0,0)), mask_avatar)
        avatar_x, avatar_y = 100, (H - avatar_size)//2 - 20
        overlay.paste(avatar_img, (avatar_x, avatar_y), avatar_img)
    except:
        pass

    # ---- Имя ----
    username = member.display_name
    draw.text((avatar_x + avatar_size//2, avatar_y + avatar_size + 10), username,
              font=get_font(44), fill=(255,255,255,255), anchor="mt")

    # ---- Роль ----
    role_key, role_info = get_role_info(review_count)
    role_label = role_info["label"]
    role_color = role_info["text_color"]
    draw.text((avatar_x + avatar_size//2, avatar_y + avatar_size + 70), role_label,
              font=get_font(36), fill=role_color, anchor="mt")

    # ---- Отзывы + баланс ----
    draw.text((avatar_x + avatar_size//2, avatar_y + avatar_size + 120),
              f"{review_count} отзывов    {balance} DC",
              font=get_font(24), fill=(220,220,220,255), anchor="mt")

    # ---- Прогресс ----
    progress = get_progress(review_count)
    bar_x, bar_y = avatar_x, avatar_y + avatar_size + 170
    bar_w, bar_h = 480, 26
    draw.rounded_rectangle((bar_x, bar_y, bar_x+bar_w, bar_y+bar_h), radius=40,
                           fill=(50,50,50,180), outline=(255,255,255,60), width=1)
    if progress > 0:
        fill_w = int(bar_w * progress / 100)
        prog_color = role_info["progress_color"]
        draw.rounded_rectangle((bar_x, bar_y, bar_x+fill_w, bar_y+bar_h), radius=40,
                               fill=prog_color, outline=None)
    draw.text((bar_x + bar_w - 40, bar_y + bar_h//2), f"{progress}%",
              font=get_font(18), fill=(0,0,0,200), anchor="rm")
    draw.text((bar_x, bar_y + bar_h + 10), get_next_label(review_count),
              font=get_font(16), fill=(200,200,200,255), anchor="la")

    # ---- Meta ----
    meta_text = f"ID: {member.id}   Высшая роль: {member.top_role.name}   С: {member.joined_at.strftime('%d.%m.%Y')}"
    draw.text((avatar_x, bar_y + bar_h + 60), meta_text,
              font=get_font(14), fill=(180,180,180,255), anchor="la")

    # ---- Правая часть ----
    right_x, right_y = 750, 50
    right_w, right_h = 400, 600
    right_bg = Image.new("RGBA", (right_w, right_h), (255,255,255,20)).filter(ImageFilter.GaussianBlur(radius=2))
    overlay.paste(right_bg, (right_x, right_y), right_bg)

    draw.text((right_x + right_w//2, right_y + 30), "СТАТИСТИКА",
              font=get_font(26), fill=(220,220,220,255), anchor="mt")

    grid_x, grid_y = right_x + 20, right_y + 80
    cell_w, cell_h = (right_w - 60)//2, 70
    stats_data = [
        ("Баланс DC", f"{balance}"),
        ("Покупок", str(len(purchases))),
        ("Неиспользовано", str(sum(1 for p in purchases if not p.get("used", False)))),
        ("Отзывов", str(review_count))
    ]
    for i, (label, value) in enumerate(stats_data):
        cx = grid_x + (i % 2) * (cell_w + 20)
        cy = grid_y + (i // 2) * (cell_h + 15)
        draw.rounded_rectangle((cx, cy, cx+cell_w, cy+cell_h), radius=16,
                               fill=(255,255,255,20), outline=(255,255,255,30), width=1)
        draw.text((cx + cell_w//2, cy + 10), label,
                  font=get_font(13), fill=(170,170,170,255), anchor="mt")
        draw.text((cx + cell_w//2, cy + 35), value,
                  font=get_font(28), fill=(255,255,255,255), anchor="mt")

    # ---- История ----
    history_y = grid_y + 2 * (cell_h + 15) + 30
    draw.text((right_x + right_w//2, history_y), "ИСТОРИЯ ОПЕРАЦИЙ",
              font=get_font(22), fill=(220,220,220,255), anchor="mt")
    history_start_y = history_y + 40
    for idx, entry in enumerate(history[-5:]):
        y = history_start_y + idx * 35
        date_str = datetime.fromtimestamp(entry["date"]).strftime("%d.%m.%Y")
        amount = entry["amount"]
        sign = "+" if amount > 0 else ""
        color = (125, 237, 159) if amount > 0 else (255, 107, 107)
        draw.text((right_x + 20, y), date_str,
                  font=get_font(16), fill=(200,200,200,255), anchor="la")
        draw.text((right_x + right_w - 20, y), f"{sign}{amount} DC",
                  font=get_font(16), fill=color, anchor="ra")

    total_earned = sum(e["amount"] for e in history[-5:] if e["amount"] > 0)
    draw.text((right_x + right_w//2, history_start_y + len(history[-5:])*35 + 20),
              f"Всего заработано: {total_earned} DC",
              font=get_font(18), fill=(200,200,200,255), anchor="mt")

    output_path = os.path.join(DATA_DIR, f"profile_{member.id}.png")
    overlay.save(output_path, "PNG")
    return output_path
