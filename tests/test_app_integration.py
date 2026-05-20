"""End-to-end tests for the Streamlit app using ``streamlit.testing.v1.AppTest``.

These tests drive the actual app.py script in a headless Streamlit runtime and
inspect session_state + rendered elements. Because the app depends on the
``streamlit_local_storage`` custom component (which hangs without a real
browser), we monkey-patch the module before AppTest imports app.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Patch streamlit_local_storage BEFORE AppTest imports app.py.
#
# Both test_app_integration.py and test_app_bug_regressions.py need to install
# a fake LocalStorage. To ensure both files share a single fake (so per-test
# cleanup works regardless of import order), we install once on a shared module
# and reuse it if pytest has already loaded the sibling file.
# ---------------------------------------------------------------------------
def _install_fake_local_storage():
    if "streamlit_local_storage" in sys.modules:
        existing = sys.modules["streamlit_local_storage"]
        # If the already-installed module has a LocalStorage with a class-level
        # ``_store``, reuse it. Otherwise overwrite with a fresh fake.
        if hasattr(existing, "LocalStorage") and hasattr(existing.LocalStorage, "_store"):
            return existing.LocalStorage

    class FakeLocalStorage:
        _store: dict = {}

        def __init__(self, key="storage_init"):
            pass

        def getItem(self, k):
            return FakeLocalStorage._store.get(k)

        def setItem(self, itemKey=None, itemValue=None, *a, **kw):
            if itemKey:
                FakeLocalStorage._store[itemKey] = itemValue

        def deleteItem(self, k, *a, **kw):
            FakeLocalStorage._store.pop(k, None)

        def deleteAll(self, *a, **kw):
            FakeLocalStorage._store.clear()

        def getAll(self):
            return dict(FakeLocalStorage._store)

        def refreshItems(self):
            pass

    fake_mod = ModuleType("streamlit_local_storage")
    fake_mod.LocalStorage = FakeLocalStorage
    sys.modules["streamlit_local_storage"] = fake_mod
    return FakeLocalStorage


FakeLocalStorage = _install_fake_local_storage()

from streamlit.testing.v1 import AppTest  # noqa: E402

import scheduler_core as core  # noqa: E402


APP_PATH = str(REPO_ROOT / "app.py")


# ---------------------------------------------------------------------------
# Per-test isolation: clear the fake store every test.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_local_storage():
    FakeLocalStorage._store.clear()
    yield
    FakeLocalStorage._store.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_member(name, gender="Male", availability=None, **kwargs):
    if availability is None:
        availability = {d: list(core.TIME_SLOTS.values()) for d in core.ALL_DAYS}
    return core.Member(
        name=name,
        gender=gender,
        availability=availability,
        avoid_opening=kwargs.get("avoid_opening", False),
        avoid_closing=kwargs.get("avoid_closing", False),
        preferred_days=kwargs.get("preferred_days", []),
        time_overrides=kwargs.get("time_overrides", {}),
    )


def _fillable_pool(count=40, male_count=None):
    """Build ``count`` members, the first ``male_count`` male and the rest female.

    When ``male_count`` is None we default to all male (which trivially passes
    the Opening/Closing gender requirement)."""
    if male_count is None:
        male_count = count
    pool = []
    for i in range(count):
        gender = "Male" if i < male_count else "Female"
        pool.append(_make_member(f"M_{i:02d}", gender=gender))
    return pool


def _seed_members(at, members):
    """Inject members + a non-zero file_hash so the upload branch is skipped."""
    at.session_state["members"] = members
    at.session_state["file_hash"] = 99999  # any non-zero placeholder


def _click_auto_generate(at):
    """Click the auto-generate button and re-run the script."""
    [b for b in at.button if "Auto-Generate" in b.label][0].click()
    at.run(timeout=30)


# ===========================================================================
# Cold-start
# ===========================================================================
class TestColdStart:
    def test_cold_start_shows_upload_prompt(self):
        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)
        assert not at.exception
        # No schedule yet -> tabs do NOT render, the info prompt does.
        assert at.session_state["schedule_grid"] == []
        assert at.session_state["members"] == []
        info_texts = [i.value for i in at.info]
        assert any("Upload your file" in t for t in info_texts)

    def test_cold_start_renders_title_and_button(self):
        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)
        assert not at.exception
        # Auto-Generate button must be present.
        assert any("Auto-Generate" in b.label for b in at.button)


# ===========================================================================
# Auto-generate flow
# ===========================================================================
class TestAutoGenerate:
    def test_generate_populates_20_slot_grid(self):
        at = AppTest.from_file(APP_PATH)
        _seed_members(at, _fillable_pool(40))
        at.run(timeout=15)
        _click_auto_generate(at)

        grid = at.session_state["schedule_grid"]
        # Mon-Fri × 4 slots = 20 shifts.
        assert len(grid) == 20

    def test_generate_fills_each_shift_with_two_members(self):
        at = AppTest.from_file(APP_PATH)
        _seed_members(at, _fillable_pool(40))
        at.run(timeout=15)
        _click_auto_generate(at)

        grid = at.session_state["schedule_grid"]
        for shift in grid:
            assert len(shift.assigned_members) == 2, (
                f"Shift {shift.day} idx={shift.time_idx} only had "
                f"{len(shift.assigned_members)} members"
            )

    def test_opening_and_closing_shifts_have_a_male(self):
        """Gender constraint: time_idx 0 or 3 must include at least one male."""
        at = AppTest.from_file(APP_PATH)
        # Build a pool where exactly the right number are male so the solver
        # cannot avoid this constraint: 20 males (one per Opening/Closing
        # shift on 5 days × 2 heavy slots) and 20 females.
        at.session_state["members"] = _fillable_pool(40, male_count=20)
        at.session_state["file_hash"] = 99999
        at.run(timeout=15)
        _click_auto_generate(at)

        grid = at.session_state["schedule_grid"]
        for shift in grid:
            if shift.time_idx in (0, 3):
                genders = [m.gender for m in shift.assigned_members]
                assert "Male" in genders, (
                    f"{shift.day} idx={shift.time_idx} missing Male: {genders}"
                )

    def test_no_member_assigned_twice(self):
        at = AppTest.from_file(APP_PATH)
        _seed_members(at, _fillable_pool(40))
        at.run(timeout=15)
        _click_auto_generate(at)

        seen = []
        for shift in at.session_state["schedule_grid"]:
            for m in shift.assigned_members:
                seen.append(m.name)
        # Each member should appear at most once across the grid.
        assert len(seen) == len(set(seen))


# ===========================================================================
# Constraint enforcement
# ===========================================================================
class TestConstraintEnforcement:
    def test_forbidden_pair_never_shares_a_shift(self):
        at = AppTest.from_file(APP_PATH)
        pool = _fillable_pool(40)
        _seed_members(at, pool)
        # Pick two arbitrary members and forbid them.
        at.session_state["forbidden_pairs"] = [(pool[0].name, pool[1].name)]
        at.run(timeout=15)
        _click_auto_generate(at)

        forbidden = {(pool[0].name, pool[1].name), (pool[1].name, pool[0].name)}
        for shift in at.session_state["schedule_grid"]:
            names = tuple(m.name for m in shift.assigned_members)
            if len(names) == 2:
                assert tuple(sorted(names)) != tuple(sorted((pool[0].name, pool[1].name))), (
                    f"Forbidden pair appeared together at {shift.day} idx={shift.time_idx}"
                )

    def test_must_schedule_member_appears_in_grid(self):
        at = AppTest.from_file(APP_PATH)
        pool = _fillable_pool(40)
        _seed_members(at, pool)
        must_name = pool[5].name
        at.session_state["must_schedule"] = [must_name]
        at.run(timeout=15)
        _click_auto_generate(at)

        scheduled = {m.name for s in at.session_state["schedule_grid"] for m in s.assigned_members}
        assert must_name in scheduled

    def test_never_schedule_member_does_not_appear(self):
        at = AppTest.from_file(APP_PATH)
        pool = _fillable_pool(40)
        _seed_members(at, pool)
        excluded_name = pool[7].name
        at.session_state["never_schedule"] = [excluded_name]
        at.run(timeout=15)
        _click_auto_generate(at)

        scheduled = {m.name for s in at.session_state["schedule_grid"] for m in s.assigned_members}
        assert excluded_name not in scheduled


# ===========================================================================
# Config save/load round-trip
# ===========================================================================
class TestConfigRoundTrip:
    def test_export_then_load_restores_grid(self):
        # Seed a Scheduler directly so we don't depend on AppTest button flow.
        pool = _fillable_pool(40)
        scheduler = core.Scheduler(pool, active_days=core.ALL_DAYS)
        scheduler.solve()
        original_grid = scheduler.schedule_grid

        cfg = core.export_configuration(
            schedule_grid=original_grid,
            forbidden_pairs=[],
            active_days=list(core.ALL_DAYS),
            must_schedule=[],
            never_schedule=[],
            members=pool,
        )

        # Round-trip via load_configuration with no existing members.
        a_days, f_pairs, must_s, never_s, new_grid, restored_members = core.load_configuration(
            cfg, None
        )

        # Same number of shifts, same assignments.
        assert len(new_grid) == len(original_grid)
        orig_state = {(s.day, s.time_idx): sorted(m.name for m in s.assigned_members) for s in original_grid}
        new_state = {(s.day, s.time_idx): sorted(m.name for m in s.assigned_members) for s in new_grid}
        assert orig_state == new_state
        # Members restored fully.
        assert {m.name for m in restored_members} == {m.name for m in pool}
        assert a_days == list(core.ALL_DAYS)
        assert f_pairs == []

    def test_export_then_load_preserves_time_overrides(self):
        pool = _fillable_pool(40)
        # Add an override to one member.
        pool[0].time_overrides = {"Monday": {1: False, 2: True}}
        scheduler = core.Scheduler(pool, active_days=core.ALL_DAYS)
        scheduler.solve()
        cfg = core.export_configuration(
            schedule_grid=scheduler.schedule_grid,
            forbidden_pairs=[],
            active_days=list(core.ALL_DAYS),
            must_schedule=[],
            never_schedule=[],
            members=pool,
        )
        _, _, _, _, _, restored_members = core.load_configuration(cfg, None)

        restored_first = next(m for m in restored_members if m.name == pool[0].name)
        # Keys are restored as ints (not the JSON-stringified keys).
        assert restored_first.time_overrides == {"Monday": {1: False, 2: True}}

    def test_export_then_load_preserves_locks(self):
        pool = _fillable_pool(40)
        scheduler = core.Scheduler(pool, active_days=core.ALL_DAYS)
        scheduler.solve()
        # Lock the first shift.
        scheduler.schedule_grid[0].locked = True

        cfg = core.export_configuration(
            schedule_grid=scheduler.schedule_grid,
            forbidden_pairs=[],
            active_days=list(core.ALL_DAYS),
            must_schedule=[],
            never_schedule=[],
            members=pool,
        )
        _, _, _, _, new_grid, _ = core.load_configuration(cfg, None)

        # Find the corresponding shift in the new grid and verify lock status.
        original = scheduler.schedule_grid[0]
        match = next(
            s for s in new_grid if s.day == original.day and s.time_idx == original.time_idx
        )
        assert match.locked is True

    def test_load_config_round_trip_through_session_state(self):
        """End-to-end: AppTest cold start, then inject a config JSON and verify
        session_state ends up populated correctly."""
        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)
        assert at.session_state["members"] == []

        # Build a config via the core APIs.
        pool = _fillable_pool(40)
        scheduler = core.Scheduler(pool, active_days=core.ALL_DAYS)
        scheduler.solve()
        cfg = core.export_configuration(
            schedule_grid=scheduler.schedule_grid,
            forbidden_pairs=[(pool[0].name, pool[1].name)],
            active_days=list(core.ALL_DAYS),
            must_schedule=[pool[2].name],
            never_schedule=[pool[3].name],
            members=pool,
        )

        # Directly populate as the on_change callback would.
        a_days, f_pairs, must_s, never_s, new_grid, restored_members = core.load_configuration(
            cfg, None
        )
        at.session_state["members"] = restored_members
        at.session_state["active_days_selection"] = a_days
        at.session_state["active_days"] = a_days
        at.session_state["forbidden_pairs"] = f_pairs
        at.session_state["must_schedule"] = must_s
        at.session_state["never_schedule"] = never_s
        at.session_state["schedule_grid"] = new_grid
        at.run(timeout=15)

        # The View tab should now exist (schedule_grid is populated).
        assert len(at.session_state["schedule_grid"]) == 20
        assert len(at.session_state["members"]) == 40
        assert at.session_state["forbidden_pairs"] == [(pool[0].name, pool[1].name)]
        assert at.session_state["must_schedule"] == [pool[2].name]
        assert at.session_state["never_schedule"] == [pool[3].name]
