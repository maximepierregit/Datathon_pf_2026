#!/usr/bin/env bash
# Publie le backend des agents sur l'EC2 du front, derrière nginx (/api/) : ./deploy/deploy-backend.sh
#
# Le compte Workshop interdit de créer un rôle IAM, donc ni AgentCore Runtime ni Lambda. L'EC2 appelle Bedrock
# avec le profil d'instance du participant, à attacher une fois à la main (voir CLAUDE.md, section Commandes) :
# ce script ne le fait pas, il vérifie seulement qu'il est là.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_PATH="$HOME/.ssh/bas-de-laine-front.pem"
APP=/opt/monport-backend

HOST=$("$ROOT/deploy/provision.sh")
INSTANCE_ID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=bas-de-laine-front Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
PROFILE=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].IamInstanceProfile.Arn' --output text)
if [ "$PROFILE" = None ]; then
  echo "L'instance $INSTANCE_ID n'a pas de profil IAM : le backend ne pourrait pas appeler Bedrock." >&2
  echo "Attache-le d'abord (commande dans CLAUDE.md, section Commandes), puis relance ce script." >&2
  exit 1
fi

SSH_OPTS="-i $KEY_PATH -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$HOME/.ssh/bas-de-laine-front.known_hosts -o ConnectTimeout=10"
remote() { ssh $SSH_OPTS "ec2-user@$HOST" "$@"; }

# Le dataset est lu depuis S3 (MONPORT_UNIVERSE_PARQUET_URI dans monport-backend.service) : rien à envoyer, on vérifie seulement
# qu'il est publié. Pour le mettre à jour : python data-prep/build_universe.py --upload s3://monport-datasets-381491955506
DATASET_URI=$(sed -n 's/^Environment=MONPORT_UNIVERSE_PARQUET_URI=//p' "$ROOT/deploy/monport-backend.service")
if ! aws s3api head-object --bucket "$(cut -d/ -f3 <<<"$DATASET_URI")" --key "$(cut -d/ -f4- <<<"$DATASET_URI")" >/dev/null; then
  echo "Dataset introuvable ou illisible : $DATASET_URI" >&2
  exit 1
fi

echo "› préparation du serveur" >&2
remote "set -e
  # 1 Go de mémoire : un fichier d'échange évite que pip échoue en installant pandas et scipy.
  if ! swapon --show | grep -q /swapfile; then
    [ -f /swapfile ] || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
    sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
    grep -q /swapfile /etc/fstab || echo '/swapfile none swap defaults 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
  rpm -q python3.12 rsync >/dev/null || sudo dnf install -y -q python3.12 python3.12-pip rsync
  sudo mkdir -p $APP && sudo chown ec2-user: $APP"

echo "› envoi du backend" >&2
rsync -az --delete --exclude .venv --exclude build --exclude __pycache__ --exclude '*.egg-info' --exclude .env \
  --exclude /data/ \
  -e "ssh $SSH_OPTS" "$ROOT/backend/" "ec2-user@$HOST:$APP/"

echo "› installation des dépendances (quelques minutes la première fois)" >&2
remote "set -e; cd $APP
  [ -d .venv ] || python3.12 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ."

echo "› service" >&2
rsync -az -e "ssh $SSH_OPTS" "$ROOT/deploy/monport-backend.service" "ec2-user@$HOST:/tmp/monport-backend.service"
remote "sudo install -m 644 /tmp/monport-backend.service /etc/systemd/system/monport-backend.service
  sudo systemctl daemon-reload && sudo systemctl enable -q monport-backend && sudo systemctl restart monport-backend
  for _ in \$(seq 1 30); do curl -fsS localhost:8091/ping >/dev/null 2>&1 && break; sleep 1; done
  curl -fsS localhost:8091/ping >/dev/null || { sudo journalctl -u monport-backend -n 30 --no-pager; exit 1; }"

echo "Backend en ligne derrière http://$HOST/api/ (redéploie le front avec ./deploy/deploy.sh pour la conf nginx)."
