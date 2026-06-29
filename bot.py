import telebot
from telebot import types
import sqlite3
import os
from datetime import datetime
import requests

TOKEN = "8950946789:AAFagTuyF9hO9pnbIx5rLWrEFsuKRKg9YPY"
CRYPTO_API = "59054:AAeYmni9Huqfd3L9jB05jquBxg5VLxFI7Vs"
CRYPTO_BOT_URL = "https://testnet-pay.crypt.bot/api"

bot = telebot.TeleBot(TOKEN)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dolies.db')

user_states = {}

S = {
    'logo': '◈', 'gem': '◇', 'game': '◎', 'wallet': '◻',
    'check': '✓', 'cross': '✗', 'star': '★', 'refresh': '↻',
    'shield': '♔', 'crown': '♛', 'lock': '⊘', 'globe': '◎',
    'user': '◉', 'pen': '✎', 'warning': '⚠', 'dot': '·',
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS invoices")
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, deposit REAL DEFAULT 0, roulette_balance REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS deals (id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, partner_id INTEGER, amount REAL, subject TEXT, conditions TEXT, status TEXT DEFAULT 'waiting', created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS invoices (user_id INTEGER, invoice_id TEXT, amount REAL, pay_type TEXT, status TEXT)''')
    conn.commit()
    conn.close()
    print("✓ База готова")

init_db()

def create_invoice(amount):
    url = f"{CRYPTO_BOT_URL}/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    data = {"asset": "USDT", "amount": str(amount), "description": "DOLIES пополнение", "paid_btn_name": "callback", "paid_btn_url": "https://t.me/dolies_bot"}
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.json()
    except: return None

def check_invoice(invoice_id):
    url = f"{CRYPTO_BOT_URL}/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    params = {"invoice_ids": invoice_id}
    try:
        response = requests.get(url, headers=headers, params=params)
        return response.json()
    except: return None

def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton(f"{S['gem']} Пополнить депозит"), types.KeyboardButton(f"{S['game']} Пополнить казино"))
    markup.add(types.KeyboardButton(f"{S['wallet']} Баланс"), types.KeyboardButton(f"{S['globe']} Приложение"))
    return markup

def amounts_keyboard(prefix):
    currency = 'USDT' if prefix == 'dep' else '$'
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"10 {currency}", callback_data=f"{prefix}_10"),
        types.InlineKeyboardButton(f"25 {currency}", callback_data=f"{prefix}_25"),
        types.InlineKeyboardButton(f"50 {currency}", callback_data=f"{prefix}_50"),
        types.InlineKeyboardButton(f"100 {currency}", callback_data=f"{prefix}_100"),
        types.InlineKeyboardButton(f"500 {currency}", callback_data=f"{prefix}_500"),
        types.InlineKeyboardButton(f"{S['pen']} Своя сумма", callback_data=f"{prefix}_custom"),
        types.InlineKeyboardButton(f"{S['cross']} Отмена", callback_data=f"{prefix}_cancel")
    )
    return markup

def payment_keyboard(invoice_url, check_data):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{S['gem']} Оплатить", url=invoice_url))
    markup.add(types.InlineKeyboardButton(f"{S['refresh']} Проверить", callback_data=check_data))
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()
    text = f"{S['crown']} <b>DOLIES COMPANY</b>\n<code>основан 29.06.2026</code>\n\n{S['star']} <b>ДОБРО ПОЖАЛОВАТЬ!</b>\n\n{S['shield']} Безопасные сделки\n{S['lock']} Авто-гарант\n{S['gem']} CryptoBot\n\n{S['dot']} Выбери действие:"
    bot.send_message(message.chat.id, text, reply_markup=main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: "Пополнить депозит" in m.text)
def deposit_start(message):
    bot.send_message(message.chat.id, f"{S['gem']} <b>ПОПОЛНЕНИЕ ДЕПОЗИТА</b>\n\nВыбери сумму <b>USDT</b>", reply_markup=amounts_keyboard('dep'), parse_mode="HTML")

@bot.message_handler(func=lambda m: "Пополнить казино" in m.text)
def casino_start(message):
    bot.send_message(message.chat.id, f"{S['game']} <b>ПОПОЛНЕНИЕ КАЗИНО</b>\n\nВыбери сумму <b>$</b>", reply_markup=amounts_keyboard('casino'), parse_mode="HTML")

@bot.message_handler(func=lambda m: "Баланс" in m.text)
def check_balance(message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT deposit, roulette_balance FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    if user:
        text = f"{S['wallet']} <b>БАЛАНС</b>\n\n{S['gem']} Депозит: <code>{user[0]:,.1f} USDT</code>\n{S['game']} Казино: <code>{user[1]:.1f} $</code>"
        bot.send_message(message.chat.id, text, reply_markup=main_keyboard(), parse_mode="HTML")

@bot.message_handler(func=lambda m: "Приложение" in m.text)
def open_miniapp(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{S['globe']} Открыть DOLIES", web_app=types.WebAppInfo(url="https://dolies.pythonanywhere.com")))
    bot.send_message(message.chat.id, "Нажми кнопку ниже", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('dep_', 'casino_')))
def process_payment(call):
    parts = call.data.split('_')
    prefix = parts[0]
    if parts[1] == 'cancel':
        bot.edit_message_text(f"{S['cross']} Отменено", call.message.chat.id, call.message.message_id)
        return
    if parts[1] == 'custom':
        user_states[call.from_user.id] = f'waiting_{prefix}'
        currency = 'USDT' if prefix == 'dep' else '$'
        bot.edit_message_text(f"Введи сумму в {currency}", call.message.chat.id, call.message.message_id)
        return
    amount = float(parts[1])
    pay_type = 'deposit' if prefix == 'dep' else 'casino'
    create_payment(call, amount, pay_type)

def create_payment(call, amount, pay_type):
    invoice = create_invoice(amount)
    if invoice and invoice.get('ok'):
        invoice_url = invoice['result']['pay_url']
        invoice_id = invoice['result']['invoice_id']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO invoices VALUES (?, ?, ?, ?, 'pending')", (call.from_user.id, invoice_id, amount, pay_type))
        conn.commit()
        conn.close()
        check_data = f"check_{pay_type}_{invoice_id}"
        currency = 'USDT' if pay_type == 'deposit' else '$'
        text = f"{S['gem']} <b>СЧЁТ СОЗДАН</b>\n\nСумма: <code>{amount} {currency}</code>\n\nОплати через @Cryptotestnetbot"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=payment_keyboard(invoice_url, check_data), parse_mode="HTML")
    else:
        bot.edit_message_text(f"{S['cross']} Ошибка создания счёта", call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) in ['waiting_dep', 'waiting_casino'])
def custom_amount(message):
    state = user_states.pop(message.from_user.id, None)
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0 or amount > 10000:
            bot.send_message(message.chat.id, "Сумма от 1 до 10000")
            return
        pay_type = 'deposit' if state == 'waiting_dep' else 'casino'
        invoice = create_invoice(amount)
        if invoice and invoice.get('ok'):
            invoice_url = invoice['result']['pay_url']
            invoice_id = invoice['result']['invoice_id']
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO invoices VALUES (?, ?, ?, ?, 'pending')", (message.from_user.id, invoice_id, amount, pay_type))
            conn.commit()
            conn.close()
            check_data = f"check_{pay_type}_{invoice_id}"
            currency = 'USDT' if pay_type == 'deposit' else '$'
            text = f"{S['gem']} <b>СЧЁТ СОЗДАН</b>\n\nСумма: <code>{amount} {currency}</code>"
            bot.send_message(message.chat.id, text, reply_markup=payment_keyboard(invoice_url, check_data), parse_mode="HTML")
    except ValueError:
        bot.send_message(message.chat.id, "Введи число!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def check_payment(call):
    _, pay_type, invoice_id = call.data.split('_', 2)
    user_id = call.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT amount FROM invoices WHERE user_id = ? AND invoice_id = ? AND status = 'pending'", (user_id, invoice_id))
    invoice = c.fetchone()
    if not invoice:
        bot.answer_callback_query(call.id, "Нет активных счетов")
        conn.close()
        return
    amount = invoice[0]
    result = check_invoice(invoice_id)
    if result and result.get('ok') and result['result'].get('items', [{}])[0].get('status') == 'paid':
        if pay_type == 'deposit':
            c.execute("UPDATE users SET deposit = deposit + ? WHERE user_id = ?", (amount, user_id))
        else:
            c.execute("UPDATE users SET roulette_balance = roulette_balance + ? WHERE user_id = ?", (amount, user_id))
        c.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (invoice_id,))
        conn.commit()
        c.execute("SELECT deposit, roulette_balance FROM users WHERE user_id = ?", (user_id,))
        b = c.fetchone()
        conn.close()
        text = f"{S['check']} <b>ОПЛАЧЕНО!</b>\n\n{S['gem']} Депозит: <code>{b[0]:,.1f} USDT</code>\n{S['game']} Казино: <code>{b[1]:.1f} $</code>"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML")
    else:
        conn.close()
        bot.answer_callback_query(call.id, "Счёт не оплачен")

if __name__ == '__main__':
    print(f"{S['logo']} DOLIES BOT запущен {S['logo']}")
    bot.polling(none_stop=True)