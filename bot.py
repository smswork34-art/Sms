import telebot
from telebot import types
import requests
import time
import threading
from flask import Flask
import os
import logging
import json
from datetime import datetime, timedelta
from collections import OrderedDict

# ===== НАСТРОЙКИ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger('DoliesBot')

# Токены
TOKEN = os.environ.get('TELEGRAM_TOKEN', '8950946789:AAF9oW0piW6YbnveA7rZXiO4KiK9LLnDLEY')
CRYPTO_API = os.environ.get('CRYPTO_API', '575343:AA8lI3rebCZuc9HxysqN073qP3jLgrz2sx8')
CRYPTO_BOT_URL = "https://pay.crypt.bot/api"
API_URL = "https://dolies.pythonanywhere.com/api"
ADMIN_ID = int(os.environ.get('ADMIN_ID', '7518728008'))
PORT = int(os.environ.get('PORT', 10000))

# ===== FLASK ДЛЯ RENDER =====
web_app = Flask(__name__)

@web_app.route('/')
def index():
    return f'DOLIES Bot is running! 🚀\nTime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', 200

@web_app.route('/health')
def health():
    return json.dumps({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'uptime': time.time() - start_time
    }), 200

@web_app.route('/ping')
def ping():
    try:
        me = bot.get_me()
        return json.dumps({
            'ok': True,
            'bot_username': me.username,
            'bot_id': me.id,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Ping check failed: {e}")
        return json.dumps({'ok': False, 'error': str(e)}), 500

# ===== БОТ (исправленная строка) =====
bot = telebot.TeleBot(TOKEN, threaded=True)
bot.remove_webhook()
logger.info("✅ Webhook removed, using polling mode")

# Дальше весь код без изменений...

# ===== КЭШ СОСТОЯНИЙ ПОЛЬЗОВАТЕЛЕЙ =====
class UserStateCache:
    """Потокобезопасный кэш состояний с автоочисткой"""
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
            # Очищаем старые если лимит
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
        """Принудительная очистка старых записей"""
        with self.lock:
            cutoff = datetime.now() - timedelta(minutes=self.max_age)
            self.cache = OrderedDict(
                (k, v) for k, v in self.cache.items() 
                if v[1] > cutoff
            )
            logger.debug(f"Cache cleaned: {len(self.cache)} active states")

user_states = UserStateCache()

# ===== ЭМОДЗИ =====
S = {
    'gem': '◇', 'game': '◎', 'wallet': '◻', 'check': '✓', 
    'cross': '✗', 'star': '★', 'refresh': '↻', 'crown': '♛', 
    'globe': '◎', 'pen': '✎', 'dot': '·', 'rocket': '🚀',
    'money': '💎', 'error': '⚠️', 'lock': '🔒'
}

# ===== СЛУЖЕБНЫЕ ФУНКЦИИ =====
class RequestHandler:
    """Обработчик HTTP запросов с ретраями"""
    
    @staticmethod
    def request(method, url, max_retries=3, **kwargs):
        """Выполняет запрос с автоматическими повторными попытками"""
        timeout = kwargs.pop('timeout', 15)
        
        for attempt in range(max_retries):
            try:
                response = method(url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout for {url} (attempt {attempt + 1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error for {url} (attempt {attempt + 1}/{max_retries})")
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP error for {url}: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error for {url}: {e}")
                return None
            
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))  # Прогрессивная задержка
        
        logger.error(f"All retries failed for {url}")
        return None
    
    @staticmethod
    def get(url, **kwargs):
        return RequestHandler.request(requests.get, url, **kwargs)
    
    @staticmethod
    def post(url, **kwargs):
        return RequestHandler.request(requests.post, url, **kwargs)

req = RequestHandler()

def create_invoice(amount):
    """Создание инвойса в CryptoPay"""
    url = f"{CRYPTO_BOT_URL}/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    data = {
        "asset": "USDT",
        "amount": str(amount),
        "description": f"DOLIES: Пополнение на {amount} USDT",
        "paid_btn_name": "callback",
        "paid_btn_url": "https://t.me/dolies_bot"
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        if not response.ok:
            logger.error(f"CryptoPay error: {response.status_code} - {response.text}")
            return None
        
        result = response.json()
        if not result.get('ok'):
            logger.error(f"CryptoPay API error: {result.get('error')}")
            return None
        
        return result
    except Exception as e:
        logger.error(f"Create invoice exception: {e}")
        return None

def check_invoice(invoice_id):
    """Проверка статуса инвойса"""
    url = f"{CRYPTO_BOT_URL}/getInvoices"
    headers = {"Crypto-Pay-API-Token": CRYPTO_API}
    
    try:
        response = requests.get(
            url, 
            headers=headers, 
            params={"invoice_ids": invoice_id},
            timeout=10
        )
        if not response.ok:
            return None
        
        return response.json()
    except Exception as e:
        logger.error(f"Check invoice error: {e}")
        return None

def verify_payment(invoice_id, user_id, pay_type):
    """
    Проверяет и подтверждает платеж.
    Возвращает True если платеж успешно обработан
    """
    try:
        # Проверяем статус в CryptoPay
        crypto_result = check_invoice(invoice_id)
        if not crypto_result or not crypto_result.get('ok'):
            return False
        
        if crypto_result['result']['items'][0]['status'] != 'paid':
            return False
        
        # Проверяем статус в нашей системе
        inv_response = req.get(f"{API_URL}/invoice/{invoice_id}", params={"user_id": user_id})
        if not inv_response:
            return False
        
        inv_data = inv_response.json()
        
        # Если еще не отмечен как оплаченный
        if inv_data.get('status') != 'paid':
            pay_response = req.post(
                f"{API_URL}/invoice/pay",
                json={
                    "user_id": user_id,
                    "invoice_id": invoice_id,
                    "amount": inv_data['amount'],
                    "pay_type": pay_type
                }
            )
            
            if not pay_response or not pay_response.ok:
                logger.error(f"Failed to mark invoice as paid: {invoice_id}")
                return False
            
            logger.info(f"✅ Payment verified: user={user_id}, amount={inv_data['amount']}, type={pay_type}")
        
        return True
        
    except Exception as e:
        logger.error(f"Verify payment error: {e}")
        return False

# ===== КЛАВИАТУРЫ =====
def main_keyboard():
    """Главная клавиатура"""
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
    """Клавиатура выбора суммы"""
    currency = 'USDT' if prefix == 'dep' else '$'
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    for amount in [10, 25, 50, 100, 500]:
        markup.add(types.InlineKeyboardButton(
            f"{amount} {currency}",
            callback_data=f"{prefix}_{amount}"
        ))
    
    markup.add(
        types.InlineKeyboardButton(
            f"{S['pen']} Своя сумма", 
            callback_data=f"{prefix}_custom"
        ),
        types.InlineKeyboardButton(
            f"{S['cross']} Отмена", 
            callback_data=f"{prefix}_cancel"
        )
    )
    return markup

def payment_keyboard(invoice_url, check_data):
    """Клавиатура для оплаты"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        f"{S['money']} Оплатить", 
        url=invoice_url
    ))
    markup.add(types.InlineKeyboardButton(
        f"{S['refresh']} Проверить оплату", 
        callback_data=check_data
    ))
    return markup

# ===== ОБРАБОТЧИКИ КОМАНД =====
@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик /start"""
    try:
        user = message.from_user
        logger.info(f"User {user.id} (@{user.username}) started bot")
        
        welcome_text = (
            f"{S['rocket']} <b>DOLIES COMPANY</b> {S['rocket']}\n\n"
            f"{S['star']} Добро пожаловать, {user.first_name}!\n\n"
            f"{S['dot']} Выберите действие в меню ниже:"
        )
        
        bot.send_message(
            message.chat.id,
            welcome_text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in start: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Попробуйте /start")

@bot.message_handler(commands=['help'])
def help_command(message):
    """Справка"""
    help_text = (
        f"{S['crown']} <b>ПОМОЩЬ</b>\n\n"
        f"{S['gem']} <b>Депозит</b> - пополнение в USDT\n"
        f"{S['game']} <b>Казино</b> - игровой баланс\n"
        f"{S['wallet']} <b>Баланс</b> - проверка счетов\n"
        f"{S['globe']} <b>Приложение</b> - веб-версия\n\n"
        f"{S['dot']} По вопросам: @support"
    )
    bot.send_message(message.chat.id, help_text, parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text and "Пополнить депозит" in m.text)
def deposit_start(message):
    """Начало пополнения депозита"""
    try:
        bot.send_message(
            message.chat.id,
            f"{S['gem']} <b>ПОПОЛНЕНИЕ ДЕПОЗИТА</b>\n\n"
            f"{S['dot']} Выберите сумму <b>USDT</b>\n"
            f"{S['dot']} Или введите свою сумму",
            reply_markup=amounts_keyboard('dep'),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Deposit start error: {e}")

@bot.message_handler(func=lambda m: m.text and "Пополнить казино" in m.text)
def casino_start(message):
    """Начало пополнения казино"""
    try:
        bot.send_message(
            message.chat.id,
            f"{S['game']} <b>ПОПОЛНЕНИЕ КАЗИНО</b>\n\n"
            f"{S['dot']} Выберите сумму <b>$</b>\n"
            f"{S['dot']} Или введите свою сумму",
            reply_markup=amounts_keyboard('casino'),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Casino start error: {e}")

@bot.message_handler(func=lambda m: m.text and "Баланс" in m.text)
def check_balance(message):
    """Проверка баланса"""
    try:
        user_id = message.from_user.id
        
        # Запрашиваем баланс
        response = req.get(f"{API_URL}/user/{user_id}")
        
        if not response:
            raise Exception("API unavailable")
        
        data = response.json()
        deposit = data.get('deposit', 0)
        roulette = data.get('roulette_balance', 0)
        
        balance_text = (
            f"{S['wallet']} <b>ВАШ БАЛАНС</b>\n\n"
            f"{S['gem']} Депозит: <code>{deposit:,.2f} USDT</code>\n"
            f"{S['game']} Казино: <code>{roulette:,.2f} $</code>\n\n"
            f"{S['dot']} Для пополнения используйте кнопки ниже"
        )
        
        bot.send_message(
            message.chat.id,
            balance_text,
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Balance check error: {e}")
        bot.send_message(
            message.chat.id,
            f"{S['error']} Не удалось получить баланс. Попробуйте позже.",
            reply_markup=main_keyboard()
        )

@bot.message_handler(func=lambda m: m.text and "Приложение" in m.text)
def open_miniapp(message):
    """Открытие веб-приложения"""
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            f"{S['rocket']} Открыть DOLIES",
            web_app=types.WebAppInfo(url="https://dolies.pythonanywhere.com")
        ))
        
        bot.send_message(
            message.chat.id,
            f"{S['globe']} Нажмите кнопку ниже чтобы открыть приложение:",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Miniapp error: {e}")

# ===== ОБРАБОТЧИК CALLBACK =====
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Единый обработчик всех callback запросов"""
    try:
        data = call.data
        user_id = call.from_user.id
        logger.info(f"Callback: {data} | User: {user_id}")
        
        # Обработка отмены
        if data.endswith('_cancel'):
            handle_cancel(call)
            return
        
        # Обработка ввода своей суммы
        if data.endswith('_custom'):
            handle_custom_amount(call)
            return
        
        # Обработка выбора суммы
        if data.startswith(('dep_', 'casino_')):
            handle_amount_selection(call)
            return
        
        # Обработка проверки платежа
        if data.startswith('check_'):
            handle_payment_check(call)
            return
        
        # Неизвестный callback
        bot.answer_callback_query(call.id, "Неизвестная команда")
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка")
        except:
            pass

def handle_cancel(call):
    """Обработка отмены"""
    try:
        bot.edit_message_text(
            f"{S['cross']} Операция отменена",
            call.message.chat.id,
            call.message.message_id
        )
        bot.answer_callback_query(call.id)
    except:
        pass

def handle_custom_amount(call):
    """Запрос своей суммы"""
    try:
        prefix = call.data.split('_')[0]
        user_states.set(call.from_user.id, f'waiting_{prefix}')
        
        currency = 'USDT' if prefix == 'dep' else '$'
        
        bot.edit_message_text(
            f"{S['pen']} <b>ВВЕДИТЕ СУММУ</b>\n\n"
            f"Валюта: <b>{currency}</b>\n"
            f"Диапазон: от 1 до 10 000\n\n"
            f"{S['dot']} Отправьте число в чат:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )
        bot.answer_callback_query(call.id)
    except Exception as e:
        logger.error(f"Custom amount error: {e}")

def handle_amount_selection(call):
    """Обработка выбранной суммы"""
    try:
        parts = call.data.split('_')
        prefix = parts[0]
        amount = float(parts[1])
        
        pay_type = 'deposit' if prefix == 'dep' else 'casino'
        
        # Создаем платеж
        process_new_payment(call.from_user.id, call.message, amount, pay_type)
        bot.answer_callback_query(call.id)
        
    except (ValueError, IndexError) as e:
        logger.error(f"Amount selection error: {e}")
        bot.answer_callback_query(call.id, "Неверная сумма")

def process_new_payment(user_id, message, amount, pay_type):
    """Создание нового платежа"""
    try:
        # Создаем инвойс
        invoice = create_invoice(amount)
        
        if not invoice:
            raise Exception("Failed to create invoice")
        
        invoice_url = invoice['result']['pay_url']
        invoice_id = invoice['result']['invoice_id']
        
        # Регистрируем в нашей системе
        try:
            reg_response = req.post(
                f"{API_URL}/invoice/create",
                json={
                    "user_id": user_id,
                    "invoice_id": invoice_id,
                    "amount": amount,
                    "pay_type": pay_type
                }
            )
            if not reg_response:
                logger.warning(f"Invoice registration failed for {invoice_id}")
        except Exception as e:
            logger.error(f"Invoice registration error: {e}")
        
        # Отправляем сообщение с оплатой
        currency = 'USDT' if pay_type == 'deposit' else '$'
        check_data = f"check_{pay_type}_{invoice_id}"
        
        payment_text = (
            f"{S['money']} <b>СЧЁТ СОЗДАН</b>\n\n"
            f"Сумма: <code>{amount:.2f} {currency}</code>\n"
            f"ID: <code>{invoice_id}</code>\n\n"
            f"{S['dot']} 1. Нажмите <b>Оплатить</b>\n"
            f"{S['dot']} 2. Оплатите в CryptoBot\n"
            f"{S['dot']} 3. Нажмите <b>Проверить оплату</b>"
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
            # Если не можем отредактировать, отправляем новое
            bot.send_message(
                message.chat.id,
                payment_text,
                reply_markup=payment_keyboard(invoice_url, check_data),
                parse_mode="HTML"
            )
        
        logger.info(f"✅ Invoice created: {invoice_id} | User: {user_id} | Amount: {amount} {currency}")
        
    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        try:
            bot.send_message(
                message.chat.id,
                f"{S['error']} Не удалось создать счёт. Попробуйте позже."
            )
        except:
            pass

def handle_payment_check(call):
    """Проверка статуса платежа"""
    try:
        parts = call.data.split('_')
        pay_type = parts[1]
        invoice_id = parts[2]
        user_id = call.from_user.id
        
        # Показываем что проверяем
        bot.answer_callback_query(call.id, "🔄 Проверяю платёж...")
        
        # Проверяем платеж
        if verify_payment(invoice_id, user_id, pay_type):
            # Получаем обновленный баланс
            user_response = req.get(f"{API_URL}/user/{user_id}")
            
            if user_response:
                data = user_response.json()
                deposit = data.get('deposit', 0)
                roulette = data.get('roulette_balance', 0)
                
                success_text = (
                    f"{S['check']} <b>ОПЛАЧЕНО!</b>\n\n"
                    f"{S['gem']} Депозит: <code>{deposit:,.2f} USDT</code>\n"
                    f"{S['game']} Казино: <code>{roulette:,.2f} $</code>\n\n"
                    f"{S['rocket']} Баланс обновлён!"
                )
            else:
                success_text = f"{S['check']} <b>ОПЛАЧЕНО!</b>\n\nБаланс обновится автоматически."
            
            bot.edit_message_text(
                success_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML"
            )
        else:
            bot.answer_callback_query(
                call.id,
                f"{S['cross']} Платёж ещё не получен. Попробуйте позже.",
                show_alert=True
            )
            
    except Exception as e:
        logger.error(f"Payment check error: {e}")
        try:
            bot.answer_callback_query(call.id, "Ошибка проверки платежа")
        except:
            pass

# ===== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ =====
@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) in ['waiting_dep', 'waiting_casino'])
def handle_custom_amount_input(message):
    """Обработка ввода своей суммы"""
    try:
        state = user_states.pop(message.from_user.id)
        
        if not state:
            return
        
        # Парсим сумму
        amount_str = message.text.strip().replace(',', '.')
        
        try:
            amount = float(amount_str)
        except ValueError:
            bot.send_message(
                message.chat.id,
                f"{S['error']} Пожалуйста, введите число!\nНапример: 100 или 50.5"
            )
            return
        
        # Проверяем диапазон
        if amount < 1 or amount > 10000:
            bot.send_message(
                message.chat.id,
                f"{S['error']} Сумма должна быть от 1 до 10 000"
            )
            return
        
        # Определяем тип платежа
        pay_type = 'deposit' if state == 'waiting_dep' else 'casino'
        
        # Создаем платеж
        process_new_payment(message.from_user.id, message, amount, pay_type)
        
    except Exception as e:
        logger.error(f"Custom amount input error: {e}")
        bot.send_message(message.chat.id, f"{S['error']} Произошла ошибка")

# ===== АНТИ-СОН =====
def keep_alive():
    """Продвинутый анти-сон для Render"""
    
    # URL для пинга
    urls = [
        "https://sms-45xq.onrender.com/ping",
        "https://sms-45xq.onrender.com/health",
        f"{API_URL}/user/{ADMIN_ID}",
    ]
    
    # Статистика
    stats = {'success': 0, 'fail': 0, 'last_success': None}
    
    while True:
        try:
            for url in urls:
                try:
                    start = time.time()
                    response = requests.get(url, timeout=10)
                    elapsed = time.time() - start
                    
                    if response.status_code == 200:
                        stats['success'] += 1
                        stats['last_success'] = datetime.now()
                        logger.debug(f"✅ Ping OK: {url} ({elapsed:.2f}s)")
                    else:
                        stats['fail'] += 1
                        logger.warning(f"⚠️ Ping {url}: {response.status_code}")
                        
                except Exception as e:
                    stats['fail'] += 1
                    logger.warning(f"❌ Ping failed: {url} - {str(e)[:50]}")
            
            # Проверяем что бот жив
            try:
                bot.get_me()
                logger.debug("Bot connection OK")
            except Exception as e:
                logger.error(f"Bot connection lost: {e}")
            
            # Каждые 100 пингов показываем статистику
            if (stats['success'] + stats['fail']) % 100 == 0:
                logger.info(
                    f"📊 Keep-alive stats: "
                    f"Success={stats['success']}, "
                    f"Fail={stats['fail']}, "
                    f"Last success={stats['last_success']}"
                )
            
            # Пинг каждые 10 минут (Render засыпает через 15)
            time.sleep(600)
            
        except Exception as e:
            logger.error(f"Keep-alive critical error: {e}")
            time.sleep(30)

# ===== ОЧИСТКА КЭША =====
def cache_cleaner():
    """Периодическая очистка кэша состояний"""
    while True:
        time.sleep(1800)  # Каждые 30 минут
        user_states.clean()
        logger.debug("Cache cleaned")

# ===== ЗАПУСК =====
start_time = time.time()

def run_flask():
    """Запуск Flask сервера"""
    logger.info(f"Starting Flask on port {PORT}")
    web_app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

def run_bot():
    """Запуск бота с автоматическим восстановлением"""
    logger.info("Starting bot polling...")
    
    while True:
        try:
            bot.polling(
                none_stop=True,
                interval=0,
                timeout=30,
                long_polling_timeout=30
            )
        except requests.exceptions.ReadTimeout:
            logger.warning("Polling timeout, restarting...")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)
            logger.info("Restarting bot polling...")

if __name__ == '__main__':
    print("=" * 50)
    print(f"  DOLIES BOT v2.0")
    print(f"  Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    # Запускаем все сервисы в отдельных потоках
    services = [
        threading.Thread(target=keep_alive, daemon=True, name="KeepAlive"),
        threading.Thread(target=cache_cleaner, daemon=True, name="CacheCleaner"),
        threading.Thread(target=run_flask, daemon=True, name="Flask"),
    ]
    
    for service in services:
        service.start()
        logger.info(f"Started {service.name} thread")
    
    # Бот в главном потоке
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
