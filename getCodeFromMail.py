import imaplib
import email
import re
from datetime import datetime, timezone
import logging


class FirstMailCodeReader:
    def __init__(self, login, password, imap_server="imap.firstmail.ltd", imap_port=993):
        self.login = login
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port

    def fetch_latest_code(self, subject_filter="Steam", since_dt: datetime = None):
        with imaplib.IMAP4_SSL(self.imap_server, self.imap_port) as mail:
            mail.login(self.login, self.password)
            mail.select("inbox")

            if since_dt:
                since_str = since_dt.strftime("%d-%b-%Y")
                typ, data = mail.search(None, f'(SINCE {since_str})')
                logging.info(f"[FirstMailCodeReader] Поиск писем начиная с {since_str}")
            else:
                typ, data = mail.search(None, 'ALL')
                logging.info("[FirstMailCodeReader] Поиск всех писем")

            if typ != 'OK':
                logging.warning("[FirstMailCodeReader] Ошибка при выполнении поиска писем (IMAP)")
                return None

            uids = data[0].split()
            if not uids:
                logging.info("[FirstMailCodeReader] Письма не найдены")
                return None

            for num in reversed(uids):
                typ, msg_data = mail.fetch(num, '(RFC822)')
                raw_msg = msg_data[0][1]
                msg = email.message_from_bytes(raw_msg)

                subject = msg.get("Subject", "")
                if subject_filter not in subject:
                    logging.debug(f"[FirstMailCodeReader] Пропущено письмо с темой: {subject}")
                    continue

                date_str = msg.get("Date")
                try:
                    msg_date = email.utils.parsedate_to_datetime(date_str)
                    logging.debug(f"[FirstMailCodeReader] Проверяется дата письма: {msg_date}")
                except Exception as e:
                    logging.warning(f"[FirstMailCodeReader] Не удалось разобрать дату '{date_str}': {e}")
                    continue

                msg_date_utc = msg_date.astimezone(timezone.utc)

                if since_dt and msg_date_utc < since_dt:
                    logging.debug(f"[FirstMailCodeReader] Письмо старше чем since_dt ({since_dt}), пропущено")
                    continue

                try:
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                if self.is_steam_verification_email(body):
                                    code = self.extract_code(body)
                                    if code:
                                        logging.info(f"[FirstMailCodeReader] Найден код: {code}")
                                        return code
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")
                        if self.is_steam_verification_email(body):
                            code = self.extract_code(body)
                            if code:
                                logging.info(f"[FirstMailCodeReader] Найден код: {code}")
                                return code
                except Exception as e:
                    logging.error(f"[FirstMailCodeReader] Ошибка при обработке тела письма: {e}")

        return None

    def is_steam_verification_email(self, body: str) -> bool:
        """
        Проверяет, является ли письмо уведомлением Steam о входе с нового устройства.
        """
        expected_phrase = "It looks like you are trying to log in from a new device."
        if expected_phrase.lower() in body.lower():
            logging.debug("[FirstMailCodeReader] Письмо соответствует шаблону проверки входа Steam.")
            return True
        logging.debug("[FirstMailCodeReader] Письмо не содержит ключевой фразы входа Steam.")
        return False

    def extract_code(self, text: str) -> str | None:
        match = re.search(r"Steam Guard code.*?([A-Z0-9]{5})", text, re.IGNORECASE)
        if match:
            return match.group(1)
        fallback = re.search(r'\b[A-Z0-9]{5}\b', text)
        return fallback.group(0) if fallback else None
