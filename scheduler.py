import time
import json
import os
import argparse
import requests
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

def format_party_reminder_message(party_name, bills, title="AUTOMATED PAYMENT REMINDER"):
    today_formatted = datetime.now().strftime("%d-%m-%Y")
    today = datetime.now().date()
    
    if len(bills) == 1:
        b = bills[0]
        inv_date = format_to_dd_mm_yyyy(b.get("date") or b.get("Invoice Date", ""))
        due_date = format_to_dd_mm_yyyy(b.get("due_date") or b.get("Due Date", ""))
        amt = float(b.get("amount") or b.get("Bill Amt (₹)", 0))
        
        days_od = b.get("Days Overdue")
        if days_od is None or days_od == "":
            try:
                d_str = b.get("due_date") or b.get("Due Date", "")
                due_d = datetime.strptime(d_str, "%Y-%m-%d").date()
                days_od = max(0, (today - due_d).days)
            except Exception:
                days_od = 0
                
        bill_number = b.get("bill_number") or b.get("Bill No", "")
        bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
        
        msg = (
            f"🔔 <b>{title}</b>\n"
            f"Customer: <b>{party_name}</b>\n\n"
            f"{bill_no_text}"
            f"Date of Invoice: <b>{inv_date}</b>\n"
            f"Amount: <b>₹{amt:,.2f}</b>\n"
            f"Due Date: <b>{due_date}</b>\n"
            f"Today's Date: <b>{today_formatted}</b>\n"
            f"Days Overdue: <b>{days_od} days</b>\n\n"
            f"Please arrange for payment. Thank you!"
        )
        return msg
    else:
        total_amount = 0.0
        bills_blocks = []
        for idx, b in enumerate(bills, 1):
            inv_date = format_to_dd_mm_yyyy(b.get("date") or b.get("Invoice Date", ""))
            due_date = format_to_dd_mm_yyyy(b.get("due_date") or b.get("Due Date", ""))
            amt = float(b.get("amount") or b.get("Bill Amt (₹)", 0))
            total_amount += amt
            
            days_od = b.get("Days Overdue")
            if days_od is None or days_od == "":
                try:
                    d_str = b.get("due_date") or b.get("Due Date", "")
                    due_d = datetime.strptime(d_str, "%Y-%m-%d").date()
                    days_od = max(0, (today - due_d).days)
                except Exception:
                    days_od = 0
                    
            bill_number = b.get("bill_number") or b.get("Bill No", "")
            bill_no_text = f"Bill No: <b>{bill_number}</b>\n" if bill_number else ""
            
            block = (
                f"{idx}. {bill_no_text}"
                f"Date of Invoice: <b>{inv_date}</b>\n"
                f"Amount: <b>₹{amt:,.2f}</b>\n"
                f"Due Date: <b>{due_date}</b>\n"
                f"Today's Date: <b>{today_formatted}</b>\n"
                f"Days Overdue: <b>{days_od} days</b>"
            )
            bills_blocks.append(block)
            
        bills_text = "\n\n".join(bills_blocks)
        
        msg = (
            f"🔔 <b>{title}</b>\n"
            f"Customer: <b>{party_name}</b>\n\n"
            f"<b><u>Overdue Invoices ({len(bills)} Bills):</u></b>\n\n"
            f"{bills_text}\n\n"
            f"<b>Total Overdue Amount: ₹{total_amount:,.2f}</b>\n\n"
            f"Please arrange for payment as soon as possible. Thank you!"
        )
        return msg

HISTORY_PATH = "reminders_history.json"

def get_most_recent_reminded_date(bill_id, party_name, bill_obj, history_data):
    """Safely extract the latest reminder date across all local and remote sources."""
    dates = []
    
    # 1. From history log
    dispatched = history_data.get("dispatched", {})
    if bill_id in dispatched:
        try:
            dates.append(datetime.strptime(dispatched[bill_id].split()[0], "%Y-%m-%d").date())
        except Exception:
            pass
            
    party_key = f"PARTY_{party_name.strip().lower()}"
    if party_key in dispatched:
        try:
            dates.append(datetime.strptime(dispatched[party_key].split()[0], "%Y-%m-%d").date())
        except Exception:
            pass
            
    # 2. From bill object (Google Sheet or local db cache)
    b_rem = bill_obj.get("last_reminded", "")
    if b_rem:
        try:
            dates.append(datetime.strptime(b_rem.split()[0], "%Y-%m-%d").date())
        except Exception:
            pass
            
    if not dates:
        return None
    return max(dates)

