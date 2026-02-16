import streamlit as st
import scheduler_core as core
import pandas as pd
import copy

st.set_page_config(page_title="HKSA Scheduler", page_icon="📅", layout="wide")

def apply_config_callback():
    """
    Called immediately when a file is uploaded, BEFORE the rest of the app runs.
    This allows us to update widget states safely.
    """
    uploaded_file = st.session_state.get('config_loader') # Access via key
    
    if uploaded_file and st.session_state.get('members'):
        try:
            # 1. Clear current assignments
            for m in st.session_state['members']:
                m.assigned_shifts = []

            # 2. Load and Parse
            a_days, f_pairs, must_s, never_s, new_grid = core.load_configuration(
                uploaded_file.getvalue(), 
                st.session_state['members']
            )
            
            # 3. Update Session State
            st.session_state['active_days_selection'] = a_days  
            st.session_state['active_days'] = a_days
            st.session_state['forbidden_pairs'] = f_pairs
            st.session_state['must_schedule'] = must_s
            st.session_state['never_schedule'] = never_s
            st.session_state['schedule_grid'] = new_grid
            st.session_state['top_schedules'] = [] # Reset tops on manual load
            st.session_state['last_stable_state'] = {} # Reset diff history
            
        except Exception as e:
            st.error(f"Error applying config: {e}")

if 'members' not in st.session_state: st.session_state['members'] = []
if 'schedule_grid' not in st.session_state: st.session_state['schedule_grid'] = []
if 'active_days_selection' not in st.session_state: st.session_state['active_days_selection'] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
if 'active_days' not in st.session_state: st.session_state['active_days'] = []
if 'editor_selected_slot' not in st.session_state: st.session_state['editor_selected_slot'] = None
if 'forbidden_pairs' not in st.session_state: st.session_state['forbidden_pairs'] = []
if 'top_schedules' not in st.session_state: st.session_state['top_schedules'] = []
if 'file_hash' not in st.session_state: st.session_state['file_hash'] = 0
if 'must_schedule' not in st.session_state: st.session_state['must_schedule'] = []
if 'never_schedule' not in st.session_state: st.session_state['never_schedule'] = []
# NEW: Store the last "good" state to calculate diffs against
if 'last_stable_state' not in st.session_state: st.session_state['last_stable_state'] = {}

st.title("📅 HKSA Tabling Scheduler Pro")

# --- HELPER: Capture State Wrapper ---
def capture_current_state():
    state = {}
    for shift in st.session_state['schedule_grid']:
        names = [m.name for m in shift.assigned_members]
        state[(shift.day, shift.time_idx)] = names
    return state

# --- SIDEBAR ---
with st.sidebar:
    st.header("1. Configuration")
    all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    selected_days = st.multiselect("Active Days:", all_days, key="active_days_selection")
    st.session_state['active_days'] = selected_days
    
    st.header("2. Upload Data")
    uploaded_file = st.file_uploader("Upload Availability.csv", type=["csv", "xlsx"])
    
    if uploaded_file:
        current_hash = hash(uploaded_file.getvalue())
        if current_hash != st.session_state['file_hash']:
            st.session_state['file_hash'] = current_hash
            try:
                members = core.parse_file(uploaded_file)
                st.session_state['members'] = members
                st.session_state['top_schedules'] = [] 
                st.session_state['schedule_grid'] = []
                st.session_state['last_stable_state'] = {}
                st.success(f"Loaded {len(members)} members")
            except Exception as e:
                st.error(f"Error parsing: {e}")
        elif st.session_state['members']:
            st.info(f"Loaded {len(st.session_state['members'])} members")

    st.header("3. Actions")
    if st.button("🚀 Auto-Generate Schedule", type="primary"):
        if not st.session_state['members']:
            st.error("Upload data first!")
        else:
            with st.spinner("Solving..."):
                # Initial solve, no previous state to compare to
                st.session_state['last_stable_state'] = {}
                scheduler = core.Scheduler(
                    st.session_state['members'], 
                    active_days=selected_days, 
                    forbidden_pairs=st.session_state['forbidden_pairs'],
                    must_schedule=st.session_state['must_schedule'],
                    never_schedule=st.session_state['never_schedule']
                )
                success_count = scheduler.solve()
                st.session_state['schedule_grid'] = scheduler.schedule_grid
                st.session_state['top_schedules'] = scheduler.top_schedules 
                st.session_state['editor_selected_slot'] = None 
                # After generate, save as stable state
                st.session_state['last_stable_state'] = capture_current_state()
                
                if success_count > 0: 
                    st.success(f"Found {success_count} valid schedules!")
                else: 
                    st.warning("Could not find a valid schedule with these constraints.")

    # --- SAVE/LOAD ---
    st.divider()
    st.header("4. Save/Load Config")
    
    if st.session_state['schedule_grid']:
        config_json = core.export_configuration(
            st.session_state['schedule_grid'],
            st.session_state['forbidden_pairs'],
            st.session_state['active_days'],
            st.session_state['must_schedule'],
            st.session_state['never_schedule'],
            st.session_state['members'] 
        )
        st.download_button(
            label="💾 Save Configuration",
            data=config_json,
            file_name="hksa_scheduler_config.json",
            mime="application/json",
            help="Download a file containing the current schedule, locks, conflict rules, and participation constraints."
        )

    st.file_uploader(
        "Load Config (.json)", 
        type=["json"], 
        key="config_loader", 
        on_change=apply_config_callback
    )

    if st.session_state.get('config_loader') and not st.session_state.get('members'):
        st.warning("⚠️ Please upload the Availability CSV first!")

