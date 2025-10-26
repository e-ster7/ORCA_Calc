# notification_service.py
import smtplib
import time
import socket
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
    """
    Sends an email notification with exponential backoff retry logic.
    (仕様書2.2に基づく変更)
    """
    
    # スロットルチェック
    if throttle_instance and not throttle_instance.can_send(subject):
        _throttle_logger.warning(f"Notification '{subject}' throttled.")
        return

    # 設定セクションチェック
    if not config.has_section('gmail'):
        _throttle_logger.warning("Gmail section not configured. Notification not sent.")
        return

    # --- ★★★ ここからが変更点 ★★★ ---
    
    # リトライ設定
    max_retries = 3
    base_delay_seconds = 2 # 指数関数的バックオフの基礎待機時間 (2^0=1s, 2^1=2s, 2^2=4s...)

    try:
        gmail_config = config['gmail']
        sender_email = gmail_config['user']
        receiver_email = gmail_config['recipient']
        password = gmail_config['password'] # 実際のアプリケーションではより安全な方法を使用
    except KeyError as e:
        _throttle_logger.error(f"Gmail config missing key: {e}. Cannot send notification.")
        return

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = f"ORCA Pipeline: {subject}"

    msg.attach(MIMEText(body, 'plain'))

    # リトライループ
    for attempt in range(max_retries):
        try:
            # タイムアウトを10秒に設定
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10) as server:
                server.login(sender_email, password)
                server.sendmail(sender_email, receiver_email, msg.as_string())
            
            _throttle_logger.info(f"Notification sent: '{subject}'")
            return # 成功したら即座に終了

        except smtplib.SMTPAuthenticationError as e:
            # 恒久的なエラー: 認証失敗
            _throttle_logger.error(f"Failed to send notification (Permanent Error): Authentication failed. Check credentials. {e}")
            return # リトライしない

        except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, socket.timeout, socket.error) as e:
            # 一時的なエラー: 接続切断、タイムアウト、ソケットエラー
            wait_time = (base_delay_seconds ** attempt)
            _throttle_logger.warning(f"Failed to send notification (Temporary Error): {e}. Retrying in {wait_time}s... (Attempt {attempt + 1}/{max_retries})")
            time.sleep(wait_time) # 指数関数的バックオフ
        
        except Exception as e:
            # 予期しないその他のエラー
            _throttle_logger.error(f"Failed to send notification (Unexpected Error): {e}")
            return # リトライしない

    _throttle_logger.error(f"Failed to send notification '{subject}' after {max_retries} attempts.")
    # --- ★★★ 変更点ここまで ★★★ ---
