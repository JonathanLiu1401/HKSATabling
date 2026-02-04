import streamlit as st
import scheduler_core as core
import pandas as pd
import copy

st.set_page_config(page_title="HKSA Scheduler", page_icon="📅", layout="wide")

if 'members' not in st.session_state: st.session_state['members'] = []
if 'schedule_grid' not in st.session_state: st.session_state['schedule_grid'] = []
if 'active_days' not in st.session_state: st.session_state['active_days'] = []

st.title("📅 HKSA Tabling Scheduler Pro")

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Configuration")
    all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    selected_days = st.multiselect("Active Days:", all_days, default=all_days)
    st.session_state['active_days'] = selected_days
    
    st.header("2. Upload Data")
    uploaded_file = st.file_uploader("Upload Availability.csv", type=["csv", "xlsx"])
    
    if uploaded_file:
        try:
            members = core.parse_file(uploaded_file)
            st.session_state['members'] = members
            st.success(f"Loaded {len(members)} members")
        except Exception as e:
            st.error(f"Error parsing: {e}")

    st.header("3. Actions")
    if st.button("🚀 Auto-Generate Schedule", type="primary"):
        if not st.session_state['members']:
            st.error("Upload data first!")
        else:
            with st.spinner("Solving..."):
                scheduler = core.Scheduler(st.session_state['members'], active_days=selected_days)
                success = scheduler.solve()
                st.session_state['schedule_grid'] = scheduler.schedule_grid
                if success: st.success("Perfect schedule found!")
                else: st.warning("Generated with suggestions.")

# --- HELPER FUNCTIONS ---
def get_member_options(day, time_idx, current_shift_members):
    options = []
    current_names = [m.name for m in current_shift_members]
    for m in st.session_state['members']:
        label = m.name
        # Check matching including prefix variations
        is_assigned_here = any(curr_name == m.name or curr_name.endswith(f" {m.name}") for curr_name in current_names)
        
        is_free = m.is_available(day, time_idx)
        shift_count = len(m.assigned_shifts)
        is_pref = day in m.preferred_days
        
        status_icon = ""
        if is_assigned_here: continue
        if is_free:
            if is_pref: status_icon = "🌟"
            elif shift_count == 0: status_icon = "✅"
            else: status_icon = "⚠️"
        else: status_icon = "⛔"
        options.append(f"{status_icon} {m.name}")
    options.sort() 
    return options

def find_member_by_str(name_str):
    if not name_str: return None
    # Remove icon prefix if exists (e.g. "✅ Name")
    parts = name_str.split(" ")
    # If the first part is an emoji/icon, skip it
    if len(parts) > 1 and any(char in parts[0] for char in ["✅", "⛔", "⚠️", "🌟", "👤"]):
        clean_name = " ".join(parts[1:])
    else:
        clean_name = name_str
        
    for m in st.session_state['members']:
        if m.name == clean_name: return m
    return None

def find_member_exact(name):
    for m in st.session_state['members']:
        if m.name == name: return m
    return None

def perform_overwrite_assign(target_shift, new_members):
    """
    Strictly assigns new_members to target_shift.
    1. Removes new_members from any OLD slots they had (including fixing 'Suggestion' copies).
    2. Frees up the people currently in target_shift.
    3. Assigns new_members to target_shift.
    """
    grid = st.session_state['schedule_grid']
    
    # 1. Clean up the NEW members (Remove them from old slots)
    for p_new in new_members:
        # Search entire grid to see where they were
        for shift in grid:
            # Iterate a copy of the list so we can remove safely
            for p_curr in shift.assigned_members[:]:
                # Check for Match:
                # 1. Exact Object Match
                # 2. Exact Name Match
                # 3. Suggestion Copy Match (e.g. "(*) Jonathan" matches "Jonathan")
                is_match = (p_curr == p_new) or \
                           (p_curr.name == p_new.name) or \
                           (p_curr.name.endswith(f" {p_new.name}"))
                
                if is_match:
                    shift.assigned_members.remove(p_curr)
                    # Also ensure the tuple is removed from the real member's record
                    if (shift.day, shift.time_idx) in p_new.assigned_shifts:
                        p_new.assigned_shifts.remove((shift.day, shift.time_idx))

    # 2. Clean up the OLD members in the target slot (Free them up)
    for old_m in target_shift.assigned_members:
        # If the old member is NOT one of the new ones
        if old_m not in new_members:
            # We need to find the REAL object corresponding to old_m (in case old_m is a copy)
            real_old_m = find_member_exact(old_m.name.split(")")[-1].strip())
            
            if real_old_m:
                if (target_shift.day, target_shift.time_idx) in real_old_m.assigned_shifts:
                    real_old_m.assigned_shifts.remove((target_shift.day, target_shift.time_idx))

    # 3. Assign
    target_shift.assigned_members = new_members
    for p in new_members:
        p.assigned_shifts.append((target_shift.day, target_shift.time_idx))


