# 🦾 OpenClaw — AI Trading Agent System

> מערכת סוכני AI אוטומטית לניהול תיק מסחר בשוק ההון, רצה על Kubernetes ב-AWS

---

## 🎯 מה זה OpenClaw?

OpenClaw היא מערכת Multi-Agent אוטומטית שמנהלת תיק מסחר בשוק ההון ללא התערבות אנושית.  
המערכת מקבלת פקודות דרך Telegram, מנתחת מניות, מבצעת עסקאות, ושולחת דוחות — הכל אוטומטי.

---

## 🏗️ ארכיטקטורה

```
User (Telegram)
        ↓
🧠 Brain (תמיד רץ על AWS)
   ├── מאזין להודעות Telegram
   ├── מחליט איזה סוכן לפי Groq AI
   └── יוצר Kubernetes Job
        ↓
☸️ Kubernetes (מפעיל Job אוטומטי)
        ↓
🤖 Agent (מתעורר, עובד, נמחק)
   ├── מתחבר ל-Alpaca API
   ├── מנתח / סוחר / סורק
   └── שולח תשובה ל-Telegram
        ↓
📱 Telegram (המשתמש מקבל תשובה)
```

---

## 🤖 הסוכנים

| סוכן | תפקיד | טריגר |
|------|--------|--------|
| 🧠 **Brain** | מאזין ומנתב הודעות | תמיד פעיל |
| 📊 **Analyst** | מנתח מניה (RSI, MA7, MA20) | "נתח את AAPL" |
| 💰 **Trader** | קנייה/מכירה דרך Alpaca — עם כפתור אישור | "קנה 5 מניות TSLA" |
| 🔍 **Scanner** | סורק 20 מניות וקונה עד 3 חדשות | CronJob 9:35 שעון ניו יורק |
| 📈 **Backtest** | בודק אסטרטגיה על נתונים היסטוריים | "הרץ backtest" |
| 🎯 **LDM Backtest** | בודק שיטת Dual Momentum | "הרץ LDM backtest" |
| 🔬 **Researcher** | מחקר כללי | כל שאלה |
| 💻 **Coder** | כתיבת קוד | "כתוב קוד..." |
| 📝 **Summarizer** | סיכום טקסטים | "סכם את..." |

---

## ⏰ אוטומציה יומית

```
09:35 שעון ניו יורק — סריקת בוקר
  ├── בודק SPY מול MA20 (פילטר שוק; אין נתונים → לא קונה)
  ├── סורק 20 מניות לפי RSI + MA7/MA20 + נפח + מומנטום
  ├── קונה עד 3 מניות חדשות (מדלג על מה שכבר בתיק, מקסימום 5 פוזיציות)
  └── שולח דוח לטלגרם

15:45 שעון ניו יורק — סריקת ערב
  ├── בודק כל פוזיציה
  ├── מוכר אם רווח > 15% או הפסד > 10%
  ├── מוכר פוזיציות שהסורק פתח אחרי 10 ימים
  └── שולח דוח ערב

(ה-CronJobs משתמשים ב-timeZone: America/New_York — מתעדכן לבד בשעון קיץ/חורף)
```

---

## 📊 אסטרטגיית המסחר

### Swing Trading (אוטומטי)
- **פילטר שוק:** SPY מעל MA20 → קונה, מתחת → לא קונה
- **כניסה:** ציון ≥ 50 מתוך: RSI 30-50, MA7 > MA20, נפח פי 1.5 מהממוצע, עלייה יומית של 0-3%
- **יציאה:** רווח > 15%, הפסד > 10%, או 10 ימים בתיק
- **גודל:** עד 5 פוזיציות במקביל, בלי קנייה כפולה של אותה מניה

