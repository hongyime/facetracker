#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
command -v docker >/dev/null 2>&1 || { echo 'Docker with Compose is required.' >&2; exit 127; }
compose=(docker compose --env-file "${FACETRACKER_DEV_ENV:-.env.dev}" -f compose.dev.yaml)
action="${1:-start}"
if (( $# )); then shift; fi
case "$action" in
  start) exec "${compose[@]}" up --no-build --pull never "$@" ;;
  stop) exec "${compose[@]}" stop "$@" ;;
  logs) exec "${compose[@]}" logs --follow "$@" ;;
  status) exec "${compose[@]}" ps "$@" ;;
  build) exec "${compose[@]}" build "$@" ;;
  *) echo 'Usage: bash facetracker.sh {start|stop|logs|status|build} [Compose arguments]' >&2; exit 2 ;;
esac
