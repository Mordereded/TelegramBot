import imaplib
import email
import re
from datetime import datetime, timezone
import logging
from email.header import decode_header

class FirstMailCodeReader:
    def __init__(self, login, password, imap_server="imap.firstmail.ltd", imap_port=993):
        self.login = login
        self.password = password
        self.imap_server = imap_server
        self.imap_port = imap_port

    def fetch_latest_code(self, subject_filter="Steam", since_dt: datetime | None = None) -> tuple[
                                                                                                 str, datetime] | None:
        """
        Ищет код Steam в письмах.
        Если есть письма, пришедшие после since_dt (новые), возвращает первый из них.
        Если таких нет, возвращает самое последнее письмо вообще.
        Возвращает кортеж (код, дата письма).
        """
        logging.info("[FirstMailCodeReader] Начало поиска кода Steam...")
        try:
            with imaplib.IMAP4_SSL(self.imap_server, self.imap_port) as mail:
                typ, msg = mail.login(self.login, self.password)
                if typ != "OK":
                    logging.error("[FirstMailCodeReader] Не удалось войти в почту")
                    return None

                typ, msg = mail.select("inbox")
                if typ != "OK":
                    logging.error("[FirstMailCodeReader] Не удалось выбрать INBOX")
                    return None

                search_criteria = f'(SINCE {since_dt.strftime("%d-%b-%Y")})' if since_dt else 'ALL'
                typ, data = mail.search(None, search_criteria)
                if typ != 'OK':
                    logging.warning("[FirstMailCodeReader] Ошибка поиска писем")
                    return None

                uids = data[0].split()
                logging.info(f"[FirstMailCodeReader] Найдено писем: {len(uids)}")
                if not uids:
                    return None

                newest_code = None
                newest_date = None
                recent_code = None
                recent_date = None

                for num in reversed(uids):
                    typ, msg_data = mail.fetch(num, '(RFC822)')
                    if typ != "OK":
                        continue

                    raw_msg = msg_data[0][1]
                    msg = email.message_from_bytes(raw_msg)

                    subject = self.decode_subject(msg.get("Subject", ""))
                    if subject_filter.lower() not in subject.lower():
                        continue

                    msg_date = email.utils.parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc)
                    body = self.extract_body(msg)
                    if not body:
                        continue

                    email_text = body.replace("\r", "").replace("\n\n", "\n")

                    if self.is_steam_verification_email(email_text):
                        code = self.extract_code(email_text)
                        if code:
                            # сохраняем самое свежее письмо вообще
                            if newest_date is None or msg_date > newest_date:
                                newest_date = msg_date
                                newest_code = code
                            # если письмо пришло после since_dt — это новое
                            if since_dt is None or msg_date >= since_dt:
                                recent_code = code
                                recent_date = msg_date
                                break  # возвращаем сразу новое письмо

                if recent_code:
                    logging.info(f"[FirstMailCodeReader] Найден свежий код: {recent_code} ({recent_date})")
                    return recent_code, recent_date
                elif newest_code:
                    logging.info(
                        f"[FirstMailCodeReader] Используем последнее найденное письмо: {newest_code} ({newest_date})")
                    return newest_code, newest_date

        except Exception as e:
            logging.error(f"[FirstMailCodeReader] Ошибка IMAP соединения: {e}")

        logging.info("[FirstMailCodeReader] Код не найден")
        return None

    def decode_subject(self, subject_raw):
        decoded_parts = decode_header(subject_raw)
        return "".join(
            str(part, enc or "utf-8", errors="ignore") if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )

    def extract_body(self, msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        return part.get_payload(decode=True).decode(errors="ignore")
                    except Exception:
                        continue
        else:
            try:
                return msg.get_payload(decode=True).decode(errors="ignore")
            except Exception:
                pass
        return None

    def is_steam_verification_email(self, body: str) -> bool:
        body_low = body.lower()
        keywords = ["steam guard", "steam code", "код steam", "код доступа", "steam guard code", "login code"]
        return any(k in body_low for k in keywords)

    def extract_code(self, text: str) -> str | None:
        # Пробуем сначала ключевые слова + следующая строка
        lines = text.splitlines()
        for i, line in enumerate(lines):
            line_lower = line.strip().lower()
            if any(k in line_lower for k in ["login code", "steam guard code", "код steam"]):
                for next_line in lines[i+1:]:
                    next_line = next_line.strip()
                    if re.fullmatch(r"[A-Z0-9]{5}", next_line, re.IGNORECASE):
                        return next_line
        # Если не нашли, ищем любую 5-символьную комбинацию с конца письма
        for line in reversed(lines):
            line = line.strip()
            if re.fullmatch(r"[A-Z0-9]{5}", line, re.IGNORECASE):
                return line
        return None
