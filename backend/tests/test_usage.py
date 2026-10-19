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


def test_calls_since_counts_one_vendors_rows_from_a_moment():
    ledger = Ledger()
    ledger.record("p1", "elevenlabs", "speech", 7, "characters", 0.001)
    import time
    from app.timefmt import now_iso
    time.sleep(0.002)   # moments are kept to the millisecond: the mark is after the first row
    mark = now_iso()
    ledger.record("p1", "elevenlabs", "speech", 7, "characters", 0.001)
    ledger.record("p1", "elevenlabs", "speech", 7, "characters", 0.001)
    ledger.record("p1", "anthropic", "plan", 10, "tokens", 0.001)
    ledger.record("p2", "elevenlabs", "speech", 7, "characters", 0.001)
    assert ledger.calls_since("p1", "elevenlabs", mark) == 2
    assert ledger.calls_since("p1", "elevenlabs", "2000-01-01T00:00:00.000Z") == 3


def test_each_refusal_names_its_scope_and_the_way_on():
    from datetime import datetime, timezone
    from app.usage import ProjectCeilingReached, UserCeilingReached
    assert str(SpendCeilingReached(2.1, 2.0, "ad.mp4")) == (
        "ad.mp4 has reached its $2 video ceiling. Raise it in Settings, or start a variant.")
    assert str(ProjectCeilingReached(10.2, 10.0, "Ashish Testing")) == (
        "Ashish Testing has reached its $10 project ceiling. Raise it on the project page, or move the video out.")
    october = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert str(UserCeilingReached(100.5, 100.0, now=october)) == (
        "You have reached your $100 ceiling for October. It resets on 1 November.")
    assert str(UserCeilingReached(1, 2.5, now=datetime(2026, 12, 3, tzinfo=timezone.utc))).endswith(
        "$2.50 ceiling for December. It resets on 1 January.")


def test_a_row_carries_the_turn_running_when_it_was_charged():
    from app.usage import current_turn
    ledger = Ledger()
    ledger.record("p1", "openai", "transcription", 1, "minutes", 0.01)
    token = current_turn.set("j7")
    try:
        ledger.record("p1", "anthropic", "agent", 10, "tokens", 0.02)
        ledger.record_project_level("f1", "elevenlabs", "voice design", 5, "characters", 0.03)
    finally:
        current_turn.reset(token)
    with ledger.db.tx() as c:
        rows = [tuple(r) for r in c.execute("SELECT project_id, folder_id, turn_id FROM usage ORDER BY id")]
    assert rows == [("p1", None, None), ("p1", None, "j7"), ("", "f1", "j7")]
    assert ledger.spent_usd_by_turn("p1", "j7") == pytest.approx(0.02)
    assert ledger.spent_usd("p1") == pytest.approx(0.03)        # the project-level row is no video's
