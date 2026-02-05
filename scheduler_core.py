import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import io
import copy

# --- CONSTANTS ---
TIME_SLOTS = {
    "10:30-11:30": 0,
    "11:30-12:30": 1,
    "12:30-1:30": 2,
    "1:30-2:30": 3
}
ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

@dataclass
class Member:
    name: str
    gender: str
    availability: Dict[str, List[int]] 
    avoid_opening: bool
    avoid_closing: bool
    preferred_days: List[str] = field(default_factory=list)
    assigned_shifts: List[Tuple[str, int]] = field(default_factory=list)

    def is_available(self, day: str, time_idx: int) -> bool:
        if time_idx not in self.availability.get(day, []): return False
        if self.avoid_opening and time_idx == 0: return False
        if self.avoid_closing and time_idx == 3: return False
        return True

@dataclass
class Shift:
    day: str
    time_idx: int
    time_label: str
    assigned_members: List[Member] = field(default_factory=list)
    locked: bool = False 
    
    def needs_male(self):
        return self.time_idx == 0 or self.time_idx == 3 

    def is_valid(self):
        if len(self.assigned_members) != 2: return False
        if self.needs_male():
            if not any(m.gender == 'Male' for m in self.assigned_members): return False
        return True

class Scheduler:
    def __init__(self, members: List[Member], active_days: List[str] = None, pre_filled_grid: List[Shift] = None):
        self.members = members
        self.active_days = active_days if active_days else ALL_DAYS
        
        if pre_filled_grid:
            self.schedule_grid = pre_filled_grid
        else:
            self.schedule_grid = self._initialize_grid()
            
        self.attempts = 0
        self.best_grid_state = {} 
        self.max_filled_count = -1

    def _initialize_grid(self) -> List[Shift]:
        grid = []
        for day in self.active_days:
            for label, idx in TIME_SLOTS.items():
                grid.append(Shift(day, idx, label))
        return grid

    def solve(self) -> bool:
        self.attempts = 0
        self.max_filled_count = -1
        self.best_grid_state = {}

        # 1. Reset assignments for non-locked members
        for m in self.members:
            m.assigned_shifts = []

        # 2. Re-apply locked assignments
        for shift in self.schedule_grid:
            if shift.locked:
                for m in shift.assigned_members:
                    # Find the real member object
                    real_m = next((x for x in self.members if x.name == m.name), None)
                    if real_m:
                        real_m.assigned_shifts.append((shift.day, shift.time_idx))
            else:
                shift.assigned_members = [] # Clear non-locked slots

        unlocked_shifts = [s for s in self.schedule_grid if not s.locked]
        
        shift_difficulty = []
        for shift in unlocked_shifts:
            valid_pairs = self._get_valid_pairs(shift)
            shift_difficulty.append((len(valid_pairs), shift))
        
        shift_difficulty.sort(key=lambda x: x[0])
        
        locked_shifts = [s for s in self.schedule_grid if s.locked]
        self.schedule_grid = locked_shifts + [item[1] for item in shift_difficulty]
        
        start_index = len(locked_shifts)
        
        # We ignore the return value because we always want the "best effort" result
        self._backtrack(start_index)
        
        # Always restore the best state found
        self._restore_best_state()
        
        # [BUG FIX 1] Accurate Success Reporting
        total_slots = len(self.schedule_grid)
        return self.max_filled_count == total_slots

    def _backtrack(self, shift_index: int) -> bool:
        self.attempts += 1
        if self.attempts > 500000: return False 

        current_filled_count = sum(1 for s in self.schedule_grid if len(s.assigned_members) == 2)
        if current_filled_count > self.max_filled_count:
            self.max_filled_count = current_filled_count
            self._save_current_state()

        if shift_index >= len(self.schedule_grid): 
            return True

        current_shift = self.schedule_grid[shift_index]
        if current_shift.locked:
            return self._backtrack(shift_index + 1)

        potential_pairs = self._get_valid_pairs(current_shift)
        
        def pair_score(pair):
            p1, p2 = pair
            score = 0
            if current_shift.day in p1.preferred_days: score += 5
            if current_shift.day in p2.preferred_days: score += 5
            return score

        potential_pairs.sort(key=pair_score, reverse=True)

        for p1, p2 in potential_pairs:
            current_shift.assigned_members = [p1, p2]
            p1.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            p2.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            
            if self._backtrack(shift_index + 1): return True
            
            current_shift.assigned_members = []
            p1.assigned_shifts.pop()
            p2.assigned_shifts.pop()
            
        return self._backtrack(shift_index + 1)

    def _save_current_state(self):
        state = {}
        for shift in self.schedule_grid:
            names = [m.name for m in shift.assigned_members]
            state[(shift.day, shift.time_idx)] = names
        self.best_grid_state = state

    def _restore_best_state(self):
        # [BUG FIX 2] Double Assignment Corruption
        # Clears assignments before restoring to avoid duplicate entries
        
        # 1. Clear ALL assignments first
        for m in self.members:
            m.assigned_shifts = []

        # 2. Re-apply locked assignments
        for shift in self.schedule_grid:
            if shift.locked:
                for m in shift.assigned_members:
                    real_m = next((x for x in self.members if x.name == m.name), None)
                    if real_m: real_m.assigned_shifts.append((shift.day, shift.time_idx))

        # 3. Apply best state to unlocked shifts
        for shift in self.schedule_grid:
            if shift.locked: continue
            
            saved_names = self.best_grid_state.get((shift.day, shift.time_idx), [])
            restored_members = []
            for name in saved_names:
                mem = next((m for m in self.members if m.name == name), None)
                if mem: 
                    restored_members.append(mem)
                    mem.assigned_shifts.append((shift.day, shift.time_idx))
            shift.assigned_members = restored_members

    def _get_valid_pairs(self, shift: Shift):
        available_people = [
            m for m in self.members 
            if m.is_available(shift.day, shift.time_idx) and len(m.assigned_shifts) == 0
        ]
        
        valid_pairs = []
        from itertools import combinations
        for p1, p2 in combinations(available_people, 2):
            if shift.needs_male():
                if p1.gender != 'Male' and p2.gender != 'Male': continue
            valid_pairs.append((p1, p2))
        return valid_pairs

