"""Подготовка корня data/postgres. Содержимое базы не разбирается."""

import re

_ID_UID = re.compile(r"\buid=(\d+)\b")
_ID_GID = re.compile(r"\bgid=(\d+)\b")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MOUNT = "/var/lib/postgresql"


_HOSTS = {"data/redis", "data/prometheus", "data/grafana"}
_MOUNT_PATH = re.compile(r"^/[A-Za-z0-9_./-]+$")


def image_tag_ok(tag):
    return bool(_TAG.match(str(tag or "")))


def data_host_ok(path):
    return str(path or "") in _HOSTS


def mount_path_ok(path):
    text = str(path or "")
    if not _MOUNT_PATH.match(text) or ".." in text.split("/"):
        return False
    return text != "/"


def parse_posix_id(text):
    uid_match = _ID_UID.search(str(text or ""))
    gid_match = _ID_GID.search(str(text or ""))
    if uid_match is None or gid_match is None:
        raise ValueError("id output has no uid or gid")
    uid = int(uid_match.group(1))
    gid = int(gid_match.group(1))
    if uid <= 0 or gid < 0:
        raise ValueError("image user must not be root")
    return {"uid": uid, "gid": gid}


def pgdata_from_env(text):
    found = ""
    for line in str(text or "").splitlines():
        if line.startswith("PGDATA="):
            found = line.split("=", 1)[1].strip()
    if not found.startswith(_MOUNT + "/"):
        raise ValueError("PGDATA is not inside /var/lib/postgresql")
    if ".." in found.split("/"):
        raise ValueError("PGDATA has a parent segment")
    return found


def _bits(mode):
    text = str(mode or "").strip()
    if not text or any(char not in "01234567" for char in text):
        return None
    return int(text, 8) & 0o7777


def postgres_dir_plan(exists, uid, gid, mode, image_uid, image_gid):
    image_uid = int(image_uid)
    image_gid = int(image_gid)
    if image_uid <= 0 or image_gid < 0:
        raise ValueError("bad image user")
    if not exists:
        return {"action": "create", "chown": True, "mode": "0700", "recurse": False}
    same_owner = int(uid) == image_uid and int(gid) == image_gid
    same_mode = _bits(mode) == 0o700
    if same_owner and same_mode:
        return {"action": "keep", "chown": False, "mode": "0700", "recurse": False}
    return {
        "action": "fix_root",
        "chown": not same_owner,
        "mode": "0700",
        "recurse": False,
    }


class FilterModule:
    def filters(self):
        return {
            "image_tag_ok": image_tag_ok,
            "data_host_ok": data_host_ok,
            "mount_path_ok": mount_path_ok,
            "parse_posix_id": parse_posix_id,
            "pgdata_from_env": pgdata_from_env,
            "postgres_dir_plan": postgres_dir_plan,
        }
