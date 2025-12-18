import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

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
    feed = feedparser.parse("https://weworkremotely.com/remote-jobs.rss")
    jobs = []
    for e in feed.entries:
        if is_allowed_job(e.title, "", "Remote", e.summary):
            jobs.append({
                "source": "WeWorkRemotely",
                "title": e.title,
                "company": "Unknown",
                "location": "Remote",
                "url": e.link,
            })
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

    jobs = fetch_wwr() + fetch_remoteok()

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
    send_email(f"[Daily Remote Jobs] {len(new_jobs)} - {today}", body)

    for k in unique:
        sent.add(k)
    save_sent(sent)

if __name__ == "__main__":
    main()