# HKSA Tabling Scheduler

This application automates the scheduling of tabling shifts for the Hong Kong Student Association (HKSA).

## Features
- **Strict Logic**: Ensures 2 people per shift.
- **Heavy Lifting**: Ensures at least 1 male during Opening (10:30) and Closing (1:30) shifts.
- **Preferences**: Respects "No Opening" and "No Closing" requests.
- **Output**: Generates a formatted Excel file with 2 rows per slot.

## How to Update
If the logic needs to change (e.g., shift times change or new constraints are added):
1. Open `scheduler_core.py`.
2. Edit the `TIME_SLOTS` dictionary or the `Scheduler` class logic.
3. Commit the changes to GitHub.
4. Streamlit Cloud will automatically update the live app.