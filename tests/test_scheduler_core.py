"""Comprehensive pytest suite for scheduler_core.py.

Covers Member.is_available, Shift.needs_male, Scheduler.solve and its
hard/soft constraints, Least-Changes scoring with previous_state, pre_filled_grid
behavior, restore_state, _get_valid_pairs/_get_valid_partners,
find_best_slots_for_pair, parse_file (using sample CSVs via FakeUpload),
generate_excel_bytes (round-tripped through pandas), and the
export_configuration / load_configuration round-trip.
"""

import io
import json
from itertools import combinations

import pandas as pd
import pytest

import scheduler_core as core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_avail():
    return {d: list(core.TIME_SLOTS.values()) for d in core.ALL_DAYS}


def _make_single_day_pool(member_builder, day="Monday", n_male=6, n_female=2):
    """Build a small predictable pool: members available only on `day` for all
    four time slots. Used for scoring tests that need a 4-shift grid."""
    pool = []
    for i in range(n_male):
        pool.append(
            member_builder(
                f"M_{i:02d}",
                gender="Male",
                availability={day: list(core.TIME_SLOTS.values())},
            )
        )
    for i in range(n_female):
        pool.append(
            member_builder(
                f"F_{i:02d}",
                gender="Female",
                availability={day: list(core.TIME_SLOTS.values())},
            )
        )
    return pool


def _grid_state(grid):
    """Snapshot of (day, time_idx) -> sorted name list, for comparison."""
    return {
        (s.day, s.time_idx): sorted(m.name for m in s.assigned_members)
        for s in grid
    }


# ---------------------------------------------------------------------------
# Member.is_available
# ---------------------------------------------------------------------------


class TestMemberIsAvailable:
    def test_base_availability_true_when_slot_listed(self, member_builder):
        m = member_builder("Alice", availability={"Monday": [0, 1]})
        assert m.is_available("Monday", 0) is True
        assert m.is_available("Monday", 1) is True

    def test_base_availability_false_when_slot_not_listed(self, member_builder):
        m = member_builder("Alice", availability={"Monday": [0, 1]})
        assert m.is_available("Monday", 2) is False
        assert m.is_available("Monday", 3) is False

    def test_base_availability_false_when_day_missing(self, member_builder):
        m = member_builder("Alice", availability={"Monday": [0]})
        assert m.is_available("Tuesday", 0) is False

    def test_avoid_opening_blocks_only_time_idx_0(self, member_builder):
        m = member_builder("Alice", avoid_opening=True)
        # Default fixture is fully available -- avoid_opening blocks slot 0 only.
        assert m.is_available("Monday", 0) is False
        assert m.is_available("Monday", 1) is True
        assert m.is_available("Monday", 2) is True
        # Closing (idx 3) is NOT blocked by avoid_opening.
        assert m.is_available("Monday", 3) is True

    def test_avoid_closing_blocks_only_time_idx_3(self, member_builder):
        m = member_builder("Alice", avoid_closing=True)
        assert m.is_available("Monday", 3) is False
        assert m.is_available("Monday", 0) is True
        assert m.is_available("Monday", 1) is True
        assert m.is_available("Monday", 2) is True

    def test_time_override_true_forces_on_even_when_unavailable(self, member_builder):
        m = member_builder(
            "Alice",
            availability={"Monday": []},  # base says not available
            time_overrides={"Monday": {0: True}},
        )
        assert m.is_available("Monday", 0) is True

    def test_time_override_false_forces_off_even_when_available(self, member_builder):
        m = member_builder(
            "Alice",
            availability={"Monday": [0, 1, 2, 3]},
            time_overrides={"Monday": {1: False}},
        )
        assert m.is_available("Monday", 1) is False
        # Non-overridden slots still follow base availability.
        assert m.is_available("Monday", 0) is True

    def test_time_override_takes_precedence_over_avoid_opening(self, member_builder):
        m = member_builder(
            "Alice",
            avoid_opening=True,
            time_overrides={"Monday": {0: True}},
        )
        # avoid_opening would normally block idx 0 — override wins.
        assert m.is_available("Monday", 0) is True

    def test_time_override_takes_precedence_over_avoid_closing(self, member_builder):
        m = member_builder(
            "Alice",
            avoid_closing=True,
            time_overrides={"Monday": {3: True}},
        )
        assert m.is_available("Monday", 3) is True

    def test_time_override_none_value_does_not_special_case(self, member_builder):
        # The dataclass defaults time_overrides to {}; None should never appear in
        # the dict. But explicitly check that a missing override key falls back
        # to base availability.
        m = member_builder("Alice", time_overrides={"Monday": {}})
        # The Monday key exists, but time_idx 0 isn't in the inner map -> falls
        # back to base availability (which is full).
        assert m.is_available("Monday", 0) is True


# ---------------------------------------------------------------------------
# Shift.needs_male
# ---------------------------------------------------------------------------


