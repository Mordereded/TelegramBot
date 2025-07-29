
import asyncio

from sqlalchemy import except_, desc

from States import (
    ADMIN_ADD_LOGIN, ADMIN_ADD_PASSWORD, ADMIN_ADD_MMR,
    ADMIN_ADD_CALIBRATION, ADMIN_EDIT_CHOOSE_ID, ADMIN_EDIT_CHOOSE_FIELD,
    ADMIN_EDIT_NEW_VALUE, USER_RENT_SELECT_ACCOUNT, USER_RENT_SELECT_DURATION,
    ADMIN_DELETE_CHOOSE_ID, ADMIN_ADD_BEHAVIOR, ADMIN_EDIT_EMAIL_CHOOSE_FIELD,
    RETURN_CONFIRM_UPDATE, RETURN_SELECT_FIELDS, RETURN_INPUT_MMR,
    RETURN_INPUT_BEHAVIOR,WAIT_FOR_EMAIL_CODE,WAIT_FOR_2FA_CONFIRM,
    ADMIN_ADD_2FA_ASK,ADMIN_ADD_EMAIL,ADMIN_ADD_EMAIL_PASSWORD,
)
from getCodeFromMail import FirstMailCodeReader

from models import Account, User, AccountLog, Email
from config import TOKEN, Session, scheduler, ADMIN_IDS
from utils import is_admin, format_datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)

from telegram.ext import (
    Application, CommandHandler, CallbackContext,
    ConversationHandler, MessageHandler, filters,
    CallbackQueryHandler
)
from telegram import ReplyKeyboardRemove
from datetime import datetime, timedelta, timezone
import logging


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
            return await show_registration_error(update, "❌ Вы не зарегистрированы.")
        if not user_obj.is_approved:
            return await show_registration_error(update, "⏳ Ваш аккаунт ещё не подтверждён админом.")

        accounts = session.query(Account).order_by(desc(Account.mmr)).all()
        text = ""

        if is_admin(user_id):
            text = "🛠 *Все аккаунты (админ):*\n\n"
            for acc in accounts:
                email_obj = session.query(Email).filter_by(accountfk=acc.id).first()
                email_info = ""
                if email_obj:
                    email_info = (
                        f"📧 *Почта:* `{email_obj.login}`\n"
                        f"🔑 *Пароль почты:* `{email_obj.password}`\n"
                        f"🛡 *2FA:* Да\n"
                    )

                rent_info = ""
                if acc.status == "rented" and acc.rented_at and acc.rent_duration:
                    rent_end = acc.rented_at + timedelta(minutes=acc.rent_duration)
                    duration_str = format_duration(acc.rent_duration)
                    rent_info = (
                        f"⏰ *Взято:* {format_datetime(acc.rented_at)}\n"
                        f"⏳ *Длительность аренды:* {duration_str}\n"
                        f"📅 *Вернуть до:* {format_datetime(rent_end)}\n"
                        f"👤 *Арендатор Telegram ID:* `{acc.renter_id or '—'}`\n"
                    )
                calibrated_str = "✅ Да" if acc.calibration else "❌ Нет"

                text += (
                    f"🆔 *ID:* `{acc.id}`\n"
                    f"🎯 *Откалиброван:* {calibrated_str}\n"
                    f"📈 *MMR:* {acc.mmr}\n"
                    f"🧠 *Поведение:* {acc.behavior or '—'}\n"
                    f"🔒 *Статус:* {acc.status.capitalize()}\n"
                    f"👤 *Логин аккаунта:* `{acc.login}`\n"
                    f"🔐 *Пароль аккаунта:* `{acc.password}`\n"
                    f"{email_info}"
                    f"{rent_info}"
                    + ("─" * 30) + "\n\n"
                )
        else:
            text = "🎮 *Доступные аккаунты:*\n\n"
            for acc in accounts:
                status_emoji = "✅" if acc.status == "free" else "⛔"
                calibrated_str = "✅ Да" if acc.calibration else "❌ Нет"

                text += (
                    f"🆔 *ID:* `{acc.id}`\n"
                    f"📈 *MMR:* {acc.mmr}\n"
                    f"🧠 *Поведение:* {acc.behavior or '—'}\n"
                    f"🎯 *Откалиброван:* {calibrated_str}\n"
                    f"🔒 *Статус:* {status_emoji} {acc.status.capitalize()}\n"
                    + ("─" * 25) + "\n\n"
                )

        if not text.strip():
            text = "❌ Нет аккаунтов."

        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        elif update.callback_query:
            current_text = update.callback_query.message.text or ""
            current_markup = update.callback_query.message.reply_markup
            new_markup = main_menu_keyboard(user_id)

            def markup_equals(m1, m2):
                if m1 is None and m2 is None:
                    return True
                if m1 is None or m2 is None:
                    return False
                kb1 = getattr(m1, 'inline_keyboard', None)
                kb2 = getattr(m2, 'inline_keyboard', None)
                return kb1 == kb2

            if current_text == text and markup_equals(current_markup, new_markup):
                await update.callback_query.answer()  # "погасить" спиннер
                return
            else:
                await update.callback_query.edit_message_text(text, reply_markup=new_markup, parse_mode="Markdown")
    finally:
        session.close()


