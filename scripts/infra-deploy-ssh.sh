#!/bin/sh
set -eu

sha=${SSH_ORIGINAL_COMMAND-}
case "$sha" in
  *[!0123456789abcdef]*)
    echo "Ожидается один 40-символьный SHA коммита." >&2
    exit 2
    ;;
esac

if [ "${#sha}" -ne 40 ]; then
  echo "Ожидается один 40-символьный SHA коммита." >&2
  exit 2
fi

exec /usr/bin/sudo -n /usr/local/sbin/swarmhouse-infra-deploy "$sha"