def run_sync_and_reminders(config, db_data, history_data=None, allow_dispatch=True):
    if history_data is None:
        history_data = load_json(HISTORY_PATH, {"last_daily_dispatch_date": "", "dispatched": {}})
        
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
            
            # Prefer latest timestamp between Google Sheet, local db cache, and history log
            sheet_last_rem = r.get("last_reminded", "")
            sheet_count = r.get("reminder_count", 0)
            local_last_rem = bills_dict.get(bill_id, {}).get("last_reminded", "") if bill_id in bills_dict else ""
            local_count = bills_dict.get(bill_id, {}).get("reminder_count", 0) if bill_id in bills_dict else 0
            hist_last_rem = history_data.get("dispatched", {}).get(bill_id, "")
            
            # Pick latest timestamp string
            all_rems = [s for s in (sheet_last_rem, local_last_rem, hist_last_rem) if s]
            last_reminded = max(all_rems) if all_rems else ""
            reminder_count = max(sheet_count, local_count)
                
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

    # Check once-per-day dispatch guard
    today = datetime.now().date()
    today_str = str(today)
    
    if not allow_dispatch:
        log_message(f"Routine sync complete. Automated reminders already handled for today ({today_str}). Dispatch skipped.")
        return

    # 2. EVALUATE DUE BILLS AND SEND TELEGRAM REMINDERS
    from telegram_client import TelegramClient
    telegram_client = TelegramClient(telegram_token, telegram_chat_id)
    if not telegram_client.is_configured():
        log_message("Telegram Bot is not configured. Reminders aborted.")
        return

    log_message("Scanning database for due/overdue bills...")
    bills_dict = db_data.get("bills", {})
    
    # Group eligible overdue bills by Party
    party_overdue_map = {} # party -> list of bills

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
                            # 3-Day Spam Control across all layers
                            already_reminded_recently = False
                            last_rem_date = get_most_recent_reminded_date(b_no, b["party"], b, history_data)
                            
                            if last_rem_date:
                                days_since = (today - last_rem_date).days
                                if days_since < 3:
                                    already_reminded_recently = True
                            
                            if not already_reminded_recently:
                                party_name = b["party"]
                                if party_name not in party_overdue_map:
                                    party_overdue_map[party_name] = []
                                party_overdue_map[party_name].append(b)
                except Exception as ex:
                    log_message(f"Error parsing due date for row {b.get('row_index')}: {ex}")

    if not party_overdue_map:
        log_message("No bills are due/overdue today OR they were already reminded in the last 3 days.")
        # Mark today as checked
        history_data["last_daily_dispatch_date"] = today_str
        save_json(HISTORY_PATH, history_data)
        return

    total_eligible_bills = sum(len(bills) for bills in party_overdue_map.values())
    log_message(f"Found {total_eligible_bills} overdue bills across {len(party_overdue_map)} parties eligible for reminder.")
    success_party_count = 0
    success_bill_count = 0
    apps_script_url = config.get("apps_script_url", "")
    
    # Send party-wise consolidated notifications
    for party, bills in party_overdue_map.items():
        msg = format_party_reminder_message(party, bills, title="AUTOMATED PAYMENT REMINDER")
        total_party_amt = sum(float(b.get("amount", 0)) for b in bills)
        
        log_message(f"Sending Telegram reminder for {party} ({len(bills)} overdue bills, Total: ₹{total_party_amt:,.2f})...")
        ok, res_msg = telegram_client.send_message(msg)
        
        if ok:
            success_party_count += 1
            last_rem_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            
            # Immediately record in local history lock table
            if "dispatched" not in history_data:
                history_data["dispatched"] = {}
            history_data["dispatched"][f"PARTY_{party.strip().lower()}"] = last_rem_time
            
            for bill in bills:
                success_bill_count += 1
                row_no = bill["row_index"]
                b_id = f"ROW-{row_no}"
                history_data["dispatched"][b_id] = last_rem_time
                
                new_count = 1
                if b_id in db_data["bills"]:
                    db_data["bills"][b_id]["last_reminded"] = last_rem_time
                    db_data["bills"][b_id]["reminder_count"] = db_data["bills"][b_id].get("reminder_count", 0) + 1
                    new_count = db_data["bills"][b_id]["reminder_count"]
                
                # Call Apps Script to write back to Google Sheet with retry
                if apps_script_url:
                    for attempt in range(3):
                        try:
                            resp = requests.get(f"{apps_script_url}?action=logReminder&row={row_no}&last_reminded={last_rem_time}&reminder_count={new_count}", timeout=10)
                            if resp.status_code == 200:
                                log_message(f"Logged reminder to Google Sheet Row {row_no}")
                                break
                        except Exception as e_script:
                            if attempt == 2:
                                log_message(f"Failed to log reminder to Google Sheet Row {row_no} after 3 attempts: {e_script}")
                            time.sleep(1)
            
            # Mark today's dispatch locked
            history_data["last_daily_dispatch_date"] = today_str
            save_json(HISTORY_PATH, history_data)
            save_json(DB_PATH, db_data)
            
            # Sleep slightly to prevent hitting Telegram API rate limits
            time.sleep(0.5)
        else:
            log_message(f"Failed to send Telegram reminder for {party}: {res_msg}")
            
    log_message(f"Completed background execution. Successfully sent {success_party_count} party-wise reminders covering {success_bill_count} bills.")

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
            history_data = load_json(HISTORY_PATH, {"last_daily_dispatch_date": "", "dispatched": {}})
            sync_interval_mins = int(config.get("auto_sync_interval_mins", 30))
            
            today_str = datetime.now().strftime("%Y-%m-%d")
            # Only trigger reminder dispatch once per calendar day
            allow_dispatch = (history_data.get("last_daily_dispatch_date") != today_str)
            
            log_message(f"Performing routine background cycle (Allow Reminder Dispatch: {allow_dispatch})...")
            run_sync_and_reminders(config, db_data, history_data, allow_dispatch=allow_dispatch)
            
            log_message(f"Cycle finished. Sleeping for {sync_interval_mins} minutes...")
            time.sleep(sync_interval_mins * 60)
    else:
        config = load_config_env()
        db_data = load_json(DB_PATH, {"bills": {}, "last_sync_time": ""})
        history_data = load_json(HISTORY_PATH, {"last_daily_dispatch_date": "", "dispatched": {}})
        run_sync_and_reminders(config, db_data, history_data, allow_dispatch=True)
        log_message("Scheduler single run execution completed.")

if __name__ == "__main__":
    main()
