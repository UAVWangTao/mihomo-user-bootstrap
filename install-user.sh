#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${HOME}/.local/share/mihomo-user-bootstrap"
SCRIPT_ROOT="${INSTALL_ROOT}/scripts"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${HOME}/.config/mihomo"

mkdir -p "${SCRIPT_ROOT}" "${SYSTEMD_USER_DIR}" "${CONFIG_DIR}"

install -m 755 "${PROJECT_DIR}/scripts/update_mihomo_subscription.py" "${SCRIPT_ROOT}/update_mihomo_subscription.py"
install -m 755 "${PROJECT_DIR}/scripts/update_mihomo_geodata.py" "${SCRIPT_ROOT}/update_mihomo_geodata.py"

if [[ ! -f "${CONFIG_DIR}/override.yaml" ]]; then
  install -m 644 "${PROJECT_DIR}/config/override.yaml" "${CONFIG_DIR}/override.yaml"
fi

if [[ ! -f "${CONFIG_DIR}/subscription.env" ]]; then
  sed "s|__HOME__|${HOME}|g" "${PROJECT_DIR}/env/subscription.env.example" > "${CONFIG_DIR}/subscription.env"
  chmod 600 "${CONFIG_DIR}/subscription.env"
fi

if [[ ! -f "${CONFIG_DIR}/geodata.env" ]]; then
  sed "s|__HOME__|${HOME}|g" "${PROJECT_DIR}/env/geodata.env.example" > "${CONFIG_DIR}/geodata.env"
  chmod 600 "${CONFIG_DIR}/geodata.env"
fi

install -m 644 "${PROJECT_DIR}/systemd-user/mihomo-subscription-update.service" "${SYSTEMD_USER_DIR}/mihomo-subscription-update.service"
install -m 644 "${PROJECT_DIR}/systemd-user/mihomo-subscription-update.timer" "${SYSTEMD_USER_DIR}/mihomo-subscription-update.timer"
install -m 644 "${PROJECT_DIR}/systemd-user/mihomo-geodata-update.service" "${SYSTEMD_USER_DIR}/mihomo-geodata-update.service"
install -m 644 "${PROJECT_DIR}/systemd-user/mihomo-geodata-update.timer" "${SYSTEMD_USER_DIR}/mihomo-geodata-update.timer"

systemctl --user daemon-reload

cat <<EOF
Installed Mihomo user bootstrap files.

Next steps:
  1. Edit ${CONFIG_DIR}/subscription.env
  2. Edit ${CONFIG_DIR}/geodata.env
  3. Edit ${CONFIG_DIR}/override.yaml
  4. Enable timers:
     systemctl --user enable --now mihomo-subscription-update.timer
     systemctl --user enable --now mihomo-geodata-update.timer
EOF
