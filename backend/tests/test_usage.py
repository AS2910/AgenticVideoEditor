"""The usage ledger (Phase 9b)."""
import pytest

from app.usage import Ledger, SpendCeilingReached, claude_usd


def test_lines_group_by_vendor_and_purpose():
    ledger = Ledger()
    ledger.record("p1", "anthropic", "intent", 600, "tokens", 0.004)
    ledger.record("p1", "anthropic", "intent", 400, "tokens", 0.003)
    ledger.record("p1", "openai", "transcription", 0.5, "minutes", 0.003)
    ledger.record("p2", "openai", "transcription", 9, "minutes", 0.054)

    lines = {(u.vendor, u.what): u for u in ledger.lines("p1")}

    assert lines["anthropic", "intent"].units == 1000 and lines["anthropic", "intent"].calls == 2
    assert ledger.spent_usd("p1") == pytest.approx(0.010)


def test_the_ceiling_refuses_only_once_reached():
    ledger = Ledger(ceiling_usd=0.05)
    ledger.record("p1", "openai", "transcription", 1, "minutes", 0.049)
    ledger.ensure_can_spend("p1")
    ledger.record("p1", "anthropic", "intent", 10, "tokens", 0.001)
    with pytest.raises(SpendCeilingReached) as err:
        ledger.ensure_can_spend("p1")
    assert "$0.05" in str(err.value)


def test_claude_price():
    assert claude_usd("claude-opus-5", 1_000_000, 0) == pytest.approx(5.0)
    assert claude_usd("claude-opus-5", 0, 1_000_000) == pytest.approx(25.0)