async def my(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    session = Session()
    try:
        user_obj = session.query(User).filter_by(telegram_id=user_id).first()
        if not user_obj:
            return await show_registration_error(update, "❌ Вы не зарегистрированы.")
        if not user_obj.is_approved:
            return await show_registration_error(update, "⏳ Ваш аккаунт ещё не подтверждён админом.")

        accounts = session.query(Account).filter_by(renter_id=user_id, status="rented").all()
        if accounts:
            text = "📋 *Ваши арендованные аккаунты:*\n\n"
            for acc in accounts:
                rent_end = acc.rented_at + timedelta(minutes=acc.rent_duration) if acc.rented_at and acc.rent_duration else None
                duration_str = format_duration(acc.rent_duration) if acc.rent_duration else "—"
                rent_start_str = format_datetime(acc.rented_at) if acc.rented_at else "—"
                rent_end_str = format_datetime(rent_end) if rent_end else "—"
                calibrated_str = "✅ Да" if acc.calibration else "❌ Нет"
                behavior_str = acc.behavior or "—"

                # Получаем почту из связанной таблицы emails
                email_obj = session.query(Email).filter_by(accountfk=acc.id).first()
                email_info = ""
                if email_obj and is_admin(user_id):
                    email_info = (
                        f"📧 *Почта:* `{email_obj.login}`\n"
                        f"🔑 *Пароль почты:* `{email_obj.password}`\n"
                        f"🛡 *2FA:* Да\n"
                    )

                text += (
                    f"🆔 *ID:* `{acc.id}`\n"
                    f"🎯 *Откалиброван:* {calibrated_str}\n"
                    f"📈 *MMR:* {acc.mmr}\n"
                    f"🧠 *Поведение:* {behavior_str}\n"
                    f"🔑 *Логин аккаунта:* `{acc.login}`\n"
                    f"🔒 *Пароль аккаунта:* `{acc.password}`\n"
                    f"{email_info}"
                    f"⏰ *Взято:* {rent_start_str}\n"
                    f"⏳ *Длительность аренды:* {duration_str}\n"
                    f"🕒 *Вернуть до:* {rent_end_str}\n"
                )
                if is_admin(user_id):
                    text += f"👤 *Арендатор Telegram ID:* `{acc.renter_id}`\n"

                text += "\n" + ("─" * 30) + "\n\n"
        else:
            text = "❌ У вас нет арендованных аккаунтов."

        markup = main_menu_keyboard(user_id)
        if update.message:
            await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
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
        username = f"@{user_obj.username}" if user_obj.username else "(нет)"
        first_name = user_obj.first_name if user_obj.first_name else "(нет)"
        last_name = user_obj.last_name if user_obj.last_name else ""

        text = (
            f"👤 *Информация о пользователе:*\n\n"
            f"🆔 *ID:* `{user_obj.telegram_id}`\n"
            f"🔗 *Username:* {username}\n"
            f"📛 *Имя:* {first_name} {last_name}\n"
            f"🎭 *Роль:* {role}"
        )

        if update.message:
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown")
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

        already_rented = session.query(Account).filter_by(renter_id=user_id, status="rented").first()
        if already_rented:
            await query.answer("У вас уже есть арендованный аккаунт.", show_alert=True)
            return ConversationHandler.END

        email_entry = session.query(Email).filter_by(accountfk=acc.id).first()

        # Сразу меняем статус и сохраняем
        acc.status = "rented"
        acc.renter_id = user_id
        acc.rented_at = datetime.now(timezone.utc)
        acc.rent_duration = duration


        session.commit()

        if email_entry:
            # Сохраняем данные почты для дальнейшего ожидания кода
            context.user_data["pending_rent"] = {
                "acc_id": acc.id,
                "duration": duration,
                "email_login": email_entry.login,
                "email_password": email_entry.password
            }
            context.user_data["code_wait_start"] = datetime.now(timezone.utc)

            buttons = [
                [InlineKeyboardButton("✅ Код требуется", callback_data="confirm_2fa_yes")],
                [InlineKeyboardButton("❌ Код не требуется", callback_data="confirm_2fa_no")]
            ]
            await query.edit_message_text(
                f"👤 Логин: `{acc.login}`\n"
                f"🔐 Пароль: `{acc.password}`\n\n"
                "📩 Требуется ли код Steam Guard для входа?\n"
                "✏️ Пожалуйста, подтвердите.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return WAIT_FOR_2FA_CONFIRM
        else:
            message_text = (
                f"👤 Логин: `{acc.login}`\n🔐 Пароль: `{acc.password}`\n\n"
                "⚠️ Для этого аккаунта не настроена двухфакторная аутентификация — код подтверждения не придёт.\n"
                "✅ Аккаунт успешно арендован."
            )
            session.add(AccountLog(
                user_id=user_id,
                account_id=acc.id,
                action='Арендован (без 2FA)',
                action_date=acc.rented_at
            ))
            session.commit()
            await query.edit_message_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(user_id)
            )
            return ConversationHandler.END
    finally:
        session.close()

async def confirm_2fa_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    session = Session()
    try:
        acc_id = context.user_data.get('rent_acc_id')
        user_id = query.from_user.id
        acc = session.query(Account).filter_by(id=acc_id).first()
        if data == "confirm_2fa_yes":
            await query.answer("Ожидаем код с почты...")
            return await wait_for_code_and_confirm(update, context)

        elif data == "confirm_2fa_no":
            await query.answer("Аренда завершена без кода.")
            session.add(AccountLog(
                user_id=user_id,
                account_id=acc_id,
                action='Арендован (без 2FA)',
                action_date=acc.rented_at
            ))
            session.commit()
            context.user_data.clear()
            await query.edit_message_text("Вы в главном меню.", reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END

        else:
            await query.answer()
            return WAIT_FOR_2FA_CONFIRM
    finally:
        session.close()

async def wait_for_code_and_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    data = context.user_data.get("pending_rent")
    if not data:
        await query.edit_message_text("Ошибка: неправильные данные.", reply_markup=main_menu_keyboard(user_id))
        return ConversationHandler.END

    acc_id = data["acc_id"]
    email_login = data.get("email_login")
    email_password = data.get("email_password")

    if not email_login or not email_password:
        await query.edit_message_text("Ошибка: получения кода с почты.", reply_markup=main_menu_keyboard(user_id))
        return ConversationHandler.END

    session = Session()
    acc = session.query(Account).filter_by(id=acc_id).first()
    session.close()
    if not acc:
        await query.edit_message_text("Ошибка: аккаунт не найден.", reply_markup=main_menu_keyboard(user_id))
        return ConversationHandler.END

    total_attempts = 30
    wait_seconds = 10

    cancel_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Отменить аренду", callback_data="cancel_rent")]
    ])

    reader = FirstMailCodeReader(email_login, email_password)

    await query.edit_message_text(
        f"👤 Логин: `{acc.login}`\n"
        f"🔐 Пароль: `{acc.password}`\n\n"
        f"📥 Начинаю поиск кода Steam Guard...\n"
        f"⏳ Максимальное время ожидания: {total_attempts * wait_seconds // 60} мин.",
        parse_mode="Markdown",
        reply_markup=cancel_markup
    )
    await asyncio.sleep(2)
    for attempt in range(total_attempts):
        since_dt = context.user_data.get("code_wait_start")
        if since_dt:
            since_dt = since_dt - timedelta(minutes=5)

        code = reader.fetch_latest_code(since_dt=since_dt)
        if code:
            # Обновляем статус аккаунта в базе
            await query.edit_message_text(
                f"✅ Аккаунт успешно арендован!\n"
                f"👤 Логин: `{acc.login}`\n"
                f"🔐 Пароль: `{acc.password}`\n\n"
                f"📩 Код Steam: `{code}`\n"
                f"🆔 Аккаунт ID: {acc.id}",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(user_id)
            )
            session.add(AccountLog(
                user_id=user_id,
                account_id=acc.id,
                action='Арендован (с 2FA)',
                action_date=acc.rented_at
            ))
            context.user_data.clear()
            return ConversationHandler.END

        else:

            await query.edit_message_text(
                f"👤 Логин: `{acc.login}`\n"
                f"🔐 Пароль: `{acc.password}`\n\n"
                f"📥 Ожидаю код Steam Guard... Попытка {attempt + 1} из {total_attempts}",
                parse_mode="Markdown",
                reply_markup=cancel_markup
            )
            await asyncio.sleep(wait_seconds)

    # Если код не пришёл
    await query.edit_message_text(
        f"⚠️ Не удалось получить код Steam в течение {total_attempts * wait_seconds // 60} минут.\n"
        "Попробуйте позже.",
        reply_markup=main_menu_keyboard(user_id)
    )
    session.add(AccountLog(
        user_id=user_id,
        account_id=acc.id,
        action='Арендован (Ошибка получения кода с почты)',
        action_date=acc.rented_at
    ))
    context.user_data.clear()
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

        # Запись в лог
        session.add(AccountLog(
            user_id=user_id,
            account_id=acc.id,
            action='Возврат аккаунта',
            action_date=datetime.now(timezone.utc)
        ))

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
        context.user_data["created_account_id"] = new_acc.id
        await update.message.reply_text(
            f"Аккаунт успешно добавлен:\nID {new_acc.id}, MMR {new_acc.mmr}",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да", callback_data="2fa_yes"),
             InlineKeyboardButton("❌ Нет", callback_data="2fa_no")]
        ])
        await update.message.reply_text("У аккаунта включена двухфакторная авторизация?", reply_markup=keyboard)
        return ADMIN_ADD_2FA_ASK
    finally:
        session.close()

