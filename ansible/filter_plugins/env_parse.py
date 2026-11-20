"""Разбор KEY=value без source и без вывода значений."""


def parse_env(text):
    if text is None:
        return {}
    data = {}
    for raw in str(text).splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'").strip('"')
    return data


class FilterModule:
    def filters(self):
        return {"parse_env": parse_env}
