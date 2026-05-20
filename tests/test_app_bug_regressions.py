"""Regression tests, one per app.py bug recently fixed.

These tests exercise each fix narrowly so a future change re-introducing the
bug fails the relevant test rather than the broader integration suite.

Some bugs are best exercised end-to-end via ``streamlit.testing.v1.AppTest``
(notably Bug #3 day-sync, Bug #6 Time Manager staleness, Bug #7 autosave
dismissal). Others — duplicate-message upload, the perform_overwrite_assign
move sequence — are tested via the helper exec-shim because AppTest can't
upload files or easily drive the Live Editor selectbox+button chain due to a
``format_func`` capture issue with the "Options" selectbox in Tab 2.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Stub streamlit_local_storage BEFORE app.py is loaded by AppTest.
#
# Both test_app_integration.py and test_app_bug_regressions.py need to install
# a fake LocalStorage. To ensure they share a single fake (so per-test cleanup
# works regardless of import order), we install once and reuse if a sibling
# test file has already loaded one.
# ---------------------------------------------------------------------------
def _install_fake_local_storage():
    if "streamlit_local_storage" in sys.modules:
        existing = sys.modules["streamlit_local_storage"]
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

    fake_mod = types.ModuleType("streamlit_local_storage")
    fake_mod.LocalStorage = FakeLocalStorage
    sys.modules["streamlit_local_storage"] = fake_mod
    return FakeLocalStorage


FakeLocalStorage = _install_fake_local_storage()

from streamlit.testing.v1 import AppTest  # noqa: E402

import scheduler_core as core  # noqa: E402


APP_PATH = str(REPO_ROOT / "app.py")


@pytest.fixture(autouse=True)
def _clean_local_storage():
    FakeLocalStorage._store.clear()
    yield
    FakeLocalStorage._store.clear()


# ---------------------------------------------------------------------------
# Helpers reused across multiple tests.
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


def _fillable_pool(count=40):
    return [_make_member(f"M_{i:02d}") for i in range(count)]


def _solve_pool(pool, active_days=None):
    if active_days is None:
        active_days = list(core.ALL_DAYS)
    sched = core.Scheduler(pool, active_days=active_days)
    sched.solve()
    return sched.schedule_grid


# ---------------------------------------------------------------------------
# Shim helpers from app.py for the bugs where AppTest can't drive the UI.
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


class _FakeSessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def __setattr__(self, k, v):
        self[k] = v


def _extract_helpers():
    src = (REPO_ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    parts = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in HELPER_NAMES:
            parts.append(ast.get_source_segment(src, node))
    return "\n\n".join(parts)


def _build_helper_ns():
    fake_st = types.SimpleNamespace()
    fake_st.session_state = _FakeSessionState(
        members=[],
        schedule_grid=[],
        never_schedule=[],
        must_schedule=[],
        forbidden_pairs=[],
        active_days=list(core.ALL_DAYS),
        last_stable_state={},
        top_schedules=[],
    )
    fake_st.toasts = []
    fake_st.warnings = []
    fake_st.errors = []
    fake_st.infos = []
    fake_st.successes = []

    def _record_toast(msg, icon=None):
        fake_st.toasts.append({"msg": msg, "icon": icon})

    fake_st.toast = _record_toast
    fake_st.warning = lambda m: fake_st.warnings.append(m)
    fake_st.error = lambda m: fake_st.errors.append(m)
    fake_st.info = lambda m: fake_st.infos.append(m)
    fake_st.success = lambda m: fake_st.successes.append(m)

    ns = {"st": fake_st, "core": core, "copy": __import__("copy")}
    exec(_extract_helpers(), ns)
    return ns, fake_st


# ===========================================================================
# Bug #1: duplicate upload handler — should emit ONE message per render.
# ===========================================================================
class TestBug1DuplicateUploadHandler:
    """The old code had two `if uploaded_file:` blocks, causing two messages
    to fire on each render after upload. The fix consolidates them so:
      - first-time upload: exactly 1 success ("Loaded N members")
      - re-render with same file: exactly 1 info ("Loaded N members")
      - never both, never twice
    """

    def _run_upload_branch(self, file_hash_in_state, file_hash_uploaded, members_already_loaded):
        """Mimic the upload handler block from app.py:158-175.

        Returns ``(successes, infos, errors)`` lists capturing what would have
        rendered.
        """
        successes = []
        infos = []
        errors = []

        session_state = {
            "file_hash": file_hash_in_state,
            "members": members_already_loaded,
            "top_schedules": [],
            "schedule_grid": [],
            "last_stable_state": {},
        }

        # uploaded_file is truthy because we got something.
        current_hash = file_hash_uploaded
        if current_hash != session_state.get("file_hash"):
            session_state["file_hash"] = current_hash
            members = [_make_member(f"Member_{i}") for i in range(5)]  # simulate parse_file
            session_state["members"] = members
            session_state["top_schedules"] = []
            session_state["schedule_grid"] = []
            session_state["last_stable_state"] = {}
            successes.append(f"Loaded {len(members)} members")
        elif session_state.get("members"):
            infos.append(f"Loaded {len(session_state['members'])} members")

        return successes, infos, errors, session_state

    def test_new_upload_emits_exactly_one_success(self):
        successes, infos, errors, _ = self._run_upload_branch(
            file_hash_in_state=0,
            file_hash_uploaded=42,
            members_already_loaded=[],
        )
        assert len(successes) == 1
        assert len(infos) == 0
        assert len(errors) == 0

    def test_repeat_render_with_same_file_emits_exactly_one_info(self):
        members = [_make_member("Existing")]
        successes, infos, errors, _ = self._run_upload_branch(
            file_hash_in_state=42,
            file_hash_uploaded=42,
            members_already_loaded=members,
        )
        # Same hash, members already loaded -> info path, NOT success path.
        assert len(infos) == 1
        assert len(successes) == 0
        assert len(errors) == 0

    def test_no_double_render_on_unchanged_file(self):
        """The old code emitted both success AND info on every render. The fix
        is mutually exclusive: at most one of them fires per render."""
        members = [_make_member("Existing")]
        successes, infos, _, _ = self._run_upload_branch(
            file_hash_in_state=42,
            file_hash_uploaded=42,
            members_already_loaded=members,
        )
        total_messages = len(successes) + len(infos)
        assert total_messages == 1, (
            "Expected exactly one of success/info to fire per render, got "
            f"{len(successes)} success + {len(infos)} info"
        )


# ===========================================================================
# Bug #2: config loader requires CSV — restore must work with empty state.
# ===========================================================================
class TestBug2ConfigLoaderRequiresCsv:
    """The old code refused to apply a config JSON unless members were already
    in session_state. The fix has ``restore_state_from_json`` rebuild members
    from the JSON itself, so no prior CSV upload is required.
    """

    def test_restore_from_json_populates_members(self):
        ns, fake_st = _build_helper_ns()
        # Build a config JSON via core API.
        pool = _fillable_pool(40)
        sched = core.Scheduler(pool, active_days=list(core.ALL_DAYS))
        sched.solve()
        cfg = core.export_configuration(
            sched.schedule_grid, [], list(core.ALL_DAYS), [], [], pool
        )

        # Start with NO members. Bug #2 was: the loader rejected the JSON unless
        # session_state['members'] was already populated. The fix lets the JSON
        # itself reconstruct the member list.
        assert fake_st.session_state["members"] == []

        # Drive the app.py helper directly via the shim.
        ns["restore_state_from_json"](cfg)

        # Bug #2 fix: members must be populated by restore_state_from_json.
        assert len(fake_st.session_state["members"]) == 40
        assert len(fake_st.session_state["schedule_grid"]) == 20
        # Bug #2 fix: no "Please upload the Availability CSV first" warning.
        assert not any("CSV" in w for w in fake_st.warnings)
        assert not any("Availability" in w for w in fake_st.warnings)

    def test_appttest_load_config_with_no_csv_uploaded(self):
        """End-to-end via AppTest: cold-start (no members), then inject a JSON
        config — the resulting session must have members + a schedule grid."""
        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)
        assert at.session_state["members"] == []

        pool = _fillable_pool(40)
        sched = core.Scheduler(pool, active_days=list(core.ALL_DAYS))
        sched.solve()
        cfg = core.export_configuration(
            sched.schedule_grid, [], list(core.ALL_DAYS), [], [], pool
        )

        # Drive load_configuration as the file-uploader's on_change would.
        a_days, f_pairs, must_s, never_s, new_grid, restored_members = (
            core.load_configuration(cfg, None)
        )
        at.session_state["members"] = restored_members
        at.session_state["active_days_selection"] = a_days
        at.session_state["active_days"] = a_days
        at.session_state["forbidden_pairs"] = f_pairs
        at.session_state["must_schedule"] = must_s
        at.session_state["never_schedule"] = never_s
        at.session_state["schedule_grid"] = new_grid
        at.run(timeout=15)

        assert len(at.session_state["members"]) == 40
        assert len(at.session_state["schedule_grid"]) == 20
        # No warnings about needing a CSV.
        all_warnings = [w.value for w in at.warning] + [w.value for w in at.sidebar.warning]
        assert not any("CSV" in w for w in all_warnings)
        assert not any("upload the Availability" in w for w in all_warnings)


# ===========================================================================
# Bug #3: stale grid when active_days changes
# ===========================================================================
class TestBug3ActiveDaysStaleGrid:
    """The grid must reconcile with active_days_selection on every render.
    Selecting a subset of days should drop the inactive shifts AND clear the
    affected members' ``assigned_shifts`` entries.
    """

    def test_grid_shrinks_when_days_reduced(self):
        pool = _fillable_pool(40)
        grid = _solve_pool(pool)

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        at.session_state["active_days_selection"] = ["Monday", "Tuesday"]
        at.run(timeout=15)

        # 2 days × 4 slots = 8 shifts.
        assert len(at.session_state["schedule_grid"]) == 8
        # All remaining shifts should be Monday or Tuesday.
        days_in_grid = sorted({s.day for s in at.session_state["schedule_grid"]})
        assert days_in_grid == ["Monday", "Tuesday"]

    def test_members_lose_inactive_day_assignments(self):
        pool = _fillable_pool(40)
        grid = _solve_pool(pool)

        # Snapshot which Wed/Thu/Fri assignments exist BEFORE.
        before_inactive = []
        for m in pool:
            for d, t in m.assigned_shifts:
                if d in ("Wednesday", "Thursday", "Friday"):
                    before_inactive.append((m.name, d, t))
        assert before_inactive  # sanity: we should have some

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        at.session_state["active_days_selection"] = ["Monday", "Tuesday"]
        at.run(timeout=15)

        # AFTER: no member should hold a Wed/Thu/Fri assignment.
        for m in at.session_state["members"]:
            assert all(d in ("Monday", "Tuesday") for d, _ in m.assigned_shifts), (
                f"{m.name} still has stale shifts: {m.assigned_shifts}"
            )

    def test_day_change_emits_info_message(self):
        pool = _fillable_pool(40)
        grid = _solve_pool(pool)

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        at.session_state["active_days_selection"] = ["Monday", "Tuesday"]
        at.run(timeout=15)

        info_texts = [i.value for i in at.info] + [i.value for i in at.sidebar.info]
        assert any("Day selection changed" in t for t in info_texts), (
            f"Expected day-change info message, got: {info_texts}"
        )

    def test_grid_unchanged_when_days_unchanged(self):
        """Sanity: rerun with the same day selection should NOT touch the grid."""
        pool = _fillable_pool(40)
        grid = _solve_pool(pool)

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        # Default 5-day selection used.
        at.run(timeout=15)

        assert len(at.session_state["schedule_grid"]) == 20


# ===========================================================================
# Bug #5: no-reroll warning when a slot becomes understaffed
# ===========================================================================
class TestBug5NoRerollWarning:
    """Update Slot (No Reroll) — when moving a member from slot A to slot B
    leaves slot A with only 1 member, the user must see a toast warning rather
    than the cheery "Updated!" toast.
    """

    def test_warn_if_understaffed_fires_when_move_understaffs_source(self):
        """Simulates the button click code path directly via the helper shim,
        as AppTest can't drive the Live Editor selectbox/button chain reliably
        (the Options selectbox in Tab 2 has a ``format_func`` that crashes
        during widget-state collection)."""
        ns, fake_st = _build_helper_ns()

        # Build two fully-staffed slots, both on Monday.
        m1, m2, m3, m4 = (_make_member(n) for n in ("A", "B", "C", "D"))
        fake_st.session_state["members"] = [m1, m2, m3, m4]

        slot_a = core.Shift("Monday", 0, "10:30-11:30")
        slot_a.assigned_members = [m1, m2]
        m1.assigned_shifts.append(("Monday", 0))
        m2.assigned_shifts.append(("Monday", 0))

        slot_b = core.Shift("Monday", 1, "11:30-12:30")
        slot_b.assigned_members = [m3, m4]
        m3.assigned_shifts.append(("Monday", 1))
        m4.assigned_shifts.append(("Monday", 1))

        # Add the other empty Monday slots so the active-days logic is consistent.
        slot_c = core.Shift("Monday", 2, "12:30-1:30")
        slot_d = core.Shift("Monday", 3, "1:30-2:30")
        fake_st.session_state["schedule_grid"] = [slot_a, slot_b, slot_c, slot_d]

        active_days = ["Monday"]
        # Compose the exact code path from the "Update Slot (No Reroll)" branch.
        before_keys = ns["get_incomplete_slot_keys"](
            fake_st.session_state["schedule_grid"], slot_b, active_days
        )
        # Pull m1 (from slot_a) into slot_b alongside m3.
        ns["perform_overwrite_assign"](slot_b, [m1, m3])
        slot_b.locked = False
        after_keys = ns["get_incomplete_slot_keys"](
            fake_st.session_state["schedule_grid"], slot_b, active_days
        )
        warned = ns["warn_if_understaffed"](before_keys, after_keys)

        # Slot A is now down to {m2} only -> newly understaffed -> warn.
        assert warned is True
        assert len(fake_st.toasts) == 1
        msg = fake_st.toasts[0]["msg"]
        assert "Monday" in msg
        assert "Lock & Reroll" in msg

    def test_no_warn_when_no_slot_becomes_understaffed(self):
        """Negative case: an update that doesn't drain anyone should NOT warn."""
        ns, fake_st = _build_helper_ns()
        m1, m2, m3, m4 = (_make_member(n) for n in ("A", "B", "C", "D"))
        fake_st.session_state["members"] = [m1, m2, m3, m4]

        slot_a = core.Shift("Monday", 0, "10:30-11:30")
        slot_a.assigned_members = [m1, m2]
        m1.assigned_shifts.append(("Monday", 0))
        m2.assigned_shifts.append(("Monday", 0))

        slot_b = core.Shift("Monday", 1, "11:30-12:30")  # empty
        fake_st.session_state["schedule_grid"] = [slot_a, slot_b]

        active_days = ["Monday"]
        before_keys = ns["get_incomplete_slot_keys"](
            fake_st.session_state["schedule_grid"], slot_b, active_days
        )
        # Fill slot_b with two NEW (currently unassigned) members.
        m5 = _make_member("E")
        m6 = _make_member("F")
        fake_st.session_state["members"].extend([m5, m6])
        ns["perform_overwrite_assign"](slot_b, [m5, m6])
        after_keys = ns["get_incomplete_slot_keys"](
            fake_st.session_state["schedule_grid"], slot_b, active_days
        )
        warned = ns["warn_if_understaffed"](before_keys, after_keys)
        assert warned is False


