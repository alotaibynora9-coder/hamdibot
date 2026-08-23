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

import telethon
from telethon import Button, TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    ImportChatInviteRequest,
)
from telethon.tl.types import BotCommand, BotCommandScopeDefault, Channel, Chat

try:
    from nudenet import NudeDetector
    detector = NudeDetector()
except Exception as e:
    detector = None

API_ID = 21799597
API_HASH = '4e7a8aee718c1e8e63956fec3339d01d'
BOT_TOKEN = '8596141491:AAHIJxZhl_y0wW89o_712h_9DqGIH6qKkw8'
ADMIN_ID = 7226664693

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Main Bot Service is Active and Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

BASE_SESSIONS_DIR = 'sessions_users'
ALLOWED_USERS_FILE = 'allowed_users.json'
GLOBAL_JOINED_FILE = 'global_joined_links.txt'
GLOBAL_WA_FILE = 'global_wa_links.txt'
SHARED_PRIVATE_FILE = 'shared_private_groups.txt'
LEAVE_LOCKED_SETTINGS_FILE = 'leave_locked_settings.json'

TG_LINK_REGEX = r'(https?://(?:t\.me|telegram\.me)/(?:joinchat/|\+)?[\w-]+)'
WA_LINK_REGEX = r'(https?://chat\.whatsapp\.com/[\w-]+)'

NSFW_KEYWORDS = [
    'سكس', 'إباحي', 'اباحي', 'سكسي', 'تعري', 'مقاطع 18', 'افلام 18', 'شرموطة', 'زب', 
    'كس', 'نياك', 'طيز', 'نيك', 'قحبة', 'سحاق', 'ورعان', 'موجب', 'سالب', 'ديوث',
    'porn', 'sex', 'nsfw', 'xvideo', 'hentai', 'xnxx', 'erotic', 'adult 18+'
]

EXPLICIT_KEYWORDS = [
    "سكس", "جنس", "اباحي", "إباحي", "شرموط", "قحبة", "دعارة", "فضايح", "فضيحة",
    "سكسي", "تعري", "نيك", "ممحونة", "ورعان", "طيز", "زب", "كس", "افلام جنس",
    "porn", "paja", "placer", "caliente", "squirt", "modelos", "las girls",
    "sex", "nude", "adult", "18+", "nsfw", "xxx", "erotic", "hentai", "vip activo",
    "onlyfans", "leak", "stripper", "hot", "topless", "bitch",
    "🔞", "💦", "🍑", "🍆", "👙"
]

EXPLICIT_LABELS = [
    "BUTTOCKS_EXPOSED", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED", "MALE_BREAST_EXPOSED"
]

if not os.path.exists(BASE_SESSIONS_DIR):
    os.makedirs(BASE_SESSIONS_DIR)

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

def load_failed_links(user_folder, phone):
    file_path = os.path.join(user_folder, f'failed_{phone}_links.json')
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_failed_link(user_folder, phone, link, reason):
    file_path = os.path.join(user_folder, f'failed_{phone}_links.json')
    failed_data = load_failed_links(user_folder, phone)
    failed_data[link] = {'reason': str(reason), 'timestamp': time.time()}
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(failed_data, f, ensure_ascii=False, indent=4)

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

def is_explicit_text(text):
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in EXPLICIT_KEYWORDS)

def is_explicit_image(image_path):
    if not detector or not os.path.exists(image_path):
        return False
    try:
        detections = detector.detect(image_path)
        for item in detections:
            if item['class'] in EXPLICIT_LABELS and item['score'] > 0.5:
                return True
    except Exception:
        pass
    return False

