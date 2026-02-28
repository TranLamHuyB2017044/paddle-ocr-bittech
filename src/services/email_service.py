import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.utils.logger import Log
from src import config

class EmailService:
    """Service class for sending emails using SMTP."""
    def __init__(self):
        self.email_host = config.EMAIL_HOST
        self.email_port = config.EMAIL_PORT
        self.email_user = config.EMAIL_USER
        self.email_password = config.EMAIL_PASSWORD

    def send_email(self, to_email: str, subject: str, body: str):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_user
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(self.email_host, self.email_port) as server:
                server.starttls()
                server.login(self.email_user, self.email_password)
                server.sendmail(self.email_user, to_email, msg.as_string())
            
            Log.info(f"Email sent to {to_email}")
        except Exception as e:
            Log.error(f"Failed to send email to {to_email}: {e}")

email_service = EmailService()
