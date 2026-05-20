"""Unit tests for helper functions defined in app.py.

We can't simply `import app`, because importing app.py runs `st.set_page_config`,
initializes session state via the Streamlit runtime, mounts the LocalStorage
component, and otherwise has heavy side effects. Instead, we parse app.py with
``ast``, lift out the function definitions we want to test, and ``exec`` them
into a controlled namespace where ``streamlit`` is replaced with a lightweight
fake that records toasts/warnings into lists.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

# Make sure the repo root is importable and load scheduler_core.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scheduler_core as core  # noqa: E402


# ---------------------------------------------------------------------------
# Fake streamlit module — just enough for the helpers we lift from app.py.
# ---------------------------------------------------------------------------
class _FakeSessionState(dict):
    """dict-like session state that also supports attribute-style access."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


def _build_fake_st():
    fake = types.SimpleNamespace()
    fake.session_state = _FakeSessionState()
    fake.toasts = []  # recorded by fake.toast()
    fake.warnings = []
    fake.errors = []
    fake.infos = []
    fake.successes = []

    def toast(msg, icon=None):
        fake.toasts.append({"msg": msg, "icon": icon})

    def warning(msg):
        fake.warnings.append(msg)

    def error(msg):
        fake.errors.append(msg)

    def info(msg):
        fake.infos.append(msg)

    def success(msg):
        fake.successes.append(msg)

    fake.toast = toast
    fake.warning = warning
    fake.error = error
    fake.info = info
    fake.success = success
    return fake


# ---------------------------------------------------------------------------
# Extract the helper function source from app.py.
# ---------------------------------------------------------------------------
HELPER_NAMES = (
    "capture_current_state",
    "find_member_by_str",
    "find_member_exact",
    "perform_overwrite_assign",
    "get_incomplete_slot_keys",
    "warn_if_understaffed",
    "restore_state_from_json",
)


