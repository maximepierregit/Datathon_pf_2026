#!/usr/bin/env bash
# Publie les outils métier derrière AgentCore Gateway : ./deploy/deploy-gateway.sh
#
#   1. runtime monport_tools : le serveur MCP (backend/mcp_server/main.py), rôle monport-tools-runtime (lecture S3)
#   2. Gateway monport-tools (MCP, authentification entrante IAM), rôle monport-gateway (InvokeAgentRuntime)
#   3. cible monport-tools : le runtime MCP, appelé en SigV4 avec le rôle de la Gateway, puis synchronisation
# Écrit deploy/state/{tools-runtime-arn,gateway-id,gateway-url}. Ensuite : TOOLS_BACKEND=gateway, voir deploy-agentcore.sh.
source "$(dirname "$0")/lib.sh"

TRUST="$(render "$ROOT/deploy/agentcore/runtime-trust.json")"

# 1. Serveur MCP sur AgentCore Runtime
TOOLS_ROLE=$(ensure_role monport-tools-runtime "$TRUST" "$(render "$ROOT/deploy/agentcore/tools-policy.json")")
if [ "${SKIP_BUILD:-0}" != 1 ]; then
  log "construction du zip du serveur MCP"
  ENTRY=mcp_server/main.py OUT=build/tools_package.zip "$ROOT/backend/scripts/build_package.sh" >&2
fi
ENV=$(printf '{"MONPORT_UNIVERSE_PARQUET_URI":"s3://%s/universe/universe.parquet","MONPORT_MACRO_PARQUET_URI":"s3://%s/macro/macro_long_z.parquet","MONPORT_FACTORS_PARQUET_URI":"s3://%s/factors/factor_scores.parquet"}' "$BUCKET" "$BUCKET" "$BUCKET")
TOOLS_ARN=$(deploy_runtime monport_tools "$ROOT/backend/build/tools_package.zip" "$TOOLS_ROLE" "$ENV" '{"serverProtocol":"MCP"}')
state_set tools-runtime-arn "$TOOLS_ARN"

# 2. Gateway
GW_POLICY=$(cat <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"bedrock-agentcore:InvokeAgentRuntime",
 "Resource":["$TOOLS_ARN","$TOOLS_ARN/*"]}]}
EOF
)
GW_ROLE=$(ensure_role monport-gateway "$TRUST" "$GW_POLICY")
# Sessions MCP : la Gateway garde la session du serveur MCP, donc la même microVM (dataset déjà en mémoire). Sans elles,
# chaque appel d'outil démarre une microVM à froid (environ 18 s au lieu de 0,5 s).
GW_ARGS=(--name monport-tools --role-arn "$GW_ROLE" --protocol-type MCP --authorizer-type AWS_IAM --exception-level DEBUG
  --description "Outils financiers MonPort (univers, optimiseur, vérificateur, macro)"
  --protocol-configuration '{"mcp":{"sessionConfiguration":{"sessionTimeoutInSeconds":28800}}}')
GW_ID=$(aws bedrock-agentcore-control list-gateways --query "items[?name=='monport-tools'].gatewayId | [0]" --output text)
if [ "$GW_ID" = None ] || [ -z "$GW_ID" ]; then
  log "création de la Gateway monport-tools"
  GW_ID=$(aws bedrock-agentcore-control create-gateway "${GW_ARGS[@]}" --query gatewayId --output text)
else
  log "mise à jour de la Gateway ($GW_ID)"
  aws bedrock-agentcore-control update-gateway --gateway-identifier "$GW_ID" "${GW_ARGS[@]}" >/dev/null
fi
sleep 3
for _ in $(seq 1 30); do
  GW_STATUS=$(aws bedrock-agentcore-control get-gateway --gateway-identifier "$GW_ID" --query status --output text)
  [ "$GW_STATUS" = READY ] && break; sleep 5
done
[ "$GW_STATUS" = READY ] || { log "Gateway pas prête ($GW_STATUS)"; exit 1; }
GW_URL=$(aws bedrock-agentcore-control get-gateway --gateway-identifier "$GW_ID" --query gatewayUrl --output text)

# 3. Cible : le runtime MCP, invoqué en SigV4 par le rôle de la Gateway
ENC_ARN=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$TOOLS_ARN")
ENDPOINT="https://bedrock-agentcore.$REGION.amazonaws.com/runtimes/$ENC_ARN/invocations?qualifier=DEFAULT"
TARGET_CFG=$(printf '{"mcp":{"mcpServer":{"endpoint":"%s"}}}' "$ENDPOINT")
CREDS=$(printf '[{"credentialProviderType":"GATEWAY_IAM_ROLE","credentialProvider":{"iamCredentialProvider":{"service":"bedrock-agentcore","region":"%s"}}}]' "$REGION")
TARGET_ID=$(aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GW_ID" \
  --query "items[?name=='monport-tools'].targetId | [0]" --output text)
if [ "$TARGET_ID" = None ] || [ -z "$TARGET_ID" ]; then
  log "création de la cible monport-tools"
  TARGET_ID=$(aws bedrock-agentcore-control create-gateway-target --gateway-identifier "$GW_ID" --name monport-tools \
    --target-configuration "$TARGET_CFG" --credential-provider-configurations "$CREDS" --query targetId --output text)
else
  log "mise à jour de la cible (resynchronise les outils)"
  aws bedrock-agentcore-control update-gateway-target --gateway-identifier "$GW_ID" --target-id "$TARGET_ID" \
    --name monport-tools --target-configuration "$TARGET_CFG" --credential-provider-configurations "$CREDS" >/dev/null
fi
for _ in $(seq 1 60); do
  T_STATUS=$(aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GW_ID" --target-id "$TARGET_ID" \
    --query status --output text)
  case "$T_STATUS" in READY) break ;; FAILED|*FAILED*)
    aws bedrock-agentcore-control get-gateway-target --gateway-identifier "$GW_ID" --target-id "$TARGET_ID" \
      --query statusReasons --output text >&2; exit 1 ;; esac
  sleep 5
done
[ "$T_STATUS" = READY ] || { log "cible pas prête ($T_STATUS)"; exit 1; }

state_set gateway-id "$GW_ID"
state_set gateway-url "$GW_URL"
echo "$GW_URL"
