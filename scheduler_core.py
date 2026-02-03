import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
import io

# --- CONSTANTS ---
TIME_SLOTS = {
    "10:30-11:30": 0,
    "11:30-12:30": 1,
    "12:30-1:30": 2,
    "1:30-2:30": 3
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# --- DATA CLASSES ---
@dataclass
class Member:
    name: str
    gender: str
    availability: Dict[str, List[int]] 
    avoid_opening: bool
    avoid_closing: bool
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

# --- SCHEDULER LOGIC ---
class Scheduler:
    def __init__(self, members: List[Member]):
        self.members = members
        self.schedule_grid = self._initialize_grid()
        
    def _initialize_grid(self) -> List[Shift]:
        grid = []
        for day in DAYS:
            for label, idx in TIME_SLOTS.items():
                grid.append(Shift(day, idx, label))
        return grid

    def solve(self) -> bool:
        # Sort members by availability (most restricted first)
        self.members.sort(key=lambda m: sum(len(v) for v in m.availability.values()))
        return self._backtrack(0)

    def _backtrack(self, shift_index: int) -> bool:
        if shift_index >= len(self.schedule_grid): return self._verify_global_constraints()
        current_shift = self.schedule_grid[shift_index]
        potential_pairs = self._get_valid_pairs(current_shift)
        
        for p1, p2 in potential_pairs:
            current_shift.assigned_members = [p1, p2]
            p1.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            p2.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            
            if self._backtrack(shift_index + 1): return True
            
            current_shift.assigned_members = []
            p1.assigned_shifts.pop()
            p2.assigned_shifts.pop()
        return False

    def _get_valid_pairs(self, shift: Shift):
        available_people = [m for m in self.members if m.is_available(shift.day, shift.time_idx)]
        valid_pairs = []
        from itertools import combinations
        for p1, p2 in combinations(available_people, 2):
            if shift.needs_male():
                if p1.gender != 'Male' and p2.gender != 'Male': continue
            valid_pairs.append((p1, p2))
        return valid_pairs

    def _verify_global_constraints(self) -> bool:
        for member in self.members:
            if len(member.assigned_shifts) < 1: return False
        return True

# --- I/O HELPERS ---
def parse_file(file_obj) -> List[Member]:
    try:
        if file_obj.name.endswith('.csv'):
            df = pd.read_csv(file_obj)
        else:
            df = pd.read_excel(file_obj)
    except Exception as e:
        return []

    # Clean headers
    df.columns = [str(c).strip() for c in df.columns]
    
    # Map columns
    col_map = {}
    for col in df.columns:
        c_lower = col.lower()
        if "name (first and last)" in c_lower: col_map["name"] = col
        elif "name" in c_lower and "user" not in c_lower: col_map["name"] = col
        elif "gender" in c_lower: col_map["gender"] = col
        elif "ok" in c_lower and "open" in c_lower: col_map["pref_open"] = col
        elif "ok" in c_lower and "clo" in c_lower: col_map["pref_close"] = col
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
        
        raw_open = str(row[col_map["pref_open"]]).lower()
        raw_close = str(row[col_map["pref_close"]]).lower()
        avoid_open = "no" in raw_open
        avoid_close = "no" in raw_close
        
        availability = {}
        for day in DAYS:
            if day not in col_map: continue
            day_idx = []
            val = str(row[col_map[day]])
            for t_str, t_idx in TIME_SLOTS.items():
                if t_str.replace(" ","") in val.replace(" ",""):
                    day_idx.append(t_idx)
            if day_idx: availability[day] = day_idx
        members.append(Member(name, gender, availability, avoid_open, avoid_close))
    return members

def generate_excel_bytes(schedule_grid):
    output = io.BytesIO()
    data_rows = []
    
    # Create 2 rows per time slot
    for time_label, time_idx in TIME_SLOTS.items():
        row_a = {"Time": time_label}
        row_b = {"Time": ""}
        
        for day in DAYS:
            shift = next((s for s in schedule_grid if s.day == day and s.time_idx == time_idx), None)
            p1, p2 = "UNFILLED", "UNFILLED"
            if shift and len(shift.assigned_members) >= 1: p1 = shift.assigned_members[0].name
            if shift and len(shift.assigned_members) >= 2: p2 = shift.assigned_members[1].name
            
            row_a[day] = p1
            row_b[day] = p2
            
        data_rows.append(row_a)
        data_rows.append(row_b)

    df = pd.DataFrame(data_rows)
    cols = ["Time"] + DAYS
    df = df[cols]
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Final Schedule')
    return output.getvalue()