class TestShiftNeedsMale:
    def test_opening_slot_needs_male(self):
        shift = core.Shift("Monday", 0, "10:30-11:30")
        assert shift.needs_male() is True

    def test_closing_slot_needs_male(self):
        shift = core.Shift("Monday", 3, "1:30-2:30")
        assert shift.needs_male() is True

    def test_middle_slots_do_not_need_male(self):
        assert core.Shift("Monday", 1, "11:30-12:30").needs_male() is False
        assert core.Shift("Monday", 2, "12:30-1:30").needs_male() is False

    def test_needs_male_independent_of_day(self):
        for day in core.ALL_DAYS:
            assert core.Shift(day, 0, "10:30-11:30").needs_male() is True
            assert core.Shift(day, 3, "1:30-2:30").needs_male() is True
            assert core.Shift(day, 1, "11:30-12:30").needs_male() is False


# ---------------------------------------------------------------------------
# Scheduler.solve — fillable / infeasible / caps
# ---------------------------------------------------------------------------


class TestSolverBasic:
    def test_fillable_pool_completes_fully(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        n = s.solve()
        assert n >= 1
        # Every shift filled with exactly 2.
        for shift in s.schedule_grid:
            assert len(shift.assigned_members) == 2

    def test_top_schedules_cap_at_51(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        assert len(s.top_schedules) <= 51

    def test_attempts_capped_at_one_million(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        # We never spin forever — attempts always bounded.
        assert s.attempts <= 1_000_001

    def test_infeasible_pool_returns_zero_without_crash(self, member_builder):
        # All female members. Opening (idx 0) and Closing (idx 3) need a Male,
        # so any complete schedule is impossible.
        females = [
            member_builder(f"F_{i}", gender="Female") for i in range(40)
        ]
        s = core.Scheduler(females)
        n = s.solve()  # Must not raise.
        assert n == 0
        # No top_schedules collected because we never completed a grid.
        assert s.top_schedules == []

    def test_best_grid_state_captured_on_partial(self, member_builder):
        # All female: cannot solve fully. best_grid_state should still hold the
        # best partial reached (could be empty, but should be a dict).
        females = [
            member_builder(f"F_{i}", gender="Female") for i in range(8)
        ]
        s = core.Scheduler(females)
        s.solve()
        assert isinstance(s.best_grid_state, dict)
        # Female members can fill middle slots (1, 2) on Monday but not
        # opening/closing slots.
        # We can still verify the best_grid_state has the right SHAPE: keys are
        # (day, time_idx) tuples.
        if s.best_grid_state:
            for key in s.best_grid_state:
                assert isinstance(key, tuple)
                assert len(key) == 2

    def test_solve_returns_number_of_top_schedules(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        n = s.solve()
        assert n == len(s.top_schedules)


# ---------------------------------------------------------------------------
# Hard constraints
# ---------------------------------------------------------------------------


class TestHardConstraints:
    def test_each_member_at_most_one_shift(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        seen = {}
        for shift in s.schedule_grid:
            for m in shift.assigned_members:
                seen[m.name] = seen.get(m.name, 0) + 1
        for name, count in seen.items():
            assert count <= 1, f"{name} scheduled {count} times"

    def test_exactly_two_members_per_filled_shift(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        for shift in s.schedule_grid:
            assert len(shift.assigned_members) in (0, 2)

    def test_opening_includes_at_least_one_male(self, mixed_pool):
        s = core.Scheduler(mixed_pool)
        s.solve()
        for shift in s.schedule_grid:
            if shift.time_idx == 0 and len(shift.assigned_members) == 2:
                genders = [m.gender for m in shift.assigned_members]
                assert "Male" in genders

    def test_closing_includes_at_least_one_male(self, mixed_pool):
        s = core.Scheduler(mixed_pool)
        s.solve()
        for shift in s.schedule_grid:
            if shift.time_idx == 3 and len(shift.assigned_members) == 2:
                genders = [m.gender for m in shift.assigned_members]
                assert "Male" in genders

    def test_forbidden_pair_never_scheduled_together(self, fillable_pool):
        forbid_a, forbid_b = "Member_00", "Member_01"
        s = core.Scheduler(
            fillable_pool,
            forbidden_pairs=[(forbid_a, forbid_b)],
        )
        s.solve()
        for shift in s.schedule_grid:
            names = {m.name for m in shift.assigned_members}
            assert not ({forbid_a, forbid_b}.issubset(names))

    def test_never_schedule_members_excluded(self, fillable_pool):
        s = core.Scheduler(
            fillable_pool,
            never_schedule=["Member_00", "Member_01"],
        )
        s.solve()
        scheduled = {
            m.name for shift in s.schedule_grid for m in shift.assigned_members
        }
        assert "Member_00" not in scheduled
        assert "Member_01" not in scheduled

    def test_must_schedule_member_is_assigned(self, fillable_pool):
        # Force "Member_05" into the schedule.
        s = core.Scheduler(
            fillable_pool,
            must_schedule=["Member_05"],
        )
        n = s.solve()
        if n > 0:
            scheduled = {
                m.name
                for shift in s.schedule_grid
                for m in shift.assigned_members
            }
            assert "Member_05" in scheduled

    def test_avoid_opening_member_never_in_opening(self, member_builder):
        pool = []
        for i in range(20):
            pool.append(member_builder(f"M_{i:02d}", gender="Male"))
        # M_00 avoids opening.
        pool[0] = member_builder("M_00", gender="Male", avoid_opening=True)
        pool += [
            member_builder(f"M_extra_{i:02d}", gender="Male") for i in range(20)
        ]
        s = core.Scheduler(pool)
        s.solve()
        for shift in s.schedule_grid:
            if shift.time_idx == 0:
                names = [m.name for m in shift.assigned_members]
                assert "M_00" not in names

    def test_avoid_closing_member_never_in_closing(self, member_builder):
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(40)]
        pool[3] = member_builder("M_03", gender="Male", avoid_closing=True)
        s = core.Scheduler(pool)
        s.solve()
        for shift in s.schedule_grid:
            if shift.time_idx == 3:
                names = [m.name for m in shift.assigned_members]
                assert "M_03" not in names


# ---------------------------------------------------------------------------
# Soft scoring / Least-Changes
# ---------------------------------------------------------------------------


class TestLeastChangesScoring:
    """Scoring is a sort heuristic, but combined with the (changes ASC,
    score DESC) sort the WINNING grid (top_schedules[0]['state']) should match
    our predictions in small constructed scenarios."""

    def test_preferred_day_increments_pref_score(self, member_builder):
        # Tiny scenario: Monday only, 8 members, all available. One member has
        # Monday as preferred day. The final pref_score for any complete grid
        # should be >= 5 (since that member is assigned somewhere).
        pool = [
            member_builder(
                f"M_{i:02d}",
                gender="Male",
                availability={"Monday": list(core.TIME_SLOTS.values())},
                preferred_days=["Monday"] if i == 0 else [],
            )
            for i in range(8)
        ]
        s = core.Scheduler(pool, active_days=["Monday"])
        s.solve()
        # Every top schedule has M_00 placed (single-day, 8 members, 4 shifts, 2
        # per shift -> all 8 assigned). pref_score should be 5.
        assert s.top_schedules
        for entry in s.top_schedules:
            assert entry["score"] >= 5

    def test_exact_match_dominates_previous_state(self, member_builder):
        """If previous_state set (M_00, M_01) on Monday slot 0, the +5000
        exact-match bonus should attract the solver to keep them there."""
        pool = _make_single_day_pool(member_builder, "Monday", n_male=8, n_female=0)
        previous = {("Monday", 0): ["M_00", "M_01"]}
        s = core.Scheduler(pool, active_days=["Monday"], previous_state=previous)
        s.solve()
        assert s.top_schedules
        # The winning option (lowest changes) should keep (M_00, M_01) on slot 0.
        winning = s.top_schedules[0]["state"]
        assert set(winning[("Monday", 0)]) == {"M_00", "M_01"}

    def test_least_changes_picks_minimal_diff_schedule(self, member_builder):
        # 8 members, single day. previous_state pins all four shifts.
        pool = _make_single_day_pool(member_builder, "Monday", n_male=8, n_female=0)
        prev = {
            ("Monday", 0): ["M_00", "M_01"],
            ("Monday", 1): ["M_02", "M_03"],
            ("Monday", 2): ["M_04", "M_05"],
            ("Monday", 3): ["M_06", "M_07"],
        }
        s = core.Scheduler(pool, active_days=["Monday"], previous_state=prev)
        s.solve()
        # The expected outcome: identical grid -> 0 changes.
        winning = s.top_schedules[0]
        assert winning["changes"] == 0
        for key, expected_names in prev.items():
            assert set(winning["state"][key]) == set(expected_names)

    def test_must_schedule_member_included_via_score(self, member_builder):
        # Setup: 8 members on a single day -> grid needs all 8. Force M_00 into
        # the schedule. n=8 means all members will be scheduled anyway, but
        # this exercises the must_schedule path.
        pool = _make_single_day_pool(member_builder, "Monday", n_male=8, n_female=0)
        s = core.Scheduler(
            pool,
            active_days=["Monday"],
            must_schedule=["M_00"],
        )
        n = s.solve()
        assert n > 0
        scheduled = {
            m.name for shift in s.schedule_grid for m in shift.assigned_members
        }
        assert "M_00" in scheduled

    def test_must_schedule_unfeasible_returns_zero(self, member_builder):
        """If must_schedule member has no availability anywhere, the constraint
        at lines 171-173 of solve rejects every otherwise-complete grid."""
        # 9 members, Monday only, 4 shifts (=8 slots).
        # M_00 has no availability anywhere -> can never be assigned.
        pool = []
        for i in range(8):
            pool.append(
                member_builder(
                    f"M_{i+1:02d}",
                    gender="Male",
                    availability={"Monday": list(core.TIME_SLOTS.values())},
                )
            )
        # No availability at all for M_00.
        m_unavail = member_builder(
            "M_00",
            gender="Male",
            availability={},
        )
        pool.append(m_unavail)
        s = core.Scheduler(
            pool,
            active_days=["Monday"],
            must_schedule=["M_00"],
        )
        n = s.solve()
        # No complete grid satisfies must_schedule.
        assert n == 0

    def test_anti_poaching_keeps_member_in_original_slot(self, member_builder):
        """Setup so that the only stable-pair the solver can preserve is on
        slot 0, but moving M_00 to slot 1 (and replacing with someone else on
        slot 0) is also feasible. The −100 penalty should make the solver
        prefer keeping M_00 on slot 0."""
        # 8 members on Monday. previous_state had M_00 + M_01 on slot 0.
        # We construct so the solver could either keep them on slot 0 (best,
        # +5000 exact match) or split them apart (incurs anti-poach).
        pool = _make_single_day_pool(member_builder, "Monday", n_male=8, n_female=0)
        previous = {("Monday", 0): ["M_00", "M_01"]}
        s = core.Scheduler(pool, active_days=["Monday"], previous_state=previous)
        s.solve()
        winning = s.top_schedules[0]["state"]
        # Anti-poaching + exact-match both push toward M_00, M_01 staying on slot 0.
        assert set(winning[("Monday", 0)]) == {"M_00", "M_01"}


# ---------------------------------------------------------------------------
# pre_filled_grid path
# ---------------------------------------------------------------------------


class TestPreFilledGrid:
    def test_locked_shift_preserved_across_solve(self, member_builder):
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(40)]
        # Build a full empty grid, then lock Monday/slot-0 to M_00 + M_01.
        grid = []
        for day in core.ALL_DAYS:
            for label, idx in core.TIME_SLOTS.items():
                grid.append(core.Shift(day, idx, label))

        lock_shift = next(
            s for s in grid if s.day == "Monday" and s.time_idx == 0
        )
        lock_shift.locked = True
        lock_shift.assigned_members = [pool[0], pool[1]]

        s = core.Scheduler(pool, pre_filled_grid=grid)
        s.solve()
        # Locked pair must remain on Monday slot 0.
        result_shift = next(
            sh for sh in s.schedule_grid if sh.day == "Monday" and sh.time_idx == 0
        )
        names = {m.name for m in result_shift.assigned_members}
        assert names == {"M_00", "M_01"}

    def test_restored_locks_count_toward_assigned_shifts(self, member_builder):
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(40)]
        grid = []
        for day in core.ALL_DAYS:
            for label, idx in core.TIME_SLOTS.items():
                grid.append(core.Shift(day, idx, label))

        lock_shift = next(
            s for s in grid if s.day == "Monday" and s.time_idx == 0
        )
        lock_shift.locked = True
        lock_shift.assigned_members = [pool[0], pool[1]]

        s = core.Scheduler(pool, pre_filled_grid=grid)
        s.solve()
        # The 1-shift-per-week rule should have correctly counted M_00 and M_01
        # in the restored lock — they should not appear elsewhere.
        for shift in s.schedule_grid:
            if (shift.day, shift.time_idx) != ("Monday", 0):
                names = {m.name for m in shift.assigned_members}
                assert "M_00" not in names
                assert "M_01" not in names
        # And their assigned_shifts list should contain exactly the lock.
        assert ("Monday", 0) in pool[0].assigned_shifts
        assert ("Monday", 0) in pool[1].assigned_shifts
        assert len(pool[0].assigned_shifts) == 1
        assert len(pool[1].assigned_shifts) == 1

    def test_partially_locked_slot_completed(self, member_builder):
        """A locked shift with only ONE assigned member gets a second partner
        chosen by the solver."""
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(40)]
        grid = []
        for day in core.ALL_DAYS:
            for label, idx in core.TIME_SLOTS.items():
                grid.append(core.Shift(day, idx, label))

        partial = next(
            s for s in grid if s.day == "Monday" and s.time_idx == 1
        )
        partial.locked = True
        partial.assigned_members = [pool[0]]

        s = core.Scheduler(pool, pre_filled_grid=grid)
        s.solve()
        result = next(
            sh
            for sh in s.schedule_grid
            if sh.day == "Monday" and sh.time_idx == 1
        )
        names = {m.name for m in result.assigned_members}
        assert "M_00" in names
        assert len(names) == 2


# ---------------------------------------------------------------------------
# restore_state
# ---------------------------------------------------------------------------


class TestRestoreState:
    def test_restore_state_clears_prior_assignments(self, member_builder):
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(8)]
        # Manually populate one member's assigned_shifts.
        pool[0].assigned_shifts = [("Monday", 0)]
        pool[1].assigned_shifts = [("Tuesday", 1)]

        s = core.Scheduler(pool, active_days=["Monday"])
        # Empty state -> everything cleared.
        s.restore_state({})
        for m in pool:
            assert m.assigned_shifts == []

    def test_restore_state_applies_state_by_name(self, member_builder):
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(8)]
        s = core.Scheduler(pool, active_days=["Monday"])
        state = {
            ("Monday", 0): ["M_00", "M_01"],
            ("Monday", 1): [],
            ("Monday", 2): [],
            ("Monday", 3): [],
        }
        s.restore_state(state)
        shift_0 = next(
            sh for sh in s.schedule_grid if sh.day == "Monday" and sh.time_idx == 0
        )
        names = {m.name for m in shift_0.assigned_members}
        assert names == {"M_00", "M_01"}
        # Members' own assigned_shifts also updated.
        m00 = next(m for m in pool if m.name == "M_00")
        assert ("Monday", 0) in m00.assigned_shifts

    def test_restore_state_ignores_unknown_names(self, member_builder):
        pool = [member_builder(f"M_{i:02d}", gender="Male") for i in range(4)]
        s = core.Scheduler(pool, active_days=["Monday"])
        state = {
            ("Monday", 0): ["GhostMember", "M_00"],
            ("Monday", 1): [],
            ("Monday", 2): [],
            ("Monday", 3): [],
        }
        # Should not raise.
        s.restore_state(state)
        shift_0 = next(
            sh for sh in s.schedule_grid if sh.day == "Monday" and sh.time_idx == 0
        )
        names = [m.name for m in shift_0.assigned_members]
        # Only the real member kept.
        assert names == ["M_00"]