async def inspect_and_clean_dialogs(client, phone):
    left_count = 0
    temp_dir = f"temp_media_{phone.replace('+', '')}"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, (Channel, Chat)):
                continue

            title = dialog.name or ""
            is_explicit = False

            if is_explicit_text(title):
                is_explicit = True

            if not is_explicit:
                try:
                    photo_path = await client.download_profile_photo(entity, file=os.path.join(temp_dir, "profile.jpg"))
                    if photo_path and is_explicit_image(photo_path):
                        is_explicit = True
                    if photo_path and os.path.exists(photo_path):
                        os.remove(photo_path)
                except Exception:
                    pass

            if not is_explicit:
                try:
                    async for message in client.iter_messages(entity, limit=15):
                        msg_text = message.text or message.caption or ""
                        if is_explicit_text(msg_text):
                            is_explicit = True
                            break

                        if message.photo or message.video:
                            try:
                                media_path = await message.download_media(file=os.path.join(temp_dir, "msg_media"))
                                if media_path and is_explicit_image(media_path):
                                    is_explicit = True
                                    if os.path.exists(media_path):
                                        os.remove(media_path)
                                    break
                                if media_path and os.path.exists(media_path):
                                    os.remove(media_path)
                            except Exception:
                                pass
                except Exception:
                    pass

            if is_explicit:
                try:
                    await client(LeaveChannelRequest(entity))
                    left_count += 1
                    await asyncio.sleep(2)
                except Exception:
                    pass
    except Exception:
        pass

    try:
        for f in os.listdir(temp_dir):
            os.remove(os.path.join(temp_dir, f))
        os.rmdir(temp_dir)
    except Exception:
        pass

    return left_count

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
            Button.inline('🗑️ مغادرة القروبات الضاره', b'clean_bad_groups'),
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

def settings_delay_keyboard():
    return [
        [
            Button.inline('⏱️ 5 دقائق', b'set_delay_5'),
            Button.inline('⏱️ 10 دقائق', b'set_delay_10'),
        ],
        [Button.inline('⚙️ مخصص (إدخال يدوي)', b'set_delay_custom')],
        [Button.inline('🔙 رجوع للوحة الرئيسية', b'back_to_main')],
    ]

async def set_bot_commands():
    commands = [
        BotCommand(command='start', description='🚀 تشغيل البوت وفتح لوحة التحكم الرئيسية'),
        BotCommand(command='status', description='ℹ️ عرض حالة المحرك والحسابات الحالية'),
        BotCommand(command='stop', description='⏹ إيقاف محرك الانضمام التلقائي فوراً'),
    ]
    try:
        await bot(SetBotCommandsRequest(scope=BotCommandScopeDefault(), lang_code='', commands=commands))
    except Exception:
        pass

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    allowed_users = load_allowed_users()

    if user_id not in allowed_users:
        user_info = (
            f'👤 الاسم: {event.sender.first_name}\n🆔 الآيدي:'
            f' `{user_id}`\n🏷 اليوزر:'
            f' @{event.sender.username if event.sender.username else "لا يوجد"}'
        )
        await bot.send_message(
            ADMIN_ID,
            '🔔 **طلب إذن دخول جديد إلى البوت:**\n\n'
            f'{user_info}\n\n'
            'هل تريد السماح له باستخدام البوت؟',
            buttons=[[
                Button.inline('✅ موافقة وسماح', f'auth_accept_{user_id}'.encode()),
                Button.inline('❌ رفض الطلب', f'auth_reject_{user_id}'.encode()),
            ]],
        )
        return await event.respond(
            '⚠️ **عذراً، هذا البوت خاص ومقفل.**\n\n'
            'يرجى الانتظار لحين قبول طلبك من المسؤول.'
        )

    user_states[user_id] = None
    await event.respond(
        '⭐ **مرحباً بك في مدير الانضمام والاستخراج التلقائي المطور**\n\n'
        'تم تفعيل الاستخراج التلقائي اليومي، فصل الروابط، الفلترة الذكية للمحتوى الإباحي، والانضمام التلقائي المتقدم.',
        buttons=main_keyboard(user_id),
    )

@bot.on(events.NewMessage(pattern='/status'))
async def status_command_handler(event):
    user_id = event.sender_id
    if user_id not in load_allowed_users():
        return
    event.data = b'system_status'
    await callback_handler(event)

@bot.on(events.NewMessage(pattern='/stop'))
async def stop_command_handler(event):
    user_id = event.sender_id
    if user_id not in load_allowed_users():
        return
    event.data = b'stop_manager'
    await callback_handler(event)

