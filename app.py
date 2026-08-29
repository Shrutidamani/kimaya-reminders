import streamlit as st
import json
import os
import pandas as pd
import requests
from datetime import datetime
from sheets_client import SheetsClient
from telegram_client import TelegramClient

# Page configuration
st.set_page_config(page_title="Kimaya Google Sheets Reminders", layout="wide", page_icon="🤖")

# File paths
CONFIG_PATH = "config.json"
DB_PATH = "db.json"

# Load JSON helper functions
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# Date formatting helper YYYY-MM-DD -> DD-MM-YYYY
def format_to_dd_mm_yyyy(date_str):
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return date_str

# Load configurations (support Streamlit Secrets in Cloud, fallback to config.json)
is_cloud = not os.path.exists(CONFIG_PATH)
config = {}
if not is_cloud:
    config = load_json(CONFIG_PATH, {})
else:
    try:
        config = {
            "sheet_url": st.secrets.get("sheet_url", ""),
            "telegram_token": st.secrets.get("telegram_token", ""),
            "telegram_chat_id": st.secrets.get("telegram_chat_id", ""),
            "apps_script_url": st.secrets.get("apps_script_url", ""),
            "auto_sync_interval_mins": int(st.secrets.get("auto_sync_interval_mins", 30)),
            "reminder_time": st.secrets.get("reminder_time", "09:00")
        }
    except Exception:
        pass

if not config:
    config = {
        "sheet_url": "https://docs.google.com/spreadsheets/d/1xH9BhlW1x2iiCm88BrCxi8IGbFyM4QMJ/edit?gid=1463730745#gid=1463730745",
        "telegram_token": "",
        "telegram_chat_id": "",
        "apps_script_url": "",
        "auto_sync_interval_mins": 30,
        "reminder_time": "09:00"
    }

db_data = load_json(DB_PATH, {"bills": {}, "last_sync_time": ""})

# Initialize Clients
sheets_client = SheetsClient(config.get("sheet_url", ""))
telegram_client = TelegramClient(config.get("telegram_token"), config.get("telegram_chat_id"))
apps_script_url = config.get("apps_script_url", "")