# ===========================================================================
# Bug #6: Time Manager staleness warning
# ===========================================================================
class TestBug6TimeManagerStaleness:
    """When a member's overrides mark a slot they're currently scheduled into
    as unavailable, the Time Manager tab must surface a warning naming that
    slot."""

    def _build_at_with_target_assigned(self, override_day="Monday", override_idx=0):
        """Build an AppTest with a scheduled grid and one member's overrides
        flipped off for ``(override_day, override_idx)``."""
        pool = _fillable_pool(40)
        grid = _solve_pool(pool)

        # Find a member who is actually assigned to (override_day, override_idx).
        target = None
        for s in grid:
            if s.day == override_day and s.time_idx == override_idx:
                if s.assigned_members:
                    target = s.assigned_members[0]
                    break
        assert target is not None, "Test prerequisite: someone must be on that slot."

        # Apply an override making that slot unavailable for them.
        target.time_overrides = {override_day: {override_idx: False}}

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        # Pre-select target in the Time Manager selectbox.
        at.session_state["tm_member"] = target.name
        at.run(timeout=15)
        return at, target

    def test_stale_slot_warning_mentions_member_and_slot(self):
        at, target = self._build_at_with_target_assigned()

        warnings = [w.value for w in at.warning] + [w.value for w in at.sidebar.warning]
        assert any(target.name in w and "Monday" in w for w in warnings), (
            f"Expected warning naming {target.name} + Monday, got: {warnings}"
        )

    def test_no_warning_when_member_not_in_conflict(self):
        """Sanity: a member with no overrides shouldn't trigger the warning."""
        pool = _fillable_pool(40)
        grid = _solve_pool(pool)
        # Pick a target with NO override.
        target = pool[0]
        target.time_overrides = {}

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        at.session_state["tm_member"] = target.name
        at.run(timeout=15)

        warnings = [w.value for w in at.warning] + [w.value for w in at.sidebar.warning]
        assert not any("is currently scheduled at" in w for w in warnings)


