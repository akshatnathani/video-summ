#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  AWS VPC + EC2 Setup Script
#  Run this on your LOCAL machine (not the server).
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Check AWS CLI ──
command -v aws >/dev/null 2>&1 || error "AWS CLI not installed. Run: pip install awscli"
aws sts get-caller-identity >/dev/null 2>&1 || error "AWS not configured. Run: aws configure"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"
KEY_NAME="video-summarizer-key"

echo ""
info "=== AWS VPC + EC2 Setup ==="
echo "  Account: $ACCOUNT_ID"
echo "  Region:  $REGION"
echo ""

# ── Step 1: Create Key Pair ──
if ! aws ec2 describe-key-pairs --key-names $KEY_NAME --region $REGION >/dev/null 2>&1; then
  info "Creating key pair..."
  aws ec2 create-key-pair --key-name $KEY_NAME --region $REGION \
    --query 'KeyMaterial' --output text > ~/${KEY_NAME}.pem
  chmod 400 ~/${KEY_NAME}.pem
  info "Key saved to ~/${KEY_NAME}.pem"
else
  info "Key pair $KEY_NAME already exists."
fi

# ── Step 2: Create VPC ──
VPC_ID=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 \
  --query 'Vpc.VpcId' --output text --region $REGION)
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-support --region $REGION
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames --region $REGION
aws ec2 create-tags --resources $VPC_ID --tags Key=Name,Value=video-summarizer-vpc --region $REGION
info "VPC: $VPC_ID"

# ── Step 3: Internet Gateway ──
IGW_ID=$(aws ec2 create-internet-gateway --region $REGION \
  --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID --region $REGION
aws ec2 create-tags --resources $IGW_ID --tags Key=Name,Value=video-summarizer-igw --region $REGION
info "IGW: $IGW_ID"

# ── Step 4: Subnets (2 AZs) ──
SUBNET_A=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 \
  --availability-zone ${REGION}a --region $REGION \
  --query 'Subnet.SubnetId' --output text)
aws ec2 create-tags --resources $SUBNET_A --tags Key=Name,Value=video-summarizer-subnet-a --region $REGION

SUBNET_B=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.2.0/24 \
  --availability-zone ${REGION}b --region $REGION \
  --query 'Subnet.SubnetId' --output text)
aws ec2 create-tags --resources $SUBNET_B --tags Key=Name,Value=video-summarizer-subnet-b --region $REGION
info "Subnet-A: $SUBNET_A (${REGION}a)"
info "Subnet-B: $SUBNET_B (${REGION}b)"

# ── Step 5: Route Table ──
RT_ID=$(aws ec2 create-route-table --vpc-id $VPC_ID --region $REGION \
  --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $RT_ID --destination-cidr-block 0.0.0.0/0 \
  --gateway-id $IGW_ID --region $REGION
aws ec2 associate-route-table --route-table-id $RT_ID --subnet-id $SUBNET_A --region $REGION
aws ec2 associate-route-table --route-table-id $RT_ID --subnet-id $SUBNET_B --region $REGION
aws ec2 modify-subnet-attribute --subnet-id $SUBNET_A --map-public-ip-on-launch --region $REGION
aws ec2 modify-subnet-attribute --subnet-id $SUBNET_B --map-public-ip-on-launch --region $REGION
info "Route table: $RT_ID"

# ── Step 6: Security Group (80, 443, 22 only) ──
SG_ID=$(aws ec2 create-security-group --group-name video-summarizer-sg \
  --description "HTTP/HTTPS/SSH only" --vpc-id $VPC_ID --region $REGION \
  --query 'GroupId' --output text)
MY_IP=$(curl -s http://checkip.amazonaws.com)

# SSH from your IP only
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
  --protocol tcp --port 22 --cidr "${MY_IP}/32" --region $REGION

# HTTP from anywhere
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
  --protocol tcp --port 80 --cidr 0.0.0.0/0 --region $REGION

# HTTPS from anywhere
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
  --protocol tcp --port 443 --cidr 0.0.0.0/0 --region $REGION

aws ec2 create-tags --resources $SG_ID --tags Key=Name,Value=video-summarizer-sg --region $REGION
info "Security Group: $SG_ID (SSH locked to ${MY_IP}/32)"

# ── Step 7: Create IAM Role for EC2 (S3 access) ──
ROLE_NAME="video-summarizer-ec2-role"
if ! aws iam get-role --role-name $ROLE_NAME >/dev/null 2>&1; then
  aws iam create-role --role-name $ROLE_NAME \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
    }'

  aws iam put-role-policy --role-name $ROLE_NAME --policy-name s3-access \
    --policy-document '{
      "Version": "2012-10-17",
      "Statement": [{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],"Resource":"*"}]
    }'

  aws iam create-instance-profile --instance-profile-name ${ROLE_NAME}-profile
  aws iam add-role-to-instance-profile --instance-profile-name ${ROLE_NAME}-profile --role-name $ROLE_NAME
  sleep 10
  info "IAM role created: $ROLE_NAME"
fi

# ── Step 8: Launch EC2 Instance ──
AMI_ID=$(aws ec2 describe-images --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
  "Name=state,Values=available" --region $REGION \
  --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)

# Startup script
cat > /tmp/user-data.sh << 'USERDATA'
#!/bin/bash
set -e
apt-get update && apt-get upgrade -y
apt-get install -y docker.io docker-compose-v2 git awscli ufw

systemctl enable docker && systemctl start docker
usermod -aG docker ubuntu

# Swap (helps with 1GB RAM)
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
swapon /swapfile

# UFW firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "Setup complete" > /home/ubuntu/setup-done.log
USERDATA

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id $AMI_ID \
  --instance-type t3.micro \
  --key-name $KEY_NAME \
  --subnet-id $SUBNET_A \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=${ROLE_NAME}-profile \
  --user-data file:///tmp/user-data.sh \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=video-summarizer}]' \
  --region $REGION \
  --query 'Instances[0].InstanceId' --output text)

info "Launching instance: $INSTANCE_ID"
aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $REGION
sleep 15

PUBLIC_IP=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --region $REGION \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo ""
echo "============================================="
info "AWS Infrastructure Ready!"
echo "============================================="
echo ""
echo "  Instance:  $INSTANCE_ID"
echo "  Public IP: $PUBLIC_IP"
echo "  SSH:       ssh -i ~/${KEY_NAME}.pem ubuntu@${PUBLIC_IP}"
echo ""
echo "  Next steps:"
echo "  1. SSH into the instance"
echo "  2. git clone https://github.com/akshatnathani/video-summ.git"
echo "  3. cd video-summ && cp .env.example .env && nano .env"
echo "  4. ./deploy.sh"
echo ""
