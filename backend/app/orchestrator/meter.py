"""How a Claude call is charged to a project: (model, input tokens, output
tokens[, cache read, cache write]) → the ledger."""
from __future__ import annotations

from typing import Callable

Meter = Callable[..., None]
