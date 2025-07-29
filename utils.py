from config import ADMIN_IDS
from datetime import timezone, timedelta
import logging

MOSCOW_TZ = timezone(timedelta(hours=3))  # UTC+3

def is_admin(user_id):
    return user_id in ADMIN_IDS

def format_datetime(dt):
    if not dt:
        return "—"
    try:
        if dt.tzinfo is None:
            logging.debug("Datetime наивный, добавляем UTC")
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            logging.debug(f"Datetime уже с таймзоной: {dt.tzinfo}")

        localized_dt = dt.astimezone(MOSCOW_TZ)
        return localized_dt.strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        return f"Неверная дата: {e}"