#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  Video Summarizer — Production Deploy Script
#  Run this ON the EC2 / Compute Engine instance.
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

sudo systemctl is-active --quiet docker || sudo systemctl start docker

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

set -a
source .env
set +a

if [ -z "${GOOGLE_API_KEY:-}" ]; then
  error "GOOGLE_API_KEY is empty in .env — set it before deploying."
fi

info "GOOGLE_API_KEY is set."

# ----------------------------------------------------------
# 2. Cookie file for yt-dlp
# ----------------------------------------------------------
if [ ! -f cookies.txt ]; then
  touch cookies.txt
  warn "Created empty cookies.txt — populate with browser cookies if YouTube blocks downloads."
fi

# ----------------------------------------------------------
# 3. Build and start all services
# ----------------------------------------------------------
info "Building and starting production containers..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d

# ----------------------------------------------------------
# 4. Wait for health checks
# ----------------------------------------------------------
info "Waiting for services to become healthy..."
for i in $(seq 1 30); do
  if docker compose ps 2>/dev/null | grep -q "(healthy)"; then
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
PUBLIC_IP=$(curl -s http://checkip.amazonaws.com 2>/dev/null || \
            curl -s http://checkip.google-gcloud.com 2>/dev/null || \
            echo "<your-server-ip>")

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
# 6. SSL setup instructions
# ----------------------------------------------------------
if [ -n "${DOMAIN:-}" ]; then
  echo ""
  warn "DOMAIN is set to '${DOMAIN}'. To enable HTTPS:"
  echo ""
  echo "  1. Point your domain's DNS A record to ${PUBLIC_IP}"
  echo "  2. Wait for DNS propagation (use: dig ${DOMAIN})"
  echo "  3. Run:  ./deploy.sh ssl"
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

  docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm certbot \
    certonly --webroot --webroot-path=/var/www/certbot \
    --email "admin@${DOMAIN}" --agree-tos --no-eff-email \
    -d "${DOMAIN}"

  info "Switching nginx to HTTPS mode..."

  cat > frontend/nginx.prod.conf << SSLCONF
upstream gateway {
    server gateway:8000;
    keepalive 32;
}

limit_req_zone \$binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone \$binary_remote_addr zone=general:10m rate=30r/s;
limit_conn_zone \$binary_remote_addr zone=conn_limit:10m;

# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self' data:;" always;

    limit_conn conn_limit 50;
    client_max_body_size 500M;
    client_body_timeout 60s;
    client_header_timeout 60s;

    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_min_length 256;
    gzip_types text/plain text/css text/javascript application/javascript application/json application/xml image/svg+xml;

    root /usr/share/nginx/html;
    index index.html;

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2|woff|ttf|eot|map)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location /health {
        access_log off;
        return 200 'ok';
        add_header Content-Type text/plain;
    }

    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://gateway/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1h;
        proxy_send_timeout 60s;
        proxy_connect_timeout 10s;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
        location ~* \.html\$ {
            expires -1;
            add_header Cache-Control "no-cache, no-store, must-revalidate";
        }
    }

    location ~ /\. { deny all; access_log off; log_not_found off; }
    location ~* /(wp-admin|wp-login|phpmyadmin|\.env|\.git) { return 444; }

    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log warn;
}
SSLCONF

  # Restart nginx to pick up SSL config
  docker compose -f docker-compose.yml -f docker-compose.prod.yml restart frontend

  info "SSL certificate installed! https://${DOMAIN} should now work."
  echo ""
  echo "  Auto-renewal runs every 12 hours via certbot container."
  echo "  Manual renew: docker compose run --rm certbot renew"
fi

# ----------------------------------------------------------
# 8. Show firewall status
# ----------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
  echo ""
  info "=== Firewall Status ==="
  ufw status numbered 2>/dev/null || true
fi
