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

# استيراد المكتبة الرئيسية والأدوات المطلوبة
import telethon
from telethon import Button, TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.functions.bots import SetBotCommandsRequest
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import (
    CheckChatInviteRequest,
    DeleteHistoryRequest,
    ImportChatInviteRequest,
)
from telethon.tl.types import BotCommand, BotCommandScopeDefault, Channel, Chat, User

# --- إعدادات الـ API والتحكم الأساسي ---
API_ID = 21799597
API_HASH = '4e7a8aee718c1e8e63956fec3339d01d'
BOT_TOKEN = '8596141491:AAHIJxZhl_y0wW89o_712h_9DqGIH6qKkw8'
ADMIN_ID = 7226664693

# --- سيرفر Flask المدمج لمنع توقف الخدمة ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Main Bot Service is Active and Running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# --- إعدادات المجلدات وملفات الأمان ---
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

# --- إدارة المستخدمين المسموح لهم ---
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

# --- إدارة إعدادات مغادرة المجموعات المقفلة ---
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

# --- إدارة إعدادات فحص ومغادرة الجروبات والقنوات والبوتات ---
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

# --- إدارة الملفات والقوائم ---
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

# --- متغيرات الحالة العامة ---
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

# --- دالة التحقق الإجباري من الاتصال وتجديده عند الانقطاع ---
async def ensure_connected(client):
    if not client.is_connected():
        try:
            await client.connect()
        except Exception as e:
            print(f"[⚠️] فشلت إعادة الاتصال: {e}")

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
            Button.inline(f'🛡️ فحص ومغادرة (جروبات/قنوات/بوتات) [{nsfw_status}]', b'toggle_nsfw_scanner'),
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
        'تم إحكام الربط ومنع مشكلة الانقطاع ومعالجة أسماء الجروبات الخاصة بنجاح.',
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
    except Exception as e:
        print(f'[⚠️] خطأ أثناء استخراج الروابط للحساب {phone}: {e}')
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
        try:
            print("[+] بدء دالة الاستخراج المجدولة اليومية...")
            allowed_users = load_allowed_users()
            for user_id in allowed_users:
                await run_full_extraction_and_distribute(user_id)
            await asyncio.sleep(86400)
        except Exception as e:
            print(f"[⚠️] خطأ أثناء الاستخراج المجدول: {e}")
            await asyncio.sleep(300)

def process_name_rules(title):
    title_strip = title.strip() if title else ""
    title_lower = title_strip.lower()

    for kw in NSFW_KEYWORDS:
        if kw in title_lower:
            return True, f"كلمة مخالفة ({kw})"

    has_arabic = bool(re.search(r'[\u0600-\u06FF]', title_strip))
    if not has_arabic:
        return True, "الاسم لغة غير عربية / رموز / إنجليزي"

    return False, ""

async def process_standalone_scanner_for_account(client, user_id, phone):
    try:
        await ensure_connected(client)
        async for dialog in client.iter_dialogs(limit=None):
            if not is_nsfw_scanner_enabled(user_id):
                break

            entity = dialog.entity
            title = dialog.name or ""
            entity_type_str = "👥 مجموعة"
            is_bot = False

            if isinstance(entity, User) and entity.bot:
                entity_type_str = "🤖 بوت"
                is_bot = True
            elif isinstance(entity, Channel):
                entity_type_str = "📢 قناة" if entity.broadcast else "👥 مجموعة"
            elif isinstance(entity, Chat):
                entity_type_str = "👥 مجموعة"
            else:
                continue

            should_leave, reason = process_name_rules(title)

            if not should_leave and is_leave_locked_enabled(user_id) and not is_bot:
                if hasattr(entity, 'default_banned_rights') and entity.default_banned_rights:
                    if entity.default_banned_rights.send_messages:
                        should_leave = True
                        reason = "مجموعة مقفلة لا تسمح بالكتابة"

            if should_leave:
                try:
                    await ensure_connected(client)
                    if is_bot:
                        await client(BlockRequest(entity.id))
                        await client(DeleteHistoryRequest(peer=entity, max_id=0, revoke=True))
                    else:
                        await client(LeaveChannelRequest(entity))

                    await bot.send_message(
                        user_id,
                        f"🛡️ **[تقرير الفحص المطور]**\n\n"
                        f"📱 **الحساب:** `{phone}`\n"
                        f"📌 **الاسم:** {title}\n"
                        f"🏷️ **النوع:** {entity_type_str}\n"
                        f"📝 **السبب:** {reason}\n"
                        f"🚪 **الإجراء:** تم المغادرة/الحظر بنجاح."
                    )
                except Exception as ex_leave:
                    print(f"[⚠️] فشل المغادرة من {title}: {ex_leave}")

            await asyncio.sleep(0.02)

    except FloodWaitError as e:
        print(f"[⏳] الحساب {phone} دخل في انتظار FloodWait لمدة {e.seconds} ثانية.")
    except Exception as e:
        print(f"[⚠️] خطأ أثناء فحص الحساب {phone}: {e}")

