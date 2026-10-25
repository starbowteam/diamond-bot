# -*- coding: utf-8 -*-
import os
import io
import re
import ast
import time
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List

import disnake
from disnake import ui

from core.utils import db, cur, logger

LOG_CHANNEL_ID          = 1530453871581855744
GIVEAWAY_CHANNEL_ID     = 1462390938851741923
STAFF_PANEL_CHANNEL_ID  = 1551276116679860314
REPORT_DM_USER_ID       = 796293832751972352
REVIEW_CHANNEL_ID       = 1462074763437543435

GIVEAWAY_FULL_ROLES = [
    1530823425764098058,
    1530822331188903966,
    1127428607606796294,
    1471844291595731016,
]

MSK = timezone(timedelta(hours=3))

P = "\u3164"  # Невидимый пробел для кнопки

GIVEAWAY_TEMPLATES = {
    "100":  {"prize": "100 DC",  "amount": 100,  "winners": 1,
             "description": "🎉 Быстрый розыгрыш 100 Diamond Coins! Небольшой приз — хороший шанс испытать удачу. Жми участвовать!"},
    "150":  {"prize": "150 DC",  "amount": 150,  "winners": 1,
             "description": "🎉 Стандартный розыгрыш 150 DC для всех! Отличный стартовый приз на любые нужды магазина. Заходи и участвуй!"},
    "350":  {"prize": "350 DC",  "amount": 350,  "winners": 1,
             "description": "🎉 Розыгрыш 350 DC — средний куш для настоящих ценителей! Хорошая сумма для любых покупок. Не упусти свой шанс!"},
    "400":  {"prize": "400 DC",  "amount": 400,  "winners": 2,
             "description": "🎉 Розыгрыш 400 DC на двоих победителей! Двойной шанс сорвать куш. Участвуй — удача может улыбнуться именно тебе!"},
    "450":  {"prize": "450 DC",  "amount": 450,  "winners": 2,
             "description": "🎉 Розыгрыш 450 DC на двоих победителей! Щедрый приз для любителей адреналина. Жми участвовать и не упусти свой шанс!"},
    "600":  {"prize": "600 DC",  "amount": 600,  "winners": 3,
             "description": "🎉 Розыгрыш 600 DC на троих победителей! Тройной шанс на хороший куш. Собирайся с мыслями — и вперёд!"},
    "700":  {"prize": "700 DC",  "amount": 700,  "winners": 3,
             "description": "🎉 Розыгрыш 700 DC на троих победителей! Большие призы для активных ребят. Удача любит смелых!"},
    "1000": {"prize": "1000 DC", "amount": 1000, "winners": 5,
             "description": "👑 Большой розыгрыш 1000 DC на пятерых победителей! Крупный куш для настоящих везунчиков. Испытай судьбу — она может быть на твоей стороне!"},
    "1400": {"prize": "1400 DC", "amount": 1400, "winners": 7,
             "description": "🔥 Розыгрыш 1400 DC на семерых победителей! Огромная сумма — и множество шансов. Не упусти свой момент!"},
    "1800": {"prize": "1800 DC", "amount": 1800, "winners": 9,
             "description": "🔥 Розыгрыш 1800 DC на девятерых победителей! Щедрый куш для многих участников. Присоединяйся к борьбе за приз!"},
    "2400": {"prize": "2400 DC", "amount": 2400, "winners": 12,
             "description": "💎 Розыгрыш 2400 DC на двенадцать победителей! Массовый праздник щедрости для всех. Присоединяйся — весело и прибыльно!"},
    "3000": {"prize": "3000 DC", "amount": 3000, "winners": 15,
             "description": "💎 Розыгрыш 3000 DC на пятнадцать победителей! Большой призовой фонд для всех. Участвуй — и забери своё!"},
    "3600": {"prize": "3600 DC", "amount": 3600, "winners": 18,
             "description": "👑 Огромный розыгрыш 3600 DC на восемнадцать победителей! Максимум призов и возможностей. Докажи, что ты достоин!"},
    "4000": {"prize": "4000 DC", "amount": 4000, "winners": 20,
             "description": "👑 Мега-розыгрыш 4000 DC на двадцать победителей! Королевский куш и море победителей. Сражайся за свой шанс прямо сейчас!"},
}


def _ensure_col(table: str, column: str, ddl: str):
    try:
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if column not in cols:
            cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {ddl}')
            db.commit()
            logger.info(f"[giveaways] миграция: {table}.{column} добавлена")
    except Exception as e:
        logger.warning(f"[giveaways] миграция {table}.{column}: {e}")


def _init_tables():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS giveaways (
        giveaway_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id           INTEGER,
        channel_id         INTEGER,
        message_id         INTEGER,
        host_id            INTEGER,
        prize              TEXT,
        description        TEXT,
        winners_count      INTEGER,
        end_time           INTEGER,
        created_at         INTEGER,
        required_invites   INTEGER DEFAULT 0,
        participants       TEXT,
        winners            TEXT,
        status             TEXT,
        valid_participants TEXT,
        final_embed_id     INTEGER,
        auto_payout        INTEGER DEFAULT 0,
        payout_done        INTEGER DEFAULT 0
    );
    """)
    db.commit()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS giveaway_pending_payouts (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        giveaway_id    INTEGER,
        user_id        INTEGER,
        amount         INTEGER,
        dm_message_id  INTEGER DEFAULT 0,
        created_at     INTEGER,
        paid_at        INTEGER DEFAULT 0
    );
    """)
    db.commit()

    _ensure_col("giveaway_pending_payouts", "giveaway_id",   "giveaway_id INTEGER")
    _ensure_col("giveaway_pending_payouts", "user_id",       "user_id INTEGER")
    _ensure_col("giveaway_pending_payouts", "amount",        "amount INTEGER DEFAULT 0")
    _ensure_col("giveaway_pending_payouts", "dm_message_id", "dm_message_id INTEGER DEFAULT 0")
    _ensure_col("giveaway_pending_payouts", "created_at",    "created_at INTEGER DEFAULT 0")
    _ensure_col("giveaway_pending_payouts", "paid_at",       "paid_at INTEGER DEFAULT 0")

    _ensure_col("giveaways", "auto_payout", "auto_payout INTEGER DEFAULT 0")
    _ensure_col("giveaways", "payout_done", "payout_done INTEGER DEFAULT 0")

    try:
        cur.executescript("""
        CREATE INDEX IF NOT EXISTS idx_giveaways_message ON giveaways(message_id);
        CREATE INDEX IF NOT EXISTS idx_giveaways_status  ON giveaways(status);
        CREATE INDEX IF NOT EXISTS idx_gpp_user          ON giveaway_pending_payouts (user_id, paid_at);
        CREATE INDEX IF NOT EXISTS idx_gpp_giveaway      ON giveaway_pending_payouts (giveaway_id, paid_at);
        """)
        db.commit()
    except Exception as e:
        logger.warning(f"[giveaways] idx create: {e}")

