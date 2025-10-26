# notification_service.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
# 依存関係: logging_utilsからロガーを取得
from logging_utils import get_logger

_throttle_logger = get_logger('throttle')

class NotificationThrottle:
    """Limits the frequency of notifications."""
    def __init__(self, interval_minutes=60):
        self.interval = timedelta(minutes=interval_minutes)
        self.last_sent = {}
    
    def can_send(self, subject):
        """Checks if a notification with this subject can be sent now."""
        now = datetime.now()
        if subject not in self.last_sent or (now - self.last_sent[subject]) > self.interval:
            self.last_sent[subject] = now
            return True
        return False

def send_notification(config, subject, body, throttle_instance=None):
    """Sends an email notification."""
    
    # スロットルチェック
    if throttle_instance and not throttle_instance.can_send(subject):
        _throttle_logger.warning(f"Notification '{subject}' throttled.")
        return

    # 設定セクションチェック
    if not config.has_section('gmail'):
        _throttle_logger.warning("Gmail section not configured. Notification not sent.")
        return

    try:
        gmail_config = config['gmail']
        sender_email = gmail_config['user']
        receiver_email = gmail_config['recipient']
        password = gmail_config['password'] # 実際のアプリケーションではより安全な方法を使用

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = f"ORCA Pipeline: {subject}"

        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        
        _throttle_logger.info(f"Notification sent: '{subject}'")

    except Exception as e:
        _throttle_logger.error(f"Failed to send notification: {e}")