async def extract_links_from_account(user_id, phone):
    user_folder = get_user_folder(user_id)
    session_file = os.path.join(user_folder, f'{phone}.session')

    if not os.path.exists(session_file):
        return 0, 0

    client = TelegramClient(session_file, API_ID, API_HASH)
    tg_links = set()
    wa_links = set()

    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return 0, 0

        cutoff_date = datetime.now(timezone.utc) - timedelta(hours=24)

        async for dialog in client.iter_dialogs(limit=100):
            try:
                async for msg in client.iter_messages(dialog.entity, offset_date=cutoff_date, limit=200):
                    if msg.text:
                        found_tg = re.findall(TG_LINK_REGEX, msg.text)
                        found_wa = re.findall(WA_LINK_REGEX, msg.text)
                        for link in found_tg:
                            tg_links.add(link)
                        for link in found_wa:
                            wa_links.add(link)
            except Exception:
                continue

        await client.disconnect()
    except Exception:
        return 0, 0

    tg_file = os.path.join(user_folder, f'extracted_tg_{phone}.txt')
    wa_file = os.path.join(user_folder, f'extracted_wa_{phone}.txt')

    append_to_file(tg_file, list(tg_links))
    append_to_file(wa_file, list(wa_links))

    if wa_links:
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        append_to_file(global_wa_path, list(wa_links))

    if tg_links:
        links_file = os.path.join(user_folder, f'custom_{phone}_links.txt')
        append_to_file(links_file, list(tg_links))

    return len(tg_links), len(wa_links)

async def run_full_extraction_and_distribute(user_id):
    user_folder = get_user_folder(user_id)
    accounts = await get_active_accounts(user_id)
    if not accounts:
        return 0, 0

    total_tg, total_wa = 0, 0
    new_tg_all = set()

    for phone in accounts:
        tg_count, wa_count = await extract_links_from_account(user_id, phone)
        total_tg += tg_count
        total_wa += wa_count

        tg_file = os.path.join(user_folder, f'extracted_tg_{phone}.txt')
        for link in load_list_from_file(tg_file):
            new_tg_all.add(link)

    global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
    global_joined = set(load_list_from_file(global_joined_path))
    available_tg = [l for l in new_tg_all if l not in global_joined]

    if available_tg and accounts:
        chunk_size = (len(available_tg) + len(accounts) - 1) // len(accounts)
        for i, phone in enumerate(accounts):
            acc_chunk = available_tg[i * chunk_size : (i + 1) * chunk_size]
            if acc_chunk:
                links_file = os.path.join(user_folder, f'custom_{phone}_links.txt')
                append_to_file(links_file, acc_chunk)

    return total_tg, total_wa

