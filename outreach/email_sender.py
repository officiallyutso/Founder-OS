import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import config

logger = logging.getLogger(__name__)

def send_email(to_address: str, subject: str, body: str, reply_to: str = None) -> dict:
    """Send an email via Gmail SMTP."""
    if not config.gmail_address or not config.gmail_app_password:
        return {"success": False, "error": "Gmail not configured. Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{config.my_name} <{config.gmail_address}>"
    msg["To"] = to_address
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(config.gmail_address, config.gmail_app_password)
            server.sendmail(config.gmail_address, to_address, msg.as_string())
        logger.info(f"Email sent to {to_address}: {subject}")
        return {"success": True, "to": to_address, "subject": subject}
    except Exception as e:
        logger.error(f"Email send failed: {e}")
        return {"success": False, "error": str(e)}
