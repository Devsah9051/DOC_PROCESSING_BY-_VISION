#!/usr/bin/env bash
# Setup Docker PostgreSQL for EGCA Phase 1
# Usage: ./scripts/setup_docker_postgres.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"

echo "==> Starting PostgreSQL via Docker Compose..."
docker compose -f "$COMPOSE_FILE" up -d

echo "==> Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
  if docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U postgres >/dev/null 2>&1; then
    echo "==> PostgreSQL is ready."
    break
  fi
  sleep 2
done

echo "==> Initializing database schema..."
DATABASE_URL=postgresql://postgres:password@localhost:5432/egca \
  python3 "$PROJECT_DIR/scripts/init_db.py"

echo "==> Writing .env file..."
cat > "$ENV_FILE" <<EOF
DATABASE_URL=postgresql://postgres:password@localhost:5432/egca
SEAL_KEY=$(python3 -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64; print(base64.b64encode(Ed25519PrivateKey.generate().private_bytes_raw()).decode())")
EOF

echo "==> Done. PostgreSQL is running on localhost:5432"
echo "    Connect: psql -U postgres -d egca -h localhost -p 5432"
echo "    Password: password"
