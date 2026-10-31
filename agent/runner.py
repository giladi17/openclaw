"""
מריץ סוכנים בלי Kubernetes (פריסה עם docker compose).

1. מאזין לתור agent_jobs ב-Redis (ה-Brain דוחף אליו כש-RUNNER=queue) ומריץ כל משימה
   כתהליך נפרד של agent.py — במקום Kubernetes Job.
2. מחליף את ה-CronJobs: סריקת בוקר 9:35 וסריקת ערב 15:45 שעון ניו יורק, שני-שישי.
"""
import os
import sys
import json
import time
import logging
import threading
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import redis
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
JOB_QUEUE      = "agent_jobs"
JOB_TIMEOUT    = 600   # כמו activeDeadlineSeconds של ה-Jobs ב-K8s
# משימה שחיכתה בתור יותר מזה (למשל ה-runner היה למטה) לא רצה — פקודת מסחר ישנה מסוכנת
MAX_JOB_AGE    = 300
MAX_PARALLEL   = 3

NY = ZoneInfo("America/New_York")
# (TASK, שעה, דקה, timeout) — אותן שעות כמו k8s/cronjob.yaml
SCHEDULE     = [("morning_scan", 9, 35, 900), ("evening_scan", 15, 45, 600)]
START_WINDOW = 600     # כמו startingDeadlineSeconds: אם פספסנו את הדקה המדויקת, עדיין מריצים עד 10 דקות אחרי

redis_client = redis.Redis(host="redis-service", port=6379, decode_responses=True)
slots        = threading.BoundedSemaphore(MAX_PARALLEL)


def notify(chat_id: str, text: str):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=15)
    except requests.RequestException as e:
        logger.error(f"שליחה לטלגרם נכשלה: {e}")


def run_agent(job_env: dict, timeout: int):
    """מריץ את agent.py פעם אחת — בלי ניסיון חוזר, כדי שפקודת מסחר לא תישלח פעמיים"""
    name = f"{job_env.get('ROLE')}/{job_env.get('TASK')}"
    logger.info(f"מריץ סוכן: {name}")
    try:
        result = subprocess.run([sys.executable, "agent.py"], env={**os.environ, **job_env}, timeout=timeout)
        logger.info(f"סוכן {name} הסתיים עם קוד {result.returncode}")
    except subprocess.TimeoutExpired:
        logger.error(f"סוכן {name} נעצר אחרי {timeout} שניות")
        notify(job_env.get("CHAT_ID", ""), f"⏱️ הסוכן {job_env.get('ROLE')} לא סיים בזמן ונעצר.")


def run_queued(job_env: dict):
    try:
        run_agent(job_env, JOB_TIMEOUT)
    finally:
        slots.release()


def queue_loop():
    while True:
        try:
            item = redis_client.blpop(JOB_QUEUE, timeout=30)
        except redis.ConnectionError as e:
            logger.warning(f"אין חיבור ל-Redis: {e}")
            time.sleep(5)
            continue
        if not item:
            continue

        job     = json.loads(item[1])
        job_env = job["env"]
        age     = time.time() - job.get("created", 0)
        if age > MAX_JOB_AGE:
            logger.warning(f"משימה ישנה ({int(age)} שניות) — לא מריץ: {job_env.get('ROLE')}")
            notify(job_env.get("CHAT_ID", ""), "⌛ המשימה חיכתה יותר מדי בתור ולא בוצעה. שלח אותה שוב.")
            continue

        slots.acquire()
        threading.Thread(target=run_queued, args=(job_env,), daemon=True).start()


def schedule_loop():
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").split(",")[0].strip()
    while True:
        now = datetime.now(NY)
        if now.weekday() < 5:
            for task, hour, minute, timeout in SCHEDULE:
                start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if not 0 <= (now - start).total_seconds() < START_WINDOW:
                    continue
                try:
                    # SET NX — גם אם ה-runner עולה מחדש בתוך החלון, הסריקה לא רצה פעמיים באותו יום
                    first = redis_client.set(f"sched:{task}:{now.date()}", 1, nx=True, ex=86400)
                except redis.ConnectionError as e:
                    logger.warning(f"אין חיבור ל-Redis, מדלג על בדיקת התזמון: {e}")
                    continue
                if first:
                    job_env = {"ROLE": "scanner", "TASK": task, "CHAT_ID": chat_id,
                               "JOB_ID": f"{task}-{now:%Y%m%d}"}
                    threading.Thread(target=run_agent, args=(job_env, timeout), daemon=True).start()
        time.sleep(20)


if __name__ == "__main__":
    threading.Thread(target=schedule_loop, daemon=True).start()
    logger.info("ה-runner עלה: מאזין לתור ומתזמן סריקות בוקר/ערב (שעון ניו יורק)")
    queue_loop()
