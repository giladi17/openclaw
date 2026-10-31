region    = "eu-north-1"
vpc_id    = "vpc-036a4c9e20ce02383"
subnet_id = "subnet-093acb39abe21a235"
key_name  = "Gilad-agent"
# התראת התקציב נוצרה ידנית בקונסולה, והמפתחות לא שמורים ב-Secrets Manager —
# לכן budget_email ו-instance_profile נשארים ריקים, ואת .env ממלאים בשרת
