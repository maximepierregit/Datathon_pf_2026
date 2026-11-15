#!/usr/bin/env bash
# Construit build/deployment_package.zip pour AgentCore Runtime (déploiement par code, Linux arm64, Python 3.13).
# Prérequis: uv, zip.
# Le dataset est lu depuis S3 (MONPORT_UNIVERSE_PARQUET_URI=s3://monport-datasets-381491955506/universe/universe.parquet) et n'est
# plus inclus dans le zip. Repli sans S3: EMBED_DATASET=1 ./scripts/build_package.sh embarque data/universe.parquet
# (MONPORT_UNIVERSE_PARQUET_URI reste alors à sa valeur par défaut).
# ENTRY=mcp_server/main.py OUT=build/tools_package.zip construit le zip du serveur MCP des outils (même code).
set -euo pipefail
cd "$(dirname "$0")/.."
ENTRY="${ENTRY:-main.py}"
OUT="${OUT:-build/deployment_package.zip}"

rm -rf build/pkg && mkdir -p build/pkg
uv pip install \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.13 \
  --target build/pkg \
  --only-binary=:all: \
  -r pyproject.toml --extra otel

cp "$ENTRY" build/pkg/main.py
cp -r src/invest_agents build/pkg/src_invest_agents_tmp
mkdir -p build/pkg/src && mv build/pkg/src_invest_agents_tmp build/pkg/src/invest_agents
if [ "${EMBED_DATASET:-0}" = "1" ]; then
  [ -f data/universe.parquet ] || { echo "data/universe.parquet introuvable (EMBED_DATASET=1)" >&2; exit 1; }
  mkdir -p build/pkg/data && cp data/universe.parquet build/pkg/data/
  # Table macro (MONPORT_MACRO_PARQUET_URI à sa valeur par défaut). Facultative: sans elle, les outils macro répondent par une erreur.
  if [ -f data/macro_long_z.parquet ]; then cp data/macro_long_z.parquet build/pkg/data/; fi
fi

find build/pkg -name "__pycache__" -type d -prune -exec rm -rf {} +
find build/pkg -type d -exec chmod 755 {} +
find build/pkg -type f -exec chmod 644 {} +

rm -f "$OUT" && (cd build/pkg && zip -qr "../$(basename "$OUT")" .)
ls -lh "$OUT"
