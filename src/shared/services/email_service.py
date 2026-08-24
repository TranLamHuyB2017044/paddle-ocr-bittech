import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from src.shared.utils.logger import Log
import src.core.config as config

class EmailService:
    """Service class for sending emails using SMTP."""
    def __init__(self):
        self.email_host = config.EMAIL_HOST
        self.email_port = config.EMAIL_PORT
        self.email_user = config.EMAIL_USER
        self.email_password = config.EMAIL_PASSWORD
        self.email_to = config.EMAIL_TO

    def send_email(self, subject: str, body: str):
        try:
            if not self.email_host or not self.email_port:
                raise ValueError("Email credentials (host/port) are not configured in .env")
                
            port = int(self.email_port)

            msg = MIMEMultipart()
            # The sender is the system account
            msg['From'] = self.email_user
            msg['To'] = self.email_to
            msg['Subject'] = subject
            
            msg.attach(MIMEText(body, 'plain'))

            if port == 465:
                # Standard SSL setup
                with smtplib.SMTP_SSL(self.email_host, port) as server:
                    server.login(self.email_user, self.email_password)
                    server.sendmail(self.email_user, self.email_to, msg.as_string())
            else:
                # Standard TLS setup (e.g. port 587)
                with smtplib.SMTP(self.email_host, port) as server:
                    server.starttls()
                    server.login(self.email_user, self.email_password)
                    server.sendmail(self.email_user, self.email_to, msg.as_string())
            
            Log.info(f"Email sent from system {self.email_user} to {self.email_to}")
        except Exception as e:
            Log.error(f"Failed to send email to {self.email_to}: {e}")

email_service = EmailService()
