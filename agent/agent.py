import os
import logging
import asyncio
import json
from groq import Groq
from telegram import Bot
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")
TASK           = os.environ.get("TASK")
ROLE           = os.environ.get("ROLE")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")

ROLE_PROMPTS = {
    "researcher": "אתה סוכן מחקר מומחה. תחקור את הנושא ותחזיר תשובה מפורטת ומדויקת.",
    "coder":      "אתה סוכן פיתוח מומחה. תכתוב קוד נקי ומוסבר לפי הבקשה.",
    "summarizer": "אתה סוכן סיכום מומחה. תסכם את הטקסט בצורה קצרה וברורה."
}

async def run():
    logger.info(f"סוכן {ROLE} התעורר למשימה: {TASK}")

    if ROLE == "analyst":
        from analyst import run as analyst_run
        await analyst_run()
        return

    if ROLE == "trader":
        from trader import run as trader_run
        await trader_run()
        return

    if ROLE == "scanner":
        from scanner import run as scanner_run
        await scanner_run()
        return

    # סוכנים רגילים
    redis_client = redis.Redis(host="redis-service", port=6379, decode_responses=True)
    history      = redis_client.get(f"chat:{CHAT_ID}")
    messages     = json.loads(history) if history else []

    groq_client  = Groq(api_key=GROQ_API_KEY)
    conversation = [{"role": "system", "content": ROLE_PROMPTS.get(ROLE, ROLE_PROMPTS["researcher"])}]
    conversation.extend(messages)
    conversation.append({"role": "user", "content": TASK})

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=conversation
    )
    result = response.choices[0].message.content

    existing          = redis_client.get(f"chat:{CHAT_ID}")
    existing_messages = json.loads(existing) if existing else []
    existing_messages.append({"role": "assistant", "content": result})
    existing_messages = existing_messages[-10:]
    redis_client.setex(f"chat:{CHAT_ID}", 3600, json.dumps(existing_messages))

    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(
        chat_id=CHAT_ID,
        text=f"סוכן {ROLE} השלים את המשימה:\n\n{result}"
    )

if __name__ == "__main__":
    asyncio.run(run())

  