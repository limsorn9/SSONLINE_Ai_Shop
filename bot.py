import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import requests
import os
import time
import sqlite3
import uuid
from flask import Flask, request

# ================= ការកំណត់ទូទៅ (Config) =================
TELEGRAM_BOT_TOKEN = os.environ.get('BOT_TOKEN', 'YOUR_TELEGRAM_TOKEN_HERE')
ZOOM_API_KEY = os.environ.get('ZOOM_API_KEY', 'mk_ec260365_329361fe5240beacde3b4a500a02369b')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '') 

ZOOM_BASE_URL = "https://api.zoomstore255.com/api/v1"
ADMIN_ID = 240224709 # Default admin ID

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
app = Flask(__name__)

# ================= ប្រព័ន្ធទិន្នន័យ (Database) =================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER, 
                    type TEXT, 
                    amount REAL, 
                    description TEXT, 
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def log_transaction(user_id, trans_type, amount, description):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)", (user_id, trans_type, amount, description))
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0.0

def add_user_balance(user_id, amount):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?", (user_id, amount, amount))
    conn.commit()
    conn.close()
    log_transaction(user_id, "TOPUP", amount, "បញ្ជូលលុយ")

def deduct_user_balance(user_id, amount, desc):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    if not result or result[0] < amount:
        conn.close()
        return False
    c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()
    log_transaction(user_id, "BUY", amount, desc)
    return True

init_db()

# ================= ជំនួយការ API (API Helpers) =================
def get_zoom_headers():
    return {"X-API-Key": ZOOM_API_KEY}

def call_zoom_api(method, endpoint, json_data=None, extra_headers=None):
    url = f"{ZOOM_BASE_URL}{endpoint}"
    headers = get_zoom_headers()
    if extra_headers:
        headers.update(extra_headers)
        
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=15)
        else:
            resp = requests.post(url, headers=headers, json=json_data, timeout=30)
            
        if resp.status_code == 429: # Rate Limited
            time.sleep(2) # Simple backoff
            return call_zoom_api(method, endpoint, json_data, extra_headers)
            
        return resp.json()
    except Exception as e:
        return {"success": False, "code": "NETWORK_ERROR", "message": str(e)}

# ================= មុខងារ Bot (Bot Handlers) =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("🛒 មើលទំនិញ (Shop)"), KeyboardButton("👤 គណនី (Info)"))
    bot.send_message(message.chat.id, "👋 សួស្តី! សូមស្វាគមន៍មកកាន់ Zoom Store Bot!", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "👤 គណនី (Info)" or m.text == "/info")
def show_info(message):
    user_id = message.from_user.id
    
    if user_id == ADMIN_ID:
        api_res = call_zoom_api("GET", "/balance")
        real_bal = api_res.get('balance', 0.0) if 'balance' in api_res else 0.0
        currency = api_res.get('currency', 'USDT')
        
        msg = (f"👑 **ព័ត៌មាន Admin:**\n\n"
               f"🆔 **Telegram ID:** `{user_id}`\n"
               f"🏦 **លុយក្នុង Zoom API:** {real_bal:.2f} {currency}\n\n"
               f"👉 វាយបញ្ជាខាងក្រោមដើម្បីគ្រប់គ្រងអតិថិជន៖\n"
               f"1. បញ្ចូលលុយ ៖ `/addmoney [ID] [លុយ]`\n"
               f"2. ដកលុយវិញ ៖ `/removemoney [ID] [លុយ]`\n"
               f"3. ឆែកលុយភ្ញៀវ៖ `/checkuser [ID]`\n"
               f"4. ឆែកប្រវត្តិទិញ៖ `/history [ID]`")
    else:
        balance = get_user_balance(user_id)
        msg = (f"👤 **ព័ត៌មានគណនីរបស់អ្នក:**\n\n"
               f"🆔 **ID របស់អ្នក:** `{user_id}`\n"
               f"👛 **ទឹកប្រាក់មាន:** `${balance:.2f}`\n\n"
               f"👉 (សូមទាក់ទង Admin ដើម្បីបញ្ចូលលុយ)")
               
    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🛒 មើលទំនិញ (Shop)" or m.text == "/shop")
