import os
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackContext,
    ConversationHandler, MessageHandler, filters,
    CallbackQueryHandler
)
from telegram import ReplyKeyboardRemove
from sqlalchemy import Column, Integer, String, DateTime, Boolean, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import logging
import sys

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
engine = create_engine('sqlite:///accounts.db', connect_args={"check_same_thread": False})
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
    id = Column(Integer, primary_key=True)
    login = Column(String)
    password = Column(String)
    mmr = Column(Integer)
    status = Column(String)  # free or rented
    rented_at = Column(DateTime, nullable=True)
    renter_id = Column(Integer, nullable=True)
    rent_duration = Column(Integer, nullable=True)

class User(Base):
    __tablename__ = 'users'
    telegram_id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_approved = Column(Boolean, default=False)
    registered_at = Column(DateTime, default=datetime.now)

Base.metadata.create_all(engine)

# --- Состояния для ConversationHandler ---
(ADMIN_ADD_LOGIN, ADMIN_ADD_PASSWORD, ADMIN_ADD_MMR,
 ADMIN_EDIT_CHOOSE_ID, ADMIN_EDIT_CHOOSE_FIELD, ADMIN_EDIT_NEW_VALUE,
 USER_RENT_SELECT_ACCOUNT, USER_RENT_SELECT_DURATION) = range(8)

# --- Вспомогательные функции ---
def is_admin(user_id):
    return user_id in ADMIN_IDS

