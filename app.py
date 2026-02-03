import streamlit as st
import scheduler_core as core  # Imports the logic file

st.set_page_config(page_title="HKSA Scheduler", page_icon="📅")

st.title("📅 HKSA Tabling Scheduler")
st.markdown("""
**Instructions:**
1. Download your Google Form responses as `.xlsx` or `.csv`.
2. Upload the file below.
3. Click 'Generate' to create the schedule.
""")

uploaded_file = st.file_uploader("Upload Availability File", type=["csv", "xlsx"])

if uploaded_file is not None:
    st.info("Parsing file...")
    # Use the function from the core file
    members = core.parse_file(uploaded_file)
    
    if not members:
        st.error("Could not find any members. Please check your column names.")
    else:
        st.success(f"Loaded {len(members)} members.")
        
        if st.button("Generate Schedule"):
            with st.spinner("Calculating optimal schedule..."):
                # Use the class from the core file
                scheduler = core.Scheduler(members)
                success = scheduler.solve()
                
                if success:
                    st.balloons()
                    st.success("✅ Perfect schedule found!")
                else:
                    st.warning("⚠️ Could not find a perfect fit. Generating best partial schedule.")
                
                # Generate Excel
                excel_data = core.generate_excel_bytes(scheduler.schedule_grid)
                
                st.download_button(
                    label="📥 Download Schedule (Excel)",
                    data=excel_data,
                    file_name="HKSA_Tabling_Schedule.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )