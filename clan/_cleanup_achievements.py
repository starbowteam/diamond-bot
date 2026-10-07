# -*- coding: utf-8 -*-
"""
⚠️ ОДНОРАЗОВЫЙ СКРИПТ. Удаляет старые ключи достижений из БД.
Вызывается из clan/__init__.py при старте. После первого запуска —
можешь удалить вызов из clan/__init__.py и сам файл.
"""
from core.utils import db, cur, logger


OLD_ACH_KEYS = {
    "king", "legend",
    "buyer_5", "buyer_25", "buyer_100", "buyer_500",
    "rich_500k", "investor_500k",
    "reviewer_50", "reviewer_500",
    "clan_5k", "clan_loyal", "clan_hunter", "clan_sniper",
    "casino_lucky",
    "staff_hr_5", "staff_hr_50",
}


def run_cleanup_achievements() -> int:
    """Удаляет записи со старыми ключами. Идемпотентно."""
    if not OLD_ACH_KEYS:
        return 0
    try:
        placeholders = ",".join("?" * len(OLD_ACH_KEYS))
        cur.execute(
            f"DELETE FROM clan_achievements WHERE ach_key IN ({placeholders})",
            tuple(OLD_ACH_KEYS),
        )
        db.commit()
        removed = cur.rowcount or 0
        logger.info(
            f"🧹 Cleanup achievements: удалено {removed} старых записей "
            f"({len(OLD_ACH_KEYS)} ключей)"
        )
        return removed
    except Exception as e:
        logger.exception(f"run_cleanup_achievements: {e}")
        return 0