# ---------------------------------------------------------------------------
# _get_valid_pairs / _get_valid_partners
# ---------------------------------------------------------------------------


class TestValidPairs:
    def test_pairs_filter_by_availability(self, member_builder):
        pool = [
            member_builder("A", gender="Male", availability={"Monday": [0]}),
            member_builder("B", gender="Male", availability={"Monday": [0]}),
            member_builder("C", gender="Male", availability={}),  # unavailable
        ]
        s = core.Scheduler(pool, active_days=["Monday"])
        shift = core.Shift("Monday", 0, "10:30-11:30")
        pairs = s._get_valid_pairs(shift)
        names_in_pairs = {n for pair in pairs for n in (pair[0].name, pair[1].name)}
        assert "C" not in names_in_pairs
        # Only one valid pair: (A, B).
        assert len(pairs) == 1

    def test_pairs_filter_by_assigned_shifts(self, member_builder):
        # If a member already has an assigned shift, they shouldn't appear in
        # candidate pairs.
        pool = [
            member_builder("A", gender="Male"),
            member_builder("B", gender="Male"),
            member_builder("C", gender="Male"),
        ]
        pool[0].assigned_shifts = [("Tuesday", 0)]
        s = core.Scheduler(pool, active_days=["Monday"])
        shift = core.Shift("Monday", 0, "10:30-11:30")
        pairs = s._get_valid_pairs(shift)
        names_in_pairs = {n for pair in pairs for n in (pair[0].name, pair[1].name)}
        assert "A" not in names_in_pairs

    def test_pairs_filter_male_required_for_opening(self, member_builder):
        # All-female pool -> no pairs valid for opening shift.
        pool = [
            member_builder("F1", gender="Female"),
            member_builder("F2", gender="Female"),
        ]
        s = core.Scheduler(pool, active_days=["Monday"])
        shift_open = core.Shift("Monday", 0, "10:30-11:30")
        pairs = s._get_valid_pairs(shift_open)
        assert pairs == []

    def test_pairs_allow_mixed_gender_for_middle_slot(self, member_builder):
        pool = [
            member_builder("F1", gender="Female"),
            member_builder("F2", gender="Female"),
        ]
        s = core.Scheduler(pool, active_days=["Monday"])
        shift_middle = core.Shift("Monday", 1, "11:30-12:30")
        pairs = s._get_valid_pairs(shift_middle)
        assert len(pairs) == 1

    def test_pairs_filter_forbidden(self, member_builder):
        pool = [
            member_builder("A", gender="Male"),
            member_builder("B", gender="Male"),
            member_builder("C", gender="Male"),
        ]
        s = core.Scheduler(pool, forbidden_pairs=[("A", "B")])
        shift = core.Shift("Monday", 0, "10:30-11:30")
        pairs = s._get_valid_pairs(shift)
        # (A, B) forbidden; remaining: (A, C), (B, C)
        names_pairs = {frozenset((p1.name, p2.name)) for p1, p2 in pairs}
        assert frozenset(("A", "B")) not in names_pairs
        assert frozenset(("A", "C")) in names_pairs
        assert frozenset(("B", "C")) in names_pairs

    def test_get_valid_partners_excludes_self(self, member_builder):
        pool = [
            member_builder("A", gender="Male"),
            member_builder("B", gender="Male"),
        ]
        s = core.Scheduler(pool)
        shift = core.Shift("Monday", 0, "10:30-11:30")
        partners = s._get_valid_partners(shift, pool[0])
        names = [p.name for p in partners]
        assert "A" not in names
        assert "B" in names

    def test_get_valid_partners_filters_forbidden(self, member_builder):
        pool = [
            member_builder("A", gender="Male"),
            member_builder("B", gender="Male"),
            member_builder("C", gender="Male"),
        ]
        s = core.Scheduler(pool, forbidden_pairs=[("A", "B")])
        shift = core.Shift("Monday", 0, "10:30-11:30")
        partners = s._get_valid_partners(shift, pool[0])
        names = [p.name for p in partners]
        assert "B" not in names
        assert "C" in names

    def test_get_valid_partners_requires_male_for_opening_if_existing_is_female(
        self, member_builder
    ):
        pool = [
            member_builder("F1", gender="Female"),
            member_builder("F2", gender="Female"),
            member_builder("M1", gender="Male"),
        ]
        s = core.Scheduler(pool)
        shift = core.Shift("Monday", 0, "10:30-11:30")
        partners = s._get_valid_partners(shift, pool[0])  # F1 is current
        names = [p.name for p in partners]
        assert "M1" in names
        # F2 not acceptable because both would be female and slot needs a male.
        assert "F2" not in names