async def run_nsfw_scanner_loop(user_id):
    while is_nsfw_scanner_enabled(user_id):
        try:
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
                    if await client.is_user_authorized():
                        await process_standalone_scanner_for_account(client, user_id, phone)
                    await client.disconnect()
                except Exception as e:
                    print(f"[⚠️] خطأ الاتصال بالحساب {phone}: {e}")
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                await asyncio.sleep(0.1)

            await asyncio.sleep(2)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[⚠️] خطأ في حلقة الفحص: {e}")
            await asyncio.sleep(3)

# --- منطق الانضمام المعدل لمنع خطأ ChatInvite ---
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

        action_str = f"📱 الحساب الحالي: `{phone}`\n🔗 الرابط: `{link}`"
        current_action_status[user_id] = action_str
        try:
            await status_msg.edit(f"⚙️ **جاري العمل الحالي:**\n{action_str}")
        except Exception:
            pass

        await ensure_connected(client)

        try:
            if 'joinchat/' in link or '+' in link:
                hash_val = link.split('/')[-1].replace('+', '')
                try:
                    check_res = await client(CheckChatInviteRequest(hash_val))
                    
                    # الفحص الآمن لخاصية اسم المجموعة لمنع الخطأ
                    if hasattr(check_res, 'chat'):
                        chat_title = getattr(check_res.chat, 'title', 'مجموعة خاصة')
                    else:
                        chat_title = getattr(check_res, 'title', 'مجموعة خاصة')
                    
                    if hasattr(check_res, 'already_joined') and check_res.already_joined:
                        append_to_file(shared_private_path, [link])
                        await bot.send_message(user_id, f'🔒 [{phone}]: انضمام سابق لمجموعة خاصة ({chat_title}).\n🔗 {link}')
                    else:
                        await client(ImportChatInviteRequest(hash_val))
                        append_to_file(shared_private_path, [link])
                        await bot.send_message(user_id, f'🎉 [{phone}]: تم الانضمام بنجاح لمجموعة خاصة ({chat_title})! 🔒\n🔗 {link}')

                except Exception as ex_inv:
                    ex_str = str(ex_inv)
                    if "USER_ALREADY_PARTICIPANT" in ex_str or "already a participant" in ex_str:
                        append_to_file(shared_private_path, [link])
                        await bot.send_message(user_id, f'ℹ️ [{phone}]: الحساب منضم مسبقاً لهذا الرابط الخاص.\n🔗 {link}')
                    elif "requested to join" in ex_str or "INVITE_REQUEST_SENT" in ex_str:
                        append_to_file(shared_private_path, [link])
                        await bot.send_message(user_id, f'📩 [{phone}]: تم إرسال طلب الانضمام وبانتظار موافقة المشرف.\n🔗 {link}')
                    else:
                        raise ex_inv
            else:
                target = link.split('/')[-1]
                ent = await client.get_entity(target)
                await client(JoinChannelRequest(ent))
                await bot.send_message(user_id, f'🎉 [{phone}]: تم الانضمام بنجاح للرابط العام:\n🔗 {link}')

            append_to_file(global_joined_path, [link])
            append_to_file(acc_joined_file, [link])
            extracted_links.remove(link)
            save_to_file(links_file, extracted_links)

        except FloodWaitError as e:
            user_floods = flood_expiry.setdefault(user_id, {})
            user_floods[phone] = time.time() + e.seconds
            await bot.send_message(user_id, f'⏳ [{phone}]: تعذر الانضمام للرابط بسبب تقييد مؤقت (FloodWait) لمدة {e.seconds} ثانية.')
            break

        except Exception as e:
            ex_err = str(e)
            if "Disconnected" in ex_err or "disconnected" in ex_err:
                print(f"[⚠️] حدث انقطاع أثناء طلب الانضمام، جاري إعادة المحاولة... ({ex_err})")
                await asyncio.sleep(2)
                await ensure_connected(client)
                continue

            save_failed_link(user_folder, phone, link, ex_err)
            await bot.send_message(user_id, f'❌ [{phone}]: فشل الانضمام للرابط:\n{link}\n┗ السبب: `{ex_err}`')
            
            extracted_links.remove(link)
            save_to_file(links_file, extracted_links)

        delay_sec = get_user_delay(user_id)
        await asyncio.sleep(delay_sec)

