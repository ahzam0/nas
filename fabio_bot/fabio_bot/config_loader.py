"""Load config from YAML with env var substitution."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except ImportError:
    yaml = None


def _env_sub(s: str) -> str:
    if not isinstance(s, str):
        return s
    for m in re.finditer(r"\$\{(\w+)\}", s):
        key = m.group(1)
        s = s.replace(m.group(0), os.environ.get(key, ""))
    return s


def load_config(path: str) -> Dict[str, Any]:
    if not yaml:
        raise RuntimeError("PyYAML required: pip install pyyaml")
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / path
    if not p.exists():
        return _default_config()
    with open(p, "r") as f:
        data = yaml.safe_load(f) or {}
    # Substitute env vars in string values
    for k, v in data.items():
        if isinstance(v, dict):
            data[k] = {k2: _env_sub(v2) if isinstance(v2, str) else v2 for k2, v2 in v.items()}
        elif isinstance(v, str):
            data[k] = _env_sub(v)
    return data


def _default_config() -> Dict[str, Any]:
    return {
        "tradovate": {
            "base_url": "https://demo.tradovateapi.com",
            "client_id": "",
            "client_secret": "",
            "username": "",
            "password": "",
            "app_id": "fabio_bot",
            "app_version": "1.0",
        },
        "bookmap": {"data_provider": "Tradovate", "interval_seconds": 15},
        "strategy": {
            "symbol": "NQ",
            "big_trade_threshold": 30,
            "risk_pct": 0.01,
            "session_start": "09:30",
            "session_end": "16:00",
            "min_delta": 500,
            "delta_sensitivity": 1.0,
            "vah_val_pct": 0.70,
            "absorption_ticks": 3,
            "max_hold_seconds": 60,
        },
        "targets": {"rr_first": 1.0, "rr_second": 2.0, "scale_out_pct": 0.5},
        "risk": {
            "max_daily_drawdown_pct": 0.03,
            "max_consecutive_losses": 3,
            "max_daily_trades": 20,
            "atr_stop_multiplier": 1.5,
            "tick_value": 5,
        },
        "mode": "simulation",
    }
