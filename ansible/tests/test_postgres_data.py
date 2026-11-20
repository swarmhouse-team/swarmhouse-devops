"""Корень data/postgres: решения без Docker и без секретов."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "filter_plugins"))

from postgres_data import (  # noqa: E402
    data_host_ok,
    image_tag_ok,
    mount_path_ok,
    parse_posix_id,
    pgdata_from_env,
    postgres_dir_plan,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = (ROOT / "tasks" / "deploy.yml").read_text(encoding="utf-8")
DATADIR = (ROOT / "tasks" / "postgres_datadir.yml").read_text(encoding="utf-8")
ACCESS = (ROOT / "tasks" / "postgres_access.yml").read_text(encoding="utf-8")
SERVICE = (ROOT / "tasks" / "service_datadir.yml").read_text(encoding="utf-8")
KIND = (ROOT / "tasks" / "datadir_kind.yml").read_text(encoding="utf-8")
ROOTDIR = (ROOT / "tasks" / "datadir_root.yml").read_text(encoding="utf-8")


def main():
    assert image_tag_ok("18.7-trixie") is True
    assert image_tag_ok("18") is True
    assert image_tag_ok("") is False
    assert image_tag_ok("18;rm") is False

    debian = parse_posix_id("uid=70(postgres) gid=70(postgres) groups=70(postgres)")
    assert debian == {"uid": 70, "gid": 70}
    other = parse_posix_id("uid=999(postgres) gid=999(postgres) groups=999(postgres)")
    assert other["uid"] == 999
    root = parse_posix_id("uid=0(root) gid=0(root) groups=0(root)")
    assert root == {"uid": 0, "gid": 0}
    root_dir = postgres_dir_plan(False, 0, 0, "", 0, 0)
    assert root_dir == {"action": "create", "chown": True, "mode": "0700", "recurse": False}
    try:
        parse_posix_id("postgres")
    except ValueError:
        pass
    else:
        raise AssertionError("unparsed id was accepted")

    env = "PATH=/usr/lib/postgresql/18/bin\nPGDATA=/var/lib/postgresql/18/docker\n"
    assert pgdata_from_env(env) == "/var/lib/postgresql/18/docker"
    for bad in ("PGDATA=/var/lib/postgresql", "PGDATA=/tmp/pg", "PATH=/bin"):
        try:
            pgdata_from_env(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("bad PGDATA accepted: %s" % bad)

    created = postgres_dir_plan(False, 0, 0, "", 70, 70)
    assert created == {"action": "create", "chown": True, "mode": "0700", "recurse": False}
    owned_by_deploy = postgres_dir_plan(True, 1001, 1001, "0750", 70, 70)
    assert owned_by_deploy["action"] == "fix_root"
    assert owned_by_deploy["chown"] is True
    assert owned_by_deploy["recurse"] is False
    assert owned_by_deploy["mode"] == "0700"
    repeat = postgres_dir_plan(True, 70, 70, "0700", 70, 70)
    assert repeat["action"] == "keep"
    assert repeat["chown"] is False
    mode_only = postgres_dir_plan(True, 70, 70, "0750", 70, 70)
    assert mode_only["action"] == "fix_root"
    assert mode_only["chown"] is False

    assert data_host_ok("data/prometheus") is True
    assert data_host_ok("data/grafana") is True
    assert data_host_ok("data/redis") is True
    assert data_host_ok("data/postgres") is False
    assert data_host_ok("../data/prometheus") is False
    assert mount_path_ok("/prometheus") is True
    assert mount_path_ok("/var/lib/grafana") is True
    assert mount_path_ok("/data") is True
    assert mount_path_ok("/var/lib/../grafana") is False
    nobody = parse_posix_id("uid=65534(nobody) gid=65534(nogroup) groups=65534(nogroup)")
    grafana = parse_posix_id("uid=472(grafana) gid=472(grafana) groups=472(grafana)")
    assert postgres_dir_plan(True, 1001, 1001, "0750", nobody["uid"], nobody["gid"])["chown"] is True
    assert postgres_dir_plan(True, 472, 472, "0700", grafana["uid"], grafana["gid"])["action"] == "keep"
    prepare = DEPLOY.split("Подготовить корни данных Redis, Prometheus и Grafana", 1)[1].split(
        "Подготовить корень данных PostgreSQL", 1
    )[0]
    assert "owner:" not in prepare
    assert "0750" not in prepare
    for host in ("data/redis", "data/prometheus", "data/grafana"):
        assert host in prepare
    assert DEPLOY.index("{{ devops_checkout }}/data") < DEPLOY.index("datadir_kind.yml")
    assert "datadir_kind.yml" in DEPLOY
    assert DEPLOY.index("datadir_kind.yml") < DEPLOY.index("service_datadir.yml")
    assert "service_datadir.yml" in DEPLOY
    assert DEPLOY.index("service_datadir.yml") < DEPLOY.index("postgres_datadir.yml")
    assert DEPLOY.index("postgres_datadir.yml") < DEPLOY.index("Запустить postgres и redis")
    assert DEPLOY.index("Запустить postgres и redis") < DEPLOY.index("postgres_access.yml")

    for text in (KIND, ROOTDIR, DATADIR, SERVICE):
        assert "recurse: true" not in text
        assert "-R" not in text
        assert "0777" not in text
        assert "deploy_user" not in text
    assert "recurse: false" in ROOTDIR
    assert "islnk" in KIND
    assert "chown" in ROOTDIR
    assert "999" not in DATADIR
    assert "65534" not in SERVICE
    assert "472" not in SERVICE
    assert "--entrypoint" in DATADIR
    assert "\n      - id\n" in DATADIR
    assert "--user" in DATADIR
    assert "target=/var/lib/postgresql,readonly" in DATADIR
    assert "test -x /var/lib/postgresql" in DATADIR
    assert DATADIR.index("parse_posix_id") < DATADIR.index("datadir_kind.yml")
    assert DATADIR.index("datadir_kind.yml") < DATADIR.index("datadir_root.yml")
    assert DATADIR.count("datadir_kind.yml") == 1
    assert "test -d \"$PGDATA\"" in ACCESS
    assert "--user" in ACCESS
    assert "999" not in ACCESS
    assert "--entrypoint" in SERVICE
    assert "\n      - id\n" in SERVICE
    assert "test -w" in SERVICE
    assert SERVICE.index("parse_posix_id") < SERVICE.index("datadir_kind.yml")
    assert SERVICE.index("datadir_kind.yml") < SERVICE.index("datadir_root.yml")
    assert SERVICE.count("datadir_kind.yml") == 1

    print("id", debian["uid"], other["uid"])
    print("create", created["action"])
    print("fix deploy", owned_by_deploy["action"], owned_by_deploy["chown"])
    print("repeat", repeat["action"], repeat["chown"])
    print("mode only", mode_only["chown"])
    print("ok")


if __name__ == "__main__":
    main()