def show_shop(message):
    bot.send_message(message.chat.id, "កំពុងទាញយកទិន្នន័យទំនិញពី Zoom Store... ⏳")
    
    res = call_zoom_api("GET", "/products")
    products = res.get('products', [])
    
    if not products:
        bot.send_message(message.chat.id, "❌ មិនមានទំនិញលក់ទេនៅពេលនេះ!")
        return
        
    list_text = ""
    for p in products:
        p_id = p.get('id')
        name = p.get('name')
        price = float(p.get('price', 0))
        stock = p.get('stock', 0)
        
        # TODO: បន្ថែមរូបមន្តគណនាតម្លៃលក់ចេញនៅទីនេះ បើបងចង់បាន
        sell_price = price 
        
        list_text += f"👉 /buy\_{p_id} : 📦 {name} | 💵 **${sell_price:.2f}** | 📦 {stock}\n"
        
    # Telegram អនុញ្ញាតអក្សរយ៉ាងច្រើន ៤០៩៦ តួអក្សរក្នុងមួយសារ
    # យើងត្រូវកាត់ផ្តាច់វាបើវាវែងពេក
    messages_to_send = []
    chunk = ""
    lines = list_text.strip().split('\n')
    for line in lines:
        if len(chunk) + len(line) + 2 > 4000:
            messages_to_send.append(chunk)
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk:
        messages_to_send.append(chunk)
        
    bot.send_message(message.chat.id, f"📂 **បញ្ជីទំនិញទាំងអស់ ({len(products)} មុខ):**", parse_mode="Markdown")
    for i, msg in enumerate(messages_to_send):
        if i == len(messages_to_send) - 1:
            msg += "\n📌 *ចុចលើលេខកូដបញ្ជាពណ៌ខៀវខាងលើ ដើម្បីទិញទំនិញ!*"
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text and message.text.startswith('/buy_'))
def handle_buy_command(message):
    try:
        product_id = message.text.split('_')[1].strip()
    except:
        return
        
    user_id = message.from_user.id
    bot.send_message(message.chat.id, "កំពុងដំណើរការទិញ... សូមរង់ចាំ! ⏳")
    
    # 1. ស្វែងរកតម្លៃដើមពី API
    res = call_zoom_api("GET", "/products")
    products = res.get('products', [])
    
    target_product = next((p for p in products if str(p.get('id')) == product_id), None)
    if not target_product:
        bot.send_message(message.chat.id, "❌ រកមិនឃើញទំនិញនេះទេ!")
        return
        
    original_price = float(target_product.get('price', 0))
    sell_price = original_price # TODO: កែប្រែរូបមន្តតម្លៃ
    
    # 2. កាត់លុយ
    if user_id != ADMIN_ID:
        user_balance = get_user_balance(user_id)
        if user_balance < sell_price:
            bot.send_message(message.chat.id, f"❌ លុយរបស់អ្នកមិនគ្រប់គ្រាន់ទេ! (មានតែ ${user_balance:.2f})")
            return
        if not deduct_user_balance(user_id, sell_price, f"ទិញទំនិញ Zoom: {product_id}"):
            bot.send_message(message.chat.id, "❌ មានបញ្ហាក្នុងការកាត់ប្រាក់!")
            return
            
    # 3. ធ្វើការបញ្ជាទិញតាម API
    idempotency_key = str(uuid.uuid4())
    payload = {"product_id": product_id, "quantity": 1}
    headers = {"Idempotency-Key": idempotency_key}
    
    buy_res = call_zoom_api("POST", "/purchase", json_data=payload, extra_headers=headers)
    
    if buy_res.get('success'):
        codes = buy_res.get('codes', [])
        codes_str = "\n".join([f"`{c}`" for c in codes])
        
        msg = (f"✅ **ការបញ្ជាទិញជោគជ័យ!**\n\n"
               f"📦 ទំនិញ: {target_product.get('name')}\n"
               f"🔑 **ទិន្នន័យរបស់អ្នក:**\n{codes_str}\n\n")
        if user_id != ADMIN_ID:
            msg += f"💰 លុយនៅសល់: `${get_user_balance(user_id):.2f}`"
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    else:
        # បង្វិលលុយវិញ
        if user_id != ADMIN_ID:
            add_user_balance(user_id, sell_price)
            
        error_code = buy_res.get('code')
        if error_code == "INSUFFICIENT_BALANCE":
            err_msg = "❌ លុយនៅក្នុងកុង API (Zoom Store) មិនគ្រប់គ្រាន់ទេ! សូមប្រាប់ Admin ឲ្យបញ្ជូលលុយ។"
        elif error_code == "OUT_OF_STOCK":
            err_msg = "❌ ទំនិញនេះអស់ពីស្តុកហើយ!"
        elif error_code == "PRODUCT_NOT_FOUND":
            err_msg = "❌ រកមិនឃើញទំនិញនេះក្នុងប្រព័ន្ធទេ។"
        else:
            err_msg = f"❌ បរាជ័យក្នុងការទិញ! (Code: {error_code})"
            
        bot.send_message(message.chat.id, err_msg)

