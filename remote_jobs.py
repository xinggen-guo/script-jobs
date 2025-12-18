import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from indeed_imap import fetch_indeed_jobs_from_gmail

import requests
import feedparser
from dotenv import load_dotenv

# =====================
# Config
# =====================

load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")  # Gmail App Password
EMAIL_TO = os.getenv("EMAIL_TO", EMAIL_USER)
DEBUG = os.getenv("DEBUG", "0") == "1"

TIMEZONE = os.getenv("TIMEZONE", "Asia/Dubai")
TZ = ZoneInfo(TIMEZONE)

SENT_CACHE_FILE = os.getenv("SENT_CACHE_FILE", "sent_jobs.json")

SEARCH_KEYWORDS = [
    k.strip().lower()
    for k in os.getenv("SEARCH_KEYWORDS", "").split(",")
    if k.strip()
]
if not SEARCH_KEYWORDS:
    SEARCH_KEYWORDS = ["developer", "engineer"]

EXCLUDE_CHINA_KEYWORDS = [
    "china", "beijing", "shanghai", "shenzhen",
    "guangzhou", "prc", "cn", "hong kong"
]

# =====================
# Helpers
# =====================

def text_contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in (text or "").lower() for k in keywords)

def job_matches_keywords(title: str, desc: str) -> bool:
    return text_contains_any(f"{title} {desc}", SEARCH_KEYWORDS)

def is_allowed_job(title, company, location, desc):
    blob = f"{title} {company} {location} {desc}".lower()
    if text_contains_any(blob, EXCLUDE_CHINA_KEYWORDS):
        return False
    return job_matches_keywords(title, desc)

# =====================
# Sent cache
# =====================

def load_sent():
    try:
        with open(SENT_CACHE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_sent(keys: set):
    with open(SENT_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(keys), f, indent=2)

def job_key(job: dict) -> str:
    return job.get("url") or f"{job['source']}::{job['title']}::{job['company']}"

# =====================
# Job sources
# =====================

def fetch_wwr():
    url = "https://weworkremotely.com/remote-jobs.rss"
    if DEBUG:
        print(f"[WWR] Fetching RSS: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if DEBUG:
            print(f"[WWR] HTTP status={resp.status_code}, bytes={len(resp.content)}")
        resp.raise_for_status()
    except Exception as e:
        print(f"[WWR] Request failed: {e}")
        return []

    feed = feedparser.parse(resp.content)

    if DEBUG:
        bozo = getattr(feed, "bozo", 0)
        bozo_exc = getattr(feed, "bozo_exception", None)
        print(f"[WWR] bozo={bozo}")
        if bozo and bozo_exc:
            print(f"[WWR] bozo_exception={bozo_exc}")
        print(f"[WWR] entries={len(getattr(feed, 'entries', []))}")

    jobs = []
    total = 0
    rejected_china = 0
    rejected_keyword = 0

    for idx, e in enumerate(getattr(feed, "entries", []), 1):
        total += 1
        title = getattr(e, "title", "") or ""
        summary = getattr(e, "summary", "") or ""
        link = getattr(e, "link", "") or ""

        blob = f"{title} Remote {summary}".lower()

        if text_contains_any(blob, EXCLUDE_CHINA_KEYWORDS):
            rejected_china += 1
            if DEBUG and idx <= 5:
                print(f"[WWR][REJECT China] {title}")
            continue

        if not job_matches_keywords(title, summary):
            rejected_keyword += 1
            if DEBUG and idx <= 5:
                print(f"[WWR][REJECT Keyword] {title}")
            continue

        jobs.append({
            "source": "WeWorkRemotely",
            "title": title,
            "company": "Unknown",
            "location": "Remote",
            "url": link,
        })

        if DEBUG and idx <= 5:
            print(f"[WWR][ACCEPT] {title}")

    if DEBUG:
        print(f"[WWR] total={total}, accepted={len(jobs)}, "
              f"rejected_china={rejected_china}, rejected_keyword={rejected_keyword}")

    return jobs

def fetch_remoteok():
    jobs = []
    try:
        r = requests.get("https://remoteok.com/api", timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return jobs

    for item in data[1:]:
        title = item.get("position") or item.get("title") or ""
        if is_allowed_job(title, item.get("company",""), item.get("location",""), item.get("description","")):
            jobs.append({
                "source": "RemoteOK",
                "title": title,
                "company": item.get("company","Unknown"),
                "location": item.get("location","Remote"),
                "url": item.get("url",""),
            })
    return jobs

# =====================
# Email
# =====================

def send_email(subject, text):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain", "utf-8"))

    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as s:
        s.starttls()
        s.login(EMAIL_USER, EMAIL_PASS)
        s.send_message(msg)

# =====================
# Main
# =====================

def main():
    sent = load_sent()

    jobs_wwr = fetch_wwr()
    jobs_rok = fetch_remoteok()
    indeed_jobs = []
    try:
        indeed_jobs = fetch_indeed_jobs_from_gmail()
        if DEBUG:
            print(f"[INDEED] jobs={len(indeed_jobs)} (from Gmail alerts)")
    except Exception as e:
        print("[INDEED] error:", e)
    jobs = fetch_wwr() + fetch_remoteok() + indeed_jobs
    if DEBUG:
        print(f"[MAIN] WWR={len(jobs_wwr)} RemoteOK={len(jobs_rok)} Total={len(jobs)}")

    unique = {}
    for j in jobs:
        k = job_key(j)
        if k not in sent:
            unique[k] = j

    new_jobs = list(unique.values())

    if not new_jobs:
        print("No new jobs.")
        return

    lines = ["Search keywords: " + ", ".join(SEARCH_KEYWORDS), ""]
    for i, j in enumerate(new_jobs, 1):
        lines.append(f"{i}. [{j['source']}] {j['title']} - {j['company']}")
        lines.append(j["url"])
        lines.append("")

    body = "\n".join(lines)

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    if DEBUG:
        print(f"[MAIN] Prepared email for {len(new_jobs)} new jobs (sending disabled).")
    send_email(f"[Daily Remote Jobs] {len(new_jobs)} - {today}", body)

    for k in unique:
        sent.add(k)
    save_sent(sent)

if __name__ == "__main__":
    main()