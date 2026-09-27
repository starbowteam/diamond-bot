# -*- coding: utf-8 -*-
"""
Автозамена ссылки страйпа (stripe) во всех файлах проекта.

Использование:
  · Автоматически: добавь в main.py (см. инструкцию)
  · Вручную: python fix_stripe.py

Заменяет ЛЮБУЮ ссылку на файл 1537851307757539390/image.png
(с любыми устаревшими ex/is/hm) — на актуальную чистую.
"""
import os
import re
from pathlib import Path

# ============================================================
# КОНФИГ
# ============================================================
NEW_URL = (
    "https://cdn.discordapp.com/attachments/1527006158282555412/"
    "1537851307757539390/image.png"
    "?ex=6aba8d23&is=6ab93ba3&"
    "hm=ae3ed04a3d7751d003df0753d1784af492fd0ad971a033f3dafca3a5b57cb26d&"
)

# Регулярка ловит любую ссылку на этот файл с хвостом ?...&
# Включая порченные ссылки с мусором (&https%3A%2F%2F...)
STRIPE_URL_RE = re.compile(
    r"https://cdn\.discordapp\.com/attachments/1527006158282555412/"
    r"1537851307757539390/image\.png\?[^\s\"'\)\]]+"
)

BASE_DIR = Path(__file__).parent.resolve()

EXCLUDE_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".backup_stripe", ".idea", ".vscode",
}

VALID_EXTS = {".py", ".json", ".txt", ".md"}


# ============================================================
# ЛОГИКА
# ============================================================
def should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
    return path.suffix.lower() not in VALID_EXTS


def fix_content(content: str) -> tuple[str, int]:
    """Возвращает (новое содержимое, число замен)."""
    matches = STRIPE_URL_RE.findall(content)
    count = len(matches)
    if count == 0:
        return content, 0
    new_content = STRIPE_URL_RE.sub(NEW_URL, content)
    return new_content, count


def run_fix(verbose: bool = True) -> dict:
    """Проходит по всем файлам, чинит ссылки. Возвращает статистику."""
    stats = {
        "scanned": 0,
        "changed": 0,
        "total_replacements": 0,
        "files": [],
    }

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for fname in files:
            path = Path(root) / fname
            if should_skip(path):
                continue

            stats["scanned"] += 1

            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, PermissionError, IsADirectoryError):
                continue

            new_content, count = fix_content(content)
            if count == 0:
                continue

            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)

                stats["changed"] += 1
                stats["total_replacements"] += count
                rel = str(path.relative_to(BASE_DIR))
                stats["files"].append((rel, count))

                if verbose:
                    print(f"  ✅ {rel} — {count} замен")

            except Exception as e:
                if verbose:
                    print(f"  ❌ {path}: {e}")

    return stats


# ============================================================
# ТОЧКА ВХОДА (если запускается как скрипт)
# ============================================================
def main():
    print("🔧 Автозамена ссылок страйпа (stripe)")
    print(f"📂 {BASE_DIR}")
    print()
    print("🔍 Сканирую .py / .json / .txt / .md ...")
    print()

    stats = run_fix(verbose=True)

    print()
    print("=" * 55)
    print(f"📊 Просканировано файлов:      {stats['scanned']}")
    print(f"✏️  Изменено файлов:            {stats['changed']}")
    print(f"🔄 Всего ссылок заменено:      {stats['total_replacements']}")

    if stats["changed"] == 0:
        print()
        print("✅ Всё актуально, менять нечего.")
    else:
        print()
        print("✅ Готово!")

    return stats


if __name__ == "__main__":
    main()
