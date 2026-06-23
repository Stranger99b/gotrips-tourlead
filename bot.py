#!/usr/bin/env python3
"""GoTrips Tourlead — бот для отчётов турлидеров."""
import logging
import warnings
from datetime import datetime
from logging.handlers import RotatingFileHandler

warnings.filterwarnings("ignore", message=".*per_message=False.*")

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
    ContextTypes,
)

def _md(text: str) -> str:
    """Escape user-provided text for Markdown v1."""
    return str(text).replace("_", r"\_").replace("*", r"\*").replace("`", r"\`").replace("[", r"\[")


from config import (
    ALLOWED_USER_IDS,
    BASE_DIR,
    BOT_TOKEN,
    CHANNEL_ID,
    DEEPGRAM_API_KEY,
    TOPIC_IDS,
    TOUR_DIRECTIONS,
)
from transcription import transcribe

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
    handlers=[
        RotatingFileHandler(
            BASE_DIR / "bot.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    ],
)
# httpx логирует каждый getUpdates на INFO — это раздувало лог до десятков МБ.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Conversation states ──────────────────────────────────────────────────────
SELECTING_DIRECTION, TYPING_DIRECTION, SELECTING_DATE, COLLECTING = range(4)


# ── Keyboards ────────────────────────────────────────────────────────────────

def _main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["📋 Начать отчет"]], resize_keyboard=True)


def _collect_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["✅ Закрыть отчет"]], resize_keyboard=True)


