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

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "SSH"
  }

  ingress {
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
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
    from_port   = 30000
    to_port     = 32767
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "NodePort Services"
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
    kubeadm token create --print-join-command > /home/ubuntu/join-command.sh
    chmod +x /home/ubuntu/join-command.sh
    aws secretsmanager get-secret-value --secret-id openclaw/secrets --region eu-central-1 --query SecretString --output text > /tmp/secret.json
    TELEGRAM_TOKEN=$(python3 -c "import json; d=json.load(open('/tmp/secret.json')); print(d['TELEGRAM_TOKEN'])")
    GROQ_API_KEY=$(python3 -c "import json; d=json.load(open('/tmp/secret.json')); print(d['GROQ_API_KEY'])")
    DOCKERHUB_USERNAME=$(python3 -c "import json; d=json.load(open('/tmp/secret.json')); print(d['DOCKERHUB_USERNAME'])")
    DOCKERHUB_TOKEN=$(python3 -c "import json; d=json.load(open('/tmp/secret.json')); print(d['DOCKERHUB_TOKEN'])")
    kubectl create secret generic openclaw-secrets --from-literal=TELEGRAM_TOKEN=$TELEGRAM_TOKEN --from-literal=GROQ_API_KEY=$GROQ_API_KEY
    kubectl create secret docker-registry dockerhub-secret --docker-username=$DOCKERHUB_USERNAME --docker-password=$DOCKERHUB_TOKEN
    kubectl apply -f https://raw.githubusercontent.com/doronsun/openclaw/main/k8s/rbac.yaml
    kubectl apply -f https://raw.githubusercontent.com/doronsun/openclaw/main/k8s/redis.yaml
    kubectl apply -f https://raw.githubusercontent.com/doronsun/openclaw/main/k8s/brain.yaml
    rm /tmp/secret.json
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