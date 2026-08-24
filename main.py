import os
import glob
import asyncio
import urllib.request
import unicodedata
import re
from threading import Thread
from flask import Flask
from PIL import Image
import numpy as np
import onnxruntime as ort
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import Channel, Chat

# --- البيانات الأساسية ---
API_ID = int(os.environ.get("API_ID", 30327806))
API_HASH = os.environ.get("API_HASH", "e2fddd21d8966b80eeb0fed4c37a7597")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8620273059:AAE6jHcDIb0S3BxlUJffdrZMRtOhC5qSA4k")

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# --- تحميل نموذج ONNX ---
MODEL_PATH = "detector.onnx"
MODEL_URL = "https://github.com/nottyo/NudeNet/releases/download/v0.0/detector.onnx"

if not os.path.exists(MODEL_PATH):
    print("جاري تحميل نموذج الفحص...")
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("تم تحميل النموذج بنجاح!")
    except Exception as e:
        print(f"⚠️ تعذر تحميل النموذج تلقائياً: {e}")

session_ort = None
if os.path.exists(MODEL_PATH):
    try:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        session_ort = ort.InferenceSession(MODEL_PATH, opts)
    except Exception as e:
        print(f"فشل إعداد نموذج ONNX: {e}")

# --- سيرفر Flask لمنع توقف الخدمة ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Cleaner Bot is Running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

Thread(target=run_flask, daemon=True).start()

# --- الكلمات المخالفة موسعة ---
EXPLICIT_KEYWORDS = [
    "سكس", "جنس", "اباحي", "إباحي", "شرموط", "قحبة", "دعارة", "فضايح", "فضيحة",
    "سكسي", "تعري", "نيك", "ممحونة", "ورعان", "طيز", "زب", "كس", "افلام جنس",
    "porn", "paja", "placer", "caliente", "squirt", "modelos", "girls", "girl",
    "sex", "nude", "adult", "18+", "nsfw", "xxx", "erotic", "hentai", "vip",
    "onlyfans", "leak", "stripper", "hot", "topless", "bitch", "tanguita", "archivos",
    "🔞", "💦", "🍑", "🍆", "👙"
]

bot = TelegramClient('official_cleaner_bot', API_ID, API_HASH)
user_states = {}

MAIN_KEYBOARD = [
    [Button.text("➕ إضافة حساب", resize=True), Button.text("👥 الحسابات", resize=True)],
    [Button.text("▶️ تشغيل الفحص", resize=True)]
]

def normalize_text(text):
    """إزالة الزخارف والرموز وتحويل الأحرف للنمط القياسي"""
    if not text:
        return ""
    # تطبيع Unicode لإزالة التشكيل والزخارف الأحرفية
    text = unicodedata.normalize('NFKD', text)
    # إزالة الأشكال والرموز الملتصقة بالكلمات
    text = re.sub(r'[^\w\s]', '', text)
    return text.lower()

def is_explicit_text(text):
    if not text:
        return False
    
    # فحص النص الأصلي والمطهر
    raw_text = text.lower()
    clean_text = normalize_text(text)
    
    for kw in EXPLICIT_KEYWORDS:
        if kw in raw_text or kw in clean_text:
            return True
    return False

def is_explicit_image(image_path):
    if not session_ort:
        return False
    try:
        with Image.open(image_path) as img:
            img = img.convert('RGB').resize((320, 320))
            img_data = np.array(img).astype(np.float32) / 255.0
            img_data = np.transpose(img_data, (2, 0, 1))
            img_data = np.expand_dims(img_data, axis=0)

        input_name = session_ort.get_inputs()[0].name
        outputs = session_ort.run(None, {input_name: img_data})
        
        if len(outputs) > 0 and len(outputs[0]) > 0:
            for detection in outputs[0]:
                score = detection[4] if len(detection) > 4 else 0
                if score > 0.35: # تخفيض الحساسية لالتقاط الصور المشبوهة بدقة أكبر
                    return True
    except Exception as e:
        print(f"خطأ في فحص الصورة: {e}")
    return False

