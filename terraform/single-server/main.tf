# שרת אחד עם docker compose — זול בהרבה מה-cluster של K8s (../main.tf)
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_security_group" "openclaw" {
  name        = "openclaw-single-sg"
  description = "OpenClaw single server - SSH only"
  vpc_id      = var.vpc_id

  # הבוט רק פונה החוצה (Telegram, Alpaca, Groq) — אין צורך בפורטים נכנסים חוץ מ-SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
    description = "SSH"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = {
    Name    = "openclaw-single-sg"
    Project = "open-claw"
  }
}

# Ubuntu 22.04 ל-ARM (Graviton) — זול יותר מ-t3 באותו גודל, וה-images נבנים גם ל-arm64
data "aws_ami" "ubuntu_arm" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# המפתח הציבורי עולה ל-AWS; הפרטי נשאר רק במחשב שלך (ssh-keygen -t ed25519 -f ~/.ssh/openclaw)
resource "aws_key_pair" "openclaw" {
  key_name   = "openclaw"
  public_key = file(pathexpand(var.public_key_path))
}

resource "aws_instance" "bot" {
  ami                         = data.aws_ami.ubuntu_arm.id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.openclaw.id]
  key_name                    = aws_key_pair.openclaw.key_name
  iam_instance_profile        = var.instance_profile != "" ? var.instance_profile : null
  associate_public_ip_address = true

  metadata_options {
    http_tokens = "required"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e
    # swap של 1GB — רשת ביטחון ל-build של ה-images
    fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab

    apt-get update
    apt-get install -y ca-certificates curl git awscli python3
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker ubuntu

    sudo -u ubuntu git clone ${var.repo_url} /home/ubuntu/openclaw
    cd /home/ubuntu/openclaw
    # עדכון אוטומטי: כל 5 דקות בודק אם יש commit חדש ב-main ומעדכן את הבוט
    echo '*/5 * * * * ubuntu /home/ubuntu/openclaw/deploy/auto-update.sh >> /home/ubuntu/auto-update.log 2>&1' > /etc/cron.d/openclaw-update

    # אם יש גישה לסוד ב-Secrets Manager — כותבים .env ומפעילים את הבוט. אחרת ממלאים .env ידנית.
    umask 077
    if aws secretsmanager get-secret-value --secret-id ${var.secrets_id} --region ${var.secrets_region} \
         --query SecretString --output text > /tmp/secret.json 2>/dev/null; then
      python3 - <<'PY' > .env
    import json
    d = json.load(open("/tmp/secret.json"))
    for k in ["TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "GROQ_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"]:
        print(f"{k}={d.get(k, '')}")
    print(f"ALPACA_BASE_URL={d.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')}")
    PY
      rm -f /tmp/secret.json
      chown ubuntu:ubuntu .env
      docker compose up -d --build
    else
      echo "Secrets Manager not reachable - fill /home/ubuntu/openclaw/.env and run: docker compose up -d --build" > /home/ubuntu/README-FIRST.txt
    fi
  EOF

  user_data_replace_on_change = true

  # בלי זה, כל גרסת Ubuntu חדשה או שינוי ב-user_data יגרמו ל-apply הבא (למשל עדכון IP של SSH)
  # למחוק את השרת ולבנות חדש — והבוט ייפול עד שממלאים .env מחדש. החלפה מכוונת: terraform apply -replace=aws_instance.bot
  lifecycle {
    ignore_changes = [ami, user_data]
  }

  root_block_device {
    volume_size = 16
    volume_type = "gp3"
  }

  tags = {
    Name    = "openclaw-bot"
    Project = "open-claw"
  }
}

# התראה במייל כשיש חיוב אמיתי. העלות כאן היא אחרי קיזוז קרדיטים (ברירת המחדל של AWS Budgets),
# כך שכל עוד הקרדיט מכסה — אין התראה. אחרי שהקרדיט נגמר או פג — מקבלים מייל.
# נוצרת רק אם budget_email מוגדר (אם כבר יצרת התראה ידנית בקונסולה — השאר ריק).
resource "aws_budgets_budget" "monthly" {
  count        = var.budget_email != "" ? 1 : 0
  name         = "openclaw-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
