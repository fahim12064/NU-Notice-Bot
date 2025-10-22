import os
import json
import csv
import requests
import time
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin

# --- Configuration ---
CSV_FILE_NAME = "scraped_notices.csv"
USER_IDS_FILE = "user_ids.json"
# অনুগ্রহ করে আপনার আসল টেলিগ্রাম বট টোকেন এখানে দিন
TELEGRAM_BOT_TOKEN = "7976309371:AAE6FFKsxllfEUH7PrJk6tdjIXdSCGCspHk"
BASE_URL = "https://www.nu.ac.bd/"
LAST_UPDATE_ID_FILE = "last_update_id.txt"


# ---------- Utility Functions ----------

def load_user_ids():
    """JSON ফাইল থেকে ব্যবহারকারীর আইডি লোড করে।"""
    if not os.path.exists(USER_IDS_FILE):
        return set()
    try:
        with open(USER_IDS_FILE, "r", encoding="utf-8") as f:
            ids = json.load(f)
            return {str(i) for i in ids}
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_user_ids(user_ids):
    """ব্যবহারকারীর আইডি JSON ফাইলে সেভ করে।"""
    with open(USER_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(user_ids), f, indent=2, ensure_ascii=False)


def get_last_update_id():
    """ফাইল থেকে সর্বশেষ আপডেট আইডি লোড করে।"""
    if not os.path.exists(LAST_UPDATE_ID_FILE):
        return 0
    try:
        with open(LAST_UPDATE_ID_FILE, "r") as f:
            return int(f.read().strip())
    except (ValueError, FileNotFoundError):
        return 0


def save_last_update_id(update_id):
    """ফাইলে সর্বশেষ আপডেট আইডি সেভ করে।"""
    with open(LAST_UPDATE_ID_FILE, "w") as f:
        f.write(str(update_id))


def handle_telegram_updates():
    """টেলিগ্রামের নতুন ব্যবহারকারীদের হ্যান্ডেল করে।"""
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ টেলিগ্রাম বট টোকেন সেট করা নেই।")
        return

    print("\n--- নতুন টেলিগ্রাম ব্যবহারকারী খোঁজা হচ্ছে ---")
    user_ids = load_user_ids()
    last_update_id = get_last_update_id()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=10"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        updates = response.json().get("result", [])
    except Exception as e:
        print(f"❌ টেলিগ্রাম API ত্রুটি: {e}")
        return

    if not updates:
        print("👍 কোনো নতুন টেলিগ্রাম বার্তা নেই।")
        return

    new_users_found = False
    max_update_id = last_update_id
    for update in updates:
        max_update_id = max(max_update_id, update["update_id"])
        msg = update.get("message", {})
        if not msg or "text" not in msg or "chat" not in msg:
            continue

        chat_id = str(msg["chat"]["id"])
        if msg["text"].strip().lower() == "/start" and chat_id not in user_ids:
            user_ids.add(chat_id)
            new_users_found = True
            first_name = msg.get("from", {}).get("first_name", "বন্ধু")
            print(f"✅ নতুন ব্যবহারকারী রেজিস্টার করেছেন: {chat_id} ({first_name})")
            # Welcome message
            welcome_text = (
                f"👋 স্বাগতম, {first_name}!\n\nআপনি এখন থেকে জাতীয় বিশ্ববিদ্যালয়ের নতুন নোটিশের জন্য নোটিফিকেশন পাবেন।")
            try:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                              json={"chat_id": chat_id, "text": welcome_text})
            except Exception as e:
                print(f"❌ স্বাগত বার্তা পাঠাতে ব্যর্থ: {e}")

    if new_users_found:
        save_user_ids(user_ids)
        print(f"💾 মোট {len(user_ids)} জন ব্যবহারকারীকে user_ids.json ফাইলে সেভ করা হয়েছে।")

    save_last_update_id(max_update_id)


