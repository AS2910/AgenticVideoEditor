"""The numbered schema migrations (Step 0, M0).

Each module `mNNNN_<name>.py` holds one step with an `up(conn)` and a
`down(conn)`. The runner (`app.store.migrate`) applies them in order inside
one transaction each and records what is applied in `schema_migrations`.

Every `up` is idempotent: a database made before the runner existed already
has some or all of the schema, so its steps run, change nothing, and are
recorded as applied. Never edit a shipped step; add the next number.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable

_NAME = re.compile(r"^m(\d{4})_(\w+)$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: Callable[[Any], Any]
    down: Callable[[Any], Any]


def _load(module: ModuleType, version: int, name: str) -> Migration:
    return Migration(version, name, module.up, module.down)


def all_migrations() -> list[Migration]:
    """Every step in this package, in version order."""
    found = []
    for info in pkgutil.iter_modules(__path__):
        match = _NAME.match(info.name)
        if not match:
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        found.append(_load(module, int(match.group(1)), match.group(2)))
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise RuntimeError(f"two migrations share a number: {versions}")
    return found
