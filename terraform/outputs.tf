output "master_public_ip" {
  value       = aws_instance.master.public_ip
  description = "IP ציבורי של Master Node"
}

output "worker_public_ip" {
  value       = aws_instance.worker.public_ip
  description = "IP ציבורי של Worker Node"
}

output "master_ssh_command" {
  value       = "ssh -i ~/.ssh/Gilad-agent.pem ubuntu@${aws_instance.master.public_ip}"
  description = "פקודת SSH למאסטר"
}

output "worker_ssh_command" {
  value       = "ssh -i ~/.ssh/Gilad-agent.pem ubuntu@${aws_instance.worker.public_ip}"
  description = "פקודת SSH לוורקר"
}
