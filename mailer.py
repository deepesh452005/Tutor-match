import os
import smtplib
from email.message import EmailMessage

# Read the mail settings from the computer (never written in the code)
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").replace(" ", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER

# Email is only "on" if the three main settings exist.
# Without them we run in dev mode: the code is printed in the terminal.
EMAIL_ENABLED = bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD)

if EMAIL_ENABLED:
    print(f"[MAILER] Email is ON: sending through {SMTP_HOST}:{SMTP_PORT} as {SMTP_USER}")
else:
    print("[MAILER] Email is OFF (dev mode): reset codes will be printed here instead")


def send_reset_code(to_email: str, code: str):
    if not EMAIL_ENABLED:
        print("\n" + "=" * 54)
        print(f"[DEV MODE] Password reset code for {to_email}: {code}")
        print("Email isn't set up, so the code is shown here instead.")
        print("=" * 54 + "\n")
        return

    try:
        msg = EmailMessage()
        msg["Subject"] = "Your Tutor Match password reset code"
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.set_content(
            f"Your Tutor Match password reset code is: {code}\n\n"
            "It works for 15 minutes. If you didn't ask for this, you can ignore this email."
        )

        if SMTP_PORT == 465:
            # Port 465 = secure connection from the very start
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            # Port 587 = start normal, then upgrade to secure
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

        print(f"[MAILER] Reset code emailed to {to_email}")
    except Exception as e:
        # Never show mail errors to the website user, just log them for you
        print(f"[MAILER] Could not send reset email to {to_email}: {e}")