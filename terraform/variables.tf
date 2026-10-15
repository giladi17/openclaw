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

variable "key_name" {
  description = "Key Pair Name"
  type        = string
}

variable "master_instance_type" {
  description = "Instance type for master node"
  type        = string
  default     = "t3.small"
}

variable "worker_instance_type" {
  description = "Instance type for worker node"
  type        = string
  default     = "t2.micro"
}
variable "secrets_id" {
  description = "שם הסוד ב-AWS Secrets Manager"
  type        = string
  default     = "openclaw/secrets"
}

variable "secrets_region" {
  description = "האזור שבו שמור הסוד ב-Secrets Manager (יכול להיות שונה מאזור השרתים)"
  type        = string
  default     = "eu-central-1"
}

variable "ssh_allowed_cidrs" {
  description = "מי רשאי להתחבר ב-SSH. ה-CI של GitHub מתחבר ב-SSH מכתובות משתנות, ולכן ברירת המחדל פתוחה — הגישה מוגנת במפתח בלבד."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "k8s_api_allowed_cidrs" {
  description = "כתובות חיצוניות שמורשות לגשת ל-Kubernetes API (פורט 6443), למשל [\"1.2.3.4/32\"]. ריק = רק מתוך ה-VPC."
  type        = list(string)
  default     = []
}
