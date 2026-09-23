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