_bot = None
_setup_done = False

def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())

def list_from_str(data):
    if not data: return []
    try: return ast.literal_eval(data)
    except Exception: return []

def str_from_list(data):
    return str(data)

def parse_duration(duration_str: str):
    match = re.fullmatch(r'(\d+)\s*([mhd])', duration_str.strip().lower())
    if not match: return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == 'm': return timedelta(minutes=value)
    if unit == 'h': return timedelta(hours=value)
    if unit == 'd': return timedelta(days=value)

def is_giveaway_staff(member: disnake.Member) -> bool:
    return any(r.id in GIVEAWAY_FULL_ROLES for r in member.roles)

def _parse_dc_amount(prize: str) -> int:
    if not prize: return 0
    m = re.search(r"(\d+)", prize)
    if not m: return 0
    try: return int(m.group(1))
    except Exception: return 0

async def log_discord(title: str, description: str, color: int = 0x00ff00, fields: list = None):
    if _bot is None: return
    try:
        channel = _bot.get_channel(LOG_CHANNEL_ID)
        if not channel: channel = await _bot.fetch_channel(LOG_CHANNEL_ID)
        if not channel: return
        embed = disnake.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
        if fields:
            for name, value, inline in fields: embed.add_field(name=name, value=value, inline=inline)
        await channel.send(embed=embed)
    except Exception as e:
        logger.warning(f"[giveaways.log] {e}")

IMG_BANNER_GW  = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735389618798632/image.png?backend=b2&ex=6ac53e4f&is=6ac3eccf&hm=ed4085879047dc6da3c00fc5a55edf0fe24d334f55f7086339380e0364a0ee09&"
IMG_STRIPE_GW  = "https://cdn.discordapp.com/attachments/1527006158282555412/1530795801268453447/pisk.png?ex=6a66e02f&is=6a658eaf&hm=79e41273327d2e1048ba42df62868cbb88f5b06b112ca864de2c7a02326523e9&"
IMG_BANNER_FIN = "https://cdn.discordapp.com/attachments/1527006158282555412/1556735391875203082/image.png?backend=b2&ex=6ac53e50&is=6ac3ecd0&hm=b331ed1665f81621e08ee916aaabaf5bb78430e86de1d7a51c0ce7072ec175f9&"
IMG_STRIPE     = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"

COLOR_GW = 6776679


def build_giveaway_embeds(prize, description, winners_count, participants_count, end_dt):
    """
    Активный розыгрыш — 2 embed'а:
      [0] — баннер
      [1] — заголовок + описание + время окончания + inline-поля
    """
    end_ts = int(end_dt.timestamp())

    desc_text = (description or "").strip()
    if not desc_text:
        desc_text = "Проводим розыгрыш — стоит нажать на кнопку участвовать, и больше условий нет!"

    # [0] Баннер
    embed_banner = disnake.Embed(color=COLOR_GW)
    embed_banner.set_image(url=IMG_BANNER_GW)

    # [1] Основной
    embed_main = disnake.Embed(
        title=f"Розыгрыш на {prize} ! 🎁",
        description=(
            f"> {desc_text}\n\n"
            f"Время окончания: <t:{end_ts}:R>"
        ),
        color=COLOR_GW,
    )
    embed_main.set_image(url=IMG_STRIPE_GW)
    
    embed_main.add_field(
        name="> **Участвуют:**",
        value=f"```{participants_count}```",
        inline=True,
    )
    embed_main.add_field(
        name="> **Победителей:**",
        value=f"```{winners_count}```",
        inline=True,
    )

    return [embed_banner, embed_main]


def build_finished_giveaway_embed(prize, description, participants_count, winners_mentions, end_dt):
    """
    Завершённый розыгрыш — 2 embed'а:
      [0] — баннер
      [1] — заголовок + описание + победители (пинги) + дата + кол-во участников
    """
    end_ts = int(end_dt.timestamp())
    date_str = datetime.fromtimestamp(end_ts, MSK).strftime("%d.%m.%Y")

    desc_text = (description or "").strip()
    if not desc_text:
        desc_text = "Розыгрыш завершён."

    # [0] Баннер
    embed_banner = disnake.Embed(color=COLOR_GW)
    embed_banner.set_image(url=IMG_BANNER_FIN)

    # [1] Основной
    embed_main = disnake.Embed(
        title=f"Розыгрыш на {prize} завершён! 🏆",
        description=(
            f"> {desc_text}\n\n"
            f"> **Победитель(и):** {winners_mentions}\n\n"
            f"> Спасибо за участие в розыгрышах! Ожидайте последующие розыгрыши!"
        ),
        color=COLOR_GW,
    )
    embed_main.set_image(url=IMG_STRIPE_GW)

    embed_main.add_field(
        name="> **Участвовали:**",
        value=f"```{participants_count}```",
        inline=True,
    )
    embed_main.add_field(
        name="> **Завершён:**",
        value=f"```{date_str}```",
        inline=True,
    )

    return [embed_banner, embed_main]


