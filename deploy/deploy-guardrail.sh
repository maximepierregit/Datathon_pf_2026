#!/usr/bin/env bash
# Crée ou met à jour le guardrail Bedrock de Pépite (deploy/agentcore/guardrail.json) et publie une version.
#   ./deploy/deploy-guardrail.sh      puis ./deploy/deploy-agentcore.sh pour que le runtime l'utilise
# L'id et la version sont écrits dans deploy/state/guardrail-id et guardrail-version.
source "$(dirname "$0")/lib.sh"

NAME=monport-pepite
CONFIG="$ROOT/deploy/agentcore/guardrail.json"
ID=$(aws bedrock list-guardrails --query "guardrails[?name=='$NAME'].id | [0]" --output text)
if [ "$ID" = None ] || [ -z "$ID" ]; then
  log "création du guardrail $NAME"
  ID=$(aws bedrock create-guardrail --name "$NAME" --cli-input-json "file://$CONFIG" --tags key=project,value=monport \
    --query guardrailId --output text)
else
  log "mise à jour du guardrail $NAME ($ID)"
  aws bedrock update-guardrail --guardrail-identifier "$ID" --name "$NAME" --cli-input-json "file://$CONFIG" >/dev/null
fi
VERSION=$(aws bedrock create-guardrail-version --guardrail-identifier "$ID" --description "deploy $(date +%F_%T)" \
  --query version --output text)
state_set guardrail-id "$ID"
state_set guardrail-version "$VERSION"
echo "$ID $VERSION"
