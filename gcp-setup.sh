#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  GCP VPC + Compute Engine Setup Script
#  Run this on your LOCAL machine.
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Check gcloud ──
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not installed."
gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1 >/dev/null 2>&1 || \
  error "gcloud not authenticated. Run: gcloud auth login"

PROJECT_ID=$(gcloud config get-value project)
REGION="us-central1"
ZONE="${REGION}-a"

echo ""
info "=== GCP VPC + Compute Engine Setup ==="
echo "  Project: $PROJECT_ID"
echo "  Region:  $REGION"
echo "  Zone:    $ZONE"
echo ""

# ── Step 1: Enable APIs ──
info "Enabling required APIs..."
gcloud services enable compute.googleapis.com container.googleapis.com \
  storage.googleapis.com dns.googleapis.com 2>/dev/null || true

# ── Step 2: Create VPC ──
if ! gcloud compute networks describe video-summarizer-vpc --project=$PROJECT_ID >/dev/null 2>&1; then
  gcloud compute networks create video-summarizer-vpc --subnet-mode=custom
  info "VPC created: video-summarizer-vpc"
else
  info "VPC already exists: video-summarizer-vpc"
fi

# ── Step 3: Create Subnets (2 AZs) ──
for SUBNET in "vs-subnet-a 10.0.1.0/24 ${REGION}" "vs-subnet-b 10.0.2.0/24 ${REGION}"; do
  read -r NAME CIDR SUBREGION <<< "$SUBNET"
  if ! gcloud compute networks subnets describe $NAME --region=$SUBREGION --project=$PROJECT_ID >/dev/null 2>&1; then
    gcloud compute networks subnets create $NAME \
      --network=video-summarizer-vpc --region=$SUBREGION --range=$CIDR
    info "Subnet created: $NAME ($CIDR)"
  else
    info "Subnet exists: $NAME"
  fi
done

# ── Step 4: Firewall Rules ──
MY_IP=$(curl -s http://checkip.amazonaws.com)

# Allow SSH, HTTP, HTTPS
if ! gcloud compute firewall-rules describe allow-ssh-http-https --project=$PROJECT_ID >/dev/null 2>&1; then
  gcloud compute firewall-rules create allow-ssh-http-https \
    --network=video-summarizer-vpc \
    --allow=tcp:22,tcp:80,tcp:443 \
    --source-ranges="${MY_IP}/32,0.0.0.0/0" \
    --direction=INGRESS --priority=1000
  info "Firewall: allow-ssh-http-https (SSH from ${MY_IP}/32)"
fi

# Allow internal
if ! gcloud compute firewall-rules describe allow-internal --project=$PROJECT_ID >/dev/null 2>&1; then
  gcloud compute firewall-rules create allow-internal \
    --network=video-summarizer-vpc \
    --allow=tcp,udp,icmp \
    --source-ranges=10.0.0.0/8 \
    --direction=INGRESS --priority=500
fi

# Deny all else
if ! gcloud compute firewall-rules describe deny-all-ingress --project=$PROJECT_ID >/dev/null 2>&1; then
  gcloud compute firewall-rules create deny-all-ingress \
    --network=video-summarizer-vpc \
    --action=DENY --rules=all \
    --source-ranges=0.0.0.0/0 \
    --direction=INGRESS --priority=65534
fi

# ── Step 5: Create Startup Script ──
cat > /tmp/gcp-startup.sh << 'STARTUP'
#!/bin/bash
set -e
apt-get update && apt-get upgrade -y
apt-get install -y docker.io docker-compose-v2 git ufw

systemctl enable docker && systemctl start docker
usermod -aG docker ubuntu

# Swap
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
swapon /swapfile

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "Setup complete" > /home/ubuntu/setup-done.log
STARTUP

# ── Step 6: Reserve Static IP ──
if ! gcloud compute addresses describe vs-static-ip --region=$REGION --project=$PROJECT_ID >/dev/null 2>&1; then
  gcloud compute addresses create vs-static-ip --region=$REGION --project=$PROJECT_ID
  info "Static IP reserved"
fi
STATIC_IP=$(gcloud compute addresses describe vs-static-ip --region=$REGION \
  --project=$PROJECT_ID --format="value(address)")

# ── Step 7: Launch Instance (Always Free e2-micro) ──
if ! gcloud compute instances describe video-summarizer --zone=$ZONE --project=$PROJECT_ID >/dev/null 2>&1; then
  gcloud compute instances create video-summarizer \
    --zone=$ZONE \
    --machine-type=e2-micro \
    --network-interface=subnet=vs-subnet-a,address=$STATIC_IP \
    --metadata-from-file startup-script=/tmp/gcp-startup.sh \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-standard \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=video-summarizer \
    --project=$PROJECT_ID
  info "Instance launched: video-summarizer"
else
  info "Instance already exists: video-summarizer"
fi

# ── Step 8: Create S3-equivalent Bucket ──
BUCKET="${PROJECT_ID}-media-cache"
if ! gsutil ls gs://${BUCKET} >/dev/null 2>&1; then
  gsutil mb -l $REGION -b on gs://${BUCKET}

  # Lifecycle: delete after 7 days
  cat > /tmp/lifecycle.json << 'EOF'
{
  "rule": [
    {"action": {"type": "Delete"}, "condition": {"age": 7}},
    {"action": {"type": "SetStorageClass", "storageClass": "COLDLINE"}, "condition": {"age": 2}}
  ]
}
EOF
  gsutil lifecycle set /tmp/lifecycle.json gs://${BUCKET}

  # Block public
  gsutil iam d allUsers gs://${BUCKET} 2>/dev/null || true
  info "Bucket created: gs://${BUCKET}"
fi

echo ""
echo "============================================="
info "GCP Infrastructure Ready!"
echo "============================================="
echo ""
echo "  Instance:  video-summarizer ($ZONE)"
echo "  Static IP: $STATIC_IP"
echo "  SSH:       gcloud compute ssh video-summarizer --zone=$ZONE"
echo ""
echo "  Next steps:"
echo "  1. SSH into the instance"
echo "  2. git clone https://github.com/akshatnathani/video-summ.git"
echo "  3. cd video-summ && cp .env.example .env && nano .env"
echo "  4. ./deploy.sh"
echo ""
