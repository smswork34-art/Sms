import telebot
from telebot import types
import requests
import time
import threading
from flask import Flask
import os
import logging
import json
import sys
from datetime import datetime, timedelta
from collections import OrderedDict

# ===== НАСТРОЙКИ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('DoliesBot')

# Токены
TOKEN = os.environ.get('TELEGRAM_TOKEN', '8950946789:AAHfb-ZMRsWRg3-OvyDiOsPBzXbHKB8lzQw')
CRYPTO_API = os.environ.get('CRYPTO_API', '575343:AA8lI3rebCZuc9HxysqN073qP3jLgrz2sx8')
CRYPTO_BOT_URL = "https://pay.crypt.bot/api"
API_URL = "https://dolies.pythonanywhere.com/api"
ADMIN_ID = int(os.environ.get('ADMIN_ID', '7518728008'))
PORT = int(os.environ.get('PORT', 10000))

# ===== FLASK =====
def create_app():
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return f'DOLIES Bot is running! 🚀\nTime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', 200
    
    @app.route('/health')
    def health():
        return {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat()
        }, 200
    
    @app.route('/ping')
    def ping():
        try:
            me = bot.get_me()
            return {
                'ok': True,
                'bot': f'@{me.username}',
                'timestamp': datetime.now().isoformat()
            }, 200
        except Exception as e:
            return {'ok': False, 'error': str(e)}, 500
    
    return app

web_app = create_app()

# ===== БОТ =====
bot = telebot.TeleBot(TOKEN, threaded=True)
bot.remove_webhook()
logger.info("✅ Bot initialized, webhook removed")

# ===== КЭШ СОСТОЯНИЙ =====
class UserStateCache:
    def __init__(self, max_age_minutes=30, max_size=500):
        self.cache = OrderedDict()
        self.max_age = max_age_minutes
        self.max_size = max_size
        self.lock = threading.Lock()
    
    def get(self, user_id):
        with self.lock:
            if user_id in self.cache:
                state, timestamp = self.cache[user_id]
                if datetime.now() - timestamp < timedelta(minutes=self.max_age):
                    return state
                else:
                    del self.cache[user_id]
            return None
    
    def set(self, user_id, state):
        with self.lock:
            if len(self.cache) >= self.max_size:
                cutoff = datetime.now() - timedelta(minutes=self.max_age)
                self.cache = OrderedDict(
                    (k, v) for k, v in self.cache.items() 
                    if v[1] > cutoff
                )
            self.cache[user_id] = (state, datetime.now())
    
    def pop(self, user_id, default=None):
        with self.lock:
            if user_id in self.cache:
                state, _ = self.cache[user_id]
                del self.cache[user_id]
                return state
            return default
    
    def clean(self):
        with self.lock:
            cutoff = datetime.now() - timedelta(minutes=self.max_age)
            self.cache = OrderedDict(
                (k, v) for k, v in self.cache.items() 
                if v[1] > cutoff
            )

user_states = UserStateCache()

# ===== ЭМОДЗИ =====
S = {
    'gem': '◇', 'game': '◎', 'wallet': '◻', 'check': '✓', 
    'cross': '✗', 'star': '★', 'refresh': '↻', 'crown': '♛', 
    'globe': '◎', 'pen': '✎', 'dot': '·', 'rocket': '🚀',
    'money': '💎', 'error': '⚠️'
}

# ===== HTTP КЛИЕНТ С РЕТРАЯМИ =====
def make_request(method, url, max_retries=3, **kwargs):
    timeout = kwargs.pop('timeout', 15)
    
    for attempt in range(max_retries):
        try:
            response = method(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout: {url} (attempt {attempt + 1}/{max_retries})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error: {url} (attempt {attempt + 1}/{max_retries})")
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None
        
        if attempt < max_retries - 1:
            time.sleep(1 * (attempt + 1))
    
    return None

def create_invoice(amount):
    url = f"{CRYPTO_BOT_URL}/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    data = {
        "asset": "USDT",
        "amount": str(amount),
        "description": f"DOLIES: {amount} USDT",
        "paid_btn_name": "callback",
        "paid_btn_url": "https://t.me/dolies_bot"
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        if not response.ok:
            logger.error(f"CryptoPay error: {response.text}")
            return None
        result = response.json()
        if not result.get('ok'):
            logger.error(f"CryptoPay API error: {result.get('error')}")
            return None
        return result
    except Exception as e:
        logger.error(f"Invoice creation error: {e}")
        return None

def check_invoice(invoice_id):
    url = f"{CRYPTO_BOT_URL}/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    
    try:
        response = requests.get(url, headers=headers, params={"invoice_ids": invoice_id}, timeout=10)
        if not response.ok:
            return None
        return response.json()
    except Exception as e:
        logger.error(f"Check invoice error: {e}")
        return None

# ===== КЛАВИАТУРЫ =====
def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton(f"{S['gem']} Пополнить депозит"),
        types.KeyboardButton(f"{S['game']} Пополнить казино")
    )
    markup.add(
        types.KeyboardButton(f"{S['wallet']} Баланс"),
        types.KeyboardButton(f"{S['globe']} Приложение")
    )
    return markup

