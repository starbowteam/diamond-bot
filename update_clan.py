# -*- coding: utf-8 -*-
"""Разово: переименовать клан id=1 в 'Мультяшности'."""
import sqlite3
import os

DB = "data/diamond.db"

if not os.path.exists(DB):
    print(f"❌ Файл не найден: {DB}")
    raise SystemExit(1)

db = sqlite3.connect(DB)

# Показать до
rows = db.execute("SELECT id, name FROM clans ORDER BY id").fetchall()
print("ДО:")
for r in rows:
    print(f"  id={r[0]}  name={r[1]}")

# Обновить
db.execute("UPDATE clans SET name='Мультяшности' WHERE id=1")
db.commit()

# Показать после
rows = db.execute("SELECT id, name FROM clans ORDER BY id").fetchall()
print("ПОСЛЕ:")
for r in rows:
    print(f"  id={r[0]}  name={r[1]}")

db.close()
print("✅ Готово")
