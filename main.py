import os
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)

from telegram.ext import (
    Application, CommandHandler, CallbackContext,
    ConversationHandler, MessageHandler, filters,
    CallbackQueryHandler
)
from telegram import ReplyKeyboardRemove
from sqlalchemy import Column, Integer, String, DateTime, Boolean, create_engine, BigInteger
from sqlalchemy.orm import declarative_base, sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone
import logging
import sys


from flask import Flask, Response
import threading

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return Response("OK", status=200)

def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)


# --- Загрузка переменных окружения ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("Ошибка: в файле .env не найден BOT_TOKEN")
    sys.exit(1)

ADMIN_IDS = set()
if os.getenv("ADMIN_IDS"):
    ADMIN_IDS = set(map(int, filter(None, os.getenv("ADMIN_IDS").split(","))))

Base = declarative_base()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
scheduler = BackgroundScheduler()
scheduler.start()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- Модели ---
class Account(Base):
    __tablename__ = 'accounts'
    id = Column(BigInteger, primary_key=True)
    login = Column(String)
    password = Column(String)
    behavior = Column(Integer)
    mmr = Column(Integer)
    calibration = Column(Boolean,default=False)
    status = Column(String)  # free or rented
    rented_at = Column(DateTime, nullable=True)
    renter_id = Column(Integer, nullable=True)
    rent_duration = Column(Integer, nullable=True)

class User(Base):
    __tablename__ = 'users'
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_approved = Column(Boolean, default=False)
    registered_at = Column(DateTime, default=datetime.now(timezone.utc))

Base.metadata.create_all(engine)

# --- Состояния для ConversationHandler ---
(ADMIN_ADD_LOGIN, ADMIN_ADD_PASSWORD, ADMIN_ADD_MMR,ADMIN_ADD_CALIBRATION,
 ADMIN_EDIT_CHOOSE_ID, ADMIN_EDIT_CHOOSE_FIELD, ADMIN_EDIT_NEW_VALUE,
 USER_RENT_SELECT_ACCOUNT, USER_RENT_SELECT_DURATION,
 ADMIN_DELETE_CHOOSE_ID,ADMIN_ADD_BEHAVIOR) = range(11)
(
    RETURN_CONFIRM_UPDATE,
    RETURN_SELECT_FIELDS,
    RETURN_INPUT_MMR,
    RETURN_INPUT_BEHAVIOR
) = range(200, 204)

# --- Вспомогательные функции ---
def is_admin(user_id):
    return user_id in ADMIN_IDS


MOSCOW_TZ = timezone(timedelta(hours=3))  # Московское время UTC+3
def format_datetime(dt):
    if not dt:
        return "—"
    try:
        # Если datetime наивный — считаем его UTC
        if dt.tzinfo is None:
            logging.debug("Datetime наивный, добавляем UTC")
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            logging.debug(f"Datetime уже с таймзоной: {dt.tzinfo}")

        # Переводим время в московскую зону
        localized_dt = dt.astimezone(MOSCOW_TZ)
        formatted = localized_dt.strftime("%d.%m.%Y %H:%M")
        return formatted
    except Exception as e:

        return f"Неверная дата: {e}"


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

def format_duration(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    parts = []
    if hours > 0:
        parts.append(f"{hours} ч")
    if mins > 0:
        parts.append(f"{mins} мин")
    return " ".join(parts) if parts else "0 мин"

def main_menu_keyboard(user_id):
    buttons = []

    # Блок пользователя
    buttons.append([InlineKeyboardButton("⠀", callback_data="ignore_gap")])
    buttons.append([InlineKeyboardButton("👤 Пользовательское меню:", callback_data="ignore_user_menu")])
    buttons.append([InlineKeyboardButton("🔍 Список аккаунтов", callback_data="list")])
    buttons.append([InlineKeyboardButton("📦 Мой аккаунт", callback_data="my")])
    buttons.append([InlineKeyboardButton("📥 Взять в аренду", callback_data="rent_start")])
    buttons.append([InlineKeyboardButton("📤 Вернуть аккаунт", callback_data="return")])
    buttons.append([InlineKeyboardButton("👤 Кто я", callback_data="whoami")])


    # Блок администратора (если админ)
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton("⠀", callback_data="ignore_gap")])
        buttons.append([InlineKeyboardButton("🛡 Админ-панель:", callback_data="ignore_admin_panel")])
        buttons.append([InlineKeyboardButton("➕ Добавить аккаунт", callback_data="admin_add_start")])
        buttons.append([InlineKeyboardButton("✏️ Редактировать аккаунт", callback_data="admin_edit_start")])
        buttons.append([InlineKeyboardButton("🗑 Удалить аккаунт", callback_data="admin_delete_start")])
        buttons.append([InlineKeyboardButton("📋 Все пользователи", callback_data="show_all_users")])
        buttons.append([InlineKeyboardButton("🆕 Новые пользователи", callback_data="show_pending_users")])
        buttons.append([InlineKeyboardButton("⠀", callback_data="ignore_gap")])

    return InlineKeyboardMarkup(buttons)

