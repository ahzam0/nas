"""Unit tests for risk manager."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabio_bot.risk_manager import RiskManager


def test_position_size():
    rm = RiskManager(risk_pct=0.01, tick_value=5.0)
    size = rm.position_size(100_000, 20, 0.25, max_contracts=10)
    # Risk = 1000, per contract = 20 * 0.25 * 5 = 25
    assert size >= 1
    assert size <= 10


def test_can_trade_after_consecutive_losses():
    rm = RiskManager(max_consecutive_losses=3, session_start="00:00", session_end="23:59", use_globex=True)
    rm.set_session_equity(100_000)
    rm.record_trade(-100)
    rm.record_trade(-100)
    rm.record_trade(-100)
    can, reason = rm.can_trade(99_700)
    assert can is False
    assert "consecutive" in reason or "halted" in reason


def test_can_trade_ok():
    rm = RiskManager(max_consecutive_losses=3, max_daily_trades=20, session_start="00:00", session_end="23:59", use_globex=True)
    rm.set_session_equity(100_000)
    can, reason = rm.can_trade(100_000)
    assert can is True
    assert reason == "ok"
