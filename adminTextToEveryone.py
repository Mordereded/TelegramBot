from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import CallbackContext, CallbackQueryHandler, MessageHandler, ConversationHandler, CommandHandler, filters
from utils import get_all_user_ids, show_registration_error, is_admin, main_menu_keyboard
from config import Session
from models import User
from States import ADMIN_BROADCAST_MESSAGE


async def check_user_is_approved_and_admin(update: Update, context: CallbackContext):
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


async def admin_broadcast_start(update: Update, context: CallbackContext):
    allowed = await check_user_is_approved_and_admin(update, context)
    if not allowed:
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")]]

    # Удаляем предыдущее сообщение с меню
    try:
        await query.message.delete()
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    await query.message.chat.send_message(
        text="Введите сообщение для рассылки:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_BROADCAST_MESSAGE


async def admin_broadcast_cancel_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # Удаляем сообщение с кнопками
    try:
        await query.message.delete()
    except Exception as e:
        print(f"Ошибка при удалении сообщения: {e}")

    # Отправляем сообщение об отмене + главное меню
    await context.bot.send_message(
        chat_id=user_id,
        text="❌ Рассылка отменена.\n\n📋 Главное меню:",
        reply_markup=main_menu_keyboard(user_id)
    )

    return ConversationHandler.END


async def admin_broadcast_send(update: Update, context: CallbackContext):
    message_text = update.message.text
    admin_id = update.effective_user.id
    user_ids = [uid for uid in get_all_user_ids() if uid != admin_id]

    # Удаляем сообщение администратора
    try:
        await update.message.delete()
    except Exception as e:
        print(f"Ошибка при удалении сообщения админа: {e}")

    count = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ *Оповещение от админа:*\n\n{message_text}",
                parse_mode="Markdown"
            )
            count += 1
        except Exception as e:
            print(f"Не удалось отправить пользователю {user_id}: {e}")

    # Подтверждение + главное меню
    await context.bot.send_message(
        chat_id=admin_id,
        text=f"✅ Рассылка завершена. Отправлено {count} пользователям.\n\n📋 Главное меню:",
        reply_markup=main_menu_keyboard(admin_id)
    )

    return ConversationHandler.END


broadcast_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast_start$")
    ],
    states={
        ADMIN_BROADCAST_MESSAGE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send),
            CallbackQueryHandler(admin_broadcast_cancel_callback, pattern="^cancel_broadcast$")
        ],
    },
    fallbacks=[
        CommandHandler("cancel", admin_broadcast_cancel_callback)
    ],
    allow_reentry=True
)