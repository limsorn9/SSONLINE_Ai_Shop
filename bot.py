import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import requests
import os
import time
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db as rtdb
import datetime
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

import threading

def delete_msg(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass

def temp_send_message(chat_id, text, **kwargs):
    msg = bot.send_message(chat_id, text, **kwargs)
    threading.Timer(60.0, delete_msg, args=(chat_id, msg.message_id)).start()
    return msg

def temp_reply_to(message, text, **kwargs):
    msg = bot.reply_to(message, text, **kwargs)
    threading.Timer(60.0, delete_msg, args=(message.chat.id, msg.message_id)).start()
    try:
        threading.Timer(60.0, delete_msg, args=(message.chat.id, message.message_id)).start()
    except:
        pass
    return msg

# ================= ប្រព័ន្ធទិន្នន័យ (Database - Firebase) =================
try:
    if not firebase_admin._apps:
        firebase_cred_json = os.environ.get('FIREBASE_CRED_JSON')
        if firebase_cred_json:
            import json
            cred_dict = json.loads(firebase_cred_json)
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.Certificate('firebase_key.json')
        db_url = os.environ.get('FIREBASE_DATABASE_URL')
        if db_url:
            firebase_admin.initialize_app(cred, {
                'databaseURL': db_url
            })
        else:
            firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Init Error: {e}")

def log_transaction(user_id, trans_type, amount, description):
    try:
        ref = rtdb.reference('transactions')
        ref.push({
            'user_id': user_id,
            'type': trans_type,
            'amount': amount,
            'description': description,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
    except Exception as e:
        print(e)

def get_user_balance(user_id):
    try:
        ref = rtdb.reference(f'users/{user_id}')
        user = ref.get()
        if user and 'balance' in user:
            return float(user['balance'])
    except Exception as e:
        print(e)
    return 0.0

def add_user_balance(user_id, amount):
    try:
        ref = rtdb.reference(f'users/{user_id}')
        user = ref.get()
        if user:
            current_balance = float(user.get('balance', 0.0))
            ref.update({'balance': current_balance + amount})
        else:
            ref.set({'balance': amount, 'group': 'member'})
        log_transaction(user_id, "TOPUP", amount, "បញ្ជូលលុយ")
    except Exception as e:
        print(e)

def deduct_user_balance(user_id, amount, desc):
    try:
        ref = rtdb.reference(f'users/{user_id}')
        user = ref.get()
        if user:
            current_balance = float(user.get('balance', 0.0))
            if current_balance >= amount:
                ref.update({'balance': current_balance - amount})
                log_transaction(user_id, "BUY", amount, desc)
                return True
    except Exception as e:
        print(e)
    return False

def check_and_add_receipt(user_id, file_unique_id):
    try:
        ref = rtdb.reference(f'receipts/{file_unique_id}')
        if ref.get():
            return True # Already exists
        ref.set({
            'user_id': user_id,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
    except Exception as e:
        print(e)
    return False

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

def safe_float(val):
    try:
        return float(val)
    except:
        return 0.0

def calculate_sell_price(original_price):
    if original_price < 3.0:
        return original_price * 3.0
    else:
        return original_price * 2.0

def get_product_group(product_name, category_keywords):
    name_lower = product_name.lower()
    for kw in category_keywords:
        if kw in name_lower:
            return kw.capitalize()
    return product_name.split()[0].capitalize() if product_name else "Other"

# ================= មុខងារ Bot (Bot Handlers) =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    from telebot.types import ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("🛒 មើលទំនិញ (Shop)", callback_data="cmd_shop"), 
               InlineKeyboardButton("👤 គណនី (Info)", callback_data="cmd_info"))
    markup.row(InlineKeyboardButton("🏦 បញ្ចូលប្រាក់ (Topup)", callback_data="cmd_topup"))
    
    # We still send ReplyKeyboardRemove just in case they had the old big keyboard stuck
    bot.send_message(message.chat.id, "👋 សួស្តី! សូមស្វាគមន៍មកកាន់ SSONLINE AI SHOP Bot!\n\n👉 សូមចុចលើប៊ូតុងខាងក្រោម ដើម្បីចាប់ផ្តើម៖", reply_markup=markup, parse_mode="Markdown")
    # Also send a hidden message to remove the old big keyboard if it exists
    msg = bot.send_message(message.chat.id, "កំពុងរៀបចំប្រព័ន្ធ...", reply_markup=ReplyKeyboardRemove())
    bot.delete_message(message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data in ["cmd_shop", "cmd_info", "cmd_topup"])
def handle_inline_menu(call):
    bot.answer_callback_query(call.id)
    # Simulate a message object
    call.message.from_user = call.from_user
    if call.data == "cmd_shop":
        call.message.text = "/shop"
        show_shop(call.message)
    elif call.data == "cmd_info":
        show_info(call.message)
    elif call.data == "cmd_topup":
        handle_topup(call.message)

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
               f"👉 ចុចបញ្ជាខាងក្រោមដើម្បីគ្រប់គ្រងអតិថិជន៖\n"
               f"1. បញ្ចូលលុយ ៖ /addmoney\n"
               f"2. ដកលុយវិញ ៖ /removemoney\n"
               f"3. ឆែកលុយភ្ញៀវ៖ /checkuser\n"
               f"4. ឆែកប្រវត្តិទិញ៖ /history")
    else:
        balance = get_user_balance(user_id)
        msg = (f"👤 **ព័ត៌មានគណនីរបស់អ្នក:**\n\n"
               f"🆔 **ID របស់អ្នក:** `{user_id}`\n"
               f"👛 **ទឹកប្រាក់មាន:** `${balance:.2f}`\n\n"
               f"🏦 **របៀបបញ្ចូលលុយ (Binance Pay) ៖**\n"
               f"1️⃣ បាញ់លុយទៅកាន់ Binance ID: `832944944`\n"
               f"2️⃣ ថតវិក័យប័ត្រ (Screenshot) ផ្ញើមកកាន់ Admin\n"
               f"3️⃣ ភ្ជាប់ជាមួយលេខ ID របស់អ្នក (`{user_id}`) ឲ្យ Admin ដើម្បីបញ្ចូលលុយចូលកាបូប!")
    temp_send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['topup'])
def handle_topup(message):
    user_id = message.from_user.id
    msg = (f"🏦 **របៀបបញ្ចូលលុយ (Binance Pay) ៖**\n\n"
           f"បងអាចបញ្ចូលលុយបាន ២ របៀប៖\n"
           f"1️⃣ **បាញ់តាម Binance ID:** `832944944`\n"
           f"2️⃣ **ឬ Scan QR Code ខាងលើ**\n\n"
           f"📸 ពេលបាញ់រួច សូមថតវិក័យប័ត្រ (Screenshot)\n"
           f"រួចផ្ញើ (Upload) រូបនោះចូលមកក្នុង Bot នេះផ្ទាល់ នោះ Admin នឹងទទួលបាន និងបញ្ជូលលុយឲ្យបងភ្លាម!\n\n"
           f"💡 _ចំណាំ៖ ប្រសិនបើបងចង់បញ្ចូលប្រាក់តាម **KHQR (ធនាគារខ្មែរ)** សូមធ្វើការឆាតទៅកាន់ Admin ផ្ទាល់!_")
           
    try:
        with open('qr_binance.png', 'rb') as photo:
            msg_obj = bot.send_photo(message.chat.id, photo, caption=msg, parse_mode="Markdown")
            threading.Timer(60.0, delete_msg, args=(message.chat.id, msg_obj.message_id)).start()
    except:
        temp_send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(content_types=['photo'])
def handle_receipt_photo(message):
    user_id = message.from_user.id
    if user_id == ADMIN_ID: return # Admin អត់បាច់ផ្ញើវិក័យបត្រទេ
    
    file_unique_id = message.photo[-1].file_unique_id
    file_id = message.photo[-1].file_id
    
    if check_and_add_receipt(user_id, file_unique_id):
        temp_reply_to(message, "❌ វិក័យបត្រនេះត្រូវបានផ្ញើរួចម្តងហើយ! សូមកុំផ្ញើដដែលៗ។")
        return
    
    # ផ្ញើទៅ Admin
    caption = (f"📥 **មានវិក័យបត្រថ្មីពីភ្ញៀវ!**\n\n"
               f"👤 **ID ភ្ញៀវ:** `{user_id}`\n\n"
               f"👉 ចុចបញ្ជាខាងក្រោមដើម្បីបញ្ចូលលុយ៖\n"
               f"/addmoney (រួចវាយ ID ភ្ញៀវបញ្ចូលតាមក្រោយ)")
    bot.send_photo(ADMIN_ID, file_id, caption=caption, parse_mode="Markdown")
    
    temp_reply_to(message, "✅ វិក័យបត្ររបស់អ្នកត្រូវបានបញ្ជូនទៅ Admin រួចរាល់។ សូមរង់ចាំបន្តិច!")

@bot.message_handler(func=lambda m: m.text == "🛒 មើលទំនិញ (Shop)" or m.text == "/shop")
def show_shop(message):
    msg = (f"📂 **សូមជ្រើសរើសប្រភេទប្រព័ន្ធទំនិញ៖**\n\n"
           f"👉 /1 : 🤖 AI Tools (ChatGPT, Claude, Gemini...)\n"
           f"👉 /2 : 🌐 VPN & Network\n"
           f"👉 /3 : 💻 Developer Tools (API, Replit, GitHub...)\n"
           f"👉 /4 : 🎬 Media & Streaming (CapCut, YouTube, Netflix...)\n"
           f"👉 /5 : 🎨 Design & Office (Canva, Figma, Microsoft...)\n"
           f"👉 /6 : 📦 ផ្សេងៗ (Others)")
    temp_send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['1', '2', '3', '4', '5', '6'])
@bot.message_handler(func=lambda message: message.text in ['1', '2', '3', '4', '5', '6'])
def handle_category_commands(message):
    cmd = message.text.strip()
    if not cmd.startswith('/'):
        cmd = '/' + cmd
        
    category_map = {
        "/1": {"name": "🤖 AI Tools", "keywords": ["chatgpt", "gpt", "claude", "gemini", "grok", "ai", "perplexity", "heygen", "gamma", "bolt", "lovable"]},
        "/2": {"name": "🌐 VPN & Network", "keywords": ["vpn", "express", "proxy", "ip"]},
        "/3": {"name": "💻 Developer Tools", "keywords": ["api", "replit", "github", "cursor", "warp", "supabase", "posthog", "linear", "framer"]},
        "/4": {"name": "🎬 Media & Streaming", "keywords": ["capcut", "youtube", "netflix", "spotify", "descript"]},
        "/5": {"name": "🎨 Design & Office", "keywords": ["canva", "figma", "microsoft", "office", "autodesk", "notion"]},
        "/6": {"name": "📦 ផ្សេងៗ (Others)", "keywords": []} # Catch-all
    }
    
    selected_cat = category_map.get(cmd)
    if not selected_cat: return
    
    temp_send_message(message.chat.id, f"កំពុងទាញយកទិន្នន័យទំនិញសម្រាប់ **{selected_cat['name']}**... ⏳", parse_mode="Markdown")
    
    res = call_zoom_api("GET", "/products")
    products = res.get('products', [])
    products = [p for p in products if safe_float(p.get('price', 0)) <= 35.0]
    
    if not products:
        temp_send_message(message.chat.id, "❌ មិនមានទំនិញលក់ទេនៅពេលនេះ!")
        return
        
    filtered_products = []
    if cmd == "/6":
        # រកទំនិញដែលមិនចូលក្នុង Category ទី 1 ដល់ 5
        all_keywords = []
        for k, v in category_map.items():
            if k != "/6": all_keywords.extend(v["keywords"])
            
        for p in products:
            name_lower = p.get('name', '').lower()
            if not any(kw in name_lower for kw in all_keywords):
                filtered_products.append(p)
    else:
        for p in products:
            name_lower = p.get('name', '').lower()
            if any(kw in name_lower for kw in selected_cat["keywords"]):
                filtered_products.append(p)
                
    if not filtered_products:
        temp_send_message(message.chat.id, "❌ មិនមានទំនិញក្នុងប្រភេទនេះទេនៅពេលនេះ។")
        return
    filtered_products.sort(key=lambda x: x.get('name', '').lower())
    
    list_text = ""
    for p in filtered_products:
        p_id = p.get('id')
        name = p.get('name', '').replace('_', ' ').replace('*', '')
        original_price = safe_float(p.get('price', 0))
        stock = p.get('stock', 0)
        sell_price = calculate_sell_price(original_price)
        
        list_text += f"👉 /buy_{p_id} : 📦 {name} | 💵 **${sell_price:.2f}** | 📦 {stock}\n"
        
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
        
    temp_send_message(message.chat.id, f"📂 **{selected_cat['name']} ({len(filtered_products)} មុខ):**", parse_mode="Markdown")
    for i, msg in enumerate(messages_to_send):
        if i == len(messages_to_send) - 1:
            msg += "\n📌 *ចុចលើលេខកូដបញ្ជាពណ៌ខៀវខាងលើ ដើម្បីទិញទំនិញ!*"
        temp_send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text and message.text.startswith('/buy_'))
