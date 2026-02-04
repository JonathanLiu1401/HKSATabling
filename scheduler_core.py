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
    
    def needs_male(self):
        return self.time_idx == 0 or self.time_idx == 3 

    def is_valid(self):
        if len(self.assigned_members) != 2: return False
        if self.needs_male():
            if not any(m.gender == 'Male' for m in self.assigned_members): return False
        return True

class Scheduler:
    def __init__(self, members: List[Member], active_days: List[str] = None):
        self.members = members
        self.active_days = active_days if active_days else ALL_DAYS
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

        # Sort shifts by difficulty
        shift_difficulty = []
        for shift in self.schedule_grid:
            valid_pairs = self._get_valid_pairs(shift)
            shift_difficulty.append((len(valid_pairs), shift))
        
        shift_difficulty.sort(key=lambda x: x[0])
        self.schedule_grid = [item[1] for item in shift_difficulty]
        
        success = self._backtrack(0)
        
        if not success:
            print("Optimization failed. Restoring best partial solution...")
            self._restore_best_state()
            self._fill_with_suggestions()
            return False
        return True

    def _backtrack(self, shift_index: int) -> bool:
        self.attempts += 1
        if self.attempts > 200000: return False 

        if shift_index > self.max_filled_count:
            self.max_filled_count = shift_index
            self._save_current_state()

        if shift_index >= len(self.schedule_grid): 
            return True

        current_shift = self.schedule_grid[shift_index]
        potential_pairs = self._get_valid_pairs(current_shift)
        
        # Scoring: Preference > Load Balancing
        def pair_score(pair):
            p1, p2 = pair
            score = 0
            if current_shift.day in p1.preferred_days: score += 5
            if current_shift.day in p2.preferred_days: score += 5
            score -= (len(p1.assigned_shifts) + len(p2.assigned_shifts)) * 10
            return score

        potential_pairs.sort(key=pair_score, reverse=True)

        for p1, p2 in potential_pairs:
            current_shift.assigned_members = [p1, p2]
            p1.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            p2.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            
            if self._backtrack(shift_index + 1): return True
            
            # Backtrack
            current_shift.assigned_members = []
            p1.assigned_shifts.pop()
            p2.assigned_shifts.pop()
            
        return False

    def _save_current_state(self):
        state = {}
        for shift in self.schedule_grid:
            names = [m.name for m in shift.assigned_members]
            state[(shift.day, shift.time_idx)] = names
        self.best_grid_state = state

    def _restore_best_state(self):
        for shift in self.schedule_grid:
            saved_names = self.best_grid_state.get((shift.day, shift.time_idx), [])
            restored_members = []
            for name in saved_names:
                mem = next((m for m in self.members if m.name == name), None)
                if mem: 
                    restored_members.append(mem)
                    mem.assigned_shifts.append((shift.day, shift.time_idx))
            shift.assigned_members = restored_members

    def _fill_with_suggestions(self):
        for shift in self.schedule_grid:
            if len(shift.assigned_members) == 2: continue 
            needed = 2 - len(shift.assigned_members)
            candidates = []
            for m in self.members:
                if m in shift.assigned_members: continue
                
                score = 0
                label = "(*)"
                
                if len(m.assigned_shifts) > 0:
                    score -= 1000
                    label = "(* 2nd Shift)"
                else:
                    score += 100 

                if shift.day in m.preferred_days: score += 50
                
                if shift.needs_male():
                    has_male = any(x.gender == 'Male' for x in shift.assigned_members)
                    if not has_male and m.gender == 'Male':
                        score += 50
                
                if m.is_available(shift.day, shift.time_idx): score += 10
                
                candidates.append((score, m, label))
            
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            for i in range(needed):
                if i < len(candidates):
                    _, best_member, label = candidates[i]
                    suggestion_dummy = copy.copy(best_member)
                    suggestion_dummy.name = f"{label} {best_member.name}"
                    shift.assigned_members.append(suggestion_dummy)

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

