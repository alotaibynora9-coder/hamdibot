import os
import asyncio
from threading import Thread
from flask import Flask
from PIL import Image
from nudenet import NudeDetector
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.types import Channel, Chat

# البيانات الخاصة بالبوت في السيرفر الجديد
API_ID = 7226664693
API_HASH = '4e7a8aee718c1e8e63956fec3339d01d'
BOT_TOKEN = '8620273059:AAE6jHcDIb0S3BxlUJffdrZMRtOhC5qSA4k'

# --- سيرفر Flask لمنع إغلاق الخدمة من الاستضافة ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Bot2 Cleaner Service is Online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# تشغيل الـ Web Server في الخلفية
Thread(target=run_flask, daemon=True).start()

# --- قائمة الكلمات والتصنيفات ---
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

detector = NudeDetector()
user_states = {}

# إنشاء كائن البوت مع جلسة مستقلة
bot = TelegramClient('standalone_cleaner_bot', API_ID, API_HASH)

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

async def inspect_and_clean(user_client, status_msg):
    left_count = 0
    temp_dir = "temp_media_cleaner"
    os.makedirs(temp_dir, exist_ok=True)

    async for dialog in user_client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, (Channel, Chat)):
            continue

        title = dialog.name or ""
        is_explicit = False

        if is_explicit_text(title):
            is_explicit = True

        if not is_explicit:
            try:
                photo_path = await user_client.download_profile_photo(entity, file=os.path.join(temp_dir, "profile.jpg"))
                if photo_path and is_explicit_image(photo_path):
                    is_explicit = True
                if photo_path and os.path.exists(photo_path):
                    os.remove(photo_path)
            except Exception:
                pass

        if not is_explicit:
            try:
                async for message in user_client.iter_messages(entity, limit=15):
                    msg_text = message.text or message.caption or ""
                    if is_explicit_text(msg_text):
                        is_explicit = True
                        break

                    if message.photo:
                        try:
                            media_path = await message.download_media(file=os.path.join(temp_dir, "msg_media.jpg"))
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
                await user_client(LeaveChannelRequest(entity))
                left_count += 1
                await status_msg.edit(f"⏳ جاري الفحص...\nتم اكتشاف ومغادرة: **{title}**\nإجمالي المغادرات حتى الآن: {left_count}")
                await asyncio.sleep(2)
            except Exception:
                pass

    return left_count

# --- معالجة أمر /start ---
@bot.on(events.NewMessage(pattern=r'^/start'))
async def start_handler(event):
    await event.respond(
        "أهلاً بك في بوت تنظيف الحسابات! 🧹\n\n"
        "لتبدأ فحص حسابك، أرسل رقم الهاتف مع مفتاح الدولة (مثال: `+966500000000`)"
    )

# --- معالجة الرسائل العادية للتعامل مع تسجيل الدخول ---
@bot.on(events.NewMessage)
async def message_handler(event):
    if event.text.startswith('/'):
        return

    chat_id = event.chat_id
    text = event.text.strip()

    # مرحلة كود التحقق
    if chat_id in user_states and user_states[chat_id].get('step') == 'await_code':
        data = user_states[chat_id]
        client = data['client']
        phone = data['phone']
        phone_code_hash = data['phone_code_hash']

        status_msg = await event.respond("جاري التحقق من الكود...")
        try:
            await client.sign_in(phone, text, phone_code_hash=phone_code_hash)
        except Exception as e:
            if "TWO_STEP" in str(e):
                user_states[chat_id]['step'] = 'await_password'
                await status_msg.edit("الحساب محمّي بكلمة سر (التحقق بخطوتين)، يرجى إرسال كلمة السر الآن:")
                return
            else:
                await status_msg.edit(f"فشل التسجيل: {e}")
                del user_states[chat_id]
                return

        await status_msg.edit("تم تسجيل الدخول بنجاح! 🚀 جاري بدء فحص القنوات والمجموعات...")
        count = await inspect_and_clean(client, status_msg)
        await client.disconnect()
        await status_msg.edit(f"✅ اكتمل الفحص بنجاح!\nعدد المجموعات والقنوات الإباحية التي تم الخروج منها: **{count}**")
        del user_states[chat_id]
        return

    # مرحلة كلمة سر التحقق بخطوتين
    elif chat_id in user_states and user_states[chat_id].get('step') == 'await_password':
        data = user_states[chat_id]
        client = data['client']
        
        status_msg = await event.respond("جاري فحص كلمة السر...")
        try:
            await client.sign_in(password=text)
        except Exception as e:
            await status_msg.edit(f"كلمة السر خاطئة: {e}")
            return

        await status_msg.edit("تم تسجيل الدخول بنجاح! 🚀 جاري بدء فحص القنوات والمجموعات...")
        count = await inspect_and_clean(client, status_msg)
        await client.disconnect()
        await status_msg.edit(f"✅ اكتمل الفحص بنجاح!\nعدد المجموعات والقنوات الإباحية التي تم الخروج منها: **{count}**")
        del user_states[chat_id]
        return

    # مرحلة إرسال رقم الهاتف
    elif text.startswith('+') and text[1:].isdigit():
        status_msg = await event.respond("جاري إرسال كود التحقق إلى حسابك...")
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
            await status_msg.edit("تم إرسال كود التحقق عبر التلجرام. أرسل الكود هنا:")
        except Exception as e:
            await status_msg.edit(f"تعذر إرسال الكود: {e}")
            await temp_client.disconnect()

if __name__ == '__main__':
    print("السيرفر المستقل يعمل الآن...")
    bot.start(bot_token=BOT_TOKEN)
    bot.run_until_disconnected()
