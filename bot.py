import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
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
REQUIRED_GROUP = os.environ.get('REQUIRED_GROUP', '@SSONLINE_Ai_Bot').strip()

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

# ================= ការត្រួតពិនិត្យសមាជិកភាពក្រុម (Group Membership Verification) =================
_MEMBERSHIP_CACHE = {}  # {user_id: timestamp}
_MEMBERSHIP_CACHE_TTL = 300  # Cache 5 នាទីដើម្បីកុំឲ្យ spam Telegram API

def get_required_chat_id():
    grp = REQUIRED_GROUP
    if grp.startswith('https://t.me/'):
        return '@' + grp.split('https://t.me/')[-1].strip('/')
    if not grp.startswith('@') and not grp.startswith('-'):
        return '@' + grp
    return grp

def get_join_group_url():
    clean = REQUIRED_GROUP.lstrip('@')
    if REQUIRED_GROUP.startswith('http'):
        return REQUIRED_GROUP
    return f"https://t.me/{clean}"

def check_membership_status(user_id):
    """
    ពិនិត្យមើលថាតើសមាជិកបានចូលរួមក្នុងក្រុម REQUIRED_GROUP ឬនៅ
    Returns: (is_member: bool, reason: str or None)
    """
    if user_id == ADMIN_ID:
        return True, None
    now = time.time()
    if user_id in _MEMBERSHIP_CACHE:
        if now - _MEMBERSHIP_CACHE[user_id] < _MEMBERSHIP_CACHE_TTL:
            return True, None
    try:
        target_chat = get_required_chat_id()
        chat_member = bot.get_chat_member(target_chat, user_id)
        if chat_member.status in ['creator', 'administrator', 'member', 'restricted']:
            _MEMBERSHIP_CACHE[user_id] = now
            return True, None
        return False, "not_joined"
    except telebot.apihelper.ApiTelegramException as e:
        err_msg = str(e).lower()
        if "user not found" in err_msg or "participant_id_invalid" in err_msg:
            return False, "not_joined"
        if "chat not found" in err_msg or "bot is not a member" in err_msg or "chat_admin_required" in err_msg:
            print(f"⚠️ Bot permission issue in {REQUIRED_GROUP}: {e}")
            return False, "bot_not_in_group"
        print(f"⚠️ get_chat_member error: {e}")
        return False, "unknown_error"
    except Exception as e:
        print(f"⚠️ check_membership_status error: {e}")
        return False, "unknown_error"

def is_user_member(user_id):
    is_mem, _ = check_membership_status(user_id)
    return is_mem

def send_join_required_message(chat_id, user_id, message_id_to_edit=None):
    group_url = get_join_group_url()
    text = (
        f"👋 <b>សូមស្វាគមន៍មកកាន់ SSONLINE Store!</b> 🐥\n\n"
        f"⚠️ <b>លក្ខខណ្ឌប្រើប្រាស់ Bot៖</b>\n"
        f"ដើម្បីអាចប្រើប្រាស់ Bot និងបញ្ជាទិញទំនិញបាន អ្នកត្រូវតែចូលរួមក្នុងក្រុមផ្លូវការរបស់យើងជាមុនសិន។\n\n"
        f"👉 <b>ក្រុម៖</b> <a href=\"{group_url}\">{REQUIRED_GROUP}</a>\n\n"
        f"<i>សូមចុចប៊ូតុង <b>«📢 ចូលក្រុម»</b> ខាងក្រោម រួចចុច <b>«✅ ខ្ញុំបានចូលរួចហើយ»</b> ដើម្បីចាប់ផ្តើមប្រើប្រាស់។</i>"
    )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton(f"📢 ចូលក្រុម {REQUIRED_GROUP} ↗", url=group_url))
    mk.row(InlineKeyboardButton("✅ ខ្ញុំបានចូលរួចហើយ (Verify)", callback_data="verify_joined"))

    if message_id_to_edit:
        try:
            bot.edit_message_text(text, chat_id, message_id_to_edit, parse_mode="HTML", reply_markup=mk, disable_web_page_preview=True)
            return
        except:
            pass
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=mk, disable_web_page_preview=True)

def check_member_or_prompt(message_or_call):
    """
    Guard function: returns True if user is a member.
    If not, answers callback (if callback) and displays the Join Group screen, then returns False.
    """
    user_id = message_or_call.from_user.id
    if is_user_member(user_id):
        return True
    
    if hasattr(message_or_call, 'message') and message_or_call.message:
        call = message_or_call
        try:
            bot.answer_callback_query(call.id, f"⚠️ សូមចូលរួមក្រុម {REQUIRED_GROUP} ជាមុនសិន!", show_alert=True)
        except:
            pass
        send_join_required_message(call.message.chat.id, user_id, message_id_to_edit=call.message.message_id)
    else:
        send_join_required_message(message_or_call.chat.id, user_id)
    return False

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