async def scheduled_daily_extraction():
    while True:
        now = datetime.now()
        next_run = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        wait_seconds = (next_run - now).total_seconds()

        await asyncio.sleep(wait_seconds)

        allowed_users = load_allowed_users()
        for user_id in allowed_users:
            try:
                tg, wa = await run_full_extraction_and_distribute(user_id)
                await bot.send_message(
                    user_id,
                    '🕒 **تقرير الاستخراج التلقائي اليومي:**\n\n'
                    f'• `{tg}` رابط تلجرام جديد.\n• `{wa}` رابط واتساب جديد.',
                )
            except Exception:
                pass

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    allowed_users = load_allowed_users()
    data = event.data

    if data.startswith(b'auth_'):
        if user_id != ADMIN_ID:
            return await event.answer('⚠️ هذا الخيار متاح للمطور الأساسي فقط!', alert=True)

        action, target_id = data.decode().split('_')[1], int(data.decode().split('_')[2])
        if action == 'accept':
            save_allowed_user(target_id)
            await event.edit(f'✅ تم قبول المستخدم `{target_id}` بنجاح.')
            await bot.send_message(target_id, '🎉 **تهانينا! تم موافقة المسؤول.**\nأرسل /start الآن لفتح اللوحة.')
        else:
            await event.edit(f'❌ تم رفض طلب المستخدم `{target_id}`.')
            await bot.send_message(target_id, '❌ عذراً، تم رفض طلبك.')
        return

    if user_id not in allowed_users:
        return await event.answer('⚠️ غير مصرح لك باستخدام هذه اللوحة.', alert=True)

    user_folder = get_user_folder(user_id)

    if data == b'clean_bad_groups':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات مضافة لفحصها!', alert=True)

        await event.edit('🔍 **جاري فحص جميع الحسابات ومغادرة القروبات الضارة...**\n\nيرجى الانتظار.')
        
        total_cleaned = 0
        for phone in accounts:
            session_file = os.path.join(user_folder, f'{phone}.session')
            if not os.path.exists(session_file):
                continue

            client = TelegramClient(session_file, API_ID, API_HASH)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    count = await inspect_and_clean_dialogs(client, phone)
                    total_cleaned += count
                await client.disconnect()
            except Exception:
                pass

        await event.edit(
            f'✅ **تم الانتهاء من الفحص!**\n\n• إجمالي القروبات المغادَرة: `{total_cleaned}`',
            buttons=main_keyboard(user_id)
        )

    elif data == b'toggle_leave_locked':
        current = is_leave_locked_enabled(user_id)
        new_status = not current
        set_leave_locked_setting(user_id, new_status)
        status_msg = "تم تفعيل مغادرة المجموعات المقفلة ✅" if new_status else "تم إيقاف مغادرة المجموعات المقفلة 🔴"
        await event.answer(status_msg, alert=True)
        await event.edit('⭐ **اللوحة الرئيسية:**', buttons=main_keyboard(user_id))

    elif data == b'add_acc':
        user_states[user_id] = {'action': 'waiting_phone'}
        await event.edit('➕ **إضافة حساب جديد**\n\nأرسل رقم الهاتف مع مفتاح الدولة الآن.\nمثال: `+9665XXXXXXXX`', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'add_bulk_file':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات نشطة مضافة!', alert=True)

        user_states[user_id] = {'action': 'waiting_bulk_file'}
        await event.edit('📥 **إضافة ملف روابط للكل**\n\nأرسل ملف (.txt) يحتوي على الروابط الآن.', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'manage_accs':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            await event.edit('❌ لا توجد حسابات مضافة حالياً.', buttons=main_keyboard(user_id))
        else:
            text = '👥 **قائمة الحسابات:**'
            buttons = []
            for idx, acc in enumerate(accounts, 1):
                buttons.append([Button.inline(f'#{idx} - 📱 {acc}', f'viewacc_{acc}'.encode())])
            buttons.append([Button.inline('🔙 رجوع', b'back_to_main')])
            await event.edit(text, buttons=buttons)

    elif data.startswith(b'viewacc_'):
        acc_name = data.decode().replace('viewacc_', '')
        text = f'⚙️ **إدارة الحساب:** `{acc_name}`'
        buttons = [
            [Button.inline('1-تلجرام', f'ex_tg_{acc_name}'.encode()), Button.inline('2-واتساب', f'ex_wa_{acc_name}'.encode())],
            [Button.inline('📊 تقرير الروابط', f'accstatus_{acc_name}'.encode())],
            [Button.inline('❌ حذف الحساب', f'del_{acc_name}'.encode())],
            [Button.inline('🔙 رجوع', b'manage_accs')],
        ]
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'ex_tg_'):
        acc_name = data.decode().replace('ex_tg_', '')
        tg_file = os.path.join(user_folder, f'extracted_tg_{acc_name}.txt')
        links = load_list_from_file(tg_file)

        if not links:
            await event.answer('ℹ️ لا توجد روابط تلجرام مستخرجة', alert=True)
        else:
            links_text = '\n'.join(links)
            if len(links_text) > 3900:
                file_path = os.path.join(user_folder, 'tg_extracted.txt')
                save_to_file(file_path, links)
                await bot.send_file(user_id, file_path, caption=f'📥 روابط التلجرام (`{acc_name}`)')
            else:
                await event.edit(f'📥 **روابط التلجرام (`{acc_name}`):**\n\n{links_text}', buttons=[[Button.inline('🔙 رجوع', f'viewacc_{acc_name}'.encode())]])

    elif data.startswith(b'ex_wa_'):
        acc_name = data.decode().replace('ex_wa_', '')
        wa_file = os.path.join(user_folder, f'extracted_wa_{acc_name}.txt')
        links = load_list_from_file(wa_file)

        if not links:
            await event.answer('ℹ️ لا توجد روابط واتساب مستخرجة', alert=True)
        else:
            links_text = '\n'.join(links)
            if len(links_text) > 3900:
                file_path = os.path.join(user_folder, 'wa_extracted.txt')
                save_to_file(file_path, links)
                await bot.send_file(user_id, file_path, caption=f'📥 روابط الواتساب (`{acc_name}`)')
            else:
                await event.edit(f'📥 **روابط الواتساب (`{acc_name}`):**\n\n{links_text}', buttons=[[Button.inline('🔙 رجوع', f'viewacc_{acc_name}'.encode())]])

    elif data.startswith(b'accstatus_'):
        acc_name = data.decode().replace('accstatus_', '')
        links_file = os.path.join(user_folder, f'custom_{acc_name}_links.txt')
        acc_joined_file = os.path.join(user_folder, f'joined_{acc_name}_links.txt')

        rem = len(load_list_from_file(links_file))
        joined_list = load_list_from_file(acc_joined_file)
        failed_dict = load_failed_links(user_folder, acc_name)

        text = f'📊 **ملخص الحساب:** `{acc_name}`\n\n'
        text += f'📥 المتبقية: `{rem}`\n'
        text += f'✅ الناجحة: `{len(joined_list)}`\n'
        text += f'❌ الفاشلة: `{len(failed_dict)}`'

        buttons = [[Button.inline('🔙 رجوع', f'viewacc_{acc_name}'.encode())]]
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'del_'):
        acc_to_delete = data.decode().replace('del_', '')
        for ext in ['.session', '_links.txt', '_links.json']:
            f_path = os.path.join(user_folder, f'{acc_to_delete}{ext}')
            if os.path.exists(f_path):
                os.remove(f_path)

        await event.answer(f'🗑 تم حذف الحساب {acc_to_delete}', alert=True)
        event.data = b'manage_accs'
        await callback_handler(event)

    elif data == b'add_links_menu':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات مضافة!', alert=True)

        text = '🔗 **اختر الحساب:**'
        buttons = []
        for idx, acc in enumerate(accounts, 1):
            buttons.append([Button.inline(f'#{idx} - 📱 {acc}', f'addl_{acc}'.encode())])
        buttons.append([Button.inline('🔙 رجوع', b'back_to_main')])
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'addl_'):
        target_acc = data.decode().replace('addl_', '')
        user_states[user_id] = {'action': 'waiting_links', 'target_acc': target_acc}
        await event.edit(f'🔗 **إضافة روابط للحساب:** `{target_acc}`\n\nأرسل الروابط الآن.', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'global_wa_menu':
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        count = len(load_list_from_file(global_wa_path))
        text = f'📱 **سجل روابط الواتساب العام:**\n\n• إجمالي الروابط: `{count}`'
        buttons = [
            [Button.inline('📄 استخراج ملف', b'export_global_wa'), Button.inline('🗑️ حذف السجل', b'delete_global_wa')],
            [Button.inline('🔙 رجوع', b'back_to_main')],
        ]
        await event.edit(text, buttons=buttons)

    elif data == b'export_global_wa':
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        links = load_list_from_file(global_wa_path)
        if not links:
            return await event.answer('ℹ️ السجل فارغ.', alert=True)

        file_path = os.path.join(user_folder, 'global_wa_export.txt')
        save_to_file(file_path, links)
        await bot.send_file(user_id, file_path, caption=f'📱 **ملف الواتساب ({len(links)}):**')

    elif data == b'delete_global_wa':
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        if os.path.exists(global_wa_path):
            os.remove(global_wa_path)
        await event.answer('🗑️ تم الحذف!', alert=True)
        event.data = b'global_wa_menu'
        await callback_handler(event)

    elif data == b'stored_links_menu':
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        count = len(load_list_from_file(global_joined_path))
        text = f'📦 **سجل الانضمام العام:**\n\n• إجمالي الروابط: `{count}`'
        buttons = [
            [Button.inline('➕ إضافة روابط', b'add_to_stored_links'), Button.inline('📄 استخراج ملف', b'export_stored_links')],
            [Button.inline('🗑️ حذف السجل', b'delete_stored_links')],
            [Button.inline('🔙 رجوع', b'back_to_main')],
        ]
        await event.edit(text, buttons=buttons)

    elif data == b'add_to_stored_links':
        user_states[user_id] = {'action': 'waiting_stored_links'}
        await event.edit('➕ **إضافة روابط لسجل الانضمام العام**\n\nأرسل الروابط الآن:', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'export_stored_links':
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        links = load_list_from_file(global_joined_path)
        if not links:
            return await event.answer('ℹ️ السجل فارغ.', alert=True)

        file_path = os.path.join(user_folder, 'global_joined_export.txt')
        save_to_file(file_path, links)
        await bot.send_file(user_id, file_path, caption=f'📦 **ملف الروابط المخزنة ({len(links)}):**')

    elif data == b'delete_stored_links':
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        if os.path.exists(global_joined_path):
            os.remove(global_joined_path)
        await event.answer('🗑️ تم الحذف!', alert=True)
        event.data = b'stored_links_menu'
        await callback_handler(event)

    elif data == b'manage_users':
        if user_id != ADMIN_ID:
            return await event.answer('⚠️ غير متاح لك!', alert=True)

        users = load_allowed_users()
        text = '👥 **قائمة المستخدمين:**\n\n'
        buttons = []
        for idx, u_id in enumerate(users, 1):
            tag = "(المالك)" if u_id == ADMIN_ID else ""
            buttons.append([Button.inline(f'#{idx} - 🆔 {u_id} {tag}', f'userinfo_{u_id}'.encode())])
        buttons.append([Button.inline('🔙 رجوع', b'back_to_main')])
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'userinfo_'):
        target_id = int(data.decode().replace('userinfo_', ''))
        text = f'👤 **المستخدم:** `{target_id}`'
        buttons = []
        if target_id != ADMIN_ID:
            buttons.append([Button.inline('❌ حذف المستخدم', f'deluser_{target_id}'.encode())])
        buttons.append([Button.inline('🔙 رجوع', b'manage_users')])
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'deluser_'):
        target_id = int(data.decode().replace('deluser_', ''))
        remove_allowed_user(target_id)
        await event.answer('🗑️ تم الحذف!', alert=True)
        event.data = b'manage_users'
        await callback_handler(event)

    elif data == b'view_shared_private':
        shared_file = os.path.join(user_folder, SHARED_PRIVATE_FILE)
        private_links = load_list_from_file(shared_file)

        if not private_links:
            await event.answer('ℹ️ لا توجد روابط خاصة مكتشفة.', alert=True)
        else:
            links_text = '\n'.join(private_links)
            if len(links_text) > 3900:
                file_path = os.path.join(user_folder, 'private_shared.txt')
                save_to_file(file_path, private_links)
                await bot.send_file(user_id, file_path, caption=f'🔒 **الجروبات الخاصة ({len(private_links)}):**')
            else:
                await event.edit(f'🔒 **الجروبات الخاصة ({len(private_links)}):**\n\n{links_text}', buttons=main_keyboard(user_id))

    elif data == b'manual_extract':
        await event.answer('⏳ جاري الاستخراج...')
        tg, wa = await run_full_extraction_and_distribute(user_id)
        await event.edit(
            f'✅ **اكتمل الاستخراج!**\n\n• `{tg}` تلجرام.\n• `{wa}` واتساب.',
            buttons=main_keyboard(user_id),
        )

    elif data == b'start_manager':
        if running_tasks.get(user_id) and not running_tasks[user_id].done():
            return await event.edit('🟢 **البوت قيد التشغيل بالفعل!**', buttons=main_keyboard(user_id))

        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات نشطة!', alert=True)

        stop_signals[user_id] = False
        await event.answer('▶️ تم التشغيل...')
        status_msg = await bot.send_message(user_id, '⚙️ **جاري البدء...**')
        running_tasks[user_id] = asyncio.create_task(run_infinite_loop(user_id, status_msg))

    elif data == b'stop_manager':
        if not running_tasks.get(user_id) or running_tasks[user_id].done():
            return await event.answer('⚠️ المدير متوقف بالفعل.', alert=True)
        stop_signals[user_id] = True
        await event.answer('⏹ جاري الإيقاف...', alert=True)

    elif data == b'view_stats':
        accounts = await get_active_accounts(user_id)
        global_joined_count = len(load_list_from_file(os.path.join(user_folder, GLOBAL_JOINED_FILE)))
        global_wa_count = len(load_list_from_file(os.path.join(user_folder, GLOBAL_WA_FILE)))

        text = '📊 **الإحصائيات:**\n\n'
        text += f'👤 الحسابات: {len(accounts)}\n'
        text += f'✅ الانضمامات الناجحة: {global_joined_count}\n'
        text += f'📱 روابط الواتساب: {global_wa_count}'
        await event.edit(text, buttons=main_keyboard(user_id))

    elif data == b'system_status':
        accounts = await get_active_accounts(user_id)
        is_running = running_tasks.get(user_id) and not running_tasks[user_id].done()
        status = '🟢 نشط' if is_running else '🔴 متوقف'

        text = f'ℹ️ **حالة النظام:** {status}\n'
        text += f'• الفاصل: `{get_user_delay(user_id) // 60} دقيقة`\n'
        text += f'• الحسابات: `{len(accounts)}`\n'
        await event.edit(text, buttons=main_keyboard(user_id))

    elif data == b'view_delays':
        current_delay = get_user_delay(user_id)
        await event.edit(f'⏳ **التأخير الحالي:** `{current_delay // 60} دقيقة`.', buttons=main_keyboard(user_id))

    elif data == b'settings':
        current_delay = get_user_delay(user_id)
        text = f'⚙️ **الإعدادات:**\n\n⏱️ الفاصل الحالي: **{current_delay // 60} دقيقة**'
        await event.edit(text, buttons=settings_delay_keyboard())

    elif data == b'set_delay_5':
        join_delays[user_id] = 5 * 60
        await event.answer('✅ الفاصل: 5 دقائق', alert=True)
        event.data = b'settings'
        await callback_handler(event)

    elif data == b'set_delay_10':
        join_delays[user_id] = 10 * 60
        await event.answer('✅ الفاصل: 10 دقائق', alert=True)
        event.data = b'settings'
        await callback_handler(event)

    elif data == b'set_delay_custom':
        user_states[user_id] = {'action': 'waiting_custom_delay'}
        await event.edit('⚙️ أرسل عدد الدقائق بالترقيم:', buttons=[Button.inline('❌ إلغاء', b'settings')])

    elif data == b'cancel_state':
        user_states[user_id] = None
        await event.edit('❌ تم الإلغاء.', buttons=main_keyboard(user_id))

    elif data == b'back_to_main':
        await event.edit('⭐ **اللوحة الرئيسية:**', buttons=main_keyboard(user_id))