def _extract_helpers():
    src = (REPO_ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    pieces = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES:
            pieces.append(ast.get_source_segment(src, node))
    return "\n\n".join(pieces)


HELPERS_SOURCE = _extract_helpers()


@pytest.fixture
def helpers_ns():
    """Return a namespace containing exec'd helpers + the fake streamlit module.

    The namespace mirrors app.py's globals enough for these helpers to run.
    """
    fake_st = _build_fake_st()
    ns = {
        "st": fake_st,
        "core": core,
        "copy": __import__("copy"),
    }
    exec(HELPERS_SOURCE, ns)
    # Initialize session_state defaults that the helpers rely on.
    fake_st.session_state["members"] = []
    fake_st.session_state["schedule_grid"] = []
    fake_st.session_state["never_schedule"] = []
    fake_st.session_state["must_schedule"] = []
    fake_st.session_state["forbidden_pairs"] = []
    fake_st.session_state["active_days"] = list(core.ALL_DAYS)
    fake_st.session_state["last_stable_state"] = {}
    fake_st.session_state["top_schedules"] = []
    return ns, fake_st


def _make_member(name, gender="Male", availability=None):
    if availability is None:
        availability = {d: list(core.TIME_SLOTS.values()) for d in core.ALL_DAYS}
    return core.Member(
        name=name,
        gender=gender,
        availability=availability,
        avoid_opening=False,
        avoid_closing=False,
        preferred_days=[],
        time_overrides={},
    )


# ===========================================================================
# find_member_by_str
# ===========================================================================
class TestFindMemberByStr:
    def test_returns_none_for_empty_string(self, helpers_ns):
        ns, _ = helpers_ns
        assert ns["find_member_by_str"]("") is None

    def test_returns_none_when_no_match(self, helpers_ns):
        ns, st = helpers_ns
        st.session_state["members"] = [_make_member("Alice")]
        assert ns["find_member_by_str"]("Nobody") is None

    def test_strips_status_icon_prefix(self, helpers_ns):
        ns, st = helpers_ns
        alice = _make_member("Alice")
        st.session_state["members"] = [alice]
        # Each of the recognized status-icon prefixes should resolve correctly.
        for icon in ("✅", "⛔", "⚠️", "🌟", "👤"):
            found = ns["find_member_by_str"](f"{icon} Alice")
            assert found is alice, f"Failed to strip prefix for icon: {icon}"

    def test_matches_bare_name(self, helpers_ns):
        ns, st = helpers_ns
        alice = _make_member("Alice")
        st.session_state["members"] = [alice]
        assert ns["find_member_by_str"]("Alice") is alice

    def test_does_not_strip_when_first_token_lacks_status_icon(self, helpers_ns):
        ns, st = helpers_ns
        # If the first space-separated token has no recognized icon, the full
        # name is used as the lookup key.
        first_last = _make_member("First Last")
        st.session_state["members"] = [first_last]
        assert ns["find_member_by_str"]("First Last") is first_last

    def test_preserves_internal_punctuation_in_name(self, helpers_ns):
        """Bug #11 regression: previously a stray .split(')') truncated names."""
        ns, st = helpers_ns
        tricky = _make_member("Hong Kong)Test")
        st.session_state["members"] = [tricky]
        # With the status-icon stripped, the remainder should still match exactly.
        found = ns["find_member_by_str"]("✅ Hong Kong)Test")
        assert found is tricky


# ===========================================================================
# find_member_exact
# ===========================================================================
class TestFindMemberExact:
    def test_returns_none_when_missing(self, helpers_ns):
        ns, _ = helpers_ns
        assert ns["find_member_exact"]("Nobody") is None

    def test_returns_member_when_match(self, helpers_ns):
        ns, st = helpers_ns
        bob = _make_member("Bob")
        st.session_state["members"] = [_make_member("Alice"), bob]
        assert ns["find_member_exact"]("Bob") is bob

    def test_does_not_strip_status_prefix(self, helpers_ns):
        ns, st = helpers_ns
        bob = _make_member("Bob")
        st.session_state["members"] = [bob]
        # find_member_exact requires the full literal name. A label with an
        # icon should NOT match — only find_member_by_str strips icons.
        assert ns["find_member_exact"]("✅ Bob") is None

    def test_handles_paren_in_name(self, helpers_ns):
        """Bug #11 regression: names with ')' must be treated as one whole string."""
        ns, st = helpers_ns
        tricky = _make_member("Hong Kong)Test")
        st.session_state["members"] = [tricky]
        assert ns["find_member_exact"]("Hong Kong)Test") is tricky


# ===========================================================================
# capture_current_state
# ===========================================================================
class TestCaptureCurrentState:
    def test_empty_grid_returns_empty_dict(self, helpers_ns):
        ns, st = helpers_ns
        st.session_state["schedule_grid"] = []
        assert ns["capture_current_state"]() == {}

    def test_captures_assigned_member_names_per_slot(self, helpers_ns):
        ns, st = helpers_ns
        alice = _make_member("Alice")
        bob = _make_member("Bob")
        s = core.Shift("Monday", 0, "10:30-11:30")
        s.assigned_members = [alice, bob]
        st.session_state["schedule_grid"] = [s]

        snapshot = ns["capture_current_state"]()
        assert snapshot == {("Monday", 0): ["Alice", "Bob"]}

    def test_captures_empty_shifts_as_empty_lists(self, helpers_ns):
        ns, st = helpers_ns
        empty = core.Shift("Tuesday", 1, "11:30-12:30")
        st.session_state["schedule_grid"] = [empty]
        snapshot = ns["capture_current_state"]()
        assert snapshot == {("Tuesday", 1): []}

    def test_preserves_member_order(self, helpers_ns):
        ns, st = helpers_ns
        a = _make_member("A")
        b = _make_member("B")
        s = core.Shift("Friday", 3, "1:30-2:30")
        s.assigned_members = [b, a]  # intentionally reversed
        st.session_state["schedule_grid"] = [s]
        snapshot = ns["capture_current_state"]()
        # capture_current_state preserves the existing list order.
        assert snapshot[("Friday", 3)] == ["B", "A"]


# ===========================================================================
# get_incomplete_slot_keys
# ===========================================================================
class TestGetIncompleteSlotKeys:
    def _build_grid(self):
        """4-slot Monday grid for compact reasoning."""
        grid = []
        for label, idx in core.TIME_SLOTS.items():
            grid.append(core.Shift("Monday", idx, label))
        return grid

    def test_all_empty_slots_reported(self, helpers_ns):
        ns, _ = helpers_ns
        grid = self._build_grid()
        # Exclude shift = a dummy, not in grid.
        decoy = core.Shift("Tuesday", 0, "10:30-11:30")
        result = ns["get_incomplete_slot_keys"](grid, decoy, ["Monday"])
        assert result == {("Monday", 0), ("Monday", 1), ("Monday", 2), ("Monday", 3)}

    def test_excludes_target_shift(self, helpers_ns):
        ns, _ = helpers_ns
        grid = self._build_grid()
        target = grid[0]
        result = ns["get_incomplete_slot_keys"](grid, target, ["Monday"])
        assert ("Monday", 0) not in result
        assert ("Monday", 1) in result

    def test_full_slots_not_reported(self, helpers_ns):
        ns, _ = helpers_ns
        grid = self._build_grid()
        grid[1].assigned_members = [_make_member("A"), _make_member("B")]
        decoy = core.Shift("Tuesday", 0, "10:30-11:30")
        result = ns["get_incomplete_slot_keys"](grid, decoy, ["Monday"])
        assert ("Monday", 1) not in result

    def test_partial_slots_are_reported(self, helpers_ns):
        ns, _ = helpers_ns
        grid = self._build_grid()
        grid[2].assigned_members = [_make_member("A")]  # only 1 person
        decoy = core.Shift("Tuesday", 0, "10:30-11:30")
        result = ns["get_incomplete_slot_keys"](grid, decoy, ["Monday"])
        assert ("Monday", 2) in result

    def test_inactive_days_excluded(self, helpers_ns):
        ns, _ = helpers_ns
        grid = self._build_grid()
        for label, idx in core.TIME_SLOTS.items():
            grid.append(core.Shift("Tuesday", idx, label))
        decoy = core.Shift("Wednesday", 0, "10:30-11:30")
        result = ns["get_incomplete_slot_keys"](grid, decoy, ["Monday"])
        assert all(d == "Monday" for d, _ in result)


# ===========================================================================
# warn_if_understaffed
# ===========================================================================
class TestWarnIfUnderstaffed:
    def test_no_new_understaffed_no_toast(self, helpers_ns):
        ns, st = helpers_ns
        before = {("Monday", 0)}
        after = {("Monday", 0)}
        result = ns["warn_if_understaffed"](before, after)
        assert result is False
        assert st.toasts == []

    def test_newly_understaffed_triggers_toast(self, helpers_ns):
        ns, st = helpers_ns
        before = set()
        after = {("Monday", 0)}
        result = ns["warn_if_understaffed"](before, after)
        assert result is True
        assert len(st.toasts) == 1
        # The toast should mention the slot.
        assert "Monday" in st.toasts[0]["msg"]
        assert "Lock & Reroll" in st.toasts[0]["msg"]

    def test_multiple_newly_understaffed_listed(self, helpers_ns):
        ns, st = helpers_ns
        before = set()
        after = {("Monday", 0), ("Friday", 3)}
        result = ns["warn_if_understaffed"](before, after)
        assert result is True
        assert len(st.toasts) == 1
        msg = st.toasts[0]["msg"]
        assert "Monday" in msg
        assert "Friday" in msg

    def test_already_understaffed_does_not_warn(self, helpers_ns):
        ns, st = helpers_ns
        before = {("Monday", 0)}
        after = {("Monday", 0), ("Friday", 3)}
        ns["warn_if_understaffed"](before, after)
        # Only the new slot triggers a warning; old understaffed slots don't.
        assert len(st.toasts) == 1
        assert "Friday" in st.toasts[0]["msg"]
        assert "Monday" not in st.toasts[0]["msg"]


# ===========================================================================
# perform_overwrite_assign
# ===========================================================================
class TestPerformOverwriteAssign:
    def _seed_grid(self, st):
        a = _make_member("Alice")
        b = _make_member("Bob")
        c = _make_member("Charlie")
        st.session_state["members"] = [a, b, c]

        s1 = core.Shift("Monday", 0, "10:30-11:30")
        s2 = core.Shift("Monday", 1, "11:30-12:30")
        s1.assigned_members = [a, b]
        a.assigned_shifts.append(("Monday", 0))
        b.assigned_shifts.append(("Monday", 0))

        grid = [s1, s2]
        st.session_state["schedule_grid"] = grid
        return a, b, c, s1, s2

    def test_assigns_new_members_to_target(self, helpers_ns):
        ns, st = helpers_ns
        a, b, c, s1, s2 = self._seed_grid(st)

        ns["perform_overwrite_assign"](s2, [c])

        assert s2.assigned_members == [c]
        assert ("Monday", 1) in c.assigned_shifts

    def test_removes_old_members_from_previous_shift(self, helpers_ns):
        """Moving Alice from shift1 -> shift2 must remove her from shift1."""
        ns, st = helpers_ns
        a, b, c, s1, s2 = self._seed_grid(st)

        ns["perform_overwrite_assign"](s2, [a])

        # Alice was on shift1, now should only be on shift2.
        assert a not in s1.assigned_members
        assert a in s2.assigned_members
        # Her assigned_shifts list should reflect this move (no Monday-0, has Monday-1).
        assert ("Monday", 0) not in a.assigned_shifts
        assert ("Monday", 1) in a.assigned_shifts

    def test_removes_displaced_old_members_assigned_shifts(self, helpers_ns):
        """When Alice is removed from target s1 in favor of Charlie, Alice's
        assigned_shifts must lose the (Monday, 0) entry."""
        ns, st = helpers_ns
        a, b, c, s1, s2 = self._seed_grid(st)

        ns["perform_overwrite_assign"](s1, [b, c])  # drops Alice from s1

        assert a not in s1.assigned_members
        assert ("Monday", 0) not in a.assigned_shifts
        # Bob stays, his assignment shouldn't be duplicated.
        assert a.assigned_shifts == []
        assert b.assigned_shifts.count(("Monday", 0)) == 1
        # Charlie was added.
        assert ("Monday", 0) in c.assigned_shifts

    def test_handles_name_with_close_paren(self, helpers_ns):
        """Bug #11 regression: a member name containing ')' must be respected as
        a whole; the helper used to do `.split(')')` which truncated names."""
        ns, st = helpers_ns
        tricky = _make_member("Hong Kong)Test")
        partner = _make_member("Partner")
        st.session_state["members"] = [tricky, partner]
        shift = core.Shift("Monday", 0, "10:30-11:30")
        st.session_state["schedule_grid"] = [shift]

        ns["perform_overwrite_assign"](shift, [tricky, partner])

        assert tricky in shift.assigned_members
        assert partner in shift.assigned_members
        assert ("Monday", 0) in tricky.assigned_shifts


# ===========================================================================
# restore_state_from_json  (Bug #2 path)
# ===========================================================================
class TestRestoreStateFromJson:
    def test_restores_members_without_pre_existing_csv(self, helpers_ns):
        """Bug #2 regression: load_configuration must rebuild members from JSON
        even when session_state['members'] is empty."""
        ns, st = helpers_ns

        # Build a tiny config with the exporter so the JSON layout is correct.
        alice = _make_member("Alice")
        bob = _make_member("Bob", gender="Female")
        shift = core.Shift("Monday", 0, "10:30-11:30")
        shift.assigned_members = [alice, bob]
        alice.assigned_shifts.append(("Monday", 0))
        bob.assigned_shifts.append(("Monday", 0))

        config_json = core.export_configuration(
            schedule_grid=[shift],
            forbidden_pairs=[],
            active_days=["Monday"],
            must_schedule=[],
            never_schedule=[],
            members=[alice, bob],
        )

        # Start with NO members in session_state — Bug #2 happened here.
        st.session_state["members"] = []

        ns["restore_state_from_json"](config_json)

        names = {m.name for m in st.session_state["members"]}
        assert names == {"Alice", "Bob"}
        assert len(st.session_state["schedule_grid"]) == 1
        # No warning should have fired about needing the CSV first.
        assert not any("CSV" in w for w in st.warnings)