async def admin_add_ask_2fa_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    if query.data == "2fa_yes":
        await query.edit_message_text("Введите логин от почты:")
        return ADMIN_ADD_EMAIL

    elif query.data == "2fa_no":
        await query.edit_message_text("Аккаунт успешно добавлен без почты.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    else:
        await query.edit_message_text("Неверный выбор. Повторите.")
        return ADMIN_ADD_2FA_ASK

async def admin_add_email_login_handler(update: Update, context: CallbackContext):
    context.user_data['email_login'] = update.message.text.strip()
    await update.message.reply_text("Введите пароль от почты:")
    return ADMIN_ADD_EMAIL_PASSWORD

async def admin_add_email_password_handler(update: Update, context: CallbackContext):

    email_password = update.message.text.strip()
    email_login = context.user_data.get("email_login")
    account_id = context.user_data.get("created_account_id")

    if not account_id:
        await update.message.reply_text("Ошибка: ID аккаунта не найден.")
        return ConversationHandler.END

    session = Session()
    try:
        new_email = Email(login=email_login, password=email_password, accountfk=account_id)
        session.add(new_email)
        session.commit()
        await update.message.reply_text("Почта успешно добавлена к аккаунту.",
                                        reply_markup=main_menu_keyboard(update.effective_user.id))
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
        [InlineKeyboardButton("Почта (2FA)", callback_data="edit_field_email")],
        [InlineKeyboardButton("Отмена", callback_data="admin_back")]
    ]
    await query.edit_message_text("Выберите поле для редактирования:", reply_markup=InlineKeyboardMarkup(buttons))
    return ADMIN_EDIT_CHOOSE_FIELD

