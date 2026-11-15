#!/usr/bin/env bash
# Crée la mémoire AgentCore des conversations MonPort (court terme, sans stratégie d'extraction, 7 jours) :
#   ./deploy/deploy-memory.sh      puis ./deploy/deploy-agentcore.sh pour que le runtime l'utilise
# L'id est écrit dans deploy/state/memory-id.
source "$(dirname "$0")/lib.sh"

NAME=monport_conversations
ID=$(aws bedrock-agentcore-control list-memories --query "memories[?starts_with(id, '$NAME')].id | [0]" --output text)
if [ "$ID" = None ] || [ -z "$ID" ]; then
  log "création de la mémoire $NAME"
  ID=$(aws bedrock-agentcore-control create-memory --name "$NAME" --event-expiry-duration 7 \
    --description "État des conversations MonPort (questionnaire, portefeuilles, verdicts), pour reprendre après une microVM recyclée" \
    --tags project=monport --query memory.id --output text)
fi
for _ in $(seq 1 60); do
  STATUS=$(aws bedrock-agentcore-control get-memory --memory-id "$ID" --query memory.status --output text)
  [ "$STATUS" = ACTIVE ] && break; sleep 5
done
[ "$STATUS" = ACTIVE ] || { log "mémoire pas prête ($STATUS)"; exit 1; }
state_set memory-id "$ID"
echo "$ID"
