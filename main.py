import asyncio
from datetime import datetime, timedelta, timezone
import glob
import json
import os
import re
import sys
import time
from threading import Thread
from flask import Flask

# استيراد PIL و NudeNet لفحص الصور والمحتوى
from PIL import Image
from nudenet import NudeDetector

# استيراد مكتبة Telethon
import telethon
from telethon import Button, TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.types import BotCommand, BotCommandScopeDefault, Channel, Chat

# --- إعدادات الـ API والتحكم الأساسي ---
API_ID = 21799597
API_HASH = '4e7a8aee718c1e8e63956fec3339d01d'
BOT_TOKEN = '8848042206:AAG1iGAxLIppkWk8ejr0tIdhUa23N5YLKYc'
ADMIN_ID = 8111089651

# تهيئة فاحص الصور الذكي
detector = NudeDetector()

# --- سيرفر Flask المدمج لمنع توقف الخدمة في Render ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Main Bot Service is Active and Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# تشغيل سيرفر Flask في مسار جانبي (Thread)
Thread(target=run_flask, daemon=True).start()

# --- إعدادات المجلدات وملفات الأمان ---
BASE_SESSIONS_DIR = 'sessions_users'
ALLOWED_USERS_FILE = 'allowed_users.json'
GLOBAL_JOINED_FILE = 'global_joined_links.txt'
GLOBAL_WA_FILE = 'global_wa_links.txt'
SHARED_PRIVATE_FILE = 'shared_private_groups.txt'
LEAVE_LOCKED_SETTINGS_FILE = 'leave_locked_settings.json'

TG_LINK_REGEX = r'(https?://(?:t\.me|telegram\.me)/(?:joinchat/|\+)?[\w-]+)'
WA_LINK_REGEX = r'(https?://chat\.whatsapp\.com/[\w-]+)'

# الكلمات الإباحية للفلترة النصية
EXPLICIT_KEYWORDS = [
    'سكس', 'إباحي', 'اباحي', 'سكسي', 'تعري', 'مقاطع 18', 'افلام 18', 'شرموطة', 'زب', 
    'كس', 'نياك', 'طيز', 'نيك', 'قحبة', 'سحاق', 'ورعان', 'موجب', 'سالب', 'ديوث',
    'porn', 'sex', 'nsfw', 'xvideo', 'hentai', 'xnxx', 'erotic', 'adult 18+',
    'paja', 'placer', 'caliente', 'squirt', 'modelos', 'las girls', 'nude', 'xxx',
    'onlyfans', 'leak', 'stripper', 'hot', 'topless', 'bitch', '🔞', '💦', '🍑', '🍆', '👙'
]

# تصنيفات الحظر عند فحص الصور بالذكاء الاصطناعي
EXPLICIT_LABELS = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED", "MALE_BREAST_EXPOSED"
]

if not os.path.exists(BASE_SESSIONS_DIR):
    os.makedirs(BASE_SESSIONS_DIR)

# --- دمج فحص الصور والنصوص ---
def is_explicit_text(text):
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in EXPLICIT_KEYWORDS)

def is_explicit_image(image_path):
    try:
        detections = detector.detect(image_path)
        for item in detections:
            if item['class'] in EXPLICIT_LABELS and item['score'] > 0.5:
                return True
    except Exception:
        pass
    return False

