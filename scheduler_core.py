import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import io
import copy
import json

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
    # NEW: Store temporary overrides. Structure: { "Monday": {0: False, 1: True} }
    # True = Force Available, False = Force Unavailable
    time_overrides: Dict[str, Dict[int, bool]] = field(default_factory=dict)

    def is_available(self, day: str, time_idx: int) -> bool:
        # 1. Check Overrides First
        if day in self.time_overrides and time_idx in self.time_overrides[day]:
            return self.time_overrides[day][time_idx]

        # 2. Standard Checks
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

class Scheduler:
    def __init__(self, members: List[Member], active_days: List[str] = None, 
                 pre_filled_grid: List[Shift] = None, forbidden_pairs: List[Tuple[str, str]] = None,
                 must_schedule: List[str] = None, never_schedule: List[str] = None):
        self.members = members
        self.active_days = active_days if active_days else ALL_DAYS
        self.forbidden_pairs = forbidden_pairs if forbidden_pairs else []
        self.must_schedule = must_schedule if must_schedule else []
        self.never_schedule = never_schedule if never_schedule else []
        
        if pre_filled_grid:
            self.schedule_grid = pre_filled_grid
        else:
            self.schedule_grid = self._initialize_grid()
            
        self.attempts = 0
        self.best_grid_state = {} 
        self.max_filled_count = -1
        self.top_schedules = []
        
        self.working_members = [m for m in self.members if m.name not in self.never_schedule]

    def _initialize_grid(self) -> List[Shift]:
        grid = []
        for day in self.active_days:
            for label, idx in TIME_SLOTS.items():
                grid.append(Shift(day, idx, label))
        return grid

    def solve(self) -> int:
        self.attempts = 0
        self.max_filled_count = -1
        self.best_grid_state = {}
        self.top_schedules = []

        # Clear assignments
        for m in self.members:
            m.assigned_shifts = []

        # Restore locks
        for shift in self.schedule_grid:
            if shift.locked:
                restored_members = []
                for m in shift.assigned_members:
                    real_m = next((x for x in self.members if x.name == m.name), None)
                    if real_m:
                        real_m.assigned_shifts.append((shift.day, shift.time_idx))
                        restored_members.append(real_m)
                shift.assigned_members = restored_members
            else:
                shift.assigned_members = []

        fully_locked = []
        partially_locked = []
        unlocked = []

        for s in self.schedule_grid:
            if s.locked:
                if len(s.assigned_members) >= 2: fully_locked.append(s)
                else: partially_locked.append(s)
            else:
                unlocked.append(s)

        def get_difficulty(shift):
            if len(shift.assigned_members) == 1:
                return len(self._get_valid_partners(shift, shift.assigned_members[0]))
            else:
                return len(self._get_valid_pairs(shift))

        processable = partially_locked + unlocked
        diff_list = [(get_difficulty(s), s) for s in processable]
        diff_list.sort(key=lambda x: x[0])
        
        self.schedule_grid = fully_locked + [x[1] for x in diff_list]
        
        start_index = len(fully_locked)
        
        try:
            self._backtrack(start_index)
        except StopIteration:
            pass 

        if self.top_schedules:
            self.top_schedules.sort(key=lambda x: x['score'], reverse=True)
            self.restore_state(self.top_schedules[0]['state'])
            return len(self.top_schedules)
        else:
            self.restore_state(self.best_grid_state)
            return 0

    def _backtrack(self, shift_index: int) -> bool:
        self.attempts += 1
        if self.attempts > 1000000: 
            raise StopIteration 

        current_filled_count = sum(1 for s in self.schedule_grid if len(s.assigned_members) == 2)
        
        if current_filled_count > self.max_filled_count:
            self.max_filled_count = current_filled_count
            self.best_grid_state = self._capture_state()

        if current_filled_count == len(self.schedule_grid):
            assigned_names = set()
            for s in self.schedule_grid:
                for m in s.assigned_members:
                    assigned_names.add(m.name)
            
            for must_name in self.must_schedule:
                if must_name not in assigned_names:
                    return False 
            
            score = 0
            for s in self.schedule_grid:
                for m in s.assigned_members:
                    if s.day in m.preferred_days: score += 5
            
            self.top_schedules.append({
                "state": self._capture_state(),
                "score": score,
                "description": f"Full Schedule (Score: {score})"
            })
            
            if len(self.top_schedules) >= 51:
                raise StopIteration
            
            return False 

        if shift_index >= len(self.schedule_grid): return False

        current_shift = self.schedule_grid[shift_index]

        if current_shift.locked and len(current_shift.assigned_members) >= 2:
            return self._backtrack(shift_index + 1)

        if len(current_shift.assigned_members) == 1:
            existing_member = current_shift.assigned_members[0]
            partners = self._get_valid_partners(current_shift, existing_member)
            
            for p in partners:
                current_shift.assigned_members.append(p)
                p.assigned_shifts.append((current_shift.day, current_shift.time_idx))
                
                self._backtrack(shift_index + 1)
                
                current_shift.assigned_members.pop()
                p.assigned_shifts.pop()
            return False

        potential_pairs = self._get_valid_pairs(current_shift)
        
        def pair_score(pair):
            p1, p2 = pair
            score = 0
            if p1.name in self.must_schedule: score += 1000
            if p2.name in self.must_schedule: score += 1000
            if current_shift.day in p1.preferred_days: score += 5
            if current_shift.day in p2.preferred_days: score += 5
            return score
            
        potential_pairs.sort(key=pair_score, reverse=True)

        for p1, p2 in potential_pairs:
            current_shift.assigned_members = [p1, p2]
            p1.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            p2.assigned_shifts.append((current_shift.day, current_shift.time_idx))
            
            self._backtrack(shift_index + 1) 
            
            current_shift.assigned_members = []
            p1.assigned_shifts.pop()
            p2.assigned_shifts.pop()
            
        return False

    def _capture_state(self):
        state = {}
        for shift in self.schedule_grid:
            names = [m.name for m in shift.assigned_members]
            state[(shift.day, shift.time_idx)] = names
        return state

    def restore_state(self, state_dict):
        for m in self.members: m.assigned_shifts = []
        for shift in self.schedule_grid:
            saved_names = state_dict.get((shift.day, shift.time_idx), [])
            restored = []
            for name in saved_names:
                mem = next((m for m in self.members if m.name == name), None)
                if mem: 
                    restored.append(mem)
                    mem.assigned_shifts.append((shift.day, shift.time_idx))
            shift.assigned_members = restored

    def _is_pair_forbidden(self, p1_name: str, p2_name: str) -> bool:
        for f1, f2 in self.forbidden_pairs:
            if (p1_name == f1 and p2_name == f2) or (p1_name == f2 and p2_name == f1):
                return True
        return False

    def _get_valid_pairs(self, shift: Shift):
        available_people = [
            m for m in self.working_members 
            if m.is_available(shift.day, shift.time_idx) and len(m.assigned_shifts) == 0
        ]
        valid_pairs = []
        from itertools import combinations
        for p1, p2 in combinations(available_people, 2):
            if self._is_pair_forbidden(p1.name, p2.name): continue
            if shift.needs_male():
                if p1.gender != 'Male' and p2.gender != 'Male': continue
            valid_pairs.append((p1, p2))
        return valid_pairs

    def _get_valid_partners(self, shift: Shift, current_member: Member):
        available_people = [
            m for m in self.working_members 
            if m.is_available(shift.day, shift.time_idx) and len(m.assigned_shifts) == 0 and m.name != current_member.name
        ]
        valid_partners = []
        for p in available_people:
            if self._is_pair_forbidden(current_member.name, p.name): continue
            if shift.needs_male():
                if current_member.gender != 'Male' and p.gender != 'Male': continue
            valid_partners.append(p)
        valid_partners.sort(key=lambda m: 1 if shift.day in m.preferred_days else 0, reverse=True)
        return valid_partners

