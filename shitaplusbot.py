import datetime
import os
import sqlite3
import pandas as pd
from telegram import Update, ReplyKeyboardMarkup, Bot
from telegram.ext import (
    CallbackContext,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters
)
import threading
import asyncio
import logging
import nest_asyncio  # اضافه کردن این خط


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


admin_id_str = os.getenv("ADMIN_ID")
if admin_id_str is None:
    logger.error("ADMIN_ID environment variable is not set. Please set it in your environment.")
    raise ValueError("ADMIN_ID environment variable is not set.")

bot_token = os.getenv("BOT_TOKEN")
if bot_token is None:
    logger.error("BOT_TOKEN environment variable is not set. Please set it in your environment.")
    raise ValueError("BOT_TOKEN environment variable is not set.")


ADMIN_ID = int(admin_id_str)


DB_PATH = 'user_data.db'
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        lastname TEXT,
        gender TEXT,
        height INTEGER,
        weight INTEGER,
        last_payment_date TEXT
    )
    ''')
    conn.commit()
except sqlite3.Error as e:
    logger.error(f"Error connecting to database: {e}")
    raise e


lock = threading.Lock()


async def remove_webhook(bot_token):
    try:
        bot = Bot(bot_token)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook successfully removed.")
    except Exception as e:
        logger.error(f"Error removing webhook: {e}")


def get_last_payment_date(user_id: int) -> datetime.date:
    try:
        cursor.execute('SELECT last_payment_date FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            return datetime.datetime.strptime(row[0], "%Y-%m-%d").date()
        return None
    except sqlite3.Error as e:
        logger.error(f"Error fetching last payment date for user {user_id}: {e}")
        return None


def save_user_info(user_info: dict) -> None:
    with lock:
        try:
            cursor.execute('''
                INSERT INTO users (user_id, name, lastname, gender, height, weight, last_payment_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                lastname=excluded.lastname,
                gender=excluded.gender,
                height=excluded.height,
                weight=excluded.weight,
                last_payment_date=excluded.last_payment_date
            ''', (user_info['user_id'], user_info['name'], user_info['lastname'],
                  user_info['gender'], user_info['height'], user_info['weight'],
                  user_info.get('last_payment_date')))
            conn.commit()
            logger.info(f"User {user_info['user_id']} info saved/updated.")
        except sqlite3.Error as e:
            logger.error(f"Error saving user info for {user_info['user_id']}: {e}")


def calculate_months_difference(date1: datetime.date, date2: datetime.date) -> int:
    try:
        return (date1.year - date2.year) * 12 + date1.month - date2.month
    except Exception as e:
        logger.error(f"Error calculating months difference between {date1} and {date2}: {e}")
        return 0


def get_payment_options(user_type: str) -> list:
    if user_type == 'new':
        return [['پرداخت آنلاین', 'پرداخت کارت به کارت']]
    elif user_type == 'old':
        return [['پرداخت نقدی', 'پرداخت با کارت']]
    else:
        return [['پرداخت آنلاین']]


# استیج‌های مختلف برای مکالمه
NAME, LASTNAME, GENDER, HEIGHT, WEIGHT = range(5)

# شروع مکالمه با درخواست نام
async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("لطفاً نام خود را وارد کنید:")
    return NAME

# دریافت نام و درخواست فامیل
async def get_name(update: Update, context: CallbackContext) -> int:
    context.user_data['name'] = update.message.text
    await update.message.reply_text("لطفاً نام خانوادگی خود را وارد کنید:")
    return LASTNAME

# دریافت فامیل و درخواست جنسیت
async def get_lastname(update: Update, context: CallbackContext) -> int:
    context.user_data['lastname'] = update.message.text
    await update.message.reply_text("لطفاً جنسیت خود را وارد کنید (مرد/زن):")
    return GENDER

# دریافت جنسیت و درخواست قد
async def get_gender(update: Update, context: CallbackContext) -> int:
    context.user_data['gender'] = update.message.text
    await update.message.reply_text("لطفاً قد خود را به سانتی‌متر وارد کنید:")
    return HEIGHT

# دریافت قد و درخواست وزن
async def get_height(update: Update, context: CallbackContext) -> int:
    context.user_data['height'] = update.message.text
    await update.message.reply_text("لطفاً وزن خود را به کیلوگرم وارد کنید:")
    return WEIGHT

# دریافت وزن و ذخیره اطلاعات در دیتابیس
async def get_weight(update: Update, context: CallbackContext) -> int:
    weight = update.message.text
    user_id = update.message.from_user.id
    name = context.user_data['name']
    lastname = context.user_data['lastname']
    gender = context.user_data['gender']
    height = context.user_data['height']

    # ذخیره در دیتابیس
    save_user_info({
        'user_id': user_id,
        'name': name,
        'lastname': lastname,
        'gender': gender,
        'height': height,
        'weight': weight
    })

    await update.message.reply_text("اطلاعات شما ذخیره شد.")
    return ConversationHandler.END

# کنسل کردن مکالمه
async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("مکالمه لغو شد.")
    return ConversationHandler.END


async def handle_selection(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.message.from_user.id
        last_payment_date = get_last_payment_date(user_id)
        user_type = 'new' if last_payment_date is None else 'old'

        payment_options = get_payment_options(user_type)

        if update.message.text == 'ثبت نام حضوری':
            await update.message.reply_text(
                "لطفاً باشگاه مورد نظر را انتخاب کنید:",
                reply_markup=ReplyKeyboardMarkup(
                    [['پالادیوم'], ['پرش طلایی'], ['برگشت']],
                    one_time_keyboard=True
                )
            )
        elif update.message.text == 'ثبت نام غیر حضوری':
            await update.message.reply_text(
                "لطفاً روش پرداخت را انتخاب کنید:",
                reply_markup=ReplyKeyboardMarkup(payment_options + [['برگشت']], one_time_keyboard=True)
            )
        elif update.message.text == 'پالادیوم' or update.message.text == 'پرش طلایی':
            options = []
            current_date = datetime.date.today()
            months_difference = 0
            if last_payment_date:
                months_difference = calculate_months_difference(current_date, last_payment_date)
            if months_difference <= 3:
                if update.message.text == 'پالادیوم':
                    options.extend([
                        'افراد قدیمی - 12 جلسه: 2,000,000 تومان',
                        'افراد قدیمی - 8 جلسه: 1,600,000 تومان'
                    ])
                else:
                    options.extend([
                        'افراد قدیمی - 16 جلسه: 1,200,000 تومان',
                        'افراد قدیمی - 12 جلسه: 1,000,000 تومان',
                        'افراد قدیمی - 8 جلسه: 800,000 تومان'
                    ])
            if update.message.text == 'پالادیوم':
                options.extend([
                    'افراد جدید - 12 جلسه: 2,500,000 تومان',
                    'افراد جدید - 8 جلسه: 2,000,000 تومان',
                    'کیک فیت - 3 جلسه کیک بوکس + 3 جلسه بدنی: 2,800,000 تومان',
                    'کیک فیت - 3 جلسه کیک بوکس + 2 جلسه بدنی: 3,700,000 تومان',
                    'کیک فیت - 2 جلسه کیک بوکس + 2 جلسه بدنی: 3,300,000 تومان',
                    'کیک فیت - 1 جلسه کیک بوکس + 2 جلسه بدنی: 4,100,000 تومان',
                    'برنامه تخصصی هر رشته - 16 جلسه: 2,500,000 تومان',
                    'برنامه تخصصی هر رشته - 12 جلسه: 2,000,000 تومان',
                    'برنامه تخصصی هر رشته - 8 جلسه: 1,500,000 تومان',
                    'برنامه تخصصی تغذیه: 500,000 تومان'
                ])
            else:
                options.extend([
                    'افراد جدید - 16 جلسه: 1,500,000 تومان',
                    'افراد جدید - 12 جلسه: 1,250,000 تومان',
                    'افراد جدید - 8 جلسه: 1,000,000 تومان',
                    'کیک فیت - 3 جلسه کیک بوکس + 3 جلسه بدنی: 2,800,000 تومان',
                    'کیک فیت - 3 جلسه کیک بوکس + 2 جلسه بدنی: 3,200,000 تومان',
                    'کیک فیت - 2 جلسه کیک بوکس + 2 جلسه بدنی: 2,500,000 تومان',
                    'کیک فیت - 1 جلسه کیک بوکس + 3 جلسه بدنی: 1,900,000 تومان',
                    'برنامه تخصصی هر رشته - 16 جلسه: 2,500,000 تومان',
                    'برنامه تخصصی هر رشته - 12 جلسه: 2,000,000 تومان',
                    'برنامه تخصصی هر رشته - 8 جلسه: 1,500,000 تومان',
                    'برنامه تخصصی تغذیه VIP: 2,000,000 تومان',
                    'برنامه تخصصی تغذیه VIP+: 2,500,000 تومان'
                ])
            await update.message.reply_text(
                "لطفاً گزینه مورد نظر را انتخاب کنید:",
                reply_markup=ReplyKeyboardMarkup(
                    [options[i:i+2] for i in range(0, len(options), 2)] + [['برگشت']],
                    one_time_keyboard=True
                )
            )
        elif update.message.text == 'برگشت':
            await start(update, context)
        else:
            await update.message.reply_text("لطفاً یک گزینه معتبر انتخاب کنید.")
    except Exception as e:
        logger.error(f"Error handling user selection: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفاً دوباره امتحان کنید.")


async def handle_admin(update: Update, context: CallbackContext) -> None:
    try:
        if update.message.from_user.id != ADMIN_ID:
            await update.message.reply_text("شما دسترسی لازم برای این فرمان را ندارید.")
            return

        df = pd.read_sql_query("SELECT * FROM users", conn)
        excel_file = 'user_data.xlsx'
        df.to_excel(excel_file, index=False)

        await update.message.reply_document(document=open(excel_file, 'rb'))
    except Exception as e:
        logger.error(f"Error handling admin command: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفاً دوباره امتحان کنید.")


async def unknown(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "دستور نامعتبر است. لطفاً یک گزینه معتبر را انتخاب کنید."
    )


async def main() -> None:
    await remove_webhook(bot_token)

    application = ApplicationBuilder().token(bot_token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            LASTNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_lastname)],
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_gender)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_weight)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("admin", handle_admin))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))  # هندلر برای دستورات ناشناس

    await application.run_polling()

if __name__ == '__main__':
    nest_asyncio.apply()
    asyncio.run(main())
