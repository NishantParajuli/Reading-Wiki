#!/usr/bin/env bash
# One-time installer for the current production laptop.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
UNIT_DIR="${HOME}/.config/systemd/user"
STATE_DIR="${HOME}/.local/share/tideglass-deploy"
STATE_FILE="${STATE_DIR}/last-deployed-sha"
REPOSITORY_URL="https://github.com/NishantParajuli/Reading-Wiki.git"

mkdir -p "${BIN_DIR}" "${UNIT_DIR}" "${STATE_DIR}"
install -m 0755 "${ROOT_DIR}/deploy/tideglass-deploy-agent" "${BIN_DIR}/tideglass-deploy-agent"
install -m 0644 "${ROOT_DIR}/deploy/tideglass-deploy.service" "${UNIT_DIR}/tideglass-deploy.service"
install -m 0644 "${ROOT_DIR}/deploy/tideglass-deploy.timer" "${UNIT_DIR}/tideglass-deploy.timer"

# The currently running image predates revision labels. Seed the current main SHA once so
# installation never causes an unexpected redeploy; only a later successful main commit does.
if [[ ! -f "${STATE_FILE}" ]]; then
  current_main="$(git ls-remote "${REPOSITORY_URL}" refs/heads/main | awk 'NR == 1 {print $1}')"
  [[ "${current_main}" =~ ^[0-9a-f]{40}$ ]]
  printf '%s\n' "${current_main}" > "${STATE_FILE}"
  printf 'Seeded deployment state with current main: %s\n' "${current_main}"
fi

systemctl --user daemon-reload
systemctl --user enable --now tideglass-deploy.timer

printf 'Installed the Tideglass deploy agent.\n'
printf 'Timer status: systemctl --user status tideglass-deploy.timer\n'
printf 'Deployment logs: journalctl --user -u tideglass-deploy.service -f\n'

if [[ "$(loginctl show-user "${USER}" --property=Linger --value 2>/dev/null || true)" != "yes" ]]; then
  printf 'To deploy after reboot even before login, run: sudo loginctl enable-linger %s\n' "${USER}"
fi
