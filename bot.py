import telebot
from telebot import types
import requests
import time
import threading

TOKEN = "8950946789:AAEvGNNj65P33VL4N9sVFIkNdJFKuCv3Hhk"
CRYPTO_API = "575343:AA8lI3rebCZuc9HxysqN073qP3jLgrz2sx8"  # ← Замени!
CRYPTO_BOT_URL = "https://pay.crypt.bot/api"  # Боевой
API_URL = "https://dolies.pythonanywhere.com/api"
ADMIN_ID = 7518728008

bot = telebot.TeleBot(TOKEN)
bot.remove_webhook()

user_states = {}

S = {
    'gem': '◇', 'game': '◎', 'wallet': '◻', 'check': '✓', 'cross': '✗',
    'star': '★', 'refresh': '↻', 'crown': '♛', 'globe': '◎', 'pen': '✎', 'dot': '·',
}

# Анти-сон
def keep_alive():
    while True:
        time.sleep(180)
        try:
            requests.get(f"{API_URL}/user/{ADMIN_ID}")
            print(f"✓ Keep-alive: {time.strftime('%H:%M:%S')}")
        except: pass

threading.Thread(target=keep_alive, daemon=True).start()

def create_invoice(amount):
    url = f"{CRYPTO_BOT_URL}/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    data = {
        "asset": "USDT",
        "amount": str(amount),
        "description": f"Пополнение DOLIES: {amount} USDT",
        "paid_btn_name": "callback",
        "paid_btn_url": "https://t.me/dolies_bot"
    }
    try:
        return requests.post(url, headers=headers, json=data).json()
    except: return None

def check_invoice(invoice_id):
    url = f"{CRYPTO_BOT_URL}/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    try:
        return requests.get(url, headers=headers, params={"invoice_ids": invoice_id}).json()
    except: return None

def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton(f"{S['gem']} Пополнить депозит"), types.KeyboardButton(f"{S['game']} Пополнить казино"))
    markup.add(types.KeyboardButton(f"{S['wallet']} Баланс"), types.KeyboardButton(f"{S['globe']} Приложение"))
    return markup

def amounts_keyboard(prefix):
    currency = 'USDT' if prefix == 'dep' else '$'
    markup = types.InlineKeyboardMarkup(row_width=2)
    for a in [10, 25, 50, 100, 500]:
        markup.add(types.InlineKeyboardButton(f"{a} {currency}", callback_data=f"{prefix}_{a}"))
    markup.add(types.InlineKeyboardButton(f"{S['pen']} Своя сумма", callback_data=f"{prefix}_custom"))
    markup.add(types.InlineKeyboardButton(f"{S['cross']} Отмена", callback_data=f"{prefix}_cancel"))
    return markup

def payment_keyboard(invoice_url, check_data):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{S['gem']} Оплатить через CryptoBot", url=invoice_url))
    markup.add(types.InlineKeyboardButton(f"{S['refresh']} Проверить оплату", callback_data=check_data))
    return markup

@bot.message_handler(commands=['start'])
def start(message):
    text = f"{S['crown']} DOLIES COMPANY\n{S['star']} Добро пожаловать!\n\n{S['dot']} Выбери действие:"
    bot.send_message(message.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda m: "Пополнить депозит" in m.text)
def deposit_start(message):
    bot.send_message(message.chat.id, f"{S['gem']} <b>ПОПОЛНЕНИЕ ДЕПОЗИТА</b>\n\nВыбери сумму <b>USDT</b>", reply_markup=amounts_keyboard('dep'), parse_mode="HTML")

@bot.message_handler(func=lambda m: "Пополнить казино" in m.text)
def casino_start(message):
    bot.send_message(message.chat.id, f"{S['game']} <b>ПОПОЛНЕНИЕ КАЗИНО</b>\n\nВыбери сумму <b>$</b>", reply_markup=amounts_keyboard('casino'), parse_mode="HTML")

@bot.message_handler(func=lambda m: "Баланс" in m.text)
def check_balance(message):
    try:
        r = requests.get(f"{API_URL}/user/{message.from_user.id}").json()
        text = f"{S['wallet']} <b>БАЛАНС</b>\n\n{S['gem']} Депозит: <code>{r.get('deposit', 0):,.1f} USDT</code>\n{S['game']} Казино: <code>{r.get('roulette_balance', 0):.1f} $</code>"
        bot.send_message(message.chat.id, text, reply_markup=main_keyboard(), parse_mode="HTML")
    except:
        bot.send_message(message.chat.id, "Ошибка загрузки баланса")

