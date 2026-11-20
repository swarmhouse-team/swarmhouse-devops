"""Проверки деплоя без вывода секретов."""

import re

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
URI = re.compile(r"^postgres:5432/([A-Za-z_][A-Za-z0-9_]*)\?sslmode=disable$")
RESTORE_DB = re.compile(r"^restore_test_[a-z0-9_]+$")
PLACEHOLDERS = {
    "ci-placeholder-not-for-production",
    "change_me_strong_password",
    "api-token",
    "email-jira",
    "root_url",
}
WEAK_PASSWORDS = {
    "admin",
    "grafana",
    "password",
    "changeme",
    "change_me_strong_password",
}
SYNC_KEYS = {
    "DATA_SOURCE_URI",
    "GF_AUTH_BASIC_ENABLED",
    "GF_SECURITY_COOKIE_SECURE",
    "GF_AUTH_ANONYMOUS_ENABLED",
}


def is_ident(value):
    return bool(IDENT.match(str(value or "")))


def datasource_uri(db_name):
    if not is_ident(db_name):
        raise ValueError("bad db name")
    return "postgres:5432/%s?sslmode=disable" % db_name


def db_name_from_uri(uri):
    match = URI.match(str(uri or ""))
    return match.group(1) if match else ""


def exporter_db_problem(postgres_db, uri):
    if not is_ident(postgres_db):
        return "postgres_db_invalid"
    if str(uri or "") != datasource_uri(postgres_db):
        return "datasource_uri_mismatch"
    return ""


def jira_problems(env):
    problems = []
    for key in ("JIRA_API_TOKEN", "JIRA_USER"):
        value = str((env or {}).get(key, ""))
        if value == "" or value in PLACEHOLDERS:
            problems.append(key)
    return problems


def grafana_blockers(env):
    env = env or {}
    blockers = []
    if str(env.get("GF_AUTH_ANONYMOUS_ENABLED", "false")).lower() == "true":
        blockers.append("anonymous_enabled")
    if str(env.get("GF_AUTH_BASIC_ENABLED", "false")).lower() != "true":
        blockers.append("basic_disabled")
    protocol = str(env.get("GF_SERVER_PROTOCOL", "http")).lower()
    root = str(env.get("GF_SERVER_ROOT_URL", ""))
    secure = str(env.get("GF_SECURITY_COOKIE_SECURE", "false")).lower() == "true"
    if secure and (protocol == "http" or root.startswith("http://")):
        blockers.append("cookie_secure_on_http")
    password = str(env.get("GF_SECURITY_ADMIN_PASSWORD", ""))
    user = str(env.get("GF_SECURITY_ADMIN_USER", ""))
    if (
        password == ""
        or password in PLACEHOLDERS
        or password.lower() in WEAK_PASSWORDS
        or password == user
    ):
        blockers.append("admin_password_rejected")
    return blockers


def grafana_sync_updates(blockers):
    updates = {}
    blockers = blockers or []
    if "basic_disabled" in blockers:
        updates["GF_AUTH_BASIC_ENABLED"] = "true"
    if "cookie_secure_on_http" in blockers:
        updates["GF_SECURITY_COOKIE_SECURE"] = "false"
    if "anonymous_enabled" in blockers:
        updates["GF_AUTH_ANONYMOUS_ENABLED"] = "false"
    return updates


def sync_updates(postgres_db):
    return {
        "DATA_SOURCE_URI": datasource_uri(postgres_db),
        "GF_AUTH_BASIC_ENABLED": "true",
        "GF_SECURITY_COOKIE_SECURE": "false",
        "GF_AUTH_ANONYMOUS_ENABLED": "false",
    }


def sync_env(text, updates):
    updates = dict(updates or {})
    refused = sorted(set(updates) - SYNC_KEYS)
    if refused:
        raise ValueError("refusing keys: %s" % ",".join(refused))
    lines = str(text or "").splitlines()
    seen = set()
    output = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append("%s=%s" % (key, updates[key]))
            seen.add(key)
        else:
            output.append(line)
    for key in SYNC_KEYS:
        if key in updates and key not in seen:
            output.append("%s=%s" % (key, updates[key]))
    return "\n".join(output) + ("\n" if output else "")


def backup_dir_from_log(text):
    marker = "Готово: "
    for line in str(text or "").splitlines():
        if marker not in line:
            continue
        path = line.split(marker, 1)[1].strip().split(" ", 1)[0]
        if path.startswith("/"):
            return path
    return ""


def restore_db_from_log(text):
    marker = "Тестовая база: "
    for line in str(text or "").splitlines():
        if marker not in line:
            continue
        name = line.split(marker, 1)[1].strip().split(" ", 1)[0]
        if RESTORE_DB.match(name) and len(name) <= 63:
            return name
    return ""


class FilterModule:
    def filters(self):
        return {
            "is_ident": is_ident,
            "datasource_uri": datasource_uri,
            "db_name_from_uri": db_name_from_uri,
            "exporter_db_problem": exporter_db_problem,
            "jira_problems": jira_problems,
            "grafana_blockers": grafana_blockers,
            "grafana_sync_updates": grafana_sync_updates,
            "sync_updates": sync_updates,
            "sync_env": sync_env,
            "backup_dir_from_log": backup_dir_from_log,
            "restore_db_from_log": restore_db_from_log,
        }
