# Appointment booking bot for Telegram

A booking assistant for a small service business (barbershop, salon, studio,
clinic). Clients book in a few taps, the owner gets every booking in their own
chat, and nobody has to answer "do you have anything Thursday?" by hand.

## Client side

- No commands to remember: a persistent menu under the chat (📅 Book an appointment,
  🗓 My bookings, 💈 Prices & hours, 📞 Contact us) plus Telegram's Menu button
- Book → choose a service (duration and price shown) → choose a day → choose a free time
- Shares phone number with one button, gets a confirmation
- Automatic reminder the day before
- My bookings lists upcoming bookings with a Cancel button

## Owner side

- Instant message on every new booking and cancellation
- An extra "Today's schedule" button (owner only) shows the day's agenda with names and phone numbers
- Working hours, days off and services are set at the top of `bot.py`

## How it's built

- `schedule.py` holds all booking logic and SQLite storage, with no Telegram code,
  so it is fully unit-tested (`pytest`, 7 tests)
- Slot search respects service length: a 75-minute appointment blocks every
  slot it overlaps, not just its start time
- Double booking is impossible: inserts run inside an `IMMEDIATE` transaction
  with an overlap check, so two people tapping the same slot at once get a
  clear "just taken" message instead of a clash
- Past slots are hidden, fully booked days are not offered
- Reminders are tracked so each one is sent exactly once, even after a restart

## Run

```bash
pip install -r requirements.txt
export BOT_TOKEN=123456:ABC...   # from @BotFather
export ADMIN_CHAT_ID=123456789   # owner's Telegram user id
python bot.py
pytest
```

Runs on any small VPS, Railway or Render with a single `python bot.py` process.
Easy to extend with Google Calendar sync, deposits via Stripe, or multiple staff
members with separate schedules.
