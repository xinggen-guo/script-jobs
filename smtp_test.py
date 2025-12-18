import os
import smtplib
from dotenv import load_dotenv

load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO   = os.getenv("EMAIL_TO")

with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as s:
    s.starttls()
    s.login(EMAIL_USER, EMAIL_PASS)
    s.sendmail(
        EMAIL_USER,
        EMAIL_TO,
        "Subject: SMTP Test\n\nHello, your job script email works."
    )

print("SMTP OK")