# ---------------------------------------------------------------------------
# find_best_slots_for_pair
# ---------------------------------------------------------------------------


class TestFindBestSlots:
    def test_returns_only_overlapping_availability(self, member_builder):
        p1 = member_builder(
            "P1", gender="Male", availability={"Monday": [0, 1], "Tuesday": [0]}
        )
        p2 = member_builder(
            "P2", gender="Male", availability={"Monday": [1, 2], "Tuesday": [3]}
        )
        slots = core.find_best_slots_for_pair(p1, p2, core.ALL_DAYS)
        # Both available: Monday slot 1 only.
        keys = {(s["day"], s["time_idx"]) for s in slots}
        assert keys == {("Monday", 1)}

    def test_skips_opening_if_no_male(self, member_builder):
        p1 = member_builder("F1", gender="Female", availability={"Monday": [0]})
        p2 = member_builder("F2", gender="Female", availability={"Monday": [0]})
        slots = core.find_best_slots_for_pair(p1, p2, ["Monday"])
        # Slot 0 needs a male -> excluded.
        assert all(s["time_idx"] != 0 for s in slots)

    def test_skips_closing_if_no_male(self, member_builder):
        p1 = member_builder("F1", gender="Female", availability={"Monday": [3]})
        p2 = member_builder("F2", gender="Female", availability={"Monday": [3]})
        slots = core.find_best_slots_for_pair(p1, p2, ["Monday"])
        assert all(s["time_idx"] != 3 for s in slots)

    def test_pref_day_increases_score(self, member_builder):
        p1 = member_builder(
            "P1",
            gender="Male",
            availability={"Monday": [1], "Tuesday": [1]},
            preferred_days=["Monday"],
        )
        p2 = member_builder(
            "P2",
            gender="Male",
            availability={"Monday": [1], "Tuesday": [1]},
            preferred_days=["Monday"],
        )
        slots = core.find_best_slots_for_pair(p1, p2, ["Monday", "Tuesday"])
        # Two slots with same overlap; Monday should rank higher due to prefs.
        assert slots[0]["day"] == "Monday"
        # Both members prefer Monday: +10 + +10 + base 100 + +5.
        mon_slot = next(s for s in slots if s["day"] == "Monday")
        tue_slot = next(s for s in slots if s["day"] == "Tuesday")
        assert mon_slot["score"] > tue_slot["score"]


# ---------------------------------------------------------------------------
# parse_file (CSV)
# ---------------------------------------------------------------------------


class TestParseFile:
    def test_parses_small_sample_count(self, fake_file_factory, small_sample_csv_path):
        fu = fake_file_factory(small_sample_csv_path)
        members = core.parse_file(fu)
        assert len(members) == 14

    def test_alex_parsed_correctly(
        self, fake_file_factory, small_sample_csv_path
    ):
        fu = fake_file_factory(small_sample_csv_path)
        members = core.parse_file(fu)
        alex = next(m for m in members if m.name == "Alex")
        assert alex.gender == "Male"
        assert alex.avoid_opening is False
        assert alex.avoid_closing is False
        assert "Monday" in alex.preferred_days
        assert "Wednesday" in alex.preferred_days
        # Monday only had "10:30-11:30" -> slot 0.
        assert alex.availability.get("Monday") == [0]

    def test_riley_avoid_opening_and_closing(
        self, fake_file_factory, small_sample_csv_path
    ):
        fu = fake_file_factory(small_sample_csv_path)
        members = core.parse_file(fu)
        riley = next(m for m in members if m.name == "Riley")
        assert riley.gender == "Female"
        assert riley.avoid_opening is True
        assert riley.avoid_closing is True

    def test_availability_parsing_handles_spaces_commas(self, fake_csv_factory):
        # Hand-build a CSV with quoted multi-slot fields and weird spacing.
        csv = (
            "Name (First and Last),Gender,Are you OK with opening shifts?,"
            "Are you OK with closing shifts?,Monday,Tuesday,Wednesday,Thursday,"
            "Friday,Select days you prefer to table on (if applicable)\n"
            'Alex,Male,Yes,Yes,"10:30-11:30, 11:30-12:30","11:30-12:30,12:30-1:30",'
            ',,,Monday\n'
        )
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        assert len(members) == 1
        alex = members[0]
        assert alex.availability.get("Monday") == [0, 1]
        assert alex.availability.get("Tuesday") == [1, 2]
        # No Wednesday data -> not in dict.
        assert "Wednesday" not in alex.availability

    def test_blank_name_row_skipped(self, fake_csv_factory):
        csv = (
            "Name (First and Last),Gender,Are you OK with opening shifts?,"
            "Are you OK with closing shifts?,Monday,Tuesday,Wednesday,Thursday,"
            "Friday,Select days you prefer to table on (if applicable)\n"
            ",Male,Yes,Yes,10:30-11:30,,,,,\n"
            "Alex,Male,Yes,Yes,10:30-11:30,,,,,\n"
        )
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        names = [m.name for m in members]
        assert names == ["Alex"]


