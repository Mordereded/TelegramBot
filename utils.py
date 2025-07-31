import telegram
from telegram.ext import CallbackContext

from config import ADMIN_IDS, Session
from datetime import timezone, timedelta
import logging
from models import User
from telegram import (
    Update, ReplyKeyboardRemove, InlineKeyboardButton,InlineKeyboardMarkup
)

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

def get_all_user_ids():
    with Session() as session:
        return [user_id for (user_id,) in session.query(User.telegram_id).all()]


async def show_registration_error(update: Update, message: str):
    try:
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.delete()
        elif update.message:
            await update.message.delete()
    except Exception:
        pass

    await update.effective_chat.send_message(
        text=message + "\n\nПожалуйста, отправьте команду /start, чтобы начать.",
        reply_markup=ReplyKeyboardRemove()
    )


def main_menu_keyboard(user_id):
    buttons = []

    # Заголовок пользовательского блока
    buttons.append([InlineKeyboardButton("👤 Пользовательское меню", callback_data="ignore_user_menu")])

    # Пользовательские действия, сгруппированные
    buttons += [
        [InlineKeyboardButton("📦  Мой аккаунт", callback_data="my"),
         InlineKeyboardButton("📥  Арендовать", callback_data="rent_start")],

        [InlineKeyboardButton("📤  Вернуть аккаунт", callback_data="return"),
         InlineKeyboardButton("👁️  Кто я", callback_data="whoami")],

        [InlineKeyboardButton("🔍  Список аккаунтов", callback_data="list")]
    ]

    # Админ-блок
    if is_admin(user_id):
        # Разделитель
        buttons.append([InlineKeyboardButton("🛡 Админ-панель", callback_data="ignore_admin_panel")])

        # Админ-действия, сгруппированные
        buttons += [
            [InlineKeyboardButton("➕  Добавить аккаунт", callback_data="admin_add_start"),
             InlineKeyboardButton("✏️  Редактировать", callback_data="admin_edit_start")],

            [InlineKeyboardButton("🗑  Удалить аккаунт", callback_data="admin_delete_start"),
             InlineKeyboardButton("📋  Все пользователи", callback_data="show_all_users")],

            [InlineKeyboardButton("🆕  Новые пользователи", callback_data="show")],
            [InlineKeyboardButton("📢  Рассылка", callback_data="admin_broadcast_start")]
        ]

    return InlineKeyboardMarkup(buttons)

async def show_main_menu(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    try:
        if update.callback_query:
            await update.callback_query.message.delete()
        elif update.message:
            await update.message.delete()
    except Exception as e:
        print(f"Не удалось удалить сообщение: {e}")
    await context.bot.send_message(
        chat_id=user_id,
        text="📋 Главное меню:",
        reply_markup=main_menu_keyboard(user_id)
    )

async def check_user_is_approved_and_admin(update: Update):
    user_id = update.effective_user.id
    session = Session()
    user_obj = session.query(User).filter_by(telegram_id=user_id).first()
    session.close()

    if not user_obj:
        await show_registration_error(update, "❌ Вы не зарегистрированы.")
        return False

    if not user_obj.is_approved:
        await show_registration_error(update, "⏳ Ваш аккаунт ещё не подтверждён админом.")
        return False

    if not is_admin(user_id):
        await show_registration_error(update, "❌ У вас нет прав администратора.")
        return False
    return True