def handle_buy_command(message):
    try:
        product_id = message.text.split('_')[1].strip()
    except:
        return
        
    user_id = message.from_user.id
    temp_send_message(message.chat.id, "កំពុងដំណើរការទិញ... សូមរង់ចាំ! ⏳")
    
    # 1. ស្វែងរកតម្លៃដើមពី API
    res = call_zoom_api("GET", "/products")
    products = res.get('products', [])
    
    target_product = next((p for p in products if str(p.get('id')) == product_id and safe_float(p.get('price', 0)) <= 35.0), None)
    if not target_product:
        temp_send_message(message.chat.id, "❌ រកមិនឃើញទំនិញនេះទេ!")
        return
        
    original_price = safe_float(target_product.get('price', 0))
    sell_price = calculate_sell_price(original_price)
    
    # 2. កាត់លុយ
    if user_id != ADMIN_ID:
        user_balance = get_user_balance(user_id)
        if user_balance < sell_price:
            temp_send_message(message.chat.id, f"❌ លុយរបស់អ្នកមិនគ្រប់គ្រាន់ទេ! (មានតែ ${user_balance:.2f})")
            return
        if not deduct_user_balance(user_id, sell_price, f"ទិញទំនិញ: {product_id}"):
            temp_send_message(message.chat.id, "❌ មានបញ្ហាក្នុងការកាត់ប្រាក់!")
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
        temp_send_message(message.chat.id, msg, parse_mode="Markdown")
    else:
        # បង្វិលលុយវិញ
        if user_id != ADMIN_ID:
            add_user_balance(user_id, sell_price)
            
        error_code = buy_res.get('code')
        if error_code == "INSUFFICIENT_BALANCE":
            if user_id == ADMIN_ID:
                err_msg = "❌ (Admin) លុយនៅក្នុងកុង API (SSONLINE AI SHOP) មិនគ្រប់គ្រាន់ទេ! សូមបញ្ចូលលុយ។"
            else:
                err_msg = "❌ បច្ចុប្បន្នទំនិញនេះកំពុងមានបញ្ហាបច្ចេកទេស! សូមទាក់ទងទៅកាន់ Admin ផ្ទាល់។"
        elif error_code == "OUT_OF_STOCK":
            err_msg = "❌ ទំនិញនេះអស់ពីស្តុកហើយ!"
        elif error_code == "PRODUCT_NOT_FOUND":
            err_msg = "❌ រកមិនឃើញទំនិញនេះក្នុងប្រព័ន្ធទេ។"
        else:
            err_msg = f"❌ បរាជ័យក្នុងការទិញ! (Code: {error_code})"
            
        temp_send_message(message.chat.id, err_msg)