# ================= Admin Commands =================
# (អក្សរកាត់សម្រាប់ Admin Command ដែលឲ្យចុចវាយបញ្ចូល)
@bot.message_handler(commands=['addmoney', 'removemoney', 'checkuser', 'history'])
def handle_admin_commands(message):
    if message.from_user.id != ADMIN_ID: return
    cmd = message.text.split()[0]
    parts = message.text.split()
    
    if cmd == '/addmoney':
        if len(parts) == 3: process_add_money(message, parts[1], parts[2])
        else:
            msg = bot.reply_to(message, "📝 សូមបញ្ចូល **[IDភ្ញៀវ]** និង **[ចំនួនលុយ]** ៖", parse_mode="Markdown")
            bot.register_next_step_handler(msg, lambda m: process_add_money(m, *m.text.split()[:2]) if len(m.text.split())>=2 else bot.reply_to(m,"❌ ខុសទម្រង់"))
            
    elif cmd == '/removemoney':
        if len(parts) == 3: process_remove_money(message, parts[1], parts[2])
        else:
            msg = bot.reply_to(message, "📝 សូមបញ្ចូល **[IDភ្ញៀវ]** និង **[ចំនួនលុយ]** ដែលត្រូវដក៖", parse_mode="Markdown")
            bot.register_next_step_handler(msg, lambda m: process_remove_money(m, *m.text.split()[:2]) if len(m.text.split())>=2 else bot.reply_to(m,"❌ ខុសទម្រង់"))

def process_add_money(message, u_id, amt):
    try:
        user_id, amount = int(u_id), float(amt)
        add_user_balance(user_id, amount)
        bot.reply_to(message, f"✅ បានបញ្ចូលលុយ `${amount:.2f}` ទៅឲ្យ ID: `{user_id}` ជោគជ័យ!")
    except:
        bot.reply_to(message, "⚠️ ទម្រង់ខុស!")

def process_remove_money(message, u_id, amt):
    try:
        user_id, amount = int(u_id), float(amt)
        if deduct_user_balance(user_id, amount, "ដកលុយដោយ Admin"):
            bot.reply_to(message, f"✅ បានដកលុយ `${amount:.2f}` ពី ID: `{user_id}` ជោគជ័យ!")
        else:
            bot.reply_to(message, "❌ ភ្ញៀវមានលុយមិនគ្រប់!")
    except:
        bot.reply_to(message, "⚠️ ទម្រង់ខុស!")

# ================= Webhook & Flask =================
@app.route('/' + TELEGRAM_BOT_TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@app.route("/")
def webhook():
    return "Zoom Store Bot is running!", 200

if __name__ == '__main__':
    bot.remove_webhook()
    if WEBHOOK_URL:
        bot.set_webhook(url=WEBHOOK_URL + '/' + TELEGRAM_BOT_TOKEN)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