def _directions_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TOUR_DIRECTIONS), 2):
        row = [InlineKeyboardButton(TOUR_DIRECTIONS[i], callback_data=f"dir:{TOUR_DIRECTIONS[i]}")]
        if i + 1 < len(TOUR_DIRECTIONS):
            row.append(InlineKeyboardButton(TOUR_DIRECTIONS[i + 1], callback_data=f"dir:{TOUR_DIRECTIONS[i + 1]}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Другое направление", callback_data="dir:__other__")])
    return InlineKeyboardMarkup(rows)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_allowed(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def _display_name(update: Update) -> str:
    u = update.effective_user
    name = f"{u.first_name or ''} {u.last_name or ''}".strip()
    return f"{name} (@{u.username})" if u.username else (name or f"ID:{u.id}")


# ── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ закрыт. Обратитесь к администратору.")
        return ConversationHandler.END

    ctx.user_data.pop("report", None)
    ctx.user_data.pop("direction", None)

    await update.message.reply_text(
        f"Привет, {update.effective_user.first_name}! 👋\n\n"
        "Это бот для отправки отчётов турлидеров *GoTrips*.\n\n"
        "Нажми кнопку ниже, чтобы создать отчёт по туру.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_main_kb(),
    )
    return ConversationHandler.END


async def start_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ закрыт.")
        return ConversationHandler.END

    # Если есть незакрытый отчёт — предлагаем продолжить
    report = ctx.user_data.get("report")
    if report:
        n = len(report["items"])
        await update.message.reply_text(
            f"⚠️ У тебя есть незакрытый отчёт:\n"
            f"🗺 *{_md(report['direction'])}* · {_md(report['date'])}\n"
            f"📝 Сообщений: {n}\n\n"
            "Продолжай добавлять материалы. Когда закончишь — нажми «✅ Закрыть отчет».\n\n"
            "Чтобы отменить текущий отчёт — /cancel",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_collect_kb(),
        )
        return COLLECTING

    await update.message.reply_text(
        "🗺 Выбери направление тура:",
        reply_markup=_directions_kb(),
    )
    return SELECTING_DIRECTION


async def cb_direction(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    data = q.data[4:]  # strip "dir:"

    if data == "__other__":
        await q.edit_message_text("✏️ Напиши название направления тура:")
        return TYPING_DIRECTION

    ctx.user_data["direction"] = data
    await q.edit_message_text(f"✅ Направление: *{data}*", parse_mode=ParseMode.MARKDOWN)
    await q.message.reply_text("📅 Введи дату старта тура (например: 20.05.2026):")
    return SELECTING_DATE


async def type_direction(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    direction = update.message.text.strip()
    ctx.user_data["direction"] = direction
    await update.message.reply_text(
        f"✅ Направление: *{direction}*\n\n📅 Введи дату старта тура (например: 20.05.2026):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return SELECTING_DATE


async def enter_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    date = update.message.text.strip()
    direction = ctx.user_data.get("direction", "—")
    name = _display_name(update)

    ctx.user_data["report"] = {
        "direction": direction,
        "date": date,
        "tourlead_name": name,
        "tourlead_id": update.effective_user.id,
        "started_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "items": [],
    }

    await update.message.reply_text(
        f"📋 *Отчёт открыт*\n"
        f"{'─' * 24}\n"
        f"🗺 *Направление:* {_md(direction)}\n"
        f"📅 *Дата старта:* {_md(date)}\n"
        f"👤 *Турлидер:* {_md(name)}\n"
        f"{'─' * 24}\n\n"
        "Что можно добавить в отчёт:\n"
        "• 🎙 *Голосовые сообщения* _(расшифрую автоматически)_\n"
        "• 📝 Текст\n"
        "• 📸 Фото и видео\n"
        "• 📎 Документы\n\n"
        "📌 *Что хотим видеть в отчёте:*\n"
        "— Любые спорные ситуации в туре\n"
        "— Если всё прошло хорошо — так и напиши!\n"
        "— Замечания по отелям, транспорту, водителям\n"
        "— Оценка принимающей стороны\n"
        "— Технические неполадки\n\n"
        "Отправляй сколько угодно сообщений. Когда закончишь — нажми кнопку ниже 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_collect_kb(),
    )
    return COLLECTING


async def collect_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    # update.message бывает None, когда турлидер РЕДАКТИРУЕТ ранее отправленное
    # сообщение (тогда заполнено update.edited_message). Раньше это роняло хендлер
    # на msg.voice. effective_message покрывает оба случая.
    msg = update.effective_message
    if msg is None:
        return COLLECTING
    report = ctx.user_data.get("report")

    if not report:
        await msg.reply_text("Нет открытого отчёта. Нажми «📋 Начать отчет».", reply_markup=_main_kb())
        return ConversationHandler.END

    # Турлидер РЕДАКТИРУЕТ ранее отправленное сообщение → Telegram шлёт edited_message.
    # Раньше это добавляло ДУБЛЬ пункта в отчёт (одно сообщение уходило в канал 2-3 раза).
    # Теперь находим уже добавленный пункт по id исходного сообщения и обновляем его
    # НА МЕСТЕ, без повторного подтверждения/расшифровки. Если пункт не найден
    # (например, бот перезапускался) — просто игнорируем правку, дубль не создаём.
    if update.edited_message is not None:
        for item in report["items"]:
            if item.get("src_msg_id") == msg.message_id:
                if item["type"] == "text" and msg.text:
                    item["content"] = msg.text
                elif "caption" in item:
                    item["caption"] = msg.caption or ""
                break
        return COLLECTING

    if msg.voice or msg.audio:
        is_voice = bool(msg.voice)
        file_id = msg.voice.file_id if is_voice else msg.audio.file_id
        status = await msg.reply_text("🎙 Расшифровываю…")
        try:
            tg_file = await ctx.bot.get_file(file_id)
            audio_bytes = bytes(await tg_file.download_as_bytearray())
            text = await transcribe(audio_bytes, DEEPGRAM_API_KEY)
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            text = "[ошибка расшифровки]"

        report["items"].append({
            "type": "voice" if is_voice else "audio",
            "file_id": file_id,
            "transcription": text,
            "src_msg_id": msg.message_id,
        })
        # Обрезаем для отображения турлидеру (не обрезаем то что уйдёт в канал)
        preview = text[:500] + ("…" if len(text) > 500 else "")
        await status.edit_text(
            f"✅ *Расшифровано:*\n_{_md(preview)}_",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif msg.text:
        report["items"].append({"type": "text", "content": msg.text, "src_msg_id": msg.message_id})

    elif msg.photo:
        report["items"].append({
            "type": "photo",
            "file_id": msg.photo[-1].file_id,
            "caption": msg.caption or "",
            "src_msg_id": msg.message_id,
        })
        await msg.reply_text("📸 Фото добавлено в отчёт.")

    elif msg.video:
        report["items"].append({
            "type": "video",
            "file_id": msg.video.file_id,
            "caption": msg.caption or "",
            "src_msg_id": msg.message_id,
        })
        await msg.reply_text("🎬 Видео добавлено в отчёт.")

    elif msg.video_note:
        report["items"].append({"type": "video_note", "file_id": msg.video_note.file_id, "src_msg_id": msg.message_id})
        await msg.reply_text("🎬 Видео добавлено в отчёт.")

    elif msg.document:
        report["items"].append({
            "type": "document",
            "file_id": msg.document.file_id,
            "file_name": msg.document.file_name or "документ",
            "caption": msg.caption or "",
            "src_msg_id": msg.message_id,
        })
        await msg.reply_text(f"📎 Файл «{msg.document.file_name or 'документ'}» добавлен.")

    else:
        await msg.reply_text("⚠️ Этот тип сообщения не поддерживается, пропускаю.")

    return COLLECTING


async def close_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    report = ctx.user_data.get("report")

    if not report:
        await update.message.reply_text("Нет открытого отчёта.", reply_markup=_main_kb())
        return ConversationHandler.END

    closed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    wait_msg = await update.message.reply_text("⏳ Отправляю отчёт в канал…")

    try:
        await _send_to_channel(ctx, report, closed_at)
        ctx.user_data.pop("report", None)
        ctx.user_data.pop("direction", None)
        await wait_msg.delete()
        await ctx.bot.send_message(
            update.effective_chat.id,
            "✅ *Отчёт успешно отправлен!*\n\nСпасибо за работу 🙌\n\n"
            "👇 Нажми кнопку чтобы создать новый отчёт",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_main_kb(),
        )
    except Exception as e:
        logger.error(f"Report send failed: {e}")
        await wait_msg.edit_text("❌ Ошибка при отправке.")
        await ctx.bot.send_message(
            update.effective_chat.id,
            "❌ Не удалось отправить отчёт. Попробуй ещё раз или свяжись с администратором.",
            reply_markup=_collect_kb(),
        )
        return COLLECTING

    return ConversationHandler.END


async def _send_to_channel(ctx, report: dict, closed_at: str) -> None:
    bot = ctx.bot
    ch = CHANNEL_ID
    items = report["items"]

    # Определяем тему канала по направлению (fallback → _default → без темы)
    direction = report["direction"]
    thread_id: int | None = TOPIC_IDS.get(direction) or TOPIC_IDS.get("_default") or None

    # Все вызовы send_* получают thread_id если он задан
    thr = {"message_thread_id": thread_id} if thread_id else {}

    header = (
        f"📋 *ОТЧЁТ ТУРА*\n"
        f"{'━' * 26}\n"
        f"🗺 *Направление:* {_md(direction)}\n"
        f"📅 *Дата старта:* {_md(report['date'])}\n"
        f"👤 *Турлидер:* {_md(report['tourlead_name'])}\n"
        f"🕐 *Открыт:* {_md(report['started_at'])}   *Закрыт:* {_md(closed_at)}\n"
        f"📝 *Сообщений:* {len(items)}\n"
        f"{'━' * 26}"
    )
    await bot.send_message(ch, header, parse_mode=ParseMode.MARKDOWN, **thr)

    for idx, item in enumerate(items, 1):
        try:
            t = item["type"]
            if t == "text":
                await bot.send_message(ch, item["content"], **thr)

            elif t in ("voice", "audio"):
                tr = item["transcription"]
                await bot.send_message(
                    ch,
                    f"🎙 *Голосовое #{idx}:*\n{_md(tr)}",
                    parse_mode=ParseMode.MARKDOWN,
                    **thr,
                )
                if t == "voice":
                    await bot.send_voice(ch, item["file_id"], **thr)
                else:
                    await bot.send_audio(ch, item["file_id"], **thr)

            elif t == "photo":
                await bot.send_photo(ch, item["file_id"], caption=item.get("caption") or None, **thr)

            elif t == "video":
                await bot.send_video(ch, item["file_id"], caption=item.get("caption") or None, **thr)

            elif t == "video_note":
                await bot.send_video_note(ch, item["file_id"], **thr)

            elif t == "document":
                await bot.send_document(ch, item["file_id"], caption=item.get("file_name") or None, **thr)

        except Exception as e:
            logger.error(f"Failed to send item #{idx} ({item['type']}): {e}")
            await bot.send_message(ch, f"⚠️ Не удалось отправить элемент #{idx} ({item['type']})", **thr)

    await bot.send_message(
        ch,
        f"{'━' * 26}\n✅ *Конец отчёта*",
        parse_mode=ParseMode.MARKDOWN,
        **thr,
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.pop("report", None)
    ctx.user_data.pop("direction", None)
    await update.message.reply_text(
        "❌ Отчёт отменён.",
        reply_markup=_main_kb(),
    )
    return ConversationHandler.END


async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    await update.message.reply_text(
        f"👤 *Твой Telegram ID:* `{u.id}`\n\n"
        "Отправь этот номер администратору, чтобы получить доступ к боту.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception:", exc_info=ctx.error)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")
    if not CHANNEL_ID:
        raise RuntimeError("REPORT_CHANNEL_ID не задан в .env")

    data_dir = BASE_DIR / "data"
    data_dir.mkdir(exist_ok=True)

    persistence = PicklePersistence(filepath=data_dir / "persistence")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .concurrent_updates(True)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.Regex(r"^📋 Начать отчет$"), start_report),
        ],
        states={
            SELECTING_DIRECTION: [
                CallbackQueryHandler(cb_direction, pattern=r"^dir:"),
            ],
            TYPING_DIRECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, type_direction),
            ],
            SELECTING_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date),
            ],
            COLLECTING: [
                MessageHandler(filters.Regex(r"^✅ Закрыть отчет$"), close_report),
                MessageHandler(
                    (
                        filters.TEXT
                        | filters.VOICE
                        | filters.AUDIO
                        | filters.PHOTO
                        | filters.VIDEO
                        | filters.VIDEO_NOTE
                        | filters.Document.ALL
                    )
                    & ~filters.COMMAND,
                    collect_msg,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
        ],
        persistent=True,
        name="main_conv",
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_error_handler(error_handler)

    logger.info("GoTrips Tourlead Bot запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
