#!/usr/bin/env sh
# Creates .env from .env.example with freshly generated secrets.
# Safe to re-run: an existing .env is never overwritten.
set -eu
cd "$(dirname "$0")/.."

secret() { python3 -c "import secrets,sys; print(secrets.token_urlsafe(int(sys.argv[1])))" "$1" 2>/dev/null \
  || openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'; }

if [ -f .env ]; then
  # Existing install: only add settings introduced by later releases; never change values.
  if ! grep -q '^SECRETS_MASTER_KEY=..' .env || grep -q '^SECRETS_MASTER_KEY=CHANGE_ME' .env; then
    sed -i.bak '/^SECRETS_MASTER_KEY=/d' .env && rm -f .env.bak
    {
      echo ""
      echo "# Added by setup-env: encrypts stored AI provider API keys."
      echo "SECRETS_MASTER_KEY=$(secret 32)"
    } >> .env
    echo "Added SECRETS_MASTER_KEY to existing .env."
  else
    echo ".env already exists - leaving it unchanged."
  fi
  exit 0
fi

pg=$(secret 24)
jwt=$(secret 48)
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${pg}|" \
    -e "s|^JWT_SECRET=.*|JWT_SECRET=${jwt}|" \
    -e "s|^SECRETS_MASTER_KEY=.*|SECRETS_MASTER_KEY=$(secret 32)|" .env.example > .env
chmod 600 .env
echo "Created .env with new random secrets."
