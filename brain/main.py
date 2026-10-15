import os
import re
import time
import asyncio
import logging
import json
import uuid
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from kubernetes import client, config
import redis
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config.load_incluster_config()
k8s = client.BatchV1Api()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")
NAMESPACE      = os.environ.get("NAMESPACE", "default")
# ה-CI מעדכן את זה לתגית של ה-commit, כך שה-Jobs רצים בדיוק על אותה גרסה של הקוד
AGENT_IMAGE    = os.environ.get("AGENT_IMAGE", "giladi17/openclaw-agent:latest")

HEARTBEAT_FILE = Path("/tmp/heartbeat")

redis_client = redis.Redis(host="redis-service", port=6379, decode_responses=True)
groq_client  = Groq(api_key=GROQ_API_KEY)

# רק צ'אטים ברשימה הזו יכולים לתת פקודות לבוט (מופרדים בפסיק).
# אם הרשימה ריקה — הבוט חוסם את כולם (fail-closed), כדי שאף אחד זר לא יוכל לסחור בחשבון.
ALLOWED_CHAT_IDS = {
    int(x) for x in os.environ.get("ALLOWED_CHAT_IDS", "").replace(" ", "").split(",") if x
}
if not ALLOWED_CHAT_IDS:
    logger.warning("ALLOWED_CHAT_IDS ריק — כל ההודעות ייחסמו!")

VALID_AGENTS = ["coder", "researcher", "summarizer", "analyst", "trader", "backtest", "ldm_backtest"]


def decide_agent(message: str) -> str:
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """אתה נתב שמחליט איזה סוכן מתאים למשימה. ענה רק במילה אחת בלי שום תוספת.

הכללים:
- אם המשתמש מבקש לנתח מניה, לבדוק מחיר, RSI, סיגנל קנייה/מכירה - ענה: analyst
- אם המשתמש מבקש לקנות מניה - ענה: trader
- אם המשתמש מבקש למכור מניה - ענה: trader
- אם המשתמש שואל על הפוזיציות שלו, התיק שלו - ענה: trader
- אם המשתמש מבקש LDM backtest, Dual Momentum, QLD - ענה: ldm_backtest
- אם המשתמש מבקש backtest, לבדוק את האסטרטגיה, לבדוק ביצועים היסטוריים - ענה: backtest
- אם המשתמש מבקש לסכם, לקצר - ענה: summarizer
- אם המשתמש מבקש קוד, תכנות - ענה: coder
- בכל מקרה אחר - ענה: researcher"""
            },
            {"role": "user", "content": message}
        ],
        max_tokens=10,
        temperature=0
    )
    agent = response.choices[0].message.content.strip().lower()
    return agent if agent in VALID_AGENTS else "researcher"


def save_context(chat_id: int, role: str, message: str):
    key = f"chat:{chat_id}"
    history  = redis_client.get(key)
    messages = json.loads(history) if history else []
    messages.append({"role": role, "content": message})
    messages = messages[-10:]
    redis_client.setex(key, 3600, json.dumps(messages))


def save_job_status(job_id: str, chat_id: int, agent_type: str, status: str):
    key  = f"job:{job_id}"
    data = {"chat_id": chat_id, "agent_type": agent_type, "status": status}
    redis_client.setex(key, 3600, json.dumps(data))


def secret_env(name: str) -> client.V1EnvVar:
    return client.V1EnvVar(
        name=name,
        value_from=client.V1EnvVarSource(
            secret_key_ref=client.V1SecretKeySelector(name="openclaw-secrets", key=name)
        )
    )


