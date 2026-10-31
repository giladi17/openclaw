output "public_ip" {
  value       = aws_instance.bot.public_ip
  description = "IP ציבורי של השרת"
}

output "ssh_command" {
  value       = "ssh -i ~/.ssh/${var.key_name}.pem ubuntu@${aws_instance.bot.public_ip}"
  description = "פקודת SSH לשרת"
}