def log_transaction(user_id, trans_type, amount, description, extra_data=None):
    try:
        ref = rtdb.reference('transactions')
        entry = {
            'user_id': user_id,
            'type': trans_type,
            'amount': amount,
            'description': description,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        if extra_data:
            entry.update(extra_data)
        ref.push(entry)
    except Exception as e:
        print(e)

def log_purchase(user_id, product_id, product_name, sell_price, keys_list, quantity=1):
    """រក្សាទុកប្រវត្តិទិញទំនិញជារៀងរហូតក្នុង Firebase (purchases/ node)"""
    try:
        ref = rtdb.reference('purchases')
        ref.push({
            'user_id': user_id,
            'product_id': str(product_id),
            'product_name': product_name,
            'quantity': quantity,
            'price_paid': sell_price,
            'keys': keys_list,
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
        # Track product popularity stats
        increment_product_stat(product_id, quantity)
    except Exception as e:
        print(f"log_purchase error: {e}")

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
api_session = requests.Session()

def get_zoom_headers():
    return {
        "X-API-Key": ZOOM_API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

def call_zoom_api(method, endpoint, json_data=None, extra_headers=None):
    url = f"{ZOOM_BASE_URL}{endpoint}"
    headers = get_zoom_headers()
    if extra_headers:
        headers.update(extra_headers)
        
    try:
        if method == "GET":
            resp = api_session.get(url, headers=headers, timeout=12)
        else:
            resp = api_session.post(url, headers=headers, json=json_data, timeout=25)
            
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
    """Calculate our sell price based on pricing tiers (API price is NEVER shown to user)"""
    if original_price < 1.0:
        return round(original_price * 5.0, 2)
    elif original_price < 2.0:
        return round(original_price * 3.0, 2)
    elif original_price < 5.0:
        return round(original_price * 2.5, 2)
    else:
        return round(original_price * 2.0, 2)

def calculate_display_price(sell_price):
    """Generate a fake 'original' crossed-out price that is always >= 60% above sell price.
    This is shown as the 'before discount' price. API cost is NEVER revealed."""
    # Apply at least 60% markup (so discount appears as 37.5%+)
    # Use clean numbers to look realistic (e.g. $4.99, $9.99, $12.00)
    multiplier = 1.65  # 65% above sell = user sees ~40% discount
    display = sell_price * multiplier
    # Round to .99 or .00 for a retail-style price
    base = int(display)
    if display - base >= 0.5:
        display = base + 0.99
    else:
        display = base - 0.01 if base > 0 else 0.99
    # Safety: ensure at least 60% above sell
    if display < sell_price * 1.60:
        display = round(sell_price * 1.65, 2)
    return round(display, 2)

def get_product_logo(name):
    """Return a matching emoji logo for well-known brands/tools"""
    n = name.lower()
    # AI Tools
    if "chatgpt" in n or "openai" in n:    return "🧠"
    if "claude" in n:                       return "🟣"
    if "gemini" in n:                       return "✨"
    if "grok" in n:                         return "🤖"
    if "copilot" in n or "github" in n:    return "🐙"
    if "deepseek" in n:                     return "🔍"
    if "manus" in n:                        return "🧠"
    if "gamma" in n:                        return "🎨"
    if "perplexity" in n:                   return "🔮"
    if "quillbot" in n:                     return "✍️"
    if "midjourney" in n:                   return "🌄"
    if "runway" in n:                       return "🎥"
    if "heygen" in n:                       return "🎤"
    if "elevenlabs" in n:                   return "🔊"
    if "notion" in n:                       return "📝"
    if "grammarly" in n:                    return "📖"
    # Design & Office
    if "canva" in n:                        return "🎨"
    if "adobe" in n:                        return "🅰️"
    if "figma" in n:                        return "🕎"
    if "microsoft" in n or "office" in n or "m365" in n or "365" in n: return "📊"
    if "outlook" in n:                      return "📧"
    if "linkedin" in n:                     return "💼"
    if "autodesk" in n:                     return "🏗️"
    if "miro" in n:                         return "📌"
    # Media & Streaming
    if "netflix" in n:                      return "🎬"
    if "spotify" in n:                      return "🎵"
    if "youtube" in n:                      return "▶️"
    if "capcut" in n:                       return "✂️"
    if "apple" in n:                        return "🍎"
    if "amazon" in n or "prime" in n:      return "📦"
    if "disney" in n:                       return "⭐"
    if "hbo" in n or "max" in n:           return "🎦"
    if "tidal" in n:                        return "🎶"
    if "deezer" in n:                       return "🎧"
    # VPN & Network
    if "vpn" in n or "expressvpn" in n or "express" in n: return "🔒"
    if "nordvpn" in n or "nord" in n:      return "🛡️"
    if "surfshark" in n:                    return "🦈"
    if "warp" in n or "cloudflare" in n:   return "⚡"
    # Developer Tools
    if "replit" in n:                       return "💻"
    if "supabase" in n:                     return "🔩"
    if "railway" in n:                      return "🚂"
    if "cursor" in n:                       return "📦"
    if "duolingo" in n:                     return "🦉"
    if "coursera" in n:                     return "🎓"
    if "pdf" in n:                          return "📄"
    # Fallback
    return "🔥"

# ===== POPULARITY TRACKING =====
_POPULARITY_CACHE = {}
_POPULARITY_CACHE_TIME = 0
_POPULARITY_CACHE_TTL = 300  # 5 minutes

def get_product_popularity():
    """Fetch product purchase counts from Firebase product_stats node.
    Returns dict: {product_id_str: total_sold_count}"""
    global _POPULARITY_CACHE, _POPULARITY_CACHE_TIME
    now = time.time()
    if now - _POPULARITY_CACHE_TIME < _POPULARITY_CACHE_TTL and _POPULARITY_CACHE:
        return _POPULARITY_CACHE
    try:
        ref = rtdb.reference('product_stats')
        data = ref.get() or {}
        result = {pid: int(info.get('sold', 0)) for pid, info in data.items()}
        _POPULARITY_CACHE = result
        _POPULARITY_CACHE_TIME = now
        return result
    except Exception as e:
        print(f"get_product_popularity error: {e}")
        return _POPULARITY_CACHE or {}

def increment_product_stat(product_id, quantity=1):
    """Increment sold count for a product in Firebase product_stats"""
    try:
        ref = rtdb.reference(f'product_stats/{product_id}')
        current = ref.get() or {}
        ref.update({'sold': int(current.get('sold', 0)) + quantity})
        # Invalidate cache
        global _POPULARITY_CACHE_TIME
        _POPULARITY_CACHE_TIME = 0
    except Exception as e:
        print(f"increment_product_stat error: {e}")

def get_product_badge(product_id, popularity):
    """Return a badge based on sales count: 🔥HOT, ⭐NEW, or empty"""
    sold = popularity.get(str(product_id), 0)
    if sold >= 50: return "🔥"
    if sold >= 20: return "⭐"
    if sold >= 5:  return "✨"
    return ""

# ===================== ZOOM STORE STYLE UI & BUY FLOW =====================
import re
import io
import datetime
import uuid
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

PRODUCTS_PER_PAGE = 10

def clean_description(desc):
    if not desc:
        return ""
    # Replace <<ce:...>> with neat emoji
    cleaned = re.sub(r'<<ce:\d+>>\s*', '💥 ', desc)
    # Replace any external zoom support bot mentions with @limsorn
    cleaned = re.sub(r'@\w*zoom\w*', '@limsorn', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'https?://t\.me/\w*zoom\w*', 'https://t.me/limsorn', cleaned, flags=re.IGNORECASE)
    # Escape raw HTML brackets to prevent broken HTML parsing
    cleaned = cleaned.replace('<', '&lt;').replace('>', '&gt;')
    return cleaned.strip()

def build_home_markup(user_id):
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("💳 Products", callback_data="products_p0"))
    mk.row(InlineKeyboardButton("🎉 Offers", callback_data="menu_offers"))
    mk.row(
        InlineKeyboardButton("🛒 Cart", callback_data="menu_cart"),
        InlineKeyboardButton("💰 Top Up", callback_data="cmd_topup")
    )
    mk.row(
        InlineKeyboardButton("📑 My Orders", callback_data="my_orders"),
        InlineKeyboardButton("🦆 Profile", callback_data="cmd_info")
    )
    mk.row(
        InlineKeyboardButton("📢 Group ↗", url=get_join_group_url()),
        InlineKeyboardButton("🎧 Admin Support ↗", url="https://t.me/limsorn")
    )
    mk.row(InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"))
    return mk

def home_text(user_id, first_name, username):
    bal = get_user_balance(user_id) if user_id != ADMIN_ID else None
    balance_str = "Admin" if user_id == ADMIN_ID else f"${bal:.2f}"
    uname = f"@{username}" if username and not username.startswith("@") else (username or str(user_id))
    return (
        f"Hey <b>{first_name}</b> 🇰🇭 🐥\n"
        f"Welcome to <b>SSONLINE Store</b>\n"
        f"<i>Pay, and it's yours before you close the app</i>\n\n"
        f"<pre>"
        f"| {'🦆 Account':<20} | {'💰 Wallet':<12} |\n"
        f"| {uname:<20} | {balance_str:<12} |\n"
        f"| {str(user_id):<20} | {'':<12} |\n"
        f"</pre>\n"
        f"📢 ក្រុម: <a href='{get_join_group_url()}'>{REQUIRED_GROUP}</a>\n"
        f"🎧 Admin: <a href='https://t.me/limsorn'>@limsorn</a>\n"
        f"Choose an option below 👇"
    )

@bot.callback_query_handler(func=lambda call: call.data == "verify_joined")
def cb_verify_joined(call):
    user_id = call.from_user.id
    _MEMBERSHIP_CACHE.pop(user_id, None)
    is_mem, reason = check_membership_status(user_id)
    if is_mem:
        bot.answer_callback_query(call.id, "✅ ការផ្ទៀងផ្ទាត់ជោគជ័យ! សូមស្វាគមន៍មកកាន់ Store។", show_alert=True)
        first_name = call.from_user.first_name or "Guest"
        username = call.from_user.username or ""
        text = home_text(user_id, first_name, username)
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                                  parse_mode="HTML", reply_markup=build_home_markup(user_id))
        except:
            bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=build_home_markup(user_id))
    elif reason == "bot_not_in_group":
        bot.answer_callback_query(
            call.id,
            f"⚠️ Bot មិនទាន់ត្រូវបាន Add ចូលក្នុងក្រុម {REQUIRED_GROUP} ជា Admin នៅឡើយទេ។ សូមទាក់ទង Admin @limsorn!",
            show_alert=True
        )
    else:
        bot.answer_callback_query(
            call.id,
            f"❌ អ្នកមិនទាន់បានចូលរួមក្រុម {REQUIRED_GROUP} នៅឡើយទេ! សូមចុច Join Group រួចចុចផ្ទៀងផ្ទាត់ម្ដងទៀត។",
            show_alert=True
        )

@bot.message_handler(commands=['start'])
def send_welcome(message):
    global COMMANDS_INITIALIZED
    if not COMMANDS_INITIALIZED:
        threading.Thread(target=set_bot_commands, daemon=True).start()
    if not check_member_or_prompt(message):
        return
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Guest"
    username = message.from_user.username or ""
    try:
        cleanup = bot.send_message(message.chat.id, ".", reply_markup=ReplyKeyboardRemove())
        bot.delete_message(message.chat.id, cleanup.message_id)
    except:
        pass
    bot.send_message(message.chat.id, home_text(user_id, first_name, username),
                     parse_mode="HTML", reply_markup=build_home_markup(user_id))

@bot.callback_query_handler(func=lambda call: call.data == "home")
def go_home(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    first_name = call.from_user.first_name or "Guest"
    username = call.from_user.username or ""
    text = home_text(user_id, first_name, username)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=build_home_markup(user_id))
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=build_home_markup(user_id))

@bot.callback_query_handler(func=lambda call: call.data == "menu_offers")
def cb_offers(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    text = (
        "🎉 <b>Special Offers & Promotions</b>\n\n"
        "🔥 All prices are discounted up to 50%!\n"
        "⚡ Instant automatic delivery 24/7.\n"
        "🎁 Check back often for flash deals and new tools!"
    )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("💳 Browse Products", callback_data="products_p0"))
    mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data == "menu_cart")
