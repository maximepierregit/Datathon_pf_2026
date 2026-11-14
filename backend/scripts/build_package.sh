#!/usr/bin/env bash
# Construit build/deployment_package.zip pour AgentCore Runtime (déploiement par code, Linux arm64, Python 3.13).
# Prérequis: uv, zip. Le dataset (data/universe.parquet) est inclus s'il existe; sinon, utiliser DATASET_PATH=s3://...
set -euo pipefail
cd "$(dirname "$0")/.."

rm -rf build && mkdir -p build/pkg
uv pip install \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.13 \
  --target build/pkg \
  --only-binary=:all: \
  -r pyproject.toml

cp main.py build/pkg/main.py
cp -r src/invest_agents build/pkg/src_invest_agents_tmp
mkdir -p build/pkg/src && mv build/pkg/src_invest_agents_tmp build/pkg/src/invest_agents
if [ -f data/universe.parquet ]; then mkdir -p build/pkg/data && cp data/universe.parquet build/pkg/data/; fi

find build/pkg -name "__pycache__" -type d -prune -exec rm -rf {} +
find build/pkg -type d -exec chmod 755 {} +
find build/pkg -type f -exec chmod 644 {} +

(cd build/pkg && zip -qr ../deployment_package.zip .)
ls -lh build/deployment_package.zip
