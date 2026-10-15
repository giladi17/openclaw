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

resource "aws_security_group" "open_claw_sg" {
  name        = "open-claw-sg"
  description = "Security Group for Open-Claw K8s Cluster"
  vpc_id      = var.vpc_id

  # SSH — רק מהכתובות ב-ssh_allowed_cidrs (ראה variables.tf)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
    description = "SSH"
  }

  # Kubernetes API — מתוך ה-VPC, ובנוסף מהכתובות ב-k8s_api_allowed_cidrs (למשל ה-IP שלך ל-kubectl)
  ingress {
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = concat(["172.31.0.0/16"], var.k8s_api_allowed_cidrs)
    description = "Kubernetes API Server"
  }

  ingress {
    from_port   = 2379
    to_port     = 2380
    protocol    = "tcp"
    cidr_blocks = ["172.31.0.0/16"]
    description = "etcd"
  }

  ingress {
    from_port   = 10250
    to_port     = 10252
    protocol    = "tcp"
    cidr_blocks = ["172.31.0.0/16"]
    description = "Kubelet API"
  }

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["172.31.0.0/16"]
    description = "Internal VPC traffic"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = {
    Name    = "open-claw-sg"
    Project = "open-claw"
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "master" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.master_instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.open_claw_sg.id]
  key_name                    = var.key_name
  iam_instance_profile        = "openclaw-ec2-profile"
  associate_public_ip_address = true

  user_data = <<-EOF
    #!/bin/bash
    set -e
    apt-get update
    apt-get install -y apt-transport-https ca-certificates curl awscli python3
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
    apt-get update
    apt-get install -y kubelet kubeadm kubectl containerd
    systemctl enable --now containerd
    mkdir -p /etc/containerd
    containerd config default > /etc/containerd/config.toml
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    systemctl restart containerd
    swapoff -a
    sed -i '/ swap / s/^/#/' /etc/fstab
    modprobe br_netfilter
    echo 'net.bridge.bridge-nf-call-iptables=1' >> /etc/sysctl.conf
    echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
    sysctl -p
    PRIVATE_IP=$(curl -s http://169.254.169.254/latest/meta-data/local-ipv4)
    kubeadm init --apiserver-advertise-address=$PRIVATE_IP --pod-network-cidr=10.244.0.0/16
    mkdir -p /home/ubuntu/.kube
    cp /etc/kubernetes/admin.conf /home/ubuntu/.kube/config
    chown ubuntu:ubuntu /home/ubuntu/.kube/config
    export KUBECONFIG=/etc/kubernetes/admin.conf
    kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml
    kubectl taint nodes --all node-role.kubernetes.io/control-plane:NoSchedule-
    kubeadm token create --print-join-command > /home/ubuntu/join-command.sh
    chmod +x /home/ubuntu/join-command.sh
    umask 077
    aws secretsmanager get-secret-value --secret-id ${var.secrets_id} --region ${var.secrets_region} --query SecretString --output text > /tmp/secret.json
    get() { python3 -c "import json,sys; d=json.load(open('/tmp/secret.json')); print(d.get(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else ''))" "$@"; }
    # כל המפתחות שהסוכנים צריכים — כולל Alpaca ו-Chat ID שהיו חסרים קודם
    kubectl create secret generic openclaw-secrets \
      --from-literal=TELEGRAM_TOKEN="$(get TELEGRAM_TOKEN)" \
      --from-literal=TELEGRAM_CHAT_ID="$(get TELEGRAM_CHAT_ID)" \
      --from-literal=GROQ_API_KEY="$(get GROQ_API_KEY)" \
      --from-literal=ALPACA_API_KEY="$(get ALPACA_API_KEY)" \
      --from-literal=ALPACA_SECRET_KEY="$(get ALPACA_SECRET_KEY)" \
      --from-literal=ALPACA_BASE_URL="$(get ALPACA_BASE_URL https://paper-api.alpaca.markets)"
    kubectl create secret docker-registry dockerhub-secret --docker-username="$(get DOCKERHUB_USERNAME)" --docker-password="$(get DOCKERHUB_TOKEN)"
    rm -f /tmp/secret.json
    for f in rbac redis quota brain cronjob network-policy; do
      kubectl apply -f https://raw.githubusercontent.com/giladi17/openclaw/main/k8s/$f.yaml
    done
  EOF

  user_data_replace_on_change = true

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name    = "open-claw-master"
    Role    = "master"
    Project = "open-claw"
  }
}

resource "aws_instance" "worker" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.worker_instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.open_claw_sg.id]
  key_name                    = var.key_name
  iam_instance_profile        = "openclaw-ec2-profile"
  associate_public_ip_address = true

  user_data = <<-EOF
    #!/bin/bash
    set -e
    apt-get update
    apt-get install -y apt-transport-https ca-certificates curl
    curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
    echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list
    apt-get update
    apt-get install -y kubelet kubeadm kubectl containerd
    systemctl enable --now containerd
    mkdir -p /etc/containerd
    containerd config default > /etc/containerd/config.toml
    sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
    systemctl restart containerd
    swapoff -a
    sed -i '/ swap / s/^/#/' /etc/fstab
    modprobe br_netfilter
    echo 'net.bridge.bridge-nf-call-iptables=1' >> /etc/sysctl.conf
    echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
    sysctl -p
  EOF

  user_data_replace_on_change = true

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name    = "open-claw-worker"
    Role    = "worker"
    Project = "open-claw"
  }
}