async def clean_account(session_file, status_msg):
    phone = os.path.basename(session_file).replace('.session', '')
    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            session_str = f.read().strip()
    except Exception as e:
        await status_msg.respond(f"❌ خطأ في قراءة ملف الجلسة `{phone}`: {e}")
        return 0

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await status_msg.respond(f"❌ الجلسة للحساب `{phone}` منتهية.")
            await client.disconnect()
            return 0
    except Exception as e:
        await status_msg.respond(f"⚠️ فشل الاتصال بالحساب `{phone}`: {e}")
        return 0

    left_count = 0
    temp_dir = "temp_media_cleaner"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, (Channel, Chat)):
                continue

            title = dialog.name or ""
            username = getattr(entity, 'username', '') or ""
            is_explicit = False

            # 1. فحص اسم المجموعة والمعرف (Username)
            if is_explicit_text(title) or is_explicit_text(username):
                is_explicit = True

            # 2. فحص صورة المجموعة الشخصية
            if not is_explicit:
                try:
                    photo_path = await client.download_profile_photo(entity, file=os.path.join(temp_dir, f"{phone}_prof.jpg"))
                    if photo_path and is_explicit_image(photo_path):
                        is_explicit = True
                    if photo_path and os.path.exists(photo_path):
                        os.remove(photo_path)
                except Exception:
                    pass

            # 3. فحص أحدث 30 رسالة (نصوص، توجيهات، وصور)
            if not is_explicit:
                try:
                    async for message in client.iter_messages(entity, limit=30):
                        msg_text = message.text or message.caption or ""
                        
                        # فحص النص والرسائل الموجهة (Forward Header)
                        if is_explicit_text(msg_text):
                            is_explicit = True
                            break

                        if message.fwd_from and message.fwd_from.from_name:
                            if is_explicit_text(message.fwd_from.from_name):
                                is_explicit = True
                                break

                        # فحص وسائط الرسالة
                        if message.photo:
                            try:
                                media_path = await message.download_media(file=os.path.join(temp_dir, f"{phone}_msg.jpg"))
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

            # تنفيذ المغادرة إذا ثبتت المخالفة
            if is_explicit:
                try:
                    await client(LeaveChannelRequest(entity))
                    left_count += 1
                    await status_msg.edit(f"⏳ جاري فحص `{phone}`...\n🚨 تم المغادرة من: **{title}**\nإجمالي المغادرات: {left_count}")
                    await asyncio.sleep(1)
                except Exception:
                    pass
    finally:
        await client.disconnect()

    return left_count

# --- الأحداث والردود ---
@bot.on(events.NewMessage(pattern=r'^/start'))
async def start_handler(event):
    if event.out:
        return
    user_states[event.chat_id] = None
    await event.respond("أهلاً بك! اختر من الأزرار بالأسفل للبدء:", buttons=MAIN_KEYBOARD)

@bot.on(events.NewMessage(pattern=r'^(➕ إضافة حساب|👥 الحسابات|▶️ تشغيل الفحص)$'))
async def buttons_handler(event):
    if event.out:
        return
    chat_id = event.chat_id
    text = event.text.strip()

    if text == "➕ إضافة حساب":
        user_states[chat_id] = {'step': 'await_phone'}
        await event.respond("📱 أرسل رقم الهاتف مع مفتاح الدولة (مثال: `+966500000000`):")

    elif text == "👥 الحسابات":
        sessions = glob.glob(f"{SESSIONS_DIR}/*.session")
        if not sessions:
            await event.respond("لا توجد حسابات محفوظة حالياً.")
            return

        msg = "📱 **الحسابات المسجلة:**\n\n"
        buttons = []
        for s in sessions:
            phone = os.path.basename(s).replace('.session', '')
            msg += f"• `{phone}`\n"
            buttons.append([Button.inline(f"🗑 حذف {phone}", data=f"del_{phone}")])

        await event.respond(msg, buttons=buttons)

    elif text == "▶️ تشغيل الفحص":
        sessions = glob.glob(f"{SESSIONS_DIR}/*.session")
        if not sessions:
            await event.respond("⚠️ لا توجد حسابات مضافة!")
            return

        status_msg = await event.respond("🚀 جاري بدء الفحص الشامل للصور، النصوص، والزخارف...")
        total_cleaned = 0

        for session_file in sessions:
            phone = os.path.basename(session_file).replace('.session', '')
            await status_msg.edit(f"🔍 جاري فحص الحساب: `{phone}`...")
            count = await clean_account(session_file, status_msg)
            total_cleaned += count

        await status_msg.edit(f"✅ اكتمل الفحص!\nإجمالي المجموعات التي غادرها البوت: **{total_cleaned}**")

