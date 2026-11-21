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


JIRA_KEYS = ("JIRA_USER", "JIRA_API_TOKEN")


def jira_problems(env):
    problems = []
    for key in JIRA_KEYS:
        value = str((env or {}).get(key, ""))
        if value == "" or value in PLACEHOLDERS:
            problems.append(key)
    return problems


def jira_missing(env):
    """Только отсутствующие и пустые ключи. Непустое значение не запрашивается."""
    missing = []
    env = env or {}
    for key in JIRA_KEYS:
        if str(env.get(key, "")).strip() == "":
            missing.append(key)
    return missing


def jira_value_ok(value):
    """Значение, которое parse_env и env_file Compose сохраняют без shell-экранирования."""
    text = "" if value is None else str(value)
    if text == "" or text != text.strip():
        return False
    if any(char in text for char in "\n\r\x00#'\"\\$ "):
        return False
    return True


def jira_answers_ready(missing, answers):
    missing = list(missing or [])
    answers = dict(answers or {})
    if set(answers) != set(missing) or set(answers) - set(JIRA_KEYS):
        return False
    return all(jira_value_ok(answers[key]) for key in missing)


def jira_prompt_plan(deploy_services, env, host_count, interactive):
    if str(deploy_services).strip().lower() not in ("true", "yes", "1") and deploy_services is not True:
        return {"action": "skip", "ask": []}
    missing = jira_missing(env)
    if not missing:
        return {"action": "skip", "ask": []}
    if int(host_count) != 1:
        return {"action": "fail", "reason": "multi_host", "ask": missing}
    if not interactive:
        return {"action": "fail", "reason": "not_interactive", "ask": missing}
    return {"action": "ask", "ask": missing}


def apply_jira_lines(text, updates):
    updates = dict(updates or {})
    if set(updates) - set(JIRA_KEYS):
        raise ValueError("refusing keys")
    for value in updates.values():
        if not jira_value_ok(value):
            raise ValueError("unsafe value")
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
    for key in JIRA_KEYS:
        if key in updates and key not in seen:
            output.append("%s=%s" % (key, updates[key]))
    if not output:
        return ""
    return "\n".join(output) + "\n"


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


_SECRET_MARKERS = (
    "password=",
    "token=",
    "_secret",
    "api_key=",
    "begin openssh private key",
    "begin private key",
)


def service_ready(name, state):
    text = str(state or "").strip()
    if name == "alloy-init":
        return text == "exited 0"
    return text.startswith("running")


def _failure_source(value):
    if isinstance(value, dict):
        results = value.get("results")
        if isinstance(results, list) and results:
            parts = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("item") or "").strip()
                detail = item.get("stdout")
                if detail is None or str(detail).strip() == "":
                    detail = item.get("msg") or ""
                detail = str(detail).replace("\n", " ").strip()
                parts.append("%s: %s" % (name, detail) if name else detail)
            if parts:
                return "; ".join(parts)
        return str(value.get("msg") or "")
    return str(value or "")


def public_failure_text(value):
    raw = _failure_source(value).replace("\x00", "").strip()
    if not raw:
        return "не прочитана"
    lowered = raw.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return "текст ошибки скрыт, потому что может содержать секрет"
    if len(raw) > 600:
        return raw[:600] + "..."
    return raw


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
            "jira_missing": jira_missing,
            "jira_value_ok": jira_value_ok,
            "jira_answers_ready": jira_answers_ready,
            "jira_prompt_plan": jira_prompt_plan,
            "apply_jira_lines": apply_jira_lines,
            "grafana_blockers": grafana_blockers,
            "grafana_sync_updates": grafana_sync_updates,
            "sync_updates": sync_updates,
            "sync_env": sync_env,
            "backup_dir_from_log": backup_dir_from_log,
            "public_failure_text": public_failure_text,
            "service_ready": service_ready,
            "restore_db_from_log": restore_db_from_log,
        }
