variable "region" {
  description = "AWS Region"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID"
  type        = string
}

variable "public_key_path" {
  description = "המפתח הציבורי ל-SSH שיותקן בשרת"
  type        = string
  default     = "~/.ssh/openclaw.pub"
}

variable "instance_type" {
  description = "t4g.small (2GB) מספיק בנוחות; t4g.micro (1GB) זול יותר אבל צפוף"
  type        = string
  default     = "t4g.small"
}

variable "instance_profile" {
  description = "IAM instance profile עם הרשאת קריאה לסוד ב-Secrets Manager. ריק = בלי, ואז ממלאים .env ידנית"
  type        = string
  default     = ""
}

variable "repo_url" {
  description = "מאיפה השרת מושך את הקוד"
  type        = string
  default     = "https://github.com/giladi17/openclaw.git"
}

variable "secrets_id" {
  description = "שם הסוד ב-AWS Secrets Manager"
  type        = string
  default     = "openclaw/secrets"
}

variable "secrets_region" {
  description = "האזור שבו שמור הסוד ב-Secrets Manager"
  type        = string
  default     = "eu-central-1"
}

variable "ssh_allowed_cidrs" {
  description = "מי רשאי להתחבר ב-SSH. מומלץ להגביל ל-IP שלך, למשל [\"1.2.3.4/32\"]. הגישה מוגנת במפתח בכל מקרה."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "budget_email" {
  description = "לאן לשלוח התראה על חיוב אמיתי (לא נשמר ב-git — ראה README). ריק = לא ליצור התראה"
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "התראה כשהחיוב האמיתי בחודש (אחרי קרדיטים) עובר את הסכום הזה"
  type        = string
  default     = "5"
}
