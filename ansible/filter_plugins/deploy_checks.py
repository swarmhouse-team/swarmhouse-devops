"""Проверки деплоя без вывода секретов."""

import re

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESTORE_DB = re.compile(r"^restore_test_[a-z0-9_]+$")


def is_ident(value):
    return bool(IDENT.match(str(value or "")))


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
            "backup_dir_from_log": backup_dir_from_log,
            "public_failure_text": public_failure_text,
            "service_ready": service_ready,
            "restore_db_from_log": restore_db_from_log,
        }