def amounts_keyboard(prefix):
    currency = 'USDT' if prefix == 'dep' else '$'
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for amount in [10, 25, 50, 100, 500]:
        markup.add(types.InlineKeyboardButton(
            f"{amount} {currency}",
            callback_data=f"{prefix}_{amount}"
        ))
    
    markup.add(
        types.InlineKeyboardButton(f"{S['pen']} Своя сумма", callback_data=f"{prefix}_custom"),
        types.InlineKeyboardButton(f"{S['cross']} Отмена", callback_data=f"{prefix}_cancel")
    )
    return markup

def payment_keyboard(invoice_url, check_data):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(f"{S['money']} Оплатить", url=invoice_url))
    markup.add(types.InlineKeyboardButton(f"{S['refresh']} Проверить оплату", callback_data=check_data))
    return markup

# ===== ОБРАБОТЧИКИ КОМАНД =====
@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        welcome_text = (
            f"{S['rocket']} <b>DOLIES COMPANY</b> {S['rocket']}\n\n"
            f"{S['star']} Добро пожаловать!\n\n"
            f"{S['dot']} Выберите действие в меню:"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=main_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Start error: {e}")

@bot.message_handler(func=lambda m: m.text and "Пополнить депозит" in m.text)
def deposit_start(message):
    try:
        bot.send_message(
            message.chat.id,
            f"{S['gem']} <b>ПОПОЛНЕНИЕ ДЕПОЗИТА</b>\n\nВыберите сумму <b>USDT</b>:",
            reply_markup=amounts_keyboard('dep'),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Deposit start error: {e}")

@bot.message_handler(func=lambda m: m.text and "Пополнить казино" in m.text)
def casino_start(message):
    try:
        bot.send_message(
            message.chat.id,
            f"{S['game']} <b>ПОПОЛНЕНИЕ КАЗИНО</b>\n\nВыберите сумму <b>$</b>:",
            reply_markup=amounts_keyboard('casino'),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Casino start error: {e}")

@bot.message_handler(func=lambda m: m.text and "Баланс" in m.text)
def check_balance(message):
    try:
        user_id = message.from_user.id
        response = make_request(requests.get, f"{API_URL}/user/{user_id}")
        
        if not response:
            bot.send_message(message.chat.id, f"{S['error']} Не удалось получить баланс", reply_markup=main_keyboard())
            return
        
        data = response.json()
        deposit = data.get('deposit', 0)
        roulette = data.get('roulette_balance', 0)
        
        balance_text = (
            f"{S['wallet']} <b>ВАШ БАЛАНС</b>\n\n"
            f"{S['gem']} Депозит: <code>{deposit:,.2f} USDT</code>\n"
            f"{S['game']} Казино: <code>{roulette:,.2f} $</code>"
        )
        
        bot.send_message(message.chat.id, balance_text, reply_markup=main_keyboard(), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Balance error: {e}")

@bot.message_handler(func=lambda m: m.text and "Приложение" in m.text)
def open_miniapp(message):
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            f"{S['rocket']} Открыть DOLIES",
            web_app=types.WebAppInfo(url="https://dolies.pythonanywhere.com")
        ))
        bot.send_message(message.chat.id, "Нажмите кнопку ниже:", reply_markup=markup)
    except Exception as e:
        logger.error(f"Miniapp error: {e}")

# ===== ОБРАБОТЧИК CALLBACK =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        data = call.data
        
        if data.endswith('_cancel'):
            bot.edit_message_text(f"{S['cross']} Отменено", call.message.chat.id, call.message.message_id)
            return
        
        if data.endswith('_custom'):
            prefix = data.split('_')[0]
            user_states.set(call.from_user.id, f'waiting_{prefix}')
            currency = 'USDT' if prefix == 'dep' else '$'
            bot.edit_message_text(
                f"Введите сумму в {currency} (1-10000):",
                call.message.chat.id,
                call.message.message_id
            )
            return
        
        if data.startswith(('dep_', 'casino_')):
            parts = data.split('_')
            amount = float(parts[1])
            pay_type = 'deposit' if parts[0] == 'dep' else 'casino'
            create_payment(call.from_user.id, call.message, amount, pay_type)
            return
        
        if data.startswith('check_'):
            _, pay_type, invoice_id = data.split('_', 2)
            check_payment_status(call, pay_type, invoice_id)
            return
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        try:
            bot.answer_callback_query(call.id, "Ошибка")
        except:
            pass

def create_payment(user_id, message, amount, pay_type):
    try:
        invoice = create_invoice(amount)
        
        if not invoice:
            bot.send_message(message.chat.id, f"{S['error']} Ошибка создания счёта")
            return
        
        invoice_url = invoice['result']['pay_url']
        invoice_id = invoice['result']['invoice_id']
        
        # Регистрируем в API
        try:
            requests.post(
                f"{API_URL}/invoice/create",
                json={
                    "user_id": user_id,
                    "invoice_id": invoice_id,
                    "amount": amount,
                    "pay_type": pay_type
                },
                timeout=10
            )
        except:
            pass
        
        currency = 'USDT' if pay_type == 'deposit' else '$'
        check_data = f"check_{pay_type}_{invoice_id}"
        
        payment_text = (
            f"{S['money']} <b>СЧЁТ СОЗДАН</b>\n\n"
            f"Сумма: <code>{amount:.2f} {currency}</code>\n"
            f"ID: <code>{invoice_id}</code>\n\n"
            f"1. Нажмите <b>Оплатить</b>\n"
            f"2. Оплатите в CryptoBot\n"
            f"3. Нажмите <b>Проверить оплату</b>"
        )
        
        try:
            bot.edit_message_text(
                payment_text,
                message.chat.id,
                message.message_id,
                reply_markup=payment_keyboard(invoice_url, check_data),
                parse_mode="HTML"
            )
        except:
            bot.send_message(
                message.chat.id,
                payment_text,
                reply_markup=payment_keyboard(invoice_url, check_data),
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Create payment error: {e}")

def check_payment_status(call, pay_type, invoice_id):
    try:
        result = check_invoice(invoice_id)
        
        if not result or not result.get('ok'):
            bot.answer_callback_query(call.id, "❌ Ошибка проверки")
            return
        
        if result['result']['items'][0]['status'] == 'paid':
            user_id = call.from_user.id
            
            # Проверяем и подтверждаем в нашей системе
            try:
                inv_response = requests.get(
                    f"{API_URL}/invoice/{invoice_id}",
                    params={"user_id": user_id},
                    timeout=10
                )
                
                if inv_response.ok:
                    inv = inv_response.json()
                    if inv.get('status') != 'paid':
                        requests.post(
                            f"{API_URL}/invoice/pay",
                            json={
                                "user_id": user_id,
                                "invoice_id": invoice_id,
                                "amount": inv['amount'],
                                "pay_type": pay_type
                            },
                            timeout=10
                        )
            except:
                pass
            
            # Получаем баланс
            user_response = make_request(requests.get, f"{API_URL}/user/{user_id}")
            
            if user_response:
                data = user_response.json()
                deposit = data.get('deposit', 0)
                roulette = data.get('roulette_balance', 0)
                text = (
                    f"{S['check']} <b>ОПЛАЧЕНО!</b>\n\n"
                    f"{S['gem']} Депозит: <code>{deposit:,.2f} USDT</code>\n"
                    f"{S['game']} Казино: <code>{roulette:,.2f} $</code>"
                )
            else:
                text = f"{S['check']} <b>ОПЛАЧЕНО!</b>\nБаланс обновится автоматически."
            
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML")
        else:
            bot.answer_callback_query(call.id, "❌ Счёт не оплачен", show_alert=True)
            
    except Exception as e:
        logger.error(f"Check payment error: {e}")

# ===== ВВОД СВОЕЙ СУММЫ =====
@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) in ['waiting_dep', 'waiting_casino'])
def custom_amount(message):
    try:
        state = user_states.pop(message.from_user.id)
        
        if not state:
            return
        
        amount_str = message.text.strip().replace(',', '.')
        
        try:
            amount = float(amount_str)
        except ValueError:
            bot.send_message(message.chat.id, f"{S['error']} Введите число!")
            return
        
        if amount < 1 or amount > 10000:
            bot.send_message(message.chat.id, f"{S['error']} Сумма от 1 до 10000")
            return
        
        pay_type = 'deposit' if state == 'waiting_dep' else 'casino'
        create_payment(message.from_user.id, message, amount, pay_type)
        
    except Exception as e:
        logger.error(f"Custom amount error: {e}")

# ===== АНТИ-СОН =====
def keep_alive():
    """Анти-сон для Render"""
    urls = [
        f"https://sms-45xq.onrender.com/ping",
        f"https://sms-45xq.onrender.com/health",
        f"{API_URL}/user/{ADMIN_ID}",
    ]
    
    while True:
        try:
            for url in urls:
                try:
                    response = requests.get(url, timeout=10)
                    if response.status_code == 200:
                        logger.debug(f"✅ Ping OK: {url}")
                    else:
                        logger.warning(f"⚠️ Ping {url}: {response.status_code}")
                except Exception as e:
                    logger.warning(f"❌ Ping failed: {url}")
            
            # Проверяем бота
            try:
                bot.get_me()
            except:
                logger.error("Bot connection lost")
            
            time.sleep(600)  # Каждые 10 минут
            
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
            time.sleep(30)

# ===== ЗАПУСК =====
def run_flask():
    logger.info(f"Starting Flask on port {PORT}")
    web_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def run_bot():
    logger.info("Starting bot polling...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=30)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    print("=" * 50)
    print("  DOLIES BOT v2.0")
    print("=" * 50)
    
    # Запускаем сервисы
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Бот в главном потоке
    run_bot()