class JoinButton(disnake.ui.Button):
    def __init__(self):
        # 👇 Возвращаем классическую кнопку с эмодзи 🎉 в label
        super().__init__(
            label="ㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ🎉 Участвоватьㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤㅤ", 
            style=disnake.ButtonStyle.secondary,
            custom_id="giveaway_join",
        )

    async def callback(self, inter: disnake.MessageInteraction):
        try:
            row = cur.execute("SELECT * FROM giveaways WHERE message_id=? AND status='active'", (inter.message.id,)).fetchone()
            if not row: return await inter.response.send_message("❌ Розыгрыш не найден или завершён.", ephemeral=True)
            gid = row["giveaway_id"]
            participants = list_from_str(row["participants"])
            user_id = inter.user.id
            if user_id in participants: return await inter.response.send_message("🎊 Вы уже участвуете в розыгрыше!", ephemeral=True)
            participants.append(user_id)
            cur.execute("UPDATE giveaways SET participants=? WHERE giveaway_id=?", (str_from_list(participants), gid))
            db.commit()
            end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc)
            embeds = build_giveaway_embeds(row["prize"], row["description"], row["winners_count"], len(participants), end_dt)
            try: await inter.message.edit(embeds=embeds)
            except Exception: pass
            await inter.response.send_message("✅ Ты успешно присоединился к розыгрышу!", ephemeral=True)
            embed_dm = disnake.Embed(title="✅ Ты участвуешь в розыгрыше!", description=f"> **Приз:** {row['prize']}\n> **ID розыгрыша:** `{gid}`\n> **Участников:** {len(participants)}", color=0x00ff00)
            try: await inter.user.send(embed=embed_dm)
            except Exception: pass
        except Exception as e:
            logger.warning(f"[JoinButton] {e}")

class GiveawayView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(JoinButton())

class GiveawaySelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="・Начать розыгрыш", description="Создать розыгрыш вручную", emoji="<:__:1538399607699021895>", value="create"),
            disnake.SelectOption(label="・Шаблонные розыгрыши", description="Готовые шаблоны DC-розыгрышей", emoji="<:cakleb:1553236134316875846>", value="templates"),
            disnake.SelectOption(label="・Лист розыгрышей", description="Все существующие розыгрыши", emoji="<:banne1:1538551829246513312>", value="list"),
            disnake.SelectOption(label="・Завершить принудительно", description="Принудительно завершить розыгрыш", emoji="<:clear:1538561439491686410>", value="end"),
            disnake.SelectOption(label="・Перевыбрать победителя", description="Перевыбрать победителя", emoji="<:restart:1553231421190049813>", value="reroll"),
        ]
        super().__init__(placeholder="Выберите нужный пункт", min_values=1, max_values=1, options=options, custom_id="giveaway_select")

    async def callback(self, inter: disnake.MessageInteraction):
        if not is_giveaway_staff(inter.author):
            return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        await log_discord(title="🎮 Выбор в панели розыгрышей", description=f"> **Пользователь:** {inter.author.mention}\n> **Выбрано:** `{inter.data.values[0]}`", color=0x00aaff)
        value = inter.data.values[0]
        if value == "create":
            await inter.response.send_modal(GiveawayModal())
        elif value == "templates":
            await show_templates_panel(inter)
        elif value == "list":
            await inter.response.defer(ephemeral=True)
            await list_giveaways(inter)
        elif value == "end":
            await inter.response.send_modal(EndGiveawayModal())
        elif value == "reroll":
            await inter.response.send_modal(RerollModal())

class GiveawayPanelView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GiveawaySelect())