### LDM — Leveraged Dual Momentum
- **בדיקה חודשית:** QQQ מול SMA200
- **מעל SMA200:** קנה QLD (נאסד"ק x2)
- **מתחת SMA200:** קנה BIL (אג"ח בטוח)
- ה-backtest משווה מול קנה-והחזק של QQQ ו-QLD, עם עלות משוערת לכל החלפה

---

## 🛠️ טכנולוגיות

| תחום | טכנולוגיה |
|------|-----------|
| ☁️ ענן | AWS EC2, IAM, Secrets Manager |
| 🏗️ תשתית | Terraform (IaC) |
| ☸️ Orchestration | Kubernetes (K8s Jobs + CronJobs) |
| 🐳 Containers | Docker, DockerHub |
| 🔄 CI/CD | GitHub Actions |
| 🐍 Backend | Python 3.11, asyncio |
| 🤖 AI | Groq API (llama-3.3-70b-versatile) |
| 📈 מסחר | Alpaca Markets API |
| 💬 Messaging | Telegram Bot API |
| 🗃️ Cache | Redis |

---

## 📁 מבנה הפרויקט

```
openclaw/
├── brain/                  # 🧠 המוח המרכזי
│   ├── main.py             # Telegram listener + agent router
│   ├── Dockerfile
│   └── requirements.txt
│
├── agent/                  # 🤖 סוכני המסחר
│   ├── agent.py            # dispatcher לכל הסוכנים
│   ├── analyst.py          # ניתוח מניות
│   ├── trader.py           # ביצוע עסקאות
│   ├── scanner.py          # סריקת בוקר/ערב
│   ├── backtest.py         # בדיקת אסטרטגיה היסטורית
│   ├── ldm_backtest.py     # LDM Dual Momentum backtest (3 שנים מול QQQ/QLD)
│   ├── Dockerfile
│   └── requirements.txt
│
├── k8s/                    # ☸️ Kubernetes manifests
│   ├── brain.yaml          # Brain deployment
│   ├── redis.yaml          # Redis deployment
│   ├── rbac.yaml           # brain-sa (יוצר Jobs) + agent-sa (בלי הרשאות)
│   ├── cronjob.yaml        # Morning + Evening CronJobs
│   ├── network-policy.yaml
│   └── quota.yaml
│
└── terraform/              # 🏗️ AWS Infrastructure
    ├── main.tf
    ├── variables.tf
    └── terraform.tfvars
```

---

## 🚀 פריסה

### דרישות
- AWS Account
- DockerHub Account
- Alpaca Account (Paper Trading)
- Telegram Bot Token
- Groq API Key

### מפתחות ב-AWS Secrets Manager
הסוד `openclaw/secrets` (JSON) חייב להכיל:
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `GROQ_API_KEY`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`,
`ALPACA_BASE_URL` (אופציונלי — ברירת מחדל Paper), `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

`TELEGRAM_CHAT_ID` הוא גם רשימת המורשים — הבוט מתעלם מכל צ'אט אחר.
אפשר כמה מזהים מופרדים בפסיק.

### התקנה
```bash
# 1. Clone
git clone https://github.com/giladi17/openclaw.git

# 2. הרמת תשתית AWS
cd terraform
terraform init && terraform apply

# 3. פריסת K8s manifests
kubectl apply -f k8s/

# 4. GitHub Actions יבנה ויפרוס אוטומטית
git push origin main
```

---

## 💬 פקודות Telegram

```
נתח את מניית AAPL        → ניתוח טכני מלא
קנה 5 מניות TSLA          → קנייה (אחרי לחיצה על ✅ אשר)
מכור 3 מניות AAPL         → מכירה (אחרי לחיצה על ✅ אשר)
מה הפוזיציות שלי?         → מצב התיק
הרץ backtest              → backtest 6 חודשים
הרץ LDM backtest          → LDM vs QQQ benchmark
```

---

## 💰 עלות חודשית

| שירות | עלות |
|-------|------|
| EC2 Master (t3.small) | ~$15 |
| EC2 Worker (t3.micro) | ~$8 |
| Secrets Manager | ~$0.40 |
| רשת | ~$0.60 |
| **סה"כ** | **~$24/חודש** |

> Groq, Telegram, Alpaca Paper Trading — **חינם לחלוטין**

---

## 📈 תוצאות Backtest

| אסטרטגיה | תקופה | תשואה |
|----------|-------|--------|
| Swing Trading | 18 חודשים | +24.4% |
| LDM x2 | 3 שנים | `הרץ LDM backtest` בטלגרם |

> ⚠️ ה-backtest קונה במחיר הסגירה של יום הסיגנל, לא כולל slippage, ורשימת המניות נבחרה בדיעבד —
> התוצאות בפועל צפויות להיות נמוכות יותר. ביצועי עבר אינם מבטיחים תשואה עתידית.

---

## 🔒 אבטחה

- אפס מפתחות בקוד — הכל ב-AWS Secrets Manager
- הבוט מקבל פקודות רק מ-Chat ID מורשה
- כל עסקה ידנית דורשת אישור בכפתור, עם תקרת כמות (`MAX_ORDER_QTY`)
- RBAC מינימלי: ה-Brain יכול רק ליצור Jobs ב-namespace שלו; לסוכנים אין גישה ל-API
- Jobs רצים עם `backoffLimit: 0` — פקודת מסחר לא נשלחת פעמיים בגלל retry
- Kubernetes API פתוח רק מתוך ה-VPC (ומכתובות ב-`k8s_api_allowed_cidrs`)
- Network Policies מוכנות — נאכפות רק עם CNI תומך (Calico/Canal; Flannel לא אוכף)
- Docker images מתויגים לפי commit SHA — אפשר לדעת מה רץ ולחזור אחורה

---

## 👨‍💻 פותח על ידי

**Gilad** — Built from scratch on AWS + Kubernetes

*OpenClaw — Where AI meets the Stock Market* 🦾📈