async def notify_admins_new_user(session, new_user: User, app: Application):
    for admin_id in ADMIN_IDS:
        buttons = [
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_user_{new_user.telegram_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_user_{new_user.telegram_id}"),
            ],
            [InlineKeyboardButton("📋 Показать всех ожидающих", callback_data="show_pending_users")]
        ]
        text = (
            f"Новый пользователь ожидает подтверждения:\n\n"
            f"ID: {new_user.telegram_id}\n"
            f"Username: @{new_user.username if new_user.username else '(нет)'}\n"
            f"Имя: {new_user.first_name or '(нет)'} {new_user.last_name or ''}\n"
            f"Зарегистрирован: {format_datetime(new_user.registered_at)}"
        )
        try:
            await app.bot.send_message(admin_id, text, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception as e:
            logging.error(f"Ошибка уведомления админа {admin_id}: {e}")

# --- Хендлеры ---
async def start(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = user.id
    session = Session()
    try:
        existing_user = session.query(User).filter_by(telegram_id=user_id).first()

        if existing_user:
            if existing_user.is_approved:
                role = "Админ" if is_admin(user_id) else "Пользователь"
                await update.message.reply_text(
                    f"Привет, {role}! Этот бот позволяет арендовать Steam аккаунты с Dota 2 MMR.",
                    reply_markup=main_menu_keyboard(user_id)
                )
            else:
                await update.message.reply_text("Ваш аккаунт ещё не подтверждён админом. Пожалуйста, подождите.")
        else:
            is_approved = is_admin(user_id)
            new_user = User(
                telegram_id=user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_approved=is_approved,
                registered_at=datetime.now(timezone.utc)
            )
            session.add(new_user)
            session.commit()

            if is_approved:
                await update.message.reply_text(
                    "Привет, Админ! Этот бот позволяет арендовать Steam аккаунты с Dota 2 MMR.",
                    reply_markup=main_menu_keyboard(user_id)
                )
            else:
                await update.message.reply_text(
                    "Спасибо за регистрацию! Ваш аккаунт ожидает подтверждения админом. Пожалуйста, дождитесь подтверждения."
                )
                await notify_admins_new_user(session, new_user, context.application)
    finally:
        session.close()

async def list_accounts(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        user_obj = session.query(User).filter_by(telegram_id=user_id).first()
        if not user_obj:
            return await show_registration_error(update, "Вы не зарегистрированы.")
        if not user_obj.is_approved:
            return await show_registration_error(update, "Ваш аккаунт ещё не подтверждён админом.")

        accounts = session.query(Account).all()
        text = ""

        if is_admin(user_id):
            for acc in accounts:
                rent_info = ""
                if acc.status == "rented" and acc.rented_at and acc.rent_duration:
                    rent_end = acc.rented_at + timedelta(minutes=acc.rent_duration)
                    duration_str = format_duration(acc.rent_duration)
                    rent_info = (
                        f"Взято: {format_datetime(acc.rented_at)}\n"
                        f"Длительность: {duration_str}\n"
                        f"Вернуть до: {format_datetime(rent_end)}\n"
                        f"Арендатор Telegram ID: {acc.renter_id or '—'}\n"
                    )
                calibrated_str = "Да" if acc.calibration else "Нет"
                text += (
                    f"ID: {acc.id}\n"
                    f"Откалиброван: {calibrated_str}\n"
                    f"MMR: {acc.mmr}\n"
                    f"Behavior: {acc.behavior or '—'}\n"
                    f"Статус: {acc.status}\n"
                    f"Логин: {acc.login}\n"
                    f"Пароль: {acc.password}\n"
                    f"{rent_info}\n"
                )
        else:
            for acc in accounts:
                status = "✅ Свободен" if acc.status == "free" else "⛔ Арендован"
                calibrated_str = "Да" if acc.calibration else "Нет"
                text += (
                    f"ID: {acc.id}\n"
                    f"MMR: {acc.mmr}\n"
                    f"Behavior: {acc.behavior or '—'}\n"
                    f"Откалиброван: {calibrated_str}\n"
                    f"Статус: {status}\n\n"
                )

        if not text:
            text = "Нет аккаунтов."

        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
        elif update.callback_query:
            current_text = update.callback_query.message.text or ""
            current_markup = update.callback_query.message.reply_markup
            new_markup = main_menu_keyboard(user_id)

            def markup_equals(m1, m2):
                if m1 is None and m2 is None:
                    return True
                if m1 is None or m2 is None:
                    return False
                # Сравним структуру inline_keyboard (список списков кнопок)
                kb1 = getattr(m1, 'inline_keyboard', None)
                kb2 = getattr(m2, 'inline_keyboard', None)
                return kb1 == kb2

            if current_text == text and markup_equals(current_markup, new_markup):
                await update.callback_query.answer()  # просто "погасить" спиннер
                return
            else:
                await update.callback_query.edit_message_text(text, reply_markup=new_markup)
    finally:
        session.close()




async def my(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        user_obj = session.query(User).filter_by(telegram_id=user_id).first()

        if not user_obj:
            return await show_registration_error(update, "Вы не зарегистрированы.")
        if not user_obj.is_approved:
            return await show_registration_error(update, "Ваш аккаунт ещё не подтверждён админом.")

        accounts = session.query(Account).filter_by(renter_id=user_id, status="rented").all()
        if accounts:
            text = "Ваши арендованные аккаунты:\n\n"
            for acc in accounts:
                rent_end = acc.rented_at + timedelta(minutes=acc.rent_duration) if acc.rented_at and acc.rent_duration else None
                duration_str = format_duration(acc.rent_duration) if acc.rent_duration else "—"
                calibrated_str = "Да" if acc.calibration else "Нет"
                text += (
                    f"ID: {acc.id}\n"
                    f"Откалиброван: {calibrated_str}\n"
                    f"MMR: {acc.mmr}\n"
                    f"Behavior: {acc.behavior or '—'}\n"
                    f"Статус: аренда\n"
                    f"Логин: {acc.login}\nПароль: {acc.password}\n"
                    f"Взято: {format_datetime(acc.rented_at)}\n"
                    f"Длительность: {duration_str}\n"
                    f"Вернуть до: {format_datetime(rent_end)}\n\n"
                )
                if user_id in ADMIN_IDS:
                    text += f"Арендатор Telegram ID: {acc.renter_id}\n\n"
        else:
            text = "У вас нет арендованных аккаунтов."

        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
    finally:
        session.close()




async def whoami(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        user_obj = session.query(User).filter_by(telegram_id=user_id).first()

        if not user_obj:
            return await show_registration_error(update, "Вы не зарегистрированы.")
        if not user_obj.is_approved:
            return await show_registration_error(update, "Ваш аккаунт ещё не подтверждён админом.")

        role = "Админ" if is_admin(user_id) else "Пользователь"
        text = (
            f"ID: {user_obj.telegram_id}\n"
            f"Username: @{user_obj.username or '(нет)'}\n"
            f"Имя: {user_obj.first_name or '(нет)'} {user_obj.last_name or ''}\n"
            f"Подтверждён админом: Да\n"
            f"Роль: {role}"
        )

        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
    finally:
        session.close()




# --- Аренда: старт выбора аккаунта ---
async def rent_start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        user_obj = session.query(User).filter_by(telegram_id=user_id).first()

        if not user_obj:
            await show_registration_error(update, "Вы не зарегистрированы.")
            return ConversationHandler.END

        if not user_obj.is_approved:
            await show_registration_error(update, "Ваш аккаунт ещё не подтверждён админом.")
            return ConversationHandler.END

        # Проверяем, есть ли уже арендованный аккаунт у пользователя
        already_rented = session.query(Account).filter_by(renter_id=user_id, status="rented").first()
        if already_rented:
            text = f"У вас уже есть арендованный аккаунт ID {already_rented.id}. Сначала верните его."
            if update.callback_query:
                await update.callback_query.answer(text, show_alert=True)
                # Можно просто отредактировать сообщение, чтобы не оставлять кнопки аренды:
                await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
            else:
                await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END

        free_accs = session.query(Account).filter_by(status="free").all()
        if not free_accs:
            if update.callback_query:
                await update.callback_query.answer("Свободных аккаунтов нет.", show_alert=True)
            return ConversationHandler.END

        buttons = [

            [InlineKeyboardButton(f"MMR: {acc.mmr} Откалиброван: {'Да' if acc.calibration == 1 else 'Нет'} Порядочность: {acc.behavior}", callback_data=f"rent_acc_{acc.id}")]
            for acc in free_accs

        ]
        # Кнопка отмены — callback_data "cancel_rent", чтобы ловилась fallbacks
        buttons.append([InlineKeyboardButton("Отмена", callback_data="cancel_rent")])

        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                "Выберите аккаунт для аренды:", reply_markup=InlineKeyboardMarkup(buttons)
            )
        return USER_RENT_SELECT_ACCOUNT
    finally:
        session.close()

async def cancel_rent(update: Update, context: CallbackContext):
    query = update.callback_query
    if query:
        await query.answer()
        # Просто возвращаем главное меню, не делая ничего лишнего
        await query.edit_message_text("Главное меню", reply_markup=main_menu_keyboard(query.from_user.id))
    elif update.message:
        await update.message.reply_text("Главное меню", reply_markup=main_menu_keyboard(update.effective_user.id))
    context.user_data.clear()
    return ConversationHandler.END



# --- Аренда: выбор аккаунта ---
async def rent_select_account(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    await query.answer()
    if not data.startswith("rent_acc_"):
        return USER_RENT_SELECT_ACCOUNT
    acc_id = int(data.split("_")[-1])
    context.user_data['rent_acc_id'] = acc_id
    buttons = [
        [InlineKeyboardButton("60 минут", callback_data="rent_dur_60")],
        [InlineKeyboardButton("120 минут", callback_data="rent_dur_120")],
        [InlineKeyboardButton("3 часа", callback_data="rent_dur_180")],
        [InlineKeyboardButton("6 часов", callback_data="rent_dur_360")],
        [InlineKeyboardButton("12 часов", callback_data="rent_dur_720")],
        [InlineKeyboardButton("24 часа", callback_data="rent_dur_1440")],
    ]
    await query.edit_message_text("Выберите длительность аренды:", reply_markup=InlineKeyboardMarkup(buttons))
    return USER_RENT_SELECT_DURATION

# --- Аренда: выбор длительности ---
async def rent_select_duration(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if not data.startswith("rent_dur_"):
        await query.answer()
        return USER_RENT_SELECT_DURATION
    duration = int(data.split("_")[-1])
    acc_id = context.user_data.get('rent_acc_id')
    user_id = query.from_user.id
    session = Session()
    try:
        acc = session.query(Account).filter_by(id=acc_id).first()
        if not acc or acc.status != "free":
            await query.answer("Аккаунт уже арендован.", show_alert=True)
            return ConversationHandler.END
        # Проверка, нет ли у пользователя уже аренды
        already_rented = session.query(Account).filter_by(renter_id=user_id, status="rented").first()
        if already_rented:
            await query.answer("У вас уже есть арендованный аккаунт. Сначала верните его.", show_alert=True)
            return ConversationHandler.END
        acc.status = "rented"
        acc.renter_id = user_id
        acc.rented_at = datetime.now(timezone.utc)
        acc.rent_duration = duration
        session.commit()
        await query.edit_message_text(
            f"Аккаунт ID {acc.id} успешно арендован на {format_duration(duration)}.",
            reply_markup=main_menu_keyboard(user_id)
        )
        logging.info(f"User {user_id} rented account {acc.id} for {duration} minutes.")
    finally:
        session.close()
    return ConversationHandler.END


# --- Возврат аккаунта ---
async def return_account(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user or not user.is_approved:
            return await show_registration_error(update, "Вы не зарегистрированы или не подтверждены.")

        acc = session.query(Account).filter_by(renter_id=user_id, status="rented").first()
        if not acc:
            await update.callback_query.answer("У вас нет арендованных аккаунтов.", show_alert=True)
            return ConversationHandler.END

        context.user_data["return_acc_id"] = acc.id

        buttons = [
            [InlineKeyboardButton("Да", callback_data="return_update_yes")],
            [InlineKeyboardButton("Нет", callback_data="return_update_no")]
        ]
        await update.callback_query.edit_message_text(
            "Вы хотите обновить MMR или Behavior перед возвратом?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return RETURN_CONFIRM_UPDATE
    finally:
        session.close()

async def return_confirm_handler(update: Update, context: CallbackContext):
    if update.callback_query.data == "return_update_yes":
        buttons = [
            [InlineKeyboardButton("MMR", callback_data="update_mmr")],
            [InlineKeyboardButton("Behavior", callback_data="update_behavior")],
            [InlineKeyboardButton("Оба", callback_data="update_both")]
        ]
        await update.callback_query.edit_message_text(
            "Что вы хотите обновить?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return RETURN_SELECT_FIELDS
    else:
        return await finalize_return(update, context)  # обычный возврат без изменений

async def return_input_mmr(update: Update, context: CallbackContext):
    mmr = update.message.text.strip()
    if not mmr.isdigit():
        await update.message.reply_text("MMR должен быть числом:")
        return RETURN_INPUT_MMR
    context.user_data["new_mmr"] = int(mmr)

    if context.user_data["update_choice"] == "update_both":
        await update.message.reply_text("Введите новый Behavior:")
        return RETURN_INPUT_BEHAVIOR
    else:
        return await finalize_return(update, context)

async def return_input_behavior(update: Update, context: CallbackContext):
    behavior = update.message.text.strip()
    if not behavior.isdigit():
        await update.message.reply_text("Behavior должен быть числом:")
        return RETURN_INPUT_BEHAVIOR
    context.user_data["new_behavior"] = int(behavior)
    return await finalize_return(update, context)

async def finalize_return(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        acc = session.query(Account).get(context.user_data["return_acc_id"])
        acc.status = "free"
        acc.renter_id = None
        acc.rented_at = None
        acc.rent_duration = None

        if "new_mmr" in context.user_data:
            acc.mmr = context.user_data["new_mmr"]
        if "new_behavior" in context.user_data:
            acc.behavior = context.user_data["new_behavior"]

        session.commit()

        text = f"Аккаунт ID {acc.id} успешно возвращён!"
        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
        else:
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
    finally:
        session.close()
        context.user_data.clear()
    return ConversationHandler.END


async def return_select_fields(update: Update, context: CallbackContext):
    data = update.callback_query.data
    context.user_data["update_choice"] = data
    if data == "update_mmr":
        await update.callback_query.edit_message_text("Введите новый MMR:")
        return RETURN_INPUT_MMR
    elif data == "update_behavior":
        await update.callback_query.edit_message_text("Введите новый Behavior:")
        return RETURN_INPUT_BEHAVIOR
    elif data == "update_both":
        await update.callback_query.edit_message_text("Введите новый MMR:")
        return RETURN_INPUT_MMR



# --- Админ: Показать новых пользователей ---
async def show_pending_users_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.callback_query.answer("Доступ запрещён", show_alert=True)
        return
    session = Session()
    try:
        pending_users = session.query(User).filter_by(is_approved=False).all()
        if not pending_users:
            text = "Нет новых пользователей, ожидающих подтверждения."
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
            return
        text = "Новые пользователи:\n\n"
        buttons = []
        for u in pending_users:
            uname = f"@{u.username}" if u.username else "(нет username)"
            text += f"ID: {u.telegram_id} {uname}\n"
            buttons.append([
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"approve_user_{u.telegram_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_user_{u.telegram_id}"),
            ])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")])
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    finally:
        session.close()

# --- Обработка callback от админских кнопок ---
async def admin_approve_reject_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if not is_admin(user_id):
        await query.answer("Доступ запрещён", show_alert=True)
        return

    session = Session()
    try:
        # --- Подтверждение пользователя ---
        if data.startswith("approve_user_"):
            target_id = int(data.split("_")[-1])
            user = session.query(User).filter_by(telegram_id=target_id).first()
            if user:
                if user.is_approved:
                    await query.answer("Пользователь уже подтверждён", show_alert=True)
                    return

                user.is_approved = True
                session.commit()
                await query.answer("Пользователь одобрен")

                try:
                    await context.application.bot.send_message(
                        target_id,
                        "Ваш аккаунт подтверждён администратором!\nТеперь вы можете пользоваться ботом.",
                        reply_markup=main_menu_keyboard(target_id)
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки сообщения пользователю {target_id}: {e}")

            else:
                await query.answer("Пользователь не найден", show_alert=True)

        # --- Отклонение пользователя ---
        elif data.startswith("reject_user_"):
            target_id = int(data.split("_")[-1])
            user = session.query(User).filter_by(telegram_id=target_id).first()
            if user:
                if is_admin(target_id):
                    await query.answer("Нельзя отклонить администратора!", show_alert=True)
                    return
                user.is_approved = False
                session.commit()
                await query.answer("Пользователь отклонён")
                # При желании можно уведомить пользователя
                try:
                    await context.application.bot.send_message(
                        target_id,
                        "Ваш аккаунт был отклонён администратором. Свяжитесь с поддержкой для уточнения."
                    )
                except Exception as e:
                    logging.error(f"Ошибка отправки сообщения пользователю {target_id}: {e}")

            else:
                await query.answer("Пользователь не найден", show_alert=True)

        # --- Удаление пользователя ---
        elif data.startswith("delete_user_"):
            target_id = int(data.split("_")[-1])

            if target_id == user_id:
                await query.answer("Вы не можете удалить самого себя!", show_alert=True)
                return

            if is_admin(target_id):
                await query.answer("Нельзя удалить другого администратора!", show_alert=True)
                return

            user = session.query(User).filter_by(telegram_id=target_id).first()
            if user:
                # Возвращаем все арендованные аккаунты пользователя в пул
                rented_accs = session.query(Account).filter_by(renter_id=target_id, status="rented").all()
                for acc in rented_accs:
                    acc.status = "free"
                    acc.renter_id = None
                    acc.rented_at = None
                    acc.rent_duration = None

                session.delete(user)
                session.commit()
                await query.answer("Пользователь удалён и его аккаунты возвращены в пул.")
            else:
                await query.answer("Пользователь не найден", show_alert=True)

        # --- Показать новых пользователей ---
        elif data == "show_pending_users":
            await show_pending_users_handler(update, context)
            return

        # --- Показать всех пользователей ---
        elif data == "show_all_users":
            await show_all_users_handler(update, context)
            return

        # --- Назад в главное меню ---
        elif data == "admin_back":
            await query.edit_message_text("Главное меню", reply_markup=main_menu_keyboard(user_id))
            return

        # --- Показать список аккаунтов ---
        elif data == "list":
            await list_accounts(update, context)
            return

        else:
            await query.answer()

    except Exception as e:
        logging.error(f"Ошибка в admin_approve_reject_handler: {e}")
        await query.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)

    finally:
        session.close()

    # После действия показываем обновлённый список новых пользователей
    if data.startswith(("approve_user_", "reject_user_", "delete_user_")):
        await show_pending_users_handler(update, context)


# --- Админ: показать всех пользователей ---
async def show_all_users_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.callback_query.answer("Доступ запрещён", show_alert=True)
        return
    session = Session()
    try:
        users = session.query(User).all()
        if not users:
            text = "Пользователей нет."
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
            return

        text = "Все пользователи:\n\n"
        buttons = []
        for u in users:
            uname = f"@{u.username}" if u.username else "(нет username)"
            approved = "✅" if u.is_approved else "❌"
            text += f"ID: {u.telegram_id} {uname} Подтверждён: {approved}\n"
            buttons.append([
                InlineKeyboardButton(f"Удалить {u.telegram_id}", callback_data=f"delete_user_{u.telegram_id}")
            ])
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_back")])

        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    finally:
        session.close()

# --- Добавление аккаунта (ConversationHandler) ---
async def admin_add_start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.callback_query.answer("Доступ запрещён", show_alert=True)
        return ConversationHandler.END
    await update.callback_query.edit_message_text("Введите логин нового аккаунта:")
    return ADMIN_ADD_LOGIN

async def admin_add_login_handler(update: Update, context: CallbackContext):
    context.user_data['new_login'] = update.message.text.strip()
    await update.message.reply_text("Введите пароль аккаунта:")
    return ADMIN_ADD_PASSWORD

async def admin_add_password_handler(update: Update, context: CallbackContext):
    context.user_data['new_password'] = update.message.text.strip()
    await update.message.reply_text("Введите Behavior аккаунта (число):")
    return ADMIN_ADD_BEHAVIOR

async def admin_add_behavior_handler(update: Update, context: CallbackContext):
    behavior_text = update.message.text.strip()
    if not behavior_text.isdigit():
        await update.message.reply_text("Behavior должен быть числом. Попробуйте снова:")
        return ADMIN_ADD_BEHAVIOR

    context.user_data['new_behavior'] = int(behavior_text)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data="calibration_yes"),
         InlineKeyboardButton("❌ Нет", callback_data="calibration_no")]
    ])

    await update.message.reply_text("Аккаунт откалиброван?", reply_markup=keyboard)
    return ADMIN_ADD_CALIBRATION

async def admin_add_calibration_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "calibration_yes":
        context.user_data['new_calibration'] = True
    elif query.data == "calibration_no":
        context.user_data['new_calibration'] = False
    else:
        await query.edit_message_text("Неверный выбор. Попробуйте ещё раз.")
        return ADMIN_ADD_CALIBRATION

    await query.edit_message_text("Введите MMR аккаунта (число):")
    return ADMIN_ADD_MMR

async def admin_add_mmr_handler(update: Update, context: CallbackContext):
    mmr_text = update.message.text.strip()
    if not mmr_text.isdigit():
        await update.message.reply_text("MMR должен быть числом. Попробуйте снова:")
        return ADMIN_ADD_MMR
    mmr = int(mmr_text)
    session = Session()
    try:
        new_acc = Account(
            login=context.user_data['new_login'],
            password=context.user_data['new_password'],
            behavior=context.user_data['new_behavior'],
            mmr=mmr,
            calibration= context.user_data['new_calibration'],
            status="free",
            rented_at=None,
            renter_id=None,
            rent_duration=None
        )
        session.add(new_acc)
        session.commit()
        await update.message.reply_text(
            f"Аккаунт успешно добавлен:\nID {new_acc.id}, MMR {new_acc.mmr}",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
    finally:
        session.close()
    return ConversationHandler.END

async def admin_add_cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Добавление аккаунта отменено.", reply_markup=main_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

# --- Редактирование аккаунта (ConversationHandler) ---
async def admin_edit_start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.callback_query.answer("Доступ запрещён", show_alert=True)
        return ConversationHandler.END
    session = Session()
    try:
        accounts = session.query(Account).all()
        buttons = []
        for acc in accounts:
            buttons.append([InlineKeyboardButton(f"ID: {acc.id}\n Login: {acc.login}\n MMR: {acc.mmr}\n Статус: {acc.status}", callback_data=f"edit_acc_{acc.id}")])
        buttons.append([InlineKeyboardButton("Отмена", callback_data="admin_back")])
        await update.callback_query.edit_message_text("Выберите аккаунт для редактирования:", reply_markup=InlineKeyboardMarkup(buttons))
    finally:
        session.close()
    return ADMIN_EDIT_CHOOSE_ID

async def admin_edit_choose_id(update: Update, context: CallbackContext):
    logging.info(">>> Вызван admin_edit_choose_id")
    query = update.callback_query
    data = query.data
    acc_id = int(data.split("_")[-1])
    context.user_data['edit_acc_id'] = acc_id

    buttons = [
        [InlineKeyboardButton("Логин", callback_data="edit_field_login")],
        [InlineKeyboardButton("Пароль", callback_data="edit_field_password")],
        [InlineKeyboardButton("MMR", callback_data="edit_field_mmr")],
        [InlineKeyboardButton("Behavior", callback_data="edit_field_behavior")],
        [InlineKeyboardButton("Калибровка", callback_data="edit_field_calibration")],
        [InlineKeyboardButton("Отмена", callback_data="admin_back")]
    ]
    await query.edit_message_text("Выберите поле для редактирования:", reply_markup=InlineKeyboardMarkup(buttons))
    return ADMIN_EDIT_CHOOSE_FIELD

async def admin_edit_choose_field(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    field = data.replace("edit_field_", "")
    context.user_data['edit_field'] = field
    await query.edit_message_text(f"Введите новое значение для {get_field_display_name(field)}:")
    return ADMIN_EDIT_NEW_VALUE

def get_field_display_name(field_name: str) -> str:
    field_map = {
        "id": "ID",
        "login": "Логин",
        "password": "Пароль",
        "mmr": "MMR",
        "behavior": "Рейтинг поведение",
        "status": "Статус",
        "rented_at": "Время аренды",
        "renter_id": "ID арендатора",
        "rent_duration": "Длительность аренды (мин)",
        "calibration": "Откалиброван",
        "telegram_id": "Telegram ID",
        "username": "Имя пользователя",
        "first_name": "Имя",
        "last_name": "Фамилия",
        "is_approved": "Подтверждён",
        "registered_at": "Дата регистрации",
    }
    return field_map.get(field_name, field_name)

async def admin_edit_new_value(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    value = update.message.text.strip()
    acc_id = context.user_data.get('edit_acc_id')
    field = context.user_data.get('edit_field')
    session = Session()
    try:
        acc = session.query(Account).filter_by(id=acc_id).first()
        if not acc:
            await update.message.reply_text("Аккаунт не найден.", reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END
        # Валидация MMR
        if field == "mmr" or field == "behavior":
            if not value.isdigit():
                await update.message.reply_text(f"{get_field_display_name(field)} должно быть числом. Попробуйте снова:")
                return ADMIN_EDIT_NEW_VALUE
            setattr(acc, field, int(value))

        elif field == "calibration":
            if value.lower() in ["да", "yes", "true", "1"]:
                acc.calibration = True
            elif value.lower() in ["нет", "no", "false", "0"]:
                acc.calibration = False
            else:
                await update.message.reply_text("Введите 'да' или 'нет' для калибровки:")
                return ADMIN_EDIT_NEW_VALUE
        else:
            setattr(acc, field, value)
        session.commit()
        await update.message.reply_text("Аккаунт успешно обновлён.", reply_markup=main_menu_keyboard(user_id))
    finally:
        session.close()
    return ConversationHandler.END

async def admin_edit_cancel(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if update.message:  # отмена через команду
        await update.message.reply_text("Редактирование аккаунта отменено.", reply_markup=main_menu_keyboard(user_id))
    elif update.callback_query:  # отмена через кнопку
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Редактирование аккаунта отменено.", reply_markup=main_menu_keyboard(user_id))

    return ConversationHandler.END

async def admin_delete_cancel(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    if update.message:
        await update.message.reply_text("Удаление аккаунта отменено.", reply_markup=main_menu_keyboard(user_id))
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Удаление аккаунта отменено.", reply_markup=main_menu_keyboard(user_id))

    return ConversationHandler.END

async def admin_delete_start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.callback_query.answer("Доступ запрещён", show_alert=True)
        return ConversationHandler.END
    session = Session()
    try:
        accounts = session.query(Account).all()
        if not accounts:
            await update.callback_query.edit_message_text("Аккаунтов нет.", reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END

        buttons = [
            [InlineKeyboardButton(f"ID {acc.id} MMR {acc.mmr} Статус {acc.status}", callback_data=f"delete_acc_{acc.id}")]
            for acc in accounts
        ]
        buttons.append([InlineKeyboardButton("Отмена", callback_data="admin_back")])
        await update.callback_query.edit_message_text("Выберите аккаунт для удаления:", reply_markup=InlineKeyboardMarkup(buttons))
    finally:
        session.close()
    return ADMIN_DELETE_CHOOSE_ID

async def admin_delete_choose_account(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    logging.info(f"admin_delete_choose_id called with data: {user_id}")
    if not is_admin(user_id):
        await query.answer("Доступ запрещён", show_alert=True)
        return ConversationHandler.END

    acc_id = int(query.data.split("_")[-1])
    session = Session()
    try:
        acc = session.query(Account).filter_by(id=acc_id).first()
        if not acc:
            await query.answer("Аккаунт не найден", show_alert=True)
            return ConversationHandler.END
        session.delete(acc)
        session.commit()
        await query.edit_message_text(f"Аккаунт ID {acc_id} удалён.", reply_markup=main_menu_keyboard(user_id))
    finally:
        session.close()
    return ConversationHandler.END

# --- Автоматический возврат аккаунтов по времени ---
def auto_return_accounts():
    session = Session()
    try:
        now = datetime.now(timezone.utc)
        rented = session.query(Account).filter(Account.status == "rented").all()
        for acc in rented:
            if acc.rented_at and acc.rent_duration:
                rented_at = acc.rented_at
                if rented_at.tzinfo is None:
                    rented_at = rented_at.replace(tzinfo=timezone.utc)

                end_time = rented_at + timedelta(minutes=acc.rent_duration)
                if now >= end_time:
                    acc.status = "free"
                    acc.renter_id = None
                    acc.rented_at = None
                    acc.rent_duration = None
                    logging.info(f"Автоматический возврат аккаунта ID {acc.id}")
        session.commit()
    except Exception as e:
        logging.error(f"Ошибка автоматического возврата аккаунтов: {e}", exc_info=True)
    finally:
        session.close()

scheduler.add_job(auto_return_accounts, 'interval', minutes=1)




# --- Основной запуск ---
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(CallbackQueryHandler(
        admin_approve_reject_handler,
        pattern=r"^(approve_user_\d+|reject_user_\d+|delete_user_\d+|show_pending_users|show_all_users|admin_back)$"
    ))

    app.add_handler(CallbackQueryHandler(list_accounts, pattern="^list$"))
    app.add_handler(CallbackQueryHandler(my, pattern="^my$"))
    app.add_handler(CallbackQueryHandler(whoami, pattern="^whoami$"))
    return_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(return_account, pattern="^return$")],
        states={
            RETURN_CONFIRM_UPDATE: [CallbackQueryHandler(return_confirm_handler, pattern="^return_update_(yes|no)$")],
            RETURN_SELECT_FIELDS: [CallbackQueryHandler(return_select_fields, pattern="^update_(mmr|behavior|both)$")],
            RETURN_INPUT_MMR: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_input_mmr)],
            RETURN_INPUT_BEHAVIOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, return_input_behavior)],
        },
        fallbacks=[],
    )
    app.add_handler(return_conv)

    rent_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rent_start, pattern="^rent_start$")],
        states={
            USER_RENT_SELECT_ACCOUNT: [CallbackQueryHandler(rent_select_account, pattern="^rent_acc_\\d+$")],
            USER_RENT_SELECT_DURATION: [CallbackQueryHandler(rent_select_duration, pattern="^rent_dur_\\d+$|^cancel_rent$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_rent, pattern="^cancel_rent$")],
        allow_reentry=True
    )
    app.add_handler(rent_conv)

    add_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_start, pattern="^admin_add_start$")],
        states={
            ADMIN_ADD_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_login_handler)],
            ADMIN_ADD_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_password_handler)],
            ADMIN_ADD_BEHAVIOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_behavior_handler)],
            ADMIN_ADD_CALIBRATION: [CallbackQueryHandler(admin_add_calibration_handler, pattern="^calibration_(yes|no)$")],
            ADMIN_ADD_MMR: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_mmr_handler)],
        },
        fallbacks=[CommandHandler("cancel", admin_add_cancel)],
        allow_reentry=True
    )
    app.add_handler(add_acc_conv)

    edit_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_start, pattern="^admin_edit_start$")],
        states={
            ADMIN_EDIT_CHOOSE_ID: [
                CallbackQueryHandler(admin_edit_choose_id, pattern="^edit_acc_\\d+$"),

            ],
            ADMIN_EDIT_CHOOSE_FIELD: [
                CallbackQueryHandler(admin_edit_choose_field, pattern="^edit_field_\\w+$")
            ],
            ADMIN_EDIT_NEW_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_new_value)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', admin_edit_cancel),
            CallbackQueryHandler(admin_edit_cancel, pattern="^admin_back$"),
        ],
        allow_reentry=True
    )

    app.add_handler(edit_acc_conv)
    delete_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_delete_start, pattern="^admin_delete_start$")],
        states={
            ADMIN_DELETE_CHOOSE_ID: [
                CallbackQueryHandler(admin_delete_choose_account, pattern="^delete_acc_\\d+$")
            ]
        },
        fallbacks=[
            CommandHandler('cancel', admin_delete_cancel),
            CallbackQueryHandler(admin_delete_cancel, pattern="^admin_back$"),
        ],
        allow_reentry=True
    )
    app.add_handler(delete_acc_conv)
    app.add_handler(CallbackQueryHandler(show_all_users_handler, pattern="^show_all_users$"))
    app.add_handler(CallbackQueryHandler(lambda update, context: update.callback_query.answer(), pattern="^ignore_"))
    print("Бот запущен...")
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    app.run_polling()

if __name__ == '__main__':
    main()