@bot.message_handler(func=lambda m: "Приложение" in m.text)
def open_miniapp(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{S['globe']} Открыть DOLIES", web_app=types.WebAppInfo(url="https://dolies.pythonanywhere.com")))
    bot.send_message(message.chat.id, "Нажми кнопку ниже", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('dep_', 'casino_')))
def process_payment(call):
    parts = call.data.split('_')
    prefix = parts[0]
    if parts[1] == 'cancel': return bot.edit_message_text(f"{S['cross']} Отменено", call.message.chat.id, call.message.message_id)
    if parts[1] == 'custom':
        user_states[call.from_user.id] = f'waiting_{prefix}'
        currency = 'USDT' if prefix == 'dep' else '$'
        return bot.edit_message_text(f"Введи сумму в {currency}", call.message.chat.id, call.message.message_id)
    amount = float(parts[1])
    pay_type = 'deposit' if prefix == 'dep' else 'casino'
    create_payment(call, amount, pay_type)

def create_payment(call, amount, pay_type):
    invoice = create_invoice(amount)
    if invoice and invoice.get('ok'):
        invoice_url = invoice['result']['pay_url']
        invoice_id = invoice['result']['invoice_id']
        requests.post(f"{API_URL}/invoice/create", json={"user_id": call.from_user.id, "invoice_id": invoice_id, "amount": amount, "pay_type": pay_type})
        check_data = f"check_{pay_type}_{invoice_id}"
        currency = 'USDT' if pay_type == 'deposit' else '$'
        text = f"{S['gem']} <b>СЧЁТ СОЗДАН</b>\n\nСумма: <code>{amount} {currency}</code>\n\nОплати через @CryptoBot"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=payment_keyboard(invoice_url, check_data), parse_mode="HTML")
    else:
        bot.edit_message_text(f"{S['cross']} Ошибка создания счёта\n\nПроверь API ключ CryptoBot", call.message.chat.id, call.message.message_id)

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) in ['waiting_dep', 'waiting_casino'])
def custom_amount(message):
    state = user_states.pop(message.from_user.id, None)
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0 or amount > 10000: return bot.send_message(message.chat.id, "Сумма от 1 до 10000")
        pay_type = 'deposit' if state == 'waiting_dep' else 'casino'
        invoice = create_invoice(amount)
        if invoice and invoice.get('ok'):
            invoice_url = invoice['result']['pay_url']
            invoice_id = invoice['result']['invoice_id']
            requests.post(f"{API_URL}/invoice/create", json={"user_id": message.from_user.id, "invoice_id": invoice_id, "amount": amount, "pay_type": pay_type})
            check_data = f"check_{pay_type}_{invoice_id}"
            currency = 'USDT' if pay_type == 'deposit' else '$'
            bot.send_message(message.chat.id, f"{S['gem']} <b>СЧЁТ СОЗДАН</b>\n\nСумма: <code>{amount} {currency}</code>", reply_markup=payment_keyboard(invoice_url, check_data), parse_mode="HTML")
    except ValueError:
        bot.send_message(message.chat.id, "Введи число!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def check_payment(call):
    _, pay_type, invoice_id = call.data.split('_', 2)
    result = check_invoice(invoice_id)
    if result and result.get('ok') and result['result']['items'][0]['status'] == 'paid':
        user_id = call.from_user.id
        invoice = requests.get(f"{API_URL}/invoice/{invoice_id}?user_id={user_id}").json()
        if invoice.get('status') != 'paid':
            amount = invoice['amount']
            requests.post(f"{API_URL}/invoice/pay", json={"user_id": user_id, "invoice_id": invoice_id, "amount": amount, "pay_type": pay_type})
        r = requests.get(f"{API_URL}/user/{user_id}").json()
        text = f"{S['check']} <b>ОПЛАЧЕНО!</b>\n\n{S['gem']} Депозит: <code>{r.get('deposit', 0):,.1f} USDT</code>\n{S['game']} Казино: <code>{r.get('roulette_balance', 0):.1f} $</code>"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML")
    else:
        bot.answer_callback_query(call.id, "❌ Счёт не оплачен")

if __name__ == '__main__':
    print("◈ DOLIES BOT ◈")
    bot.polling(none_stop=True)