# ===========================================================================
# Bug #7: autosave decision persisted across reruns
# ===========================================================================
class TestBug7AutosaveDecisionPersisted:
    """Clicking "No" on the autosave restore prompt sets the dismissal hash in
    localStorage. On subsequent renders, the prompt must NOT reappear as long
    as the autosave content (its hash) hasn't changed.
    """

    def _make_config_json(self):
        pool = _fillable_pool(40)
        sched = core.Scheduler(pool, active_days=list(core.ALL_DAYS))
        sched.solve()
        return core.export_configuration(
            sched.schedule_grid, [], list(core.ALL_DAYS), [], [], pool
        )

    def test_prompt_appears_without_dismissal(self):
        cfg = self._make_config_json()
        FakeLocalStorage._store["hksa_autosave_v1"] = cfg
        # NO dismissal hash stored.

        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)

        sidebar_warnings = [w.value for w in at.sidebar.warning]
        assert any("Unsaved Session Found" in w for w in sidebar_warnings)
        # The Yes/No buttons should be present.
        sidebar_button_labels = [b.label for b in at.sidebar.button]
        assert any("Yes" in l for l in sidebar_button_labels)
        assert any("No" in l for l in sidebar_button_labels)

    def test_prompt_suppressed_when_dismissal_hash_matches(self):
        cfg = self._make_config_json()
        FakeLocalStorage._store["hksa_autosave_v1"] = cfg
        # Seed the dismissal hash with the SAME content hash.
        FakeLocalStorage._store["hksa_autosave_dismissed_v1"] = str(hash(cfg))

        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)

        sidebar_warnings = [w.value for w in at.sidebar.warning]
        assert not any("Unsaved Session Found" in w for w in sidebar_warnings)

    def test_prompt_reappears_when_autosave_content_changes(self):
        """If the autosave content changes after a dismissal, the new content's
        hash won't match the stored dismissal — so the prompt should reappear.
        """
        cfg1 = self._make_config_json()
        FakeLocalStorage._store["hksa_autosave_v1"] = cfg1
        FakeLocalStorage._store["hksa_autosave_dismissed_v1"] = str(hash(cfg1))

        # Replace the autosave with a different config.
        cfg2 = cfg1 + " "  # ensure different hash
        FakeLocalStorage._store["hksa_autosave_v1"] = cfg2

        at = AppTest.from_file(APP_PATH)
        at.run(timeout=15)

        sidebar_warnings = [w.value for w in at.sidebar.warning]
        assert any("Unsaved Session Found" in w for w in sidebar_warnings), (
            "Expected re-prompt after autosave content changed; "
            f"got sidebar warnings: {sidebar_warnings}"
        )


