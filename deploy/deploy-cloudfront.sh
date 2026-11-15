#!/usr/bin/env bash
# Front en HTTPS sur S3 + CloudFront + WAF, en parallèle de l'EC2 : ./deploy/deploy-cloudfront.sh
#
#   /*      → bucket privé monport-front-<compte>, lu par CloudFront seulement (OAC)
#   /api/*  → Function URL du proxy (deploy/state/api-url), sans cache : même origine pour le navigateur, sans CORS
#   WAF     → limite de débit sur /api/ et règles gérées AWS (corps de plus de 8 ko tolérés pour le questionnaire)
# Écrit deploy/state/cloudfront-{id,domain} et ajoute https://<domaine> aux origines CORS du proxy.
# FRONT_ONLY=1 republie seulement le build (et invalide le cache).
source "$(dirname "$0")/lib.sh"

FRONT_BUCKET="monport-front-$ACCOUNT"
API_URL=$(state_get api-url)
[ -n "$API_URL" ] || { echo "Déploie d'abord le proxy : ./deploy/deploy-proxy.sh" >&2; exit 1; }
API_HOST=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).hostname)' "$API_URL")

log "build du front (API en même origine : /api/invocations)"
(cd "$ROOT/frontend" && VITE_API_URL="" npm run build >/dev/null)