# --- HELPER FUNCTIONS ---
def get_member_options(day, time_idx, current_shift_members):
    options = []
    current_names = [m.name for m in current_shift_members]
    active_members = [m for m in st.session_state['members'] if m.name not in st.session_state['never_schedule']]
    
    for m in active_members:
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

def select_slot(day, time_idx):
    st.session_state['editor_selected_slot'] = (day, time_idx)

# --- MAIN UI ---
if not st.session_state['schedule_grid']:
    st.info("👈 Upload your file and click 'Auto-Generate' to start.")
else:
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 View", 
        "✏️ Live Editor (Grid)", 
        "Partner Matcher", 
        "Conflict Manager", 
        "🛑 Participation",
        "⏳ Time Manager"
    ])
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
            if m.name not in assigned_names and m.name not in st.session_state['never_schedule']:
                total_avail = sum(len(v) for v in m.availability.values())
                avail_parts = []
                for day, slots in m.availability.items():
                    if slots:
                        labels = [idx_to_label.get(s, "?") for s in sorted(slots)]
                        avail_parts.append(f"{day}: {', '.join(labels)}")
                unassigned_data.append({
                    "Name": m.name, "Gender": m.gender, "Slots Free": total_avail, "Availability": " | ".join(avail_parts),
                    "No Open": "Yes" if m.avoid_opening else "No", "No Close": "Yes" if m.avoid_closing else "No"
                })
        if unassigned_data:
            st.dataframe(pd.DataFrame(unassigned_data).sort_values(by="Slots Free", ascending=False), use_container_width=True, hide_index=True)
        else:
            st.success("🎉 All (active) members assigned!")

    # --- TAB 2: EDITOR ---
    with tab2:
        if st.session_state.get('top_schedules'):
            count = len(st.session_state['top_schedules'])
            count_label = ">50" if count > 50 else str(count)
            with st.expander(f"💎 Generated Options ({count_label} found)", expanded=True):
                # NEW: Show Changes
                st.caption("ℹ️ **Least Changes Mode:** Options with fewest changes from previous schedule are prioritized.")
                
                opts = range(min(count, 50))
                def fmt_func(idx):
                    s = st.session_state['top_schedules'][idx]
                    changes = s.get('changes', 0)
                    score = s['score']
                    return f"Option {idx+1} (Changes: {changes} | Score: {score})"
                
                c_sel, c_btn = st.columns([3, 1])
                with c_sel: selected_opt_idx = st.selectbox("Select Version to Load:", opts, format_func=fmt_func)
                with c_btn:
                    st.write("") 
                    if st.button("🔄 Apply Option"):
                        target_state = st.session_state['top_schedules'][selected_opt_idx]['state']
                        scheduler = core.Scheduler(st.session_state['members'], active_days=selected_days, pre_filled_grid=grid)
                        scheduler.restore_state(target_state)
                        st.session_state['schedule_grid'] = scheduler.schedule_grid
                        st.session_state['editor_selected_slot'] = None
                        st.success(f"Applied Option {selected_opt_idx+1}!")
                        st.rerun()
            st.divider()

        st.markdown("### 👆 Select a slot to edit")
        cols_config = [0.8] + [1 for _ in selected_days]
        header_cols = st.columns(cols_config)
        header_cols[0].write("**Time**")
        for i, day in enumerate(selected_days): header_cols[i+1].write(f"**{day}**")
            
        for time_label, time_idx in core.TIME_SLOTS.items():
            row_cols = st.columns(cols_config)
            row_cols[0].markdown(f"**{time_label}**")
            for i, day in enumerate(selected_days):
                shift = next((s for s in grid if s.day == day and s.time_idx == time_idx), None)
                if shift:
                    names = [m.name for m in shift.assigned_members]
                    btn_label = "\n".join(names) if names else "➕ Empty"
                    if shift.locked: btn_label = "🔒 " + btn_label.replace("\n", ", ")
                    
                    # NEW: Diff View Logic
                    is_changed = False
                    tooltip = ""
                    if st.session_state.get('last_stable_state'):
                        prev_names = st.session_state['last_stable_state'].get((day, time_idx), [])
                        if set(prev_names) != set(names):
                            is_changed = True
                            prev_str = ", ".join(prev_names) if prev_names else "(Empty)"
                            tooltip = f"Changed! WAS: {prev_str}"
                            btn_label += " 📝" # Add icon to show change
                    
                    is_selected = (st.session_state['editor_selected_slot'] == (day, time_idx))
                    # If selected: primary. If not selected but changed: secondary (Streamlit doesn't support 'warning' button type)
                    # We rely on the icon and tooltip for diff.
                    btn_type = "primary" if is_selected else "secondary"
                    
                    if row_cols[i+1].button(btn_label, key=f"btn_{day}_{time_idx}", use_container_width=True, type=btn_type, help=tooltip):
                        select_slot(day, time_idx)
                        st.rerun()

        if st.session_state['editor_selected_slot']:
            sel_day, sel_time_idx = st.session_state['editor_selected_slot']
            target_shift = next((s for s in grid if s.day == sel_day and s.time_idx == sel_time_idx), None)
            if target_shift:
                st.divider()
                st.markdown(f"### ✏️ Editing: {sel_day} @ {target_shift.time_label}")
                with st.container(border=True):
                    if target_shift.locked:
                        if st.button("🔓 Unlock Slot", type="primary"):
                            target_shift.locked = False
                            st.rerun()
                    
                    current_p1 = target_shift.assigned_members[0] if len(target_shift.assigned_members) > 0 else None
                    current_p2 = target_shift.assigned_members[1] if len(target_shift.assigned_members) > 1 else None
                    
                    c_sel1, c_sel2 = st.columns(2)
                    with c_sel1:
                        exclude_1 = [current_p1] if current_p1 else []
                        opts1 = get_member_options(sel_day, sel_time_idx, exclude_1)
                        opts1.insert(0, "(Unfilled)")
                        if current_p1: opts1.insert(0, f"👤 {current_p1.name}")
                        sel1 = st.selectbox("Slot 1 Member", opts1, key="p1_ed")
                        
                    with c_sel2:
                        exclude_2 = [current_p2] if current_p2 else []
                        opts2 = get_member_options(sel_day, sel_time_idx, exclude_2)
                        opts2.insert(0, "(Unfilled)")
                        if current_p2: opts2.insert(0, f"👤 {current_p2.name}")
                        sel2 = st.selectbox("Slot 2 Member", opts2, key="p2_ed")
                        
                    st.write("")
                    b_col1, b_col2, b_col3 = st.columns([1, 1, 1])
                    with b_col1:
                        if st.button("Update Slot (No Reroll)", use_container_width=True):
                            new_members = []
                            if sel1 != "(Unfilled)":
                                m1 = find_member_by_str(sel1)
                                if m1: new_members.append(m1)
                            if sel2 != "(Unfilled)":
                                m2 = find_member_by_str(sel2)
                                if m2 and m2 not in new_members: new_members.append(m2)
                            perform_overwrite_assign(target_shift, new_members)
                            target_shift.locked = False
                            st.success("Updated!")
                            st.rerun()
                    with b_col2:
                         # NEW: Lock without Reroll
                        if st.button("🔒 Lock (No Reroll)", use_container_width=True):
                            new_members = []
                            if sel1 != "(Unfilled)":
                                m1 = find_member_by_str(sel1)
                                if m1: new_members.append(m1)
                            if sel2 != "(Unfilled)":
                                m2 = find_member_by_str(sel2)
                                if m2 and m2 not in new_members: new_members.append(m2)
                            
                            perform_overwrite_assign(target_shift, new_members)
                            target_shift.locked = True
                            st.success("Locked!")
                            st.rerun()

                    with b_col3:
                        if st.button("🔒 Lock & Reroll", type="primary", use_container_width=True):
                            new_members = []
                            if sel1 != "(Unfilled)":
                                m1 = find_member_by_str(sel1)
                                if m1: new_members.append(m1)
                            if sel2 != "(Unfilled)":
                                m2 = find_member_by_str(sel2)
                                if m2 and m2 not in new_members: new_members.append(m2)
                            
                            # Capture state BEFORE applying new lock/reroll for diff comparison
                            st.session_state['last_stable_state'] = capture_current_state()

                            with st.spinner("Locking and re-optimizing (Least Changes)..."):
                                perform_overwrite_assign(target_shift, new_members)
                                target_shift.locked = True
                                
                                scheduler = core.Scheduler(
                                    st.session_state['members'], 
                                    active_days=st.session_state['active_days'], 
                                    pre_filled_grid=grid, 
                                    forbidden_pairs=st.session_state['forbidden_pairs'], 
                                    must_schedule=st.session_state['must_schedule'], 
                                    never_schedule=st.session_state['never_schedule'],
                                    previous_state=st.session_state['last_stable_state'] # Pass previous state
                                )
                                scheduler.solve()
                                st.session_state['schedule_grid'] = scheduler.schedule_grid
                                st.session_state['top_schedules'] = scheduler.top_schedules
                                st.success("Locked and Rerolled!")
                                st.rerun()
        else: st.info("Select a slot from the grid above to start editing.")

    # --- TAB 3: PARTNER MATCH ---
    with tab3:
        st.subheader("Partner Matcher & Re-roll")
        all_names = sorted([m.name for m in st.session_state['members'] if m.name not in st.session_state['never_schedule']])
        col_a, col_b = st.columns(2)
        with col_a: name_a = st.selectbox("Person A", all_names, key="match_a")
        with col_b: name_b = st.selectbox("Person B", all_names, key="match_b")
        
        if name_a and name_b and name_a != name_b:
            p1 = find_member_exact(name_a)
            p2 = find_member_exact(name_b)
            best_slots = core.find_best_slots_for_pair(p1, p2, selected_days)
            
            if not best_slots: st.error("No overlapping availability found!")
            else:
                st.success(f"Found {len(best_slots)} common slots")
                for i, slot in enumerate(best_slots[:3]):
                    with st.container():
                        c1, c2, c3 = st.columns([2, 4, 2])
                        with c1: st.markdown(f"**{slot['day']}**"); st.caption(slot['time_label'])
                        with c2: st.info(f"Score: {slot['score']} ({slot['reason']})")
                        with c3:
                            if st.button("Lock & Reroll", key=f"btn_{i}"):
                                # Capture state for diff
                                st.session_state['last_stable_state'] = capture_current_state()
                                
                                with st.spinner("Re-optimizing (Least Changes)..."):
                                    target = next((s for s in grid if s.day == slot['day'] and s.time_idx == slot['time_idx']), None)
                                    perform_overwrite_assign(target, []) 
                                    target.assigned_members = [p1, p2]
                                    target.locked = True
                                    scheduler = core.Scheduler(
                                        st.session_state['members'], 
                                        active_days=selected_days, 
                                        pre_filled_grid=grid, 
                                        forbidden_pairs=st.session_state['forbidden_pairs'], 
                                        must_schedule=st.session_state['must_schedule'], 
                                        never_schedule=st.session_state['never_schedule'],
                                        previous_state=st.session_state['last_stable_state']
                                    )
                                    scheduler.solve()
                                    st.session_state['schedule_grid'] = scheduler.schedule_grid
                                    st.session_state['top_schedules'] = scheduler.top_schedules 
                                    st.rerun()

    # --- TAB 4: CONFLICT ---
    with tab4:
        st.subheader("🚫 Conflict Manager")
        all_names = sorted([m.name for m in st.session_state['members'] if m.name not in st.session_state['never_schedule']])
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1: c_p1 = st.selectbox("Member 1", all_names, key="conf_1")
        with c2: c_p2 = st.selectbox("Member 2", all_names, key="conf_2")
        with c3: 
            st.write("") 
            if st.button("🚫 Lock Conflict & Reroll", type="primary", use_container_width=True):
                if c_p1 == c_p2: st.error("Select two different people.")
                else:
                    pair = tuple(sorted((c_p1, c_p2)))
                    if pair in st.session_state['forbidden_pairs']: st.warning("Exists.")
                    else:
                        st.session_state['forbidden_pairs'].append(pair)
                        # Capture state
                        st.session_state['last_stable_state'] = capture_current_state()
                        
                        with st.spinner(f"Re-optimizing (Least Changes)..."):
                            scheduler = core.Scheduler(
                                st.session_state['members'], 
                                active_days=selected_days, 
                                pre_filled_grid=grid, 
                                forbidden_pairs=st.session_state['forbidden_pairs'], 
                                must_schedule=st.session_state['must_schedule'], 
                                never_schedule=st.session_state['never_schedule'],
                                previous_state=st.session_state['last_stable_state']
                            )
                            scheduler.solve()
                            st.session_state['schedule_grid'] = scheduler.schedule_grid
                            st.session_state['top_schedules'] = scheduler.top_schedules 
                            st.rerun()
        st.divider()
        if st.session_state['forbidden_pairs']:
            for i, pair in enumerate(st.session_state['forbidden_pairs']):
                col_text, col_del = st.columns([5, 1])
                with col_text: st.error(f"🚫 **{pair[0]}** cannot work with **{pair[1]}**")
                with col_del:
                    if st.button("🗑️ Remove", key=f"del_conf_{i}"):
                        st.session_state['forbidden_pairs'].pop(i)
                        st.rerun()

    # --- TAB 5: PARTICIPATION ---
    with tab5:
        st.subheader("🛑 Participation Manager")
        all_names_full = sorted([m.name for m in st.session_state['members']])
        col_must, col_never = st.columns(2)
        with col_must:
            st.markdown("### 🔥 Force Schedule")
            valid_for_must = [n for n in all_names_full if n not in st.session_state['never_schedule']]
            new_must = st.multiselect("Select Members:", valid_for_must, default=[n for n in st.session_state['must_schedule'] if n in valid_for_must], key="widget_must")
            if st.button("💾 Apply 'Force' & Reroll"):
                st.session_state['must_schedule'] = new_must
                st.session_state['last_stable_state'] = capture_current_state()
                with st.spinner("Re-optimizing..."):
                    scheduler = core.Scheduler(st.session_state['members'], active_days=selected_days, pre_filled_grid=grid, forbidden_pairs=st.session_state['forbidden_pairs'], must_schedule=st.session_state['must_schedule'], never_schedule=st.session_state['never_schedule'], previous_state=st.session_state['last_stable_state'])
                    scheduler.solve()
                    st.session_state['schedule_grid'] = scheduler.schedule_grid
                    st.session_state['top_schedules'] = scheduler.top_schedules
                    st.rerun()
        with col_never:
            st.markdown("### ⛔ Exclude")
            valid_for_never = [n for n in all_names_full if n not in st.session_state['must_schedule']]
            new_never = st.multiselect("Select Members:", valid_for_never, default=[n for n in st.session_state['never_schedule'] if n in valid_for_never], key="widget_never")
            if st.button("💾 Apply 'Exclude' & Reroll"):
                st.session_state['never_schedule'] = new_never
                st.session_state['last_stable_state'] = capture_current_state()
                with st.spinner("Re-optimizing..."):
                    scheduler = core.Scheduler(st.session_state['members'], active_days=selected_days, pre_filled_grid=grid, forbidden_pairs=st.session_state['forbidden_pairs'], must_schedule=st.session_state['must_schedule'], never_schedule=st.session_state['never_schedule'], previous_state=st.session_state['last_stable_state'])
                    scheduler.solve()
                    st.session_state['schedule_grid'] = scheduler.schedule_grid
                    st.session_state['top_schedules'] = scheduler.top_schedules
                    st.rerun()

