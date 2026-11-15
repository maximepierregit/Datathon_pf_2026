#!/usr/bin/env bash
# Déploie les agents MonPort (backend/main.py) sur AgentCore Runtime : ./deploy/deploy-agentcore.sh
#
# Crée ou met à jour le rôle d'exécution monport-agents-runtime (Bedrock, lecture du dataset, logs et traces), construit
# le zip arm64 (backend/scripts/build_package.sh), l'envoie dans S3 et crée ou met à jour le runtime monport_agents.
# L'ARN est écrit dans deploy/state/agents-runtime-arn. Variables facultatives : MODEL_STRONG, MODEL_PEPITE, MODEL_EFFORT,
# TOOLS_BACKEND, GATEWAY_URL, GUARDRAIL_ID, GUARDRAIL_VERSION, MEMORY_ID (lues aussi dans deploy/state).
source "$(dirname "$0")/lib.sh"

NAME=monport_agents
ROLE=$(ensure_role monport-agents-runtime "$(render "$ROOT/deploy/agentcore/runtime-trust.json")" \
  "$(render "$ROOT/deploy/agentcore/agents-policy.json")")

if [ "${SKIP_BUILD:-0}" != 1 ]; then
  log "construction du zip (quelques minutes)"
  "$ROOT/backend/scripts/build_package.sh" >&2
fi

ENV=$(python3 - <<EOF
import json
env = {
    "MONPORT_UNIVERSE_PARQUET_URI": "s3://$BUCKET/universe/universe.parquet",
    "MONPORT_MACRO_PARQUET_URI": "s3://$BUCKET/macro/macro_long_z.parquet",
    "MONPORT_FACTORS_PARQUET_URI": "s3://$BUCKET/factors/factor_scores.parquet",
    "MODEL_STRONG": "${MODEL_STRONG:-global.anthropic.claude-opus-5-5}",
    "MODEL_FAST": "${MODEL_FAST:-global.anthropic.claude-opus-5-5}",
    "MODEL_PEPITE": "${MODEL_PEPITE:-global.anthropic.claude-sonnet-5-5}",
    "MODEL_EFFORT": "${MODEL_EFFORT:-high}",
    "TOOLS_BACKEND": "${TOOLS_BACKEND:-$(state_get tools-backend)}",
    "GATEWAY_URL": "${GATEWAY_URL:-$(state_get gateway-url)}",
    "GUARDRAIL_ID": "${GUARDRAIL_ID:-$(state_get guardrail-id)}",
    "GUARDRAIL_VERSION": "${GUARDRAIL_VERSION:-$(state_get guardrail-version)}",
    "MEMORY_ID": "${MEMORY_ID:-$(state_get memory-id)}",
}
print(json.dumps({k: v for k, v in env.items() if v}))
EOF
)

ARN=$(deploy_runtime "$NAME" "$ROOT/backend/build/deployment_package.zip" "$ROLE" "$ENV")
state_set agents-runtime-arn "$ARN"
echo "$ARN"
