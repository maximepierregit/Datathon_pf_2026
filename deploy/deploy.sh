#!/usr/bin/env bash
# Build le front et le publie sur l'EC2 : ./deploy/deploy.sh
# Au premier lancement, provision.sh crée l'instance et deploy.sh y installe nginx.
#
# API : le front appelle la Function URL du proxy AgentCore (deploy/state/api-url). USE_EC2_BACKEND=1 garde l'ancien
# backend de l'EC2 (/api/ servi par nginx) : c'est le retour en arrière.
# Transport : SSH si la clé ~/.ssh/bas-de-laine-front.pem est là, sinon S3 + SSM Run Command (profil d'instance requis).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_PATH="$HOME/.ssh/bas-de-laine-front.pem"
WEB_ROOT=/var/www/bas-de-laine
export AWS_REGION="${AWS_REGION:-us-east-1}"

API_URL=""
if [ "${USE_EC2_BACKEND:-0}" != 1 ] && [ -f "$ROOT/deploy/state/api-url" ]; then API_URL=$(cat "$ROOT/deploy/state/api-url"); fi
echo "› build (API : ${API_URL:-backend de l’EC2 sous /api/})" >&2
(cd "$ROOT/frontend" && VITE_API_URL="$API_URL" npm run build)

if [ ! -e "$KEY_PATH" ]; then
  echo "› pas de clé SSH : publication par S3 + SSM" >&2
  INSTANCE_ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=bas-de-laine-front Name=instance-state-name,Values=running \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)
  [ "$INSTANCE_ID" != None ] || { echo "Instance bas-de-laine-front introuvable ou arrêtée." >&2; exit 1; }
  HOST=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
  BUCKET="monport-datasets-$(aws sts get-caller-identity --query Account --output text)"
  KEY="deploy/front-$(date +%Y%m%d-%H%M%S).tgz"
  tar -C "$ROOT/frontend/dist" -czf /tmp/monport-front.tgz . && aws s3 cp --quiet /tmp/monport-front.tgz "s3://$BUCKET/$KEY"
  aws s3 cp --quiet "$ROOT/deploy/nginx.conf" "s3://$BUCKET/deploy/nginx.conf"
  SCRIPT="set -e
rpm -q nginx >/dev/null || dnf install -y -q nginx
mkdir -p $WEB_ROOT && aws s3 cp --region $AWS_REGION s3://$BUCKET/$KEY /tmp/front.tgz
rm -rf $WEB_ROOT.new && mkdir $WEB_ROOT.new && tar -xzf /tmp/front.tgz -C $WEB_ROOT.new
rm -rf $WEB_ROOT.old && mv $WEB_ROOT $WEB_ROOT.old && mv $WEB_ROOT.new $WEB_ROOT && chown -R ec2-user: $WEB_ROOT
aws s3 cp --region $AWS_REGION s3://$BUCKET/deploy/nginx.conf /etc/nginx/conf.d/bas-de-laine.conf
sed -i 's/ default_server//' /etc/nginx/nginx.conf
nginx -t -q && systemctl enable --now nginx && systemctl reload nginx"
  printf '%s' "$SCRIPT" | python3 -c 'import json, sys; print(json.dumps({"commands": [sys.stdin.read()]}))' > /tmp/monport-ssm.json
  CMD=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
    --parameters file:///tmp/monport-ssm.json --query Command.CommandId --output text)
  aws ssm wait command-executed --command-id "$CMD" --instance-id "$INSTANCE_ID" || {
    aws ssm get-command-invocation --command-id "$CMD" --instance-id "$INSTANCE_ID" --query StandardErrorContent --output text >&2
    exit 1
  }
  echo "En ligne : http://$HOST"
  exit 0
fi

HOST=$("$ROOT/deploy/provision.sh")
SSH_OPTS="-i $KEY_PATH -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$HOME/.ssh/bas-de-laine-front.known_hosts -o ConnectTimeout=10"
remote() { ssh $SSH_OPTS "ec2-user@$HOST" "$@"; }

# Une instance qui vient de démarrer met une minute environ à accepter SSH.
echo "› attente de SSH sur $HOST" >&2
for _ in $(seq 1 36); do remote true 2>/dev/null && break; sleep 5; done
remote true

echo "› préparation du serveur" >&2
remote "rpm -q nginx rsync >/dev/null || sudo dnf install -y -q nginx rsync
  sudo mkdir -p $WEB_ROOT && sudo chown ec2-user: $WEB_ROOT
  # Notre conf prend le rôle de serveur par défaut à la place de celle livrée avec nginx.
  sudo sed -i 's/ default_server//' /etc/nginx/nginx.conf
  sudo systemctl enable --now nginx"

echo "› envoi du build" >&2
rsync -az --delete -e "ssh $SSH_OPTS" "$ROOT/frontend/dist/" "ec2-user@$HOST:$WEB_ROOT/"
rsync -az -e "ssh $SSH_OPTS" "$ROOT/deploy/nginx.conf" "ec2-user@$HOST:/tmp/bas-de-laine.conf"
remote "sudo install -m 644 /tmp/bas-de-laine.conf /etc/nginx/conf.d/bas-de-laine.conf && sudo nginx -t -q && sudo systemctl reload nginx"

echo "En ligne : http://$HOST"
