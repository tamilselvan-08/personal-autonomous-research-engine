#!/usr/bin/env sh
# Creates .env from .env.example with freshly generated secrets.
# Safe to re-run: an existing .env is never overwritten.
set -eu
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists - leaving it unchanged."
  exit 0
fi

secret() { python3 -c "import secrets,sys; print(secrets.token_urlsafe(int(sys.argv[1])))" "$1" 2>/dev/null \
  || openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'; }

pg=$(secret 24)
jwt=$(secret 48)
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pg}|" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=${jwt}|" .env.example > .env
chmod 600 .env
echo "Created .env with new random secrets."
