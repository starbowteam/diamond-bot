# -*- coding: utf-8 -*-
"""Ядро клановой лиги, квесты и панели. Всё в одном."""
import os, time, math, asyncio, random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
import disnake
from disnake import ButtonStyle, SelectOption, PartialEmoji
from disnake.ui import Button, Select, View, Modal, TextInput
from disnake.ext import tasks

from core.utils import CONFIG, DATA_DIR, ADD_DIR, FILES, logger, db, cur, load_json, save_json, log_discord, now_ts, get_dc_cache, save_dc_cache, update_user_roles
from clan.achievements import show_cases_screen, check_and_unlock

MSK = timezone(timedelta(hours=3))
CLUB_ROLE_ID = 1284697274655576186
MIN_BALANCE = 45
HARD_EXCLUDED_USERS = {1124040555240898631}
EXCLUDE_FROM_CLAN = HARD_EXCLUDED_USERS
CLAN_CYCLE_DAYS = 28; PAYOUT_DAY = 28; PAYOUT_HOUR_MSK = 20; PAYOUT_MINUTE = 0
CLAN_POOL_THRESHOLD = 100; CLAN_POOL_SMALL = 1.00; CLAN_POOL_BIG = 1.00
CREATOR_ID = 796293832751972352

def clan_cut(amount: int) -> int: return int(amount * 1.00) if amount > 0 else 0
TOP_BONUSES = [7.00, 5.00, 3.00]
MIN_CONTRIB_FOR_PAYOUT = 50
REPORT_DM_USER_ID = 796293832751972352
DAILY_CLAN_LIMIT = 2500
IMG_STRIPE = "https://cdn.discordapp.com/attachments/1527006158282555412/1537851307757539390/image.png?ex=6abdd8e3&is=6abc8763&hm=103c4a69ce7a0e770b41ad99b7b1fcfab93163979bbe3f15b435645bcbb7e098&"
EMBEDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "embeds")

SEASON_NAMES = {1: "Начало", 2: "Стихия проклятья", 3: "Неутопание кристалла", 4: "Сияние богачей", 5: "Кристализация магазина", 6: "Предновогодний дроп", 7: "27 Карат", 8: "Февральская потеха", 9: "Магнитуда сияния"}
def get_season_name(number: int) -> str: return SEASON_NAMES.get(number, f"Сезон #{number}")
def get_season_title(number: int) -> str: return f"Сезон {number} — {SEASON_NAMES[number]}" if number in SEASON_NAMES else f"Сезон #{number}"

CLANS_DATA = [{"id": 1, "name": "Мультяшности", "emoji": "🎮", "role_id": 1552707675257831525, "color": 0xb3e1b9, "color_dark": 0x749472, "fa_icon": "fa-gamepad", "description": "Яркие, как мультфильмы."}, {"id": 2, "name": "Сияние", "emoji": "✨", "role_id": 1552707025723465838, "color": 0xaa8ae7, "color_dark": 0x582189, "fa_icon": "fa-star", "description": "Свет звёзд в ночи."}, {"id": 3, "name": "Кристализация", "emoji": "💎", "role_id": 1551280425312194650, "color": 0x8799ae, "color_dark": 0xf1f7ff, "fa_icon": "fa-gem", "description": "Чистота формы и холодный расчёт."}]

def init_clan_core():
    for c in CLANS_DATA: cur.execute("INSERT OR IGNORE INTO clans (id, name, emoji, role_id, color, description) VALUES (?, ?, ?, ?, ?, ?)", (c["id"], c["name"], c["emoji"], c["role_id"], c["color"], c["description"]))
    cur.execute("CREATE TABLE IF NOT EXISTS clan_daily_limit (user_id INTEGER, date TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY (user_id, date))"); db.commit()
    cleanup_excluded_users(); ensure_active_cycle()
    try:
        if not get_user_clan(CREATOR_ID): cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, joined_at, left_at, cycle_joined) VALUES (?, ?, ?, NULL, ?)", (CREATOR_ID, 1, int(time.time()), 0)); db.commit()
    except Exception: pass

def ensure_active_cycle() -> Optional[dict]:
    cycle = get_current_cycle()
    return cycle if cycle else start_new_cycle()

def cleanup_excluded_users() -> dict:
    if not HARD_EXCLUDED_USERS: return {}
    report = {}
    for uid in HARD_EXCLUDED_USERS:
        contrib_rows = cur.execute("SELECT cycle_id, clan_id, amount FROM clan_contributions WHERE user_id=?", (uid,)).fetchall()
        if contrib_rows: report[uid] = {"sum": sum(r["amount"] for r in contrib_rows), "count": len(contrib_rows), "cycles": sorted(set(r["cycle_id"] for r in contrib_rows)), "clans": sorted(set(r["clan_id"] for r in contrib_rows))}
        cur.execute("DELETE FROM clan_contributions WHERE user_id=?", (uid,)); cur.execute("DELETE FROM clan_payouts WHERE user_id=?", (uid,)); cur.execute("UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL", (int(time.time()), uid))
    db.commit(); return report

def is_hard_excluded(user_id: int) -> bool: return user_id in HARD_EXCLUDED_USERS

def cleanup_specific_user(user_id: int) -> dict:
    contrib_rows = cur.execute("SELECT cycle_id, clan_id, amount, reason, ts FROM clan_contributions WHERE user_id=?", (user_id,)).fetchall()
    total, count = sum(r["amount"] for r in contrib_rows) if contrib_rows else 0, len(contrib_rows)
    by_clan, by_cycle = {}, {}
    for r in contrib_rows: by_clan[r["clan_id"]] = by_clan.get(r["clan_id"], 0) + r["amount"]; by_cycle[r["cycle_id"]] = by_cycle.get(r["cycle_id"], 0) + r["amount"]
    cur.execute("DELETE FROM clan_contributions WHERE user_id=?", (user_id,)); cur.execute("DELETE FROM clan_payouts WHERE user_id=?", (user_id,)); cur.execute("UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL", (int(time.time()), user_id)); db.commit()
    return {"user_id": user_id, "total": total, "count": count, "by_clan": [{"clan": f"{get_clan(cid)['emoji']} {get_clan(cid)['name']}", "amount": amt} for cid, amt in by_clan.items() if get_clan(cid)], "by_cycle": [{"cycle": f"Сезон #{cur.execute('SELECT number FROM clan_cycle WHERE id=?', (cyc_id,)).fetchone()['number'] if cur.execute('SELECT number FROM clan_cycle WHERE id=?', (cyc_id,)).fetchone() else '?'}", "amount": amt} for cyc_id, amt in by_cycle.items()]}

def _get_today_str() -> str: return datetime.now(MSK).strftime("%Y-%m-%d")
def _get_daily_contributed(user_id: int) -> int:
    row = cur.execute("SELECT amount FROM clan_daily_limit WHERE user_id=? AND date=?", (user_id, _get_today_str())).fetchone(); return row["amount"] if row else 0
def _add_daily_contributed(user_id: int, amount: int):
    cur.execute("INSERT INTO clan_daily_limit (user_id, date, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, date) DO UPDATE SET amount = amount + ?", (user_id, _get_today_str(), amount, amount)); db.commit()
def get_remaining_daily_limit(user_id: int) -> int: return max(DAILY_CLAN_LIMIT - _get_daily_contributed(user_id), 0)
def get_clan(clan_id: int) -> Optional[dict]: row = cur.execute("SELECT * FROM clans WHERE id=?", (clan_id,)).fetchone(); return dict(row) if row else None
def get_clan_by_role(role_id: int) -> Optional[dict]: row = cur.execute("SELECT * FROM clans WHERE role_id=?", (role_id,)).fetchone(); return dict(row) if row else None
def get_all_clans() -> List[dict]: return [dict(r) for r in cur.execute("SELECT * FROM clans ORDER BY id").fetchall()]

def get_user_clan(user_id: int) -> Optional[dict]:
    if is_hard_excluded(user_id): return None
    row = cur.execute("SELECT clan_id FROM clan_members WHERE user_id=? AND left_at IS NULL", (user_id,)).fetchone()
    return get_clan(row["clan_id"]) if row else None
def is_club_member(guild: disnake.Guild, user_id: int) -> bool:
    member = guild.get_member(user_id); return any(r.id == CLUB_ROLE_ID for r in member.roles) if member else False
def _get_clan_stats() -> List[Tuple[dict, int, int]]:
    result = []
    for c in get_all_clans():
        members = [m for m in cur.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL", (c["id"],)).fetchall() if not is_hard_excluded(m["user_id"])]
        total_bal = sum(cur.execute("SELECT balance FROM dc_cache WHERE user_id=?", (m["user_id"],)).fetchone()["balance"] for m in members if cur.execute("SELECT balance FROM dc_cache WHERE user_id=?", (m["user_id"],)).fetchone())
        result.append((c, len(members), total_bal))
    return result
def clan_role_needs_fix(member, clan: dict) -> bool:
    if member is None: return False
    target_id = clan["role_id"]; member_role_ids = {r.id for r in member.roles}
    if target_id not in member_role_ids: return True
    alien = {c["role_id"] for c in get_all_clans()} - {target_id}; return bool(alien & member_role_ids)
async def enforce_clan_role(member, clan: dict) -> Optional[str]:
    if member is None: return None
    guild = member.guild; target = guild.get_role(clan["role_id"]); alien_roles = []
    for c in get_all_clans():
        if c["id"] != clan["id"]:
            role = guild.get_role(c["role_id"])
            if role is not None and role in member.roles: alien_roles.append(role)
    changed = None
    for role in alien_roles:
        try: await member.remove_roles(role, reason="Клан-лига: это не его клан"); changed = "removed"
        except Exception: pass
    if target is not None and target not in member.roles:
        try: await member.add_roles(target, reason="Клан-лига: роль клана"); changed = "fixed" if changed else "added"
        except Exception: pass
    return changed
def assign_user_to_clan(user_id: int, guild: disnake.Guild) -> Optional[dict]:
    if get_user_clan(user_id): return None
    member = guild.get_member(user_id)
    if not member: return None
    block = clan_block_reason(guild, user_id)
    if block: return None
    stats = _get_clan_stats(); stats.sort(key=lambda x: (x[1], x[2])); target_clan = stats[0][0]
    cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, joined_at, left_at, cycle_joined) VALUES (?, ?, ?, NULL, ?)", (user_id, target_clan["id"], int(time.time()), cycle_id)); db.commit()
    role = guild.get_role(target_clan["role_id"])
    if role and role not in member.roles: asyncio.create_task(enforce_clan_role(member, target_clan))
    asyncio.create_task(send_welcome_dm(member, target_clan))
    asyncio.create_task(log_discord(title=f"{target_clan['emoji']} Новый участник клана", description=f"> **Клан:** {target_clan['emoji']} **{target_clan['name']}**\n> **Участник:** {member.mention} (`{member.id}`)", color=target_clan["color"], channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]))
    return target_clan
