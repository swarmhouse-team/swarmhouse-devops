#!/usr/bin/env bash
set -euo pipefail
umask 077

app_dir="${1:?Set the application directory}"
state_dir="${2:?Set the application state directory}"
requested_version="${3:-}"
cd "$app_dir"

exec 9>"$state_dir/deploy.lock"
flock 9

# A successful bootstrap is recorded before updating .env so it can be resumed.
journal="$state_dir/deployed-versions"
schema_allow="$state_dir/schema-allow"
current="$(sed -n 's/^APP_VERSION=//p' .env)"

save_version() {
  local tmp
  tmp="$(mktemp .env.XXXXXX)"
  if ! { sed '/^APP_VERSION=/d' .env && printf 'APP_VERSION=%s\n' "$1"; } > "$tmp" || ! mv -f "$tmp" .env; then
    rm -f "$tmp"
    return 1
  fi
}

is_version() {
  [[ "$1" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
}

check_http() {
  local http_address path status
  http_address="$(docker compose port nginx 80)" || return 1
  for path in /ru /api/health; do
    status="$(curl --noproxy '*' --fail --silent --show-error --retry 24 --retry-all-errors --retry-delay 2 \
      --retry-max-time 60 --max-time 5 --output /dev/null --write-out '%{http_code}' "http://$http_address$path")" || return 1
    [[ "$status" == 200 ]] || return 1
  done
}

check_running_pair() {
  local service container image expected actual
  for service in api web; do
    container="$(docker compose ps -q "$service")" || return 1
    image="$(docker compose config --images "$service")" || return 1
    expected="$(docker image inspect --format '{{.Id}}' "$image")" || return 1
    actual="$(docker inspect --format '{{.Image}}' "$container")" || return 1
    [[ "$expected" == "$actual" ]] || return 1
  done
}

record_version() {
  { if [[ -f "$journal" ]]; then cat "$journal"; fi; printf '%s\n' "$APP_VERSION"; } > "$journal.tmp"
  mv -f "$journal.tmp" "$journal"
  save_version "$APP_VERSION"
}

apply_migrations() {
  docker compose run -T --rm --no-deps --pull never --entrypoint prisma api migrate deploy
}

inspect_migrations() {
  docker compose run -T --rm --no-deps --pull never --entrypoint node api -e '
    const { createHash } = require("node:crypto");
    const { createRequire } = require("node:module");
    const fs = require("node:fs");
    const { Client } = createRequire(require.resolve("@prisma/adapter-pg"))("pg");
    const migrations = "prisma/migrations";
    const [mode, version, approval = ""] = process.argv.slice(1);

    (async () => {
      const client = new Client({ connectionString: process.env.DATABASE_URL });
      await client.connect();
      try {
        const { rows } = await client.query(
          "SELECT migration_name, checksum, finished_at FROM _prisma_migrations WHERE rolled_back_at IS NULL ORDER BY migration_name"
        );
        const applied = new Set();
        const fingerprint = createHash("sha256");
        let exact = true;
        for (const row of rows) {
          if (!row.finished_at) throw Error("Unfinished migrations require manual review");
          const path = `${migrations}/${row.migration_name}/migration.sql`;
          if (!fs.existsSync(path)) {
            exact = false;
          } else if (row.checksum !== createHash("sha256").update(fs.readFileSync(path)).digest("hex")) {
            throw Error("Applied migration differs: " + row.migration_name);
          }
          fingerprint.update(JSON.stringify([row.migration_name, row.checksum]));
          applied.add(row.migration_name);
        }
        const schema = fingerprint.digest("hex");
        const pending = fs.readdirSync(migrations, { withFileTypes: true })
          .some((entry) => entry.isDirectory() && !applied.has(entry.name));
        if (mode === "rollback") {
          const [approvedSchema, ...tags] = approval.split("\n");
          if (pending || (!exact && !(approvedSchema === schema && tags.includes(version)))) {
            process.exitCode = 3;
          }
          return;
        }
        if (!exact) throw Error("The image is missing applied migrations");
        const path = "prisma/rollback-allow";
        const allowed = fs.existsSync(path) ? fs.readFileSync(path, "utf8").split(/\r?\n/) : [];
        if (mode === "snapshot") {
          if (pending) throw Error("The deployed schema still has pending migrations");
          console.log([schema, ...allowed.filter(tag => /^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(tag))].join("\n"));
        } else if (pending && !allowed.includes(version)) {
          throw Error("Pending migrations require rollback approval for " + version);
        }
      } finally {
        await client.end();
      }
    })().catch((error) => { console.error(error.message); process.exitCode = 1; });
  ' "$@"
}

record_schema_approval() {
  local snapshot previous fingerprint
  snapshot="$(inspect_migrations snapshot)"
  previous="$(cat "$schema_allow" 2>/dev/null || true)"
  fingerprint="${snapshot%%$'\n'*}"
  [[ "$fingerprint" =~ ^[0-9a-f]{64}$ ]] || return 1
  # Preserve existing approvals when the database schema did not change.
  {
    printf '%s\n' "$fingerprint"
    if [[ "${previous%%$'\n'*}" == "$fingerprint" ]]; then
      printf '%s\n' "$previous" | tail -n +2
    fi
    printf '%s\n' "$snapshot" | tail -n +2
  } > "$schema_allow.tmp"
  mv -f "$schema_allow.tmp" "$schema_allow"
}

load_confirmed_version() {
  if [[ ! -s "$journal" ]]; then
    echo 'Complete application bootstrap before switching versions.' >&2
    return 1
  fi

  current="$(tail -n 1 "$journal")"
  if ! is_version "$current"; then
    echo 'Invalid confirmed version in the deployment journal.' >&2
    return 1
  fi
  export APP_VERSION="$current"
}

switch_pair() {
  docker compose up -d --no-deps --pull never api web && check_running_pair && check_http
}

switch_or_restore() {
  local target="$APP_VERSION"
  if switch_pair; then
    record_version
    echo "Application switched to $APP_VERSION"
    return 0
  fi

  APP_VERSION="$current"
  if switch_pair; then
    echo "Switch to $target failed. Restored and verified $current." >&2
  else
    echo "Switch to $target failed and $current did not recover. Review the VPS." >&2
  fi
  return 1
}

deploy_release() {
  is_version "$requested_version" || return 2
  load_confirmed_version
  if ! check_running_pair || ! check_http; then
    echo 'The confirmed application pair is not running or healthy. Review the VPS before deploying.' >&2
    return 1
  fi
  save_version "$current"

  local latest_deployed
  latest_deployed="$(LC_ALL=C sort -V "$journal" | tail -n 1)"
  if [[ "$requested_version" == "$latest_deployed" || "$(printf '%s\n' "$latest_deployed" "$requested_version" | LC_ALL=C sort -V | tail -n 1)" != "$requested_version" ]]; then
    echo "Release $requested_version is already deployed or older than $latest_deployed"
    return 0
  fi

  APP_VERSION="$requested_version"
  docker compose pull api web
  inspect_migrations preflight "$current"
  if ! apply_migrations; then
    echo 'Migration failed. Application images were kept in place. Review the database before retrying.' >&2
    return 1
  fi
  record_schema_approval
  switch_or_restore
}

rollback_release() {
  load_confirmed_version
  local image images candidate candidates approval result
  images="$(docker compose config --images api web)"
  while IFS= read -r image; do
    docker image inspect "$image" >/dev/null
  done <<< "$images"
  approval="$(cat "$schema_allow" 2>/dev/null || true)"
  candidates="$(LC_ALL=C sort -Vru "$journal")"
  while IFS= read -r candidate; do
    is_version "$candidate" || continue
    [[ "$candidate" != "$current" ]] || continue
    [[ "$(printf '%s\n' "$candidate" "$current" | LC_ALL=C sort -V | tail -n 1)" == "$current" ]] || continue
    APP_VERSION="$candidate"
    docker compose pull api web
    if inspect_migrations rollback "$candidate" "$approval"; then
      switch_or_restore
      return
    else
      result=$?
      [[ "$result" == 3 ]] || return "$result"
      echo "Skipping $candidate: incompatible with the current schema." >&2
    fi
  done <<< "$candidates"
  echo 'No previous compatible application version was found.' >&2
  return 1
}

if [[ "$requested_version" == rollback ]]; then
  rollback_release
  exit
fi

if [[ -n "$requested_version" ]]; then
  deploy_release
  exit
fi

if [[ -n "$current" ]]; then
  exit 0
fi

if [[ -s "$journal" ]]; then
  save_version "$(tail -n 1 "$journal")"
  exit 0
fi

# Use latest only to discover the initial version. The two tags may briefly
# disagree while the publishing workflow promotes a new pair.
export APP_VERSION=latest
docker compose pull api web
api_image="$(docker compose config --images | grep '/swarmhouse-api:')"
web_image="$(docker compose config --images | grep '/swarmhouse-web:')"
release_label='{{ index .Config.Labels "org.opencontainers.image.version" }}'
api_version="$(docker image inspect --format "$release_label" "$api_image")"
web_version="$(docker image inspect --format "$release_label" "$web_image")"
if ! is_version "$api_version" || [[ "$api_version" != "$web_version" ]]; then
  echo 'GHCR latest must point to API and Web images from the same stable release.' >&2
  exit 1
fi

APP_VERSION="$api_version"
docker compose pull api web nginx
for image in "$api_image" "$web_image"; do
  latest_id="$(docker image inspect --format '{{.Id}}' "$image")"
  version_id="$(docker image inspect --format '{{.Id}}' "${image%:*}:$APP_VERSION")"
  if [[ "$latest_id" != "$version_id" ]]; then
    echo "Versioned image does not match latest: $image" >&2
    exit 1
  fi
done
apply_migrations
record_schema_approval

stop_unconfirmed_app() {
  if [[ ! -s "$journal" ]]; then
    docker compose stop nginx web api || true
  fi
}
trap stop_unconfirmed_app EXIT
docker compose up -d --pull never api web nginx
check_http

record_version
echo "Application bootstrapped at $APP_VERSION"