if [ "${FRONT_ONLY:-0}" != 1 ]; then
  # Bucket privé, chiffré, accès public bloqué
  if ! aws s3api head-bucket --bucket "$FRONT_BUCKET" 2>/dev/null; then
    log "création du bucket $FRONT_BUCKET"
    aws s3api create-bucket --bucket "$FRONT_BUCKET" >/dev/null
    aws s3api put-public-access-block --bucket "$FRONT_BUCKET" --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    aws s3api put-bucket-tagging --bucket "$FRONT_BUCKET" --tagging 'TagSet=[{Key=project,Value=monport}]'
  fi

  # WAF (portée CLOUDFRONT : toujours en us-east-1)
  WAF_NAME=monport-front
  # SearchString en base64 (exigé par la CLI en JSON) : L2FwaS8= vaut « /api/ »
  WAF_RULES=$(cat <<'EOF'
[
 {"Name":"api-rate-limit","Priority":0,"Action":{"Block":{"CustomResponse":{"ResponseCode":429}}},
  "Statement":{"RateBasedStatement":{"Limit":20,"EvaluationWindowSec":60,"AggregateKeyType":"IP",
   "ScopeDownStatement":{"ByteMatchStatement":{"SearchString":"L2FwaS8=","FieldToMatch":{"UriPath":{}},
    "TextTransformations":[{"Priority":0,"Type":"NONE"}],"PositionalConstraint":"STARTS_WITH"}}}},
  "VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"api-rate-limit"}},
 {"Name":"aws-ip-reputation","Priority":1,"OverrideAction":{"None":{}},
  "Statement":{"ManagedRuleGroupStatement":{"VendorName":"AWS","Name":"AWSManagedRulesAmazonIpReputationList"}},
  "VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"aws-ip-reputation"}},
 {"Name":"aws-common","Priority":2,"OverrideAction":{"None":{}},
  "Statement":{"ManagedRuleGroupStatement":{"VendorName":"AWS","Name":"AWSManagedRulesCommonRuleSet",
   "RuleActionOverrides":[{"Name":"SizeRestrictions_BODY","ActionToUse":{"Count":{}}}]}},
  "VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"aws-common"}}
]
EOF
)
  VIS='SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName=monport-front'
  WAF_LINE=$(aws wafv2 list-web-acls --scope CLOUDFRONT --region us-east-1 \
    --query "WebACLs[?Name=='$WAF_NAME'].[Id,LockToken,ARN] | [0]" --output text)
  if [ "$WAF_LINE" = None ] || [ -z "$WAF_LINE" ]; then
    log "création du WebACL $WAF_NAME"
    WAF_ARN=$(aws wafv2 create-web-acl --name "$WAF_NAME" --scope CLOUDFRONT --region us-east-1 --default-action Allow={} \
      --rules "$WAF_RULES" --visibility-config "$VIS" --tags Key=project,Value=monport --query Summary.ARN --output text)
  else
    read -r WAF_ID WAF_TOKEN WAF_ARN <<<"$WAF_LINE"
    log "mise à jour du WebACL $WAF_NAME"
    aws wafv2 update-web-acl --name "$WAF_NAME" --scope CLOUDFRONT --region us-east-1 --id "$WAF_ID" --lock-token "$WAF_TOKEN" \
      --default-action Allow={} --rules "$WAF_RULES" --visibility-config "$VIS" >/dev/null
  fi

  # Contrôle d'accès d'origine (OAC) pour le bucket
  OAC_ID=$(aws cloudfront list-origin-access-controls --query "OriginAccessControlList.Items[?Name=='monport-front'].Id | [0]" --output text)
  if [ "$OAC_ID" = None ] || [ -z "$OAC_ID" ]; then
    OAC_ID=$(aws cloudfront create-origin-access-control --origin-access-control-config \
      Name=monport-front,SigningProtocol=sigv4,SigningBehavior=always,OriginAccessControlOriginType=s3 \
      --query OriginAccessControl.Id --output text)
  fi

  DIST_ID=$(state_get cloudfront-id)
  CONFIG=$(python3 - "$FRONT_BUCKET" "$REGION" "$OAC_ID" "$API_HOST" "$WAF_ARN" "$(date +%s)" <<'EOF'
import json, sys
bucket, region, oac, api_host, waf, ref = sys.argv[1:]
CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"
CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
ALL_VIEWER_EXCEPT_HOST = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
SECURITY_HEADERS = "67f7725c-6f97-4210-82d7-5512b31e9d03"
s3_origin = f"s3-{bucket}"
cfg = {
    "CallerReference": f"monport-front-{ref}",
    "Comment": "monport-front",
    "Enabled": True,
    "DefaultRootObject": "index.html",
    "HttpVersion": "http2and3",
    "PriceClass": "PriceClass_100",
    "WebACLId": waf,
    "Origins": {"Quantity": 2, "Items": [
        {"Id": s3_origin, "DomainName": f"{bucket}.s3.{region}.amazonaws.com", "OriginAccessControlId": oac,
         "S3OriginConfig": {"OriginAccessIdentity": ""}},
        {"Id": "api-proxy", "DomainName": api_host,
         "CustomOriginConfig": {"HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": "https-only",
                                "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                                "OriginReadTimeout": 60, "OriginKeepaliveTimeout": 60}},
    ]},
    "DefaultCacheBehavior": {
        "TargetOriginId": s3_origin, "ViewerProtocolPolicy": "redirect-to-https", "Compress": True,
        "CachePolicyId": CACHING_OPTIMIZED, "ResponseHeadersPolicyId": SECURITY_HEADERS,
        "AllowedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"], "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
    },
    "CacheBehaviors": {"Quantity": 1, "Items": [{
        "PathPattern": "/api/*", "TargetOriginId": "api-proxy", "ViewerProtocolPolicy": "https-only", "Compress": False,
        "CachePolicyId": CACHING_DISABLED, "OriginRequestPolicyId": ALL_VIEWER_EXCEPT_HOST,
        "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                           "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
    }]},
    # Application à une page: les routes du front (/portefeuille, /profil/2...) servent index.html
    "CustomErrorResponses": {"Quantity": 2, "Items": [
        {"ErrorCode": 403, "ResponsePagePath": "/index.html", "ResponseCode": "200", "ErrorCachingMinTTL": 0},
        {"ErrorCode": 404, "ResponsePagePath": "/index.html", "ResponseCode": "200", "ErrorCachingMinTTL": 0},
    ]},
    "ViewerCertificate": {"CloudFrontDefaultCertificate": True},
}
print(json.dumps(cfg))
EOF
)
  if [ -z "$DIST_ID" ]; then
    log "création de la distribution CloudFront (10 à 15 min avant d'être en ligne)"
    DIST_ID=$(aws cloudfront create-distribution --distribution-config "$CONFIG" --query Distribution.Id --output text)
    state_set cloudfront-id "$DIST_ID"
  else
    log "mise à jour de la distribution $DIST_ID"
    ETAG=$(aws cloudfront get-distribution-config --id "$DIST_ID" --query ETag --output text)
    OLD_REF=$(aws cloudfront get-distribution-config --id "$DIST_ID" --query DistributionConfig.CallerReference --output text)
    CONFIG=$(python3 -c 'import json,sys; c=json.loads(sys.argv[1]); c["CallerReference"]=sys.argv[2]; print(json.dumps(c))' "$CONFIG" "$OLD_REF")
    aws cloudfront update-distribution --id "$DIST_ID" --if-match "$ETAG" --distribution-config "$CONFIG" >/dev/null
  fi
  DOMAIN=$(aws cloudfront get-distribution --id "$DIST_ID" --query Distribution.DomainName --output text)
  state_set cloudfront-domain "$DOMAIN"

  # Le bucket n'accepte que cette distribution
  aws s3api put-bucket-policy --bucket "$FRONT_BUCKET" --policy "$(cat <<EOF
{"Version":"2012-10-17","Statement":[
 {"Sid":"CloudFrontOnly","Effect":"Allow","Principal":{"Service":"cloudfront.amazonaws.com"},"Action":"s3:GetObject",
  "Resource":"arn:aws:s3:::$FRONT_BUCKET/*",
  "Condition":{"StringEquals":{"AWS:SourceArn":"arn:aws:cloudfront::$ACCOUNT:distribution/$DIST_ID"}}},
 {"Sid":"TLSOnly","Effect":"Deny","Principal":"*","Action":"s3:*",
  "Resource":["arn:aws:s3:::$FRONT_BUCKET","arn:aws:s3:::$FRONT_BUCKET/*"],"Condition":{"Bool":{"aws:SecureTransport":"false"}}}
]}
EOF
)"
  # Origine CORS ajoutée au proxy (utile seulement si un front appelle la Function URL directement)
  if ! grep -qx "https://$DOMAIN" "$STATE/cors-origins" 2>/dev/null; then
    echo "https://$DOMAIN" >> "$STATE/cors-origins"
    "$ROOT/deploy/deploy-proxy.sh" >/dev/null
  fi
fi

DIST_ID=$(state_get cloudfront-id); DOMAIN=$(state_get cloudfront-domain)
log "envoi du build vers s3://$FRONT_BUCKET"
# Fichiers à empreinte : cache d'un an ; index.html : jamais en cache, pour voir chaque nouveau déploiement
aws s3 sync "$ROOT/frontend/dist/" "s3://$FRONT_BUCKET/" --delete --exclude index.html \
  --cache-control "public, max-age=31536000, immutable" --only-show-errors
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$FRONT_BUCKET/index.html" --cache-control "no-cache" --only-show-errors
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/index.html" >/dev/null
echo "https://$DOMAIN"