async def try_auto_assign_clan(user_id: int) -> Optional[dict]:
    try: from core.bot import bot
    except Exception: return None
    guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
    if not guild: return None
    try: clan = assign_user_to_clan(user_id, guild)
    except Exception: return None
    return clan

async def strip_all_clan_roles(guild: disnake.Guild) -> dict:
    clans = get_all_clans(); clan_role_ids = {c["role_id"] for c in clans}; stripped, errors = 0, 0
    for member in guild.members:
        if member.bot: continue
        own = [r for r in member.roles if r.id in clan_role_ids]
        if not own: continue
        try: await member.remove_roles(*own, reason="Клан-лига: полная пересборка"); stripped += 1
        except Exception: errors += 1
        await asyncio.sleep(0.1)
    cur.execute("UPDATE clan_members SET left_at=? WHERE left_at IS NULL", (int(time.time()),)); db.commit()
    return {"stripped": stripped, "errors": errors}
async def rebuild_clans_random(guild: disnake.Guild) -> dict:
    stripped = await strip_all_clan_roles(guild)
    eligible, skipped = [], 0
    for member in guild.members:
        if member.bot or not any(r.id == CLUB_ROLE_ID for r in member.roles): continue
        if clan_block_reason(guild, member.id): skipped += 1; continue
        eligible.append(member)
    random.shuffle(eligible); clans = get_all_clans(); cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0; now = int(time.time()); assigned, role_errors, distribution = 0, 0, {c["name"]: 0 for c in clans}
    for idx, member in enumerate(eligible):
        clan = clans[idx % len(clans)]; distribution[clan["name"]] += 1
        cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, joined_at, left_at, cycle_joined) VALUES (?, ?, ?, NULL, ?)", (member.id, clan["id"], now, cycle_id))
        try: await enforce_clan_role(member, clan)
        except Exception: role_errors += 1
        assigned += 1; await asyncio.sleep(0.15)
    db.commit(); moved = resync_contribution_clans()
    return {"stripped": stripped["stripped"], "strip_errors": stripped["errors"], "assigned": assigned, "skipped": skipped, "moved": moved, "role_errors": role_errors, "distribution": distribution}
def distribute_all_club_members(guild: disnake.Guild) -> Dict[str, int]:
    assigned, skipped, excluded, repaired = 0, 0, 0, 0; cleanup_excluded_users()
    for member in guild.members:
        if member.bot or not any(r.id == CLUB_ROLE_ID for r in member.roles): continue
        if is_hard_excluded(member.id): excluded += 1; continue
        user_clan = get_user_clan(member.id)
        if user_clan:
            if clan_role_needs_fix(member, user_clan): asyncio.create_task(enforce_clan_role(member, user_clan)); repaired += 1
            else: skipped += 1
            continue
        if assign_user_to_clan(member.id, guild): assigned += 1
    max_iter = 500
    while max_iter > 0:
        max_iter -= 1; stats = _get_clan_stats(); stats.sort(key=lambda x: x[1]); smallest, largest = stats[0], stats[-1]
        if largest[1] - smallest[1] <= 1: break
        members_big = cur.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL ORDER BY joined_at DESC LIMIT 1", (largest[0]["id"],)).fetchone()
        if not members_big or is_hard_excluded(members_big["user_id"]): break
        moved_uid = members_big["user_id"]; cur.execute("UPDATE clan_members SET clan_id=? WHERE user_id=?", (smallest[0]["id"], moved_uid)); db.commit()
        moved_member = guild.get_member(moved_uid)
        if moved_member:
            new_clan = get_clan(smallest[0]["id"])
            if new_clan: asyncio.create_task(enforce_clan_role(moved_member, new_clan))
        assigned += 1
    moved = resync_contribution_clans()
    return {"assigned": assigned, "repaired": repaired, "skipped": skipped, "excluded": excluded, "moved": moved}

INACTIVE_DAYS_LIMIT = 30
def clan_block_reason(guild: disnake.Guild, user_id: int) -> Optional[str]:
    if user_id == CREATOR_ID: return None
    if is_hard_excluded(user_id): return "жёсткое исключение"
    row = cur.execute("SELECT balance, last_active_ts FROM dc_cache WHERE user_id=?", (user_id,)).fetchone()
    balance, last_active = (row["balance"] or 0) if row else 0, (row["last_active_ts"] or 0) if row else 0
    if balance < MIN_BALANCE: return f"баланс меньше {MIN_BALANCE} DC"
    member = guild.get_member(user_id)
    if not member: return "нет на сервере"
    if not any(r.id == CLUB_ROLE_ID for r in member.roles): return "нет роли покупателя (нет отзывов)"
    if last_active > 0 and (int(time.time()) - last_active) // 86400 >= INACTIVE_DAYS_LIMIT: return f"нет действий {(int(time.time()) - last_active) // 86400} дн."
    return None
async def prune_ineligible_clan_members(guild: disnake.Guild) -> dict:
    now = int(time.time()); checked, removed, seeded, total_removed_dc = 0, [], 0, 0
    cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    for c in get_all_clans():
        for r in cur.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL", (c["id"],)).fetchall():
            uid = r["user_id"]
            if uid == CREATOR_ID or is_hard_excluded(uid): continue
            checked += 1
            row = cur.execute("SELECT last_active_ts FROM dc_cache WHERE user_id=?", (uid,)).fetchone()
            if row is None or (row["last_active_ts"] or 0) <= 0:
                d = get_dc_cache(uid); d["last_active_ts"] = now; save_dc_cache(uid, d); seeded += 1; continue
            reason = clan_block_reason(guild, uid)
            if not reason: continue
            contrib = 0
            if cycle_id:
                r_c = cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND user_id=?", (cycle_id, uid)).fetchone(); contrib = r_c["s"] or 0
            cur.execute("UPDATE clan_members SET left_at=? WHERE user_id=? AND left_at IS NULL", (now, uid))
            if cycle_id and contrib > 0: cur.execute("DELETE FROM clan_contributions WHERE cycle_id=? AND user_id=?", (cycle_id, uid)); total_removed_dc += contrib
            db.commit()
            member = guild.get_member(uid); role = guild.get_role(c["role_id"])
            if role and member and role in member.roles:
                try: await member.remove_roles(role, reason=f"Клан-лига: {reason}")
                except Exception: pass
            removed.append({"user_id": uid, "clan": c["name"], "reason": reason, "contrib": contrib})
            asyncio.create_task(log_discord(title="🚪 Исключён из клана", description=f"> **Участник:** <@{uid}> (`{uid}`)\n> **Клан:** {c['emoji']} **{c['name']}**\n> **Причина:** {reason}\n> **Вклад унесён:** `{contrib} DC`", color=0xff6600, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]))
            await asyncio.sleep(0.25)
    return {"checked": checked, "removed": len(removed), "seeded": seeded, "removed_dc": total_removed_dc, "users": removed}
async def recalculate_clan_league(guild: disnake.Guild) -> dict:
    counts = load_json(FILES["review_counts"], {}) or {}
    stats = {"roles_checked": 0, "roles_errors": 0, "members_checked": 0, "removed": 0, "seeded": 0, "assigned": 0, "repaired": 0, "skipped": 0, "excluded": 0, "moved": 0, "removed_dc": 0}
    for member in guild.members:
        if member.bot or int(counts.get(str(member.id), 0) or 0) <= 0: continue
        try: await update_user_roles(member, int(counts.get(str(member.id), 0) or 0), keep_pka=True); stats["roles_checked"] += 1
        except Exception: stats["roles_errors"] += 1
        await asyncio.sleep(0.15)
    pruned = await prune_ineligible_clan_members(guild)
    stats.update({"members_checked": pruned["checked"], "removed": pruned["removed"], "seeded": pruned["seeded"], "removed_dc": pruned.get("removed_dc", 0)})
    dist = distribute_all_club_members(guild)
    stats.update({"assigned": dist["assigned"], "repaired": dist.get("repaired", 0), "skipped": dist["skipped"], "excluded": dist.get("excluded", 0), "moved": dist.get("moved", 0)})
    return stats

def get_current_cycle() -> Optional[dict]: row = cur.execute("SELECT * FROM clan_cycle WHERE state='active' ORDER BY id DESC LIMIT 1").fetchone(); return dict(row) if row else None
def get_any_last_cycle() -> Optional[dict]: row = cur.execute("SELECT * FROM clan_cycle ORDER BY id DESC LIMIT 1").fetchone(); return dict(row) if row else None
def _msk_now() -> datetime: return datetime.now(MSK)
def _next_payout_ts(from_dt: Optional[datetime] = None) -> int:
    now = from_dt or _msk_now(); target = now.replace(day=PAYOUT_DAY, hour=PAYOUT_HOUR_MSK, minute=PAYOUT_MINUTE, second=0, microsecond=0)
    if target <= now: target = target.replace(year=now.year + 1, month=1) if now.month == 12 else target.replace(month=now.month + 1)
    return int(target.timestamp())