async def admin_edit_choose_field(update: Update, context: CallbackContext):
    query = update.callback_query
    field = query.data.replace("edit_field_", "")
    context.user_data['edit_field'] = field

    if field == "email":
        acc_id = context.user_data['edit_acc_id']
        session = Session()
        try:
            email = session.query(Email).filter_by(accountfk=acc_id).first()
            if email:
                buttons = [
                    [InlineKeyboardButton("Изменить логин", callback_data="email_edit_login")],
                    [InlineKeyboardButton("Изменить пароль", callback_data="email_edit_password")],
                    [InlineKeyboardButton("Отмена", callback_data="admin_back")]
                ]
                await query.edit_message_text("Выберите, что изменить в почте:", reply_markup=InlineKeyboardMarkup(buttons))
            else:
                buttons = [
                    [InlineKeyboardButton("Добавить почту", callback_data="email_add_new")],
                    [InlineKeyboardButton("Отмена", callback_data="admin_back")]
                ]
                await query.edit_message_text("Почта не найдена. Добавить новую?", reply_markup=InlineKeyboardMarkup(buttons))
        finally:
            session.close()
        return ADMIN_EDIT_EMAIL_CHOOSE_FIELD

    await query.edit_message_text(f"Введите новое значение для поля {get_field_display_name(field)}:")
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

