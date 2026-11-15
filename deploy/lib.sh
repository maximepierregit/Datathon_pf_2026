#!/usr/bin/env bash
# Fonctions communes des scripts de déploiement AWS (sourcé, pas exécuté).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AWS_REGION="${AWS_REGION:-us-east-1}"
REGION="$AWS_REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="monport-datasets-$ACCOUNT"
STATE="$ROOT/deploy/state"  # identifiants des ressources créées (ARN, URL), versionnés pour toute l'équipe
mkdir -p "$STATE"

log() { echo "› $*" >&2; }

# Remplace ${ACCOUNT} et ${REGION} (et les variables passées en plus) dans un modèle JSON.
render() {
  local file=$1; shift
  local out; out="$(sed -e "s/\${ACCOUNT}/$ACCOUNT/g" -e "s/\${REGION}/$REGION/g" "$file")"
  while [ $# -gt 0 ]; do out="${out//\$\{$1\}/$2}"; shift 2; done
  printf '%s' "$out"
}

# Crée le rôle s'il manque, puis remplace sa politique en ligne. Affiche l'ARN.
ensure_role() {
  local name=$1 trust=$2 policy=$3
  if ! aws iam get-role --role-name "$name" >/dev/null 2>&1; then
    log "création du rôle $name"
    aws iam create-role --role-name "$name" --assume-role-policy-document "$trust" \
      --tags Key=project,Value=monport >/dev/null
    sleep 10  # propagation IAM
  else
    aws iam update-assume-role-policy --role-name "$name" --policy-document "$trust"
  fi
  aws iam put-role-policy --role-name "$name" --policy-name "$name" --policy-document "$policy"
  aws iam get-role --role-name "$name" --query Role.Arn --output text
}

# Écrit ou lit une valeur d'état (deploy/state/<clé>).
state_set() { printf '%s\n' "$2" > "$STATE/$1"; }
state_get() { [ -f "$STATE/$1" ] && cat "$STATE/$1" || true; }

# Crée ou met à jour un runtime AgentCore (déploiement par code, zip dans S3). Affiche l'ARN une fois READY.
#   deploy_runtime <nom> <zip> <role_arn> <env_json> [protocol_json]
# Le point d'entrée passe par opentelemetry-instrument (ADOT) : traces des agents et des outils dans CloudWatch.
deploy_runtime() {
  local name=$1 zip=$2 role=$3 env=$4 protocol=${5:-}
  local key="code/$name/$(date +%Y%m%d-%H%M%S).zip"
  log "envoi de $zip vers s3://$BUCKET/$key"
  local version
  version=$(aws s3api put-object --bucket "$BUCKET" --key "$key" --body "$zip" --query VersionId --output text)
  local artifact
  artifact=$(printf '{"codeConfiguration":{"code":{"s3":{"bucket":"%s","prefix":"%s","versionId":"%s"}},"runtime":"PYTHON_3_13","entryPoint":["opentelemetry-instrument","main.py"]}}' \
    "$BUCKET" "$key" "$version")
  local args=(--agent-runtime-artifact "$artifact" --role-arn "$role" --network-configuration networkMode=PUBLIC
    --environment-variables "$env" --lifecycle-configuration idleRuntimeSessionTimeout=3600,maxLifetime=28800)
  [ -n "$protocol" ] && args+=(--protocol-configuration "$protocol")

  local id
  id=$(aws bedrock-agentcore-control list-agent-runtimes \
    --query "agentRuntimes[?agentRuntimeName=='$name'].agentRuntimeId | [0]" --output text)
  if [ "$id" = None ] || [ -z "$id" ]; then
    log "création du runtime $name"
    id=$(aws bedrock-agentcore-control create-agent-runtime --agent-runtime-name "$name" "${args[@]}" \
      --query agentRuntimeId --output text)
  else
    log "mise à jour du runtime $name ($id)"
    aws bedrock-agentcore-control update-agent-runtime --agent-runtime-id "$id" "${args[@]}" >/dev/null
  fi

  local status
  for _ in $(seq 1 90); do
    status=$(aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$id" --query status --output text)
    case "$status" in
      READY) break ;;
      *FAILED) aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$id" --query failureReason --output text >&2
               return 1 ;;
    esac
    sleep 10
  done
  [ "$status" = READY ] || { log "runtime $name pas prêt ($status)"; return 1; }
  aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$id" --query agentRuntimeArn --output text
}