def cb_cart(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    text = (
        "🛒 <b>Your Cart</b>\n\n"
        "Your shopping cart is currently empty!\n"
        "Select products to buy directly with instant delivery."
    )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("💳 Shop Now", callback_data="products_p0"))
    mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data == "cart_add")
def cb_cart_add(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id, "💡 Please use 'Buy Now' for instant delivery!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "menu_api")
def cb_api(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    text = (
        "⚡ <b>API Integration</b>\n\n"
        "🟢 Status: Online & Operational\n"
        "🔗 Provider: SSONLINE Store\n"
        "⚡ Automated license code dispatch active."
    )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data == "menu_settings")
def cb_settings(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    text = (
        "⚙️ <b>Settings</b>\n\n"
        "🌐 Language: English / ភាសាខ្មែរ\n"
        "💵 Currency: USDT\n"
        "🤖 Version: 2.0 (SSONLINE Store Edition)\n"
        "📞 Support: @limsorn"
    )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=mk)

@bot.message_handler(commands=['myorders', 'myhistory'])
def cmd_myorders(message):
    if not check_member_or_prompt(message):
        return
    show_my_orders_msg(message.chat.id, message.from_user.id)

def show_my_orders_msg(chat_id, user_id, message_id_to_edit=None):
    if not is_user_member(user_id):
        send_join_required_message(chat_id, user_id, message_id_to_edit)
        return
    try:
        ref = rtdb.reference("purchases")
        query = ref.order_by_child("user_id").equal_to(user_id).get()
        if not query:
            msg = "📭 អ្នកមិនទាន់មានប្រវត្តិទិញទំនិញទេ!"
            mk = InlineKeyboardMarkup()
            mk.row(InlineKeyboardButton("🛍️ Shop Now", callback_data="products_p0"), InlineKeyboardButton("🏠 Home", callback_data="home"))
            bot.send_message(chat_id, msg, reply_markup=mk)
            return
        records = sorted(query.values(), key=lambda x: x.get("timestamp", ""), reverse=True)[:10]
        text = "<b>📋 My Orders (ប្រវត្តិទិញទំនិញ ១០ ដងចុងក្រោយ):</b>\n\n"
        for i, r in enumerate(records, 1):
            ts = r.get("timestamp", "")
            try:
                ts = datetime.datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
            except:
                pass
            qty = r.get("quantity", 1)
            keys = r.get("keys", [])
            keys_disp = "\n   ".join(f"<code>{k}</code>" for k in keys) if keys else "N/A"
            text += (
                f"{i}. 📦 <b>{r.get('product_name', 'N/A')}</b> (ចំនួន: {qty})\n"
                f"   💵 តម្លៃ: ${float(r.get('price_paid', 0)):.2f} | 🕐 {ts}\n"
                f"   🔑 Keys:\n   {keys_disp}\n\n"
            )
        mk = InlineKeyboardMarkup()
        mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
        if message_id_to_edit:
            try:
                bot.edit_message_text(text, chat_id, message_id_to_edit, parse_mode="HTML", reply_markup=mk)
                return
            except: pass
        bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=mk)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "my_orders")
def cb_my_orders(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    show_my_orders_msg(call.message.chat.id, call.from_user.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "cmd_info")
def cb_info(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    call.message.from_user = call.from_user
    show_info(call.message)

@bot.message_handler(commands=['info'])
def show_info(message):
    if not check_member_or_prompt(message):
        return
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        api_res = call_zoom_api("GET", "/balance")
        real_bal = api_res.get("balance", 0.0) if "balance" in api_res else 0.0
        currency = api_res.get("currency", "USDT")
        msg = (
            f"👑 <b>Admin Info:</b>\n\n"
            f"🆔 <code>{user_id}</code>\n"
            f"🏦 API Balance: <b>{real_bal:.2f} {currency}</b>\n\n"
            f"/addmoney | /removemoney | /checkuser | /history"
        )
    else:
        balance = get_user_balance(user_id)
        msg = (
            f"👤 <b>Account Profile:</b>\n\n"
            f"🆔 <code>{user_id}</code>\n"
            f"💰 Wallet: <b>${balance:.2f} USDT</b>\n\n"
            f"To top up your wallet: click 💰 Top Up or type /topup"
        )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("💰 Top Up", callback_data="cmd_topup"), InlineKeyboardButton("🏠 Home", callback_data="home"))
    try:
        bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=mk)
    except:
        temp_send_message(message.chat.id, msg, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "cmd_topup")