@bot.on(events.NewMessage)
async def message_handler(event):
    user_id = event.sender_id
    allowed_users = load_allowed_users()
    if user_id not in allowed_users or (event.text and event.text.startswith('/')):
        return

    state = user_states.get(user_id)
    if not state:
        return

    user_folder = get_user_folder(user_id)

    if state.get('action') == 'waiting_bulk_file':
        if not (event.file and event.file.ext in ['.txt', '.text']):
            return await event.respond('⚠️ أرسل ملف نصي (.txt):')

        file_bytes = await event.download_media(bytes)
        try:
            content = file_bytes.decode('utf-8', errors='ignore')
            links_found = re.findall(TG_LINK_REGEX, content)
        except Exception as e:
            return await event.respond(f'❌ خطأ: {e}')

        accounts = await get_active_accounts(user_id)
        if not accounts or not links_found:
            user_states[user_id] = None
            return await event.respond('❌ تعذر استخراج روابط أو لا توجد حسابات.', buttons=main_keyboard(user_id))

        chunk_size = (len(links_found) + len(accounts) - 1) // len(accounts)
        for i, phone in enumerate(accounts):
            acc_chunk = links_found[i * chunk_size : (i + 1) * chunk_size]
            if acc_chunk:
                append_to_file(os.path.join(user_folder, f'custom_{phone}_links.txt'), acc_chunk)

        user_states[user_id] = None
        await event.respond('✅ تم توزيع الروابط بنجاح!', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_stored_links':
        links_found = []
        if event.file and event.file.ext in ['.txt', '.text']:
            file_bytes = await event.download_media(bytes)
            content = file_bytes.decode('utf-8', errors='ignore')
            links_found = re.findall(TG_LINK_REGEX, content)
        elif event.text:
            links_found = re.findall(TG_LINK_REGEX, event.text)

        if links_found:
            append_to_file(os.path.join(user_folder, GLOBAL_JOINED_FILE), links_found)

        user_states[user_id] = None
        await event.respond('✅ تمت الإضافة بنجاح!', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_custom_delay':
        input_text = event.text.strip()
        if input_text.isdigit() and int(input_text) > 0:
            join_delays[user_id] = int(input_text) * 60
            user_states[user_id] = None
            await event.respond(f'✅ الفاصل الجديد: **{input_text} دقيقة**', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_phone':
        phone = event.text.strip()
        client = TelegramClient(os.path.join(user_folder, phone), API_ID, API_HASH)
        await client.connect()

        try:
            send_code_result = await client.send_code_request(phone)
            user_states[user_id] = {'action': 'waiting_code', 'phone': phone, 'phone_code_hash': send_code_result.phone_code_hash, 'client': client}
            await event.respond(f'🔑 أرسل كود التحقق لـ `{phone}`:')
        except Exception as e:
            await client.disconnect()
            user_states[user_id] = None
            await event.respond(f'❌ خطأ: `{str(e)}`', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_code':
        code, phone, phone_code_hash, client = event.text.strip(), state['phone'], state['phone_code_hash'], state['client']
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            await event.respond('🎉 تم تسجيل الحساب بنجاح!', buttons=main_keyboard(user_id))
            await client.disconnect()
            user_states[user_id] = None
        except SessionPasswordNeededError:
            user_states[user_id]['action'] = 'waiting_password'
            await event.respond('🔐 أرسل كلمة السر (2FA):')
        except Exception as e:
            await client.disconnect()
            user_states[user_id] = None
            await event.respond(f'❌ خطأ: `{str(e)}`', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_password':
        password, client = event.text.strip(), state['client']
        try:
            await client.sign_in(password=password)
            await event.respond('🎉 تم تسجيل الحساب بنجاح!', buttons=main_keyboard(user_id))
            await client.disconnect()
            user_states[user_id] = None
        except Exception as e:
            await client.disconnect()
            user_states[user_id] = None
            await event.respond(f'❌ خطأ: `{str(e)}`', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_links':
        target_acc = state['target_acc']
        links = re.findall(TG_LINK_REGEX, event.text or '')
        if links:
            append_to_file(os.path.join(user_folder, f'custom_{target_acc}_links.txt'), links)
        user_states[user_id] = None
        await event.respond('✅ تم إضافة الروابط بنجاح!', buttons=main_keyboard(user_id))

async def check_and_leave_if_inappropriate(client, user_id, phone, target, link):
    try:
        full_entity = await client.get_entity(target)
        title = getattr(full_entity, 'title', '').lower()
        
        for kw in NSFW_KEYWORDS:
            if kw in title:
                await client(LeaveChannelRequest(full_entity))
                return True

        if is_leave_locked_enabled(user_id):
            if hasattr(full_entity, 'default_banned_rights') and full_entity.default_banned_rights:
                if full_entity.default_banned_rights.send_messages:
                    await client(LeaveChannelRequest(full_entity))
                    return True
    except Exception:
        pass
    return False

async def join_links_logic(user_id, client, phone, extracted_links, links_file, global_joined_path, acc_joined_file, user_folder, status_msg):
    for link in list(extracted_links):
        if stop_signals.get(user_id, False):
            break

        try:
            if 'joinchat/' in link or '+' in link:
                hash_val = link.split('/')[-1].replace('+', '')
                await client(ImportChatInviteRequest(hash_val))
            else:
                target = link.split('/')[-1]
                await client(JoinChannelRequest(target))
                await check_and_leave_if_inappropriate(client, user_id, phone, target, link)

            append_to_file(global_joined_path, [link])
            append_to_file(acc_joined_file, [link])

        except FloodWaitError as e:
            flood_expiry.setdefault(user_id, {})[phone] = time.time() + e.seconds
            break
        except Exception as e:
            save_failed_link(user_folder, phone, link, str(e))
        finally:
            if link in extracted_links:
                extracted_links.remove(link)
                save_to_file(links_file, extracted_links)

        await asyncio.sleep(get_user_delay(user_id))

async def run_infinite_loop(user_id, status_msg):
    user_folder = get_user_folder(user_id)
    global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)

    while not stop_signals.get(user_id, False):
        accounts = await get_active_accounts(user_id)
        if not accounts:
            await asyncio.sleep(10)
            continue

        for phone in accounts:
            if stop_signals.get(user_id, False):
                break

            links_file = os.path.join(user_folder, f'custom_{phone}_links.txt')
            acc_joined_file = os.path.join(user_folder, f'joined_{phone}_links.txt')
            extracted_links = load_list_from_file(links_file)

            if not extracted_links:
                continue

            client = TelegramClient(os.path.join(user_folder, f'{phone}.session'), API_ID, API_HASH)
            try:
                await client.connect()
                if await client.is_user_authorized():
                    await join_links_logic(user_id, client, phone, extracted_links, links_file, global_joined_path, acc_joined_file, user_folder, status_msg)
                await client.disconnect()
            except Exception:
                pass

        await asyncio.sleep(15)

async def main():
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    asyncio.create_task(scheduled_daily_extraction())

    await bot.start(bot_token=BOT_TOKEN)
    await set_bot_commands()
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
