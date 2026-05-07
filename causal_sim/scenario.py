from __future__ import annotations

import json
from pathlib import Path

from causal_sim.models import CauseTemplate


def load_scenario(path: str | Path) -> CauseTemplate:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return CauseTemplate(**raw)

