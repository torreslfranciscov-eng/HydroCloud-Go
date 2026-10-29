#!/usr/bin/env bash
set -euo pipefail

# Uso: ./scripts/deploy_hf_space.sh <tu_usuario_hf>/<nombre_del_space>
# Ejemplo: ./scripts/deploy_hf_space.sh torreslfranciscov/hydrocloud-web

if [ $# -lt 1 ]; then
  echo "Uso: $0 <usuario_hf>/<nombre_space>"
  echo "Ejemplo: $0 torreslfranciscov/hydrocloud-web"
  exit 1
fi

SPACE_ID="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "📦 Preparando paquete de HydroCloud.Admin para Hugging Face Spaces ($SPACE_ID)..."
rsync -a \
  --exclude 'bin/' \
  --exclude 'obj/' \
  --exclude 'Properties/launchSettings.json' \
  --exclude 'appsettings.*.local.json' \
  "$ROOT_DIR/HydroCloud.Admin/" "$TMP_DIR/"

cd "$TMP_DIR"
git init -b main
git add .
git commit -m "Deploy HydroCloud.Admin (.NET 8 + Aiven PostgreSQL) to Hugging Face Spaces"

echo "🚀 Subiendo a https://huggingface.co/spaces/$SPACE_ID ..."
git push --force "https://huggingface.co/spaces/$SPACE_ID" main
echo "✅ Listo. Revisa el build en: https://huggingface.co/spaces/$SPACE_ID"