# --- MAIN UI ---
if not st.session_state['schedule_grid']:
    st.info("👈 Upload your file and click 'Auto-Generate' to start.")
else:
    tab1, tab2, tab3 = st.tabs(["📊 View", "✏️ Live Editor", "Partner Matcher"])
    grid = st.session_state['schedule_grid']
    
    # --- TAB 1: VIEW ---
    with tab1:
        data_rows = []
        for time_label, time_idx in core.TIME_SLOTS.items():
            row_a = {"Time": time_label}; row_b = {"Time": ""}
            for day in selected_days:
                shift = next((s for s in grid if s.day == day and s.time_idx == time_idx), None)
                p1, p2 = "-", "-"
                if shift:
                    if len(shift.assigned_members) >= 1: p1 = shift.assigned_members[0].name
                    if len(shift.assigned_members) >= 2: p2 = shift.assigned_members[1].name
                row_a[day] = p1; row_b[day] = p2
            data_rows.append(row_a); data_rows.append(row_b)
        st.dataframe(pd.DataFrame(data_rows), use_container_width=True, hide_index=True)
        st.download_button("📥 Download Excel", core.generate_excel_bytes(grid, selected_days), "Final_Schedule.xlsx")

    # --- TAB 2: EDITOR ---
    with tab2:
        col1, col2 = st.columns(2)
        with col1: edit_day = st.selectbox("Select Day", selected_days)
        with col2: 
            edit_time_label = st.selectbox("Select Time", list(core.TIME_SLOTS.keys()))
            edit_time_idx = core.TIME_SLOTS[edit_time_label]
        
        target_shift = next((s for s in grid if s.day == edit_day and s.time_idx == edit_time_idx), None)
        if target_shift:
            st.divider()
            current_p1 = target_shift.assigned_members[0] if len(target_shift.assigned_members) > 0 else None
            current_p2 = target_shift.assigned_members[1] if len(target_shift.assigned_members) > 1 else None
            
            # P1 Editor
            opts1 = get_member_options(edit_day, edit_time_idx, target_shift.assigned_members)
            if current_p1: opts1.insert(0, f"👤 {current_p1.name}")
            else: opts1.insert(0, "(Unfilled)")
            sel1 = st.selectbox("Slot 1", opts1, key="p1_ed")
            
            # P2 Editor
            opts2 = get_member_options(edit_day, edit_time_idx, target_shift.assigned_members)
            if current_p2: opts2.insert(0, f"👤 {current_p2.name}")
            else: opts2.insert(0, "(Unfilled)")
            sel2 = st.selectbox("Slot 2", opts2, key="p2_ed")

            # Apply Changes Button
            if st.button("Update Slot"):
                new_members = []
                
                # Resolve P1
                if sel1 != "(Unfilled)":
                    m1 = find_member_by_str(sel1)
                    if m1: new_members.append(m1)
                
                # Resolve P2
                if sel2 != "(Unfilled)":
                    m2 = find_member_by_str(sel2)
                    if m2: 
                        # Prevent duplicate if user selected same person twice
                        if m2 not in new_members: new_members.append(m2)
                
                # Use the strict overwrite function
                perform_overwrite_assign(target_shift, new_members)
                st.success("Updated!")
                st.rerun()

    # --- TAB 3: PARTNER MATCHER ---
    with tab3:
        st.subheader("Partner Matcher")
        st.markdown("Select two people to find their best overlapping slot. Assigning them will **automatically remove** them from any previous shifts.")
        
        all_names = sorted([m.name for m in st.session_state['members']])
        col_a, col_b = st.columns(2)
        with col_a: name_a = st.selectbox("Person A", all_names, key="match_a")
        with col_b: name_b = st.selectbox("Person B", all_names, key="match_b")
        
        if name_a and name_b:
            if name_a == name_b:
                st.error("Select two different people.")
            else:
                p1 = find_member_exact(name_a)
                p2 = find_member_exact(name_b)
                
                best_slots = core.find_best_slots_for_pair(p1, p2, selected_days)
                
                if not best_slots:
                    st.error("No overlapping availability found for these two!")
                else:
                    st.success(f"Found {len(best_slots)} common slots!")
                    
                    for i, slot in enumerate(best_slots[:3]):
                        with st.container():
                            c1, c2, c3 = st.columns([2, 4, 2])
                            with c1:
                                st.markdown(f"**{slot['day']}**")
                                st.caption(slot['time_label'])
                            with c2:
                                st.info(f"Score: {slot['score']} ({slot['reason']})")
                            with c3:
                                if st.button("Assign Pair", key=f"btn_{i}"):
                                    # Find the target shift object
                                    target = next((s for s in grid if s.day == slot['day'] and s.time_idx == slot['time_idx']), None)
                                    if target:
                                        # Use the strict overwrite function
                                        perform_overwrite_assign(target, [p1, p2])
                                        st.toast(f"Assigned {name_a} & {name_b}!", icon="✅")
                                        st.rerun()