#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hyeonbin/hotdeal_bot"
UNIT_DIR="${HOME}/.config/systemd/user"

mkdir -p "${UNIT_DIR}"
cp "${ROOT}"/systemd/* "${UNIT_DIR}/"
systemctl --user daemon-reload
systemctl --user enable --now hotdeal-discovery.timer
systemctl --user enable --now hotdeal-tracker.timer
systemctl --user enable --now hotdeal-nightly.timer
systemctl --user enable --now hotdeal-chatcmd.timer
echo "installed timers:"
systemctl --user list-timers | grep hotdeal || true
