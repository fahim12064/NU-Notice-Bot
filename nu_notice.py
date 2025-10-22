import os
import re
import json
import csv
import requests
import time
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin

# --- Configuration ---
CSV_FILE_NAME = "scraped_notices.csv"
USER_IDS_FILE = "user_ids.json"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BASE_URL = "https://www.nu.ac.bd/"


# ---------- Utility Functions ----------

def load_user_ids():
    """Load user IDs from JSON file"""
    if not os.path.exists(USER_IDS_FILE):
        return set()
    try:
        with open(USER_IDS_FILE, "r") as f:
            content = f.read()
            if not content:
                return set()
            return set(json.loads(content))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_user_ids(user_ids):
    """Save user IDs to JSON file"""
    with open(USER_IDS_FILE, "w") as f:
        json.dump(list(user_ids), f, indent=2)


def handle_telegram_updates():
    """Handle new Telegram users"""
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ Telegram bot token not set")
        return

    user_ids = load_user_ids()
    last_update_file = "last_update_id.txt"

    # Read last update ID
    if os.path.exists(last_update_file):
        try:
            with open(last_update_file, "r") as f:
                last_update_id = int(f.read().strip() or 0)
        except ValueError:
            last_update_id = 0
    else:
        last_update_id = 0

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=10"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        updates = response.json().get("result", [])
    except Exception as e:
        print(f"❌ Telegram API error: {e}")
        return

    if not updates:
        print("👍 No new Telegram messages")
        return

    new_users_found = False
    max_update_id = last_update_id

    for update in updates:
        max_update_id = max(max_update_id, update["update_id"])
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        first_name = msg.get("from", {}).get("first_name", "Friend")

        if not chat_id or not text:
            continue

        if text.strip().lower() == "/start":
            if chat_id not in user_ids:
                user_ids.add(chat_id)
                new_users_found = True
                print(f"✅ New user registered: {chat_id} ({first_name})")

                # Send welcome message
                welcome_text = (
                    f"👋 Welcome, {first_name}!\n\n"
                    "You are now subscribed to receive notifications "
                    "for *new notices* from National University 📢✨\n\n"
                    "You will receive notifications when new notices are published."
                )

                try:
                    send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    payload = {"chat_id": chat_id, "text": welcome_text, "parse_mode": "Markdown"}
                    requests.post(send_url, json=payload, timeout=10)
                except Exception as e:
                    print(f"❌ Failed to send welcome message to {chat_id}: {e}")

    # Save new users
    if new_users_found:
        save_user_ids(user_ids)
        print(f"💾 Saved {len(user_ids)} total users to user_ids.json")

    # Save last update ID
    with open(last_update_file, "w") as f:
        f.write(str(max_update_id))

    print("✅ Telegram updates handled successfully")


def load_scraped_links_from_csv():
    """Load scraped links from CSV file"""
    if not os.path.exists(CSV_FILE_NAME):
        return set()
    with open(CSV_FILE_NAME, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # Skip header
        except StopIteration:
            return set()
        return {row[1] for row in reader if len(row) > 1}


def append_to_csv(notice_title, url):
    """Append new notice to CSV file"""
    file_exists = os.path.exists(CSV_FILE_NAME)
    with open(CSV_FILE_NAME, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Notice Title", "URL"])
        writer.writerow([notice_title, url])


def safe_markdown(text):
    """Escape special characters for Markdown"""
    return re.sub(r'([_*[\]()~`>#+=|{}.!-])', r'\\\1', text)


def send_telegram_notification(notice_title, notice_url):
    """Send notification to all registered users"""
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ Telegram token not configured. Skipping notification")
        return

    user_ids = load_user_ids()
    if not user_ids:
        print("🤷 No users registered to notify")
        return

    # Create message
    message = (
        f"🔔 *NU published new notice named* {safe_markdown(notice_title)}\n\n"
        f"📄 *Please check out the link then link provide korbe.*\n"
        f"🔗 [View Notice]({notice_url})"
    )

    print(f"✉️ Sending notification to {len(user_ids)} users...")
    success = 0
    fail = 0

    for chat_id in user_ids:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            }
            response = requests.post(url, data=data, timeout=20)
            response.raise_for_status()
            success += 1
            time.sleep(1)  # Rate limiting
        except Exception as e:
            fail += 1
            print(f"❌ Failed to send to {chat_id}: {e}")

    print(f"    ✅ Sent to {success} users, ❌ Failed for {fail}")


# ---------- Scraper Functions ----------

def scrape_nu_notices():
    """Scrape notices from National University website"""
    print("\n--- Step 1: Scraping NU Notices ---")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(BASE_URL, timeout=600000)

        # Wait for table to appear
        page.wait_for_selector("table.customListTable")
        time.sleep(2)

        # Locate all rows
        rows = page.locator("table.customListTable tbody tr")
        total = rows.count()
        limit = min(total, 70)  # Take first 70 notices

        all_data = []

        for i in range(limit):
            row = rows.nth(i)
            tds = row.locator("td").all_inner_texts()
            if tds:
                notice_text = tds[0].strip().replace("\n", " ")
                publish_date = tds[1].strip() if len(tds) > 1 else ""

                # Extract link from the first td
                link_element = row.locator("td:first-child a")
                href = link_element.get_attribute("href") if link_element.count() > 0 else ""

                # Check if it's a new notice (has new-news.gif image)
                has_new_image = row.locator("img[src*='new-news.gif']").count() > 0

                if href and notice_text and has_new_image:
                    # Convert relative URL to absolute URL
                    full_url = urljoin(BASE_URL, href)

                    all_data.append({
                        "title": notice_text,
                        "url": full_url,
                        "date": publish_date
                    })
                    print(f"📰 Found new notice: {notice_text[:50]}...")

        browser.close()

    print(f"🎯 Found {len(all_data)} new notices with new-news.gif")
    return all_data


# ---------- Main Function ----------
if __name__ == "__main__":
    print("--- Starting NU Notice Scraper and Telegram Bot ---")

    # Step 1: Check for new Telegram users
    print("\n--- Checking for New Telegram Users ---")
    handle_telegram_updates()

    # Step 2: Start scraping
    all_new_notices = scrape_nu_notices()

    if not all_new_notices:
        print("\n📭 No new notices found")
    else:
        scraped_links = load_scraped_links_from_csv()
        print(f"🔎 Already scraped: {len(scraped_links)} notices")

        # Filter new notices
        new_notices_to_send = [
            notice for notice in all_new_notices
            if notice["url"] not in scraped_links
        ]

        if not new_notices_to_send:
            print("\n✅ No new notices to send")
        else:
            print(f"\n--- Sending {len(new_notices_to_send)} New Notices ---")
            for i, notice in enumerate(new_notices_to_send):
                print(f"\n[{i + 1}/{len(new_notices_to_send)}] {notice['title'][:50]}...")

                # Save to CSV
                append_to_csv(notice["title"], notice["url"])
                print(f"  💾 Saved to CSV")

                # Send Telegram notification
                send_telegram_notification(notice["title"], notice["url"])
                print(f"  📱 Notification sent")

    print("\n--- Mission Completed ---")