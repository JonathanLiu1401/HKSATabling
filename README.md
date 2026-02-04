# **HKSA Tabling Scheduler Pro**

This application automates the scheduling of tabling shifts for the Hong Kong Student Association (HKSA), designed to handle complex constraints, fairness rules, and interactive adjustments.

Visit the app at: https://hksatabling-utjuta9cmx64qjjpfh7rpk.streamlit.app/

## **Core Features**

* **Automated Scheduling:** Uses a backtracking algorithm to generate a schedule that ensures 2 people per shift while respecting individual availability.  
* **Constraint Enforcement:**  
  * **Heavy Lifting:** Guarantees at least one Male member is assigned to Opening (10:30 AM) and Closing (1:30 PM) shifts.  
  * **Fairness:** Strictly limits members to **1 shift per week**.  
  * **Preferences:** Respects "No Opening" and "No Closing" requests.  
* **Live Editor:** An interactive interface to manually swap members, fill gaps, or make adjustments with real-time validation warnings (e.g., "Member is already working Tuesday").  
* **Partner Matcher:** Seamlessly pairs two members together by finding their best overlapping time slot and re-optimizing the rest of the schedule around them.  
* **Unassigned Tracking:** automatically identifies members who could not be placed and lists their availability to help admins find backups.

## **How to Use**

### **1\. Prepare Data (Google Forms)**

1. Use the standard HKSA Tabling Availability Google Form.  
2. Ensure your form collects:  
   * Name (First and Last)  
   * Gender (Male/Female)  
   * Availability for Mon-Fri (e.g., "10:30-11:30, 12:30-1:30")  
   * Preferences (OK with Opening/Closing?)  
   * Preferred Days (Optional)  
3. Go to the **Responses** tab in your Google Sheet.  
4. Click **File \> Download \> Comma Separated Values (.csv)**.

### **2\. Run the Scheduler**

1. Open the application (via Streamlit link or local execution).  
2. **Upload** your downloaded CSV file in the sidebar.  
3. Select the **Active Days** for the week (e.g., uncheck "Monday" if it's a holiday).  
4. Click **🚀 Auto-Generate Schedule**.

### **3\. Refine & Export**

* **View Tab:** See the generated grid and a list of unassigned members.  
* **Live Editor:** Click to manually assign specific people to specific slots. The system will auto-lock these choices.  
* **Partner Matcher:** Select two names to find a time they can work together. Click "Lock & Reroll" to finalize their pair and re-shuffle the rest of the team to fit.  
* **Download:** Click **📥 Download Excel** to get the final schedule (including a sheet for Unassigned Members).

## **Installation (Local)**

1. Install Python 3.8+.  
2. Install dependencies:  
   pip install streamlit pandas xlsxwriter openpyxl

3. Run the app:  
   python \-m streamlit run app.py  