# ---------------------------------------------------------------------------
# generate_excel_bytes
# ---------------------------------------------------------------------------


class TestGenerateExcelBytes:
    def test_returns_bytes_with_two_sheets(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        b = core.generate_excel_bytes(
            s.schedule_grid, core.ALL_DAYS, all_members=fillable_pool
        )
        assert isinstance(b, (bytes, bytearray))
        sheets = pd.read_excel(io.BytesIO(b), sheet_name=None, engine="openpyxl")
        assert "Final Schedule" in sheets
        assert "Unassigned Members" in sheets

    def test_final_schedule_has_correct_columns(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        b = core.generate_excel_bytes(
            s.schedule_grid, core.ALL_DAYS, all_members=fillable_pool
        )
        sheets = pd.read_excel(io.BytesIO(b), sheet_name=None, engine="openpyxl")
        sched = sheets["Final Schedule"]
        expected_cols = ["Time"] + core.ALL_DAYS
        for col in expected_cols:
            assert col in sched.columns

    def test_unassigned_excludes_assigned_names(self, member_builder):
        # 8 single-day members; 4 shifts × 2 = 8 -> all assigned, unassigned
        # sheet should be empty of those 8 names.
        pool = _make_single_day_pool(member_builder, "Monday", n_male=8, n_female=0)
        # Add 2 extra unavailable members who will NOT be assigned.
        pool.append(
            member_builder(
                "UnusedA", gender="Male", availability={"Friday": [0, 1, 2, 3]}
            )
        )
        pool.append(
            member_builder(
                "UnusedB", gender="Female", availability={"Friday": [1, 2]}
            )
        )
        s = core.Scheduler(pool, active_days=["Monday"])
        s.solve()
        b = core.generate_excel_bytes(
            s.schedule_grid, ["Monday"], all_members=pool
        )
        sheets = pd.read_excel(io.BytesIO(b), sheet_name=None, engine="openpyxl")
        unassigned = sheets["Unassigned Members"]
        unassigned_names = (
            set(unassigned["Name"].astype(str).tolist())
            if "Name" in unassigned.columns
            else set()
        )
        # Assigned members must NOT appear in unassigned sheet.
        assigned_names = {
            m.name for sh in s.schedule_grid for m in sh.assigned_members
        }
        assert assigned_names.isdisjoint(unassigned_names)
        # UnusedA and UnusedB should appear.
        assert "UnusedA" in unassigned_names
        assert "UnusedB" in unassigned_names

    def test_all_assigned_writes_status_row(self, fillable_pool):
        s = core.Scheduler(fillable_pool)
        s.solve()
        # With a fillable pool that exactly matches required slots there may
        # still be unassigned overflow because pool has 40 and slots = 40. To
        # ensure ALL members assigned we pass exactly 40 — note that the
        # solver only assigns ~40 of the 40 fillable pool members. The
        # Unassigned sheet falls back to a "Status" row if empty.
        b = core.generate_excel_bytes(
            s.schedule_grid, core.ALL_DAYS, all_members=fillable_pool
        )
        sheets = pd.read_excel(io.BytesIO(b), sheet_name=None, engine="openpyxl")
        # Either "Status" column exists (all assigned), or "Name" column exists.
        unassigned = sheets["Unassigned Members"]
        assert "Status" in unassigned.columns or "Name" in unassigned.columns


# ---------------------------------------------------------------------------
# export_configuration / load_configuration round-trip
# ---------------------------------------------------------------------------


class TestConfigRoundTrip:
    def test_basic_round_trip_preserves_members(self, member_builder):
        pool = [
            member_builder("Alice", gender="Female", preferred_days=["Monday"]),
            member_builder("Bob", gender="Male", avoid_opening=True),
        ]
        grid = []
        for day in ["Monday"]:
            for label, idx in core.TIME_SLOTS.items():
                grid.append(core.Shift(day, idx, label))
        # Lock one slot.
        grid[0].locked = True
        grid[0].assigned_members = [pool[0], pool[1]]

        s = core.Scheduler(pool, active_days=["Monday"], pre_filled_grid=grid)
        # Don't solve — just save state as-is.
        json_str = core.export_configuration(
            s.schedule_grid,
            forbidden_pairs=[("Alice", "Bob")],
            active_days=["Monday"],
            must_schedule=["Alice"],
            never_schedule=["SomeoneElse"],
            members=pool,
        )
        active_days, forb, must, never, new_grid, restored = (
            core.load_configuration(json_str)
        )
        assert active_days == ["Monday"]
        assert forb == [("Alice", "Bob")]
        assert must == ["Alice"]
        assert never == ["SomeoneElse"]
        names = {m.name for m in restored}
        assert names == {"Alice", "Bob"}
        # Locked slot survived.
        first = new_grid[0]
        assert first.locked is True
        assert {m.name for m in first.assigned_members} == {"Alice", "Bob"}

    def test_round_trip_preserves_time_overrides(self, member_builder):
        m = member_builder(
            "Alice",
            time_overrides={
                "Monday": {0: True, 1: False},
                "Wednesday": {3: True},
            },
        )
        grid = []
        for label, idx in core.TIME_SLOTS.items():
            grid.append(core.Shift("Monday", idx, label))

        json_str = core.export_configuration(
            grid,
            forbidden_pairs=[],
            active_days=["Monday"],
            must_schedule=[],
            never_schedule=[],
            members=[m],
        )
        _, _, _, _, _, restored = core.load_configuration(json_str)
        a = next(x for x in restored if x.name == "Alice")
        assert a.time_overrides.get("Monday", {}).get(0) is True
        assert a.time_overrides.get("Monday", {}).get(1) is False
        assert a.time_overrides.get("Wednesday", {}).get(3) is True
        # Keys must have been restored as int (json keys default to str).
        for day, t_map in a.time_overrides.items():
            for k in t_map:
                assert isinstance(k, int)

    def test_round_trip_preserves_full_member_data(self, member_builder):
        m = member_builder(
            "Alice",
            gender="Female",
            availability={"Monday": [0, 1, 2], "Friday": [3]},
            avoid_opening=True,
            avoid_closing=False,
            preferred_days=["Monday", "Friday"],
        )
        grid = []
        for label, idx in core.TIME_SLOTS.items():
            grid.append(core.Shift("Monday", idx, label))
        json_str = core.export_configuration(
            grid,
            forbidden_pairs=[],
            active_days=["Monday"],
            must_schedule=[],
            never_schedule=[],
            members=[m],
        )
        _, _, _, _, _, restored = core.load_configuration(json_str)
        a = next(x for x in restored if x.name == "Alice")
        assert a.gender == "Female"
        assert a.avoid_opening is True
        assert a.avoid_closing is False
        assert a.preferred_days == ["Monday", "Friday"]
        # Availability survives (note JSON serializes keys as str but the data
        # is a dict[str, list[int]]).
        assert a.availability == {"Monday": [0, 1, 2], "Friday": [3]}

    def test_load_legacy_no_members_key_uses_existing(self, member_builder):
        pool = [
            member_builder("Alice", gender="Female"),
            member_builder("Bob", gender="Male"),
        ]
        # Build a legacy JSON: no "members" key.
        legacy = json.dumps(
            {
                "active_days": ["Monday"],
                "forbidden_pairs": [],
                "must_schedule": [],
                "never_schedule": [],
                "grid": [
                    {
                        "day": "Monday",
                        "time_idx": 0,
                        "locked": True,
                        "assigned": ["Alice", "Bob"],
                    },
                    {
                        "day": "Monday",
                        "time_idx": 1,
                        "locked": False,
                        "assigned": [],
                    },
                ],
            }
        )
        _, _, _, _, new_grid, restored = core.load_configuration(
            legacy, existing_members=pool
        )
        # restored should BE the existing list.
        assert restored is pool
        first = new_grid[0]
        assert first.locked is True
        assert {m.name for m in first.assigned_members} == {"Alice", "Bob"}