# --- UTILS ---
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
        members_map[name] = Member(name, gender, availability, avoid_open, avoid_close, pref_days)
    return list(members_map.values())

def generate_excel_bytes(schedule_grid, active_days, all_members=None):
    output = io.BytesIO()
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
        
    return output.getvalue()

def export_configuration(schedule_grid, forbidden_pairs, active_days, must_schedule, never_schedule, members):
    """Serializes the current schedule state to a JSON string."""
    grid_data = []
    for shift in schedule_grid:
        grid_data.append({
            "day": shift.day,
            "time_idx": shift.time_idx,
            "locked": shift.locked,
            "assigned": [m.name for m in shift.assigned_members]
        })
    
    # NEW: Extract overrides from members
    overrides_data = {}
    for m in members:
        if m.time_overrides:
            # We need to serialize Dict[int, bool] keys to strings for JSON
            # { "Monday": { "0": true } }
            overrides_data[m.name] = {
                day: {str(t): val for t, val in times.items()} 
                for day, times in m.time_overrides.items()
            }

    return json.dumps({
        "active_days": active_days,
        "forbidden_pairs": forbidden_pairs,
        "must_schedule": must_schedule,
        "never_schedule": never_schedule,
        "overrides": overrides_data, # NEW
        "grid": grid_data
    }, indent=2)

def load_configuration(json_content, all_members):
    """
    Parses a JSON string and reconstructs the grid state.
    """
    data = json.loads(json_content)
    
    # 1. Restore Metadata
    active_days = data.get("active_days", ALL_DAYS)
    forbidden_pairs = [tuple(p) for p in data.get("forbidden_pairs", [])]
    must_schedule = data.get("must_schedule", [])
    never_schedule = data.get("never_schedule", [])
    
    # 2. Map existing member objects by name for quick lookup
    member_map = {m.name: m for m in all_members}
    
    # NEW: Restore Overrides
    overrides_data = data.get("overrides", {})
    for name, day_map in overrides_data.items():
        if name in member_map:
            # Convert keys back to int
            # { "Monday": {0: True} }
            restored_overrides = {}
            for day, t_map in day_map.items():
                restored_overrides[day] = {int(t): val for t, val in t_map.items()}
            member_map[name].time_overrides = restored_overrides

    # 3. Reconstruct Grid
    new_grid = []
    grid_data = data.get("grid", [])
    
    for slot_data in grid_data:
        day = slot_data["day"]
        time_idx = slot_data["time_idx"]
        time_label = next((k for k, v in TIME_SLOTS.items() if v == time_idx), "Unknown")
        
        new_shift = Shift(day, time_idx, time_label)
        new_shift.locked = slot_data["locked"]
        
        restored_members = []
        for name in slot_data["assigned"]:
            if name in member_map:
                member = member_map[name]
                restored_members.append(member)
                if (day, time_idx) not in member.assigned_shifts:
                    member.assigned_shifts.append((day, time_idx))
        
        new_shift.assigned_members = restored_members
        new_grid.append(new_shift)
        
    return active_days, forbidden_pairs, must_schedule, never_schedule, new_grid