def format_datetime(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "—"


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
    buttons_user = [
        [InlineKeyboardButton("🔍 Список аккаунтов", callback_data="list")],
        [InlineKeyboardButton("📦 Мой аккаунт", callback_data="my")],
        [InlineKeyboardButton("📥 Взять в аренду", callback_data="rent_start")],
        [InlineKeyboardButton("📤 Вернуть аккаунт", callback_data="return")],
        [InlineKeyboardButton("👤 Кто я", callback_data="whoami")]
    ]
    if is_admin(user_id):
        buttons_user.append([
            InlineKeyboardButton("🛠️ Админ: Список аккаунтов", callback_data="list"),
            InlineKeyboardButton("➕ Добавить аккаунт", callback_data="admin_add_start"),
            InlineKeyboardButton("✏️ Редактировать аккаунт", callback_data="admin_edit_start"),
        ])
        buttons_user.append([InlineKeyboardButton("🆕 Новые пользователи", callback_data="show_pending_users")])
        buttons_user.append([InlineKeyboardButton("📋 Все пользователи", callback_data="show_all_users")])
    return InlineKeyboardMarkup(buttons_user)

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
        if not existing_user:
            is_approved = True if is_admin(user_id) else False
            new_user = User(
                telegram_id=user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_approved=is_approved,
                registered_at=datetime.now()
            )
            session.add(new_user)
            session.commit()
            if is_approved:
                text = "Привет, Админ! Этот бот позволяет арендовать Steam аккаунты с Dota 2 MMR."
                await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
            else:
                await update.message.reply_text(
                    "Спасибо за регистрацию! Ваш аккаунт ожидает подтверждения админом. Пожалуйста, дождитесь подтверждения.",
                )
                await notify_admins_new_user(session, new_user, context.application)
        else:
            if existing_user.is_approved:
                role = "Админ" if is_admin(user_id) else "Пользователь"
                text = f"Привет, {role}! Этот бот позволяет арендовать Steam аккаунты с Dota 2 MMR."
                await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
            else:
                await update.message.reply_text("Ваш аккаунт ещё не подтверждён админом. Пожалуйста, подождите.")
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
                text += (
                    f"ID: {acc.id}\nMMR: {acc.mmr}\nСтатус: {acc.status}\n"
                    f"Логин: {acc.login}\nПароль: {acc.password}\n{rent_info}\n"
                )
        else:
            for acc in accounts:
                status = "✅ Свободен" if acc.status == "free" else "⛔ Арендован"
                text += f"ID: {acc.id}\nMMR: {acc.mmr}\nСтатус: {status}\n\n"

        if not text:
            text = "Нет аккаунтов."

        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
        elif update.callback_query:
            current_text = update.callback_query.message.text or ""
            current_markup = update.callback_query.message.reply_markup
            new_markup = main_menu_keyboard(user_id)

            # Сравним текст и клавиатуры (строгое сравнение невозможно, поэтому можно сравнить данные клавиатуры)
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
                text += (
                    f"ID: {acc.id}\nMMR: {acc.mmr}\nСтатус: аренда\n"
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
            [InlineKeyboardButton(f"ID {acc.id} MMR {acc.mmr}", callback_data=f"rent_acc_{acc.id}")]
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
    await query.answer()  # ПО ВСЕМУ callback нужно отвечать всегда!
    if not data.startswith("rent_acc_"):
        return USER_RENT_SELECT_ACCOUNT
    acc_id = int(data.split("_")[-1])
    context.user_data['rent_acc_id'] = acc_id
    buttons = [
        [InlineKeyboardButton("1 минута", callback_data="rent_dur_1")],
        [InlineKeyboardButton("30 минут", callback_data="rent_dur_30")],
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
        acc.rented_at = datetime.now()
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
        user_obj = session.query(User).filter_by(telegram_id=user_id).first()

        if not user_obj:
            return await show_registration_error(update, "Вы не зарегистрированы.")
        if not user_obj.is_approved:
            return await show_registration_error(update, "Ваш аккаунт ещё не подтверждён админом.")

        acc = session.query(Account).filter_by(renter_id=user_id, status="rented").first()
        if not acc:
            if update.callback_query:
                await update.callback_query.answer("У вас нет арендованных аккаунтов.", show_alert=True)
            elif update.message:
                await update.message.reply_text("У вас нет арендованных аккаунтов.", reply_markup=main_menu_keyboard(user_id))
            return

        acc.status = "free"
        acc.renter_id = None
        acc.rented_at = None
        acc.rent_duration = None
        session.commit()

        text = f"Аккаунт ID {acc.id} успешно возвращён. Спасибо за использование!"
        logging.info(f"User {user_id} returned account {acc.id}.")

        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
        elif update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))

    finally:
        session.close()


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
                if not user.is_approved:
                    await query.answer("Пользователь уже не подтверждён", show_alert=True)
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
    await update.message.reply_text("Введите MMR аккаунта (число):")
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
            mmr=mmr,
            status="free",
            rented_at=None,
            renter_id=None,
            rent_duration=None
        )
        session.add(new_acc)
        session.commit()
        await update.message.reply_text(f"Аккаунт успешно добавлен:\nID {new_acc.id}, MMR {new_acc.mmr}", reply_markup=main_menu_keyboard(update.effective_user.id))
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
            buttons.append([InlineKeyboardButton(f"ID {acc.id} MMR {acc.mmr} Статус {acc.status}", callback_data=f"edit_acc_{acc.id}")])
        buttons.append([InlineKeyboardButton("Отмена", callback_data="admin_back")])
        await update.callback_query.edit_message_text("Выберите аккаунт для редактирования:", reply_markup=InlineKeyboardMarkup(buttons))
    finally:
        session.close()
    return ADMIN_EDIT_CHOOSE_ID

