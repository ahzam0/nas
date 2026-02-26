"""
ML signal filter and regime detection for higher win rate.
- Predict P(win) for a signal; only allow if above threshold.
- Regime: rolling volatility (low/med/high); only signal in allowed regimes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FEATURE_KEYS = [
    "strength", "cvd", "close", "poc", "atr", "big_buy", "big_sell",
    "dist_poc", "dist_val", "dist_vah", "bar_delta", "side_long",
]

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import joblib
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class MLSignalFilter:
    """Predict P(win) for a signal; only allow if above threshold."""

    def __init__(self, model_path: Optional[Path] = None, threshold: float = 0.52):
        self.threshold = threshold
        self.model = None
        self.scaler = None
        if model_path and model_path.exists() and HAS_SKLEARN:
            try:
                data = joblib.load(model_path)
                self.model = data.get("model")
                self.scaler = data.get("scaler")
            except Exception as e:
                logger.warning("Could not load ML model %s: %s", model_path, e)

    def predict_win_probability(self, features: Dict[str, float]) -> float:
        if self.model is None or self.scaler is None:
            return 0.55
        try:
            x = np.array([[features.get(k, 0) for k in FEATURE_KEYS]], dtype=float)
            x = self.scaler.transform(x)
            return float(self.model.predict_proba(x)[0, 1])
        except Exception:
            return 0.55

    def should_take_signal(self, features: Dict[str, float]) -> bool:
        return self.predict_win_probability(features) >= self.threshold


class RegimeDetector:
    """Volatility regime: 0=low, 1=med, 2=high. Only signal in allowed regimes."""

    def __init__(self, window: int = 20, allowed_regimes: Tuple[int, ...] = (0, 1)):
        self.window = window
        self.allowed_regimes = allowed_regimes

    def get_regime(self, df_bars: pd.DataFrame, bar_idx: Optional[int] = None) -> int:
        if bar_idx is None:
            bar_idx = len(df_bars) - 1
        if bar_idx < self.window:
            return 1
        recent = df_bars.iloc[bar_idx - self.window : bar_idx]
        if "close" not in recent.columns:
            return 1
        returns = recent["close"].pct_change().dropna()
        if len(returns) < 2:
            return 1
        vol = float(returns.std())
        if vol <= 0:
            return 0
        # Simple bands: low vol = 0, high vol = 2, else 1 (use median as mid)
        try:
            all_vols = df_bars["close"].pct_change().rolling(self.window).std().dropna()
            if len(all_vols) < 10:
                return 1
            med = float(all_vols.median())
            if med <= 0:
                return 1
            if vol < med * 0.7:
                return 0
            if vol > med * 1.4:
                return 2
        except Exception:
            pass
        return 1

    def should_trade(self, df_bars: pd.DataFrame, bar_idx: Optional[int] = None) -> bool:
        return self.get_regime(df_bars, bar_idx) in self.allowed_regimes
