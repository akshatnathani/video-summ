#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  Video Summarizer — EC2 Production Deploy Script
#  Run this ON the EC2 instance after cloning your repo.
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ----------------------------------------------------------
# 0. Prerequisites check
# ----------------------------------------------------------
command -v docker >/dev/null 2>&1 || error "Docker not installed. Run: sudo apt install -y docker.io docker-compose-v2"

# Ensure docker daemon is running
sudo systemctl is-active --quiet docker || sudo systemctl start docker

# Ensure the current user can run docker without sudo
if ! groups "$USER" | grep -q docker; then
  warn "Adding $USER to docker group..."
  sudo usermod -aG docker "$USER"
  info "Run 'newgrp docker' or log out and back in for group changes to take effect."
fi

# ----------------------------------------------------------
# 1. Environment file
# ----------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env created from .env.example — edit it and set GOOGLE_API_KEY before starting."
  echo ""
  read -rp "Press Enter after editing .env to continue..."
fi

# Source .env for use in this script
set -a
source .env
set +a

if [ -z "${GOOGLE_API_KEY:-}" ]; then
  error "GOOGLE_API_KEY is empty in .env — set it before deploying."
fi

info "GOOGLE_API_KEY is set."

# ----------------------------------------------------------
# 2. Create cookie.txt if missing (yt-dlp cookies)
# ----------------------------------------------------------
if [ ! -f cookies.txt ]; then
  touch cookies.txt
  warn "Created empty cookies.txt — populate it with browser cookies if YouTube blocks downloads."
fi

# ----------------------------------------------------------
# 3. Build and start all services
# ----------------------------------------------------------
info "Building and starting production containers..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

# ----------------------------------------------------------
# 4. Wait for health checks
# ----------------------------------------------------------
info "Waiting for services to become healthy (this may take a minute)..."
for i in $(seq 1 30); do
  if docker compose ps --format json 2>/dev/null | grep -q '"Health":"healthy"' || \
     docker compose ps 2>/dev/null | grep -q "(healthy)"; then
    break
  fi
  sleep 2
done

echo ""
info "=== Service Status ==="
docker compose ps

# ----------------------------------------------------------
# 5. Print summary
# ----------------------------------------------------------
PUBLIC_IP=$(curl -s http://checkip.amazonaws.com 2>/dev/null || echo "<your-ec2-ip>")

echo ""
echo "============================================="
info "Deployment complete!"
echo "============================================="
echo ""
echo "  Frontend:  http://${PUBLIC_IP}"
echo "  Gateway:   http://${PUBLIC_IP}/api/health"
echo ""
echo "  To view logs:    docker compose logs -f"
echo "  To stop:         docker compose down"
echo "  To restart:      docker compose restart"
echo ""

# ----------------------------------------------------------
# 6. SSL setup (optional)
# ----------------------------------------------------------
if [ -n "${DOMAIN:-}" ]; then
  echo ""
  warn "DOMAIN is set to '${DOMAIN}'. To enable HTTPS:"
  echo ""
  echo "  1. Point your domain's DNS A record to ${PUBLIC_IP}"
  echo "  2. Run:  ./deploy.sh ssl"
  echo ""
fi

# ----------------------------------------------------------
# 7. SSL certificate issuance
# ----------------------------------------------------------
if [ "${1:-}" = "ssl" ]; then
  if [ -z "${DOMAIN:-}" ]; then
    error "Set DOMAIN in .env first, then run: ./deploy.sh ssl"
  fi

  info "Requesting SSL certificate for ${DOMAIN}..."

  # Get initial certificate
  docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot \
    certonly --webroot --webroot-path=/var/www/certbot \
    --email "admin@${DOMAIN}" --agree-tos --no-eff-email \
    -d "${DOMAIN}"

  # Switch nginx to HTTPS config
  info "Switching nginx to HTTPS mode..."

  cat > frontend/nginx.prod.conf << 'SSLCONF'
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://gateway:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
    }

    location / {
        try_files $uri /index.html;
    }
}
SSLCONF

  sed -i "s/DOMAIN_PLACEHOLDER/${DOMAIN}/g" frontend/nginx.prod.conf

  # Restart nginx to pick up SSL config
  docker compose -f docker-compose.yml -f docker-compose.prod.yml restart frontend

  info "SSL certificate installed! https://${DOMAIN} should now work."
  echo ""
  echo "  Auto-renewal is configured via the certbot container."
  echo "  To manually renew: docker compose run --rm certbot renew"
fi