def find_best_slots_for_pair(p1: Member, p2: Member, active_days: List[str]) -> List[Dict]:
    ranked_slots = []
    for day in active_days:
        for time_label, time_idx in TIME_SLOTS.items():
            if p1.is_available(day, time_idx) and p2.is_available(day, time_idx):
                score = 100 
                reasons = ["Both Available"]
                if day in p1.preferred_days:
                    score += 10
                    reasons.append(f"{p1.name} prefers {day}")
                if day in p2.preferred_days:
                    score += 10
                    reasons.append(f"{p2.name} prefers {day}")
                if (time_idx == 0 or time_idx == 3) and not (p1.gender == 'Male' or p2.gender == 'Male'):
                    continue
                else:
                    score += 5
                
                ranked_slots.append({"day": day, "time_idx": time_idx, "time_label": time_label, "score": score, "reason": ", ".join(reasons)})
    ranked_slots.sort(key=lambda x: x['score'], reverse=True)
    return ranked_slots

def check_assignment_validity(member: Member, shift_day: str, shift_time_idx: int, current_partners: List[Member]) -> Dict:
    status = {"valid": True, "warnings": [], "errors": []}
    if not member.is_available(shift_day, shift_time_idx):
        status["warnings"].append("Not marked as available.")
        status["valid"] = False 
    if len(member.assigned_shifts) > 0:
         for s_day, s_time in member.assigned_shifts:
             if s_day == shift_day and s_time == shift_time_idx: status["errors"].append("Already assigned to this slot.")
             else: status["warnings"].append(f"Already working on {s_day} (2nd shift).")
    if (shift_time_idx == 0 or shift_time_idx == 3) and member.gender != 'Male' and not any(p.gender == 'Male' for p in current_partners if p.name != member.name):
        status["warnings"].append("Shift requires a Male.")
    if shift_day in member.preferred_days: status["warnings"].append("✅ Matches User Preference!")
    return status

