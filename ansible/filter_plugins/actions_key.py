"""Решения по ключу Actions и копиям env. Секреты наружу не возвращает."""


def _bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


def _flag(value):
    text = str(value if value is not None else "na").strip().lower()
    if text in ("yes", "true", "1"):
        return "yes"
    if text in ("no", "false", "0"):
        return "no"
    return "na"


def public_material(text):
    parts = str(text or "").strip().split()
    if len(parts) < 2 or not str(parts[0]).startswith("ssh-"):
        return None
    return (parts[0], parts[1])


def same_public(left, right):
    first = public_material(left)
    second = public_material(right)
    return first is not None and first == second


def _authorized_tokens(line):
    tokens = []
    buffer = []
    quote = ""
    for char in str(line or "").strip():
        if quote:
            buffer.append(char)
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
            buffer.append(char)
            continue
        if char.isspace():
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
            continue
        buffer.append(char)
    if buffer:
        tokens.append("".join(buffer))
    return tokens


def authorized_material(line):
    tokens = _authorized_tokens(line)
    for index, token in enumerate(tokens[:-1]):
        if token.startswith(("ssh-", "ecdsa-", "sk-ssh-", "sk-ecdsa-")):
            return (token, tokens[index + 1])
    return None


def authorized_has_key(text, public):
    wanted = public_material(public)
    if wanted is None:
        return False
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if authorized_material(stripped) == wanted:
            return True
    return False


def classify_actions_key(state):
    state = state or {}
    local_private = _bool(state.get("local_private"))
    local_public = _bool(state.get("local_public"))
    server_private = _bool(state.get("server_private"))
    server_public = _bool(state.get("server_public"))
    derived = _flag(state.get("local_matches_derived"))

    if local_public and not local_private:
        return {"action": "fail", "reason": "orphan_local_pub"}
    if local_private and local_public and derived == "no":
        return {"action": "fail", "reason": "local_pair_mismatch"}
    if local_private and not local_public:
        return {"action": "derive", "reason": "missing_local_pub"}
    if not local_private:
        if server_private or server_public:
            return {"action": "fail", "reason": "legacy_without_local"}
        return {"action": "generate", "reason": "new_install"}
    if server_private or server_public:
        return {"action": "install", "reason": "legacy_left"}
    return {"action": "install", "reason": "no_legacy"}


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
            "public_material": public_material,
            "same_public": same_public,
            "authorized_material": authorized_material,
            "authorized_has_key": authorized_has_key,
            "classify_actions_key": classify_actions_key,
            "local_dirs_conflict": local_dirs_conflict,
            "env_copy_action": env_copy_action,
        }
