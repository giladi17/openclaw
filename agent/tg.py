"""שליחה לטלגרם שלא נופלת בגלל Markdown שבור — למשל בטקסט שהמודל כתב, או סימבול עם קו תחתון"""
import re
import logging

from telegram.error import BadRequest

logger = logging.getLogger(__name__)


def llm_to_markdown(text: str) -> str:
    """ממיר Markdown של המודל (**מודגש**, ### כותרת, * תבליט) לפורמט הפשוט שטלגרם מבין"""
    lines = []
    for line in text.splitlines():
        header = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if header:
            line = f"*{header.group(1).replace('*', '')}*"
        else:
            line = re.sub(r"^(\s*)[*-]\s+", r"\1• ", line)
            line = line.replace("**", "*")
        lines.append(line)
    return "\n".join(lines)


async def send(bot, *, chat_id, text, **kwargs):
    """שולח עם Markdown; אם טלגרם לא מצליח לפענח — שולח שוב כטקסט רגיל במקום ליפול בשקט"""
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", **kwargs)
    except BadRequest as e:
        if "parse entities" not in str(e).lower():
            raise
        logger.warning(f"Markdown לא תקין, שולח כטקסט רגיל: {e}")
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
