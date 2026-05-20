# HKSA Tabling Scheduler Pro

A web app that builds your weekly HKSA tabling schedule for you — and lets you fix it up afterward.

**👉 Open the app:** https://hksatabling-utjuta9cmx64qjjpfh7rpk.streamlit.app/

You don't need to install anything. The link above is the live app. Bookmark it.

---

## Table of Contents

1. [What this app actually does](#what-this-app-actually-does)
2. [The fastest path: 5-minute walkthrough](#the-fastest-path-5-minute-walkthrough)
3. [Collecting availability with Google Forms](#collecting-availability-with-google-forms)
4. [Uploading your CSV](#uploading-your-csv)
5. [Generating the schedule](#generating-the-schedule)
6. [The rules the scheduler always follows](#the-rules-the-scheduler-always-follows)
7. [Reading the schedule grid](#reading-the-schedule-grid)
8. [Making changes (the six tabs explained)](#making-changes-the-six-tabs-explained)
9. [Saving your work](#saving-your-work)
10. [Common scenarios](#common-scenarios)
11. [Troubleshooting](#troubleshooting)
12. [Best practices](#best-practices)
13. [For developers (technical setup)](#for-developers-technical-setup)

---

## What this app actually does

Every week, HKSA has a tabling table that needs to be staffed by **two people at a time, in four one-hour slots, across Monday through Friday**. That's twenty shifts, with two people each — forty assignments — and you have to pick from a roster of people who have wildly different availability, preferences, and constraints. Doing this by hand in a spreadsheet takes hours and usually creates conflicts.

This app does it for you in about two seconds. You give it the availability data (from a Google Form), click one button, and it produces a complete schedule that follows all the rules HKSA cares about (heavy-lifting members on opening/closing, fairness, no double-booking, etc.). Then it gives you tools to manually adjust the result without breaking any rules — swap people, lock a specific pairing, exclude someone for the week, and so on.

**The four daily time slots** are:

| Slot | Time | Notes |
|---|---|---|
| 1 (Opening) | 10:30 AM – 11:30 AM | Needs at least one Male (heavy lifting setup) |
| 2 | 11:30 AM – 12:30 PM | Middle shift |
| 3 | 12:30 PM – 1:30 PM | Middle shift |
| 4 (Closing) | 1:30 PM – 2:30 PM | Needs at least one Male (heavy lifting teardown) |

---

## The fastest path: 5-minute walkthrough

If you just need it to work right now and don't care about the details yet, do this:

1. Open https://hksatabling-utjuta9cmx64qjjpfh7rpk.streamlit.app/
2. In the Google Sheet that has your form responses, click **File → Download → Comma Separated Values (.csv)**.
3. On the app, find the sidebar on the left. Under **"2. Upload Data"**, drag your CSV in.
4. You'll see **"Loaded N members"**. Good.
5. Click the big blue **🚀 Auto-Generate Schedule** button.
6. The **View tab** will show your finished schedule. Click **📥 Download Excel** to save it.

That's it. The rest of this README explains every part in detail.

---

## Collecting availability with Google Forms

The scheduler reads a CSV file with one row per person. The simplest way to produce that file is a Google Form.

### Required questions on your form

Set up your Google Form with these questions (the exact wording is fine — the scheduler matches on keywords, not exact text):

| Question | Type | What it asks for |
|---|---|---|
| **Name (First and Last)** | Short answer | The person's name. Used to identify them everywhere. |
| **Gender** | Multiple choice | Choices should be exactly `Male` and `Female`. Used for the opening/closing heavy-lifting rule. |
| **Are you OK with opening shifts?** | Multiple choice | `Yes` / `No`. "No" means the scheduler will never put them on the 10:30 slot. |
| **Are you OK with closing shifts?** | Multiple choice | `Yes` / `No`. "No" means the scheduler will never put them on the 1:30 slot. |
| **Monday** | Checkboxes (or short text) | Which time slots they're available, e.g. checking `10:30-11:30` and `12:30-1:30`. |
| **Tuesday** | Checkboxes (or short text) | Same as Monday. |
| **Wednesday** | Checkboxes (or short text) | Same as Monday. |
| **Thursday** | Checkboxes (or short text) | Same as Monday. |
| **Friday** | Checkboxes (or short text) | Same as Monday. |
| **Select days you prefer to table on (if applicable)** | Checkboxes (optional) | Days the person *prefers*. The scheduler tries to place them on these days when possible. |

The exact time-slot labels should be: `10:30-11:30`, `11:30-12:30`, `12:30-1:30`, `1:30-2:30`.

### Downloading the CSV

1. Open the Google Sheet attached to your form (the "Responses" sheet).
2. Click **File** in the menu bar.
3. Choose **Download → Comma Separated Values (.csv)**.
4. The file will save to your Downloads folder. That's the file you'll upload.

> **Note:** You don't need to clean up the spreadsheet — keep the auto-generated `Timestamp` column, the `Screenshot of your calendar` column, and anything else Google Forms added. The scheduler ignores the extra columns.

### What the data should look like

A working CSV row looks like this (you don't need to type this — Google Forms produces it automatically):

```
Timestamp,Name (First and Last),Gender,Are you OK with opening shifts?,Are you OK with closing shifts?,Monday,Tuesday,Wednesday,Thursday,Friday,Select days you prefer to table on (if applicable)
2/04/2026 12:00:00,Alex Smith,Male,Yes,Yes,"10:30-11:30, 12:30-1:30","11:30-12:30","10:30-11:30",,"1:30-2:30","Monday, Wednesday"
```

That's one person (Alex Smith) who is Male, OK with opening and closing, available Monday at two slots, Tuesday at one slot, etc., and prefers Monday and Wednesday.

If you want to see realistic examples, look at the `small_sample.csv`, `med_sample.csv`, or `big_sample.csv` files in this repository.

---

## Uploading your CSV

When you open the app, you'll see a sidebar on the left with four sections numbered 1–4.

### "1. Configuration" — Active Days

The first thing on the sidebar is a checkbox list called **"Active Days"** with Monday through Friday all checked. Uncheck any day you don't want to schedule for — for example, if it's a school holiday or if you only run tabling Tuesday through Thursday this week, uncheck the others.

> **Heads up:** If you change Active Days *after* generating a schedule, the app will automatically clear the shifts for the days you unchecked and tell you with a yellow banner. You'll need to click **🚀 Auto-Generate Schedule** again (or use Lock & Reroll, explained later) to re-fill anything that was lost.

### "2. Upload Data" — your CSV

Drag your CSV file into the upload box, or click "Browse files" to pick it. You'll see one of these messages:

- ✅ **"Loaded N members"** (green) — Success. N is the number of people read from the file.
- ❌ **"Error parsing: ..."** (red) — Something is wrong with the file. The most common cause is that the Google Form was missing one of the required columns (Name, Gender, etc.). See [Troubleshooting](#troubleshooting).

### "3. Actions" — the big button

Once your data is loaded, click **🚀 Auto-Generate Schedule**. The app spends 1–3 seconds thinking, then either:

- 🟢 **"Found N valid schedules!"** — Done. Switch to the View tab to see the result.
- 🟡 **"Could not find a valid schedule with these constraints."** — The rules can't all be satisfied with the availability you uploaded. See [Troubleshooting](#troubleshooting).

### "4. Save/Load Config"

This is for saving your work-in-progress or sharing a schedule with a co-organizer. Covered in [Saving your work](#saving-your-work).

---

## Generating the schedule

When you click **🚀 Auto-Generate Schedule**, here's what's actually happening behind the scenes:

1. The app builds a grid: 5 days × 4 time slots = 20 shifts, each needing 2 people = 40 assignments to make.
2. It looks at every possible pair of people who are both available for each shift.
3. It runs a search that tries to fill the whole grid following all the rules below.
4. It keeps looking even after finding the first valid answer, so it can give you alternatives. It collects up to 51 different valid schedules.
5. It picks the best one based on a scoring system that rewards preferred-day matches and (after rerolls) keeping the schedule as close to your previous version as possible.

You'll see a "Found N valid schedules" message — N tells you how flexible the constraints are. **Higher N = more wiggle room for adjustments.** If N is 1, your constraints are tight and any change might fail.

---

## The rules the scheduler always follows

These rules are **hard** — the scheduler will never break them. If it can't follow them all, it gives up rather than producing a broken schedule.

### Rule 1: Two people per shift
Every shift must have exactly two people. No solo shifts. No three-person shifts.

### Rule 2: One shift per person per week
Each member gets exactly one shift, no more. This is the fairness rule — nobody works twice while others sit idle. (If you have more shifts than members, some shifts will end up unfilled. If you have more members than shifts, some members will end up unassigned.)

### Rule 3: Heavy-lifting on opening and closing
Opening shifts (10:30–11:30) and closing shifts (1:30–2:30) require at least one Male per shift, because they involve carrying the table and supplies. Two Females cannot be assigned to an opening or closing slot. (Two Males, or one Male + one Female, are both fine.)

### Rule 4: Respect opening/closing preferences
If a member said "No" to opening shifts on the form, the scheduler will never put them on the 10:30 slot. Same for closing.

### Rule 5: Respect manual blocks (Conflict Manager)
If you've marked two members as "cannot work together" (in the Conflict Manager tab), they'll never be paired.

### Rule 6: Respect exclusions (Participation Manager)
If you've added someone to the "Never Schedule" list (e.g., they're sick this week), they won't appear in the schedule at all.

### Rule 7: Respect availability overrides (Time Manager)
If you've manually forced a member's availability on or off for a specific slot, the scheduler honors that override over their form answer.

### Soft preferences (the scheduler tries to honor these, but won't fail if it can't)

- **Preferred days** — if a member listed "I prefer to work Wednesday" on the form, the scheduler bumps the score when placing them on Wednesday.
- **Schedule stability** — when you make a small change and reroll, the scheduler tries to keep as much of the previous schedule unchanged as possible (so you're not re-explaining to 20 people why their slot moved).

---

## Reading the schedule grid

Switch to the **📊 View tab** to see your finished schedule. It looks like a table:

|  | Monday | Tuesday | Wednesday | Thursday | Friday |
|---|---|---|---|---|---|
| **10:30-11:30** | Alex Smith | Jordan Lee | Casey Park | Riley Chen | Taylor Wu |
|  | Jordan Lee | Casey Park | Alex Smith | Taylor Wu | Riley Chen |
| **11:30-12:30** | ... | ... | ... | ... | ... |

Each time slot has two rows in the grid — the first row is one person, the second row is their partner.

### Special markers

- **🔒 next to a name** — that slot is locked. You manually fixed it. Subsequent rerolls won't change it.
- **📝 next to a slot button** (in Live Editor tab) — that slot changed in the last reroll compared to the previous version. Hover for details.
- **"-"** — empty slot, nobody assigned.

### Unassigned Members section

Below the grid you'll see an **"Unassigned Members"** section listing anyone who couldn't be placed. For each unassigned person, you'll see:

- Name and gender
- "Slots Free" — total number of time slots they said they were available for
- "Availability" — exactly which days/times
- Whether they avoid opening/closing

This is useful when you need a substitute — you can see at a glance who else is free at the time you need to fill.

If everyone got assigned, you'll see **"🎉 All (active) members assigned!"** instead.

### Downloading to Excel

Click **📥 Download Excel** to save the schedule as a `.xlsx` file. The file has two sheets:

- **Final Schedule** — the same grid as on screen.
- **Unassigned Members** — the same list as on screen, sorted by who has the most free slots (easier to find backups).

---

## Making changes (the six tabs explained)

After auto-generating, you'll see six tabs across the top. Here's what each one does and when to use it.

### 📊 View

Just shows the schedule and the unassigned list. Read-only. Use this to confirm the result and download the Excel file.

### ✏️ Live Editor (Grid)

The most-used tab for manual adjustments. The grid is interactive — every slot is a clickable button.

**Workflow:**

1. **Click any slot in the grid.** It turns blue to show it's selected, and an editing panel appears below.
2. **In the panel**, you'll see two dropdowns: Slot 1 Member and Slot 2 Member. They list everyone available, with icons:
   - 🌟 = available *and* this is one of their preferred days
   - ✅ = available, no other shifts assigned yet
   - ⚠️ = available, but already working another shift this week
   - ⛔ = not available this slot (form said so, or override blocks it)
   - 👤 = currently in this slot
3. **Pick the two people you want in that slot.**
4. **Click one of the three buttons:**

| Button | What it does | When to use |
|---|---|---|
| **Update Slot (No Reroll)** | Replaces the two people, doesn't touch anything else. | You want to make a tiny tweak and don't want the rest of the schedule to shift around. |
| **🔒 Lock (No Reroll)** | Same as above, but also marks the slot as "locked" so it won't change in future rerolls. | You're committing to this pairing. |
| **🔒 Lock & Reroll** | Locks the slot AND re-shuffles every other unlocked slot to make a fresh valid schedule that's as close as possible to the current one. | You made a change and want the rest of the schedule to re-balance around it. |

> **Heads up:** If you use "Update Slot" or "Lock (No Reroll)" to move someone from another slot, the slot they came from will end up understaffed (only one person). The app shows you a ⚠️ toast warning when this happens. The fix is to use **Lock & Reroll** instead, which automatically refills any holes.

### Partner Matcher

For when two specific people *should* work together — e.g., a new member you want to train alongside an experienced one.

1. Pick **Person A** from the first dropdown.
2. Pick **Person B** from the second dropdown.
3. The app shows up to three slots where both are available, ranked by score.
4. Click **Lock & Reroll** next to the slot you want. The pair is locked in, and the rest of the schedule reshuffles around them.

### Conflict Manager

For when two people **cannot** work together (interpersonal issue, training-incompatible, etc.).

1. Pick **Member 1** and **Member 2**.
2. Click **🚫 Lock Conflict & Reroll**. The conflict is recorded, and the schedule re-rolls so they never share a slot.

Active conflicts are listed below with a 🗑️ Remove button next to each.

### 🛑 Participation

Two columns side by side:

#### 🔥 Force Schedule
A multi-select for "these members MUST appear in the schedule." Useful when you've promised someone a shift this week and don't want them to slip through. After picking, click **💾 Apply 'Force' & Reroll**.

Be careful — if you force-schedule more people than the schedule can accommodate, the reroll will fail with "Could not find a valid schedule." Remove someone and try again.

#### ⛔ Exclude
A multi-select for "these members are unavailable this week — skip them entirely." Use this when someone is sick, traveling, or has a midterm. Click **💾 Apply 'Exclude' & Reroll**.

A member can be in one list or the other, never both. The app prevents this automatically.

### ⏳ Time Manager

For overriding a single member's availability for the current week without changing their original form response. Use this for one-off changes ("Alex texted that he can't do 12:30 this Thursday after all").

1. Pick a member from the dropdown.
2. You'll see a grid of their availability with each cell as a clickable button:
   - 🟢 **Free** — Available per the CSV
   - ⚪ **Busy** — Not available per the CSV
   - ✅ **ON** — You manually forced this slot available (overrides the CSV)
   - ⛔ **OFF** — You manually forced this slot unavailable (overrides the CSV)
3. Click any cell to cycle through: **Default → ON → OFF → Default**.

There are also three Quick Action buttons at the top:

| Button | What it does |
|---|---|
| **🛡️ Force Opening/Closing Only** | Locks the middle two slots (11:30 and 12:30) as unavailable on every day. The member can only be scheduled for opening or closing shifts. Click again to undo. |
| **🚫 Force NO Opening/Closing** | The opposite — locks the opening and closing slots as unavailable. The member can only do middle shifts. Click again to undo. |
| **🔄 Reset All Overrides** | Clears every manual override for this member, reverting them to whatever the CSV said. |

> **Heads up:** Time Manager changes don't auto-update the current schedule. If you make someone unavailable for a slot they're *currently* assigned to, the app will show a yellow warning naming the affected slots. To re-shuffle, go back to the Live Editor and use Lock & Reroll on those slots.

---

## Saving your work

### Autosave (automatic)
The app automatically saves your full session — schedule, locks, conflicts, exclusions, every member's overrides — to your browser's local storage on every interaction. **You don't need to do anything for this.**

If you close the browser and come back later, the app will ask:

> 💾 **Unsaved Session Found!** Do you want to restore your previous work?
>
> ✅ Yes / ❌ No

Click **Yes** to pick up exactly where you left off. Click **No** to start fresh. (The app remembers your choice across page reloads, so you won't get re-asked every time.)

### Save/Load Config (manual file)
For when you want to share a schedule with a co-organizer, or save multiple versions of the same week.

- **💾 Save Configuration** (sidebar, section 4) — downloads a `.json` file containing the entire current state.
- **Load Config (.json)** (sidebar, section 4) — upload a previously-saved JSON to restore that state. **You do NOT need to upload a CSV first** — the JSON contains all the member data.

Use cases:
- Share with a co-admin: "Hey, here's my proposed schedule, can you look at it?"
- Save multiple variants: "Plan A.json" vs "Plan B.json"
- Recover from a mistake: save before making big changes, then reload if you don't like the result.

---

## Common scenarios

### "Someone just dropped out — replace them"

1. Go to **Live Editor**.
2. Click the slot they were assigned to.
3. In the dropdown, pick a replacement (anyone with ✅ or 🌟 next to their name).
4. Click **Lock & Reroll** so the rest of the schedule re-balances if needed.

Alternative: go to **Participation Manager**, add them to the Exclude list, and click "Apply 'Exclude' & Reroll." The scheduler will redo everything without them.

### "I need to swap two people"

1. Go to **Live Editor**.
2. Click the first slot. Pick the new pairing (the person from the other slot replaces one of the current people). Click **Lock & Reroll**.

The "Lock & Reroll" will automatically figure out where to put the displaced person.

### "Pair the new member with someone experienced for training"

Use **Partner Matcher**. Pick the new member as Person A and the experienced member as Person B. Pick one of the suggested slots and click Lock & Reroll.

### "These two people had a falling out — never pair them"

Use **Conflict Manager**. Add them as a pair. The current schedule re-rolls and they'll never be put together going forward.

### "Wednesday is a holiday this week"

In the sidebar, uncheck **Wednesday** under Active Days. The Wednesday shifts will disappear from the grid. If you'd already generated, click **🚀 Auto-Generate Schedule** again to rebuild a fresh schedule without Wednesday.

### "Someone needs to ONLY do opening/closing this week"

In **Time Manager**, pick that member and click the **🛡️ Force Opening/Closing Only** quick action. Then go to Live Editor and Lock & Reroll their current slot (if they have one) so the schedule re-runs honoring the new constraint.

### "I forced too many constraints and now it can't find a schedule"

Loosen something:
- Remove a forbidden pair from Conflict Manager.
- Remove someone from the Force Schedule list.
- Re-enable a member who was Excluded.
- Reset overrides in Time Manager.

Then click **🚀 Auto-Generate Schedule** again.

### "I want to see other valid schedules before committing"

After generating, go to **Live Editor**. At the top you'll see **💎 Generated Options (N found)** with a dropdown. Pick a different option from the dropdown and click **🔄 Apply Option**. Each option shows its "Changes from current" count and a preference score — pick whichever balances those the way you want.

---

## Troubleshooting

### "It says 'Error parsing: ...' when I upload my CSV"

The most common causes:
- **Your CSV is missing the Name column.** The error message will say something like `CSV is missing a Name column. Expected a column matching 'Name (First and Last)' or containing 'name'.` Fix the Google Form to include a Name question and re-export.
- **You uploaded the wrong file.** Make sure you downloaded the responses CSV, not the form template. Double-check the file is from File → Download → CSV in the responses sheet.
- **The file is corrupted.** Re-download from Google Sheets.

### "It says 'Loaded 0 members'"

The CSV has no usable rows. Possible causes:
- Nobody actually submitted the form yet.
- Every row has a blank name field.
- The CSV file is empty.

Open the CSV in Excel or Google Sheets to verify there's data.

### "It says 'Could not find a valid schedule with these constraints'"

This means the combination of availability + your manual constraints (forbidden pairs, must-schedule, time overrides) has no valid answer. Try in this order:
1. **Remove forbidden pairs one at a time** until it works — that tells you which one was blocking things.
2. **Reduce your "Force Schedule" list** — maybe you're forcing too many people in.
3. **Re-enable some excluded members** — maybe you removed too many.
4. **Reset Time Manager overrides** — overrides can be more restrictive than the original CSV.
5. **Check if you have enough Males** — if Males are scarce, opening/closing slots can become unfillable. The grid needs at least 10 different Male members (one per opening + one per closing) across the week.

### "I lost my work"

- If you have the autosave prompt on next load, click Yes.
- If you saved a Configuration JSON earlier, upload it via Load Config.
- If neither — there's no recovery. Re-upload the CSV and rebuild.

### "I made a change and want to undo"

There's no undo button. Workarounds:
- Click **🚀 Auto-Generate Schedule** again to start fresh from the CSV (this discards all locks and edits).
- If you saved a Configuration JSON before the change, load it back.

**Recommendation:** before making big changes, click **💾 Save Configuration** as a checkpoint.

### "The Time Manager warning says someone is in a stale slot"

You changed a member's availability override after the schedule was already generated, and they're currently sitting in a slot they're now marked unavailable for. Go to the Live Editor, click that slot, and Lock & Reroll — the scheduler will move them out and find someone else.

### "Two 'Loaded N members' messages used to show up" (FIXED)

This was a bug in older versions. As of the May 2026 update, only one message should ever appear. If you still see duplicates, hard-refresh the page (Ctrl+Shift+R on Windows, Cmd+Shift+R on Mac).

---

## Best practices

### Run the form a few days early
Give people time to respond. The scheduler is only as good as the availability data. Late responses become unassigned-members → manual headache.

### Save a Config before risky changes
Before adding multiple forbidden pairs or setting up complex overrides, click **💾 Save Configuration** as a backup. If the reroll fails or produces something weird, you can load it back.

### Start with the broadest schedule, then refine
The healthiest workflow is:

1. Upload, click Auto-Generate, get a baseline.
2. Look at the View tab. Note any obvious problems (someone in a slot they hate, two new members paired without supervision, etc.).
3. Use **Partner Matcher** to lock in pairings you definitely want.
4. Use **Conflict Manager** to record any pairings you can't have.
5. Use **Live Editor → Lock & Reroll** for individual slot tweaks.
6. Don't lock everything — leave at least 30–50% of slots unlocked so the scheduler has room to re-balance when you make changes.

### Communicate locks vs. tentative
When you tell members their shift, treat locked slots as confirmed and unlocked ones as "subject to change if there's a last-minute swap." This matches how the app actually treats them.

### Don't manually edit the downloaded Excel
If you Excel-edit the file and someone later asks you for a config save, your changes won't be there. Always make changes in the app first, then download.

### Keep the original CSV
If you re-upload a *different* CSV after starting to work, you'll lose all your locks/conflicts/overrides. Save your Configuration JSON before swapping data files.

---

## For developers (technical setup)

If you want to run the app on your own machine instead of using the live Streamlit Cloud link — for example, to develop, customize, or run it offline — follow these steps.

### Prerequisites
- Python 3.8 or newer ([download here](https://www.python.org/downloads/))
- A terminal (Command Prompt or PowerShell on Windows, Terminal on Mac/Linux)

### Install and run

```bash
git clone https://github.com/JonathanLiu1401/HKSATabling.git
cd HKSATabling
pip install -r requirements.txt
python -m streamlit run app.py
```

The app will open in your default browser at `http://localhost:8501`.

### Running the test suite

The repository includes a comprehensive automated test suite (135 tests covering both the scheduling engine and the Streamlit app).

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

All tests should pass in under 30 seconds. If any fail, something's broken — don't deploy.

### Architecture overview

For a deeper dive into the code structure, scheduling algorithm, and design decisions, see [`CLAUDE.md`](./CLAUDE.md). It's written for AI coding assistants but is equally useful for human developers.

The short version:
- **`scheduler_core.py`** — all the scheduling logic, no UI. Pure Python.
- **`app.py`** — the Streamlit UI, session state, six tabs, autosave. Imports from `scheduler_core`.

### Deployment

The live app is hosted on [Streamlit Community Cloud](https://streamlit.io/cloud) — pushing to `main` on this repo automatically redeploys.

---

## Feedback and bug reports

If you find a bug or want a feature, open an issue at https://github.com/JonathanLiu1401/HKSATabling/issues.
