"""Telegram bot for booking appointments at a small business (salon, studio, clinic).

Clients never type commands: everything is on buttons. A persistent menu under the
chat (Book / My bookings / Prices & hours / Contact) plus Telegram's Menu button.
Clients pick a service, a day and a free time slot, share a phone number, and get
a confirmation plus a reminder the day before. The owner gets every new booking
and cancellation in their own chat and an extra "Today's schedule" button.

    export BOT_TOKEN=...        # from @BotFather
    export ADMIN_CHAT_ID=...    # owner's Telegram user id
    python bot.py
"""

import logging
import os
from datetime import date, datetime, time

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from schedule import Schedule, SlotTaken

SERVICES = {  # key: (title, minutes, price)
    "cut": ("Haircut", 45, 35),
    "beard": ("Beard trim", 30, 20),
    "combo": ("Haircut + beard", 75, 50),
    "color": ("Coloring", 120, 90),
}
BUSINESS = "Bay Street Barbers"
ADDRESS = "212 Bay Street, Tampa, FL 33602"
PHONE = "(813) 555-0123"
HOURS = "Mon–Sat 9 am – 7 pm, Sunday closed"
DAYS_AHEAD = 7

BTN_BOOK = "📅 Book an appointment"
BTN_MY = "🗓 My bookings"
BTN_PRICES = "💈 Prices & hours"
BTN_CONTACT = "📞 Contact us"
BTN_TODAY = "📋 Today's schedule"
BTN_BACK = "⬅️ Back to menu"

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("booking-bot")
schedule = Schedule(os.getenv("DB_PATH", "bookings.db"), open_at=time(9), close_at=time(19))
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))


def fmt(dt):
    return dt.strftime("%a, %b %d at %I:%M %p").replace(" 0", " ")


def main_menu(user_id):
    """Persistent buttons under the chat, so nobody has to type a command."""
    rows = [[BTN_BOOK], [BTN_MY, BTN_PRICES], [BTN_CONTACT]]
    if user_id == ADMIN_CHAT_ID:
        rows.append([BTN_TODAY])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True,
                               input_field_placeholder="Tap a button below")


def keyboard(buttons, per_row=2):
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(rows)


async def notify_admin(context, text):
    if ADMIN_CHAT_ID:
        await context.bot.send_message(ADMIN_CHAT_ID, text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        f"Hi! This is the booking assistant for {BUSINESS}. "
        "Use the buttons below anytime.",
        reply_markup=main_menu(update.effective_user.id))
    await book(update, context)


async def book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [InlineKeyboardButton(f"{title} · {mins} min · ${price}", callback_data=f"svc:{key}")
               for key, (title, mins, price) in SERVICES.items()]
    await update.effective_message.reply_text("What would you like to book?",
                                              reply_markup=keyboard(buttons, per_row=1))


async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [f"• {title}: ${price} ({mins} min)" for title, mins, price in SERVICES.values()]
    await update.message.reply_text("Prices\n" + "\n".join(lines) + f"\n\nHours\n{HOURS}",
                                    reply_markup=main_menu(update.effective_user.id))


async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"{BUSINESS}\n{ADDRESS}\n{PHONE}\n{HOURS}",
                                    reply_markup=main_menu(update.effective_user.id))


