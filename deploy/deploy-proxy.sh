#!/usr/bin/env bash
# Déploie le proxy de streaming (deploy/proxy) : Lambda monport-proxy + Function URL publique, CORS limité.
#   ./deploy/deploy-proxy.sh
# Origines CORS : deploy/state/cors-origins (une par ligne, ex. http://44.199.217.243). L'URL est écrite dans
# deploy/state/api-url, que deploy.sh et deploy-cloudfront.sh lisent.
source "$(dirname "$0")/lib.sh"

FN=monport-proxy
RUNTIME_ARN=$(state_get agents-runtime-arn)
[ -n "$RUNTIME_ARN" ] || { echo "Déploie d'abord le runtime : ./deploy/deploy-agentcore.sh" >&2; exit 1; }

TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
POLICY=$(cat <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
  "Resource":"arn:aws:logs:$REGION:$ACCOUNT:log-group:/aws/lambda/$FN:*"},
 {"Effect":"Allow","Action":["xray:PutTraceSegments","xray:PutTelemetryRecords"],"Resource":"*"},
 {"Effect":"Allow","Action":"bedrock-agentcore:InvokeAgentRuntime",
  "Resource":["$RUNTIME_ARN","$RUNTIME_ARN/*"]}
]}
EOF
)
ROLE=$(ensure_role monport-proxy-lambda "$TRUST" "$POLICY")

log "paquet du proxy"
BUILD=$(mktemp -d)
cp "$ROOT/deploy/proxy/index.mjs" "$ROOT/deploy/proxy/package.json" "$BUILD/"
(cd "$BUILD" && npm install --silent --omit=dev --no-audit --no-fund >/dev/null && zip -qr proxy.zip index.mjs package.json node_modules)

ENV="Variables={AGENT_RUNTIME_ARN=$RUNTIME_ARN}"
if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  log "mise à jour de $FN"
  aws lambda update-function-code --function-name "$FN" --zip-file "fileb://$BUILD/proxy.zip" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$FN"
  aws lambda update-function-configuration --function-name "$FN" --role "$ROLE" --environment "$ENV" \
    --timeout 900 --memory-size 256 >/dev/null
else
  log "création de $FN"
  aws lambda create-function --function-name "$FN" --runtime nodejs22.x --handler index.handler --role "$ROLE" \
    --zip-file "fileb://$BUILD/proxy.zip" --timeout 900 --memory-size 256 --architectures arm64 \
    --environment "$ENV" --tags project=monport >/dev/null
fi
aws lambda wait function-updated-v2 --function-name "$FN"
# Traçage actif : sinon la Lambda propage « Sampled=0 » et AgentCore n'enregistre aucune trace des agents.
aws lambda update-function-configuration --function-name "$FN" --tracing-config Mode=Active >/dev/null
aws lambda wait function-updated-v2 --function-name "$FN"
# Plafond de requêtes simultanées : remplace la limite de débit de nginx et borne la facture Bedrock.
aws lambda put-function-concurrency --function-name "$FN" --reserved-concurrent-executions 8 >/dev/null

ORIGINS=$(state_get cors-origins | sed '/^$/d' | python3 -c 'import json,sys; print(json.dumps([l.strip() for l in sys.stdin]))')
[ "$ORIGINS" != "[]" ] || ORIGINS='["http://localhost:5173"]'
CORS="{\"AllowOrigins\":$ORIGINS,\"AllowMethods\":[\"POST\"],\"AllowHeaders\":[\"content-type\",\"x-session-id\"],\"MaxAge\":300}"
if aws lambda get-function-url-config --function-name "$FN" >/dev/null 2>&1; then
  aws lambda update-function-url-config --function-name "$FN" --auth-type NONE --invoke-mode RESPONSE_STREAM --cors "$CORS" >/dev/null
else
  aws lambda create-function-url-config --function-name "$FN" --auth-type NONE --invoke-mode RESPONSE_STREAM --cors "$CORS" >/dev/null
  aws lambda add-permission --function-name "$FN" --statement-id public-url --action lambda:InvokeFunctionUrl \
    --principal '*' --function-url-auth-type NONE >/dev/null
fi
# Lambda exige aussi lambda:InvokeFunction, limité ici aux appels passés par l'URL (pas d'appel direct à l'API Invoke).
# La CLI installée n'expose pas InvokedViaFunctionUrl : on passe par boto3.
if ! aws lambda get-policy --function-name "$FN" --query Policy --output text 2>/dev/null | grep -q public-url-invoke; then
  python3 - "$FN" <<'EOF'
import sys, boto3
boto3.client("lambda").add_permission(FunctionName=sys.argv[1], StatementId="public-url-invoke",
    Action="lambda:InvokeFunction", Principal="*", InvokedViaFunctionUrl=True)
EOF
fi
URL=$(aws lambda get-function-url-config --function-name "$FN" --query FunctionUrl --output text)
state_set api-url "$URL"
rm -rf "$BUILD"
log "CORS : $ORIGINS"
echo "$URL"
