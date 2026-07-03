import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import random
import html
from starlette.concurrency import run_in_threadpool
from core import config

logger = config.get_logger("core.email_service")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
# Strip spaces from password if it's an app password (e.g. 'rdnv pqkb nbxm iadk')
if SMTP_PASSWORD:
    SMTP_PASSWORD = SMTP_PASSWORD.replace(" ", "")
FEEDBACK_RECIPIENT_EMAILS = os.getenv("FEEDBACK_RECIPIENT_EMAILS", "")

def _send_feedback_email_sync(user_email: str, role: str, category: str, subject: str, description: str):
    if not SMTP_USERNAME or not SMTP_PASSWORD or not FEEDBACK_RECIPIENT_EMAILS:
        logger.warning("SMTP credentials or recipients not set. Skipping email notification.")
        return

    recipients = [e.strip() for e in FEEDBACK_RECIPIENT_EMAILS.split(",") if e.strip()]
    if not recipients:
        return

    msg = MIMEMultipart('alternative')
    msg['From'] = SMTP_USERNAME
    msg['To'] = ", ".join(recipients)
    msg['Subject'] = f"[DAU Buddy] New Feedback: {subject}"

    # Format as plain text
    body_plain = f"""New Feedback Received - DAU Buddy

User: {user_email}
Role: {role}
Category: {category}
Subject: {subject}

Description:
{description}

Submitted At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    # Escape HTML to prevent XSS in email clients
    safe_user = html.escape(user_email)
    safe_role = html.escape(role)
    safe_category = html.escape(category)
    safe_subject = html.escape(subject)
    safe_description = html.escape(description)

    # Generate random feedback ID
    feedback_id = f"#{random.randint(1000, 9999)}"
    submission_time = datetime.now().strftime('%d %b %Y, %I:%M %p')

    # Determine category badge color
    cat_lower = safe_category.lower()
    if "bug" in cat_lower:
        badge_bg = "#fee2e2"
        badge_color = "#991b1b"
    elif "feature" in cat_lower:
        badge_bg = "#dbeafe"
        badge_color = "#1e40af"
    elif "improvement" in cat_lower:
        badge_bg = "#ffedd5"
        badge_color = "#9a3412"
    else:
        badge_bg = "#dcfce7"
        badge_color = "#166534"

    # Format as HTML
    body_html = f"""
    <html>
      <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 40px 20px;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
          <div style="background-color: #0f3b73; padding: 25px; text-align: center;">
            <div style="color: #93c5fd; font-size: 14px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px;">DAU Buddy</div>
            <h2 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600;">New Feedback Received</h2>
          </div>
          <div style="padding: 30px;">
            <table style="width: 100%; border-collapse: collapse;">
              <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; width: 30%; color: #6b7280; font-weight: 600; font-size: 14px;">Feedback ID</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #111827; font-size: 15px; font-weight: 600;">{feedback_id}</td>
              </tr>
              <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #6b7280; font-weight: 600; font-size: 14px;">Submitted At</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #111827; font-size: 14px;">{submission_time}</td>
              </tr>
              <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #6b7280; font-weight: 600; font-size: 14px;">User</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #111827; font-size: 14px;"><a href="mailto:{safe_user}" style="color: #2563eb; text-decoration: none;">{safe_user}</a></td>
              </tr>
              <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #6b7280; font-weight: 600; font-size: 14px;">Role</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0;">
                    <span style="background-color: #e0e7ff; color: #3730a3; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">{safe_role}</span>
                </td>
              </tr>
              <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #6b7280; font-weight: 600; font-size: 14px;">Category</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #111827; font-size: 14px;">
                    <span style="background-color: {badge_bg}; color: {badge_color}; padding: 4px 10px; border-radius: 4px; font-size: 13px; font-weight: 500;">{safe_category}</span>
                </td>
              </tr>
              <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #6b7280; font-weight: 600; font-size: 14px;">Subject</td>
                <td style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; color: #111827; font-size: 18px; font-weight: bold;">{safe_subject}</td>
              </tr>
            </table>
            
            <div style="margin-top: 25px;">
              <p style="color: #6b7280; font-weight: 600; font-size: 14px; margin-bottom: 8px;">Description:</p>
              <div style="background-color: #f9fafb; padding: 20px; border-radius: 6px; border: 1px solid #e5e7eb; color: #374151; font-size: 15px; line-height: 1.6; white-space: pre-wrap; min-height: 120px;">{safe_description}</div>
            </div>
          </div>
          
          <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e5e7eb; color: #6b7280; font-size: 12px; line-height: 1.5;">
            This email was automatically generated by the DAU Buddy Feedback System.<br>
            Please do not reply directly to this automated email address.
          </div>
        </div>
      </body>
    </html>
    """

    msg.attach(MIMEText(body_plain, 'plain'))
    msg.attach(MIMEText(body_html, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info(f"Feedback email sent successfully to {recipients}")
    except Exception as e:
        logger.error(f"Failed to send feedback email: {e}")

async def send_feedback_email_async(user_email: str, role: str, category: str, subject: str, description: str):
    """Sends the feedback email in a background thread to prevent blocking the API request."""
    await run_in_threadpool(_send_feedback_email_sync, user_email, role, category, subject, description)