def cb_topup(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    call.message.from_user = call.from_user
    handle_topup(call.message)

@bot.message_handler(commands=['topup'])
def handle_topup(message):
    if not check_member_or_prompt(message):
        return
    user_id = message.from_user.id
    msg = (
        f"🏦 <b>Top Up via Binance Pay / ABA:</b>\n\n"
        f"1️⃣ <b>Binance Pay ID:</b> <code>832944944</code>\n"
        f"2️⃣ <b>Your Account ID:</b> <code>{user_id}</code>\n"
        f"3️⃣ Screenshot receipt & send photo directly into this chat.\n\n"
        f"<i>For ABA Bank / KHQR, please contact Admin @limsorn</i>"
    )
    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
    try:
        with open("qr_binance.png", "rb") as photo:
            obj = bot.send_photo(message.chat.id, photo, caption=msg, parse_mode="HTML", reply_markup=mk)
            threading.Timer(180.0, delete_msg, args=(message.chat.id, obj.message_id)).start()
    except:
        temp_send_message(message.chat.id, msg, parse_mode="HTML")

@bot.message_handler(content_types=['photo'])
def handle_receipt_photo(message):
    if not check_member_or_prompt(message):
        return
    user_id = message.from_user.id
    if user_id == ADMIN_ID:
        return
    file_unique_id = message.photo[-1].file_unique_id
    file_id = message.photo[-1].file_id
    if check_and_add_receipt(user_id, file_unique_id):
        temp_reply_to(message, "❌ វិក្កយបត្រនេះធ្លាប់បានផ្ញើរួចហើយ!")
        return
    caption = f"📥 <b>វិក្កយបត្របញ្ចូលលុយថ្មី!</b>\n\n👤 ID: <code>{user_id}</code>\n\n👉 ប្រើ /addmoney {user_id} [ចំនួន] ដើម្បីបន្ថែមប្រាក់"
    bot.send_photo(ADMIN_ID, file_id, caption=caption, parse_mode="HTML")
    temp_reply_to(message, "✅ វិក្កយបត្របានផ្ញើទៅកាន់ Admin រួចរាល់! សូមរង់ចាំការត្រួតពិនិត្យបន្តិច។")

# ================= PRODUCTS ZOOM STORE ENGINE =================

# ================= CATEGORIES & MENU COMMANDS =================
CATEGORIES = {
    "1": {
        "title": "🤖 AI Tools (ChatGPT, Claude...)",
        "short_title": "AI Tools",
        "keywords": ["chatgpt", "claude", "gemini", "grok", "gamma", "manus", "granola", "gumloop", "higgsfield", "chatprd", "quillbot", "deepseek", "copilot", "ai"]
    },
    "2": {
        "title": "🌐 VPN & Network",
        "short_title": "VPN & Network",
        "keywords": ["vpn", "express", "nord", "surfshark", "warp", "proxy"]
    },
    "3": {
        "title": "💻 Developer Tools",
        "short_title": "Developer Tools",
        "keywords": ["replit", "replite", "supabase", "runway", "github", "cursor", "railway", "warp build"]
    },
    "4": {
        "title": "🎬 Media & Streaming (Capcut...)",
        "short_title": "Media & Streaming",
        "keywords": ["capcut", "youtube", "netflix", "spotify", "apple music", "prime", "amazon"]
    },
    "5": {
        "title": "🎨 Design & Office (Canva, Office...)",
        "short_title": "Design & Office",
        "keywords": ["canva", "adobe", "figma", "microsoft", "office", "notion", "miro", "autodesk", "coursera", "duolingo", "pdf", "outlook", "linkedin"]
    },
    "6": {
        "title": "📦 ផ្សេងៗ (Others)",
        "short_title": "Others",
        "keywords": []
    }
}

def get_category_products(cat_id):
    products = get_filtered_products()
    cat_info = CATEGORIES.get(str(cat_id))
    if not cat_info:
        return products
    keywords = cat_info["keywords"]
    if str(cat_id) == "6":
        all_other_kw = []
        for cid in ["1", "2", "3", "4", "5"]:
            all_other_kw.extend(CATEGORIES[cid]["keywords"])
        return [
            p for p in products 
            if not any(kw in (p.get("name", "") + " " + (p.get("group") or "")).lower() for kw in all_other_kw)
        ]
    return [
        p for p in products 
        if any(kw in (p.get("name", "") + " " + (p.get("group") or "")).lower() for kw in keywords)
    ]

def show_category_view(chat_id, user_id, cat_id, page=0, message_id_to_edit=None):
    if not is_user_member(user_id):
        send_join_required_message(chat_id, user_id, message_id_to_edit)
        return
    cat_info = CATEGORIES.get(str(cat_id), {"title": "Products", "short_title": "Products"})
    cat_products = get_category_products(cat_id)
    if not cat_products:
        msg_text = f"❌ បច្ចុប្បន្នមិនទាន់មានទំនិញក្នុងជំពូក <b>{cat_info['title']}</b> ក្រោម $10 ទេ!"
        mk = InlineKeyboardMarkup()
        mk.row(InlineKeyboardButton("🛍️ All Products", callback_data="products_p0"))
        mk.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
        if message_id_to_edit:
            try:
                bot.edit_message_text(msg_text, chat_id, message_id_to_edit, parse_mode="HTML", reply_markup=mk)
                return
            except: pass
        bot.send_message(chat_id, msg_text, parse_mode="HTML", reply_markup=mk)
        return

    groups = group_products(cat_products)
    group_keys = sorted(groups.keys())
    total_pages = max(1, (len(group_keys) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_keys = group_keys[page * PRODUCTS_PER_PAGE:(page + 1) * PRODUCTS_PER_PAGE]
    total_products = sum(len(v) for v in groups.values())

    bal = get_user_balance(user_id) if user_id != ADMIN_ID else None
    balance_str = "Admin" if user_id == ADMIN_ID else f"${bal:.2f} USDT"

    header = (
        f"<blockquote>Pay, and it's yours before you close the app\n"
        f"🏦 Welcome to SSONLINE Store 🏦\n"
        f"💰 Your Balance: {balance_str}\n"
        f"Category: <b>{cat_info['title']}</b> ({total_products} items)\n"
        f"Please select a product below:</blockquote>"
    )

    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton(f"🛍️ {cat_info['short_title']} ({total_products})", callback_data="noop"))
    for grp_name in page_keys:
        items = groups[grp_name]
        if len(items) > 1:
            stock = sum(int(p.get("stock", 0) or 0) for p in items)
            mk.row(InlineKeyboardButton(
                f"🔥 {grp_name} ◇ {len(items)} plans ({stock}) »",
                callback_data=f"cgrp_{cat_id}_{grp_name[:15]}_p{page}"
            ))
        else:
            p = items[0]
            p_id = str(p.get("id"))
            name = p.get("name", "N/A")
            sell = calculate_sell_price(safe_float(p.get("price", 0)))
            stock = p.get("stock", 0)
            mk.row(InlineKeyboardButton(
                f"🔥 {name} | ${sell:.2f} | {stock}",
                callback_data=f"buyp_{p_id}_c{cat_id}_p{page}"
            ))

    if total_pages > 1:
        prev_p = (page - 1) % total_pages
        next_p = (page + 1) % total_pages
        mk.row(
            InlineKeyboardButton("◀ Prev", callback_data=f"cat_{cat_id}_p{prev_p}"),
            InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton("Next ▶", callback_data=f"cat_{cat_id}_p{next_p}")
        )
    mk.row(
        InlineKeyboardButton("🛍️ All Products", callback_data="products_p0"),
        InlineKeyboardButton("🛒 Cart", callback_data="menu_cart")
    )
    mk.row(InlineKeyboardButton("🐥 Home", callback_data="home"))

    if message_id_to_edit:
        try:
            bot.edit_message_text(header, chat_id, message_id_to_edit, parse_mode="HTML", reply_markup=mk)
            return
        except: pass
    bot.send_message(chat_id, header, parse_mode="HTML", reply_markup=mk)

@bot.message_handler(commands=['1', '2', '3', '4', '5', '6'])
def handle_cat_commands(message):
    if not check_member_or_prompt(message):
        return
    cat_id = message.text.replace('/', '').strip()
    show_category_view(message.chat.id, message.from_user.id, cat_id, 0)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cat_"))
def cb_cat_pagination(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    raw = call.data.replace("cat_", "")
    parts = raw.split("_p")
    cat_id = parts[0]
    page = int(parts[1]) if len(parts) > 1 else 0
    show_category_view(call.message.chat.id, call.from_user.id, cat_id, page, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cgrp_"))
def cb_cat_group(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    raw = call.data.replace("cgrp_", "")
    parts = raw.split("_p")
    page = int(parts[1]) if len(parts) > 1 else 0
    cat_and_grp = parts[0].split("_", 1)
    cat_id = cat_and_grp[0]
    grp_name = cat_and_grp[1] if len(cat_and_grp) > 1 else ""

    user_id = call.from_user.id
    cat_products = get_category_products(cat_id)
    groups = group_products(cat_products)

    matching_grp = next((g for g in groups.keys() if g.startswith(grp_name) or grp_name in g), None)
    if not matching_grp:
        bot.answer_callback_query(call.id, "Group not found!", show_alert=True)
        return

    items = sorted(groups[matching_grp], key=lambda x: safe_float(x.get("price", 0)))
    bal = get_user_balance(user_id) if user_id != ADMIN_ID else None
    balance_str = "Admin" if user_id == ADMIN_ID else f"${bal:.2f} USDT"

    header = (
        f"<blockquote>Pay, and it's yours before you close the app\n"
        f"🏦 Welcome to SSONLINE Store 🏦\n"
        f"💰 Your Balance: {balance_str}\n"
        f"<b>{matching_grp}</b> ({len(items)} plans)\n"
        f"Please select a product below:</blockquote>"
    )

    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton(f"🛍️ {matching_grp}", callback_data="noop"))
    for p in items:
        p_id = str(p.get("id"))
        name = p.get("name", "N/A")
        sell = calculate_sell_price(safe_float(p.get("price", 0)))
        stock = p.get("stock", 0)
        mk.row(InlineKeyboardButton(
            f"🔥 {name} | ${sell:.2f} | {stock}",
            callback_data=f"buyp_{p_id}_c{cat_id}_p{page}"
        ))

    mk.row(InlineKeyboardButton("🐥 Back to Category", callback_data=f"cat_{cat_id}_p{page}"))
    mk.row(InlineKeyboardButton("🚪 Home", callback_data="home"))

    try:
        bot.edit_message_text(header, call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, header, parse_mode="HTML", reply_markup=mk)


PRODUCTS_CACHE = None
PRODUCTS_CACHE_TIME = 0
CACHE_TTL = 90  # រក្សាទុក Cache រយៈពេល 90 វិនាទី (ធ្វើឲ្យចុចប៊ូតុងភ្លាម ចេញភ្លាម Instant)
CACHE_LOCK = threading.Lock()

def get_filtered_products(force_refresh=False):
    """ទាញយកទំនិញតែតម្លៃដើមក្រោម១០ $ ដោយប្រើ Memory Cache ជួយឲ្យ Bot ឆ្លើយតបលឿនបំផុត (Instant)"""
    global PRODUCTS_CACHE, PRODUCTS_CACHE_TIME
    now = time.time()
    
    with CACHE_LOCK:
        if not force_refresh and PRODUCTS_CACHE is not None and (now - PRODUCTS_CACHE_TIME) < CACHE_TTL:
            return PRODUCTS_CACHE

    res = call_zoom_api("GET", "/products")
    products = res.get("products", [])
    filtered = [p for p in products if safe_float(p.get("price", 0)) < 10.0]

    if filtered or PRODUCTS_CACHE is None:
        with CACHE_LOCK:
            PRODUCTS_CACHE = filtered
            PRODUCTS_CACHE_TIME = now

    return PRODUCTS_CACHE if PRODUCTS_CACHE is not None else filtered

def group_products(products):
    """Group products by their group field or first word of name"""
    groups = {}
    for p in products:
        grp = (p.get("group") or p.get("name", "").split()[0]).strip()
        groups.setdefault(grp, []).append(p)
    return groups

def get_sorted_group_keys(groups, popularity):
    """Sort group keys by total sold count descending (popular first)"""
    def grp_sold(grp_name):
        items = groups[grp_name]
        return sum(popularity.get(str(p.get("id", "")), 0) for p in items)
    return sorted(groups.keys(), key=grp_sold, reverse=True)

def products_header(user_id):
    bal = get_user_balance(user_id) if user_id != ADMIN_ID else None
    balance_str = "Admin" if user_id == ADMIN_ID else f"${bal:.2f} USDT"
    return (
        f"<blockquote>Pay, and it's yours before you close the app\n"
        f"🏦 Welcome to SSONLINE Store 🏦\n"
        f"💰 Your Balance: {balance_str}\n"
        f"🔥 Popular Products — Updated Live\n"
        f"Please select a product below:</blockquote>"
    )

def build_products_markup(groups, page, user_id):
    popularity = get_product_popularity()
    group_keys = get_sorted_group_keys(groups, popularity)  # popular first
    total_pages = max(1, (len(group_keys) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_keys = group_keys[page * PRODUCTS_PER_PAGE:(page + 1) * PRODUCTS_PER_PAGE]
    total_products = sum(len(v) for v in groups.values())

    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton(f"🔥 Hot Products ({total_products})", callback_data="noop"))

    for grp_name in page_keys:
        items = groups[grp_name]
        grp_idx = group_keys.index(grp_name)
        logo = get_product_logo(grp_name)
        sold_total = sum(popularity.get(str(p.get("id", "")), 0) for p in items)
        badge = "🔥 " if sold_total >= 50 else "⭐ " if sold_total >= 10 else ""
        if len(items) > 1:
            stock = sum(int(p.get("stock", 0) or 0) for p in items)
            mk.row(InlineKeyboardButton(
                f"{badge}{logo} {grp_name} ◇ {len(items)} plans ({stock}) »",
                callback_data=f"grp_{grp_idx}_p{page}"
            ))
        else:
            p = items[0]
            p_id = str(p.get("id"))
            name = p.get("name", "N/A")
            sell = calculate_sell_price(safe_float(p.get("price", 0)))
            stock = p.get("stock", 0)
            mk.row(InlineKeyboardButton(
                f"{badge}{logo} {name} | ${sell:.2f} | {stock}",
                callback_data=f"buyp_{p_id}_p{page}"
            ))

    # Controls
    mk.row(
        InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_p{page}"),
        InlineKeyboardButton("🔥 Popular First", callback_data="noop")
    )
    if total_pages > 1:
        prev_p = (page - 1) % total_pages
        next_p = (page + 1) % total_pages
        mk.row(
            InlineKeyboardButton("◀ Prev", callback_data=f"products_p{prev_p}"),
            InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"),
            InlineKeyboardButton("Next ▶", callback_data=f"products_p{next_p}")
        )
    mk.row(InlineKeyboardButton("🛒 Cart", callback_data="menu_cart"))
    mk.row(InlineKeyboardButton("🐥 Home", callback_data="home"))
    return mk

@bot.message_handler(commands=['shop'])
def show_shop(message):
    if not check_member_or_prompt(message):
        return
    user_id = message.from_user.id
    products = get_filtered_products()
    if not products:
        temp_send_message(message.chat.id, "❌ បច្ចុប្បន្នមិនមានទំនិញក្រោម $10 ទេ!")
        return
    groups = group_products(products)
    mk = build_products_markup(groups, 0, user_id)
    bot.send_message(message.chat.id, products_header(user_id), parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data.startswith("products_p") or call.data.startswith("refresh_p"))
def cb_products_page(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    is_refresh = call.data.startswith("refresh_p")
    raw = call.data.replace("products_p", "").replace("refresh_p", "")
    try:
        page = int(raw)
    except:
        page = 0
    user_id = call.from_user.id
    products = get_filtered_products(force_refresh=is_refresh)
    if not products:
        bot.answer_callback_query(call.id, "❌ No products found!", show_alert=True)
        return
    groups = group_products(products)
    mk = build_products_markup(groups, page, user_id)
    try:
        bot.edit_message_text(products_header(user_id), call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, products_header(user_id), parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data.startswith("grp_"))
def cb_group_view(call):
    """Inside a brand / group page"""
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    raw = call.data.replace("grp_", "")
    parts = raw.split("_p")
    grp_idx = int(parts[0])
    page = int(parts[1]) if len(parts) > 1 else 0

    user_id = call.from_user.id
    products = get_filtered_products()
    groups = group_products(products)
    group_keys = sorted(groups.keys())

    if grp_idx >= len(group_keys):
        bot.answer_callback_query(call.id, "Group not found!", show_alert=True)
        return

    grp_name = group_keys[grp_idx]
    items = sorted(groups[grp_name], key=lambda x: safe_float(x.get("price", 0)))

    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton(f"🛍️ {grp_name}", callback_data="noop"))
    for p in items:
        p_id = str(p.get("id"))
        name = p.get("name", "N/A")
        sell = calculate_sell_price(safe_float(p.get("price", 0)))
        stock = p.get("stock", 0)
        mk.row(InlineKeyboardButton(
            f"🔥 {name} | ${sell:.2f} | {stock}",
            callback_data=f"buyp_{p_id}_g{grp_idx}_p{page}"
        ))

    mk.row(InlineKeyboardButton("🐥 Back to Store", callback_data=f"products_p{page}"))
    mk.row(InlineKeyboardButton("🚪 Home", callback_data="home"))

    try:
        bot.edit_message_text(products_header(user_id), call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, products_header(user_id), parse_mode="HTML", reply_markup=mk)

# ================= PRODUCT DETAIL PAGE =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("buyp_"))
def cb_product_detail(call):
    """Show Zoom Store style product detail page"""
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    raw = call.data.replace("buyp_", "")
    parts = raw.split("_")
    product_id = parts[0]

    # Preserve back button navigation
    back_to_page = 0
    back_to_grp = None
    back_to_cat = None
    for part in parts[1:]:
        if part.startswith("p"):
            try: back_to_page = int(part[1:])
            except: pass
        elif part.startswith("g"):
            try: back_to_grp = int(part[1:])
            except: pass
        elif part.startswith("c"):
            try: back_to_cat = part[1:]
            except: pass

    user_id = call.from_user.id
    products = get_filtered_products()
    p = next((x for x in products if str(x.get("id")) == product_id), None)

    if not p:
        bot.answer_callback_query(call.id, "❌ Product not found or price > $10!", show_alert=True)
        return

    name = p.get("name", "N/A")
    original_price = safe_float(p.get("price", 0))  # API cost — NEVER shown
    sell_price = calculate_sell_price(original_price)
    display_price = calculate_display_price(sell_price)  # Fake crossed-out price
    stock = p.get("stock", 0)
    desc = clean_description(p.get("description", ""))

    detail_text = (
        f"1 🍭 <b>{name}</b>\n\n"
        f"🔥 Flash Sale — Up to 40% OFF!\n"
        f"💲 Price: <s>${display_price:.2f}</s> → <b>${sell_price:.2f}</b> / code\n"
        f"📦 Stock: <b>{stock}</b>\n\n"
    )
    if desc:
        detail_text += f"{desc}\n\n"

    detail_text += (
        f"🛡️ <b>No warranty after redeem ⭐</b>\n\n"
        f"❌ No Hold warranty and No warranty after successful activation (link is single-use).\n\n"
        f"<i>Delivery is automatic after payment confirmation.</i>"
    )

    if back_to_cat is not None:
        back_cb = f"cat_{back_to_cat}_p{back_to_page}"
    elif back_to_grp is not None:
        back_cb = f"grp_{back_to_grp}_p{back_to_page}"
    else:
        back_cb = f"products_p{back_to_page}"

    mk = InlineKeyboardMarkup()
    mk.row(InlineKeyboardButton("💳 Buy Now", callback_data=f"qtyselect_{product_id}"))
    mk.row(InlineKeyboardButton("🛒 Add to Cart", callback_data="cart_add"))
    mk.row(InlineKeyboardButton("🐥 Back to Store", callback_data=back_cb))

    try:
        bot.edit_message_text(detail_text, call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, detail_text, parse_mode="HTML", reply_markup=mk)

# ================= QUANTITY SELECTION =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("qtyselect_"))
def cb_qty_select(call):
    """Quantity selection buttons (1, 2, 3, 5, 10, 15, 20, 25, Custom Amount)"""
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    product_id = call.data.replace("qtyselect_", "")

    products = get_filtered_products()
    p = next((x for x in products if str(x.get("id")) == product_id), None)
    if not p:
        bot.answer_callback_query(call.id, "❌ Product not found!", show_alert=True)
        return

    name = p.get("name", "N/A")
    sell_price = calculate_sell_price(safe_float(p.get("price", 0)))
    stock = p.get("stock", 0)

    text = (
        f"📦 <b>Select Quantity</b>\n\n"
        f"Product: <b>{name}</b>\n"
        f"Price: <b>${sell_price:.2f}</b> / code\n"
        f"Stock Available: <b>{stock}</b>\n\n"
        f"Choose quantity below or enter a custom amount:"
    )

    mk = InlineKeyboardMarkup()
    mk.row(
        InlineKeyboardButton("📦 1", callback_data=f"cfmq_{product_id}_1"),
        InlineKeyboardButton("📦 2", callback_data=f"cfmq_{product_id}_2"),
        InlineKeyboardButton("📦 3", callback_data=f"cfmq_{product_id}_3"),
        InlineKeyboardButton("📦 5", callback_data=f"cfmq_{product_id}_5")
    )
    mk.row(
        InlineKeyboardButton("📦 10", callback_data=f"cfmq_{product_id}_10"),
        InlineKeyboardButton("📦 15", callback_data=f"cfmq_{product_id}_15"),
        InlineKeyboardButton("📦 20", callback_data=f"cfmq_{product_id}_20"),
        InlineKeyboardButton("📦 25", callback_data=f"cfmq_{product_id}_25")
    )
    mk.row(InlineKeyboardButton("✏️ Custom Amount", callback_data=f"customq_{product_id}"))
    mk.row(
        InlineKeyboardButton("🐥 Back", callback_data=f"buyp_{product_id}"),
        InlineKeyboardButton("🚪 Home", callback_data="home")
    )

    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=mk)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data.startswith("customq_"))
def cb_custom_qty(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    product_id = call.data.replace("customq_", "")
    msg = bot.send_message(call.message.chat.id, "📝 សូមបញ្ចូលចំនួនដែលអ្នកចង់ទិញ (ឧទាហរណ៍: 1, 2, 4...) ៖")
    bot.register_next_step_handler(msg, lambda m: step_custom_qty(m, product_id))

def step_custom_qty(message, product_id):
    if not check_member_or_prompt(message):
        return
    try:
        qty = int(message.text.strip())
        if qty <= 0:
            temp_reply_to(message, "⚠️ ចំនួនត្រូវតែធំជាង 0!")
            return
    except:
        temp_reply_to(message, "⚠️ សូមបញ្ចូលជាលេខប៉ុណ្ណោះ!")
        return

    show_confirmation(message.chat.id, message.from_user.id, product_id, qty)

# ================= PURCHASE CONFIRMATION SCREEN =================

def show_confirmation(chat_id, user_id, product_id, qty, message_id_to_edit=None):
    if not is_user_member(user_id):
        send_join_required_message(chat_id, user_id, message_id_to_edit)
        return
    products = get_filtered_products()
    p = next((x for x in products if str(x.get("id")) == product_id), None)
    if not p:
        bot.send_message(chat_id, "❌ រកមិនឃើញទំនិញនេះទៀតទេ!")
        return

    name = p.get("name", "N/A")
    sell_price = calculate_sell_price(safe_float(p.get("price", 0)))
    total_price = round(sell_price * qty, 2)
    stock = int(p.get("stock", 0) or 0)

    if user_id == ADMIN_ID:
        user_balance = 999999.0
        bal_text = "👑 Admin (Free Test)"
        can_afford = True
    else:
        user_balance = get_user_balance(user_id)
        bal_text = f"${user_balance:.2f} USDT"
        can_afford = (user_balance >= total_price)

    stock_ok = (stock >= qty)

    if not stock_ok:
        status_line = f"⚠️ <b>ស្តុកមិនគ្រប់គ្រាន់ទេ!</b> (នៅសល់តែ {stock} ប៉ុណ្ណោះ)"
    elif can_afford:
        status_line = f"✅ <b>ទឹកប្រាក់គ្រប់គ្រាន់</b> (នៅសល់: ${(user_balance - total_price):.2f})"
    else:
        status_line = f"❌ <b>ទឹកប្រាក់មិនគ្រប់គ្រាន់ទេ!</b> (ត្រូវការ ${total_price:.2f} ខ្វះ ${(total_price - user_balance):.2f})"

    confirm_text = (
        f"🛒 <b>បញ្ជាក់ការបញ្ជាទិញ (Confirm Purchase)</b>\n"
        f"{'─'*32}\n"
        f"📦 <b>ទំនិញ:</b> {name}\n"
        f"🔢 <b>ចំនួនទិញ:</b> {qty} code(s)\n"
        f"💵 <b>តម្លៃសរុប:</b> <b>${total_price:.2f}</b> (${sell_price:.2f} / code)\n"
        f"📦 <b>ស្តុកនៅសល់:</b> {stock}\n"
        f"{'─'*32}\n"
        f"💰 <b>ទឹកប្រាក់របស់អ្នក:</b> {bal_text}\n"
        f"{status_line}"
    )

    mk = InlineKeyboardMarkup()
    if stock_ok and can_afford:
        mk.row(InlineKeyboardButton("✅ Confirm & Pay", callback_data=f"dopay_{product_id}_{qty}"))
        mk.row(InlineKeyboardButton("🛒 Add to Cart", callback_data="cart_add"))
        mk.row(
            InlineKeyboardButton("🐥 Change Qty", callback_data=f"qtyselect_{product_id}"),
            InlineKeyboardButton("🚪 Home", callback_data="home")
        )
    elif not can_afford:
        mk.row(InlineKeyboardButton("🏦 បញ្ចូលប្រាក់ (Top Up)", callback_data="cmd_topup"))
        mk.row(
            InlineKeyboardButton("🐥 Change Qty", callback_data=f"qtyselect_{product_id}"),
            InlineKeyboardButton("🚪 Home", callback_data="home")
        )
    else:
        mk.row(
            InlineKeyboardButton("🐥 Change Qty", callback_data=f"qtyselect_{product_id}"),
            InlineKeyboardButton("🚪 Home", callback_data="home")
        )

    if message_id_to_edit:
        try:
            bot.edit_message_text(confirm_text, chat_id, message_id_to_edit,
                                  parse_mode="HTML", reply_markup=mk)
            return
        except:
            pass
    bot.send_message(chat_id, confirm_text, parse_mode="HTML", reply_markup=mk)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cfmq_"))
def cb_confirm_qty(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    raw = call.data.replace("cfmq_", "")
    parts = raw.split("_")
    product_id = parts[0]
    qty = int(parts[1]) if len(parts) > 1 else 1
    show_confirmation(call.message.chat.id, call.from_user.id, product_id, qty, call.message.message_id)

# ================= PAYMENT EXECUTION =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("dopay_"))
def cb_execute_pay(call):
    if not check_member_or_prompt(call):
        return
    bot.answer_callback_query(call.id)
    raw = call.data.replace("dopay_", "")
    parts = raw.split("_")
    product_id = parts[0]
    qty = int(parts[1]) if len(parts) > 1 else 1
    user_id = call.from_user.id

    # Remove inline buttons immediately to prevent duplicate clicks
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=InlineKeyboardMarkup())
    except:
        pass

    processing_msg = bot.send_message(call.message.chat.id, "⏳ កំពុងដំណើរការកាត់ប្រាក់ និងទាញយកទំនិញ... សូមរង់ចាំ!")

    # Verify product again with live API data
    products = get_filtered_products(force_refresh=True)
    target_product = next((p for p in products if str(p.get("id")) == product_id), None)
    if not target_product:
        bot.edit_message_text("❌ រកមិនឃើញទំនិញនេះទៀតទេ ឬតម្លៃលើស $10!", call.message.chat.id, processing_msg.message_id)
        return

    original_price = safe_float(target_product.get("price", 0))
    sell_price = calculate_sell_price(original_price)
    total_price = round(sell_price * qty, 2)
    product_name = target_product.get("name", "N/A")
    stock = int(target_product.get("stock", 0) or 0)

    if stock < qty:
        bot.edit_message_text(f"❌ ស្តុកមិនគ្រប់គ្រាន់ទេ! (នៅសល់តែ {stock} ប៉ុណ្ណោះ)",
                              call.message.chat.id, processing_msg.message_id)
        return

    # Deduct balance
    if user_id != ADMIN_ID:
        user_balance = get_user_balance(user_id)
        if user_balance < total_price:
            bot.edit_message_text(
                f"❌ ទឹកប្រាក់របស់អ្នកមិនគ្រប់គ្រាន់ទេ! (មាន: ${user_balance:.2f} ត្រូវការ: ${total_price:.2f})",
                call.message.chat.id, processing_msg.message_id
            )
            return
        if not deduct_user_balance(user_id, total_price, f"ទិញ {qty}x: {product_name}"):
            bot.edit_message_text("❌ មានបញ្ហាក្នុងការកាត់ប្រាក់!", call.message.chat.id, processing_msg.message_id)
            return

    # Call Zoom API Purchase
    idempotency_key = str(uuid.uuid4())
    payload = {"product_id": product_id, "quantity": qty}
    headers = {"Idempotency-Key": idempotency_key}
    buy_res = call_zoom_api("POST", "/purchase", json_data=payload, extra_headers=headers)

    try:
        bot.delete_message(call.message.chat.id, processing_msg.message_id)
    except:
        pass

    if buy_res.get("success"):
        codes = buy_res.get("codes", [])
        keys_list = list(codes)
        codes_str = "\n".join(keys_list)
        ts_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        remaining_balance = get_user_balance(user_id) if user_id != ADMIN_ID else None

        # 1️⃣ សារជោគជ័យ (ជាអចិន្ត្រៃ មិនលុបចេញជាដាច់ខាត)
        success_msg = (
            f"✅ **ការបញ្ជាទិញជោគជ័យ! (Purchase Successful)**\n"
            f"{'═'*32}\n"
            f"📦 **ទំនិញ:** {product_name}\n"
            f"🔢 **ចំនួន:** {qty} code(s)\n"
            f"💵 **តម្លៃបានបង់:** `${total_price:.2f}`\n"
            f"🕐 **កាលបរិច្ឆេទ:** `{ts_now}`\n"
            f"{'─'*32}\n"
            f"🔑 **Key / Code របស់អ្នក:**\n"
            f"```\n{codes_str}\n```\n"
            f"{'─'*32}\n"
        )
        if remaining_balance is not None:
            success_msg += f"💰 **ទឹកប្រាក់នៅសល់:** `${remaining_balance:.2f}`\n"
        success_msg += "\n📎 *ខ្ញុំបានផ្ញើ File .txt ជូនអ្នកផងដែរ ដើម្បីងាយរក្សាទុក!*"

        bot.send_message(call.message.chat.id, success_msg, parse_mode="Markdown")

        # 2️⃣ ផ្ញើជា file .txt (ជាអចិន្ត្រៃ ងាយស្រួលរក្សាទុក)
        txt_content = (
            f"========================================\n"
            f"        SSONLINE STORE - RECEIPT      \n"
            f"========================================\n"
            f"Product  : {product_name}\n"
            f"Quantity : {qty}\n"
            f"Price    : ${total_price:.2f} (${sell_price:.2f}/code)\n"
            f"Date/Time: {ts_now}\n"
            f"User ID  : {user_id}\n"
            f"========================================\n"
            f"YOUR KEY(S) / CODE(S):\n"
            f"----------------------------------------\n"
            f"{codes_str}\n"
            f"========================================\n"
            f"Thank you for shopping at SSONLINE Store!\n"
            f"Support: @limsorn\n"
        )
        file_bytes = io.BytesIO(txt_content.encode('utf-8'))
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', product_name)[:25]
        file_bytes.name = f"SSONLINE_{safe_name}_{user_id}.txt"
        bot.send_document(call.message.chat.id, file_bytes, caption=f"📄 Receipt: {product_name} (Qty: {qty})")

        # 3️⃣ កត់ត្រាទុកក្នុង Firebase RTDB ជារៀងរហូត
        log_purchase(user_id, product_id, product_name, total_price, keys_list, quantity=qty)
        log_transaction(user_id, "BUY", total_price, f"ទិញ {qty}x: {product_name}")

    else:
        # Refund if failed
        if user_id != ADMIN_ID:
            add_user_balance(user_id, total_price)

        error_code = buy_res.get("code", "")
        if error_code == "INSUFFICIENT_BALANCE":
            err_msg = "❌ លុយក្នុង API មិនគ្រប់! សូមទាក់ទង Admin។ (លុយបានបង្វិលចូលកាបូបវិញ)"
        elif error_code == "OUT_OF_STOCK":
            err_msg = "❌ ទំនិញនេះទើបតែអស់ស្តុក! (លុយបានបង្វិលចូលកាបូបវិញ)"
        elif error_code == "PRODUCT_NOT_FOUND":
            err_msg = "❌ រកមិនឃើញទំនិញនេះ! (លុយបានបង្វិលចូលកាបូបវិញ)"
        else:
            err_msg = f"❌ ការទិញបរាជ័យ (Code: {error_code})! លុយបានបង្វិលចូលកាបូបរបស់អ្នកវិញរួចរាល់។"
        bot.send_message(call.message.chat.id, err_msg)


# ================= Admin Commands =================
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
    try:
        json_data = request.get_data().decode('utf-8')
        if json_data:
            update = telebot.types.Update.de_json(json_data)
            if update:
                bot.process_new_updates([update])
    except Exception as e:
        print(f"Update processing error: {e}")
    return "!", 200

@app.route("/", methods=['GET', 'HEAD', 'POST'])
@app.route("/health", methods=['GET', 'HEAD'])
@app.route("/healthz", methods=['GET', 'HEAD'])
@app.route("/ping", methods=['GET', 'HEAD'])
def health_check():
    return "SSONLINE AI SHOP Bot is running!", 200

COMMANDS_INITIALIZED = False

def set_bot_commands():
    global COMMANDS_INITIALIZED
    from telebot.types import BotCommand
    commands = [
        BotCommand("start", "🏠 ផ្ទាំងដើម (Main Menu)"),
        BotCommand("shop", "🛍️ មើលទំនិញទាំងអស់ (All Products)"),
        BotCommand("topup", "💰 បញ្ចូលទឹកប្រាក់ (Top Up)"),
        BotCommand("myorders", "📋 ប្រវត្តិទិញទំនិញ (My Orders)"),
        BotCommand("info", "👤 គណនី និងទឹកប្រាក់ (Profile)")
    ]
    try:
        try:
            bot.delete_my_commands()
        except Exception as e_del:
            print(f"delete_my_commands note: {e_del}")
        bot.set_my_commands(commands)
        COMMANDS_INITIALIZED = True
        print("✅ Telegram bot menu commands successfully updated!")
    except Exception as e:
        print(f"❌ set_bot_commands error: {e}")

@bot.message_handler(commands=['setmenu', 'updatemenu'])
def cmd_force_update_menu(message):
    if message.from_user.id != ADMIN_ID:
        return
    msg = bot.reply_to(message, "⏳ កំពុង Reset និង Update Telegram Menu Commands...")
    try:
        set_bot_commands()
        bot.edit_message_text("✅ បាន Update Menu Commands នៅខាងឆ្វេងជោគជ័យ ១០០%!", message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, msg.message_id)

def init_background_services():
    """ដំណើរការក្នុង Background មិនឲ្យរំខាន ឬទាញឲ្យ Server ចាប់ផ្តើមយឺតឡើយ"""
    time.sleep(2)  # រង់ចាំ 2 វិនាទីឲ្យ Flask Server ចាប់ផ្តើម listening លើ Port រួចរាល់
    
    # 1. កំណត់ Webhook បើមាន WEBHOOK_URL
    if WEBHOOK_URL and TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != 'YOUR_TELEGRAM_TOKEN_HERE':
        try:
            bot.remove_webhook()
            time.sleep(1)
            webhook_full = WEBHOOK_URL.rstrip('/') + '/' + TELEGRAM_BOT_TOKEN
            bot.set_webhook(url=webhook_full)
            print(f"✅ Webhook successfully set to: {WEBHOOK_URL}")
        except Exception as e:
            print(f"❌ set_webhook error: {e}")

    # 2. Update Telegram commands
    try:
        set_bot_commands()
    except Exception as e:
        print(f"❌ set_bot_commands error: {e}")

    # 3. Pre-warm products cache
    try:
        get_filtered_products(force_refresh=True)
        print("✅ Products cache pre-warmed successfully!")
    except Exception as e:
        print(f"❌ Warmup error: {e}")

    # 4. Keep-alive ping loop for Render free tier (ការពារកុំឲ្យ Render ដេកលក់)
    if WEBHOOK_URL:
        ping_url = WEBHOOK_URL.rstrip('/') + '/'
        while True:
            try:
                time.sleep(540)  # Ping រៀងរាល់ 9 នាទីម្តង
                requests.get(ping_url, timeout=10)
            except Exception:
                pass

# ចាប់ផ្តើម Background Services ដោយមិន block Main Thread
threading.Thread(target=init_background_services, daemon=True).start()

if __name__ == '__main__':
    # យក Port ពី Render (Default 10000 ឬ 5000)
    port = int(os.environ.get('PORT', 10000))
    # threaded=True ធានាថា Flask ឆ្លើយតប Health Check របស់ Render ភ្លាមៗ (Instant 200 OK)
    app.run(host='0.0.0.0', port=port, threaded=True)
