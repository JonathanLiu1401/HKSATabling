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
                else: st.warning("Could not find a perfect fit. Partial schedule generated (no suggestions used).")

# --- HELPER FUNCTIONS ---
def get_member_options(day, time_idx, current_shift_members):
    options = []
    current_names = [m.name for m in current_shift_members]
    for m in st.session_state['members']:
        label = m.name
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
    parts = name_str.split(" ")
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
    grid = st.session_state['schedule_grid']
    for p_new in new_members:
        for shift in grid:
            for p_curr in shift.assigned_members[:]:
                is_match = (p_curr == p_new) or (p_curr.name == p_new.name) or (p_curr.name.endswith(f" {p_new.name}"))
                if is_match:
                    shift.assigned_members.remove(p_curr)
                    if (shift.day, shift.time_idx) in p_new.assigned_shifts:
                        p_new.assigned_shifts.remove((shift.day, shift.time_idx))
    for old_m in target_shift.assigned_members:
        if old_m not in new_members:
            real_old_m = find_member_exact(old_m.name.split(")")[-1].strip())
            if real_old_m and (target_shift.day, target_shift.time_idx) in real_old_m.assigned_shifts:
                real_old_m.assigned_shifts.remove((target_shift.day, target_shift.time_idx))
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
        st.subheader("Tabling Schedule")
        data_rows = []
        assigned_names = set()

        for time_label, time_idx in core.TIME_SLOTS.items():
            row_a = {"Time": time_label}; row_b = {"Time": ""}
            for day in selected_days:
                shift = next((s for s in grid if s.day == day and s.time_idx == time_idx), None)
                p1, p2 = "-", "-"
                if shift:
                    if len(shift.assigned_members) >= 1: 
                        p1 = shift.assigned_members[0].name
                        assigned_names.add(p1.split(")")[-1].strip())
                        if shift.locked: p1 += " 🔒"
                    if len(shift.assigned_members) >= 2: 
                        p2 = shift.assigned_members[1].name
                        assigned_names.add(p2.split(")")[-1].strip())
                        if shift.locked: p2 += " 🔒"
                row_a[day] = p1; row_b[day] = p2
            data_rows.append(row_a); data_rows.append(row_b)
        st.dataframe(pd.DataFrame(data_rows), use_container_width=True, hide_index=True)
        st.download_button("📥 Download Excel", core.generate_excel_bytes(grid, selected_days, st.session_state['members']), "Final_Schedule.xlsx")

        st.divider()
        st.subheader("⚠️ Unassigned Members")
        unassigned_data = []
        idx_to_label = {v: k for k, v in core.TIME_SLOTS.items()}
        for m in st.session_state['members']:
            if m.name not in assigned_names:
                total_avail = sum(len(v) for v in m.availability.values())
                avail_parts = []
                for day, slots in m.availability.items():
                    if slots:
                        labels = [idx_to_label.get(s, "?") for s in sorted(slots)]
                        avail_parts.append(f"{day}: {', '.join(labels)}")
                
                unassigned_data.append({
                    "Name": m.name, 
                    "Gender": m.gender, 
                    "Slots Free": total_avail, 
                    "Availability": " | ".join(avail_parts),
                    "No Open": "Yes" if m.avoid_opening else "No",
                    "No Close": "Yes" if m.avoid_closing else "No"
                })
        if unassigned_data:
            st.dataframe(pd.DataFrame(unassigned_data).sort_values(by="Slots Free", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.success("🎉 All members assigned!")

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
            
            # --- UNLOCK BUTTON ---
            if target_shift.locked:
                c_lock, c_msg = st.columns([1, 4])
                with c_lock:
                    if st.button("🔓 Unlock Slot", type="primary"):
                        target_shift.locked = False
                        st.rerun()
                with c_msg:
                    st.warning("This slot is locked. Unlocking it allows it to be edited or re-rolled.")
            
            current_p1 = target_shift.assigned_members[0] if len(target_shift.assigned_members) > 0 else None
            current_p2 = target_shift.assigned_members[1] if len(target_shift.assigned_members) > 1 else None
            
            opts1 = get_member_options(edit_day, edit_time_idx, target_shift.assigned_members)
            if current_p1: opts1.insert(0, f"👤 {current_p1.name}")
            else: opts1.insert(0, "(Unfilled)")
            sel1 = st.selectbox("Slot 1", opts1, key="p1_ed")
            
            opts2 = get_member_options(edit_day, edit_time_idx, target_shift.assigned_members)
            if current_p2: opts2.insert(0, f"👤 {current_p2.name}")
            else: opts2.insert(0, "(Unfilled)")
            sel2 = st.selectbox("Slot 2", opts2, key="p2_ed")

            if st.button("Update Slot"):
                new_members = []
                if sel1 != "(Unfilled)":
                    m1 = find_member_by_str(sel1)
                    if m1: new_members.append(m1)
                if sel2 != "(Unfilled)":
                    m2 = find_member_by_str(sel2)
                    if m2 and m2 not in new_members: new_members.append(m2)
                
                perform_overwrite_assign(target_shift, new_members)
                target_shift.locked = False # Manual edit breaks lock
                st.success("Updated!")
                st.rerun()

    # --- TAB 3: PARTNER MATCHER (RE-ROLL) ---
    with tab3:
        st.subheader("Partner Matcher & Re-roll")
        st.markdown("Assign a pair to a slot and **re-optimize the entire schedule** around them.")
        
        all_names = sorted([m.name for m in st.session_state['members']])
        col_a, col_b = st.columns(2)
        with col_a: name_a = st.selectbox("Person A", all_names, key="match_a")
        with col_b: name_b = st.selectbox("Person B", all_names, key="match_b")
        
        if name_a and name_b and name_a != name_b:
            p1 = find_member_exact(name_a)
            p2 = find_member_exact(name_b)
            best_slots = core.find_best_slots_for_pair(p1, p2, selected_days)
            
            if not best_slots:
                st.error("No overlapping availability found for these two!")
            else:
                st.success(f"Found {len(best_slots)} common slots")
                for i, slot in enumerate(best_slots[:3]):
                    with st.container():
                        c1, c2, c3 = st.columns([2, 4, 2])
                        with c1:
                            st.markdown(f"**{slot['day']}**")
                            st.caption(slot['time_label'])
                        with c2: st.info(f"Score: {slot['score']} ({slot['reason']})")
                        with c3:
                            if st.button("Lock & Reroll", key=f"btn_{i}"):
                                # DUPLICATE CHECK
                                already_locked = False
                                for s in grid:
                                    if s.locked:
                                        curr_names = [m.name for m in s.assigned_members]
                                        if name_a in curr_names or name_b in curr_names:
                                            already_locked = True
                                            break
                                if already_locked:
                                    st.error("One of these members is already in a locked slot! Unlock them first in 'Live Editor'.")
                                else:
                                    with st.spinner("Re-optimizing schedule..."):
                                        target = next((s for s in grid if s.day == slot['day'] and s.time_idx == slot['time_idx']), None)
                                        perform_overwrite_assign(target, []) 
                                        target.assigned_members = [p1, p2]
                                        target.locked = True
                                        
                                        scheduler = core.Scheduler(st.session_state['members'], active_days=selected_days, pre_filled_grid=grid)
                                        success = scheduler.solve()
                                        st.session_state['schedule_grid'] = scheduler.schedule_grid
                                        
                                        st.toast("Schedule re-optimized!", icon="🔄")
                                        st.rerun()

        st.divider()
        st.subheader("🔒 Locked Shifts Manager")
        
        locked_shifts = [s for s in grid if s.locked]
        
        if not locked_shifts:
            st.info("No shifts are currently locked.")
        else:
            for i, shift in enumerate(locked_shifts):
                c1, c2, c3 = st.columns([2, 4, 2])
                with c1:
                    st.write(f"**{shift.day}**")
                    st.caption(shift.time_label)
                with c2:
                    names = [m.name for m in shift.assigned_members]
                    st.write(", ".join(names) if names else "(Empty)")
                with c3:
                    if st.button("🔓 Unlock", key=f"unlock_{i}_{shift.day}_{shift.time_idx}"):
                        shift.locked = False
                        st.success("Unlocked!")
                        st.rerun()