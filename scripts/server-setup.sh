#!/usr/bin/env bash
# One-time setup of the EC2 server (Ubuntu 22.04 / 24.04). Run as the default `ubuntu` user:
#     bash server-setup.sh
# Safe to re-run. Installs Docker + Compose, adds swap, locks the firewall to SSH + HTTP,
# turns on automatic security updates, and creates /opt/vani for the app.
set -euo pipefail

APP_DIR=/opt/vani
SWAP_GB=4

echo "==> Packages and automatic security updates"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl rsync ufw unattended-upgrades
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Docker Engine + Compose plugin"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

echo "==> ${SWAP_GB} GB swap (ffmpeg renders + builds can spike past 8 GB RAM briefly)"
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l "${SWAP_GB}G" /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi
sudo sysctl -w vm.swappiness=10 >/dev/null
grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf

echo "==> Firewall: only SSH (22) and HTTP (80) in. App ports stay on Docker's private network."
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw --force enable

echo "==> App folder ${APP_DIR}"
sudo mkdir -p "$APP_DIR"
sudo chown "$USER":"$USER" "$APP_DIR"

echo
echo "Done. Next:"
echo "  1. Log out and back in (so your user can run docker without sudo)."
echo "  2. Copy your .env to ${APP_DIR}/.env (see README > Deploying to AWS)."
echo "  3. Push to main: GitHub Actions deploys the app here."
