#!/usr/bin/env bash
# Crée au besoin l'instance EC2 qui sert le front (clé SSH, security group, Amazon Linux 2023),
# puis affiche son IP publique sur stdout. Relançable : réutilise ce qui existe déjà.
set -euo pipefail

NAME=bas-de-laine-front
KEY_PATH="$HOME/.ssh/$NAME.pem"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.micro}"

log() { echo "› $*" >&2; }

# Clé SSH : la partie privée ne vit que sur cette machine.
if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
  [ -e "$KEY_PATH" ] && { echo "$KEY_PATH existe mais pas la clé AWS $NAME : supprime l'un ou l'autre." >&2; exit 1; }
  log "création de la clé SSH $NAME"
  aws ec2 create-key-pair --key-name "$NAME" --key-type ed25519 --query KeyMaterial --output text > "$KEY_PATH"
  chmod 400 "$KEY_PATH"
elif [ ! -e "$KEY_PATH" ]; then
  echo "La clé AWS $NAME existe mais $KEY_PATH est introuvable." >&2
  exit 1
fi

# Security group : HTTP ouvert à tous, SSH seulement depuis l'IP de ce poste.
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$NAME" Name=vpc-id,Values="$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG_ID" = None ]; then
  log "création du security group $NAME"
  SG_ID=$(aws ec2 create-security-group --group-name "$NAME" --vpc-id "$VPC_ID" \
    --description "Bas de Laine front: HTTP public, SSH restreint" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
fi
MY_IP=$(curl -fsS https://checkip.amazonaws.com)
if ! out=$(aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$MY_IP/32" 2>&1); then
  grep -q InvalidPermission.Duplicate <<<"$out" || { echo "$out" >&2; exit 1; }
fi

# Instance : on reprend celle qui porte le tag, sinon on en lance une.
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$INSTANCE_ID" = None ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query Parameter.Value --output text)
  # Toutes les zones ne proposent pas tous les types (t3 n'existe pas en us-east-1e).
  AZ=$(aws ec2 describe-instance-type-offerings --location-type availability-zone \
    --filters Name=instance-type,Values="$INSTANCE_TYPE" --query 'InstanceTypeOfferings[0].Location' --output text)
  SUBNET_ID=$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=availability-zone,Values="$AZ" \
    Name=default-for-az,Values=true --query 'Subnets[0].SubnetId' --output text)
  log "lancement d'une $INSTANCE_TYPE en $AZ"
  INSTANCE_ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --key-name "$NAME" \
    --subnet-id "$SUBNET_ID" --security-group-ids "$SG_ID" --metadata-options HttpTokens=required \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
    --query 'Instances[0].InstanceId' --output text)
elif [ "$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].State.Name' --output text)" != running ]; then
  log "redémarrage de $INSTANCE_ID"
  aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID" 2>/dev/null || true
  aws ec2 start-instances --instance-ids "$INSTANCE_ID" >/dev/null
fi

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text
