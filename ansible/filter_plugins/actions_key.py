"""Решения по локальным каталогам и копиям env. Секреты наружу не возвращает."""


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


def local_dirs_conflict(paths):
    values = [str(item or "") for item in (paths or [])]
    if any(not item for item in values):
        return True
    return len(values) != len(set(values))


def env_copy_action(server_exists, local_exists, server_checksum=None, local_checksum=None):
    server = _bool(server_exists)
    local = _bool(local_exists)
    if server and local:
        if not server_checksum or not local_checksum:
            return "conflict"
        if str(server_checksum) != str(local_checksum):
            return "conflict"
        return "keep"
    if not server and local:
        return "block_generate"
    if server and not local:
        return "fetch"
    return "absent"


class FilterModule:
    def filters(self):
        return {
            "local_dirs_conflict": local_dirs_conflict,
            "env_copy_action": env_copy_action,
        }