class GiveawayModal(ui.Modal):
    def __init__(self):
        components = [
            ui.TextInput(label="Приз", custom_id="prize", max_length=256),
            ui.TextInput(label="Описание", custom_id="description", style=disnake.TextInputStyle.paragraph, max_length=1024),
            ui.TextInput(label="Победителей (число)", custom_id="winners", max_length=3),
            ui.TextInput(label="Длительность (10m, 2h, 1d)", custom_id="duration", max_length=10, placeholder="Например: 30m, 2h, 7d"),
        ]
        super().__init__(title="Создание розыгрыша", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав на создание розыгрышей.", ephemeral=True)
        prize = inter.text_values["prize"].strip()
        description = inter.text_values["description"].strip()
        try:
            winners_count = int(inter.text_values["winners"].strip())
            if winners_count < 1: raise ValueError
        except ValueError: return await inter.response.send_message("❌ Поле 'Победителей' должно быть целым числом ≥ 1.", ephemeral=True)
        duration_td = parse_duration(inter.text_values["duration"])
        if duration_td is None: return await inter.response.send_message("❌ Неверный формат длительности. Примеры: `30m`, `2h`, `7d`", ephemeral=True)

        end_dt = datetime.now(MSK) + duration_td
        end_dt_utc = end_dt.astimezone(timezone.utc)
        end_time = int(end_dt_utc.timestamp())
        created_at = now_ts()
        embeds = build_giveaway_embeds(prize, description, winners_count, 0, end_dt_utc)

        await inter.response.send_message("⏳ Создаю розыгрыш...", ephemeral=True)
        channel = _bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel: return await inter.edit_original_message(content="❌ Канал для розыгрышей не найден.")
        msg = await channel.send(content="|| @everyone ||", embeds=embeds, view=GiveawayView())
        cur.execute("""INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, description, winners_count, end_time, created_at, required_invites, participants, winners, status, auto_payout, payout_done) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (inter.guild.id, channel.id, msg.id, inter.author.id, prize, description, winners_count, end_time, created_at, 0, "[]", "[]", "active", 0, 0))
        db.commit()
        gid = cur.lastrowid
        asyncio.create_task(schedule_end(gid))
        await inter.edit_original_message(content=f"✅ Розыгрыш создан! **ID: `{gid}`** (ручной — приз вручается вручную)")

async def get_valid_participants(gid: int, guild: disnake.Guild):
    row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return []
    participants = list_from_str(row["participants"])
    valid = []
    for uid in participants:
        member = guild.get_member(uid)
        if not member or member.bot: continue
        valid.append(uid)
    return list(set(valid))

async def schedule_end(gid: int):
    row = cur.execute("SELECT end_time FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return
    delay = row["end_time"] - now_ts()
    if delay > 0: await asyncio.sleep(delay)
    await finish_giveaway(gid)

async def _queue_pending_payouts(gid: int, row, winners: List[int]) -> int:
    auto_payout = row["auto_payout"]
    logger.info(f"[giveaways] _queue_pending_payouts: gid={gid} auto_payout={auto_payout} winners={winners}")

    if not auto_payout:
        logger.info(f"[giveaways] gid={gid}: РУЧНОЙ розыгрыш (auto_payout=0) — pending НЕ создаются")
        return 0

    if not winners:
        cur.execute("UPDATE giveaways SET payout_done=1 WHERE giveaway_id=?", (gid,))
        db.commit()
        logger.info(f"[giveaways] gid={gid}: winners пуст — выплат нет")
        return 0

    total_amount = _parse_dc_amount(row["prize"])
    logger.info(f"[giveaways] gid={gid}: prize='{row['prize']}' parsed={total_amount}")

    if total_amount <= 0:
        logger.warning(f"[giveaways] gid={gid}: не удалось распарсить сумму приза '{row['prize']}'")
        return 0

    share = total_amount // len(winners)
    logger.info(f"[giveaways] gid={gid}: share={share} (total={total_amount} / {len(winners)})")

    if share <= 0:
        logger.warning(f"[giveaways] gid={gid}: share={share} — выплачивать нечего")
        return 0

    now = now_ts()
    for uid in winners:
        cur.execute(
            "INSERT INTO giveaway_pending_payouts "
            "(giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) "
            "VALUES (?, ?, ?, 0, ?, 0)",
            (gid, uid, share, now),
        )
        logger.info(f"[giveaways] pending создан: gid={gid} uid={uid} amount={share}")
    cur.execute("UPDATE giveaways SET payout_done=1 WHERE giveaway_id=?", (gid,))
    db.commit()
    return share

async def process_pending_payouts(bot, user_id: int) -> int:
    logger.info(f"[giveaways] process_pending_payouts START: user={user_id}")

    rows = cur.execute(
        "SELECT id, giveaway_id, amount, dm_message_id "
        "FROM giveaway_pending_payouts WHERE user_id=? AND paid_at=0",
        (user_id,),
    ).fetchall()

    logger.info(f"[giveaways] process_pending_payouts: найдено pending={len(rows)}")

    if not rows:
        try:
            won_giveaways = cur.execute(
                "SELECT giveaway_id, prize, winners FROM giveaways "
                "WHERE status='finished' AND auto_payout=1"
            ).fetchall()
            logger.info(f"[giveaways] fallback: проверяю {len(won_giveaways)} завершённых шаблонных розыгрышей")

            for g in won_giveaways:
                winners = list_from_str(g["winners"])
                if user_id not in winners:
                    continue

                exists = cur.execute(
                    "SELECT paid_at FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=?",
                    (g["giveaway_id"], user_id)
                ).fetchone()

                if exists and exists["paid_at"]:
                    logger.info(f"[giveaways] fallback: gid={g['giveaway_id']} uid={user_id} уже выплачено")
                    continue
                if exists:
                    logger.info(f"[giveaways] fallback: gid={g['giveaway_id']} uid={user_id} pending уже существует")
                    continue

                amount = _parse_dc_amount(g["prize"]) // max(len(winners), 1)
                if amount <= 0:
                    logger.warning(f"[giveaways] fallback: gid={g['giveaway_id']} amount=0 (prize={g['prize']}, winners={len(winners)})")
                    continue

                cur.execute(
                    "INSERT INTO giveaway_pending_payouts "
                    "(giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) "
                    "VALUES (?, ?, ?, 0, ?, 0)",
                    (g["giveaway_id"], user_id, amount, now_ts())
                )
                logger.info(f"[giveaways] fallback: создана pending-запись {user_id} → gid={g['giveaway_id']} amount={amount}")
            db.commit()

            rows = cur.execute(
                "SELECT id, giveaway_id, amount, dm_message_id "
                "FROM giveaway_pending_payouts WHERE user_id=? AND paid_at=0",
                (user_id,),
            ).fetchall()
            logger.info(f"[giveaways] fallback: итого pending={len(rows)}")
        except Exception as e:
            logger.exception(f"[giveaways] fallback scan error: {e}")

    if not rows:
        logger.info(f"[giveaways] process_pending_payouts: user={user_id} — НЕЧЕГО выплачивать")
        return 0

    from modules.dc import add_dc

    total_paid = 0
    for r in rows:
        pid = r["id"]
        gid = r["giveaway_id"]
        amount = r["amount"]
        dm_mid = r["dm_message_id"]
        try:
            await add_dc(
                user_id, amount,
                f"Победа в розыгрыше #{gid} (после отзыва)",
                notify=False, log=False, to_clan_pool=True,
            )
            cur.execute(
                "UPDATE giveaway_pending_payouts SET paid_at=? WHERE id=?",
                (now_ts(), pid),
            )
            db.commit()
            total_paid += amount
            logger.info(f"[giveaways] НАЧИСЛЕНО: user={user_id} gid={gid} amount={amount}")

            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                dm_channel = user.dm_channel or await user.create_dm()
                new_embeds = _build_paid_winner_dm(gid=gid, amount=amount)

                edited = False
                if dm_mid:
                    try:
                        msg = await dm_channel.fetch_message(dm_mid)
                        await msg.edit(embeds=new_embeds)
                        edited = True
                        logger.info(f"[giveaways] DM отредактировано: user={user_id} dm={dm_mid}")
                    except Exception as e:
                        logger.warning(f"[giveaways] не отредактировать DM {dm_mid}: {e}")

                if not edited:
                    try:
                        sent = await dm_channel.send(embeds=new_embeds)
                        logger.info(f"[giveaways] DM отправлено заново: user={user_id} msg={sent.id}")
                    except Exception as e:
                        logger.warning(f"[giveaways] не отправить DM {user_id}: {e}")
            except Exception as e:
                logger.warning(f"[giveaways] DM payout {user_id}: {e}")

            await log_discord(
                title="💎 Приз за розыгрыш выдан",
                description=(
                    f"> **Победитель:** <@{user_id}>\n"
                    f"> **Розыгрыш:** `#{gid}`\n"
                    f"> **Сумма:** `+{amount} DC`\n"
                    f"> **Условие:** отзыв написан"
                ),
                color=0x00ff88,
            )
        except Exception as e:
            logger.exception(f"[giveaways] process_pending_payouts id={pid}: {e}")

    logger.info(f"[giveaways] process_pending_payouts DONE: user={user_id} total_paid={total_paid}")
    return total_paid

async def finish_giveaway(gid: int):
    logger.info(f"[giveaways] finish_giveaway START gid={gid}")
    try:
        row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
        if not row:
            logger.warning(f"[giveaways] finish_giveaway: gid={gid} не найден")
            return
        if row["status"] != "active":
            logger.warning(f"[giveaways] finish_giveaway: gid={gid} статус={row['status']}, не active")
            return
        guild = _bot.get_guild(row["guild_id"])
        if not guild:
            logger.warning(f"[giveaways] finish_giveaway: guild {row['guild_id']} не найден")
            return
        channel = guild.get_channel(row["channel_id"]) or _bot.get_channel(row["channel_id"])
        if not channel:
            logger.warning(f"[giveaways] finish_giveaway: channel {row['channel_id']} не найден")
            return

        valid_participants = await get_valid_participants(gid, guild)
        participants = list_from_str(row["participants"])
        winners_count = row["winners_count"]
        pool = valid_participants.copy()
        random.shuffle(pool)
        winners = pool[:winners_count] if pool else []
        logger.info(f"[giveaways] finish_giveaway: gid={gid} participants={len(participants)} valid={len(valid_participants)} winners={winners} auto_payout={row['auto_payout']}")

        cur.execute("UPDATE giveaways SET winners=?, status='finished', valid_participants=? WHERE giveaway_id=?", (str_from_list(winners), str_from_list(valid_participants), gid))
        db.commit()

        try:
            msg = await channel.fetch_message(row["message_id"])
            await msg.delete()
        except Exception as e:
            logger.debug(f"[giveaways] delete original: {e}")

        winners_mentions = " ".join(f"<@{u}>" for u in winners) if winners else "Нет победителей 😔"
        end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc)
        finished_embeds = build_finished_giveaway_embed(row["prize"], row["description"], len(participants), winners_mentions, end_dt)
        try:
            embed_msg = await channel.send(embeds=finished_embeds)
            cur.execute("UPDATE giveaways SET final_embed_id=? WHERE giveaway_id=?", (embed_msg.id, gid))
            db.commit()
            logger.info(f"[giveaways] финальный embed отправлен: msg_id={embed_msg.id}")
        except Exception as e:
            logger.exception(f"[giveaways] финальный embed: {e}")

        share = 0
        try:
            share = await _queue_pending_payouts(gid, row, winners)
            logger.info(f"[giveaways] pending queued: share={share}")
        except Exception as e:
            logger.exception(f"[giveaways] queue pending FAILED: {e}")

        try:
            await send_giveaway_report(gid=gid, prize=row["prize"], winners=winners, share=share, is_auto=bool(row["auto_payout"]))
        except Exception as e:
            logger.exception(f"[giveaways] send_giveaway_report FAILED: {e}")

        prize_name = row["prize"]
        is_auto = bool(row["auto_payout"])
        winner_ids = set(winners)
        fallback_share = _parse_dc_amount(prize_name) // max(len(winners), 1) if winners else 0

        sent_count = 0
        failed_count = 0
        for uid in participants:
            try:
                member = guild.get_member(uid)
                if not member:
                    continue

                if uid in winner_ids:
                    if is_auto:
                        dm = _build_template_winner_dm(gid=gid, prize=prize_name, share=share if share > 0 else fallback_share)
                    else:
                        dm = _build_manual_winner_dm(gid=gid, prize=prize_name)
                else:
                    dm = _build_loser_dm(gid=gid, prize=prize_name)

                sent = await member.send(embeds=dm)
                sent_count += 1
                if is_auto and uid in winner_ids and sent:
                    try:
                        cur.execute(
                            "UPDATE giveaway_pending_payouts SET dm_message_id=? "
                            "WHERE giveaway_id=? AND user_id=? AND paid_at=0",
                            (sent.id, gid, uid),
                        )
                        db.commit()
                        logger.info(f"[giveaways] dm_message_id сохранён: uid={uid} dm={sent.id}")
                    except Exception as e:
                        logger.warning(f"[giveaways] save dm_message_id {uid}: {e}")
            except disnake.Forbidden:
                failed_count += 1
                logger.warning(f"[giveaways] DM {uid}: Forbidden")
            except Exception as e:
                failed_count += 1
                logger.warning(f"[giveaways] DM {uid}: {e}")

        logger.info(f"[giveaways] finish_giveaway DONE gid={gid} sent={sent_count} failed={failed_count}")

    except Exception as e:
        logger.exception(f"[giveaways] finish_giveaway CRITICAL: {e}")

def _build_manual_winner_dm(gid: int, prize: str) -> list:
    e1 = disnake.Embed(color=0xffaa00)
    e1.set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(title="🏆 Ты победил в розыгрыше!", description=f"> **Приз:** {prize}\n> **ID розыгрыша:** `#{gid}`\n\n> 📩 **Что делать:**\n> Отпиши в ЛС <@{REPORT_DM_USER_ID}> в течение **24 часов**,\n> иначе приз уйдёт следующему участнику.", color=0xffaa00)
    e2.set_image(url=IMG_STRIPE)
    return [e1, e2]

def _build_template_winner_dm(gid: int, prize: str, share: int) -> list:
    e1 = disnake.Embed(color=0xffaa00)
    e1.set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(
        title="🏆 Ты выиграл в розыгрыше!",
        description=(
            f"> **Приз:** {prize}\n"
            f"> **Твоя доля:** `+{share} DC`\n"
            f"> **ID розыгрыша:** `#{gid}`\n\n"
            f"> ⏳ **Как забрать?**\n"
            f"> Напиши **новый отзыв** в <#{REVIEW_CHANNEL_ID}> — "
            f"и `{share} DC` автоматически упадут тебе на баланс.\n\n"
            f"> ❗ Если ты уже писал отзыв раньше — нужно написать **ещё один** "
            f"(кулдаун 2 минуты).\n\n"
            f"> ✨ _После отзыва это сообщение обновится._"
        ),
        color=0xffaa00,
    )
    e2.set_image(url=IMG_STRIPE)
    return [e1, e2]

def _build_paid_winner_dm(gid: int, amount: int) -> list:
    e1 = disnake.Embed(color=0x00ff88)
    e1.set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(
        title="💎 Приз зачислен на баланс!",
        description=(
            f"> **Сумма:** `+{amount} DC`\n"
            f"> **ID розыгрыша:** `#{gid}`\n\n"
            f"> ✨ DC уже у тебя на балансе. Спасибо за отзыв!"
        ),
        color=0x00ff88,
    )
    e2.set_image(url=IMG_STRIPE)
    return [e1, e2]

def _build_loser_dm(gid: int, prize: str) -> list:
    e1 = disnake.Embed(color=0x808080)
    e1.set_image(url=IMG_STRIPE)
    e2 = disnake.Embed(title="🎲 Розыгрыш завершён", description=f"> **Приз:** {prize}\n> **ID розыгрыша:** `#{gid}`\n\n> **Результат:**\n> Ты не занял призовое место. Постарайся в следующий раз! 🍀", color=0x808080)
    e2.set_image(url=IMG_STRIPE)
    return [e1, e2]

async def send_giveaway_report(gid: int, prize: str, winners: list, share: int = 0, is_auto: bool = False):
    try:
        if _bot is None:
            logger.warning("[giveaways] send_giveaway_report: _bot is None")
            return
        user = _bot.get_user(REPORT_DM_USER_ID) or await _bot.fetch_user(REPORT_DM_USER_ID)
        if not user or not winners: return
        content = "\n".join(str(uid) for uid in winners)
        file_data = io.BytesIO(content.encode("utf-8"))
        file = disnake.File(file_data, filename=f"winners_{gid}.txt")
        winners_mentions = " ".join(f"<@{u}>" for u in winners)
        type_label = "💎 Шаблонный (после отзыва)" if is_auto else "📩 Ручной"

        e1 = disnake.Embed(color=6776679)
        e1.set_image(url=IMG_STRIPE)

        if is_auto and share > 0:
            extra = (
                f"> **Каждому:** `+{share} DC`\n"
                f"> **Всего:** `{share * len(winners)} DC`\n"
                f"> ⏳ **Ждут нового отзыва в <#{REVIEW_CHANNEL_ID}>**\n"
                f"> После отзыва DC упадут автоматически\n\n"
            )
        else:
            extra = (
                "> ⏳ **Ждём отписи в ЛС** от каждого победителя\n"
                "> (в течение 24ч, иначе приз уйдёт следующему)\n\n"
            )

        e2 = disnake.Embed(
            title=f"📊 Победители розыгрыша #{gid}",
            description=(
                f"> **Приз:** {prize}\n"
                f"> **Тип:** {type_label}\n"
                f"> **Победителей:** `{len(winners)}`\n\n"
                f"{extra}"
                f"> 🏆 **Список победителей:**\n> {winners_mentions}"
            ),
            color=6776679,
        )
        e2.set_image(url=IMG_STRIPE)
        await user.send(embeds=[e1, e2], file=file)
        logger.info(f"[giveaways] отчёт админу: giveaway={gid}")
    except Exception as e:
        logger.exception(f"[giveaways] send_giveaway_report: {e}")

async def reroll_giveaway(inter, gid: int):
    row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=?", (gid,)).fetchone()
    if not row: return await inter.edit_original_message(content="❌ Розыгрыш не найден.")
    if row["status"] == "active": return await inter.edit_original_message(content="❌ Розыгрыш ещё не завершён.")

    guild = _bot.get_guild(row["guild_id"])
    channel = guild.get_channel(row["channel_id"]) or _bot.get_channel(row["channel_id"])
    valid_participants = await get_valid_participants(gid, guild)
    if not valid_participants: return await inter.edit_original_message(content="❌ Нет валидных участников для перевыбора.")

    old_winners = list_from_str(row["winners"])
    pool = [u for u in valid_participants if u not in old_winners]
    if not pool: return await inter.edit_original_message(content="❌ Нет участников для перевыбора.")

    winners_count = row["winners_count"]
    random.shuffle(pool)
    new_winners = pool[:winners_count] if pool else []

    cur.execute("UPDATE giveaways SET winners=? WHERE giveaway_id=?", (str_from_list(new_winners), gid))
    db.commit()

    try:
        if row["final_embed_id"]:
            msg = await channel.fetch_message(row["final_embed_id"])
            await msg.delete()
    except Exception: pass

    winners_mentions = " ".join(f"<@{u}>" for u in new_winners) if new_winners else "Нет победителей 😔"
    end_dt = datetime.fromtimestamp(row["end_time"], timezone.utc)
    finished_embeds = build_finished_giveaway_embed(row["prize"], row["description"] or "", len(list_from_str(row["participants"])), winners_mentions, end_dt)
    embed_msg = await channel.send(embeds=finished_embeds)
    cur.execute("UPDATE giveaways SET final_embed_id=? WHERE giveaway_id=?", (embed_msg.id, gid))
    db.commit()

    is_auto = bool(row["auto_payout"])
    share = 0

    if is_auto and new_winners:
        total_amount = _parse_dc_amount(row["prize"])
        share = total_amount // len(new_winners) if new_winners else 0

        for old_uid in old_winners:
            if old_uid in new_winners: continue
            cur.execute(
                "DELETE FROM giveaway_pending_payouts "
                "WHERE giveaway_id=? AND user_id=? AND paid_at=0",
                (gid, old_uid),
            )

        for uid in new_winners:
            existing = cur.execute(
                "SELECT id FROM giveaway_pending_payouts WHERE giveaway_id=? AND user_id=?",
                (gid, uid)
            ).fetchone()
            if not existing:
                cur.execute(
                    "INSERT INTO giveaway_pending_payouts "
                    "(giveaway_id, user_id, amount, dm_message_id, created_at, paid_at) "
                    "VALUES (?, ?, ?, 0, ?, 0)",
                    (gid, uid, share, now_ts()),
                )
        db.commit()
        logger.info(f"[giveaways] reroll: new_winners={new_winners} share={share}")

    if is_auto and new_winners:
        for uid in new_winners:
            try:
                member = guild.get_member(uid)
                if not member:
                    continue
                dm = _build_template_winner_dm(gid=gid, prize=row["prize"], share=share)
                sent = await member.send(embeds=dm)
                if sent:
                    try:
                        cur.execute(
                            "UPDATE giveaway_pending_payouts SET dm_message_id=? "
                            "WHERE giveaway_id=? AND user_id=? AND paid_at=0",
                            (sent.id, gid, uid),
                        )
                        db.commit()
                    except Exception as e:
                        logger.warning(f"[giveaways] reroll save dm {uid}: {e}")
            except Exception as e:
                logger.warning(f"[giveaways] reroll DM {uid}: {e}")

    try:
        await send_giveaway_report(gid=gid, prize=row["prize"], winners=new_winners, share=share, is_auto=is_auto)
    except Exception as e:
        logger.exception(f"[giveaways] reroll report: {e}")

    await inter.edit_original_message(content=f"✅ Перевыбор выполнен для розыгрыша #{gid}")

class EndGiveawayModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Принудительное завершение", components=[ui.TextInput(label="ID розыгрыша", custom_id="giveaway_id", max_length=10, placeholder="Введите числовой ID")])

    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        try: gid = int(inter.text_values["giveaway_id"].strip())
        except ValueError: return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        row = cur.execute("SELECT * FROM giveaways WHERE giveaway_id=? AND status='active'", (gid,)).fetchone()
        if not row: return await inter.response.send_message("❌ Активный розыгрыш не найден.", ephemeral=True)
        await inter.response.send_message("⏳ Завершаю...", ephemeral=True)
        await finish_giveaway(gid)
        await inter.edit_original_message(content=f"✅ Розыгрыш #{gid} завершён.")

class RerollModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Перевыбор победителя", components=[ui.TextInput(label="ID розыгрыша", custom_id="giveaway_id", max_length=10, placeholder="Введите числовой ID")])

    async def callback(self, inter: disnake.ModalInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        try: gid = int(inter.text_values["giveaway_id"].strip())
        except ValueError: return await inter.response.send_message("❌ ID должен быть числом.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        await reroll_giveaway(inter, gid)

async def show_templates_panel(inter: disnake.MessageInteraction):
    e = disnake.Embed(
        title="💎 Шаблонные розыгрыши",
        description=(
            "> Выберите тип ниже — розыгрыш стартует сразу.\n\n"
            "> ⏱ **Длительность:** 1 день\n"
            f"> 💰 **Выдача:** после отзыва в <#{REVIEW_CHANNEL_ID}>\n"
            "> ⭐ **Бонус:** за отзыв ещё начислят DC\n\n"
            "**Доступные шаблоны:** от **100** до **4000 DC**"
        ),
        color=6776679,
    )
    e.set_image(url=IMG_STRIPE)
    await inter.response.send_message(embed=e, view=TemplateStartView(), ephemeral=True)

class TemplateSelect(disnake.ui.StringSelect):
    def __init__(self):
        options = [
            disnake.SelectOption(label="100 DC · 1 победитель", description="Быстрый розыгрыш", value="100"),
            disnake.SelectOption(label="150 DC · 1 победитель", description="Стандартный розыгрыш", value="150"),
            disnake.SelectOption(label="350 DC · 1 победитель", description="Средний розыгрыш", value="350"),
            disnake.SelectOption(label="400 DC · 2 победителя", description="Розыгрыш на двоих", value="400"),
            disnake.SelectOption(label="450 DC · 2 победителя", description="Розыгрыш на двоих", value="450"),
            disnake.SelectOption(label="600 DC · 3 победителя", description="Розыгрыш на троих", value="600"),
            disnake.SelectOption(label="700 DC · 3 победителя", description="Розыгрыш на троих", value="700"),
            disnake.SelectOption(label="1000 DC · 5 победителей", description="Большой розыгрыш", value="1000"),
            disnake.SelectOption(label="1400 DC · 7 победителей", description="Средний розыгрыш", value="1400"),
            disnake.SelectOption(label="1800 DC · 9 победителей", description="Расширенный розыгрыш", value="1800"),
            disnake.SelectOption(label="2400 DC · 12 победителей", description="Массовый розыгрыш", value="2400"),
            disnake.SelectOption(label="3000 DC · 15 победителей", description="Большой массовый розыгрыш", value="3000"),
            disnake.SelectOption(label="3600 DC · 18 победителей", description="Огромный розыгрыш", value="3600"),
            disnake.SelectOption(label="4000 DC · 20 победителей", description="Мега-розыгрыш", value="4000"),
        ]
        super().__init__(placeholder="Выберите шаблон розыгрыша...", min_values=1, max_values=1, options=options, custom_id="giveaway_template_select")

    async def callback(self, inter: disnake.MessageInteraction):
        if not is_giveaway_staff(inter.author): return await inter.response.send_message("⛔ У вас нет прав.", ephemeral=True)
        key = inter.data.values[0]
        if key not in GIVEAWAY_TEMPLATES: return await inter.response.send_message("❌ Шаблон не найден.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        tpl = GIVEAWAY_TEMPLATES[key]
        prize = tpl["prize"]
        winners_count = tpl["winners"]
        description = tpl["description"]
        end_dt = datetime.now(MSK) + timedelta(days=1)
        end_dt_utc = end_dt.astimezone(timezone.utc)
        end_time = int(end_dt_utc.timestamp())
        created_at = now_ts()
        channel = _bot.get_channel(GIVEAWAY_CHANNEL_ID)
        if not channel: return await inter.edit_original_response(content="❌ Канал не найден.")
        embeds = build_giveaway_embeds(prize, description, winners_count, 0, end_dt_utc)
        msg = await channel.send(content="|| @everyone ||", embeds=embeds, view=GiveawayView())
        cur.execute("""INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, description, winners_count, end_time, created_at, required_invites, participants, winners, status, auto_payout, payout_done) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (inter.guild.id, channel.id, msg.id, inter.author.id, prize, description, winners_count, end_time, created_at, 0, "[]", "[]", "active", 1, 0))
        db.commit()
        gid = cur.lastrowid
        asyncio.create_task(schedule_end(gid))
        await inter.edit_original_response(
            content=(
                f"✅ Шаблонный розыгрыш **{prize}** создан! ID: `{gid}`\n"
                f"> 💰 DC начислятся победителям после нового отзыва ({winners_count} чел.)"
            ),
            embeds=[],
            view=None,
        )