# Hide Streamlit menu, header, and footer for clean white-labeling
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stApp [data-testid="stHeader"] {display: none;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Title
st.title("🤖 Kimaya Enterprises - Payment Reminders (Google Sheet)")
st.markdown("Track due dates from your Google Sheet, identify payments (green highlights), and send reminders to Telegram.")

# Sidebar Configuration
st.sidebar.header("⚙️ Configuration Settings")
if is_cloud:
    st.sidebar.warning("🔒 Running in Streamlit Cloud. Settings are managed securely via Streamlit Secrets.")

# Google Sheets URL input
sheet_url = st.sidebar.text_input("Google Sheet URL", value=config.get("sheet_url", ""), disabled=is_cloud)

# Access Instructions
st.sidebar.info("""
💡 **Important Sheet Setting:**
Please make sure your Google Sheet is shared as **"Anyone with the link can view"**. 
1. In Google Sheets, click **Share** (top-right).
2. Under **General access**, select **"Anyone with the link can view"**.
""")

# Telegram Settings
st.sidebar.subheader("Telegram Bot Settings")
telegram_token = st.sidebar.text_input("Bot Token", value=config.get("telegram_token", ""), type="password", disabled=is_cloud, help="Get this from @BotFather on Telegram")
telegram_chat_id = st.sidebar.text_input("Group/Channel/User Chat ID", value=config.get("telegram_chat_id", ""), disabled=is_cloud, help="Target Chat ID for reminders (e.g. -100xxxxxxxxx or 5736935773)")

# Apps Script URL (for highlighting rows green)
st.sidebar.subheader("Mobile App Automation")
new_apps_script_url = st.sidebar.text_input("Google Apps Script URL", value=config.get("apps_script_url", ""), disabled=is_cloud, help="Paste the deployed Google Apps Script URL here")

# Test Telegram Connection Button
if telegram_token and telegram_chat_id and not is_cloud:
    if st.sidebar.button("Test Telegram Bot connection"):
        temp_client = TelegramClient(telegram_token, telegram_chat_id)
        ok, msg = temp_client.test_connection()
        if ok:
            st.sidebar.success("Test message sent! Check your Telegram chat.")
        else:
            st.sidebar.error(f"Failed to send test message: {msg}")

# Save configuration
if not is_cloud:
    if st.sidebar.button("Save Settings"):
        config["sheet_url"] = sheet_url
        config["telegram_token"] = telegram_token
        config["telegram_chat_id"] = telegram_chat_id
        config["apps_script_url"] = new_apps_script_url
        save_json(CONFIG_PATH, config)
        st.sidebar.success("Configuration saved!")
        st.rerun()

# -----------------
# Main Body Layout
# -----------------
tab1, tab2, tab3 = st.tabs(["📋 Bills Dashboard", "📱 Mobile Quick Paid", "⚙️ Sync Logs & Operations"])

# --- TAB 1: Bills Dashboard ---
with tab1:
    bills_dict = db_data.get("bills", {})
    
    # Auto-sync on first page load in this session, or if last sync was > 10 minutes ago
    should_auto_sync = False
    if "last_auto_sync" not in st.session_state:
        should_auto_sync = True
    else:
        elapsed = datetime.now() - st.session_state["last_auto_sync"]
        if elapsed.total_seconds() > 600: # 10 minutes
            should_auto_sync = True
            
    if should_auto_sync and sheet_url:
        st.session_state["last_auto_sync"] = datetime.now()
        try:
            temp_client = SheetsClient(sheet_url)
            records = temp_client.fetch_records()
            new_bills_dict = {}
            for r in records:
                bill_id = r["bill_no"]
                last_reminded = r.get("last_reminded", "")
                reminder_count = r.get("reminder_count", 0)
                if not last_reminded and bill_id in bills_dict:
                    last_reminded = bills_dict[bill_id].get("last_reminded", "")
                    reminder_count = bills_dict[bill_id].get("reminder_count", 0)
                new_bills_dict[bill_id] = {
                    "bill_no": bill_id,
                    "row_index": r["row_index"],
                    "date": r["date"],
                    "party": r["party"],
                    "amount": r["amount"],
                    "due_date": r["due_date"],
                    "status": r["status"],
                    "bill_number": r.get("bill_number", ""),
                    "last_reminded": last_reminded,
                    "reminder_count": reminder_count
                }
            db_data["bills"] = new_bills_dict
            db_data["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_json(DB_PATH, db_data)
            bills_dict = new_bills_dict
        except Exception:
            pass
            
    # Render layout with sync buttons
    col_sync1, col_sync2, col_sync3 = st.columns([1.5, 2, 4])
    
    with col_sync1:
        if st.button("🔄 Sync from Google Sheet", type="primary", use_container_width=True):
            if not sheet_url:
                st.error("Please enter a Google Sheet URL in the sidebar.")
            else:
                with st.spinner("Downloading and parsing Google Sheet..."):
                    try:
                        temp_client = SheetsClient(sheet_url)
                        records = temp_client.fetch_records()
                        
                        # Merge and update local db (retaining reminder logs)
                        new_bills_dict = {}
                        for r in records:
                            bill_id = r["bill_no"] # e.g. "ROW-12"
                            
                            # Prioritize Google Sheet logs, fall back to local cache if empty
                            last_reminded = r.get("last_reminded", "")
                            reminder_count = r.get("reminder_count", 0)
                            if not last_reminded and bill_id in bills_dict:
                                last_reminded = bills_dict[bill_id].get("last_reminded", "")
                                reminder_count = bills_dict[bill_id].get("reminder_count", 0)
                                
                            new_bills_dict[bill_id] = {
                                "bill_no": bill_id,
                                "row_index": r["row_index"],
                                "date": r["date"],
                                "party": r["party"],
                                "amount": r["amount"],
                                "due_date": r["due_date"],
                                "status": r["status"],
                                "bill_number": r.get("bill_number", ""),
                                "last_reminded": last_reminded,
                                "reminder_count": reminder_count
                            }
                            
                        db_data["bills"] = new_bills_dict
                        db_data["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_json(DB_PATH, db_data)
                        st.success(f"Synced {len(new_bills_dict)} rows successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Sync error: {e}")
                        
    # Load data for calculations
    bills_list = list(db_data.get("bills", {}).values())
    table_rows = []
    total_outstanding_amt = 0.0
    overdue_count = 0
    total_unpaid_count = 0
    today = datetime.now().date()
    
    # Calculate rows for table
    for b in bills_list:
        party = b["party"]
        inv_date_str = b["date"]
        due_date_str = b["due_date"]
        
        # Calculate remaining days and overdue days
        days_rem = None
        days_overdue = ""
        display_due_date = due_date_str
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                if due_date.year > 1901:
                    days_rem = (due_date - today).days
                    if due_date <= today:
                        days_overdue = (today - due_date).days
                else:
                    days_rem = None
                    display_due_date = ""
            except Exception:
                pass
        
        # Determine Display Status
        status = b["status"] # "Paid" or "Unpaid"
        if status == "Unpaid":
            total_outstanding_amt += b["amount"]
            total_unpaid_count += 1
            if days_rem is not None and days_rem < 0:
                display_status = "⚠️ Overdue"
                overdue_count += 1
            elif days_rem == 0:
                display_status = "📅 Due Today"
            else:
                display_status = "Pending"
        else:
            display_status = "✅ Paid"
            
        table_rows.append({
            "Row": b["row_index"],
            "Bill No": b.get("bill_number", ""),
            "Invoice Date": inv_date_str,
            "Party Name": party,
            "Bill Amt (₹)": b["amount"],
            "Due Date": display_due_date,
            "Status": display_status,
            "Days Overdue": days_overdue if status == "Unpaid" else "",
            "Last Reminded": b.get("last_reminded", "Never"),
            "Reminders Sent": b.get("reminder_count", 0)
        })

    # One-Shot Reminder Button
    due_overdue_list = [r for r in table_rows if r["Status"] in ["⚠️ Overdue", "📅 Due Today"]]
    
    with col_sync2:
        if st.button("✉️ Send All Overdue Reminders (One-Shot)", type="secondary", use_container_width=True, disabled=len(due_overdue_list) == 0):
            if not telegram_client.is_configured():
                st.error("Telegram bot is not configured. Please fill in credentials in the sidebar.")
            else:
                progress_bar = st.progress(0.0)
                status_text = st.empty()
                success_sent_count = 0
                error_sent_count = 0
                
                # Send separate Telegram message for each bill (bill-wise)
                for idx, r in enumerate(due_overdue_list):
                    party_name = r["Party Name"]
                    inv_date_formatted = format_to_dd_mm_yyyy(r["Invoice Date"])
                    due_date_formatted = format_to_dd_mm_yyyy(r["Due Date"])
                    amount = r["Bill Amt (₹)"]
                    row_no = r["Row"]
                    
                    status_text.text(f"Sending reminder to {party_name} for ₹{amount:,.2f} (Bill {idx+1}/{len(due_overdue_list)})...")
                    
                    days_od = r.get("Days Overdue", 0)
                    if not days_od:
                        days_od = 0
                    bill_number = r.get("Bill No", "")
                    bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
                    today_formatted = datetime.now().strftime("%d-%m-%Y")
                    # Construct bill-wise reminder message (No row number!)
                    msg = (
                        f"🔔 <b>PAYMENT DUE REMINDER</b>\n"
                        f"Customer: <b>{party_name}</b>\n\n"
                        f"{bill_no_text}"
                        f"Date of Invoice: <b>{inv_date_formatted}</b>\n"
                        f"Amount: <b>₹{amount:,.2f}</b>\n"
                        f"Due Date: <b>{due_date_formatted}</b>\n"
                        f"Today's Date: <b>{today_formatted}</b>\n"
                        f"Days Overdue: <b>{days_od} days</b>\n\n"
                        f"Please arrange for payment as soon as possible. Thank you!"
                    )
                    
                    ok, res = telegram_client.send_message(msg)
                    if ok:
                        success_sent_count += 1
                        # Update DB entry
                        row_id = f"ROW-{row_no}"
                        last_rem_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                        new_count = 1
                        if row_id in db_data["bills"]:
                            db_data["bills"][row_id]["last_reminded"] = last_rem_time
                            db_data["bills"][row_id]["reminder_count"] = db_data["bills"][row_id].get("reminder_count", 0) + 1
                            new_count = db_data["bills"][row_id]["reminder_count"]
                            
                        # Call Apps Script to write back to Google Sheet
                        apps_script_url = config.get("apps_script_url", "")
                        if apps_script_url:
                            try:
                                requests.get(f"{apps_script_url}?action=logReminder&row={row_no}&last_reminded={last_rem_time}&reminder_count={new_count}", timeout=8)
                            except Exception:
                                pass
                    else:
                        error_sent_count += 1
                        st.error(f"Failed to send reminder for row {row_no} ({party_name}): {res}")
                        
                    progress_bar.progress((idx + 1) / len(due_overdue_list))
                
                save_json(DB_PATH, db_data)
                status_text.empty()
                progress_bar.empty()
                
                if success_sent_count > 0:
                    st.success(f"Successfully sent {success_sent_count} bill-wise reminders in one-shot!")
                    st.rerun()

    with col_sync3:
        last_sync = db_data.get("last_sync_time", "Never")
        st.markdown(f"**Last synced with Google Sheets:** `{last_sync}`")

    # Render summary metrics
    col_stat1, col_stat2, col_stat3, col_stat4 = st.columns(4)
    col_stat1.metric("Total Outstanding (₹)", f"{total_outstanding_amt:,.2f}")
    col_stat2.metric("Unpaid Rows", total_unpaid_count)
    col_stat3.metric("Overdue Bills", overdue_count)
    col_stat4.metric("Total Synced Rows", len(bills_list))

    if table_rows:
        df = pd.DataFrame(table_rows)
        df = df.sort_values(by="Row")
        
        # Filters
        col_filt1, col_filt2 = st.columns(2)
        with col_filt1:
            filter_status = st.selectbox("Filter by Status", ["Show All", "Unpaid & Overdue Only", "Overdue Only", "Paid Only"])
        with col_filt2:
            unique_parties = ["All Parties"] + sorted(list(df["Party Name"].dropna().unique()))
            filter_party = st.selectbox("Filter by Customer Party", options=unique_parties)
        
        if filter_status == "Unpaid & Overdue Only":
            df = df[df["Status"].isin(["Pending", "⚠️ Overdue", "📅 Due Today"])]
        elif filter_status == "Overdue Only":
            df = df[df["Status"] == "⚠️ Overdue"]
        elif filter_status == "Paid Only":
            df = df[df["Status"] == "✅ Paid"]
            
        if filter_party != "All Parties":
            df = df[df["Party Name"] == filter_party]
            
            # Party actions block
            st.markdown(f"#### ✉️ Send Reminders to **{filter_party}** (Bill-Wise)")
            
            # Filter rows for this specific party
            party_overdue = [r for r in table_rows if r["Party Name"] == filter_party and r["Status"] in ["⚠️ Overdue", "📅 Due Today"]]
            party_unpaid = [r for r in table_rows if r["Party Name"] == filter_party and r["Status"] in ["Pending", "⚠️ Overdue", "📅 Due Today"]]
            
            col_p_btn1, col_p_btn2 = st.columns(2)
            with col_p_btn1:
                if st.button(f"Send Overdue Invoices ({len(party_overdue)} bills)", disabled=len(party_overdue) == 0, key="btn_p_overdue", use_container_width=True):
                    if not telegram_client.is_configured():
                        st.error("Telegram bot is not configured.")
                    else:
                        success = 0
                        for pb in party_overdue:
                            inv_date = format_to_dd_mm_yyyy(pb["Invoice Date"])
                            due_date = format_to_dd_mm_yyyy(pb["Due Date"])
                            days_od = pb.get("Days Overdue", 0) or 0
                            bill_number = pb.get("Bill No", "")
                            bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
                            today_formatted = datetime.now().strftime("%d-%m-%Y")
                            
                            msg = (
                                f"🔔 <b>PAYMENT DUE REMINDER</b>\n"
                                f"Customer: <b>{filter_party}</b>\n\n"
                                f"{bill_no_text}"
                                f"Date of Invoice: <b>{inv_date}</b>\n"
                                f"Amount: <b>₹{pb['Bill Amt (₹)']:,.2f}</b>\n"
                                f"Due Date: <b>{due_date}</b>\n"
                                f"Today's Date: <b>{today_formatted}</b>\n"
                                f"Days Overdue: <b>{days_od} days</b>\n\n"
                                f"Please arrange for payment as soon as possible. Thank you!"
                            )
                            ok, res = telegram_client.send_message(msg)
                            if ok:
                                success += 1
                                r_id = f"ROW-{pb['Row']}"
                                last_rem_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                                new_count = 1
                                if r_id in db_data["bills"]:
                                    db_data["bills"][r_id]["last_reminded"] = last_rem_time
                                    db_data["bills"][r_id]["reminder_count"] = db_data["bills"][r_id].get("reminder_count", 0) + 1
                                    new_count = db_data["bills"][r_id]["reminder_count"]
                                    
                                # Call Apps Script to write back to Google Sheet
                                apps_script_url = config.get("apps_script_url", "")
                                if apps_script_url:
                                    try:
                                        requests.get(f"{apps_script_url}?action=logReminder&row={pb['Row']}&last_reminded={last_rem_time}&reminder_count={new_count}", timeout=8)
                                    except Exception:
                                        pass
                        
                        if success > 0:
                            save_json(DB_PATH, db_data)
                            st.success(f"Sent {success} overdue reminders to {filter_party}!")
                            st.rerun()
            
            with col_p_btn2:
                if st.button(f"Send All Unpaid Invoices ({len(party_unpaid)} bills)", disabled=len(party_unpaid) == 0, key="btn_p_unpaid", use_container_width=True):
                    if not telegram_client.is_configured():
                        st.error("Telegram bot is not configured.")
                    else:
                        success = 0
                        for pb in party_unpaid:
                            inv_date = format_to_dd_mm_yyyy(pb["Invoice Date"])
                            due_date = format_to_dd_mm_yyyy(pb["Due Date"])
                            days_od = pb.get("Days Overdue", 0)
                            if not days_od or pb["Status"] == "Pending":
                                days_od = 0
                            bill_number = pb.get("Bill No", "")
                            bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
                            today_formatted = datetime.now().strftime("%d-%m-%Y")
                                
                            msg = (
                                f"🔔 <b>PAYMENT DUE REMINDER</b>\n"
                                f"Customer: <b>{filter_party}</b>\n\n"
                                f"{bill_no_text}"
                                f"Date of Invoice: <b>{inv_date}</b>\n"
                                f"Amount: <b>₹{pb['Bill Amt (₹)']:,.2f}</b>\n"
                                f"Due Date: <b>{due_date}</b>\n"
                                f"Today's Date: <b>{today_formatted}</b>\n"
                                f"Days Overdue: <b>{days_od} days</b>\n\n"
                                f"Please arrange for payment as soon as possible. Thank you!"
                            )
                            ok, res = telegram_client.send_message(msg)
                            if ok:
                                success += 1
                                r_id = f"ROW-{pb['Row']}"
                                last_rem_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                                new_count = 1
                                if r_id in db_data["bills"]:
                                    db_data["bills"][r_id]["last_reminded"] = last_rem_time
                                    db_data["bills"][r_id]["reminder_count"] = db_data["bills"][r_id].get("reminder_count", 0) + 1
                                    new_count = db_data["bills"][r_id]["reminder_count"]
                                    
                                # Call Apps Script to write back to Google Sheet
                                apps_script_url = config.get("apps_script_url", "")
                                if apps_script_url:
                                    try:
                                        requests.get(f"{apps_script_url}?action=logReminder&row={pb['Row']}&last_reminded={last_rem_time}&reminder_count={new_count}", timeout=8)
                                    except Exception:
                                        pass
                        
                        if success > 0:
                            save_json(DB_PATH, db_data)
                            st.success(f"Sent {success} reminders to {filter_party}!")
                            st.rerun()
            
        st.subheader("Spreadsheet Invoices List")
        # Format columns in display
        display_df = df.copy()
        display_df["Invoice Date"] = display_df["Invoice Date"].apply(format_to_dd_mm_yyyy)
        display_df["Due Date"] = display_df["Due Date"].apply(format_to_dd_mm_yyyy)
        
        st.dataframe(display_df, hide_index=True, use_container_width=True)
        
        # Form to send manual reminders (for individual parties, bill-wise)
        unpaid_parties = df[df["Status"].isin(["Pending", "⚠️ Overdue", "📅 Due Today"])]["Party Name"].unique()
        
        if len(unpaid_parties) > 0:
            with st.form("manual_reminder_form"):
                st.write("✉️ **Send Telegram Payment Reminder (Bill-Wise)**")
                selected_party = st.selectbox("Select Customer Party to Notify", options=sorted(unpaid_parties))
                
                # Filter outstanding bills for the selected party
                party_bills = [r for r in table_rows if r["Party Name"] == selected_party and r["Status"] in ["Pending", "⚠️ Overdue", "📅 Due Today"]]
                
                st.write(f"This will send **{len(party_bills)} separate** bill-wise Telegram reminders for **{selected_party}**.")
                
                submit_reminder = st.form_submit_button("Send Individual Reminders Now")
                
                if submit_reminder:
                    if not telegram_client.is_configured():
                        st.error("Telegram is not configured. Please fill in the Bot Token and Chat ID in the sidebar.")
                    else:
                        success_count = 0
                        for pb in party_bills:
                            inv_date_formatted = format_to_dd_mm_yyyy(pb["Invoice Date"])
                            due_date_formatted = format_to_dd_mm_yyyy(pb["Due Date"])
                            amt = pb["Bill Amt (₹)"]
                            row_no = pb["Row"]
                            
                            days_od = pb.get("Days Overdue", 0)
                            if not days_od:
                                days_od = 0
                            bill_number = pb.get("Bill No", "")
                            bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
                            today_formatted = datetime.now().strftime("%d-%m-%Y")
                            # Construct bill-wise message (No row number!)
                            msg = (
                                f"🔔 <b>PAYMENT DUE REMINDER</b>\n"
                                f"Customer: <b>{selected_party}</b>\n\n"
                                f"{bill_no_text}"
                                f"Date of Invoice: <b>{inv_date_formatted}</b>\n"
                                f"Amount: <b>₹{amt:,.2f}</b>\n"
                                f"Due Date: <b>{due_date_formatted}</b>\n"
                                f"Today's Date: <b>{today_formatted}</b>\n"
                                f"Days Overdue: <b>{days_od} days</b>\n\n"
                                f"Please arrange for payment as soon as possible. Thank you!"
                            )
                            
                            ok, response_msg = telegram_client.send_message(msg)
                            if ok:
                                success_count += 1
                                # Update DB
                                row_id = f"ROW-{row_no}"
                                if row_id in db_data["bills"]:
                                    db_data["bills"][row_id]["last_reminded"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                    db_data["bills"][row_id]["reminder_count"] = db_data["bills"][row_id].get("reminder_count", 0) + 1
                            else:
                                st.error(f"Failed to send reminder for Row {row_no}: {response_msg}")
                                
                        if success_count > 0:
                            save_json(DB_PATH, db_data)
                            st.success(f"Successfully sent {success_count} separate reminders to Telegram for {selected_party}!")
                            st.rerun()
        else:
            st.success("🎉 All synced bills are marked as paid (highlighted in Green in your sheet)!")
    else:
        st.info("No rows loaded in the local database. Click 'Sync from Google Sheet' above to import transactions.")

# --- TAB 2: Mobile Quick Paid Screen ---
with tab2:
    st.subheader("📱 Mobile Quick Paid Panel")
    st.markdown("Use this tab from your phone to select outstanding invoices and instantly **highlight them green** in your Google Sheet.")
    
    # Check if Google Apps Script URL is configured
    if not apps_script_url:
        st.warning("""
        ⚠️ **Setup Required (One-time Google Apps Script Setup):**
        To make this feature work, you need to add a small script inside your Google Sheet:
        1. Open your Google Sheet in a browser.
        2. Go to **Extensions** -> **Apps Script**.
        3. Delete any default code and paste this script:
           ```javascript
           function doGet(e) {
             var row = e.parameter.row;
             var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
             if (row) {
               var rowNum = parseInt(row);
               var range = sheet.getRange(rowNum, 1, 1, 18); // Select row columns A-R
               range.setBackground("#D4EDDA"); // Light green highlight
               return ContentService.createTextOutput("Success");
             }
             return ContentService.createTextOutput("Error: No row specified");
           }
           ```
        4. Click **Save** (disk icon).
        5. Click **Deploy** -> **New deployment**.
           * Click the gear icon and select **Web app**.
           * Set **Execute as**: *Me (your email)*.
           * Set **Who has access**: *Anyone*.
           * Click **Deploy**.
        6. **Copy the Web App URL** it gives you and paste it in the **Google Apps Script URL** field in the sidebar of this app, then click Save.
        """)
    else:
        # Get list of unpaid bills in DB
        unpaid_list = [b for b in bills_dict.values() if b["status"] == "Unpaid"]
        
        # Sort by row
        unpaid_list = sorted(unpaid_list, key=lambda x: x["row_index"])
        
        if not unpaid_list:
            st.success("🎉 All invoices are currently paid!")
        else:
            # Create a clean form for mobile
            st.write("### Mark Payment Received")
            
            # Step 1: Select Party Name (helps filter the list on mobile)
            unique_unpaid_parties = sorted(list(set([b["party"] for b in unpaid_list if b["party"]])))
            selected_mobile_party = st.selectbox("1. Select Customer", options=unique_unpaid_parties, key="mobile_party")
            
            # Filter unpaid bills for that party
            filtered_unpaid_bills = [b for b in unpaid_list if b["party"] == selected_mobile_party]
            
            # Step 2: Select Invoice (showing Date and Amount)
            invoice_options = []
            bill_map = {}
            for ub in filtered_unpaid_bills:
                inv_date_str = format_to_dd_mm_yyyy(ub["date"])
                due_date_str = format_to_dd_mm_yyyy(ub["due_date"])
                label = f"Invoice Date: {inv_date_str} | Amt: ₹{ub['amount']:,.2f} | (Row {ub['row_index']})"
                invoice_options.append(label)
                bill_map[label] = ub
                
            selected_invoice_label = st.selectbox("2. Select Invoice Bill", options=invoice_options, key="mobile_invoice")
            selected_bill = bill_map.get(selected_invoice_label)
            
            if selected_bill:
                st.info(f"Selected Invoice Details:\n\n* **Customer:** {selected_bill['party']}\n* **Row Number:** {selected_bill['row_index']}\n* **Amount:** ₹{selected_bill['amount']:,.2f}\n* **Due Date:** {format_to_dd_mm_yyyy(selected_bill['due_date'])}")
                
                # Button to mark paid
                if st.button("✅ Mark as Paid & Highlight Green", type="primary", use_container_width=True):
                    row_no = selected_bill["row_index"]
                    with st.spinner("Updating Google Sheets..."):
                        try:
                            # Send request to Apps Script Web App
                            script_response = requests.get(f"{apps_script_url}?row={row_no}", timeout=15)
                            response_text_lower = script_response.text.lower()
                            if script_response.status_code == 200 and ("success" in response_text_lower or "ok" in response_text_lower):
                                st.success("Success! Highlighted row green in Google Sheets.")
                                
                                # Instantly mark as paid in our local DB as well
                                row_id = f"ROW-{row_no}"
                                if row_id in db_data["bills"]:
                                    db_data["bills"][row_id]["status"] = "Paid"
                                save_json(DB_PATH, db_data)
                                
                                # Brief sleep and refresh
                                time_sleep = st.empty()
                                st.success("Database updated! Reloading dashboard...")
                                st.rerun()
                            else:
                                st.error(f"Apps Script Error: {script_response.text}")
                        except Exception as ex:
                            st.error(f"Failed to connect to Google Apps Script: {ex}")

# --- TAB 3: Operations & Background Scheduler ---
with tab3:
    st.subheader("⚙️ Background Automation Details")
    st.markdown("""
    ### Run the Daily Reminder Service:
    To automate the process and run this check silently every morning without keeping this browser tab open, configure the VBScript file:
    
    * **Automation target:** [`run_daemon_silent.vbs`](file:///E:/OFFICE%20DATA/IMP/SOFTWARES/KIMAYA%20REMINDERS/run_daemon_silent.vbs)
    * **How it works:** Putting this shortcut inside the Windows Startup folder runs the daemon silently.
    
    ### Automated Reminder Logic (Spam Protection & Bill-Wise):
    1. **Bill-Wise Sending**: Each due or overdue transaction is sent as an **individual Telegram message** directly showing the Invoice Date and Due Date.
    2. **3-Day Interval**: To prevent spamming your clients daily, the background scheduler will **only send a reminder once every 3 days** for any pending overdue invoice. If a reminder was sent yesterday, it will skip it today and check again tomorrow.
    """)

    # Manual background daemon test run
    st.markdown("### Execute Test Run of Scheduler")
    st.write("Click below to run a dry run of the automated background script immediately (respecting the 3-day spam limit).")
    
    if st.button("Execute Dry Run Now"):
        st.write("Scanning sheet database for outstanding due items...")
        
        due_overdue_bills = []
        
        for b_no, b in db_data.get("bills", {}).items():
            if b["status"] == "Unpaid":
                due_date_str = b["due_date"]
                if due_date_str:
                    try:
                        due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                        if due_date.year > 1901:
                            days_rem = (due_date - today).days
                            if days_rem <= 0:
                                # Spam control: check if already reminded in last 3 days
                                last_rem_str = b.get("last_reminded", "")
                                already_reminded_recently = False
                                if last_rem_str:
                                    try:
                                        last_rem_date = datetime.strptime(last_rem_str.split()[0], "%Y-%m-%d").date()
                                        days_since = (today - last_rem_date).days
                                        if days_since < 3:
                                            already_reminded_recently = True
                                    except Exception:
                                        pass
                                
                                if not already_reminded_recently:
                                    due_overdue_bills.append((b, due_date_str, days_rem))
                    except Exception:
                        pass
                        
        if not due_overdue_bills:
            st.info("No un-highlighted items are due/overdue today OR they were already reminded in the last 3 days.")
        else:
            st.write(f"Found {len(due_overdue_bills)} bills requiring attention. Sending messages...")
            
            success_count = 0
            for bill, due_str, days_left in due_overdue_bills:
                party = bill["party"]
                amt = bill["amount"]
                inv_date_formatted = format_to_dd_mm_yyyy(bill["date"])
                due_date_formatted = format_to_dd_mm_yyyy(due_str)
                row_no = bill["row_index"]
                
                days_od = -days_left if days_left is not None else 0
                # Construct bill-wise message (No row number!)
                msg = (
                    f"🔔 <b>AUTOMATED PAYMENT REMINDER</b>\n"
                    f"Customer: <b>{party}</b>\n\n"
                    f"Date of Invoice: <b>{inv_date_formatted}</b>\n"
                    f"Amount: <b>₹{amt:,.2f}</b>\n"
                    f"Due Date: <b>{due_date_formatted}</b>\n"
                    f"Days Overdue: <b>{days_od} days</b>\n\n"
                    f"Please arrange for payment. Thank you!"
                )
                
                if telegram_client.is_configured():
                    ok, r_msg = telegram_client.send_message(msg)
                    if ok:
                        success_count += 1
                        # Update db
                        row_id = f"ROW-{row_no}"
                        db_data["bills"][row_id]["last_reminded"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                        db_data["bills"][row_id]["reminder_count"] = db_data["bills"][row_id].get("reminder_count", 0) + 1
                    else:
                        st.error(f"Failed to send to {party} for Row {row_no}: {r_msg}")
                else:
                    st.warning(f"Telegram not configured. Simulation only for Row {row_no} ({party}):\n{msg}")
            
            if success_count > 0:
                save_json(DB_PATH, db_data)
                st.success(f"Successfully sent {success_count} separate reminders to Telegram!")
                st.rerun()