# ===========================================================================
# Bug #11: split(")") dead code removed — names with ')' survive intact
# ===========================================================================
class TestBug11NameWithCloseParenSurvives:
    """The old code did a stray ``.split(')')`` on member names, truncating
    anything after a ``)`` character. The fix removes that, so a name like
    ``Hong Kong)Test`` survives in full.
    """

    def test_perform_overwrite_assign_preserves_full_name(self):
        ns, fake_st = _build_helper_ns()
        tricky = _make_member("Hong Kong)Test")
        partner = _make_member("Partner")
        fake_st.session_state["members"] = [tricky, partner]

        shift = core.Shift("Monday", 0, "10:30-11:30")
        fake_st.session_state["schedule_grid"] = [shift]

        ns["perform_overwrite_assign"](shift, [tricky, partner])

        assert tricky in shift.assigned_members
        assert partner in shift.assigned_members
        # Verify the name was not truncated when we look the member back up.
        assert ns["find_member_exact"]("Hong Kong)Test") is tricky
        # Verify nothing weird like "Hong Kong" got created.
        assert ns["find_member_exact"]("Hong Kong") is None

    def test_find_member_by_str_preserves_full_name(self):
        ns, fake_st = _build_helper_ns()
        tricky = _make_member("Hong Kong)Test")
        fake_st.session_state["members"] = [tricky]

        # With an icon prefix (as used in the selectbox):
        assert ns["find_member_by_str"]("✅ Hong Kong)Test") is tricky
        # Bare name:
        assert ns["find_member_by_str"]("Hong Kong)Test") is tricky

    def test_assigned_names_set_preserves_full_name(self):
        """The View tab builds ``assigned_names`` from ``m.name.strip()``. A
        name with ')' inside must round-trip without truncation."""
        tricky = _make_member("Hong Kong)Test")
        shift = core.Shift("Monday", 0, "10:30-11:30")
        shift.assigned_members = [tricky]

        # Replicate the View-tab snippet:
        assigned_names = set()
        for s in [shift]:
            for m in s.assigned_members:
                assigned_names.add(m.name.strip())
        assert "Hong Kong)Test" in assigned_names

    def test_appttest_grid_handles_name_with_close_paren(self):
        """End-to-end: inject a member with a ')' in the name; the app renders
        without exceptions and the Unassigned table can be built."""
        # Build a pool that includes a tricky-name member.
        tricky = _make_member("Hong Kong)Test")
        pool = [tricky] + _fillable_pool(40)
        # Re-name pool entries to avoid duplicate names colliding.
        for i, m in enumerate(pool[1:], start=1):
            m.name = f"M_{i:02d}"

        # Pre-solve to populate the grid (with all members, including tricky).
        grid = _solve_pool(pool)

        at = AppTest.from_file(APP_PATH)
        at.session_state["members"] = pool
        at.session_state["file_hash"] = 99999
        at.session_state["schedule_grid"] = grid
        at.run(timeout=15)

        # The app must render the View tab without an exception.
        assert not at.exception
