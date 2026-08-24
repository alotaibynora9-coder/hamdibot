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
from telethon.tl.types import BotCommand, BotCommandScopeDefault

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
NSFW_SCANNER_SETTINGS_FILE = 'nsfw_scanner_settings.json'

TG_LINK_REGEX = r'(https?://(?:t\.me|telegram\.me)/(?:joinchat/|\+)?[\w-]+)'
WA_LINK_REGEX = r'(https?://chat\.whatsapp\.com/[\w-]+)'

NSFW_KEYWORDS = [
    'سكس', 'إباحي', 'اباحي', 'سكسي', 'تعري', 'مقاطع 18', 'افلام 18', 'شرموطة', 'زب', 
    'كس', 'نياك', 'طيز', 'نيك', 'قحبة', 'سحاق', 'ورعان', 'موجب', 'سالب', 'ديوث',
    'porn', 'sex', 'nsfw', 'xvideo', 'hentai', 'xnxx', 'erotic', 'adult 18+'
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

def load_nsfw_scanner_settings():
    if os.path.exists(NSFW_SCANNER_SETTINGS_FILE):
        with open(NSFW_SCANNER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def is_nsfw_scanner_enabled(user_id):
    settings = load_nsfw_scanner_settings()
    return settings.get(str(user_id), False)

def set_nsfw_scanner_setting(user_id, status: bool):
    settings = load_nsfw_scanner_settings()
    settings[str(user_id)] = status
    with open(NSFW_SCANNER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
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
nsfw_scanner_tasks = {}
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

def main_keyboard(user_id):
    leave_status = "🟢 مفعل" if is_leave_locked_enabled(user_id) else "🔴 معطل"
    nsfw_status = "🟢 مفعل" if is_nsfw_scanner_enabled(user_id) else "🔴 معطل"
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
            Button.inline(f'🛡️ فحص ومغادرة الجروبات [{nsfw_status}]', b'toggle_nsfw_scanner'),
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
    except Exception as e:
        print(f'[⚠️] فشل تعيين الأوامر المنسدلة: {e}')

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
        'تم تحديث فلتر الأسماء بنجاح ومنع مغادرة المجموعات العربية أو المختلطة العادية.',
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

# --- الدالة المعدلة والمحدثة بدقة لتمييز الأسماء ---
def process_group_name_rules(title):
    title_lower = title.lower()

    # 1. التثبت من وجود الكلمات الإباحية الصريحة باستخدام حدود الكلمات
    for kw in NSFW_KEYWORDS:
        pattern = r'(?:\b|_)' + re.escape(kw) + r'(?:\b|_)'
        if re.search(pattern, title_lower):
            return True, f"اسم يحتوي على كلمة إباحية ({kw})"

    has_arabic = bool(re.search(r'[\u0600-\u06FF]', title))
    has_english = bool(re.search(r'[a-zA-Z]', title))

    # 2. مغادرة الجروب فقط إذا كان الاسم بالكامل إنجليزي بدون أي حروف عربية
    if has_english and not has_arabic:
        return True, "الاسم إنجليزي بالكامل"

    # 3. إذا كان الاسم يحتوي على حروف عربية (سواء كان خالصاً أو مختلطاً) -> لا يغادره
    return False, ""

async def check_and_leave_if_inappropriate_general(client, user_id, phone, dialog):
    try:
        entity = dialog.entity
        title = dialog.name or ""
        
        should_leave, reason = process_group_name_rules(title)
        if should_leave:
            await client(LeaveChannelRequest(entity))
            await bot.send_message(user_id, f'🚪 [{phone}]: تم مغادرة مجموعة\n📌 **الاسم:** {title}\n📝 **السبب:** {reason}')
            return True

        if is_leave_locked_enabled(user_id):
            if hasattr(entity, 'default_banned_rights') and entity.default_banned_rights:
                rights = entity.default_banned_rights
                if rights.send_messages:
                    await client(LeaveChannelRequest(entity))
                    await bot.send_message(user_id, f'🔒 [{phone}]: مجموعة مقفلة لا تسمح بالكتابة\n📌 **المجموعة:** {title} -> تم المغادرة 🚪')
                    return True

    except Exception as e:
        print(f"[⚠️] خطأ أثناء الفحص التلقائي للحساب {phone}: {e}")
    return False

async def run_nsfw_scanner_loop(user_id):
    while is_nsfw_scanner_enabled(user_id):
        accounts = await get_active_accounts(user_id)
        user_folder = get_user_folder(user_id)

        if not accounts:
            await asyncio.sleep(5)
            continue

        for phone in accounts:
            if not is_nsfw_scanner_enabled(user_id):
                break

            session_file = os.path.join(user_folder, f'{phone}.session')
            if not os.path.exists(session_file):
                continue

            client = TelegramClient(session_file, API_ID, API_HASH)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    continue

                async for dialog in client.iter_dialogs(limit=50):
                    if not is_nsfw_scanner_enabled(user_id):
                        break
                    
                    entity = dialog.entity
                    if isinstance(entity, (telethon.tl.types.Channel, telethon.tl.types.Chat)):
                        await check_and_leave_if_inappropriate_general(client, user_id, phone, dialog)
                        await asyncio.sleep(0.1)

                await client.disconnect()
            except Exception as e:
                print(f"[⚠️] خطأ/انتظار في حساب {phone}، التنقل للحساب التالي: {e}")

            await asyncio.sleep(0.5)

        await asyncio.sleep(1)

async def check_and_leave_if_inappropriate(client, user_id, phone, target, link):
    try:
        full_entity = await client.get_entity(target)
        title = getattr(full_entity, 'title', '') or ''
        
        should_leave, reason = process_group_name_rules(title)
        if should_leave:
            await client(LeaveChannelRequest(full_entity))
            await bot.send_message(user_id, f'🚪 [{phone}]: تم المغادرة\n📌 **اسم الجروب:** {title}\n📝 **السبب:** {reason}\n🔗 {link}')
            return True

        if is_leave_locked_enabled(user_id):
            if hasattr(full_entity, 'default_banned_rights') and full_entity.default_banned_rights:
                rights = full_entity.default_banned_rights
                if rights.send_messages:
                    await client(LeaveChannelRequest(full_entity))
                    await bot.send_message(user_id, f'🔒 [{phone}]: مجموعة مقفلة لا تسمح بالكتابة\n📌 **اسم الجروب:** {title} -> تم المغادرة 🚪\n🔗 {link}')
                    return True

    except Exception as e:
        print(f"[⚠️] خطأ أثناء فحص اسم الجروب للحساب {phone}: {e}")
    return False

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

    if data == b'toggle_leave_locked':
        current = is_leave_locked_enabled(user_id)
        new_status = not current
        set_leave_locked_setting(user_id, new_status)
        status_msg = "تم تفعيل مغادرة المجموعات المقفلة تلقائياً ✅" if new_status else "تم إيقاف مغادرة المجموعات المقفلة 🔴"
        await event.answer(status_msg, alert=True)
        await event.edit('⭐ **اللوحة الرئيسية للتحكم:**', buttons=main_keyboard(user_id))

    elif data == b'toggle_nsfw_scanner':
        current = is_nsfw_scanner_enabled(user_id)
        new_status = not current
        set_nsfw_scanner_setting(user_id, new_status)
        
        if new_status:
            if not nsfw_scanner_tasks.get(user_id) or nsfw_scanner_tasks[user_id].done():
                nsfw_scanner_tasks[user_id] = asyncio.create_task(run_nsfw_scanner_loop(user_id))
            await event.answer("تم تفعيل الفحص والمغادرة المستمرة لأسماء الجروبات ✅", alert=True)
        else:
            if user_id in nsfw_scanner_tasks:
                nsfw_scanner_tasks[user_id].cancel()
            await event.answer("تم إيقاف فحص أسماء الجروبات 🔴", alert=True)

        await event.edit('⭐ **اللوحة الرئيسية للتحكم:**', buttons=main_keyboard(user_id))

    elif data == b'add_acc':
        user_states[user_id] = {'action': 'waiting_phone'}
        await event.edit('➕ **إضافة حساب جديد**\n\nأرسل رقم الهاتف مع مفتاح الدولة الآن.\nمثال: `+9665XXXXXXXX`', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'start_manager':
        if running_tasks.get(user_id) and not running_tasks[user_id].done():
            last_act = current_action_status.get(user_id, 'جاري معالجة العمليات الحالية...')
            return await event.edit(f'🟢 **البوت قيد التشغيل الان!**\n\n📊 **آخر عمل يقوم به:**\n{last_act}', buttons=main_keyboard(user_id))

        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات نشطة للبدء!', alert=True)

        stop_signals[user_id] = False
        await event.answer('▶️ تم تشغيل البوت بنجاح...')
        await event.edit('⚙️ **تم تشغيل البوت والبدء في الفحص...**', buttons=main_keyboard(user_id))
        
        status_msg = await bot.send_message(user_id, '⚙️ **حالة الانضمام الحالية:**\nجاري تجهيز العملية...')
        running_tasks[user_id] = asyncio.create_task(run_infinite_loop(user_id, status_msg))

    elif data == b'stop_manager':
        if not running_tasks.get(user_id) or running_tasks[user_id].done():
            return await event.answer('⚠️ المدير متوقف بالفعل.', alert=True)
        stop_signals[user_id] = True
        await event.answer('⏹ جاري إيقاف البوت...', alert=True)

    elif data == b'cancel_state':
        user_states[user_id] = None
        await event.edit('❌ تم إلغاء العملية والعودة للوحة الرئيسية.', buttons=main_keyboard(user_id))

    elif data == b'back_to_main':
        await event.edit('⭐ **اللوحة الرئيسية للتحكم:**', buttons=main_keyboard(user_id))

async def join_links_logic(
    user_id,
    client,
    phone,
    extracted_links,
    links_file,
    global_joined_path,
    acc_joined_file,
    user_folder,
    status_msg,
):
    shared_private_path = os.path.join(user_folder, SHARED_PRIVATE_FILE)

    for link in list(extracted_links):
        if stop_signals.get(user_id, False):
            break

        global_joined = load_list_from_file(global_joined_path)
        if link in global_joined:
            extracted_links.remove(link)
            save_to_file(links_file, extracted_links)
            continue

        action_str = f"📱 الحساب: `{phone}`\n🔗 الرابط: `{link}`"
        current_action_status[user_id] = action_str
        try:
            await status_msg.edit(f"⚙️ **جاري العمل الحالي:**\n{action_str}")
        except Exception:
            pass

        try:
            if 'joinchat/' in link or '+' in link:
                hash_val = link.split('/')[-1].replace('+', '')
                try:
                    check_res = await client(CheckChatInviteRequest(hash_val))
                    chat_title = getattr(check_res.chat, 'title', 'مجموعة خاصة')
                    
                    if hasattr(check_res, 'already_joined') and check_res.already_joined:
                        append_to_file(shared_private_path, [link])
                    else:
                        await client(ImportChatInviteRequest(hash_val))
                        append_to_file(shared_private_path, [link])
                        await bot.send_message(user_id, f'🎉 [{phone}]: انضمام ناجح لمجموعة خاصة ({chat_title})! 🔒\n🔗 {link}')
                        await check_and_leave_if_inappropriate(client, user_id, phone, hash_val, link)

                except Exception as ex_inv:
                    if "ALREADY_PARTICIPANT" in str(ex_inv):
                        append_to_file(shared_private_path, [link])
                    else:
                        raise ex_inv
            else:
                target = link.split('/')[-1]
                try:
                    ent = await client.get_entity(target)
                    target_title = getattr(ent, 'title', target)
                except:
                    target_title = target

                await client(JoinChannelRequest(target))
                await bot.send_message(user_id, f'✅ [{phone}]: انضمام ناجح لـ `{target_title}`.\n🔗 {link}')
                await check_and_leave_if_inappropriate(client, user_id, phone, target, link)

            append_to_file(global_joined_path, [link])
            append_to_file(acc_joined_file, [link])

        except FloodWaitError as e:
            wait_time = e.seconds
            flood_expiry.setdefault(user_id, {})[phone] = time.time() + wait_time
            await bot.send_message(user_id, f'⏳ [{phone}]: حظر مؤقت (FloodWait) لـ {wait_time} ثانية.')
            save_failed_link(user_folder, phone, link, f"FloodWait ({wait_time}s)")
            break

        except Exception as e:
            err_msg = str(e)
            save_failed_link(user_folder, phone, link, err_msg)

        finally:
            if link in extracted_links:
                extracted_links.remove(link)
                save_to_file(links_file, extracted_links)

        delay = get_user_delay(user_id)
        await asyncio.sleep(delay)

async def run_infinite_loop(user_id, status_msg):
    user_folder = get_user_folder(user_id)
    global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)

    while not stop_signals.get(user_id, False):
        accounts = await get_active_accounts(user_id)
        if not accounts:
            current_action_status[user_id] = "لا توجد حسابات نشطة مضافة."
            await asyncio.sleep(10)
            continue

        work_done = False
        user_floods = flood_expiry.setdefault(user_id, {})
        now = time.time()

        for phone in accounts:
            if stop_signals.get(user_id, False):
                break

            if user_floods.get(phone, 0) > now:
                continue

            links_file = os.path.join(user_folder, f'custom_{phone}_links.txt')
            acc_joined_file = os.path.join(user_folder, f'joined_{phone}_links.txt')
            extracted_links = load_list_from_file(links_file)

            if not extracted_links:
                continue

            work_done = True
            session_file = os.path.join(user_folder, f'{phone}.session')
            client = TelegramClient(session_file, API_ID, API_HASH)

            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    continue

                await join_links_logic(
                    user_id, client, phone, extracted_links, links_file,
                    global_joined_path, acc_joined_file, user_folder, status_msg
                )
                await client.disconnect()

            except Exception as e:
                print(f"[⚠️] خطأ أثناء تشغيل الحساب {phone}: {e}")

        if not work_done:
            current_action_status[user_id] = "💤 جميع القوائم فارغة أو الحسابات في فترة الانتظار..."
            await asyncio.sleep(15)

    current_action_status[user_id] = "🔴 المحرك متوقف حالياً."

async def main():
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    for user_id_str, enabled in load_nsfw_scanner_settings().items():
        if enabled:
            u_id = int(user_id_str)
            nsfw_scanner_tasks[u_id] = asyncio.create_task(run_nsfw_scanner_loop(u_id))

    await bot.start(bot_token=BOT_TOKEN)
    await set_bot_commands()
    print("🤖 Main Control Bot started successfully!")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
