# -*- coding: utf-8 -*-
"""Ядро клановой лиги."""
import os, time, math, asyncio, random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
import disnake
from core.utils import CONFIG, DATA_DIR, ADD_DIR, FILES, logger, db, cur, load_json, save_json, log_discord, now_ts, get_dc_cache, save_dc_cache, update_user_roles

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

CLANS_DATA = [{"id": 1, "name": "Мультяшности", "emoji": "🎮", "role_id": 1552707675257831525, "color": 0xb3e1b9, "color_dark": 0x749472, "fa_icon": "fa-gamepad", "description": "Яркие, как мультфильмы. Энергия, юмор и лёгкость на подъём."}, {"id": 2, "name": "Сияние", "emoji": "✨", "role_id": 1552707025723465838, "color": 0xaa8ae7, "color_dark": 0x582189, "fa_icon": "fa-star", "description": "Свет звёзд в ночи. Яркие, амбициозные, недосягаемые."}, {"id": 3, "name": "Кристализация", "emoji": "💎", "role_id": 1551280425312194650, "color": 0x8799ae, "color_dark": 0xf1f7ff, "fa_icon": "fa-gem", "description": "Чистота формы и холодный расчёт. Всё по полочкам."}]

def init_clan_core():
    for c in CLANS_DATA: cur.execute("INSERT OR IGNORE INTO clans (id, name, emoji, role_id, color, description) VALUES (?, ?, ?, ?, ?, ?)", (c["id"], c["name"], c["emoji"], c["role_id"], c["color"], c["description"]))
    cur.execute("CREATE TABLE IF NOT EXISTS clan_daily_limit (user_id INTEGER, date TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY (user_id, date))"); db.commit()
    cleanup_excluded_users(); ensure_active_cycle()
    try:
        if not get_user_clan(CREATOR_ID):
            cur.execute("INSERT OR REPLACE INTO clan_members (user_id, clan_id, joined_at, left_at, cycle_joined) VALUES (?, ?, ?, NULL, ?)", (CREATOR_ID, 1, int(time.time()), 0)); db.commit()
    except Exception: pass

def ensure_active_cycle() -> Optional[dict]:
    cycle = get_current_cycle()
    if cycle: return cycle
    return start_new_cycle()

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