class TemplateStartView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(TemplateSelect())

async def list_giveaways(inter: disnake.MessageInteraction):
    rows = cur.execute("SELECT * FROM giveaways WHERE guild_id=? ORDER BY giveaway_id DESC LIMIT 20", (inter.guild.id,)).fetchall()
    if not rows:
        return await inter.edit_original_response(content="Розыгрышей не найдено.")
    lines = []
    for r in rows:
        status_icon = "🟢" if r["status"] == "active" else "🔴"
        participants_count = len(list_from_str(r["participants"]))
        winners = list_from_str(r["winners"])
        time_str = f"Конец: <t:{r['end_time']}:R>" if r["status"] == "active" else f"Закончился: <t:{r['end_time']}:d>"
        winners_str = ""
        if r["status"] == "finished" and winners: winners_str = " | Победители: " + ", ".join(f"<@{w}>" for w in winners)
        auto_str = " 💎" if r["auto_payout"] else " 📩"
        lines.append(f"{status_icon} **ID {r['giveaway_id']}**{auto_str} — {r['prize']}\n> Участников: **{participants_count}** | {time_str}{winners_str}")
    embed = disnake.Embed(title="📋 Список розыгрышей (последние 20)", description="\n\n".join(lines), color=6776679)
    embed.set_footer(text="💎 = шаблонный (после отзыва) · 📩 = ручной")
    await inter.followup.send(embed=embed, ephemeral=True)