def start_new_cycle(force_short: bool = False) -> dict:
    now_ts_val, ends_at = int(time.time()), _next_payout_ts(); last = get_any_last_cycle(); number = (last["number"] + 1) if last else 1
    cur.execute("INSERT INTO clan_cycle (number, started_at, ends_at, state) VALUES (?, ?, ?, 'active')", (number, now_ts_val, ends_at)); db.commit()
    return get_current_cycle()

async def close_cycle_and_pay(bot) -> bool:
    cycle = get_current_cycle()
    if not cycle: return False
    cleanup_excluded_users(); cur.execute("UPDATE clan_cycle SET state='payout' WHERE id=?", (cycle["id"],)); db.commit()
    cycle_id, all_clans, report, total_paid = cycle["id"], get_all_clans(), {"cycle": cycle, "clans": [], "total": 0, "payouts": []}, 0
    for c in all_clans:
        bank_row = cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND clan_id=?", (cycle_id, c["id"])).fetchone(); bank = bank_row["s"] or 0
        members = [m for m in cur.execute("SELECT user_id, joined_at FROM clan_members WHERE clan_id=? AND left_at IS NULL", (c["id"],)).fetchall() if not is_hard_excluded(m["user_id"])]
        if not members or bank <= 0: report["clans"].append({"clan": c, "bank": bank, "members": len(members), "top": [], "paid": 0}); continue
        cycle_len_sec = max(cycle["ends_at"] - cycle["started_at"], 1); members_list = []
        for m in members:
            user_id, joined_at = m["user_id"], m["joined_at"]
            contrib_row = cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND user_id=?", (cycle_id, user_id)).fetchone(); contrib = contrib_row["s"] or 0
            days_inside = max(cycle["ends_at"] - max(joined_at, cycle["started_at"]), 0)
            members_list.append({"user_id": user_id, "contrib": contrib, "weight": days_inside / cycle_len_sec})
        
        eligible_members = [m for m in members_list if m["contrib"] >= MIN_CONTRIB_FOR_PAYOUT]
        sorted_members = sorted(eligible_members, key=lambda x: -x["contrib"])
        top_ids = [m["user_id"] for m in sorted_members[:3]]

        for m in members_list:
            m["eligible"] = m["contrib"] >= MIN_CONTRIB_FOR_PAYOUT
            if m["user_id"] in top_ids and m["eligible"]: m["bonus"], m["place"] = TOP_BONUSES[top_ids.index(m["user_id"])], top_ids.index(m["user_id"]) + 1
            else: m["bonus"], m["place"] = 1.5, None
            m["eff"] = (m["weight"] * m["bonus"]) if m["eligible"] else 0.0

        total_eff = sum(m["eff"] for m in members_list); clan_paid, top_report = 0, []
        for m in members_list:
            m["payout"] = math.floor(bank * m["eff"] / total_eff) if m["eligible"] and total_eff > 0 else 0
            clan_paid += m["payout"]
            if m["payout"] > 0: m["reason"] = None
            elif not m["eligible"]: m["reason"] = f"вклад < {MIN_CONTRIB_FOR_PAYOUT} DC"
            elif bank <= 0: m["reason"] = "банк пуст"
            else: m["reason"] = "доля < 1 DC"
            if m["payout"] > 0:
                try:
                    from modules.dc import add_dc
                    bot.loop.create_task(add_dc(m["user_id"], m["payout"], f"Клановая лига: выплата за {get_season_title(cycle['number'])}", notify=False, log=False, clan_share=0.0))
                except Exception: pass
                cur.execute("INSERT INTO clan_payouts (cycle_id, clan_id, user_id, weight, bonus_mult, final_amount, paid_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (cycle_id, c["id"], m["user_id"], m["weight"], m["bonus"], m["payout"], int(time.time())))
            if m["place"]: top_report.append({"user_id": m["user_id"], "place": m["place"], "contrib": m["contrib"], "bonus": m["bonus"], "payout": m["payout"]})
            report["payouts"].append({"user_id": m["user_id"], "clan_name": c["name"], "clan_emoji": c["emoji"], "clan_color": c["color"], "season": get_season_title(cycle["number"]), "contrib": m["contrib"], "place": m["place"], "bonus": m["bonus"], "payout": m["payout"], "reason": m["reason"], "bank": bank, "eligible": m["eligible"]})
        db.commit(); total_paid += clan_paid
        report["clans"].append({"clan": c, "bank": bank, "members": len(members_list), "top": top_report, "paid": clan_paid, "not_eligible": sum(1 for m in members_list if not m["eligible"])})
    report["total"] = total_paid
    cur.execute("UPDATE clan_cycle SET state='finished', total_paid=? WHERE id=?", (total_paid, cycle_id)); db.commit()
    try:
        from clan.achievements import unlock_achievement
        top_clan_data = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None
        if top_clan_data:
            for member_row in cur.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL", (top_clan_data["clan"]["id"],)).fetchall():
                if not is_hard_excluded(member_row["user_id"]): bot.loop.create_task(unlock_achievement(member_row["user_id"], "clan_champion", bot=bot))
    except Exception: pass
    asyncio.create_task(send_payout_report_dm(bot, report)); asyncio.create_task(post_payout_results(bot, report)); asyncio.create_task(send_payout_dms(bot, report))
    try: from clan.panels import post_news_season_end; asyncio.create_task(post_news_season_end(bot, report))
    except Exception: pass
    asyncio.create_task(log_discord(title=f"🏁 Клановая лига: {get_season_title(cycle['number'])} завершён", description=f"> **Общий банк:** `{sum(c['bank'] for c in report['clans'])} DC`\n> **Выплачено:** `{total_paid} DC`\n> **Кланов:** `{len(report['clans'])}`", color=0xFFD700, channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"]))
    async def _delayed_start():
        await asyncio.sleep(300); start_new_cycle()
        from clan.panels import update_clan_pool_embed, post_news_season_start
        await update_clan_pool_embed(bot)
        try: await post_news_season_start(bot)
        except Exception: pass
    asyncio.create_task(_delayed_start()); return True

async def add_clan_contribution(user_id: int, amount: int, reason: str):
    if is_hard_excluded(user_id) or amount <= 0: return False
    clan = get_user_clan(user_id); cycle = get_current_cycle()
    if not clan or not cycle: return False
    remaining = max(DAILY_CLAN_LIMIT - _get_daily_contributed(user_id), 0)
    if remaining <= 0: return False
    actual_amount = min(amount, remaining)
    cur.execute("INSERT INTO clan_contributions (cycle_id, clan_id, user_id, amount, reason, ts) VALUES (?, ?, ?, ?, ?, ?)", (cycle["id"], clan["id"], user_id, actual_amount, reason, int(time.time()))); db.commit()
    _add_daily_contributed(user_id, actual_amount)
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        asyncio.create_task(check_and_unlock(user_id, "clan_deposit", value=get_user_contribution(user_id), bot=bot))
    except Exception: pass
    return True

async def send_welcome_dm(member: disnake.Member, clan: dict):
    try:
        data = load_json(os.path.join(EMBEDS_DIR, "welcome.json"), {}); embeds = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
        e2 = disnake.Embed(title=f"Добро пожаловать в клан {clan['emoji']} {clan['name']}!", description=f"> Ты теперь часть команды, {member.mention}!\n\n**Как играть:**\n> • Зарабатывай DC — **100%** от заработка идёт в копилку клана\n> • Выполняй квесты — **100%** в копилку\n> • Топ-1 по вкладу получит бонус ×7.00\n> • Топ-2 по вкладу получит бонус ×5.00\n> • Топ-3 по вкладу получит бонус ×3.00\n> • Остальные участники получат бонус ×1.50\n> • Дневной лимит вклада — **2500 DC**\n\n**Где смотреть:**\n> 📊 Копилка — <#1552700960474800128>\n> 📊 Сезон — <#1552700989465956403>\n> 🎮 Игры — <#1552700973753827509>\n> 📰 Новости — <#1552700701128400979>\n\n> Удачи, воин!", color=clan["color"])
        e2.set_image(url=IMG_STRIPE); embeds.append(e2); await member.send(embeds=embeds)
    except Exception: pass

def resync_contribution_clans(cycle_id: Optional[int] = None) -> int:
    if cycle_id is None: cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    if not cycle_id: return 0
    rows = cur.execute("SELECT user_id, clan_id FROM clan_members WHERE left_at IS NULL").fetchall(); moved = 0
    for r in rows: cur.execute("UPDATE clan_contributions SET clan_id = ? WHERE cycle_id = ? AND user_id = ? AND clan_id <> ?", (r["clan_id"], cycle_id, r["user_id"], r["clan_id"])); moved += cur.rowcount or 0
    db.commit(); return moved

def get_clan_bank(clan_id: int, cycle_id: Optional[int] = None) -> int:
    if cycle_id is None: cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS); row = cur.execute(f"SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND clan_id=? AND user_id NOT IN ({','.join('?' * len(ids))})", (cycle_id, clan_id, *ids)).fetchone()
    else: row = cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND clan_id=?", (cycle_id, clan_id)).fetchone()
    return row["s"] or 0

def get_clan_top(clan_id: int, cycle_id: Optional[int] = None, limit: int = 10) -> List[dict]:
    if cycle_id is None: cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS); rows = cur.execute(f"SELECT user_id, COALESCE(SUM(amount), 0) AS total FROM clan_contributions WHERE cycle_id=? AND clan_id=? AND user_id NOT IN ({','.join('?' * len(ids))}) GROUP BY user_id ORDER BY total DESC LIMIT ?", (cycle_id, clan_id, *ids, limit)).fetchall()
    else: rows = cur.execute("SELECT user_id, COALESCE(SUM(amount), 0) AS total FROM clan_contributions WHERE cycle_id=? AND clan_id=? GROUP BY user_id ORDER BY total DESC LIMIT ?", (cycle_id, clan_id, limit)).fetchall()
    return [{"user_id": r["user_id"], "total": r["total"]} for r in rows]

def get_clan_members_count(clan_id: int) -> int: return sum(1 for r in cur.execute("SELECT user_id FROM clan_members WHERE clan_id=? AND left_at IS NULL", (clan_id,)).fetchall() if not is_hard_excluded(r["user_id"]))
def get_user_contribution(user_id: int, cycle_id: Optional[int] = None) -> int:
    if is_hard_excluded(user_id): return 0
    if cycle_id is None: cycle = get_current_cycle(); cycle_id = cycle["id"] if cycle else 0
    return cur.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM clan_contributions WHERE cycle_id=? AND user_id=?", (cycle_id, user_id)).fetchone()["s"] or 0
def get_last_contributions(clan_id: int, limit: int = 5) -> List[dict]:
    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS); rows = cur.execute(f"SELECT user_id, amount, reason, ts FROM clan_contributions WHERE clan_id=? AND user_id NOT IN ({','.join('?' * len(ids))}) ORDER BY ts DESC LIMIT ?", (clan_id, *ids, limit)).fetchall()
    else: rows = cur.execute("SELECT user_id, amount, reason, ts FROM clan_contributions WHERE clan_id=? ORDER BY ts DESC LIMIT ?", (clan_id, limit)).fetchall()
    return [dict(r) for r in rows]