# ================= Admin Commands =================
# (អក្សរកាត់សម្រាប់ Admin Command ដែលឲ្យចុចវាយបញ្ចូល)
@bot.message_handler(commands=['addmoney', 'removemoney', 'checkuser', 'history'])
def handle_admin_commands(message):
    if message.from_user.id != ADMIN_ID: return
    cmd = message.text.split()[0]
    parts = message.text.split()
    
    if cmd == '/addmoney':
        if len(parts) == 3: 
            process_add_money(message, parts[1], parts[2])
        else:
            msg = bot.reply_to(message, "📝 សូមបញ្ចូល **[ID ភ្ញៀវ]** ៖", parse_mode="Markdown")
            bot.register_next_step_handler(msg, step_addmoney_id)
            
    elif cmd == '/removemoney':
        if len(parts) == 3: 
            process_remove_money(message, parts[1], parts[2])
        else:
            msg = bot.reply_to(message, "📝 សូមបញ្ចូល **[ID ភ្ញៀវ]** ដែលត្រូវដកលុយ៖", parse_mode="Markdown")
            bot.register_next_step_handler(msg, step_removemoney_id)
    elif cmd == '/checkuser':
        if len(parts) == 2: process_checkuser(message, parts[1])
        else:
            msg = bot.reply_to(message, "📝 សូមបញ្ចូល **[IDភ្ញៀវ]** ដើម្បីឆែកលុយ៖", parse_mode="Markdown")
            bot.register_next_step_handler(msg, lambda m: process_checkuser(m, m.text.strip()))
            
    elif cmd == '/history':
        if len(parts) == 2: process_history(message, parts[1])
        else:
            msg = bot.reply_to(message, "📝 សូមបញ្ចូល **[IDភ្ញៀវ]** ដើម្បីមើលប្រវត្តិ៖", parse_mode="Markdown")
            bot.register_next_step_handler(msg, lambda m: process_history(m, m.text.strip()))