# --- TAB 6: TIME MANAGER (SMART TOGGLES) ---
    with tab6:
        st.subheader("⏳ Time Slot Manager")
        st.markdown("Temporarily override availability for a specific member.")
        
        # 1. Select Member
        all_names = sorted([m.name for m in st.session_state['members']])
        target_name = st.selectbox("Select Member:", all_names, key="tm_member")
        
        target_member = find_member_exact(target_name)
        
        if target_member:
            st.divider()
            
            # Define days for both buttons and grid
            display_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

            # --- QUICK ACTIONS (TOGGLE LOGIC) ---
            st.markdown("### ⚡ Quick Actions")
            c_q1, c_q2, c_q3 = st.columns(3)
            
            with c_q1:
                if st.button("🛡️ Force Opening/Closing Only", help="Toggle: Forces 11:30 & 12:30 slots UNAVAILABLE. Click again to Revert."):
                    # 1. Check if already applied (Are middle slots forced OFF for all days?)
                    is_applied = True
                    for day in display_days:
                        ov = target_member.time_overrides.get(day, {})
                        if ov.get(1) is not False or ov.get(2) is not False:
                            is_applied = False; break
                    
                    # 2. Toggle
                    if is_applied: # REVERT
                        for day in display_days:
                            if day in target_member.time_overrides:
                                target_member.time_overrides[day].pop(1, None)
                                target_member.time_overrides[day].pop(2, None)
                                if not target_member.time_overrides[day]: del target_member.time_overrides[day]
                        st.success("Reverted: Middle slots restored to default.")
                    else: # APPLY
                        for day in display_days:
                            if day not in target_member.time_overrides: target_member.time_overrides[day] = {}
                            target_member.time_overrides[day][1] = False
                            target_member.time_overrides[day][2] = False
                        st.success("Restricted to Opening/Closing slots!")
                    st.rerun()

            with c_q2:
                if st.button("🚫 Force NO Opening/Closing", help="Toggle: Forces 10:30 & 1:30 slots UNAVAILABLE. Click again to Revert."):
                    # 1. Check if already applied (Are edge slots forced OFF for all days?)
                    is_applied = True
                    for day in display_days:
                        ov = target_member.time_overrides.get(day, {})
                        if ov.get(0) is not False or ov.get(3) is not False:
                            is_applied = False; break
                    
                    # 2. Toggle
                    if is_applied: # REVERT
                        for day in display_days:
                            if day in target_member.time_overrides:
                                target_member.time_overrides[day].pop(0, None)
                                target_member.time_overrides[day].pop(3, None)
                                if not target_member.time_overrides[day]: del target_member.time_overrides[day]
                        st.success("Reverted: Opening/Closing slots restored to default.")
                    else: # APPLY
                        for day in display_days:
                            if day not in target_member.time_overrides: target_member.time_overrides[day] = {}
                            target_member.time_overrides[day][0] = False
                            target_member.time_overrides[day][3] = False
                        st.success("Removed Opening/Closing availability!")
                    st.rerun()
            
            with c_q3:
                if st.button("🔄 Reset All Overrides", help="Clear all manual changes for this member."):
                    target_member.time_overrides = {}
                    st.success("All overrides cleared for this member.")
                    st.rerun()
            
            st.divider()

            # --- GRID VIEW (UNCHANGED) ---
            cols_config = [1.2] + [1 for _ in display_days]
            header_cols = st.columns(cols_config)
            header_cols[0].write("**Time**")
            for i, day in enumerate(display_days): 
                header_cols[i+1].write(f"**{day}**")
            
            for time_label, time_idx in core.TIME_SLOTS.items():
                row_cols = st.columns(cols_config)
                row_cols[0].markdown(f"**{time_label}**")
                
                for i, day in enumerate(display_days):
                    is_avail_base = time_idx in target_member.availability.get(day, [])
                    override_status = None
                    if day in target_member.time_overrides and time_idx in target_member.time_overrides[day]:
                        override_status = target_member.time_overrides[day][time_idx]
                    
                    if override_status is True:
                        btn_label = "✅ ON"
                        btn_type = "primary"
                        help_txt = "Override: Forced AVAILABLE."
                    elif override_status is False:
                        btn_label = "⛔ OFF"
                        btn_type = "primary"
                        help_txt = "Override: Forced UNAVAILABLE."
                    else:
                        if is_avail_base:
                            btn_label = "🟢 Free"
                            btn_type = "secondary"
                            help_txt = "CSV Default: Available."
                        else:
                            btn_label = "⚪ Busy"
                            btn_type = "secondary"
                            help_txt = "CSV Default: Busy."
                    
                    b_key = f"tm_{target_name}_{day}_{time_idx}"
                    if row_cols[i+1].button(btn_label, key=b_key, use_container_width=True, type=btn_type, help=help_txt):
                        if day not in target_member.time_overrides: target_member.time_overrides[day] = {}
                        
                        if override_status is None:
                            target_member.time_overrides[day][time_idx] = True 
                        elif override_status is True:
                            target_member.time_overrides[day][time_idx] = False 
                        elif override_status is False:
                            del target_member.time_overrides[day][time_idx]
                            if not target_member.time_overrides[day]:
                                del target_member.time_overrides[day]
                        
                        st.rerun()

            st.divider()
            st.caption("📝 **Legend:** 🟢/⚪ = Default from CSV (Click to override) | ✅ = Forced Available | ⛔ = Forced Unavailable")