def create_agent_job(task: str, agent_type: str, chat_id: int, extra_env: dict | None = None):
    job_id = uuid.uuid4().hex[:5]
    save_job_status(job_id, chat_id, agent_type, "running")

    env = [
        client.V1EnvVar(name="ROLE",    value=agent_type),
        client.V1EnvVar(name="TASK",    value=task),
        client.V1EnvVar(name="CHAT_ID", value=str(chat_id)),
        client.V1EnvVar(name="JOB_ID",  value=job_id),
        secret_env("TELEGRAM_TOKEN"),
        secret_env("GROQ_API_KEY"),
        secret_env("ALPACA_API_KEY"),
        secret_env("ALPACA_SECRET_KEY"),
        secret_env("ALPACA_BASE_URL"),
    ]
    for k, v in (extra_env or {}).items():
        env.append(client.V1EnvVar(name=k, value=str(v)))

    # שם חוקי ב-K8s: אותיות קטנות, ספרות ומקפים, עד 63 תווים (chat_id של קבוצה יכול להיות שלילי)
    safe_chat = str(abs(chat_id))
    name      = re.sub(r"[^a-z0-9-]", "-", f"agent-{safe_chat}-{agent_type}-{job_id}")[:63].rstrip("-")

    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=name, labels={"app": "openclaw-agent"}),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=60,
            # חשוב: בלי זה K8s מנסה שוב עד 6 פעמים כשפוד נכשל — וזה יכול לשלוח את אותה פקודת מסחר כמה פעמים
            backoff_limit=0,
            active_deadline_seconds=600,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "openclaw-agent"}),
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    # לסוכנים אין צורך בגישה ל-API של Kubernetes
                    service_account_name="agent-sa",
                    automount_service_account_token=False,
                    image_pull_secrets=[client.V1LocalObjectReference(name="dockerhub-secret")],
                    containers=[
                        client.V1Container(
                            name="agent",
                            image=AGENT_IMAGE,
                            resources=client.V1ResourceRequirements(
                                requests={"memory": "256Mi", "cpu": "250m"},
                                limits={"memory": "512Mi", "cpu": "500m"}
                            ),
                            env=env
                        )
                    ]
                )
            )
        )
    )
    k8s.create_namespaced_job(namespace=NAMESPACE, body=job)
    logger.info(f"פוד חדש נפתח: {agent_type} למשימה: {task}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    message = update.message.text
    chat_id = update.message.chat_id

    if chat_id not in ALLOWED_CHAT_IDS:
        logger.warning(f"הודעה נחסמה מצ'אט לא מורשה: {chat_id}")
        await update.message.reply_text("⛔ אין לך הרשאה להשתמש בבוט הזה.")
        return

    save_context(chat_id, "user", message)
    agent_type = await asyncio.to_thread(decide_agent, message)
    await update.message.reply_text(f"⚙️ מעביר למומחה {agent_type}... אני עובד על זה, תכף חוזר!")
    await asyncio.to_thread(create_agent_job, message, agent_type, chat_id)


async def handle_order_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """לחיצה על ✅ אשר / ❌ בטל בהודעת אישור של ה-Trader"""
    query   = update.callback_query
    chat_id = query.message.chat_id if query.message else None

    if chat_id not in ALLOWED_CHAT_IDS:
        await query.answer("⛔ אין הרשאה", show_alert=True)
        return

    action, _, order_id = (query.data or "").partition(":")
    if not re.fullmatch(r"[0-9a-f]{10}", order_id):
        await query.answer("פקודה לא תקינה")
        return

    if action == "cancel":
        redis_client.delete(f"pending_order:{order_id}")
        await query.answer("בוטל")
        await query.edit_message_text("❌ הפקודה בוטלה. לא בוצע דבר.")
        return

    if action == "confirm":
        if not redis_client.exists(f"pending_order:{order_id}"):
            await query.answer("הפקודה פגה", show_alert=True)
            await query.edit_message_text("⌛ הפקודה פגה (עברו יותר מ-5 דקות). שלח אותה שוב.")
            return
        await query.answer("מבצע...")
        # מסירים את הכפתורים כדי שלא ילחצו פעמיים
        await query.edit_message_reply_markup(reply_markup=None)
        await asyncio.to_thread(
            create_agent_job, "confirmed_order", "trader", chat_id,
            {"CONFIRMED_ORDER_ID": order_id}
        )


async def heartbeat_loop():
    """מעדכן קובץ כל 30 שניות. ה-livenessProbe בודק שהוא טרי — אם הלולאה נתקעה, K8s יפעיל מחדש."""
    while True:
        HEARTBEAT_FILE.write_text(str(time.time()))
        await asyncio.sleep(30)


async def post_init(app: Application):
    app.create_task(heartbeat_loop())


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_order_button, pattern=r"^(confirm|cancel):"))
    logger.info("המוח המרכזי עלה ומאזין...")
    app.run_polling()


if __name__ == "__main__":
    main()
