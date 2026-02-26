import os
import logging
import json
import uuid
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from kubernetes import client, config
import redis
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config.load_incluster_config()
k8s = client.BatchV1Api()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY")

redis_client = redis.Redis(host="redis-service", port=6379, decode_responses=True)
groq_client  = Groq(api_key=GROQ_API_KEY)


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
- אם המשתמש מבקש לסכם, לקצר - ענה: summarizer
- אם המשתמש מבקש קוד, תכנות - ענה: coder
- בכל מקרה אחר - ענה: researcher"""
            },
            {"role": "user", "content": message}
        ],
        max_tokens=10
    )
    agent = response.choices[0].message.content.strip().lower()
    valid = ["coder", "researcher", "summarizer", "analyst", "trader"]
    if agent not in valid:
        agent = "researcher"
    return agent


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


def create_agent_job(task: str, agent_type: str, chat_id: int):
    job_id = uuid.uuid4().hex[:5]
    save_job_status(job_id, chat_id, agent_type, "running")

    job = client.V1Job(
        metadata=client.V1ObjectMeta(
            name=f"agent-{chat_id}-{agent_type}-{job_id}",
            labels={"app": "openclaw-agent"}
        ),
        spec=client.V1JobSpec(
            ttl_seconds_after_finished=60,
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    image_pull_secrets=[client.V1LocalObjectReference(name="dockerhub-secret")],
                    containers=[
                        client.V1Container(
                            name="agent",
                            image="giladi17/openclaw-agent:latest",
                            resources=client.V1ResourceRequirements(
                                requests={"memory": "256Mi", "cpu": "250m"},
                                limits={"memory": "512Mi", "cpu": "500m"}
                            ),
                            env=[
                                client.V1EnvVar(name="ROLE",    value=agent_type),
                                client.V1EnvVar(name="TASK",    value=task),
                                client.V1EnvVar(name="CHAT_ID", value=str(chat_id)),
                                client.V1EnvVar(name="JOB_ID",  value=job_id),
                                client.V1EnvVar(name="TELEGRAM_TOKEN",  value_from=client.V1EnvVarSource(secret_key_ref=client.V1SecretKeySelector(name="openclaw-secrets", key="TELEGRAM_TOKEN"))),
                                client.V1EnvVar(name="GROQ_API_KEY",    value_from=client.V1EnvVarSource(secret_key_ref=client.V1SecretKeySelector(name="openclaw-secrets", key="GROQ_API_KEY"))),
                                client.V1EnvVar(name="ALPACA_API_KEY",  value_from=client.V1EnvVarSource(secret_key_ref=client.V1SecretKeySelector(name="openclaw-secrets", key="ALPACA_API_KEY"))),
                                client.V1EnvVar(name="ALPACA_SECRET_KEY", value_from=client.V1EnvVarSource(secret_key_ref=client.V1SecretKeySelector(name="openclaw-secrets", key="ALPACA_SECRET_KEY"))),
                                client.V1EnvVar(name="ALPACA_BASE_URL", value_from=client.V1EnvVarSource(secret_key_ref=client.V1SecretKeySelector(name="openclaw-secrets", key="ALPACA_BASE_URL"))),
                            ]
                        )
                    ]
                )
            )
        )
    )
    k8s.create_namespaced_job(namespace="default", body=job)
    logger.info(f"פוד חדש נפתח: {agent_type} למשימה: {task}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    chat_id = update.message.chat_id
    save_context(chat_id, "user", message)
    agent_type = decide_agent(message)
    await update.message.reply_text(f"⚙️ מעביר למומחה {agent_type}... אני עובד על זה, תכף חוזר!")
    create_agent_job(message, agent_type, chat_id)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    logger.info("המוח המרכזי עלה ומאזין...")
    app.run_polling()


if __name__ == "__main__":
    main()