def step_addmoney_id(message):
    u_id = message.text.strip()
    msg = bot.reply_to(message, f"📝 សូមបញ្ចូល **[ចំនួនលុយ]** សម្រាប់ ID `{u_id}`:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: process_add_money(m, u_id, m.text.strip()))

def step_removemoney_id(message):
    u_id = message.text.strip()
    msg = bot.reply_to(message, f"📝 សូមបញ្ចូល **[ចំនួនលុយ]** ដែលត្រូវដកពី ID `{u_id}`:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda m: process_remove_money(m, u_id, m.text.strip()))

def process_add_money(message, u_id, amt):
    try:
        user_id, amount = int(u_id), float(amt)
        add_user_balance(user_id, amount)
        temp_reply_to(message, f"✅ បានបញ្ចូលលុយ `${amount:.2f}` ទៅឲ្យ ID: `{user_id}` ជោគជ័យ!")
    except:
        temp_reply_to(message, "⚠️ ទម្រង់ខុស!")

def process_remove_money(message, u_id, amt):
    try:
        user_id, amount = int(u_id), float(amt)
        if deduct_user_balance(user_id, amount, "ដកលុយដោយ Admin"):
            temp_reply_to(message, f"✅ បានដកលុយ `${amount:.2f}` ពី ID: `{user_id}` ជោគជ័យ!")
        else:
            temp_reply_to(message, "❌ ភ្ញៀវមានលុយមិនគ្រប់!")
    except:
        temp_reply_to(message, "⚠️ ទម្រង់ខុស!")

def process_checkuser(message, u_id):
    try:
        user_id = int(u_id)
        bal = get_user_balance(user_id)
        temp_reply_to(message, f"👤 **ID ភ្ញៀវ:** `{user_id}`\n👛 **ទឹកប្រាក់មាន:** `${bal:.2f}`", parse_mode="Markdown")
    except:
        temp_reply_to(message, "⚠️ លេខ ID ខុសទម្រង់!")
        
def process_history(message, u_id):
    try:
        user_id = int(u_id)
        ref = rtdb.reference('transactions')
        query = ref.order_by_child('user_id').equal_to(user_id).get()
        
        if not query:
            temp_reply_to(message, "❌ គ្មានប្រវត្តិប្រតិបត្តិការទេ!")
            return
            
        records = list(query.values())
        records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        records = records[:10]
        
        rows = []
        for d in records:
            ts_str = d.get('timestamp', '')
            if ts_str:
                try:
                    dt = datetime.datetime.fromisoformat(ts_str)
                    ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass
            rows.append((d.get('type'), d.get('amount'), d.get('description'), ts_str))
            
        if not rows:
            temp_reply_to(message, "❌ គ្មានប្រវត្តិប្រតិបត្តិការទេ!")
            return
            
        text = f"📜 **ប្រវត្តិ ១០ ដងចុងក្រោយរបស់ `{user_id}`:**\n\n"
        for r in rows:
            text += f"▪️ {r[0]} | ${r[1]:.2f} | {r[2]} | {r[3]}\n"
        temp_reply_to(message, text, parse_mode="Markdown")
    except:
        temp_reply_to(message, "⚠️ លេខ ID ខុសទម្រង់!")

# ================= Webhook & Flask =================
@app.route('/' + TELEGRAM_BOT_TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@app.route("/")
def webhook():
    return "SSONLINE AI SHOP Bot is running!", 200

def set_bot_commands():
    from telebot.types import BotCommand
    commands = [
        BotCommand("start", "ចាប់ផ្តើមប្រើប្រាស់ Bot ឡើងវិញ"),
        BotCommand("shop", "មើលបញ្ជីទំនិញទាំងអស់"),
        BotCommand("info", "មើលព័ត៌មានគណនី និងលុយ"),
        BotCommand("topup", "របៀបបញ្ចូលទឹកប្រាក់ (Binance)"),
        BotCommand("1", "🤖 AI Tools (ChatGPT, Claude...)"),
        BotCommand("2", "🌐 VPN & Network"),
        BotCommand("3", "💻 Developer Tools"),
        BotCommand("4", "🎬 Media & Streaming (Capcut...)"),
        BotCommand("5", "🎨 Design & Office (Canva, Office...)"),
        BotCommand("6", "📦 ផ្សេងៗ (Others)")
    ]
    bot.set_my_commands(commands)

if __name__ == '__main__':
    bot.remove_webhook()
    set_bot_commands()
    if WEBHOOK_URL:
        bot.set_webhook(url=WEBHOOK_URL + '/' + TELEGRAM_BOT_TOKEN)
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
