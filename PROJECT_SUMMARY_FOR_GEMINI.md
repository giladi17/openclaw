# 🦾 OpenClaw - AI Agent System on Kubernetes
## פרויקט שלי - בקשת סיוע בבנייה

---

## 📋 מהו הפרויקט?

**OpenClaw** היא מערכת AI אגנטית מלאה שרצה על **Kubernetes** ב-**AWS** עם פריסה אוטומטית מקצה לקצה.

### 🎯 מטרה:
משתמש שולח הודעה דרך **Telegram**, המערכת מחליטה איזה סוכן מתאים (Researcher, Coder, או Summarizer), מריצה אותו, ומחזירה תשובה.

---

## 🏗️ ארכיטקטורה המערכת

```
User (Telegram) 
    ↓
Master Node (AWS EC2):
  - Brain Pod: מקבל הודעה, מחליט אילו סוכן, יוצר Job
  - Redis Pod: שומר היסטוריית שיחה וסטטוס Jobs
    ↓
Worker Node (AWS EC2):
  - Researcher Agent Job: עורך מחקר
  - Coder Agent Job: כותב קוד
  - Summarizer Agent Job: מסכם טקסטים
    ↓
תשובה חוזרת ל-Telegram
```

---

## 📁 מבנה הפרויקט

```
gilad-agent/
├── brain/           # 🧠 מודול ה"מוח" (משלח הודעות)
│   ├── main.py      # מקשיב ל-Telegram, מחליט סוכן
│   ├── Dockerfile   # image עבור Brain
│   └── requirements.txt
│
├── agent/           # 🤖 מודול הסוכנים (עורכים עבודה)
│   ├── agent.py     # קוד הסוכנים (Researcher, Coder, Summarizer)
│   ├── Dockerfile   # image עבור Agent
│   └── requirements.txt
│
├── k8s/             # ☸️ Kubernetes manifests
│   ├── brain-deployment.yaml
│   ├── redis-deployment.yaml
│   └── configmaps/secrets
│
├── terraform/       # 🏗️ Infrastructure as Code
│   ├── main.tf      # הגדרת AWS resources
│   └── variables.tf
│
└── README.md        # תיעוד
```

---

## 🧠 Brain Module (`brain/main.py`)

### המטלות:
1. **קבלת הודעה** מ-Telegram
2. **שליחת שאלה ל-Groq AI**: "איזה סוכן מתאים?" 
3. **שמירת קונטקסט** ב-Redis
4. **יצירת Job** ב-Kubernetes עם הסוכן הנבחר

### Key Functions:
- `decide_agent()`: משתמשת ב-Groq כדי להחליט אילו סוכן
- `save_context()`: שומרת היסטוריה ב-Redis
- `create_agent_job()`: יוצרת Job ב-Kubernetes

### Dependencies:
- `python-telegram-bot==20.7`
- `kubernetes==28.1.0`
- `redis==5.0.1`
- `groq==0.9.0`

---

## 🤖 Agent Module (`agent/agent.py`)

### שלושה סוגי סוכנים:
1. **Researcher**: עורך מחקר מפורט
2. **Coder**: כותב קוד נקי ומוסבר
3. **Summarizer**: מסכם בקצרה

### זרימה:
1. מקבל משתנים סביבה: `TASK`, `ROLE`, `CHAT_ID`
2. מקבל היסטוריה מ-Redis
3. שולח הודעה ל-Groq AI עם ה-prompt המתאים
4. שומר תשובה ב-Redis (10 הודעות אחרונות)
5. שולח תשובה ל-Telegram

### Dependencies:
- `groq==0.9.0`
- `python-telegram-bot==20.7`
- `redis==5.0.1`

---

## 🔄 Message Flow

```
1. User → Telegram: "כתוב לי פונקציה בPython"
           ↓
2. Brain → Groq: "איזה סוכן?"
           ↓
3. Groq ← Brain: "coder"
           ↓
4. Brain → Kubernetes: יצור Job עם role="coder"
           ↓
5. Agent runs on Worker
           ↓
6. Agent → Groq: "כתוב קוד לפי הבקשה"
           ↓
7. Groq ← Agent: קוד מלא
           ↓
8. Agent → Telegram: שלח תשובה
           ↓
9. Job delete (TTL: 60s)
```

---

## 📦 Dependencies Summary

### Brain:
```
python-telegram-bot==20.7
kubernetes==28.1.0
redis==5.0.1
groq==0.9.0
```

### Agent:
```
python-telegram-bot==20.7
groq==0.9.0
redis==5.0.1
```

---

## 🔑 Environment Variables Needed

### Brain Pod:
- `TELEGRAM_TOKEN`: TOKEN של Bot ב-Telegram
- `GROQ_API_KEY`: API Key של Groq
- `REDIS_HOST`: redis-service (K8s service)
- `REDIS_PORT`: 6379

### Agent Pod (כל Job):
- `TELEGRAM_TOKEN`: טוקן ל-Telegram
- `CHAT_ID`: ID של ה-chat אליו לשלוח תשובה
- `TASK`: המשימה שצריך לבצע
- `ROLE`: סוג הסוכן (researcher/coder/summarizer)
- `GROQ_API_KEY`: API Key של Groq

---

## 🚀 Deployment Layers

### 1. Docker
- Brain image
- Agent image

### 2. Kubernetes
- Brain Deployment (תמיד רץ)
- Redis StatefulSet
- Agent Job templates (יוצרים בעת הצורך)

### 3. Infrastructure (Terraform)
- AWS VPC
- EC2 Master Node (בעל Kubernetes control plane)
- EC2 Worker Node (בעל Kubernetes workers)
- Security Groups
- IAM Roles

---

## ❓ שאלות שיש לי (בקשת עצות):

1. **איך שיפרתי את זה?** - מה המצטמצם מבחינת performance/cost?
2. **Error Handling** - מה קורה אם Agent נכשל?
3. **Scaling** - איך להוסיף עוד Worker Nodes?
4. **Monitoring** - איך לעקוב אחרי ריצות?
5. **גרסאות חדשות של ספריות** - אילו עדכונים בטוחים?

---

הערה: זה Clone מ-https://github.com/doronsun/openclaw
