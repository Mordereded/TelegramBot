import asyncio

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import CallbackContext, CallbackQueryHandler, MessageHandler, ConversationHandler, CommandHandler, filters
from utils import get_all_user_ids, show_registration_error, is_admin, main_menu_keyboard, check_user_is_approved_and_admin
from States import ADMIN_BROADCAST_MESSAGE
import traceback
import logging
import html
import asyncio



async def admin_broadcast_start(update: Update, context: CallbackContext):
    allowed = await check_user_is_approved_and_admin(update)
    if not allowed:
        return ConversationHandler.END

    query = update.callback_query
    await query.answer()

    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_broadcast")]]

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
    logging.info(f"Отправка рассылки пользователям: {user_ids}")

    try:
        await update.message.delete()
    except Exception as e:
        logging.warning(f"Ошибка при удалении сообщения админа: {e}")

    async def send_message(user_id):
        try:
            full_message = (
                f"{html.escape(message_text)}\n\n"
                f"📋 Чтобы открыть меню, нажмите или введите команду /start"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=full_message,
                parse_mode="HTML"
            )
            logging.info(f"✅ Сообщение успешно отправлено пользователю {user_id}")
            return True
        except Exception as e:
            logging.error(f"❌ Не отправлено пользователю {user_id}: {e}")
            logging.error(traceback.format_exc())
            return False

    tasks = [send_message(uid) for uid in user_ids]
    results = await asyncio.gather(*tasks)

    count_success = sum(results)
    count_fail = len(results) - count_success

    result_message = (
        f"✅ Рассылка завершена.\n"
        f"Отправлено успешно: {count_success} пользователям.\n"
        f"Не отправлено: {count_fail} пользователям.\n\n"
        f"📋 Главное меню:\n"
        f"Если меню не появилось — введите /start"
    )

    await context.bot.send_message(
        chat_id=admin_id,
        text=result_message,
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