# --- إدارة المستخدمين والإعدادات ---
def load_allowed_users():
    if os.path.exists(ALLOWED_USERS_FILE):
        with open(ALLOWED_USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return [ADMIN_ID]

def save_allowed_user(user_id):
    users = load_allowed_users()
    if user_id not in users:
        users.append(user_id)
        with open(ALLOWED_USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f)

def remove_allowed_user(user_id):
    users = load_allowed_users()
    if user_id in users and user_id != ADMIN_ID:
        users.remove(user_id)
        with open(ALLOWED_USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f)

def load_leave_locked_settings():
    if os.path.exists(LEAVE_LOCKED_SETTINGS_FILE):
        with open(LEAVE_LOCKED_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def is_leave_locked_enabled(user_id):
    settings = load_leave_locked_settings()
    return settings.get(str(user_id), False)

def set_leave_locked_setting(user_id, status: bool):
    settings = load_leave_locked_settings()
    settings[str(user_id)] = status
    with open(LEAVE_LOCKED_SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f)

def load_list_from_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    return []

def save_to_file(file_path, data_list):
    with open(file_path, 'w', encoding='utf-8') as f:
        for item in data_list:
            f.write(f'{item}\n')

def append_to_file(file_path, new_items):
    data = load_list_from_file(file_path)
    for item in new_items:
        if item not in data:
            data.append(item)
    save_to_file(file_path, data)

user_states = {}
running_tasks = {}
stop_signals = {}
flood_expiry = {}
join_delays = {}
current_action_status = {}

bot = TelegramClient('manager_control_bot', API_ID, API_HASH)

def get_user_delay(user_id):
    return join_delays.get(user_id, 12)

def get_user_folder(user_id):
    folder = os.path.join(BASE_SESSIONS_DIR, str(user_id))
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

async def get_active_accounts(user_id):
    user_folder = get_user_folder(user_id)
    saved_sessions = glob.glob(f'{user_folder}/*.session')
    return [os.path.basename(p).replace('.session', '') for p in saved_sessions]

# --- تصميم لوحة التحكم ---
def main_keyboard(user_id):
    leave_status = "🟢 مفعل" if is_leave_locked_enabled(user_id) else "🔴 معطل"
    kb = [
        [
            Button.inline('➕ إضافة حساب', b'add_acc'),
            Button.inline('👥 الحسابات', b'manage_accs'),
        ],
        [
            Button.inline('📥 إضافة ملف روابط للكل', b'add_bulk_file'),
            Button.inline('🔗 إضافة روابط لحساب', b'add_links_menu'),
        ],
        [
            Button.inline('📦 سجل الانضمام العام', b'stored_links_menu'),
            Button.inline('📱 سجل روابط الواتس العام', b'global_wa_menu'),
        ],
        [
            Button.inline('🔒 جروبات خاصة', b'view_shared_private'),
            Button.inline(f'🚪 مغادرة المقفلة [{leave_status}]', b'toggle_leave_locked'),
        ],
        [
            Button.inline('▶️ تشغيل المدير', b'start_manager'),
            Button.inline('⏹ إيقاف المدير', b'stop_manager'),
        ],
        [
            Button.inline('📊 الإحصائيات', b'view_stats'),
            Button.inline('⏳ الانتظارات', b'view_delays'),
        ],
        [
            Button.inline('♻️ استخراج يدوي للروابط', b'manual_extract'),
            Button.inline('⚙️ الإعدادات', b'settings'),
        ],
        [
            Button.inline('ℹ️ الحالة', b'system_status'),
        ]
    ]
    if user_id == ADMIN_ID:
        kb.append([Button.inline('👥 إدارة المستخدمين', b'manage_users')])
    kb.append([Button.inline('❌ إلغاء العملية الجارية', b'cancel_state')])
    return kb

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    if user_id not in load_allowed_users():
        return await event.respond('⚠️ عذراً، هذا البوت خاص.')

    user_states[user_id] = None
    await event.respond(
        '⭐ **مرحباً بك في مدير الانضمام والتنظيف الذكي للمحتوى**',
        buttons=main_keyboard(user_id),
    )

# --- دالة فحص وتنظيف المجموعة شاملة الوسائط والنصوص ---
async def check_and_leave_if_inappropriate(client, user_id, phone, target, link):
    temp_dir = "temp_media"
    os.makedirs(temp_dir, exist_ok=True)
    try:
        full_entity = await client.get_entity(target)
        title = getattr(full_entity, 'title', '')
        
        # 1. فحص الاسم والنص
        if is_explicit_text(title):
            await client(LeaveChannelRequest(full_entity))
            await bot.send_message(user_id, f'🔞 [{phone}]: تم اكتشاف اسم إباحي -> تم المغادرة 🚪\n🔗 {link}')
            return True

        # 2. فحص صورة البروفايل
        try:
            photo_path = await client.download_profile_photo(full_entity, file=os.path.join(temp_dir, f"{phone}_prof.jpg"))
            if photo_path and is_explicit_image(photo_path):
                if os.path.exists(photo_path): os.remove(photo_path)
                await client(LeaveChannelRequest(full_entity))
                await bot.send_message(user_id, f'🔞 [{phone}]: تم اكتشاف صورة بروفايل إباحية -> تم المغادرة 🚪\n🔗 {link}')
                return True
            if photo_path and os.path.exists(photo_path): os.remove(photo_path)
        except Exception:
            pass

        # 3. فحص آخر الرسائل والصور داخل المجموعة
        async for msg in client.iter_messages(full_entity, limit=15):
            msg_text = msg.text or msg.caption or ""
            if is_explicit_text(msg_text):
                await client(LeaveChannelRequest(full_entity))
                await bot.send_message(user_id, f'🔞 [{phone}]: تم اكتشاف نص إباحي بالرسائل -> تم المغادرة 🚪\n🔗 {link}')
                return True

            if msg.photo:
                try:
                    media_path = await msg.download_media(file=os.path.join(temp_dir, f"{phone}_msg.jpg"))
                    if media_path and is_explicit_image(media_path):
                        if os.path.exists(media_path): os.remove(media_path)
                        await client(LeaveChannelRequest(full_entity))
                        await bot.send_message(user_id, f'🔞 [{phone}]: تم اكتشاف صورة إباحية بالمجموعة -> تم المغادرة 🚪\n🔗 {link}')
                        return True
                    if media_path and os.path.exists(media_path): os.remove(media_path)
                except Exception:
                    pass

        # 4. فحص قفل الكتابة
        if is_leave_locked_enabled(user_id):
            if hasattr(full_entity, 'default_banned_rights') and full_entity.default_banned_rights:
                if full_entity.default_banned_rights.send_messages:
                    await client(LeaveChannelRequest(full_entity))
                    await bot.send_message(user_id, f'🔒 [{phone}]: المجموعة مقفلة -> تم المغادرة 🚪\n🔗 {link}')
                    return True

    except Exception as e:
        print(f"[⚠️] خطأ أثناء فحص الحساب {phone}: {e}")
    
    return False

print("البوت يعمل الآن على Render...")
bot.start(bot_token=BOT_TOKEN)
bot.run_until_disconnected()
