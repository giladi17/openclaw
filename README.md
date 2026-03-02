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
| 📊 **Analyst** | מנתח מניה (RSI, MACD, MA) | "נתח את AAPL" |
| 💰 **Trader** | קנייה/מכירה דרך Alpaca | "קנה 5 מניות TSLA" |
| 🔍 **Scanner** | סורק 20 מניות וקונה Top 3 | CronJob 9:30 EST |
| 📈 **Backtest** | בודק אסטרטגיה על נתונים היסטוריים | "הרץ backtest" |
| 🎯 **LDM Backtest** | בודק שיטת Dual Momentum | "הרץ LDM backtest" |
| 🔬 **Researcher** | מחקר כללי | כל שאלה |
| 💻 **Coder** | כתיבת קוד | "כתוב קוד..." |
| 📝 **Summarizer** | סיכום טקסטים | "סכם את..." |

---

## ⏰ אוטומציה יומית

```
09:30 EST — סריקת בוקר
  ├── בודק SPY מול MA20 (פילטר שוק)
  ├── סורק 20 מניות לפי RSI + MACD + נפח
  ├── קונה Top 3 אוטומטית
  └── שולח דוח לטלגרם

15:45 EST — סריקת ערב
  ├── בודק כל פוזיציה
  ├── מוכר אם רווח > 15% או הפסד > 10%
  └── שולח דוח ערב
```

---

## 📊 אסטרטגיית המסחר

### Swing Trading (אוטומטי)
- **פילטר שוק:** SPY מעל MA20 → קונה, מתחת → לא קונה
- **כניסה:** RSI 35-50 + MA7 > MA20 + MACD חיובי + נפח גבוה
- **יציאה:** רווח > 15% או הפסד > 10%
- **החזקה:** 2-10 ימים

### LDM — Leveraged Dual Momentum
- **בדיקה חודשית:** QQQ מול SMA200
- **מעל SMA200:** קנה QLD (נאסד"ק x2)
- **מתחת SMA200:** קנה BIL (אג"ח בטוח)

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
│   ├── ldm_backtest.py     # LDM Dual Momentum backtest
│   ├── Dockerfile
│   └── requirements.txt
│
├── k8s/                    # ☸️ Kubernetes manifests
│   ├── brain.yaml          # Brain deployment
│   ├── redis.yaml          # Redis deployment
│   ├── rbac.yaml           # ServiceAccount + permissions
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
קנה 5 מניות TSLA          → קנייה אוטומטית
מכור 3 מניות AAPL         → מכירה אוטומטית
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
| LDM x2 | 3 שנים | בבדיקה |

---

## 🔒 אבטחה

- אפס מפתחות בקוד — הכל ב-AWS Secrets Manager
- RBAC מוגדר ב-Kubernetes
- Network Policies מגבילות תעבורה
- Docker images נבנים אוטומטית ב-GitHub Actions

---

## 👨‍💻 פותח על ידי

**Gilad** — Built from scratch on AWS + Kubernetes

*OpenClaw — Where AI meets the Stock Market* 🦾📈