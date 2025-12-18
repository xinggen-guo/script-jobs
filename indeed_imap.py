import os
import re
import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("GMAIL_IMAP_HOST", "imap.gmail.com")
PORT = int(os.getenv("GMAIL_IMAP_PORT", "993"))
USER = os.getenv("INDEED_USER")
PASS = os.getenv("INDEED_PASS")

INDEED_FROM = os.getenv("INDEED_FROM", "indeed").strip()
INDEED_SUBJECT = os.getenv("INDEED_SUBJECT", "Job Alert").strip()
INDEED_MAX_EMAILS = int(os.getenv("INDEED_MAX_EMAILS", "5"))


def _decode_mime(s: str) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    out = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            out += text.decode(enc or "utf-8", errors="replace")
        else:
            out += text
    return out


def _get_html_body(msg: email.message.Message) -> Optional[str]:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp:
                continue
            if ctype == "text/html":
                payload = part.get_payload(decode=True) or b""
                return payload.decode("utf-8", errors="replace")
        return None
    else:
        if msg.get_content_type() == "text/html":
            payload = msg.get_payload(decode=True) or b""
            return payload.decode("utf-8", errors="replace")
        return None


def _looks_like_job_link(url: str) -> bool:
    u = (url or "").lower()
    if not u:
        return False
    # Indeed email links often route through tracking/click domains, so we allow "indeed" broadly.
    return "indeed" in u


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def extract_jobs_from_indeed_email_html(html: str) -> List[Dict]:
    """
    Heuristic extractor:
    - Collects anchor tags that contain 'indeed' in URL
    - Uses anchor text as 'title' when it looks like a job title
    - Dedup by URL
    """
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not _looks_like_job_link(href):
            continue
        if href in seen:
            continue
        seen.add(href)

        text = _normalize_ws(a.get_text(" ", strip=True))

        # Skip tiny/unhelpful anchors
        if len(text) < 6:
            continue

        jobs.append({
            "source": "Indeed(Alert)",
            "title": text,
            "company": "Unknown",
            "location": "Remote/Unknown",
            "url": href,
            "summary": "",
        })

    return jobs


def fetch_indeed_jobs_from_gmail() -> List[Dict]:
    """
    Reads your Gmail inbox via IMAP and parses recent Indeed job alert emails.
    """
    if not USER or not PASS:
        raise RuntimeError("Missing GMAIL_USER / GMAIL_PASS in .env")

    mail = imaplib.IMAP4_SSL(HOST, PORT)
    mail.login(USER, PASS)
    mail.select("INBOX")

    # Gmail IMAP supports searching; keep it flexible.
    # Example: FROM "indeed" SUBJECT "Job Alert"
    query_parts = []
    if INDEED_FROM:
        query_parts.append(f'FROM "{INDEED_FROM}"')
    if INDEED_SUBJECT:
        query_parts.append(f'SUBJECT "{INDEED_SUBJECT}"')

    query = " ".join(query_parts) if query_parts else "ALL"

    typ, data = mail.search(None, query)
    if typ != "OK":
        mail.logout()
        return []

    ids = data[0].split()
    if not ids:
        mail.logout()
        return []

    # Read only the most recent N emails
    ids = ids[-INDEED_MAX_EMAILS:]

    all_jobs: List[Dict] = []

    for msg_id in ids:
        typ, msg_data = mail.fetch(msg_id, "(RFC822)")
        if typ != "OK":
            continue

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        # Optional debug fields if you need them later
        # subject = _decode_mime(msg.get("Subject", ""))
        # from_ = _decode_mime(msg.get("From", ""))

        html = _get_html_body(msg)
        if not html:
            continue

        jobs = extract_jobs_from_indeed_email_html(html)
        all_jobs.extend(jobs)

    mail.logout()
    return all_jobs