def parse_file(file_obj) -> List[Member]:
    try:
        if file_obj.name.endswith('.csv'): df = pd.read_csv(file_obj)
        else: df = pd.read_excel(file_obj)
    except: return []
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    for col in df.columns:
        c_lower = col.lower()
        if "name (first and last)" in c_lower: col_map["name"] = col
        elif "name" in c_lower and "user" not in c_lower: col_map["name"] = col
        elif "gender" in c_lower: col_map["gender"] = col
        elif "ok" in c_lower and "open" in c_lower: col_map["pref_open"] = col
        elif "ok" in c_lower and "clo" in c_lower: col_map["pref_close"] = col
        elif "select days" in c_lower and "prefer" in c_lower: col_map["pref_days"] = col
        elif "monday" in c_lower: col_map["Monday"] = col
        elif "tuesday" in c_lower: col_map["Tuesday"] = col
        elif "wednesday" in c_lower: col_map["Wednesday"] = col
        elif "thursday" in c_lower: col_map["Thursday"] = col
        elif "friday" in c_lower: col_map["Friday"] = col
    
    # [BUG FIX - Feature] Deduplication via Overwrite
    # Used a dictionary to ensure that if a name appears twice, 
    # the last occurrence overwrites the previous ones.
    members_map = {} 
    
    for idx, row in df.iterrows():
        if "name" not in col_map: break 
        name = str(row[col_map["name"]]).strip()
        gender = str(row[col_map["gender"]]).strip()
        avoid_open = "no" in str(row[col_map["pref_open"]]).lower()
        avoid_close = "no" in str(row[col_map["pref_close"]]).lower()
        pref_days = []
        if "pref_days" in col_map and pd.notna(row[col_map["pref_days"]]):
            raw_pref = str(row[col_map["pref_days"]])
            for d in ALL_DAYS:
                if d in raw_pref: pref_days.append(d)
        availability = {}
        for day in ALL_DAYS:
            if day not in col_map: continue
            day_idx = []
            val = str(row[col_map[day]])
            for t_str, t_idx in TIME_SLOTS.items():
                if t_str.replace(" ","") in val.replace(" ",""): day_idx.append(t_idx)
            if day_idx: availability[day] = day_idx
            
        # Overwrite if name exists
        members_map[name] = Member(name, gender, availability, avoid_open, avoid_close, pref_days)
        
    return list(members_map.values())

def generate_excel_bytes(schedule_grid, active_days, all_members=None):
    output = io.BytesIO()
    
    # --- SHEET 1: SCHEDULE ---
    data_rows = []
    def sort_order(shift):
        d_map = {day: i for i, day in enumerate(ALL_DAYS)}
        return (shift.time_idx * 10) + d_map.get(shift.day, 0)

    shifts_to_print = sorted([s for s in schedule_grid if s.day in active_days], key=sort_order)
    assigned_names = set()

    for time_label, time_idx in TIME_SLOTS.items():
        row_a = {"Time": time_label}; row_b = {"Time": ""}
        for day in active_days:
            shift = next((s for s in shifts_to_print if s.day == day and s.time_idx == time_idx), None)
            p1, p2 = "---", "---"
            if shift:
                p1, p2 = "UNFILLED", "UNFILLED"
                if len(shift.assigned_members) >= 1: 
                    name = shift.assigned_members[0].name
                    p1 = name
                    # [BUG FIX 3] Name Processing Error
                    assigned_names.add(name.strip())
                if len(shift.assigned_members) >= 2: 
                    name = shift.assigned_members[1].name
                    p2 = name
                    assigned_names.add(name.strip())
            row_a[day] = p1; row_b[day] = p2
        data_rows.append(row_a); data_rows.append(row_b)

    df_schedule = pd.DataFrame(data_rows)
    cols = ["Time"] + active_days
    df_schedule = df_schedule[cols]
    
    # --- SHEET 2: UNASSIGNED MEMBERS ---
    unassigned_rows = []
    if all_members:
        idx_to_label = {v: k for k, v in TIME_SLOTS.items()}
        for m in all_members:
            if m.name not in assigned_names:
                avail_count = sum(len(v) for v in m.availability.values())
                
                avail_parts = []
                for day, slots in m.availability.items():
                    if slots:
                        labels = [idx_to_label.get(s, "?") for s in sorted(slots)]
                        avail_parts.append(f"{day}: {', '.join(labels)}")
                
                unassigned_rows.append({
                    "Name": m.name,
                    "Gender": m.gender,
                    "Total Slots Free": avail_count,
                    "Detailed Availability": " | ".join(avail_parts),
                    "Avoids Opening": "Yes" if m.avoid_opening else "No",
                    "Avoids Closing": "Yes" if m.avoid_closing else "No",
                    "Preferred Days": ", ".join(m.preferred_days) if m.preferred_days else "None"
                })
    
    df_unassigned = pd.DataFrame(unassigned_rows)
    if not df_unassigned.empty:
        df_unassigned.sort_values(by="Total Slots Free", ascending=False, inplace=True)

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_schedule.to_excel(writer, index=False, sheet_name='Final Schedule')
        if not df_unassigned.empty:
            df_unassigned.to_excel(writer, index=False, sheet_name='Unassigned Members')
        else:
            pd.DataFrame({"Status": ["All members assigned!"]}).to_excel(writer, index=False, sheet_name='Unassigned Members')
        
        workbook = writer.book
        worksheet = workbook.add_worksheet('Legend')
        worksheet.write(0, 0, "(*) Name")
        worksheet.write(0, 1, "Suggested because no perfect match found.")
        worksheet.write(1, 0, "(* 2nd Shift)")
        worksheet.write(1, 1, "Already assigned elsewhere (2nd shift).")

    return output.getvalue()