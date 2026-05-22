#!/usr/bin/env python3
"""
Интерактивный сбор ID тем канала.

Запуск:
  ./bot.sh stop            # сначала останови бота
  python3 get_topics.py    # запусти этот скрипт

Затем зайди в каждую тему группы и напиши точное название направления
(например: Дагестан, Китай, Узбекистан).
Скрипт сам построит topics.json.
Ctrl+C — завершить и сохранить.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_STR = os.getenv("REPORT_CHANNEL_ID", "")


async def main() -> None:
    if not TOKEN or not CHANNEL_STR:
        sys.exit("Заполни TELEGRAM_BOT_TOKEN и REPORT_CHANNEL_ID в .env")

    channel_id = int(CHANNEL_STR)
    topics_file = Path(__file__).parent / "topics.json"

    print("=" * 55)
    print("ВАЖНО: бот должен быть остановлен (./bot.sh stop)")
    print("=" * 55)
    print()
    print("Зайди в каждую тему группы и напиши точное")
    print("название направления (Дагестан, Китай, и т.д.).")
    print("Ctrl+C — завершить.\n")
    print(f"{'Thread ID':>12}  Направление")
    print("─" * 40)

    mapping: dict[str, int] = {}
    offset = 0

    async with httpx.AsyncClient(timeout=35) as client:
        # Сброс старых апдейтов
        r = await client.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": -1},
        )
        result = r.json().get("result", [])
        if result:
            offset = result[-1]["update_id"] + 1

        print("Слушаю сообщения...\n")
        try:
            while True:
                r = await client.get(
                    f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                    params={"offset": offset, "timeout": 25},
                )
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    if msg.get("chat", {}).get("id") != channel_id:
                        continue
                    tid = msg.get("message_thread_id")
                    text = (msg.get("text") or "").strip()
                    if tid and text:
                        mapping[text] = tid
                        print(f"{tid:>12}  {text}")
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

    if not mapping:
        print("\nНичего не получено. Попробуй ещё раз.")
        return

    # Загружаем существующий topics.json и обновляем
    existing: dict = {}
    if topics_file.exists():
        existing = json.loads(topics_file.read_text(encoding="utf-8"))

    merged = {**existing, **mapping}
    # Сохраняем _default если есть
    merged.setdefault("_default", None)

    topics_file.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n✅ topics.json обновлён — {len(mapping)} тем сохранено.")
    print("Запускай бота: ./bot.sh start")


if __name__ == "__main__":
    asyncio.run(main())