def get_recent_contributions_all(limit: int = 5) -> List[dict]:
    if HARD_EXCLUDED_USERS:
        ids = list(HARD_EXCLUDED_USERS); rows = cur.execute(f"SELECT user_id, amount, reason, ts, clan_id FROM clan_contributions WHERE user_id NOT IN ({','.join('?' * len(ids))}) ORDER BY ts DESC LIMIT ?", (*ids, limit)).fetchall()
    else: rows = cur.execute("SELECT user_id, amount, reason, ts, clan_id FROM clan_contributions ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

async def send_payout_report_dm(bot, report: dict):
    try:
        user = bot.get_user(REPORT_DM_USER_ID) or await bot.fetch_user(REPORT_DM_USER_ID); lines = []
        for c_data in report["clans"]:
            c = c_data["clan"]; lines.append(f"\n**{c['emoji']} {c['name'].upper()}** — {c_data['members']} чел., банк `{c_data['bank']} DC`")
            for t in c_data["top"]: lines.append(f"> {['🥇', '🥈', '🥉'][t['place'] - 1]} <@{t['user_id']}> — {t['contrib']} DC (×{t['bonus']}) → **{t['payout']} DC**")
            lines.append(f"> ─── Итого выплачено: `{c_data['paid']} DC`")
        top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None
        e1 = disnake.Embed(color=0xFFD700).set_image(url=IMG_STRIPE); e2 = disnake.Embed(title=f"📊 ОТЧЁТ ПО КЛАНОВОЙ ЛИГЕ — {get_season_title(report['cycle']['number']).upper()}", description="".join(lines) + f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n💰 **Общий оборот:** `{sum(c['bank'] for c in report['clans'])} DC`\n💸 **Выплачено:** `{report['total']} DC`\n" + (f"🏆 **Победитель сезона:** {top_clan['clan']['emoji']} **{top_clan['clan']['name'].upper()}**" if top_clan else ""), color=0xFFD700).set_image(url=IMG_STRIPE)
        await user.send(embeds=[e1, e2])
    except Exception: pass

async def send_payout_dms(bot, report: dict):
    season = get_season_title(report["cycle"]["number"])
    for p in report.get("payouts", []):
        try:
            user = bot.get_user(p["user_id"]) or await bot.fetch_user(p["user_id"]); got = p["payout"] > 0; color = (p["clan_color"] or 0x2ecc71) if got else 0x2f3136
            lines = [f"> Сезон **«{season}»** завершён.\n> Клан: {p['clan_emoji']} **{p['clan_name'].upper()}**\n\n**Твой итог за сезон**\n> Вклад в копилку: `{p['contrib']} DC`\n> Банк клана: `{p['bank']} DC`"]
            lines.append(f"> Место по вкладу: `#{p['place']}`\n> Множитель: `×{p['bonus']:.2f}`" if p["place"] else f"> Множитель: `×{p['bonus']:.2f}`")
            lines += ["", "────────────────────", f"**💎 Получено: `{p['payout']} DC`**\n\n> Выплата уже на балансе.\n> Спасибо!" if got else f"**Выплата не начислена**\n\n> Причина: {p['reason']}."]
            await user.send(embed=disnake.Embed(title="💎 Клановая лига — итоги сезона", description="\n".join(lines), color=color).set_footer(text="Diamond Shop · Клановая лига"))
            await asyncio.sleep(0.5)
        except Exception: pass

async def post_payout_results(bot, report: dict):
    try:
        ch = bot.get_channel(CONFIG["CLAN_POOL_CHANNEL_ID"]) or await bot.fetch_channel(CONFIG["CLAN_POOL_CHANNEL_ID"]); lines = []
        for c_data in report["clans"]:
            lines.append(f"**{c_data['clan']['emoji']} {c_data['clan']['name'].upper()}** — банк `{c_data['bank']} DC`, выплачено `{c_data['paid']} DC` ({c_data['members']} чел.)")
            for t in c_data["top"]: lines.append(f"> {['🥇', '🥈', '🥉'][t['place'] - 1]} <@{t['user_id']}> — вклад `{t['contrib']} DC` (×{t['bonus']})")
        top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None
        e1 = disnake.Embed(color=0xFFD700).set_image(url=IMG_STRIPE); e2 = disnake.Embed(title=f"🏆 {get_season_title(report['cycle']['number']).upper()} ЗАВЕРШЁН!", description="".join(lines) + f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n💰 **Общий оборот:** `{sum(c['bank'] for c in report['clans'])} DC`\n" + (f"🏆 **Победитель:** {top_clan['clan']['emoji']} **{top_clan['clan']['name'].upper()}**" if top_clan else "") + "\n\n> Новый сезон стартует через **5 минут**!", color=0xFFD700).set_image(url=IMG_STRIPE)
        await ch.send(embeds=[e1, e2])
    except Exception: pass

def make_progress_bar(percent: float, length: int = 10) -> str: filled = int(round(max(0.0, min(1.0, percent)) * length)); return "▰" * filled + "▱" * (length - filled)
def clan_status_emoji(bank: int) -> str: return "🔥" if bank >= 5000 else "⚡" if bank >= 2000 else "💤"

# ============================================================
# КВЕСТЫ (из quests.py)
# ============================================================
QUESTS: Dict[str, dict] = {
    "msg_50": {"title": "Болтун", "desc": "Напиши 50 сообщений в чате", "reward": 30, "goal": 50, "type": "daily", "unit": "сообщений", "icon": "fa-comment"},
    "voice_1h": {"title": "Голос", "desc": "Проведи 1 час в голосовых каналах", "reward": 50, "goal": 3600, "type": "daily", "unit": "секунд", "icon": "fa-microphone"},
    "casino_3": {"title": "Азарт", "desc": "Сыграй 3 партии в казино", "reward": 30, "goal": 3, "type": "daily", "unit": "партий", "icon": "fa-dice"},
    "cmds_5": {"title": "Активный", "desc": "5 взаимодействий с панелями клана", "reward": 20, "goal": 5, "type": "daily", "unit": "действий", "icon": "fa-computer-mouse"},
    "msg_1000": {"title": "Мега-болтун", "desc": "1000 сообщений за неделю", "reward": 200, "goal": 1000, "type": "weekly", "unit": "сообщений", "icon": "fa-comments"},
    "voice_10h": {"title": "Марафонец", "desc": "10 часов в ГЧ", "reward": 250, "goal": 36000, "type": "weekly", "unit": "секунд", "icon": "fa-headphones"},
    "casino_30": {"title": "Азартная неделя", "desc": "Сыграй 30 партий в казино", "reward": 150, "goal": 30, "type": "weekly", "unit": "партий", "icon": "fa-dice-five"},
    "win_3000": {"title": "Удачливый", "desc": "Выиграй 3000 DC в казино за неделю", "reward": 350, "goal": 3000, "type": "weekly", "unit": "DC", "icon": "fa-trophy"},
    "first_review": {"title": "Первый отзыв", "desc": "Оставь первый отзыв в этом сезоне", "reward": 150, "goal": 1, "type": "once", "unit": "отзывов", "icon": "fa-star"},
    "gift_500": {"title": "Щедрость", "desc": "Подари кому-то 500 DC через магазин", "reward": 200, "goal": 500, "type": "once", "unit": "DC", "icon": "fa-gift"},
    "jackpot": {"title": "Джекпот", "desc": "Более 10K DC за раз", "reward": 500, "goal": 10000, "type": "once", "unit": "DC", "icon": "fa-fire"},
    "top_contributor": {"title": "Лидер клана", "desc": "Стань топ-1 клана", "reward": 400, "goal": 1, "type": "once", "unit": "раз", "icon": "fa-crown"},
}
def init_clan_quests():
    for key, q in QUESTS.items(): cur.execute("INSERT OR IGNORE INTO quests (key, title, description, reward, goal, type, emoji, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)", (key, q["title"], q["desc"], q["reward"], q["goal"], q["type"], q["icon"]))
    db.commit()
def _get_cycle_id() -> int:
    cycle = get_current_cycle()
    return cycle["id"] if cycle else 0
def get_quest_progress(user_id: int, quest_key: str, cycle_id: Optional[int] = None) -> dict:
    if cycle_id is None: cycle_id = _get_cycle_id()
    row = cur.execute("SELECT progress, completed_at, claimed FROM quest_progress WHERE user_id=? AND quest_key=? AND cycle_id=?", (user_id, quest_key, cycle_id)).fetchone()
    return {"progress": row["progress"], "completed_at": row["completed_at"], "claimed": row["claimed"]} if row else {"progress": 0, "completed_at": None, "claimed": 0}
def update_progress(user_id: int, quest_key: str, delta: int = 1, absolute: Optional[int] = None):
    if quest_key not in QUESTS: return
    quest = QUESTS[quest_key]; cycle_id = _get_cycle_id()
    if cycle_id == 0: return
    if not get_user_clan(user_id): return
    cur.execute("INSERT OR IGNORE INTO quest_progress (user_id, quest_key, cycle_id, progress) VALUES (?, ?, ?, 0)", (user_id, quest_key, cycle_id))
    row = cur.execute("SELECT progress, completed_at FROM quest_progress WHERE user_id=? AND quest_key=? AND cycle_id=?", (user_id, quest_key, cycle_id)).fetchone()
    if row["completed_at"]: return
    new_progress = min(absolute if absolute is not None else (row["progress"] + delta), quest["goal"])
    if new_progress >= quest["goal"]:
        cur.execute("UPDATE quest_progress SET progress=?, completed_at=? WHERE user_id=? AND quest_key=? AND cycle_id=?", (new_progress, int(time.time()), user_id, quest_key, cycle_id)); db.commit()
        asyncio.create_task(_reward_user(user_id, quest_key, quest))
    else:
        cur.execute("UPDATE quest_progress SET progress=? WHERE user_id=? AND quest_key=? AND cycle_id=?", (new_progress, user_id, quest_key, cycle_id)); db.commit()
async def _reward_user(user_id: int, quest_key: str, quest: dict):
    reward = quest["reward"]; clan = get_user_clan(user_id)
    if not clan: return
    try:
        from modules.dc import touch_activity, add_dc
        touch_activity(user_id)
    except Exception: pass
    await add_dc(user_id, reward, f"Квест: {quest['title']}", notify=False, log=False, to_clan_pool=True)
    try:
        from clan.achievements import check_and_unlock
        from core.bot import bot
        total_completed = cur.execute("SELECT COUNT(*) AS c FROM quest_progress WHERE user_id=? AND completed_at IS NOT NULL", (user_id,)).fetchone()
        asyncio.create_task(check_and_unlock(user_id, "quests", value=total_completed["c"] if total_completed else 0, bot=bot))
    except Exception: pass
    try:
        from core.bot import bot
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if user:
            e = disnake.Embed(title="✅ Квест выполнен!", description=f"> **Квест:** {quest['title']}\n> **Награда:** `+{reward} DC` на баланс\n> **В копилку клана:** `+{reward} DC` ({clan['emoji']} **{clan['name']}**)\n\n> Продолжай выполнять квесты!", color=clan["color"]).set_image(url=IMG_STRIPE)
            await user.send(embed=e)
    except Exception: pass
    await log_discord(title="🎯 Квест выполнен", description=f"> **Участник:** <@{user_id}>\n> **Клан:** {clan['emoji']} {clan['name']}\n> **Квест:** {quest['title']}\n> **На баланс:** `+{reward} DC`\n> **В копилку:** `+{reward} DC`", color=clan["color"], channel_id=CONFIG["LOG_TICKET_CHANNEL_ID"])
def get_user_quests(user_id: int) -> List[dict]:
    cycle_id = _get_cycle_id(); result = []
    for key, q in QUESTS.items():
        row = cur.execute("SELECT progress, completed_at FROM quest_progress WHERE user_id=? AND quest_key=? AND cycle_id=?", (user_id, key, cycle_id)).fetchone()
        result.append({"key": key, "title": q["title"], "desc": q["desc"], "reward": q["reward"], "goal": q["goal"], "progress": row["progress"] if row else 0, "completed": bool(row["completed_at"]) if row else False, "type": q["type"], "icon": q["icon"]})
    return result
def reset_daily_quests():
    cycle_id = _get_cycle_id(); daily_keys = [k for k, q in QUESTS.items() if q["type"] == "daily"]
    cur.execute(f"DELETE FROM quest_progress WHERE cycle_id=? AND quest_key IN ({','.join('?' * len(daily_keys))})", (cycle_id, *daily_keys)); db.commit()
def reset_weekly_quests():
    cycle_id = _get_cycle_id(); weekly_keys = [k for k, q in QUESTS.items() if q["type"] == "weekly"]
    cur.execute(f"DELETE FROM quest_progress WHERE cycle_id=? AND quest_key IN ({','.join('?' * len(weekly_keys))})", (cycle_id, *weekly_keys)); db.commit()
async def on_message_quest_hook(message: disnake.Message):
    if message.author.bot or not isinstance(message.channel, disnake.TextChannel): return
    user_id = message.author.id
    if not get_user_clan(user_id) or message.channel.id == CONFIG["REVIEW_COUNT_CHANNEL"] or len((message.content or "").strip()) < CONFIG.get("MIN_MESSAGE_LENGTH", 3): return
    update_progress(user_id, "msg_50", delta=1); update_progress(user_id, "msg_1000", delta=1)
async def on_voice_quest_hook(user_id: int, seconds: int):
    if not get_user_clan(user_id) or seconds <= 0: return
    update_progress(user_id, "voice_1h", delta=seconds); update_progress(user_id, "voice_10h", delta=seconds)
async def on_casino_quest_hook(user_id: int):
    if not get_user_clan(user_id): return
    update_progress(user_id, "casino_3", delta=1); update_progress(user_id, "casino_30", delta=1)
async def on_casino_win_hook(user_id: int, payout: int, bet: int):
    if not get_user_clan(user_id): return
    profit = max(payout - bet, 0)
    if profit > 0: update_progress(user_id, "win_3000", delta=profit)
    if profit >= 10000: update_progress(user_id, "jackpot", absolute=10000)
async def on_review_quest_hook(user_id: int):
    if not get_user_clan(user_id): return
    update_progress(user_id, "first_review", delta=1)
async def on_purchase_quest_hook(user_id: int, amount_dc: int): pass
async def on_gift_quest_hook(sender_id: int, amount_dc: int):
    if not get_user_clan(sender_id): return
    update_progress(sender_id, "gift_500", delta=amount_dc)
async def on_panel_click_quest_hook(user_id: int):
    if not get_user_clan(user_id): return
    update_progress(user_id, "cmds_5", delta=1)

# ============================================================
# ПАНЕЛИ И РЕНДЕР (из panels.py)
# ============================================================
P = "\u3164"
EMOJI_BANK   = PartialEmoji.from_str("<:1d1ds:1552730624572391584>")
EMOJI_TOP    = PartialEmoji.from_str("<:d1edf:1552730601155596348>")
EMOJI_HOWTO  = PartialEmoji.from_str("<:infor:1552730394795970621>")
EMOJI_QUESTS = PartialEmoji.from_str("<:d11d1:1552732333394763776>")
EMOJI_SLOTS  = PartialEmoji.from_str("<:game1:1552732315606589460>")
EMOJI_CASES  = PartialEmoji(name="S21", id=1552381035092648026)
EMOJI_DEPOSITS = PartialEmoji.from_str("<:Otziv:1541808692314243172>")
EMOJI_LAST     = PartialEmoji.from_str("<:warn:1552325395171381388>")
EMOJI_TOTAL    = PartialEmoji.from_str("<:Politic:1539657020695650384>")
EMOJI_ROULETTE  = "<:ropulet:1550563615675781282>"
EMOJI_BLACKJACK = "<:joke:1551288467659428020>"
EMOJI_COINFLIP  = "<:coins:1539649259245408340>"

IMG_SLOTS_TOP = "https://cdn.discordapp.com/attachments/1527006158282555412/1562685534244053065/image.png?ex=6adae3d0&is=6ad99250&hm=44b63eacd2ddd814b5ef4d6ae1551c704239ee049554dbfd310a822466269a17&"
IMG_SEASON_TOP = "https://cdn.discordapp.com/attachments/1527006158282555412/1556729820300316823/image.png?backend=b2&ex=6ac5391f&is=6ac3e79f&hm=0c9118861dcf05bc1ee7902240a762035c086b1bbd67ed2f23d1a59ad1949f0f&"
IMG_NEWS_TOP = "https://cdn.discordapp.com/attachments/1527006158282555412/1556729818517741649/image.png?backend=b2&ex=6ac5391f&is=6ac3e79f&hm=700cd6018aa1de7b77e8c0eafd8e2cb5d2534b7f280e6fa5bd90e6a83471bf46&"

async def _send_clan_screen(inter, buf, fname: str):
    try: await inter.response.defer(ephemeral=True)
    except Exception: pass
    try:
        file = disnake.File(buf, filename=fname); embed = disnake.Embed(color=6776679); embed.set_image(url=f"attachment://{fname}"); await inter.followup.send(embed=embed, file=file, ephemeral=True)
    except Exception as e:
        try: await inter.followup.send(content=f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        except Exception: pass
def _time_ago(ts: int) -> str:
    try: sec = int(datetime.now(timezone.utc).timestamp()) - int(ts)
    except Exception: return "—"
    if sec < 60: return "только что"
    if sec < 3600: return f"{sec // 60} мин назад"
    if sec < 86400: return f"{sec // 3600} ч назад"
    if sec < 86400 * 2: return "вчера"
    return f"{sec // 86400} дн назад"
async def _get_balance(user_id: int) -> int:
    try:
        from modules.dc import get_user_balance
        return await get_user_balance(user_id)
    except Exception: return 0
def _guild_name(inter, user_id: int) -> str:
    try:
        m = inter.guild.get_member(user_id) if inter.guild else None
        if m: return m.display_name
    except Exception: pass
    return str(user_id)
def _build_static_pool_embeds() -> List[disnake.Embed]:
    data = load_json(os.path.join(EMBEDS_DIR, "clan_pool.json"), {}); embeds = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    return embeds if embeds else [disnake.Embed(color=6776679)]
def _build_season_static_embeds() -> List[disnake.Embed]:
    cycle = get_current_cycle(); season_num = cycle["number"] if cycle else 1; title = f"Клубная лига — {get_season_title(season_num)}!" if cycle else f"Клубная лига — {get_season_title(1)}!"
    e1 = disnake.Embed(color=6776679).set_image(url=IMG_SEASON_TOP); desc = f"> В данный момент, участвуют 3 клана — <@&1552707675257831525> | <@&1552707025723465838> | <@&1551280425312194650>.\n> О каждом связующем — можно узнать по кнопкам ниже.\n\n**Конец сезона:** <t:{cycle['ends_at']}:f>" if cycle else f"> В данный момент, участвуют 3 клана — <@&1552707675257831525> | <@&1552707025723465838> | <@&1551280425312194650>.\n> О каждом связующем — можно узнать по кнопкам ниже.\n\n**Конец сезона:** — (сезон ещё не запущен)"
    e2 = disnake.Embed(title=title, description=desc, color=6776679).set_image(url=IMG_STRIPE); return [e1, e2]
def _build_games_embeds() -> List[disnake.Embed]:
    data = load_json(os.path.join(EMBEDS_DIR, "clan_games.json"), {}); embeds = [disnake.Embed.from_dict(e) for e in data.get("embeds", [])]
    return embeds if embeds else [disnake.Embed(color=6776679)]
async def send_detailed_report_dm(bot, user_id, clan_id, inter_guild):
    clan = get_clan(clan_id)
    if not clan: return
    bank, members, top = get_clan_bank(clan_id), get_clan_members_count(clan_id), get_clan_top(clan_id, limit=10); active_members = sum(1 for t in top if t["total"] > 0); zero_contrib = max(0, members - active_members); pros, cons = [], []
    if bank > 10000: pros.append("Очень высокий банк клана")
    if active_members > 5: pros.append("Много активных участников")
    if top and top[0]["total"] > 5000: pros.append("Есть явный лидер по вкладу")
    if zero_contrib > members / 2: cons.append(f"Больше половины участников ({zero_contrib}) не внесли вклад")
    if bank < 1000: cons.append("Низкий общий банк клана")
    if not top: cons.append("Нет вкладов вообще")
    e1 = disnake.Embed(title=f"📊 Отчёт по клану {clan['emoji']} {clan['name']}", color=clan["color"])
    e1.add_field(name="Банк клана", value=f"`{bank} DC`", inline=True).add_field(name="Участников", value=f"`{members} чел.`", inline=True).add_field(name="Активных", value=f"`{active_members} чел.`", inline=True).add_field(name="Средний вклад", value=f"`{bank // max(members, 1)} DC`", inline=True)
    e2 = disnake.Embed(title="🏆 Топ участников", color=clan["color"]); e2.description = "\n".join([f"`#{i}` {(inter_guild.get_member(t['user_id']).display_name if inter_guild.get_member(t['user_id']) else str(t['user_id']))} — **{t['total']} DC**" for i, t in enumerate(top[:10], 1)]) if top else "Нет вкладов."
    e3 = disnake.Embed(title="📋 Оценка сезона", color=clan["color"]); e3.add_field(name="✅ Плюсы", value="\n".join(f"• {p}" for p in pros) or "• Пока нет", inline=False).add_field(name="⚠️ Минусы", value="\n".join(f"• {c}" for c in cons) or "• Пока нет", inline=False)
    try: user = bot.get_user(user_id) or await bot.fetch_user(user_id); await user.send(embeds=[e1, e2, e3])
    except Exception: pass

class ClanPoolView(View):
    def __init__(self): super().__init__(timeout=None)
    @disnake.ui.button(label=f"{P}Банк клана{P}", style=ButtonStyle.gray, custom_id="clan_pool:bank", emoji=EMOJI_BANK)
    async def bank(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); user_clan = get_user_clan(inter.author.id)
        if not user_clan: return await inter.response.send_message("❌ Ты не в клане. Получи роль покупателя — и получишь клан.", ephemeral=True)
        balance, bank_sum, members, my_contrib = await _get_balance(inter.author.id), get_clan_bank(user_clan["id"]), get_clan_members_count(user_clan["id"]), get_user_contribution(inter.author.id); all_top = get_clan_top(user_clan["id"], limit=1000); my_rank, to_top3 = None, 0
        for i, t in enumerate(all_top, 1):
            if t["user_id"] == inter.author.id: my_rank = i; break
        if all_top and len(all_top) >= 3 and my_rank and my_rank > 3: to_top3 = max(all_top[2]["total"] - my_contrib + 1, 0)
        top3 = [{"user_id": t["user_id"], "user_name": _guild_name(inter, t["user_id"]), "total": t["total"]} for t in all_top[:3]]
        try:
            from clan.render import render_clan_bank
            buf = render_clan_bank(inter.author.id, balance, user_clan, bank_sum, members, my_contrib, my_rank, to_top3, top3)
        except Exception as e: return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_bank_{inter.author.id}.png")

    @disnake.ui.button(label=f"{P}Топ{P}", style=ButtonStyle.gray, custom_id="clan_pool:top", emoji=EMOJI_TOP)
    async def top(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); user_clan = get_user_clan(inter.author.id)
        if not user_clan: return await inter.response.send_message("❌ Ты не в клане.", ephemeral=True)
        balance, my_contrib, top_raw = await _get_balance(inter.author.id), get_user_contribution(inter.author.id), get_clan_top(user_clan["id"], limit=10); my_rank, to_first = None, 0
        for i, t in enumerate(top_raw, 1):
            if t["user_id"] == inter.author.id: my_rank = i; break
        if top_raw and my_rank and my_rank > 1: to_first = max(top_raw[0]["total"] - my_contrib + 1, 0)
        top_list = [{"user_id": t["user_id"], "user_name": _guild_name(inter, t["user_id"]), "total": t["total"]} for t in top_raw]
        try:
            from clan.render import render_clan_top
            buf = render_clan_top(inter.author.id, balance, user_clan, top_list, my_rank, my_contrib, to_first)
        except Exception as e: return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_top_{inter.author.id}.png")

    @disnake.ui.button(label=f"{P}Как это работает{P}", style=ButtonStyle.gray, custom_id="clan_pool:howto", emoji=EMOJI_HOWTO)
    async def howto(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); balance = await _get_balance(inter.author.id)
        try:
            from clan.render import render_clan_howto
            buf = render_clan_howto(inter.author.id, balance)
        except Exception as e: return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_howto_{inter.author.id}.png")

class ClanSeasonView(View):
    def __init__(self): super().__init__(timeout=None)
    @disnake.ui.button(label=f"{P}Вклады{P}", style=ButtonStyle.gray, custom_id="clan_season:deposits", emoji=EMOJI_DEPOSITS)
    async def deposits(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); balance = await _get_balance(inter.author.id); clans_data = []
        for c in get_all_clans():
            bank, members, top = get_clan_bank(c["id"]), get_clan_members_count(c["id"]), get_clan_top(c["id"], limit=1)
            clans_data.append({"clan": c, "bank": bank, "members": members, "leader": f"@{_guild_name(inter, top[0]['user_id'])}" if top else "—"})
        try:
            from clan.render import render_clan_deposits
            buf = render_clan_deposits(inter.author.id, balance, clans_data)
        except Exception as e: return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_dep_{inter.author.id}.png")

    @disnake.ui.button(label=f"{P}Последнее{P}", style=ButtonStyle.gray, custom_id="clan_season:last", emoji=EMOJI_LAST)
    async def last(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); balance = await _get_balance(inter.author.id); recent = get_recent_contributions_all(limit=8); feed = []
        for r in recent:
            clan = get_clan(r["clan_id"]); reason = r.get("reason", "") or ""
            feed.append({"user_id": r["user_id"], "user_name": _guild_name(inter, r["user_id"]), "clan": clan, "amount": r["amount"], "reason": reason, "time_str": _time_ago(r["ts"]), "tag": reason.split(":")[0][:16].upper() if reason else "ВКЛАД"})
        try:
            from clan.render import render_clan_last
            buf = render_clan_last(inter.author.id, balance, feed, today_count=len(feed), today_sum=sum(f["amount"] for f in feed), daily_limit=DAILY_CLAN_LIMIT, daily_used=_get_daily_contributed(inter.author.id))
        except Exception as e: return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_last_{inter.author.id}.png")

    @disnake.ui.button(label=f"{P}Общий пул{P}", style=ButtonStyle.gray, custom_id="clan_season:total", emoji=EMOJI_TOTAL)
    async def total(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); balance = await _get_balance(inter.author.id); clans_data, total_bank, total_members, top_clan, top_bank = [], 0, 0, None, -1
        for c in get_all_clans():
            bank, members = get_clan_bank(c["id"]), get_clan_members_count(c["id"])
            clans_data.append({"clan": c, "bank": bank}); total_bank += bank; total_members += members
            if bank > top_bank: top_bank, top_clan = bank, c
        try:
            from clan.render import render_clan_total_pool
            buf = render_clan_total_pool(inter.author.id, balance, total_bank, clans_data, total_members, top_clan)
        except Exception as e: return await inter.response.send_message(f"❌ Ошибка рендера: `{str(e)[:200]}`", ephemeral=True)
        await _send_clan_screen(inter, buf, f"clan_pool_{inter.author.id}.png")

class ClanGamesView(View):
    def __init__(self): super().__init__(timeout=None)
    @disnake.ui.button(label=f"{P}Квесты для копилки{P}", style=ButtonStyle.gray, custom_id="clan_games:quests", emoji=EMOJI_QUESTS)
    async def quests(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); clan = get_user_clan(inter.author.id); quests = get_user_quests(inter.author.id)
        for q in quests: q["reward_cut"] = clan_cut(q["reward"])
        e = disnake.Embed(color=clan["color"] if clan else 6776679); file = None
        try:
            from modules.shop.render_quests import render_quests
            buf = render_quests(inter.author.id, quests); file = disnake.File(buf, filename=f"quests_{inter.author.id}.png"); e.set_image(url=f"attachment://quests_{inter.author.id}.png")
            await inter.response.send_message(embed=e, file=file, ephemeral=True)
        except Exception as ex: return await inter.response.send_message(f"❌ Ошибка: `{str(ex)[:200]}`", ephemeral=True)

    @disnake.ui.button(label=f"{P}Игровые автоматы{P}", style=ButtonStyle.gray, custom_id="clan_games:slots", emoji=EMOJI_SLOTS)
    async def slots(self, button, inter):
        await on_panel_click_quest_hook(inter.author.id); e1 = disnake.Embed(color=6776679).set_image(url=IMG_SLOTS_TOP)
        e2 = disnake.Embed(title="Игровые автоматы", description="> Выбери игру, чтобы сыграть.\n> Все выигрыши — 100% суммы в копилку клана.", color=6776679).set_image(url=IMG_STRIPE)
        view = View(timeout=300); select = Select(placeholder="В какую игру хочешь сыграть?", options=[SelectOption(label="Рулетка", description="Поставь Diamond Coins на удачу!", emoji=EMOJI_ROULETTE, value="roulette"), SelectOption(label="Блэкджек", description="21 очко — классика казино!", emoji=EMOJI_BLACKJACK, value="blackjack"), SelectOption(label="Монетка", description="Орёл или решка? Быстрая игра!", emoji=EMOJI_COINFLIP, value="coinflip"), SelectOption(label="Кейсы", description="Испытай удачу и забери ценный приз", emoji=EMOJI_CASES, value="cases")], custom_id="clan_games_select")
        select.callback = _clan_games_select_callback; view.add_item(select); await inter.response.send_message(embeds=[e1, e2], view=view, ephemeral=True)

async def _clan_games_select_callback(inter):
    value = inter.data.values[0]
    if value == "cases": return await show_cases_screen(inter)
    from modules.actions import RouletteModal, BlackjackBetModal, CoinflipBetModal
    if value == "roulette": await inter.response.send_modal(RouletteModal())
    elif value == "blackjack": await inter.response.send_modal(BlackjackBetModal())
    elif value == "coinflip": await inter.response.send_modal(CoinflipBetModal())

async def send_clan_pool_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_POOL_CHANNEL_ID"]) or await bot.fetch_channel(CONFIG["CLAN_POOL_CHANNEL_ID"])
    if not ch: return
    async for msg in ch.history(limit=50):
        if msg.author == bot.user:
            try: await msg.delete()
            except Exception: pass
    await ch.send(embeds=_build_static_pool_embeds(), view=ClanPoolView())
async def send_clan_season_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"]) or await bot.fetch_channel(CONFIG["CLAN_SEASON_CHANNEL_ID"])
    if not ch: return
    async for msg in ch.history(limit=50):
        if msg.author == bot.user and msg.components:
            try: await msg.delete(); break
            except Exception: pass
    await ch.send(embeds=_build_season_static_embeds(), view=ClanSeasonView())
async def send_clan_games_panel(bot):
    ch = bot.get_channel(CONFIG["CLAN_GAMES_CHANNEL_ID"]) or await bot.fetch_channel(CONFIG["CLAN_GAMES_CHANNEL_ID"])
    if not ch: return
    async for msg in ch.history(limit=50):
        if msg.author == bot.user:
            try: await msg.delete()
            except Exception: pass
    await ch.send(embeds=_build_games_embeds(), view=ClanGamesView())

async def update_clan_pool_embed(bot):
    await send_clan_pool_panel(bot); await send_clan_season_panel(bot); await send_clan_games_panel(bot)
async def _post_clan_news(bot, title: str, news: str, description: str):
    try:
        ch = bot.get_channel(CONFIG["CLAN_NEWS_CHANNEL_ID"]) or await bot.fetch_channel(CONFIG["CLAN_NEWS_CHANNEL_ID"])
        if not ch: return
        await ch.send(embeds=[disnake.Embed(color=6776679).set_image(url=IMG_NEWS_TOP), disnake.Embed(title=title, description=f"> Новость: {news}\n\n> Описание: {description}\n", color=6776679).set_image(url=IMG_STRIPE)])
    except Exception: pass
async def post_news_season_start(bot):
    cycle = get_current_cycle()
    if cycle: await _post_clan_news(bot, f"Старт — {get_season_title(cycle['number'])}", f"Стартует новый сезон — **{get_season_title(cycle['number'])}**.", f"{get_season_title(cycle['number'])} официально открыт. Копилки кланов обнулены, отсчёт пошёл. Участники могут зарабатывать DC, выполнять квесты и вносить вклад в банк клана. Финал — **28 числа в 20:00 МСК**.")
async def post_news_season_3days(bot):
    cycle = get_current_cycle()
    if cycle: await _post_clan_news(bot, "До финала клубной лиги 3 дня", f"До финала сезона «{get_season_name(cycle['number'])}» осталось 3 дня.", f"Самое время увеличить свой вклад в банк клана. Топ-1 получит бонус ×7.00, Топ-2 — ×5.00, Топ-3 — ×3.00, остальные — ×1.50. Финал — **28 числа в 20:00 МСК**.")
async def post_news_season_1hour(bot):
    cycle = get_current_cycle()
    if cycle: await _post_clan_news(bot, "Час до финала клубной лиги", f"Остался последний час до финала сезона «{get_season_name(cycle['number'])}».", f"Успей внести последний вклад в свой клан. После 20:00 МСК банк будет распределён между участниками. Топ-1 забирает ×7.00, Топ-2 — ×5.00, Топ-3 — ×3.00.")
async def post_news_season_end(bot, report: dict):
    cycle = report["cycle"]; season_title = get_season_title(cycle["number"]); total = sum(c["bank"] for c in report["clans"]); top_clan = max(report["clans"], key=lambda x: x["bank"]) if report["clans"] else None
    winner_line = f"Победитель сезона — {top_clan['clan']['emoji']} **{top_clan['clan']['name'].upper()}** с банком {top_clan['bank']} DC. " if top_clan else ""
    await _post_clan_news(bot, f"{season_title} завершён", f"{season_title} официально завершён.", f"{winner_line}Общий пул всех кланов составил {total} DC. Выплаты произведены всем участникам, топ-3 по вкладу получили повышенные коэффициенты. Новый сезон стартует через 5 минут.")
async def post_news_weekly(bot):
    cycle = get_current_cycle()
    if not cycle: return
    total_bank, top_clan, top_bank = 0, None, -1
    for c in get_all_clans():
        bank = get_clan_bank(c["id"]); total_bank += bank
        if bank > top_bank: top_bank, top_clan = bank, c
    desc = f"В лидерах — {top_clan['emoji']} **{top_clan['name'].upper()}** с банком {top_bank} DC. Общий пул всех кланов составляет {total_bank} DC. До конца сезона осталось совсем немного — успей поддержать свой клан." if top_clan else f"Общий пул кланов: {total_bank} DC. Успей поддержать свой клан."
    await _post_clan_news(bot, "Итоги недели в клубной лиге", f"Еженедельный отчёт по сезону «{get_season_name(cycle['number'])}».", desc)

class ClanReportModal(Modal):
    def __init__(self): super().__init__(title="📊 Отчёт по клану в ЛС", components=[TextInput(label="ID юзера (пусто = свой клан)", placeholder="Например: 796293832751972352", custom_id="target_id", required=False, max_length=30)], custom_id="clan_report_modal")
    async def callback(self, inter):
        if not _is_admin(inter): return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(ephemeral=True); raw = (inter.text_values.get("target_id") or "").strip(); check_uid = inter.author.id
        if raw:
            if not raw.isdigit(): return await inter.edit_original_response(content="❌ ID должен быть числом.")
            check_uid = int(raw)
        clan = get_user_clan(check_uid)
        if not clan: return await inter.edit_original_response(content=f"❌ У юзера `{check_uid}` нет клана.")
        try: await send_detailed_report_dm(inter.bot, inter.author.id, clan["id"], inter.guild)
        except Exception as e: return await inter.edit_original_response(content=f"❌ Ошибка отправки: `{str(e)[:200]}`")
        await inter.edit_original_response(content=f"✅ Отчёт по клану {clan['emoji']} **{clan['name']}** отправлен в ЛС!")

class ClanAdminSelect(disnake.ui.StringSelect):
    def __init__(self):
        super().__init__(placeholder="Выберите действие...", min_values=1, max_values=1, options=[SelectOption(label="・Обновление кланов", description="Роли + чистка + распределение", emoji="🔄", value="update_clans"), SelectOption(label="・Пересобрать кланы", description="Снять всех и раскидать заново", emoji="🎲", value="rebuild_clans"), SelectOption(label="・Пересчитать достижения", description="Выдать всем недостающие ачивки", emoji="🏆", value="recalc_ach"), SelectOption(label="・Бонус всем кланам", description="+100 DC в копилку", emoji="🎁", value="give_bonus"), SelectOption(label="・Отчёт по клану в ЛС", description="Полная статистика + плюсы и минусы", emoji="📊", value="report"), SelectOption(label="・Обновить панели", description="Пересобрать эмбеды", emoji="🖼", value="refresh")], custom_id="clan_admin_select")
    async def callback(self, inter):
        if not _is_admin(inter): return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        value = inter.data.values[0]
        if value == "report": return await inter.response.send_modal(ClanReportModal())
        await inter.response.defer(with_message=True, ephemeral=True)
        if value == "update_clans": await self._update_clans(inter)
        elif value == "rebuild_clans": await self._confirm_rebuild(inter)
        elif value == "recalc_ach": await self._recalc_ach(inter)
        elif value == "give_bonus": await self._give_bonus(inter)
        elif value == "refresh": await update_clan_pool_embed(inter.bot); await inter.edit_original_response(content="✅ Панели обновлены.")
            
    async def _give_bonus(self, inter):
        try:
            cycle = get_current_cycle()
            if not cycle: return await inter.edit_original_response(content="❌ Нет активного сезона.")
            for cid in [1, 2, 3]: cur.execute("INSERT INTO clan_contributions (cycle_id, clan_id, user_id, amount, reason, ts) VALUES (?, ?, ?, ?, ?, ?)", (cycle["id"], cid, 0, 100, "Админ-бонус клубам", int(time.time())))
            db.commit(); await inter.edit_original_response(content="✅ Всем кланам начислено по **100 DC** в копилку!")
        except Exception as e: await inter.edit_original_response(content=f"❌ Ошибка: {str(e)[:100]}")
    async def _confirm_rebuild(self, inter): await inter.edit_original_response(content="⚠️ **Полная пересборка кланов**\n\n> Снимет роли кланов **у всех** и раскидает заново случайно.\n> Вклады за сезон переедут за людьми в их новые кланы.\n\n> Точно делаем?", view=ClanRebuildConfirmView())
    async def _update_clans(self, inter):
        try:
            await inter.edit_original_response(content="⏳ Обновляю кланы: роли, чистка, распределение...\n> Это может занять пару минут.")
            stats = await recalculate_clan_league(inter.guild); await update_clan_pool_embed(inter.bot)
            await inter.edit_original_response(content=f"✅ **Обновление кланов завершено**\n\n**Роли покупателей**\n> 🔍 Пересчитано: **{stats['roles_checked']}**\n> ⚠️ Ошибок: **{stats['roles_errors']}**\n\n**Чистка кланов**\n> 📋 Условия (баланс < {MIN_BALANCE} DC, нет роли, нет действий {INACTIVE_DAYS_LIMIT} дн.)\n> 👀 Проверено: **{stats['members_checked']}**\n> 🚪 Исключено: **{stats['removed']}**\n> 💸 Вкладов вычищено: **{stats.get('removed_dc', 0)} DC**\n> ⏳ Первый отсчёт: **{stats.get('seeded', 0)}**\n\n**Распределение**\n> ♻️ Возвращены роли: **{stats.get('repaired', 0)}**\n> 🔄 Вклады перенесены: **{stats.get('moved', 0)}**\n> ✅ Выдан клан: **{stats['assigned']}**\n> 👥 Уже были в клане: **{stats['skipped']}**\n> ⛔ Жёсткое исключение: **{stats['excluded']}**")
        except Exception as e: await inter.edit_original_response(content=f"❌ Ошибка обновления кланов: `{str(e)[:300]}`")
    async def _recalc_ach(self, inter):
        try:
            from clan.achievements import recalculate_all_achievements
            await inter.edit_original_response(content="⏳ Начинаю пересчёт достижений...\n> Всем получателям придут ЛС.")
            stats = await recalculate_all_achievements(inter.bot)
            await inter.edit_original_response(content=f"✅ **Пересчёт завершён!**\n\n> **Проверено:** `{stats['checked']}`\n> **Ошибок:** `{stats['errors']}`\n\n> Всем получателям отправлены ЛС о новых достижениях.")
        except Exception as e: await inter.edit_original_response(content=f"❌ Ошибка пересчёта: `{str(e)[:300]}`")

class ClanAdminView(View):
    def __init__(self): super().__init__(timeout=None); self.add_item(ClanAdminSelect())
def _is_admin(inter) -> bool:
    from core.utils import has_admin_command_roles
    return has_admin_command_roles(inter.author)
class ClanRebuildConfirmView(View):
    def __init__(self): super().__init__(timeout=120)
    @disnake.ui.button(label="Да, снять всех и раскидать", style=ButtonStyle.danger, custom_id="clan_rebuild:yes", emoji="🎲")
    async def confirm(self, button, inter):
        if not _is_admin(inter): return await inter.response.send_message("⛔ Нет прав.", ephemeral=True)
        await inter.response.defer(with_message=True, ephemeral=True); await _run_clan_rebuild(inter)
    @disnake.ui.button(label="Отмена", style=ButtonStyle.secondary, custom_id="clan_rebuild:no")
    async def cancel(self, button, inter): await inter.response.edit_message(content="❌ Пересборка кланов отменена.", view=None)
async def _run_clan_rebuild(inter):
    try:
        await inter.edit_original_response(content="🎲 Пересобираю кланы...\n> Может занять пару минут.", view=None)
        stats = await rebuild_clans_random(inter.guild); await update_clan_pool_embed(inter.bot); dist_lines = "\n".join(f"> · {name}: **{count}**" for name, count in stats["distribution"].items())
        await inter.edit_original_response(content=f"🎲 **Кланы пересобраны с нуля**\n\n**Снято**\n> 🚪 Освобождено: **{stats['stripped']}** чел.\n> ⚠️ Ошибок снятия: **{stats['strip_errors']}**\n\n**Раскидано**\n> ✅ Получили клан: **{stats['assigned']}**\n> 🚫 Не прошли условия: **{stats['skipped']}**\n> ⚠️ Ошибок с ролями: **{stats['role_errors']}**\n\n**Новая раскладка**\n{dist_lines}\n\n> 🔄 Вклады перенесены: **{stats['moved']}** записей", view=None)
    except Exception as e: await inter.edit_original_response(content=f"❌ Ошибка пересборки: `{str(e)[:300]}`", view=None)
async def send_clan_admin_panel(bot):
    ch = bot.get_channel(1551276116679860314) or await bot.fetch_channel(1551276116679860314)
    if not ch: return
    async for msg in ch.history(limit=30):
        if msg.author == bot.user and msg.embeds:
            for e in msg.embeds:
                if e.title and "клановой лигой" in e.title.lower():
                    try: await msg.delete(); break
                    except Exception: pass
    await ch.send(embed=disnake.Embed(title="Управление клановой лигой", description="> Обновление кланов, пересборка, пересчёт достижений, обновление панелей.\n> Сезон идёт автоматически: старт и выплата 28-го числа в 20:00 МСК.\n> Условие в клане: баланс ≥ 45 DC, роль покупателя, активность за 30 дней.\n> **📊 Отчёт по клану** — выгружает полную статистику в ЛС.", color=0x676767).set_image(url=IMG_STRIPE), view=ClanAdminView())

_last_payout_date, _news_sent = None, {"3days": None, "1hour": None, "weekly": None}
def start_clan_tasks(bot):
    if not _clan_cycle_task.is_running(): _clan_cycle_task.start(bot)
    if not _clan_daily_reset_task.is_running(): _clan_daily_reset_task.start(bot)
    if not _clan_weekly_reset_task.is_running(): _clan_weekly_reset_task.start(bot)
    if not _clan_news_task.is_running(): _clan_news_task.start(bot)
    if not _clan_prune_task.is_running(): _clan_prune_task.start(bot)
@tasks.loop(minutes=1)
async def _clan_cycle_task(bot):
    global _last_payout_date
    await bot.wait_until_ready(); now = datetime.now(MSK); today = now.date(); cycle = get_current_cycle()
    if not cycle:
        if now.day == 28 and now.hour == 20 and now.minute < 2: start_new_cycle(); await update_clan_pool_embed(bot); await post_news_season_start(bot)
        return
    if cycle["ends_at"] <= int(time.time()):
        if _last_payout_date == today: return
        _last_payout_date = today; await close_cycle_and_pay(bot)
@tasks.loop(minutes=1)
async def _clan_daily_reset_task(bot):
    await bot.wait_until_ready(); now = datetime.now(MSK)
    if now.hour == 0 and now.minute == 0: reset_daily_quests()
@tasks.loop(minutes=1)
async def _clan_weekly_reset_task(bot):
    await bot.wait_until_ready(); now = datetime.now(MSK)
    if now.weekday() == 0 and now.hour == 0 and now.minute == 0: reset_weekly_quests()
@tasks.loop(minutes=1)
async def _clan_news_task(bot):
    await bot.wait_until_ready()
    try:
        now = datetime.now(MSK); today = now.date(); cycle = get_current_cycle()
        if not cycle: return
        if now.day == 25 and now.hour == 20 and now.minute < 2 and _news_sent["3days"] != today: _news_sent["3days"] = today; await post_news_season_3days(bot)
        if now.day == 28 and now.hour == 19 and now.minute < 2 and _news_sent["1hour"] != today: _news_sent["1hour"] = today; await post_news_season_1hour(bot)
        if now.weekday() == 6 and now.hour == 20 and now.minute < 2 and _news_sent["weekly"] != today: _news_sent["weekly"] = today; await post_news_weekly(bot)
    except Exception: pass
@tasks.loop(hours=6)
async def _clan_prune_task(bot):
    await bot.wait_until_ready()
    try:
        guild = bot.get_guild(int(CONFIG["GUILD_ID"]))
        if not guild: return
        result = await prune_ineligible_clan_members(guild)
        if result["removed"] > 0: await update_clan_pool_embed(bot)
    except Exception: pass
def init_clan_panels(): pass
async def handle_clan_interaction(inter): pass