async def menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route taps on the persistent menu; anything else gets a gentle nudge to the buttons."""
    text = update.message.text
    routes = {BTN_BOOK: book, BTN_MY: my_bookings, BTN_PRICES: prices,
              BTN_CONTACT: contact_us, BTN_TODAY: today}
    if text in routes:
        return await routes[text](update, context)
    if text == BTN_BACK:
        context.user_data.clear()
    await update.message.reply_text("Please use the buttons below 👇",
                                    reply_markup=main_menu(update.effective_user.id))


async def pick_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":")[1]
    context.user_data["service"] = key
    minutes = SERVICES[key][1]
    buttons = []
    for day in schedule.open_days(date.today(), DAYS_AHEAD):
        if schedule.free_slots(day, minutes):
            buttons.append(InlineKeyboardButton(day.strftime("%a %b %d"), callback_data=f"day:{day}"))
    if not buttons:
        await query.edit_message_text("Sorry, the next week is fully booked. Please try again later.")
        return
    await query.edit_message_text(f"{SERVICES[key][0]}. Pick a day:", reply_markup=keyboard(buttons, 3))


async def pick_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = context.user_data.get("service")
    if not key:
        return await book(update, context)
    day = date.fromisoformat(query.data.split(":")[1])
    slots = schedule.free_slots(day, SERVICES[key][1])
    if not slots:
        await query.edit_message_text("That day just filled up. Tap 📅 Book an appointment to pick another one.")
        return
    buttons = [InlineKeyboardButton(s.strftime("%I:%M %p").lstrip("0"),
                                    callback_data=f"slot:{s.isoformat()}") for s in slots]
    buttons.append(InlineKeyboardButton("« Other day", callback_data=f"svc:{key}"))
    await query.edit_message_text(f"{day:%A, %B %d}. Pick a time:", reply_markup=keyboard(buttons, 4))


async def pick_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["slot"] = query.data.split(":", 1)[1]
    await query.edit_message_text(f"{fmt(datetime.fromisoformat(context.user_data['slot']))}. Almost done.")
    await query.message.reply_text(
        "Please share your phone number so we can reach you if something changes.",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📱 Share phone number", request_contact=True)],
                                          [BTN_BACK]], resize_keyboard=True, one_time_keyboard=True))


async def got_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key, slot = context.user_data.get("service"), context.user_data.get("slot")
    if not (key and slot):
        return await book(update, context)
    user = update.effective_user
    title, minutes, price = SERVICES[key]
    starts_at = datetime.fromisoformat(slot)
    try:
        booking_id = schedule.book(user.id, user.full_name, update.message.contact.phone_number,
                                   title, starts_at, minutes)
    except SlotTaken:
        await update.message.reply_text("Someone booked that time a moment ago, sorry! "
                                        "Tap 📅 Book an appointment to pick another slot.",
                                        reply_markup=main_menu(user.id))
        return
    context.user_data.clear()
    await update.message.reply_text(
        f"You're booked ✅\n\n{title}, {fmt(starts_at)}\n${price}, pay at the shop.\n\n"
        "We'll remind you the day before. Tap 🗓 My bookings to see or cancel it.",
        reply_markup=main_menu(user.id))
    await notify_admin(context, f"🆕 #{booking_id} {title}, {fmt(starts_at)}\n"
                                f"{user.full_name}, {update.message.contact.phone_number}")


async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = schedule.upcoming_for_user(update.effective_user.id)
    if not rows:
        await update.message.reply_text("You have no upcoming bookings. Tap 📅 Book an appointment to make one.")
        return
    for b in rows:
        await update.message.reply_text(
            f"{b['service']}, {fmt(datetime.fromisoformat(b['starts_at']))}",
            reply_markup=keyboard([InlineKeyboardButton("Cancel", callback_data=f"cancel:{b['id']}")]))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    b = schedule.cancel(int(query.data.split(":")[1]), update.effective_user.id)
    if not b:
        await query.edit_message_text("This booking was already cancelled.")
        return
    when = fmt(datetime.fromisoformat(b["starts_at"]))
    await query.edit_message_text(f"Cancelled: {b['service']}, {when}.")
    await notify_admin(context, f"❌ #{b['id']} cancelled: {b['service']}, {when}, {b['user_name']}")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    rows = schedule.day_agenda(date.today())
    lines = [f"{datetime.fromisoformat(b['starts_at']):%I:%M %p}  {b['service']} — "
             f"{b['user_name']}, {b['phone']}" for b in rows]
    await update.message.reply_text("Today:\n" + "\n".join(lines) if lines else "Nothing booked today.")


async def send_reminders(context: ContextTypes.DEFAULT_TYPE):
    for b in schedule.due_reminders(datetime.now()):
        try:
            await context.bot.send_message(
                b["user_id"], f"Reminder: {b['service']} {fmt(datetime.fromisoformat(b['starts_at']))} "
                              f"at {BUSINESS}. Need to cancel? Tap 🗓 My bookings.")
        except Exception:  # user blocked the bot, etc.
            log.warning("Could not remind booking %s", b["id"])


async def setup_menu(app):
    """Telegram's Menu button next to the input field lists what the bot can do."""
    await app.bot.set_my_commands([
        BotCommand("book", "Book an appointment"),
        BotCommand("my", "My bookings"),
        BotCommand("prices", "Prices & hours"),
        BotCommand("contact", "Address and phone"),
    ])


def main():
    app = Application.builder().token(os.environ["BOT_TOKEN"]).post_init(setup_menu).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("book", book))
    app.add_handler(CommandHandler("my", my_bookings))
    app.add_handler(CommandHandler("prices", prices))
    app.add_handler(CommandHandler("contact", contact_us))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CallbackQueryHandler(pick_service, pattern=r"^svc:"))
    app.add_handler(CallbackQueryHandler(pick_day, pattern=r"^day:"))
    app.add_handler(CallbackQueryHandler(pick_slot, pattern=r"^slot:"))
    app.add_handler(CallbackQueryHandler(cancel, pattern=r"^cancel:"))
    app.add_handler(MessageHandler(filters.CONTACT, got_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text))
    app.job_queue.run_repeating(send_reminders, interval=900, first=10)
    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