async def admin_edit_choose_id(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    acc_id = int(data.split("_")[-1])
    context.user_data['edit_acc_id'] = acc_id

    buttons = [
        [InlineKeyboardButton("Логин", callback_data="edit_field_login")],
        [InlineKeyboardButton("Пароль", callback_data="edit_field_password")],
        [InlineKeyboardButton("MMR", callback_data="edit_field_mmr")],
        [InlineKeyboardButton("Отмена", callback_data="admin_back")]
    ]
    await query.edit_message_text("Выберите поле для редактирования:", reply_markup=InlineKeyboardMarkup(buttons))
    return ADMIN_EDIT_CHOOSE_FIELD

async def admin_edit_choose_field(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    field = data.replace("edit_field_", "")
    context.user_data['edit_field'] = field
    await query.edit_message_text(f"Введите новое значение для поля '{field}':")
    return ADMIN_EDIT_NEW_VALUE

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
        if field == "mmr":
            if not value.isdigit():
                await update.message.reply_text("MMR должно быть числом. Попробуйте снова:")
                return ADMIN_EDIT_NEW_VALUE
            setattr(acc, field, int(value))
        else:
            setattr(acc, field, value)
        session.commit()
        await update.message.reply_text("Аккаунт успешно обновлён.", reply_markup=main_menu_keyboard(user_id))
    finally:
        session.close()
    return ConversationHandler.END

async def admin_edit_cancel(update: Update, context: CallbackContext):
    await update.message.reply_text("Редактирование аккаунта отменено.", reply_markup=main_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

# --- Автоматический возврат аккаунтов по времени ---
def auto_return_accounts():
    session = Session()
    try:
        now = datetime.now()
        rented = session.query(Account).filter(Account.status == "rented").all()
        for acc in rented:
            if acc.rented_at and acc.rent_duration:
                end_time = acc.rented_at + timedelta(minutes=acc.rent_duration)
                if now >= end_time:
                    acc.status = "free"
                    acc.renter_id = None
                    acc.rented_at = None
                    acc.rent_duration = None
                    logging.info(f"Автоматический возврат аккаунта ID {acc.id}")
        session.commit()
    except Exception as e:
        logging.error(f"Ошибка автоматического возврата аккаунтов: {e}")
    finally:
        session.close()

scheduler.add_job(auto_return_accounts, 'interval', minutes=1)

# --- Основной запуск ---
def main():
    app = Application.builder().token(TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))

    # CallbackQuery хендлеры для админских действий по пользователям (одобрение, отклонение, удаление)
    app.add_handler(CallbackQueryHandler(
        admin_approve_reject_handler,
        pattern=r"^(approve_user_\d+|reject_user_\d+|delete_user_\d+|show_pending_users|show_all_users|admin_back)$"
    ))

    # Отдельный обработчик для просмотра списка аккаунтов
    app.add_handler(CallbackQueryHandler(list_accounts, pattern="^list$"))

    # Другие основные CallbackQuery обработчики
    app.add_handler(CallbackQueryHandler(my, pattern="^my$"))
    app.add_handler(CallbackQueryHandler(whoami, pattern="^whoami$"))
    app.add_handler(CallbackQueryHandler(return_account, pattern="^return$"))

    # Разговорный хендлер для аренды аккаунта
    rent_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(rent_start, pattern="^rent_start$")],
        states={
            USER_RENT_SELECT_ACCOUNT: [CallbackQueryHandler(rent_select_account, pattern="^rent_acc_\\d+$")],
            USER_RENT_SELECT_DURATION: [
                CallbackQueryHandler(rent_select_duration, pattern="^rent_dur_\\d+$|^cancel_rent$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_rent, pattern="^cancel_rent$")]
    )
    app.add_handler(rent_conv)

    # Разговорный хендлер для добавления аккаунта (админ)
    add_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_start, pattern="^admin_add_start$")],
        states={
            ADMIN_ADD_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_login_handler)],
            ADMIN_ADD_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_password_handler)],
            ADMIN_ADD_MMR: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_mmr_handler)],
        },
        fallbacks=[CommandHandler('cancel', admin_add_cancel)]
    )
    app.add_handler(add_acc_conv)
    # Разговорный хендлер для редактирования аккаунта (админ)
    edit_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_start, pattern="^admin_edit_start$")],
        states={
            ADMIN_EDIT_CHOOSE_ID: [CallbackQueryHandler(admin_edit_choose_id, pattern="^edit_acc_\\d+$")],
            ADMIN_EDIT_CHOOSE_FIELD: [CallbackQueryHandler(admin_edit_choose_field, pattern="^edit_field_\\w+$")],
            ADMIN_EDIT_NEW_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_new_value)],
        },
        fallbacks=[CommandHandler('cancel', admin_edit_cancel)]
    )
    app.add_handler(edit_acc_conv)

    # Показать новых пользователей (админ)
    app.add_handler(CallbackQueryHandler(show_pending_users_handler, pattern="^show_pending_users$"))

    # Показать всех пользователей (админ)
    app.add_handler(CallbackQueryHandler(show_all_users_handler, pattern="^show_all_users$"))

    print("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
