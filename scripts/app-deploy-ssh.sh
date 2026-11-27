#!/usr/bin/env bash
set -euo pipefail

version="${SSH_ORIGINAL_COMMAND:-}"
if [[ "$version" != rollback && ! "$version" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo 'Expected rollback or a stable version tag in vMAJOR.MINOR.PATCH format.' >&2
  exit 2
fi
exec /usr/bin/sudo -n /usr/local/sbin/swarmhouse-app-deploy "$version"
