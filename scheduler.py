import time
import json
import os
import argparse
from datetime import datetime

CONFIG_PATH = "config.json"
DB_PATH = "db.json"
LOG_PATH = "scheduler.log"

def log_message(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"
    try:
        print(log_line.strip())
    except UnicodeEncodeError:
        safe_line = log_line.replace("₹", "Rs.").strip()
        try:
            print(safe_line)
        except Exception:
            pass
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(log_line)

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            log_message(f"Error loading {path}: {e}")
            return default
    return default

def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log_message(f"Error saving {path}: {e}")

def load_config_env():
    config = load_json(CONFIG_PATH, {})
    if not config or not config.get("sheet_url"):
        # Check environment variables (for GitHub Actions Cloud run)
        try:
            config = {
                "sheet_url": os.environ.get("SHEET_URL", ""),
                "telegram_token": os.environ.get("TELEGRAM_TOKEN", ""),
                "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
                "apps_script_url": os.environ.get("APPS_SCRIPT_URL", ""),
                "auto_sync_interval_mins": int(os.environ.get("AUTO_SYNC_INTERVAL_MINS", 30)),
                "reminder_time": os.environ.get("REMINDER_TIME", "09:00")
            }
        except Exception:
            pass
    return config

# Date formatting helper YYYY-MM-DD -> DD-MM-YYYY
def format_to_dd_mm_yyyy(date_str):
    if not date_str:
        return ""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return date_str

def run_sync_and_reminders(config, db_data):
    sheet_url = config.get("sheet_url", "")
    telegram_token = config.get("telegram_token", "")
    telegram_chat_id = config.get("telegram_chat_id", "")

    if not sheet_url:
        log_message("Google Sheet URL is not configured. Sync skipped.")
        return

    # 1. SYNC FROM GOOGLE SHEET
    log_message("Starting Google Sheet Sync...")
    try:
        from sheets_client import SheetsClient
        sheets_client = SheetsClient(sheet_url)
        records = sheets_client.fetch_records()
        
        bills_dict = db_data.get("bills", {})
        new_bills_dict = {}
        
        for r in records:
            bill_id = r["bill_no"]
            
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
        log_message(f"Successfully synced {len(new_bills_dict)} rows from Google Sheets.")
    except Exception as e:
        log_message(f"Sync failed during execution: {e}")
        log_message("Proceeding with existing database records.")

    # 2. EVALUATE DUE BILLS AND SEND TELEGRAM REMINDERS
    from telegram_client import TelegramClient
    telegram_client = TelegramClient(telegram_token, telegram_chat_id)
    if not telegram_client.is_configured():
        log_message("Telegram Bot is not configured. Reminders aborted.")
        return

    log_message("Scanning database for due/overdue bills...")
    bills_dict = db_data.get("bills", {})
    today = datetime.now().date()
    eligible_reminders = []

    for b_no, b in bills_dict.items():
        if b["status"] == "Unpaid":
            due_date_str = b["due_date"]
            if due_date_str:
                try:
                    due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                    # Filter out invalid due dates (pre-1901)
                    if due_date.year > 1901:
                        days_rem = (due_date - today).days
                        
                        # Reminder trigger: due today or overdue
                        if days_rem <= 0:
                            # 3-Day Spam Control: check if already reminded in the last 3 days
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
                                eligible_reminders.append(b)
                except Exception as ex:
                    log_message(f"Error parsing due date for row {b.get('row_index')}: {ex}")

    if not eligible_reminders:
        log_message("No bills are due/overdue today OR they were already reminded in the last 3 days.")
        return

    log_message(f"Found {len(eligible_reminders)} overdue bills eligible for reminder.")
    success_count = 0
    
    # Send bill-wise notifications
    for bill in eligible_reminders:
        party = bill["party"]
        amt = bill["amount"]
        row_no = bill["row_index"]
        
        inv_date_formatted = format_to_dd_mm_yyyy(bill["date"])
        due_date_formatted = format_to_dd_mm_yyyy(bill["due_date"])
        
        # Calculate days overdue
        days_od = 0
        try:
            due_date = datetime.strptime(bill["due_date"], "%Y-%m-%d").date()
            days_od = (today - due_date).days
            if days_od < 0:
                days_od = 0
        except Exception:
            pass
            
        # Construct message format requested (No row number, DD-MM-YYYY dates)
        bill_number = bill.get("bill_number", "")
        bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
        
        msg = (
            f"🔔 <b>AUTOMATED PAYMENT REMINDER</b>\n"
            f"Customer: <b>{party}</b>\n\n"
            f"{bill_no_text}"
            f"Date of Invoice: <b>{inv_date_formatted}</b>\n"
            f"Amount: <b>₹{amt:,.2f}</b>\n"
            f"Due Date: <b>{due_date_formatted}</b>\n"
            f"Days Overdue: <b>{days_od} days</b>\n\n"
            f"Please arrange for payment. Thank you!"
        )
        
        log_message(f"Sending Telegram reminder for {party} (Amount: ₹{amt:,.2f})...")
        ok, res_msg = telegram_client.send_message(msg)
        
        if ok:
            success_count += 1
            # Update DB entry
            b_id = f"ROW-{row_no}"
            last_rem_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_count = 1
            if b_id in db_data["bills"]:
                db_data["bills"][b_id]["last_reminded"] = last_rem_time
                db_data["bills"][b_id]["reminder_count"] = db_data["bills"][b_id].get("reminder_count", 0) + 1
                new_count = db_data["bills"][b_id]["reminder_count"]
            save_json(DB_PATH, db_data)
            
            # Call Apps Script to write back to Google Sheet
            apps_script_url = config.get("apps_script_url", "")
            if apps_script_url:
                try:
                    requests.get(f"{apps_script_url}?action=logReminder&row={row_no}&last_reminded={last_rem_time}&reminder_count={new_count}", timeout=8)
                except Exception:
                    pass
            # Sleep slightly to prevent hitting Telegram API rate limits (e.g. max 30 msgs per sec)
            time.sleep(0.5)
        else:
            log_message(f"Failed to send Telegram reminder for {party} Row {row_no}: {res_msg}")
            
    log_message(f"Completed background execution. Successfully sent {success_count} separate reminders.")

def main():
    parser = argparse.ArgumentParser(description="Kimaya Sheets Reminders Background Scheduler")
    parser.add_argument("--daemon", action="store_true", help="Run continuously in background daemon mode")
    args = parser.parse_args()

    log_message("Starting Google Sheets Scheduler Service...")

    if args.daemon:
        log_message("Running in Daemon Mode. Press Ctrl+C to stop.")
        while True:
            config = load_config_env()
            db_data = load_json(DB_PATH, {"bills": {}, "last_sync_time": ""})
            sync_interval_mins = int(config.get("auto_sync_interval_mins", 30))
            
            log_message("Performing routine background cycle...")
            run_sync_and_reminders(config, db_data)
            
            log_message(f"Cycle finished. Sleeping for {sync_interval_mins} minutes...")
            time.sleep(sync_interval_mins * 60)
    else:
        config = load_config_env()
        db_data = load_json(DB_PATH, {"bills": {}, "last_sync_time": ""})
        run_sync_and_reminders(config, db_data)
        log_message("Scheduler single run execution completed.")

if __name__ == "__main__":
    main()