async def admin_edit_email_choose_field(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data

    if data == "email_add_new":
        context.user_data['email_edit_field'] = 'new'
        await query.edit_message_text("Введите логин и пароль почты через `:` (пример: login@mail.com:password)")
    elif data == "email_edit_login":
        context.user_data['email_edit_field'] = 'login'
        await query.edit_message_text("Введите новый логин почты:")
    elif data == "email_edit_password":
        context.user_data['email_edit_field'] = 'password'
        await query.edit_message_text("Введите новый пароль почты:")
    else:
        await query.edit_message_text("Операция отменена.", reply_markup=main_menu_keyboard(query.from_user.id))
        return ConversationHandler.END

    return ADMIN_EDIT_NEW_VALUE


async def admin_edit_new_value(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    acc_id = context.user_data.get('edit_acc_id')
    field = context.user_data.get('edit_field')
    email_mode = context.user_data.get('email_edit_field')

    session = Session()
    try:
        acc = session.query(Account).filter_by(id=acc_id).first()
        if not acc:
            await update.message.reply_text("Аккаунт не найден.", reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END

        if field == "email":
            email = session.query(Email).filter_by(accountfk=acc_id).first()

            if email_mode == 'new':
                if ":" not in text:
                    await update.message.reply_text("Неверный формат. Используйте: `login:password`")
                    return ADMIN_EDIT_NEW_VALUE
                login, password = map(str.strip, text.split(":", 1))
                new_email = Email(login=login, password=password, accountfk=acc_id)
                session.add(new_email)
            elif email_mode == 'login':
                if not email:
                    await update.message.reply_text("Почта не найдена.")
                    return ConversationHandler.END
                email.login = text
            elif email_mode == 'password':
                if not email:
                    await update.message.reply_text("Почта не найдена.")
                    return ConversationHandler.END
                email.password = text

            session.commit()
            await update.message.reply_text("Почта успешно обновлена.", reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END

        # Обновление обычного поля
        if field in ("mmr", "behavior"):
            if not text.isdigit():
                await update.message.reply_text("Введите числовое значение:")
                return ADMIN_EDIT_NEW_VALUE
            setattr(acc, field, int(text))
        elif field == "calibration":
            acc.calibration = text.lower() in ("да", "yes", "true", "1")
        else:
            setattr(acc, field, text)

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

        # Удаляем связанные email'ы
        email = session.query(Email).filter_by(accountfk=acc_id).first()
        if email:
            session.delete(email)

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
                    logging.info(f"Автоматический возврат аккаунта ID {acc.id}, арендовал User {acc.renter_id}")

                    # Добавляем лог в БД
                    session.add(AccountLog(
                        user_id=acc.renter_id,
                        account_id=acc.id,
                        action='Возврат аккаунта',
                        action_date=datetime.now(timezone.utc)
                    ))

                    # Освобождаем аккаунт
                    acc.status = "free"
                    acc.renter_id = None
                    acc.rented_at = None
                    acc.rent_duration = None
        session.commit()
    except Exception as e:
        logging.error(f"Ошибка автоматического возврата аккаунтов: {e}", exc_info=True)
    finally:
        session.close()


# --- Основной запуск ---
def main():
    app = Application.builder().token(TOKEN).build()
    scheduler.add_job(auto_return_accounts, 'interval', minutes=1)
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
        entry_points=[
            CallbackQueryHandler(rent_start, pattern="^rent_start$")
        ],
        states={
            USER_RENT_SELECT_ACCOUNT: [
                CallbackQueryHandler(rent_select_account, pattern="^rent_acc_\\d+$")
            ],
            USER_RENT_SELECT_DURATION: [
                CallbackQueryHandler(rent_select_duration, pattern="^rent_dur_\\d+$")
            ],
            WAIT_FOR_2FA_CONFIRM: [
                CallbackQueryHandler(confirm_2fa_handler, pattern="^confirm_2fa_(yes|no)$")
            ],
            WAIT_FOR_EMAIL_CODE: [
                CallbackQueryHandler(wait_for_code_and_confirm, pattern="^wait_for_code$")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_rent, pattern="^cancel_rent$")
        ],
        allow_reentry=True
    )
    app.add_handler(rent_conv)

    add_acc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_start, pattern="^admin_add_start$")],
        states={
            ADMIN_ADD_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_login_handler)],
            ADMIN_ADD_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_password_handler)],
            ADMIN_ADD_BEHAVIOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_behavior_handler)],
            ADMIN_ADD_CALIBRATION: [CallbackQueryHandler(admin_add_calibration_handler)],
            ADMIN_ADD_MMR: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_mmr_handler)],
            ADMIN_ADD_2FA_ASK: [CallbackQueryHandler(admin_add_ask_2fa_handler)],
            ADMIN_ADD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_email_login_handler)],
            ADMIN_ADD_EMAIL_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_email_password_handler)],
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
            ADMIN_EDIT_EMAIL_CHOOSE_FIELD: [
                CallbackQueryHandler(admin_edit_email_choose_field,
                                     pattern="^email_(add_new|edit_login|edit_password)$")
            ],
            ADMIN_EDIT_NEW_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_new_value)
            ],
        },
        fallbacks=[
            CommandHandler('cancel', admin_edit_cancel),
            CallbackQueryHandler(admin_edit_cancel, pattern="^admin_back$")
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
    app.run_polling()

if __name__ == '__main__':
    main()
