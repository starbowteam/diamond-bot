# -*- coding: utf-8 -*-
"""
Ручная очистка вклада конкретного юзера.
Использование:
    python -m clan.cleanup 1124040555240898631
или из бота — через clan.core.cleanup_specific_user(uid)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import logger, db, cur, load_json, save_json, FILES
from clan.core import cleanup_specific_user


def main():
    if len(sys.argv) < 2:
        print("Использование: python -m clan.cleanup <user_id>")
        sys.exit(1)

    try:
        uid = int(sys.argv[1])
    except ValueError:
        print(f"❌ ID должен быть числом, получено: {sys.argv[1]}")
        sys.exit(1)

    print(f"\n🔍 Сканирую вклады юзера {uid}...\n")

    rows = cur.execute(
        "SELECT cycle_id, clan_id, amount, reason, ts FROM clan_contributions "
        "WHERE user_id=? ORDER BY ts",
        (uid,)
    ).fetchall()

    if not rows:
        print(f"✅ У юзера {uid} нет записей в clan_contributions.\n")
    else:
        print(f"📋 Найдено записей: {len(rows)}\n")
        print(f"{'Дата':<20} {'Клан':<20} {'Сумма':<15} {'Причина':<40}")
        print("-" * 100)

        from datetime import datetime, timezone
        total = 0
        for r in rows:
            c = cur.execute("SELECT name, emoji FROM clans WHERE id=?", (r["clan_id"],)).fetchone()
            clan_str = f"{c['emoji']} {c['name']}" if c else f"clan_{r['clan_id']}"
            dt = datetime.fromtimestamp(r["ts"]).strftime("%d.%m.%Y %H:%M")
            print(f"{dt:<20} {clan_str:<20} {r['amount']:>13} DC  {r['reason'][:40]:<40}")
            total += r["amount"]

        print("-" * 100)
        print(f"{'ИТОГО:':<42} {total:>13} DC\n")

    # Достижения этого юзера (показать что удалим)
    ach_rows = cur.execute(
        "SELECT ach_key, unlocked_at FROM clan_achievements WHERE user_id=?",
        (uid,)
    ).fetchall()
    if ach_rows:
        print(f"🏆 Достижений у юзера: {len(ach_rows)}")
        for a in ach_rows[:10]:
            print(f"   · {a['ach_key']}")
        if len(ach_rows) > 10:
            print(f"   ... и ещё {len(ach_rows) - 10}")
        print()

    print(f"🧹 Очищаю вклады...")
    report = cleanup_specific_user(uid)

    print(f"\n✅ ГОТОВО")
    print(f"   Юзер: {report['user_id']}")
    print(f"   Удалено записей вклада: {report['count']}")
    print(f"   Удалено DC: {report['total']}")
    print(f"   По кланам:")
    for cs in report["by_clan"]:
        print(f"     · {cs['clan']}: {cs['amount']} DC")
    print(f"   По циклам:")
    for cs in report["by_cycle"]:
        print(f"     · {cs['cycle']}: {cs['amount']} DC")

    # Спрашиваем про достижения
    if ach_rows:
        print(f"\n❓ Удалить также достижения этого юзера? (y/n)")
        try:
            ans = input("> ").strip().lower()
            if ans in ("y", "yes", "да"):
                cur.execute("DELETE FROM clan_achievements WHERE user_id=?", (uid,))
                db.commit()
                print(f"✅ Удалено достижений: {len(ach_rows)}")
            else:
                print("⏭ Достижения оставлены.")
        except Exception:
            pass

    print()


if __name__ == "__main__":
    main()