def load_scraped_urls_from_csv():
    """CSV ফাইল থেকে শুধুমাত্র পূর্বে সেভ করা নোটিশের URL-গুলো লোড করে।"""
    urls = set()
    if not os.path.exists(CSV_FILE_NAME):
        return urls
    try:
        with open(CSV_FILE_NAME, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # হেডার স্কিপ করুন
            for row in reader:
                if len(row) > 1 and row[1].strip().startswith("http"):
                    urls.add(row[1].strip())
    except Exception as e:
        print(f"❌ CSV ফাইল পড়তে সমস্যা: {e}")
    return urls


def append_notice_to_csv(notice):
    """একটি নতুন নোটিশ CSV ফাইলে যোগ (append) করে।"""
    file_exists = os.path.exists(CSV_FILE_NAME) and os.path.getsize(CSV_FILE_NAME) > 0
    try:
        with open(CSV_FILE_NAME, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["Notice Title", "URL"])  # ফাইল নতুন হলে হেডার যোগ করুন
            writer.writerow([notice["title"], notice["url"]])
    except Exception as e:
        print(f"❌ CSV ফাইলে সেভ করতে সমস্যা: {e}")


def safe_markdown_v2(text):
    """টেলিগ্রামের MarkdownV2 এর জন্য বিশেষ ক্যারেক্টারগুলো এস্কেপ করে।"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{ch}" if ch in escape_chars else ch for ch in text)


def send_telegram_notification(notice):
    """সকল রেজিস্টার্ড ব্যবহারকারীকে একটি নতুন নোটিশ সম্পর্কে নোটিফিকেশন পাঠায়।"""
    user_ids = load_user_ids()
    if not user_ids:
        print("🤷‍♂️ নোটিফিকেশন পাঠানোর জন্য কোনো ব্যবহারকারী নেই।")
        return

    title = safe_markdown_v2(notice['title'])
    message = f"🔔 *নতুন নোটিশ*\n\n{title}\n\n🔗 [নোটিশ দেখুন]({notice['url']})"

    print(f"✉️ {len(user_ids)} জন ব্যবহারকারীকে নোটিফিকেশন পাঠানো হচ্ছে...")
    for chat_id in user_ids:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "MarkdownV2",
                      "disable_web_page_preview": True},
                timeout=10
            )
            if response.status_code != 200:
                print(f"   - {chat_id} আইডিতে পাঠাতে ব্যর্থ: {response.text}")
            time.sleep(0.5)
        except Exception as e:
            print(f"   - {chat_id} আইডিতে পাঠাতে মারাত্মক ত্রুটি: {e}")


def scrape_nu_notices():
    """জাতীয় বিশ্ববিদ্যালয়ের ওয়েবসাইট থেকে প্রথম ৭০টি নোটিশ স্ক্র্যাপ করে।"""
    print("\n--- জাতীয় বিশ্ববিদ্যালয়ের ওয়েবসাইট স্ক্র্যাপ করা হচ্ছে ---")
    scraped_data = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(BASE_URL, timeout=120000)
            page.wait_for_selector("table.customListTable", timeout=60000)
            time.sleep(3)

            rows = page.locator("table.customListTable tbody tr")
            count = min(rows.count(), 80)  # আপনি চাইলে এখানে সংখ্যা বাড়াতে বা কমাতে পারেন
            print(f"ওয়েবসাইটে {rows.count()} টি নোটিশ পাওয়া গেছে, প্রথম {count} টি প্রসেস করা হচ্ছে।")

            for i in range(count):
                row = rows.nth(i)
                title_element = row.locator("td:first-child")
                link_element = title_element.locator("a")

                if link_element.count() > 0:
                    title = title_element.inner_text().strip().replace("\n", " ")
                    href = link_element.get_attribute("href")
                    full_url = urljoin(BASE_URL, href)
                    scraped_data.append({"title": title, "url": full_url})

            browser.close()
        print(f"🎯 ওয়েবসাইট থেকে {len(scraped_data)} টি নোটিশ সফলভাবে স্ক্র্যাপ করা হয়েছে।")
        return scraped_data
    except Exception as e:
        print(f"❌ স্ক্র্যাপিং করার সময় মারাত্মক ত্রুটি: {e}")
        return []


# ---------- Main Logic ----------
if __name__ == "__main__":
    print("--- নোটিশ স্ক্র্যাপার এবং টেলিগ্রাম বট চালু হয়েছে ---")

    # ধাপ ১: নতুন ব্যবহারকারীদের রেজিস্টার করুন (যদি থাকে)
    handle_telegram_updates()

    # ধাপ ২: CSV থেকে আগে সেভ করা নোটিশের URL গুলো লোড করুন
    previously_scraped_urls = load_scraped_urls_from_csv()
    print(f"\n🔎 ডাটাবেজে ({CSV_FILE_NAME}) {len(previously_scraped_urls)} টি নোটিশের রেকর্ড পাওয়া গেছে।")

    # ধাপ ৩: ওয়েবসাইট থেকে সর্বশেষ নোটিশগুলো স্ক্র্যাপ করুন
    all_recent_notices = scrape_nu_notices()

    if not all_recent_notices:
        print("\n❌ ওয়েবসাইট থেকে কোনো নোটিশ স্ক্র্যাপ করা সম্ভব হয়নি। প্রোগ্রাম শেষ হচ্ছে।")
    else:
        # ধাপ ৪: শুধুমাত্র নতুন নোটিশগুলো ফিল্টার করুন
        new_notices = []
        for notice in all_recent_notices:
            if notice['url'] not in previously_scraped_urls:
                new_notices.append(notice)

        if not new_notices:
            print("\n✅ কোনো নতুন নোটিশ পাওয়া যায়নি। সবকিছু আপ-টু-ডেট আছে।")
        else:
            print(f"\n✨ {len(new_notices)} টি নতুন নোটিশ পাওয়া গেছে!")

            # নতুন নোটিশগুলোকে উল্টো করে প্রসেস করা হচ্ছে, যাতে পুরোনোটা আগে যায়
            for notice in reversed(new_notices):
                print(f"\nপ্রসেসিং: {notice['title'][:60]}...")

                # ধাপ ৫: নতুন নোটিশটি CSV ফাইলে যোগ করুন
                append_notice_to_csv(notice)
                print("   - CSV ফাইলে সফলভাবে যোগ করা হয়েছে।")

                # ধাপ ৬: ব্যবহারকারীদের কাছে নোটিফিকেশন পাঠান
                send_telegram_notification(notice)

    print("\n--- মিশন সম্পন্ন ---")