async def send_giveaway_panel():
    try:
        ch = _bot.get_channel(STAFF_PANEL_CHANNEL_ID) or await _bot.fetch_channel(STAFF_PANEL_CHANNEL_ID)
        if not ch: return
        try:
            async for msg in ch.history(limit=50):
                if msg.author == _bot.user and msg.embeds:
                    for e in msg.embeds:
                        if e.title and "розыгрыш" in e.title.lower():
                            try: await msg.delete()
                            except Exception: pass
                            break
        except Exception: pass

        e1 = disnake.Embed(
            title="Управление розыгрышами",
            description=(
                "> Панель для управления всеми розыгрышами сервера.\n\n"
                "> **Начать розыгрыш** — создать вручную с настройками.\n"
                "> **Шаблонные розыгрыши** — готовые DC-розыгрыши (выдача после отзыва).\n"
                "> **Лист розыгрышей** — все текущие и завершённые.\n"
                "> **Завершить принудительно** — закрыть досрочно.\n"
                "> **Перевыбрать победителя** — реролл после завершения."
            ),
            color=6776679
        )
        e1.set_image(url=IMG_STRIPE)
        await ch.send(embed=e1, view=GiveawayPanelView())
        logger.info("[giveaways] панель отправлена в стафф-канал")
    except Exception as e:
        logger.warning(f"[giveaways] send_giveaway_panel: {e}")

async def _delayed_init_and_panel():
    try:
        await _bot.wait_until_ready()
        await asyncio.sleep(8)
        try:
            active_rows = cur.execute("SELECT giveaway_id, end_time FROM giveaways WHERE status='active'").fetchall()
            for r in active_rows:
                gid = r["giveaway_id"]
                if r["end_time"] <= now_ts(): asyncio.create_task(finish_giveaway(gid))
                else: asyncio.create_task(schedule_end(gid))
            logger.info(f"[giveaways] восстановлено таймеров: {len(active_rows)}")
        except Exception as e: logger.exception(f"[giveaways] restore timers: {e}")
        await send_giveaway_panel()
    except Exception as e: logger.exception(f"[giveaways] _delayed_init_and_panel: {e}")

def setup_giveaways(bot_instance):
    global _bot, _setup_done
    if _setup_done: return
    _setup_done = True
    _bot = bot_instance

    _init_tables()
    bot_instance.add_view(GiveawayView())
    bot_instance.add_view(GiveawayPanelView())

    try: bot_instance.loop.create_task(_delayed_init_and_panel())
    except Exception as e: logger.warning(f"[giveaways] не удалось запустить init task: {e}")
    logger.info("[giveaways] ✅ модуль розыгрышей подключён")
