#!/usr/bin/env bash
# Supprime les ressources AWS de MonPort après l'événement : ./deploy/teardown.sh
# Affiche d'abord la liste, puis demande de taper « supprimer ». Le bucket du dataset et l'EC2 ne sont pas touchés
# (l'EC2 : voir CLAUDE.md, profil IAM à détacher puis instance à arrêter ou résilier).
source "$(dirname "$0")/lib.sh"

AGENTS=$(state_get agents-runtime-arn); TOOLS=$(state_get tools-runtime-arn); GW=$(state_get gateway-id)
MEM=$(state_get memory-id); GR=$(state_get guardrail-id); CF=$(state_get cloudfront-id)
cat >&2 <<EOF
Ressources à supprimer :
  runtimes AgentCore : ${AGENTS:-–} ${TOOLS:-–}
  Gateway            : ${GW:-–}
  mémoire            : ${MEM:-–}
  guardrail          : ${GR:-–}
  Lambda             : monport-proxy
  CloudFront + WAF   : ${CF:-–} / monport-front, bucket monport-front-$ACCOUNT
  rôles IAM          : monport-agents-runtime monport-tools-runtime monport-gateway monport-proxy-lambda
EOF
read -r -p "Tape « supprimer » pour confirmer : " ANSWER
[ "$ANSWER" = supprimer ] || { echo "Annulé."; exit 1; }

ok() { "$@" >/dev/null 2>&1 || log "déjà absent ou en échec : $*"; }

if [ -n "$GW" ]; then
  for T in $(aws bedrock-agentcore-control list-gateway-targets --gateway-identifier "$GW" --query 'items[].targetId' --output text); do
    ok aws bedrock-agentcore-control delete-gateway-target --gateway-identifier "$GW" --target-id "$T"
  done
  sleep 10; ok aws bedrock-agentcore-control delete-gateway --gateway-identifier "$GW"
fi
for ARN in $AGENTS $TOOLS; do ok aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id "${ARN##*/}"; done
[ -n "$MEM" ] && ok aws bedrock-agentcore-control delete-memory --memory-id "$MEM"
[ -n "$GR" ] && ok aws bedrock delete-guardrail --guardrail-identifier "$GR"
ok aws lambda delete-function --function-name monport-proxy

if [ -n "$CF" ]; then
  ETAG=$(aws cloudfront get-distribution-config --id "$CF" --query ETag --output text)
  CFG=$(aws cloudfront get-distribution-config --id "$CF" --query DistributionConfig --output json \
    | python3 -c 'import json,sys; c=json.load(sys.stdin); c["Enabled"]=False; c["WebACLId"]=""; print(json.dumps(c))')
  ok aws cloudfront update-distribution --id "$CF" --if-match "$ETAG" --distribution-config "$CFG"
  log "désactivation de CloudFront (10 à 15 min)"
  aws cloudfront wait distribution-deployed --id "$CF"
  ok aws cloudfront delete-distribution --id "$CF" --if-match "$(aws cloudfront get-distribution-config --id "$CF" --query ETag --output text)"
fi
WAF=$(aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 --query "WebACLs[?Name=='monport-front'].[Id,LockToken] | [0]" --output text)
if [ "$WAF" != None ] && [ -n "$WAF" ]; then
  read -r WID WTOK <<<"$WAF"; ok aws wafv2 delete-web-acl --name monport-front --scope CLOUDFRONT --region us-east-1 --id "$WID" --lock-token "$WTOK"
fi
ok aws s3 rb "s3://monport-front-$ACCOUNT" --force

for R in monport-agents-runtime monport-tools-runtime monport-gateway monport-proxy-lambda; do
  ok aws iam delete-role-policy --role-name "$R" --policy-name "$R"; ok aws iam delete-role --role-name "$R"
done
rm -f "$STATE"/{agents-runtime-arn,tools-runtime-arn,gateway-id,gateway-url,memory-id,guardrail-id,guardrail-version,cloudfront-id,cloudfront-domain,api-url}
echo "Terminé. Le code des runtimes reste dans s3://$BUCKET/code/ (à vider à la main si besoin)."
