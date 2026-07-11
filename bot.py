import os
import logging
import base64
from collections import defaultdict, deque

from flask import Flask
import threading

from pyrogram import Client, filters
from pyrogram.types import Message

import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-6")

if not BOT_TOKEN or not API_ID or not API_HASH:
    raise ValueError("BOT_TOKEN, API_ID va API_HASH environment variable lar o'rnatilishi shart!")

if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY environment variable o'rnatilishi shart!")

client_ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
app = Client("ai_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

MAX_HISTORY = 10
conversations = defaultdict(lambda: deque(maxlen=MAX_HISTORY))

SYSTEM_PROMPT = (
    "Siz foydali, samimiy Telegram yordamchisisiz. "
    "Foydalanuvchi bilan asosan o'zbek tilida gaplashing, agar u boshqa tilda yozsa o'sha tilda javob bering. "
    "Javoblaringiz qisqa va aniq bo'lsin — Telegram xabar oynasiga mos keladigan uzunlikda."
)


def _trim_text(text: str, limit: int = 4000) -> str:
    if len(text) > limit:
        return text[:limit] + "\n\n... (davomi qisqartirildi)"
    return text


async def ask_claude(user_id: int, user_text: str, image_bytes: bytes | None = None, image_media_type: str | None = None) -> str:
    history = conversations[user_id]

    if image_bytes:
        b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type or "image/jpeg",
                    "data": b64_image,
                },
            },
            {"type": "text", "text": user_text or "Bu rasmda nima ko'rsatilgan?"},
        ]
    else:
        content = user_text

    messages = list(history) + [{"role": "user", "content": content}]

    try:
        response = client_ai.messages.create(
            model=MODEL_NAME,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        reply_text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        if not reply_text:
            reply_text = "Kechirasiz, javob shakllantira olmadim. Qaytadan urinib ko'ring."

        history.append({"role": "user", "content": user_text or "[rasm yuborildi]"})
        history.append({"role": "assistant", "content": reply_text})

        return reply_text

    except anthropic.APIStatusError as e:
        logger.error(f"❌ Anthropic API xatosi: {e}")
        return f"❌ AI xizmatidan xato qaytdi: `{str(e)[:150]}`"
    except Exception as e:
        logger.error(f"❌ Kutilmagan xato: {e}")
        return f"❌ Xatolik yuz berdi: `{str(e)[:150]}`"


@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply(
        "👋 Salom! Men sun'iy intellekt yordamchingizman (Claude asosida).\n\n"
        "💬 Menga istalgan savolni yozing — javob beraman.\n"
        "🖼 Rasm yuborib, uni tahlil qilishimni so'rashingiz ham mumkin.\n\n"
        "🧹 /clear — suhbat tarixini tozalash"
    )


@app.on_message(filters.command("clear"))
async def clear_cmd(client, message: Message):
    conversations[message.from_user.id].clear()
    await message.reply("🧹 Suhbat tarixi tozalandi.")


@app.on_message(filters.text & ~filters.command(["start", "clear"]))
async def text_handler(client, message: Message):
    thinking = await message.reply("💭 O'ylayapman...")
    reply = await ask_claude(message.from_user.id, message.text)
    await thinking.edit_text(_trim_text(reply))


@app.on_message(filters.photo)
async def photo_handler(client, message: Message):
    thinking = await message.reply("🖼 Rasm tahlil qilinmoqda...")

    photo_bytes = await client.download_media(message.photo.file_id, in_memory=True)
    image_data = photo_bytes.getvalue()

    caption = message.caption or ""
    reply = await ask_claude(
        message.from_user.id,
        caption,
        image_bytes=image_data,
        image_media_type="image/jpeg",
    )
    await thinking.edit_text(_trim_text(reply))


flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "AI Bot ishlayapti ✅"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("🚀 Bot ishga tushmoqda...")
    app.run()
