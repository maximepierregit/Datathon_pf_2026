#!/usr/bin/env bash
# Build le front et le publie sur l'EC2 : ./deploy/deploy.sh
# Au premier lancement, provision.sh crée l'instance et deploy.sh y installe nginx.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_PATH="$HOME/.ssh/bas-de-laine-front.pem"
WEB_ROOT=/var/www/bas-de-laine

HOST=$("$ROOT/deploy/provision.sh")
SSH_OPTS="-i $KEY_PATH -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$HOME/.ssh/bas-de-laine-front.known_hosts -o ConnectTimeout=10"
remote() { ssh $SSH_OPTS "ec2-user@$HOST" "$@"; }

echo "› build" >&2
(cd "$ROOT/frontend" && npm run build)

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