async def run_infinite_loop(user_id, status_msg):
    user_folder = get_user_folder(user_id)
    global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)

    while not stop_signals.get(user_id, False):
        try:
            accounts = await get_active_accounts(user_id)
            if not accounts:
                current_action_status[user_id] = "لا توجد حسابات نشطة مضافة."
                await status_msg.edit("⚠️ لا توجد حسابات مضافة حالياً لعمل المحرك.")
                await asyncio.sleep(10)
                continue

            worked_any = False

            for phone in accounts:
                if stop_signals.get(user_id, False):
                    break

                user_floods = flood_expiry.get(user_id, {})
                if user_floods.get(phone, 0) > time.time():
                    continue

                links_file = os.path.join(user_folder, f'custom_{phone}_links.txt')
                extracted_links = load_list_from_file(links_file)

                if not extracted_links:
                    continue

                worked_any = True
                acc_joined_file = os.path.join(user_folder, f'joined_{phone}_links.txt')
                session_file = os.path.join(user_folder, f'{phone}.session')

                client = TelegramClient(session_file, API_ID, API_HASH)
                try:
                    await client.connect()
                    if await client.is_user_authorized():
                        await join_links_logic(
                            user_id,
                            client,
                            phone,
                            extracted_links,
                            links_file,
                            global_joined_path,
                            acc_joined_file,
                            user_folder,
                            status_msg,
                        )
                    await client.disconnect()
                except Exception as e:
                    print(f"[⚠️] خطأ بفتح جلسة الحساب {phone}: {e}")
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

            if not worked_any:
                current_action_status[user_id] = "جميع الحسابات مكتملة أو في حالة انتظار (FloodWait)."
                try:
                    await status_msg.edit("😴 لا توجد روابط متبقية للانضمام في جميع الحسابات حالياً. بانتظار روابط جديدة...")
                except Exception:
                    pass
                await asyncio.sleep(15)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[⚠️] خطأ بالحلقة الرئيسية: {e}")
            await asyncio.sleep(5)

    current_action_status[user_id] = "المحرك متوقف."
    try:
        await status_msg.edit("⏹ **تم إيقاف محرك الانضمام التلقائي بنجاح.**")
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
            await event.answer("تم تفعيل الفحص التلقائي المستقل والسريع ✅", alert=True)
        else:
            if user_id in nsfw_scanner_tasks:
                nsfw_scanner_tasks[user_id].cancel()
            await event.answer("تم إيقاف نظام الفحص والمغادرة 🔴", alert=True)

        await event.edit('⭐ **اللوحة الرئيسية للتحكم:**', buttons=main_keyboard(user_id))

    elif data == b'add_acc':
        user_states[user_id] = {'action': 'waiting_phone'}
        await event.edit('➕ **إضافة حساب جديد**\n\nأرسل رقم الهاتف مع مفتاح الدولة الآن.\nمثال: `+9665XXXXXXXX`', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'add_bulk_file':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات نشطة مضافة لتوزيع الروابط عليها!', alert=True)

        user_states[user_id] = {'action': 'waiting_bulk_file'}
        await event.edit('📥 **إضافة ملف روابط وتوزيعها على جميع الحسابات**\n\nقم برفع وإرسال **ملف نصي (.txt)** يحتوي على روابط التلجرام الآن.', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'manage_accs':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            await event.edit('❌ لا توجد حسابات مضافة حالياً.', buttons=main_keyboard(user_id))
        else:
            text = '👥 **قائمة حساباتك المحفوظة (مرقمة):**\n\nانقر فوق الحساب للتحكم به واستعراض الروابط المستخرجة منه:'
            buttons = []
            for idx, acc in enumerate(accounts, 1):
                buttons.append([Button.inline(f'#{idx} - 📱 {acc}', f'viewacc_{acc}'.encode())])
            buttons.append([Button.inline('🔙 رجوع لقائمة الرئيسية', b'back_to_main')])
            await event.edit(text, buttons=buttons)

    elif data.startswith(b'viewacc_'):
        acc_name = data.decode().replace('viewacc_', '')
        text = f'⚙️ **إدارة الحساب:** `{acc_name}`\n\nاختر الخيار المطلوب من الأزرار أدناه:'
        buttons = [
            [Button.inline('1-تلجرام (روابط استُخرجت)', f'ex_tg_{acc_name}'.encode()), Button.inline('2-وتس (روابط استُخرجت)', f'ex_wa_{acc_name}'.encode())],
            [Button.inline('📊 حالة الحساب وتقارير الروابط', f'accstatus_{acc_name}'.encode())],
            [Button.inline('❌ حذف الحساب', f'del_{acc_name}'.encode())],
            [Button.inline('🔙 رجوع للقائمة', b'manage_accs')],
        ]
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'ex_tg_'):
        acc_name = data.decode().replace('ex_tg_', '')
        tg_file = os.path.join(user_folder, f'extracted_tg_{acc_name}.txt')
        links = load_list_from_file(tg_file)

        if not links:
            await event.answer(f'ℹ️ لا توجد روابط تلجرام مستخرجة للحساب {acc_name}', alert=True)
        else:
            links_text = '\n'.join(links)
            if len(links_text) > 3900:
                file_path = os.path.join(user_folder, 'tg_extracted.txt')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(links_text)
                await bot.send_file(user_id, file_path, caption=f'📥 جميع روابط التلجرام المستخرجة للحساب `{acc_name}` (إجمالي: {len(links)})')
            else:
                await event.edit(f'📥 **روابط التلجرام المستخرجة للحساب `{acc_name}` (العدد: {len(links)}):**\n\n{links_text}', buttons=[[Button.inline('🔙 رجوع', f'viewacc_{acc_name}'.encode())]])

    elif data.startswith(b'ex_wa_'):
        acc_name = data.decode().replace('ex_wa_', '')
        wa_file = os.path.join(user_folder, f'extracted_wa_{acc_name}.txt')
        links = load_list_from_file(wa_file)

        if not links:
            await event.answer(f'ℹ️ لا توجد روابط واتساب مستخرجة للحساب {acc_name}', alert=True)
        else:
            links_text = '\n'.join(links)
            if len(links_text) > 3900:
                file_path = os.path.join(user_folder, 'wa_extracted.txt')
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(links_text)
                await bot.send_file(user_id, file_path, caption=f'📥 جميع روابط الواتساب المستخرجة للحساب `{acc_name}` (إجمالي: {len(links)})')
            else:
                await event.edit(f'📥 **روابط الواتساب المستخرجة للحساب `{acc_name}` (العدد: {len(links)}):**\n\n{links_text}', buttons=[[Button.inline('🔙 رجوع', f'viewacc_{acc_name}'.encode())]])

    elif data.startswith(b'accstatus_'):
        acc_name = data.decode().replace('accstatus_', '')
        links_file = os.path.join(user_folder, f'custom_{acc_name}_links.txt')
        acc_joined_file = os.path.join(user_folder, f'joined_{acc_name}_links.txt')

        rem = len(load_list_from_file(links_file))
        joined_list = load_list_from_file(acc_joined_file)
        failed_dict = load_failed_links(user_folder, acc_name)

        text = f'📊 **تقرير وملخص الروابط للحساب:** `{acc_name}`\n\n'
        text += f'📥 عدد الروابط المتبقية: `{rem}`\n'
        text += f'✅ عدد الروابط الناجحة: `{len(joined_list)}`\n'
        text += f'❌ عدد الروابط الفاشلة: `{len(failed_dict)}`\n\n'

        if failed_dict:
            text += '⚠️ **تفصيل أسباب فشل آخر الروابط:**\n'
            last_failed = list(failed_dict.items())[-5:]
            for link, info in reversed(last_failed):
                text += f"🔗 {link}\n┗ ❌ **السبب:** {info['reason']}\n\n"
        else:
            text += '✅ لا توجد روابط فاشلة مسجلة لهذا الحساب.\n'

        buttons = [[Button.inline('🔙 رجوع للخلف', f'viewacc_{acc_name}'.encode())]]
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'del_'):
        acc_to_delete = data.decode().replace('del_', '')
        session_file = os.path.join(user_folder, f'{acc_to_delete}.session')
        links_file = os.path.join(user_folder, f'custom_{acc_to_delete}_links.txt')
        acc_joined_file = os.path.join(user_folder, f'joined_{acc_to_delete}_links.txt')
        failed_file = os.path.join(user_folder, f'failed_{acc_to_delete}_links.json')

        for f_path in [session_file, links_file, acc_joined_file, failed_file]:
            if os.path.exists(f_path):
                os.remove(f_path)

        await event.answer(f'🗑 تم حذف الحساب {acc_to_delete} وسجلاته بنجاح!', alert=True)
        accounts = await get_active_accounts(user_id)
        if not accounts:
            await event.edit('❌ لا توجد حسابات مضافة حالياً.', buttons=main_keyboard(user_id))
        else:
            buttons = []
            for idx, acc in enumerate(accounts, 1):
                buttons.append([Button.inline(f'#{idx} - 📱 {acc}', f'viewacc_{acc}'.encode())])
            buttons.append([Button.inline('🔙 رجوع', b'back_to_main')])
            await event.edit('👥 **قائمة حساباتك المحفوظة:**', buttons=buttons)

    elif data == b'add_links_menu':
        accounts = await get_active_accounts(user_id)
        if not accounts:
            return await event.answer('❌ لا توجد حسابات مضافة لإضافة روابط لها!', alert=True)

        text = '🔗 **اختر الحساب الذي تريد إضافة روابط إليه:**'
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
        text = f'📱 **سجل روابط الواتساب العام:**\n\n• إجمالي الروابط: `{count}` رابط.\n'
        buttons = [
            [Button.inline('📄 استخراج ملف الروابط', b'export_global_wa'), Button.inline('🗑️ حذف السجل نهائياً', b'delete_global_wa')],
            [Button.inline('🔙 رجوع للقائمة الرئيسية', b'back_to_main')],
        ]
        await event.edit(text, buttons=buttons)

    elif data == b'export_global_wa':
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        links = load_list_from_file(global_wa_path)
        if not links:
            return await event.answer('ℹ️ السجل فارغ تماماً.', alert=True)

        file_path = os.path.join(user_folder, 'global_wa_export.txt')
        save_to_file(file_path, links)
        await bot.send_file(user_id, file_path, caption=f'📱 **ملف روابط الواتساب (إجمالي: {len(links)}):**')
        await event.answer('✅ تم إرسال الملف بنجاح!')

    elif data == b'delete_global_wa':
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        if os.path.exists(global_wa_path):
            os.remove(global_wa_path)
        await event.answer('🗑️ تم حذف السجل نهائياً!', alert=True)
        event.data = b'global_wa_menu'
        await callback_handler(event)

    elif data == b'stored_links_menu':
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        count = len(load_list_from_file(global_joined_path))
        text = f'📦 **سجل الانضمام العام (الروابط المخزونة):**\n\n• إجمالي الروابط: `{count}` رابط.\n'
        buttons = [
            [Button.inline('➕ إضافة روابط', b'add_to_stored_links'), Button.inline('📄 استخراج ملف', b'export_stored_links')],
            [Button.inline('🗑️ حذف السجل نهائياً', b'delete_stored_links')],
            [Button.inline('🔙 رجوع للقائمة الرئيسية', b'back_to_main')],
        ]
        await event.edit(text, buttons=buttons)

    elif data == b'add_to_stored_links':
        user_states[user_id] = {'action': 'waiting_stored_links'}
        await event.edit('➕ **إضافة روابط لسجل الانضمام العام**\n\nأرسل الروابط كنص أو ملف .txt:', buttons=[Button.inline('❌ إلغاء', b'cancel_state')])

    elif data == b'export_stored_links':
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        links = load_list_from_file(global_joined_path)
        if not links:
            return await event.answer('ℹ️ السجل فارغ تماماً.', alert=True)

        file_path = os.path.join(user_folder, 'global_joined_export.txt')
        save_to_file(file_path, links)
        await bot.send_file(user_id, file_path, caption=f'📦 **ملف الروابط المخزنة (إجمالي: {len(links)}):**')
        await event.answer('✅ تم إرسال الملف بنجاح!')

    elif data == b'delete_stored_links':
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        if os.path.exists(global_joined_path):
            os.remove(global_joined_path)
        await event.answer('🗑️ تم حذف السجل العام نهائياً!', alert=True)
        event.data = b'stored_links_menu'
        await callback_handler(event)

    elif data == b'manage_users':
        if user_id != ADMIN_ID:
            return await event.answer('⚠️ غير متاح لك!', alert=True)

        users = load_allowed_users()
        text = '👥 **قائمة المستخدمين المسموح لهم:**\n\n'
        buttons = []
        for idx, u_id in enumerate(users, 1):
            tag = "(المالك الأساسي)" if u_id == ADMIN_ID else ""
            buttons.append([Button.inline(f'#{idx} - 🆔 {u_id} {tag}', f'userinfo_{u_id}'.encode())])
        buttons.append([Button.inline('🔙 رجوع', b'back_to_main')])
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'userinfo_'):
        target_id = int(data.decode().replace('userinfo_', ''))
        text = f'👤 **تفاصيل المستخدم:** `{target_id}`\n\n'
        buttons = []
        if target_id != ADMIN_ID:
            buttons.append([Button.inline('❌ حذف المستخدم من البوت', f'deluser_{target_id}'.encode())])
        else:
            text += '⭐ هذا المالك الرئيسي للبوت ولا يمكن حذفه.\n'
        buttons.append([Button.inline('🔙 رجوع للقائمة', b'manage_users')])
        await event.edit(text, buttons=buttons)

    elif data.startswith(b'deluser_'):
        target_id = int(data.decode().replace('deluser_', ''))
        remove_allowed_user(target_id)
        await event.answer('🗑️ تم حذف المستخدم وسحب الصلاحية منه بنجاح!', alert=True)
        event.data = b'manage_users'
        await callback_handler(event)

    elif data == b'view_shared_private':
        shared_file = os.path.join(user_folder, SHARED_PRIVATE_FILE)
        private_links = load_list_from_file(shared_file)

        if not private_links:
            await event.answer('ℹ️ لا توجد روابط مجموعات خاصة مكتشفة حتى الآن.', alert=True)
        else:
            links_text = '\n'.join(private_links)
            if len(links_text) > 3900:
                file_path = os.path.join(user_folder, 'private_shared.txt')
                save_to_file(file_path, private_links)
                await bot.send_file(user_id, file_path, caption=f'🔒 **قائمة الجروبات الخاصة (إجمالي: {len(private_links)}):**')
            else:
                await event.edit(f'🔒 **قائمة الجروبات والروابط الخاصة (إجمالي: {len(private_links)}):**\n\n{links_text}', buttons=main_keyboard(user_id))

    elif data == b'manual_extract':
        await event.answer('⏳ جاري بدء الاستخراج اليدوي وتوزيع الروابط...')
        await event.edit('⚙️ جاري قراءة الرسائل والمحادثات لجميع حساباتك...')
        tg, wa = await run_full_extraction_and_distribute(user_id)
        await event.edit(
            f'✅ **اكتمل الاستخراج بنجاح!**\n\n• تم استخراج `{tg}` رابط تلجرام جديد.\n• تم استخراج `{wa}` رابط واتساب جديد.',
            buttons=main_keyboard(user_id),
        )

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

    elif data == b'view_stats':
        accounts = await get_active_accounts(user_id)
        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        global_joined_count = len(load_list_from_file(global_joined_path))
        global_wa_path = os.path.join(user_folder, GLOBAL_WA_FILE)
        global_wa_count = len(load_list_from_file(global_wa_path))

        text = '📊 **إحصائياتك المنفصلة العامّة:**\n\n'
        text += f'👤 عدد الحسابات: {len(accounts)}\n'
        text += f'✅ إجمالي الانضمامات الناجحة: {global_joined_count}\n'
        text += f'📱 إجمالي روابط الواتس المخزنة: {global_wa_count}\n\n'
        for idx, acc in enumerate(accounts, 1):
            links_file = os.path.join(user_folder, f'custom_{acc}_links.txt')
            rem = len(load_list_from_file(links_file))
            text += f'▫️ #{idx} الحساب `{acc}`: متبقي ({rem}) روابط في الانتظار.\n'
        await event.edit(text, buttons=main_keyboard(user_id))

    elif data == b'system_status':
        accounts = await get_active_accounts(user_id)
        is_running = running_tasks.get(user_id) and not running_tasks[user_id].done()
        status = '🟢 نشط ويعمل' if is_running else '🔴 متوقف'

        text = 'ℹ️ **حالة النظام والانتظارات الحالية:**\n\n'
        text += f'• الوضع العام للمدير: **{status}**\n'
        if is_running:
            text += f'• أحدث عمل قيد التنفيذ:\n{current_action_status.get(user_id, "لا يوجد")}\n\n'
        text += f'• الفاصل المعتمد: **{get_user_delay(user_id) // 60} دقيقة و {get_user_delay(user_id) % 60} ثانية**\n'
        text += f'• الحسابات المتوفرة: `{len(accounts)}` حساباً\n\n'

        user_floods = flood_expiry.get(user_id, {})
        now = time.time()
        for idx, acc in enumerate(accounts, 1):
            expiry = user_floods.get(acc, 0)
            if expiry > now:
                remaining_wait = int(expiry - now)
                text += f'▫️ #{idx} `{acc}`: ⏳ **محظور مؤقتاً** (متبقي {remaining_wait} ثانية)\n'
            else:
                links_file = os.path.join(user_folder, f'custom_{acc}_links.txt')
                rem = len(load_list_from_file(links_file))
                text += f'▫️ #{idx} `{acc}`: ✅ جاهز (متبقي {rem} رابط)\n'

        await event.edit(text, buttons=main_keyboard(user_id))

    elif data == b'view_delays':
        current_delay = get_user_delay(user_id)
        await event.edit(f'⏳ **إعدادات الانتظار الحالي:**\n\n• الوقت بين كل انضمام: `{current_delay // 60} دقيقة و {current_delay % 60} ثانية`.', buttons=main_keyboard(user_id))

    elif data == b'settings':
        current_delay = get_user_delay(user_id)
        text = f'⚙️ **لوحة إعدادات المحرك وتوقيت الانضمام:**\n\n⏱️ الفاصل الزمني الحالي: **{current_delay // 60} دقيقة** ({current_delay} ثانية).\n\n'
        await event.edit(text, buttons=settings_delay_keyboard())

    elif data == b'set_delay_5':
        join_delays[user_id] = 5 * 60
        await event.answer('✅ تم تحديد الفاصل إلى 5 دقائق.', alert=True)
        event.data = b'settings'
        await callback_handler(event)

    elif data == b'set_delay_10':
        join_delays[user_id] = 10 * 60
        await event.answer('✅ تم تحديد الفاصل إلى 10 دقائق.', alert=True)
        event.data = b'settings'
        await callback_handler(event)

    elif data == b'set_delay_custom':
        user_states[user_id] = {'action': 'waiting_custom_delay'}
        await event.edit('⚙️ **إدخال توقيت مخصص:**\n\nأرسل عدد الدقائق كمبلغ رقمي:', buttons=[Button.inline('❌ إلغاء', b'settings')])

    elif data == b'cancel_state':
        user_states[user_id] = None
        await event.edit('❌ تم إلغاء العملية والعودة للوحة الرئيسية.', buttons=main_keyboard(user_id))

    elif data == b'back_to_main':
        await event.edit('⭐ **اللوحة الرئيسية للتحكم:**', buttons=main_keyboard(user_id))

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
            return await event.respond('⚠️ يرجى إرسال **ملف نصي بصيغة (.txt)**:')

        file_bytes = await event.download_media(bytes)
        try:
            content = file_bytes.decode('utf-8', errors='ignore')
            links_found = re.findall(TG_LINK_REGEX, content)
        except Exception as e:
            return await event.respond(f'❌ خطأ في قراءة الملف: {e}')

        if not links_found:
            return await event.respond('⚠️ لم يتم العثور على أي روابط صالحة داخل الملف!')

        accounts = await get_active_accounts(user_id)
        if not accounts:
            user_states[user_id] = None
            return await event.respond('❌ لا توجد حسابات نشطة حالياً لتوزيع الروابط عليها.', buttons=main_keyboard(user_id))

        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        global_joined = set(load_list_from_file(global_joined_path))
        
        pending_links = set()
        for acc in accounts:
            acc_links_file = os.path.join(user_folder, f'custom_{acc}_links.txt')
            pending_links.update(load_list_from_file(acc_links_file))

        unique_links = []
        for l in links_found:
            if l not in global_joined and l not in pending_links and l not in unique_links:
                unique_links.append(l)

        duplicates_count = len(links_found) - len(unique_links)

        if not unique_links:
            user_states[user_id] = None
            return await event.respond(f'⚠️ جميع الروابط الموجودة في الملف مكررة وموجودة مسبقاً!', buttons=main_keyboard(user_id))

        chunk_size = (len(unique_links) + len(accounts) - 1) // len(accounts)
        distributed_info = ""

        for i, phone in enumerate(accounts):
            acc_chunk = unique_links[i * chunk_size : (i + 1) * chunk_size]
            if acc_chunk:
                acc_links_file = os.path.join(user_folder, f'custom_{phone}_links.txt')
                append_to_file(acc_links_file, acc_chunk)
                distributed_info += f"• `{phone}`: أضيف له `{len(acc_chunk)}` رابط.\n"

        user_states[user_id] = None
        msg_out = (
            f'✅ **تمت معالجة الملف وتوزيع الروابط بنجاح!**\n\n'
            f'• إجمالي الروابط: `{len(links_found)}` | المقبولة: `{len(unique_links)}` | المكررة: `{duplicates_count}`\n\n'
            f'📊 **تفاصيل التوزيع:**\n{distributed_info}'
        )
        await event.respond(msg_out, buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_stored_links':
        links_found = []
        if event.file and event.file.ext in ['.txt', '.text']:
            file_bytes = await event.download_media(bytes)
            try:
                content = file_bytes.decode('utf-8', errors='ignore')
                links_found = re.findall(TG_LINK_REGEX, content)
            except Exception as e:
                return await event.respond(f'❌ خطأ في قراءة الملف: {e}')
        elif event.text:
            links_found = re.findall(TG_LINK_REGEX, event.text)

        if not links_found:
            return await event.respond('⚠️ لم يتم العثور على أي روابط تلجرام صالحة.')

        global_joined_path = os.path.join(user_folder, GLOBAL_JOINED_FILE)
        count_before = len(load_list_from_file(global_joined_path))
        append_to_file(global_joined_path, links_found)
        count_after = len(load_list_from_file(global_joined_path))

        user_states[user_id] = None
        await event.respond(f'✅ **تمت إضافة الروابط بنجاح!**\n\n• الروابط المضافة: **{count_after - count_before}**', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_custom_delay':
        input_text = event.text.strip()
        if not input_text.isdigit() or int(input_text) <= 0:
            return await event.respond('⚠️ يرجى إدخال رقم صحيح أكبر من الصفر:')

        join_delays[user_id] = int(input_text) * 60
        user_states[user_id] = None
        await event.respond(f'✅ تم حفظ الإعدادات!\n⏱️ الفاصل المعتمد: **{input_text} دقيقة**.', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_phone':
        phone = event.text.strip()
        await event.respond('⏳ جاري محاولة إرسال كود التحقق للحساب...')
        client = TelegramClient(os.path.join(user_folder, phone), API_ID, API_HASH)
        await client.connect()

        try:
            send_code_result = await client.send_code_request(phone)
            user_states[user_id] = {'action': 'waiting_code', 'phone': phone, 'phone_code_hash': send_code_result.phone_code_hash, 'client': client}
            await event.respond(f'🔑 أرسل كود التحقق الواصل لحسابك `{phone}` الآن:')
        except Exception as e:
            await client.disconnect()
            user_states[user_id] = None
            await event.respond(f'❌ حدث خطأ:\n`{str(e)}`', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_code':
        code, phone, phone_code_hash, client = event.text.strip(), state['phone'], state['phone_code_hash'], state['client']
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            await event.respond(f'🎉 **تم تسجيل الحساب `{phone}` بنجاح!**', buttons=main_keyboard(user_id))
            await client.disconnect()
            user_states[user_id] = None
        except SessionPasswordNeededError:
            user_states[user_id]['action'] = 'waiting_password'
            await event.respond('🔐 الحساب محمي بكلمة سر (2FA). أرسل كلمة السر الآن:')
        except Exception as e:
            await client.disconnect()
            user_states[user_id] = None
            await event.respond(f'❌ خطأ بالكود: `{str(e)}`', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_password':
        password, client = event.text.strip(), state['client']
        try:
            await client.sign_in(password=password)
            await event.respond('🎉 **تم تسجيل الحساب بنجاح!**', buttons=main_keyboard(user_id))
            await client.disconnect()
            user_states[user_id] = None
        except Exception as e:
            await client.disconnect()
            user_states[user_id] = None
            await event.respond(f'❌ خطأ بالباسورد: `{str(e)}`', buttons=main_keyboard(user_id))

    elif state.get('action') == 'waiting_links':
        target_acc = state['target_acc']
        links = []
        if event.file and event.file.ext in ['.txt', '.text']:
            file_bytes = await event.download_media(bytes)
            try:
                content = file_bytes.decode('utf-8', errors='ignore')
                links = re.findall(TG_LINK_REGEX, content)
            except Exception as e:
                return await event.respond(f'❌ خطأ في قراءة الملف: {e}')
        elif event.text:
            links = re.findall(TG_LINK_REGEX, event.text)

        if not links:
            return await event.respond('⚠️ لم يتم العثور على روابط تلجرام صالحة.')

        global_joined_links = load_list_from_file(os.path.join(user_folder, GLOBAL_JOINED_FILE))
        filtered_links = [link for link in links if link not in global_joined_links]

        if not filtered_links:
            user_states[user_id] = None
            return await event.respond('⚠️ جميع الروابط المرسلة تم الانضمام لها مسبقاً.', buttons=main_keyboard(user_id))

        append_to_file(os.path.join(user_folder, f'custom_{target_acc}_links.txt'), filtered_links)
        user_states[user_id] = None
        await event.respond(f'✅ تم إضافة **{len(filtered_links)}** رابط جديد بنجاح.', buttons=main_keyboard(user_id))

# --- تشغيل البوت مع السيرفر والمهام الخلفية ---
async def main():
    Thread(target=run_flask, daemon=True).start()
    asyncio.create_task(scheduled_daily_extraction())
    await bot.start(bot_token=BOT_TOKEN)
    await set_bot_commands()
    print("[+] البوت يعمل الآن وتأكد من استقرار الاتصال...")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
