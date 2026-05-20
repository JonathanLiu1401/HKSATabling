"""Regression tests for specific backend bugs fixed in scheduler_core.py.

Each test corresponds to a single bug-fix; if any of these starts failing
again, it means the fix has regressed.
"""

import json

import pytest

import scheduler_core as core


# ---------------------------------------------------------------------------
# Bug #4: load_configuration legacy branch left stale assigned_shifts.
# ---------------------------------------------------------------------------


class TestBug4LegacyConfigClearsAssignedShifts:
    """When `load_configuration` falls back to `existing_members` (legacy save
    files with no `members` key), it must clear each member's
    `assigned_shifts` before re-applying assignments from the saved grid.
    Otherwise stale (day, time_idx) tuples survive and would later cause the
    `_get_valid_pairs` 1-shift-per-week filter to drop the member."""

    def test_stale_assigned_shifts_cleared_on_legacy_load(self, member_builder):
        alice = member_builder("Alice", gender="Female")
        bob = member_builder("Bob", gender="Male")
        # Manually populate stale state — pretend Alice was previously
        # scheduled on Friday slot 3.
        alice.assigned_shifts = [("Friday", 3)]
        bob.assigned_shifts = []

        # Legacy JSON: NO "members" key. Saved grid puts Alice on Monday/slot 0.
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
                        "locked": False,
                        "assigned": ["Alice", "Bob"],
                    },
                ],
            }
        )
        _, _, _, _, _, restored = core.load_configuration(
            legacy, existing_members=[alice, bob]
        )
        # Stale entry must be gone — only the saved-grid assignment remains.
        assert alice.assigned_shifts == [("Monday", 0)]
        assert bob.assigned_shifts == [("Monday", 0)]

    def test_legacy_load_clears_even_when_grid_does_not_reassign(self, member_builder):
        alice = member_builder("Alice", gender="Female")
        # Stale entry that should be wiped.
        alice.assigned_shifts = [("Friday", 3)]

        # Legacy JSON where Alice is NOT in any grid slot.
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
                        "locked": False,
                        "assigned": [],
                    },
                ],
            }
        )
        core.load_configuration(legacy, existing_members=[alice])
        # Alice's stale ("Friday", 3) must be gone.
        assert alice.assigned_shifts == []


# ---------------------------------------------------------------------------
# Bug #8: parse_file raises ValueError when no Name column exists.
# ---------------------------------------------------------------------------


class TestBug8ParseFileMissingNameColumn:
    def test_parse_file_raises_when_name_column_missing(self, fake_csv_factory):
        # CSV with NO name column — only Gender, days, etc.
        csv = (
            "Gender,Are you OK with opening shifts?,Are you OK with closing shifts?,"
            "Monday,Tuesday,Wednesday,Thursday,Friday,"
            "Select days you prefer to table on (if applicable)\n"
            "Male,Yes,Yes,10:30-11:30,,,,,\n"
        )
        fu = fake_csv_factory(csv)
        with pytest.raises(ValueError) as excinfo:
            core.parse_file(fu)
        assert "Name" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Bug #9: name column detection used to be order-sensitive — a later
# column containing "name" could overwrite the earlier match. The fix uses
# "first match wins" guards so col_map["name"] sticks to the first match.
# ---------------------------------------------------------------------------


class TestBug9NameColumnOrderIndependence:
    def test_first_name_column_wins_when_later_column_also_has_name(
        self, fake_csv_factory
    ):
        # Column 1 is the canonical "Name (First and Last)". A later column
        # contains "Display Name" — under the OLD logic this could overwrite
        # col_map["name"], and parse_file would return the wrong values.
        csv = (
            "Name (First and Last),Gender,Display Name,"
            "Are you OK with opening shifts?,Are you OK with closing shifts?,"
            "Monday,Tuesday,Wednesday,Thursday,Friday,"
            "Select days you prefer to table on (if applicable)\n"
            "RealAlice,Male,DECOY1,Yes,Yes,10:30-11:30,,,,,\n"
            "RealBob,Female,DECOY2,Yes,Yes,11:30-12:30,,,,,\n"
        )
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        names = sorted(m.name for m in members)
        # If the bug recurs, names would be ["DECOY1", "DECOY2"].
        assert names == ["RealAlice", "RealBob"]


# ---------------------------------------------------------------------------
# Bug #10: substring matching on Yes/No was a false-positive trap. "No
# preference" contains "no" and would set avoid_opening=True. The fix uses
# exact-match (`val in ("no", "n")`).
# ---------------------------------------------------------------------------


class TestBug10YesNoExactMatch:
    @staticmethod
    def _build_csv(open_val, close_val):
        return (
            "Name (First and Last),Gender,Are you OK with opening shifts?,"
            "Are you OK with closing shifts?,Monday,Tuesday,Wednesday,Thursday,"
            "Friday,Select days you prefer to table on (if applicable)\n"
            f"Alice,Female,{open_val},{close_val},10:30-11:30,,,,,\n"
        )

    def test_no_preference_does_not_set_avoid_opening(self, fake_csv_factory):
        # Under the OLD substring rule, "No preference" would set avoid_opening
        # because "no" in "no preference" is True. Under the new exact-match
        # rule it should NOT.
        csv = self._build_csv("No preference", "No preference")
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        alice = next(m for m in members if m.name == "Alice")
        assert alice.avoid_opening is False
        assert alice.avoid_closing is False

    def test_exact_no_sets_avoid_opening_and_closing(self, fake_csv_factory):
        csv = self._build_csv("No", "No")
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        alice = next(m for m in members if m.name == "Alice")
        assert alice.avoid_opening is True
        assert alice.avoid_closing is True

    def test_yes_does_not_set_avoid_flags(self, fake_csv_factory):
        csv = self._build_csv("Yes", "Yes")
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        alice = next(m for m in members if m.name == "Alice")
        assert alice.avoid_opening is False
        assert alice.avoid_closing is False

    def test_short_n_also_sets_avoid_opening(self, fake_csv_factory):
        # Per fix: `val in ("no", "n")` — the shorthand "n" also flags avoid.
        csv = self._build_csv("n", "n")
        fu = fake_csv_factory(csv)
        members = core.parse_file(fu)
        alice = next(m for m in members if m.name == "Alice")
        assert alice.avoid_opening is True
        assert alice.avoid_closing is True