@bot.on(events.NewMessage)
async def input_handler(event):
    if event.out:
        return

    chat_id = event.chat_id
    text = event.text.strip() if event.text else ""

    if text.startswith('/') or text in ["➕ إضافة حساب", "👥 الحسابات", "▶️ تشغيل الفحص"]:
        return

    state = user_states.get(chat_id)
    if not state:
        return

    if state.get('step') == 'await_phone':
        if not (text.startswith('+') and text[1:].isdigit()):
            await event.respond("⚠️ رقم غير صحيح! أرسل الرقم بالصيغة الدولية.")
            return

        status_msg = await event.respond("جاري إرسال كود التحقق...")
        temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
        await temp_client.connect()

        try:
            res = await temp_client.send_code_request(text)
            user_states[chat_id] = {
                'step': 'await_code',
                'client': temp_client,
                'phone': text,
                'phone_code_hash': res.phone_code_hash
            }
            await status_msg.edit("تم إرسال الكود في تلجرام. أرسل الكود هنا:")
        except Exception as e:
            await status_msg.edit(f"❌ تعذر إرسال الكود: {e}")
            await temp_client.disconnect()
            user_states[chat_id] = None

    elif state.get('step') == 'await_code':
        client = state['client']
        phone = state['phone']
        hash_val = state['phone_code_hash']

        status_msg = await event.respond("جاري التحقق...")
        try:
            await client.sign_in(phone, text, phone_code_hash=hash_val)
        except Exception as e:
            if "TWO_STEP" in str(e) or "Password" in str(e):
                user_states[chat_id]['step'] = 'await_password'
                await status_msg.edit("الحساب محمّي بكلمة مرور، أرسل كلمة المرور:")
                return
            else:
                await status_msg.edit(f"❌ كود خاطئ: {e}")
                await client.disconnect()
                user_states[chat_id] = None
                return

        session_str = client.session.save()
        with open(os.path.join(SESSIONS_DIR, f"{phone}.session"), 'w', encoding='utf-8') as f:
            f.write(session_str)

        await client.disconnect()
        await status_msg.edit(f"✅ تم حفظ الحساب `{phone}` بنجاح!", buttons=MAIN_KEYBOARD)
        user_states[chat_id] = None

    elif state.get('step') == 'await_password':
        client = state['client']
        phone = state['phone']

        status_msg = await event.respond("جاري التحقق من كلمة المرور...")
        try:
            await client.sign_in(password=text)
        except Exception as e:
            await status_msg.edit(f"❌ كلمة المرور خاطئة: {e}")
            return

        session_str = client.session.save()
        with open(os.path.join(SESSIONS_DIR, f"{phone}.session"), 'w', encoding='utf-8') as f:
            f.write(session_str)

        await client.disconnect()
        await status_msg.edit(f"✅ تم حفظ الحساب `{phone}` بنجاح!", buttons=MAIN_KEYBOARD)
        user_states[chat_id] = None

@bot.on(events.CallbackQuery(pattern=r'^del_'))
async def delete_account_handler(event):
    phone = event.data.decode('utf-8').replace('del_', '')
    session_file = os.path.join(SESSIONS_DIR, f"{phone}.session")

    if os.path.exists(session_file):
        os.remove(session_file)
        await event.answer("تم حذف الحساب!", alert=True)
        await event.delete()
    else:
        await event.answer("الحساب غير موجود.", alert=True)

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    print("البوت يعمل الآن بالميزات المحدثة...")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
