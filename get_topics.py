#!/usr/bin/env python3
"""Утилита: выводит список тем канала с их ID."""
import asyncio
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL = os.getenv("REPORT_CHANNEL_ID", "")


async def main() -> None:
    if not TOKEN or not CHANNEL:
        print("Заполни TELEGRAM_BOT_TOKEN и REPORT_CHANNEL_ID в .env")
        return

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"https://api.telegram.org/bot{TOKEN}/getForumTopics",
            params={"chat_id": CHANNEL, "limit": 100},
        )
    data = r.json()

    if not data.get("ok"):
        print(f"Ошибка: {data.get('description')}")
        print("Проверь: бот добавлен администратором в канал/группу с темами?")
        return

    topics = data["result"]["topics"]
    print(f"\nНайдено тем: {len(topics)}\n")
    print(f"{'ID':>10}  {'Название'}")
    print("─" * 40)
    for t in topics:
        print(f"{t['message_thread_id']:>10}  {t['name']}")

    # Генерируем topics.json с найденными темами
    topics_file = Path(__file__).parent / "topics.json"
    existing: dict = {}
    if topics_file.exists():
        existing = json.loads(topics_file.read_text(encoding="utf-8"))

    mapping = {t["name"]: t["message_thread_id"] for t in topics}
    # Сохраняем уже заданные значения, добавляем новые
    merged = {**{n: None for n in mapping}, **existing, **mapping}
    merged["_default"] = existing.get("_default")

    topics_file.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\ntopics.json обновлён → {topics_file}")
    print("Отредактируй его при необходимости, затем перезапусти бота: ./bot.sh restart")


if __name__ == "__main__":
    asyncio.run(main())
