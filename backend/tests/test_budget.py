import threading

import pytest

from app.budget import VoiceBudget, BudgetExceeded
from app.errors import NonRetryableError


def test_charges_accumulate_per_project():
    budget = VoiceBudget(ceiling=100)
    budget.charge("p1", 30)
    budget.charge("p1", 20)
    assert budget.spent("p1") == 50
    assert budget.remaining("p1") == 50


def test_projects_are_metered_separately():
    budget = VoiceBudget(ceiling=100)
    budget.charge("p1", 90)
    budget.charge("p2", 90)
    assert budget.remaining("p1") == 10
    assert budget.remaining("p2") == 10


def test_an_unknown_project_has_the_full_ceiling():
    assert VoiceBudget(ceiling=100).remaining("never-seen") == 100


def test_a_charge_that_would_cross_the_ceiling_is_refused_and_not_recorded():
    budget = VoiceBudget(ceiling=100)
    budget.charge("p1", 95)
    with pytest.raises(BudgetExceeded) as err:
        budget.charge("p1", 10)
    assert budget.spent("p1") == 95
    assert isinstance(err.value, NonRetryableError)
    assert "5" in str(err.value)  # says how much is left


def test_charging_exactly_to_the_ceiling_is_allowed():
    budget = VoiceBudget(ceiling=100)
    budget.charge("p1", 100)
    assert budget.remaining("p1") == 0


def test_can_afford_does_not_charge():
    budget = VoiceBudget(ceiling=10)
    assert budget.can_afford("p1", 10) is True
    assert budget.can_afford("p1", 11) is False
    assert budget.spent("p1") == 0


def test_concurrent_charges_never_overshoot():
    budget = VoiceBudget(ceiling=100)
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        try:
            budget.charge("p1", 7)
        except BudgetExceeded:
            pass

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert budget.spent("p1") == 98  # 14 × 7; the 15th would be 105


def test_a_held_charge_is_kept_on_success_refunded_on_failure_and_after_a_crash():
    """Rehearsal item 4: a crash during the vendor call left its charge on the ledger
    (60 characters for a take that was never made); now the next start gives it back."""
    from app import budget as budget_mod
    from app.store.db import Database
    from app.usage import Ledger
    b = budget_mod.VoiceBudget(1000, Ledger(Database()))
    with b.held("p1", 60):
        pass
    assert b.spent("p1") == 60
    try:
        with b.held("p1", 40):
            raise RuntimeError("the vendor fell over")
    except RuntimeError:
        pass
    assert b.spent("p1") == 60
    # A process dies inside the call: its open charge stays behind...
    gen = b.held("p1", 25)
    gen.__enter__()
    assert b.spent("p1") == 85
    assert b.refund_orphans() == []                      # this process is alive: nothing is given back
    real = budget_mod.PROCESS
    budget_mod.PROCESS = "the next process"
    try:
        given = b.refund_orphans()                       # ...and the next start refunds it
    finally:
        budget_mod.PROCESS = real
    assert [g["amount"] for g in given] == [25] and b.spent("p1") == 60
    assert b.refund_orphans() == []                       # once