# --- HELPER: PARTNER MATCHING LOGIC ---
def find_best_slots_for_pair(p1: Member, p2: Member, active_days: List[str]) -> List[Dict]:
    """
    Finds all overlapping slots for two people and ranks them by optimality.
    """
    ranked_slots = []
    
    for day in active_days:
        for time_label, time_idx in TIME_SLOTS.items():
            # 1. Base Availability Check
            if p1.is_available(day, time_idx) and p2.is_available(day, time_idx):
                
                score = 100 # Start high
                reasons = ["Both Available"]
                
                # 2. Preference Bonus
                if day in p1.preferred_days:
                    score += 10
                    reasons.append(f"{p1.name} prefers {day}")
                if day in p2.preferred_days:
                    score += 10
                    reasons.append(f"{p2.name} prefers {day}")
                
                # 3. Gender / Heavy Lifting Validity
                needs_male = (time_idx == 0 or time_idx == 3)
                if needs_male:
                    has_male = (p1.gender == 'Male' or p2.gender == 'Male')
                    if not has_male:
                        score -= 50
                        reasons.append("⚠️ Missing Male (Heavy Lifting)")
                    else:
                        score += 5
                
                ranked_slots.append({
                    "day": day,
                    "time_idx": time_idx,
                    "time_label": time_label,
                    "score": score,
                    "reason": ", ".join(reasons)
                })
    
    # Sort by Score Descending
    ranked_slots.sort(key=lambda x: x['score'], reverse=True)
    return ranked_slots

# --- HELPER: MANUAL VALIDATION ---
def check_assignment_validity(member: Member, shift_day: str, shift_time_idx: int, current_partners: List[Member]) -> Dict:
    status = {"valid": True, "warnings": [], "errors": []}
    
    if not member.is_available(shift_day, shift_time_idx):
        status["warnings"].append("Not marked as available.")
        status["valid"] = False 

    if len(member.assigned_shifts) > 0:
         for s_day, s_time in member.assigned_shifts:
             if s_day == shift_day and s_time == shift_time_idx:
                 status["errors"].append("Already assigned to this slot.")
             else:
                 status["warnings"].append(f"Already working on {s_day} (2nd shift).")

    needs_male = (shift_time_idx == 0 or shift_time_idx == 3)
    if needs_male:
        other_male = any(p.gender == 'Male' for p in current_partners if p.name != member.name)
        if not other_male and member.gender != 'Male':
            status["warnings"].append("Shift requires a Male.")

    if shift_day in member.preferred_days:
        status["warnings"].append("✅ Matches User Preference!")

    return status

# --- I/O HELPERS ---
def parse_file(file_obj) -> List[Member]:
    try:
        if file_obj.name.endswith('.csv'):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)
    except Exception:
        return []

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

    members = []
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
                if t_str.replace(" ","") in val.replace(" ",""):
                    day_idx.append(t_idx)
            if day_idx: availability[day] = day_idx
            
        members.append(Member(name, gender, availability, avoid_open, avoid_close, pref_days))
    return members

def generate_excel_bytes(schedule_grid, active_days):
    output = io.BytesIO()
    data_rows = []
    
    def sort_order(shift):
        d_map = {day: i for i, day in enumerate(ALL_DAYS)}
        return (shift.time_idx * 10) + d_map.get(shift.day, 0)

    shifts_to_print = sorted([s for s in schedule_grid if s.day in active_days], key=sort_order)
    
    for time_label, time_idx in TIME_SLOTS.items():
        row_a = {"Time": time_label}
        row_b = {"Time": ""}
        
        for day in active_days:
            shift = next((s for s in shifts_to_print if s.day == day and s.time_idx == time_idx), None)
            p1, p2 = "---", "---"
            if shift:
                p1, p2 = "UNFILLED", "UNFILLED"
                if len(shift.assigned_members) >= 1: p1 = shift.assigned_members[0].name
                if len(shift.assigned_members) >= 2: p2 = shift.assigned_members[1].name
            row_a[day] = p1
            row_b[day] = p2
        data_rows.append(row_a)
        data_rows.append(row_b)

    df = pd.DataFrame(data_rows)
    cols = ["Time"] + active_days
    df = df[cols]
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Final Schedule')
        workbook = writer.book
        worksheet = workbook.add_worksheet('Legend')
        worksheet.write(0, 0, "(*) Name")
        worksheet.write(0, 1, "Suggested because no perfect match found.")
        worksheet.write(1, 0, "(* 2nd Shift)")
        worksheet.write(1, 1, "Already assigned elsewhere (2nd shift).")

    return output.getvalue()