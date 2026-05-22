import logging
import httpx

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


async def transcribe(audio_bytes: bytes, api_key: str) -> str:
    if not api_key:
        return "[ключ Deepgram не настроен — расшифровка недоступна]"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                DEEPGRAM_URL,
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "audio/ogg",
                },
                params={
                    "model": "nova-2",
                    "language": "ru",
                    "smart_format": "true",
                    "punctuate": "true",
                },
                content=audio_bytes,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
            return text.strip() or "[пустое голосовое сообщение]"
    except httpx.HTTPStatusError as e:
        logger.error(f"Deepgram HTTP {e.response.status_code}: {e.response.text[:300]}")
        return "[ошибка транскрипции — HTTP]"
    except Exception as e:
        logger.error(f"Deepgram error: {e}")
        return "[ошибка транскрипции]"
