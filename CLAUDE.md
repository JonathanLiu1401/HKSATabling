# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Streamlit web app that schedules tabling shifts for the Hong Kong Student Association (HKSA). It ingests a Google Forms availability CSV and generates a Mon–Fri × 4-timeslot grid where each shift is staffed by exactly 2 members under fairness, gender, and preference constraints. Deployed at https://hksatabling-utjuta9cmx64qjjpfh7rpk.streamlit.app/.

## Commands

```bash
pip install -r requirements.txt          # streamlit, pandas, xlsxwriter, openpyxl, streamlit-local-storage
python -m streamlit run app.py           # local dev server (default http://localhost:8501)
```

There is no test suite, no linter config, and no build step. The `testing archive/` folder is a historical dump of sample CSVs/XLSXs — not fixtures and not referenced by code. `small_sample.csv`, `med_sample.csv`, `big_sample.csv`, and `Availability.csv` at the repo root are the canonical sample inputs to drag into the uploader.

## Architecture

Two-file split, intentionally:

- **`scheduler_core.py`** — pure domain logic. No Streamlit imports. Holds the `Member`, `Shift`, `Scheduler` classes; CSV parsing (`parse_file`); Excel export (`generate_excel_bytes`); JSON config save/load (`export_configuration` / `load_configuration`); and the partner-overlap utility (`find_best_slots_for_pair`). Keep it that way — if you need to touch scheduling rules, do it here, not in `app.py`.
- **`app.py`** — all Streamlit UI, session state, sidebar, six tabs (View / Live Editor / Partner Matcher / Conflict Manager / Participation / Time Manager), and browser-localStorage autosave. Imports `scheduler_core as core`.

### The scheduling algorithm (`Scheduler.solve` + `_backtrack`)

This is the heart of the project. Read `scheduler_core.py:90-282` before changing anything that touches scheduling.

- **Hard constraints (never violated):**
  - Exactly 2 members per shift.
  - Each member gets at most 1 shift per week (`len(m.assigned_shifts) == 0` check in `_get_valid_pairs`).
  - Openings (`time_idx == 0`, 10:30) and Closings (`time_idx == 3`, 1:30) must include at least one Male (`Shift.needs_male`).
  - `forbidden_pairs`, `never_schedule`, and per-member `avoid_opening` / `avoid_closing` / `time_overrides` are enforced.
- **Search strategy:** classic backtracking with a difficulty-ordered shift list — fully-locked shifts first, then remaining shifts sorted ascending by candidate count (most-constrained first). Attempts are capped at 1,000,000 (`StopIteration` early-exit).
- **Multi-solution mode:** the solver doesn't stop at the first full grid — it collects up to **51 complete solutions** into `self.top_schedules`, each scored. The UI surfaces these as "Options" in the Live Editor tab.
- **"Least Changes" scoring** (`_backtrack` lines 176–193, plus `pair_score` 226–267) is the most subtle part. When the user rerolls after locking something, every reroll runs with `previous_state` = the grid snapshot from before the action (`last_stable_state`). Pair scoring then:
  - +5000 if `{p1, p2}` exactly matches the previous occupants of this slot (stability dominates).
  - +500 for a partial carryover.
  - +200 per `must_schedule` member.
  - +10 per preferred-day match.
  - **−100 anti-poaching penalty** if the pair isn't an exact match here but at least one of them was previously scheduled in a *different* slot — discourages stealing a stable pairing from elsewhere.
  - Final ranking is by `(changes ASC, score DESC)` so the option with the fewest diffs from the prior schedule wins ties.
- **Pre-filled grid path:** `Scheduler(..., pre_filled_grid=grid)` restarts from an existing grid honoring `Shift.locked`. The solver wipes unlocked assignments, restores locked ones, then resumes backtracking.

If you touch the scoring weights, also touch `app.py` only where it shows "Changes:" / "Score:" labels — the format string lives in `_backtrack` (`scheduler_core.py:192`) and in the Live Editor selectbox formatter.

### Data model gotchas

- `Member.is_available(day, time_idx)` checks `time_overrides` **first** (Tab 6 / Time Manager mutates this). Overrides can force a slot ON (even if the CSV said busy) or OFF.
- `Member.assigned_shifts` is mutated in-place during backtracking and during UI edits. The same `Member` instance is shared across `st.session_state['members']` and the `Shift.assigned_members` lists — they are not copies. Helpers like `perform_overwrite_assign` in `app.py:253` exist to keep both sides in sync; don't bypass them.
- Shift assigned_member names occasionally carry status-icon prefixes from `get_member_options` (`✅`, `⛔`, `⚠️`, `🌟`, `👤`). `find_member_by_str` strips them. Resolve to a real `Member` via `find_member_exact` whenever you need identity.

### CSV ingestion (`parse_file`)

Column detection is fuzzy and case-insensitive (`scheduler_core.py:360-402`). It looks for substrings: "name (first and last)", "gender", "ok…open", "ok…clo", "select days…prefer", and weekday names. Time strings inside cells are matched by stripping whitespace and substring-checking against the `TIME_SLOTS` keys (`"10:30-11:30"`, `"11:30-12:30"`, `"12:30-1:30"`, `"1:30-2:30"`). If a real Google Forms export adds a new column or renames one, extend the `col_map` block — don't rewrite the parser.

### Session persistence (two layers)

1. **In-memory:** `st.session_state` holds `members`, `schedule_grid`, `forbidden_pairs`, `must_schedule`, `never_schedule`, `top_schedules`, `last_stable_state`, `editor_selected_slot`, plus widget mirrors `widget_must` / `widget_never`. Initialized at the top of `app.py`.
2. **Browser localStorage** (`streamlit_local_storage`, key `hksa_autosave_v1`): the full config JSON is written on every render at the bottom of `app.py` (lines 700–710) and a restore prompt appears in the sidebar on next load if data exists and the session is empty. The Save/Load Config section in the sidebar uses the same `export_configuration` / `load_configuration` round-trip — these now serialize the full member list (including `time_overrides`), so loaded JSONs are self-contained and don't require re-uploading the CSV. Legacy configs without a `members` field fall back to the supplied `existing_members` argument.

### The "reroll" pattern

Almost every interactive action in `app.py` follows the same shape: capture `last_stable_state`, mutate the grid (lock a slot, add a forbidden pair, change must/never lists), build a new `Scheduler` with `pre_filled_grid=grid` and `previous_state=last_stable_state`, call `solve()`, swap in the new `schedule_grid` and `top_schedules`, `st.rerun()`. If you add a new constraint UI, mirror this pattern — skipping `last_stable_state` will break the Least-Changes guarantee.

## Constants worth knowing

- `TIME_SLOTS` and `ALL_DAYS` in `scheduler_core.py:9-15` are the canonical orderings. Time indices 0 and 3 are the "heavy lifting" slots that require a Male. The grid is always built in `(day, time_idx)` row order; Excel export reshapes to `(time × day)` with two rows per timeslot.
- The solver hard-caps at 1M attempts and 51 collected solutions. These are the levers if perf or option-count ever needs tuning.
