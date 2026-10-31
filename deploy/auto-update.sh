#!/bin/bash
# מושך גרסה חדשה מ-main ומעדכן את הבוט. רץ כל 5 דקות מ-cron בשרת:
#   */5 * * * * ubuntu /home/ubuntu/openclaw/deploy/auto-update.sh >> /home/ubuntu/auto-update.log 2>&1
# השרת מושך בעצמו — כך לא צריך לפתוח SSH ל-GitHub או לשמור מפתח של השרת ב-GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0

# לא לעדכן באמצע משימה (למשל סריקה שקונה מניות) — ה-runner יופעל מחדש וזה יקטע אותה.
# [.] כדי ש-grep לא ימצא את עצמו
if docker compose exec -T runner sh -c 'grep -lsa "agent[.]py" /proc/[0-9]*/cmdline' >/dev/null 2>&1; then
  echo "$(date -Is) agent is running, will retry next time"
  exit 0
fi

git merge -q --ff-only origin/main
docker compose up -d --build --remove-orphans
echo "$(date -Is) updated to $(git rev-parse --short HEAD)"
