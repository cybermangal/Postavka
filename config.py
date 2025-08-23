# config.py
import os
import json

def _parse_set(val: str) -> set[int]:
    if not val:
        return set()
    # допускает "1,2,3" или " [1, 2] "
    try:
        if val.strip().startswith('['):
            return {int(x) for x in json.loads(val)}
        return {int(x) for x in val.replace(' ', '').split(',') if x}
    except Exception:
        return set()

TOKEN = os.environ.get("TOKEN", "")  # ОБЯЗАТЕЛЬНО задать на сервере
ADMIN_IDS = _parse_set(os.environ.get("ADMIN_IDS", "537051799"))
ALLOWED_USERS = _parse_set(os.environ.get("ALLOWED_USERS", "537051799"))

TIMEZONE = os.environ.get("TIMEZONE", "UTC")
