import logging
import asyncio
from datetime import datetime, timedelta
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

# ==========================================
# الإعدادات الأساسية
# ==========================================
BOT_TOKEN = "2017218286:AAGh_0CO3bOyOJ-UkPDGJvITYwguA25icw4"
INSTAGRAM_ACCOUNT = "https://instagram.com/user98eh70s2"
SEARXNG_URL = "https://searx.tiekoetter.com/search"

# إعدادات الـ Rate Limit
MAX_ATTEMPTS = 3
HOURS_LIMIT = 3

# إعدادات تسجيل الأخطاء (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# قواعد البيانات المؤقتة (في الرام)
# ==========================================
# لتخزين المستخدمين الذين ضغطوا على "تم المتابعة"
authorized_users = set()

# لتخزين عدد المحاولات لكل مستخدم
# Structure: {user_id: {"count": int, "reset_time": datetime}}
user_rate_limits = {}

# ==========================================
# الدوال المساعدة
# ==========================================
def check_rate_limit(user_id: int) -> tuple[bool, int, int]:
    """
    تتحقق مما إذا كان المستخدم قد تجاوز الحد المسموح.
    ترجع (مسموح_أم_لا, الساعات_المتبقية, الدقائق_المتبقية)
    """
    now = datetime.now()
    
    # إذا كان المستخدم جديداً في سجل البحث
    if user_id not in user_rate_limits:
        user_rate_limits[user_id] = {
            "count": 1,
            "reset_time": now + timedelta(hours=HOURS_LIMIT)
        }
        return True, 0, 0

    user_data = user_rate_limits[user_id]
    
    # إذا انتهت فترة الحظر (مرت 3 ساعات)
    if now >= user_data["reset_time"]:
        user_data["count"] = 1
        user_data["reset_time"] = now + timedelta(hours=HOURS_LIMIT)
        return True, 0, 0

    # إذا لم تنتهِ الفترة ولكن لديه محاولات متبقية
    if user_data["count"] < MAX_ATTEMPTS:
        user_data["count"] += 1
        return True, 0, 0

    # إذا تجاوز الحد المسموح، نحسب الوقت المتبقي
    time_left = user_data["reset_time"] - now
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    return False, hours, minutes

# ==========================================
# دوال البوت (Handlers)
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع أمر /start"""
    keyboard = [
        [InlineKeyboardButton("تم المتابعة", callback_data='followed')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"مرحبًا! لاستخدام البوت يجب متابعة حساب الانستقرام التالي:\n"
        f"{INSTAGRAM_ACCOUNT}\n"
        f"بعد المتابعة اضغط زر 'تم المتابعة'"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع ضغطة زر 'تم المتابعة'"""
    query = update.callback_query
    await query.answer() # لإخفاء علامة التحميل من الزر
    
    if query.data == 'followed':
        authorized_users.add(query.from_user.id)
        await query.edit_message_text(
            text="شكراً لك! يمكنك الآن إرسال اسم حساب الانستقرام للبحث عنه."
        )

async def handle_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع الرسائل النصية (اسم الحساب)"""
    user_id = update.message.from_user.id
    
    # 1. التحقق من ضغط زر المتابعة
    if user_id not in authorized_users:
        await update.message.reply_text("الرجاء إرسال /start والضغط على زر 'تم المتابعة' أولاً.")
        return

    # 2. التحقق من Rate Limit
    is_allowed, hours_left, mins_left = check_rate_limit(user_id)
    if not is_allowed:
        await update.message.reply_text(
            f"وصلت الحد الأقصى ({MAX_ATTEMPTS} محاولات). "
            f"حاول بعد {hours_left} ساعة و {mins_left} دقيقة."
        )
        return

    username = update.message.text.strip()
    status_message = await update.message.reply_text("جاري البحث...")

    # 3. إعداد استعلام البحث
    search_query = f'site:instagram.com intext:"{username}"'
    params = {
        'q': search_query,
        'format': 'json'
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    # 4. تنفيذ البحث واستخراج النتائج
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(SEARXNG_URL, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get('results', [])
                    
                    # فلترة النتائج
                    valid_results = []
                    for r in results:
                        url = r.get('url', '')
                        title = r.get('title', 'بدون عنوان')
                        
                        if 'instagram.com' in url:
                            valid_results.append(f"{title}\n{url}")
                            
                        # نكتفي بأول 5 نتائج
                        if len(valid_results) >= 5:
                            break
                    
                    # 5. إرسال النتائج للمستخدم
                    if not valid_results:
                        await status_message.edit_text("لم يتم العثور على نتائج.")
                    else:
                        response_text = "\n\n".join(valid_results)
                        await status_message.edit_text(response_text)
                else:
                    logger.warning(f"SearXNG returned status {response.status}")
                    await status_message.edit_text("حدث خطأ أثناء البحث (رفض المحرك الطلب).")
                    
    except Exception as e:
        logger.error(f"Search Error: {str(e)}")
        await status_message.edit_text("حدث خطأ أثناء البحث.")

# ==========================================
# تشغيل البوت
# ==========================================
if __name__ == '__main__':
    # بناء التطبيق
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # إضافة الموجهات (Handlers)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_callback))
    # استقبال أي نص على أنه اسم حساب للبحث
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_username))

    # تشغيل البوت
    print("Bot is running...")
    app.run_polling()
