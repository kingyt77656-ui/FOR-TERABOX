# bot.py - HIGH SPEED VERSION
import logging
import asyncio
import uvloop  # Faster event loop
import orjson  # Faster JSON
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes
)
from config import BOT_TOKEN, FREE_DAILY_LIMIT, SUBSCRIPTION_PLANS, MAX_VIDEO_SIZE_MB
from database import *
from terabox import get_terabox_download_info, download_video_with_progress
from messages import *
from utils import is_admin, generate_key
import os
import re
from datetime import datetime, timedelta

# Use uvloop for faster async
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Regex
TERABOX_REGEX = re.compile(r'https?://(?:www\.)?terabox\.com/s/[\w\-]+')

# Connection pool for aiohttp
from aiohttp import TCPConnector, ClientSession
connector = TCPConnector(limit=100, limit_per_host=30, ttl_dns_cache=300)

# Semaphore to limit concurrent downloads
MAX_CONCURRENT_DOWNLOADS = 20
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# Cache for frequently accessed data
user_cache = {}
key_cache = {}

# Fast user cache
async def get_user_cached(user_id):
    if user_id in user_cache:
        return user_cache[user_id]
    user = await get_user(user_id)
    if user:
        user_cache[user_id] = user
    return user

# Fast key cache
async def get_key_cached(key):
    if key in key_cache:
        return key_cache[key]
    db_key = await get_key(key)
    if db_key:
        key_cache[key] = db_key
    return db_key

# Clear cache periodically
async def clear_cache_periodically():
    while True:
        await asyncio.sleep(300)  # 5 minutes
        user_cache.clear()
        key_cache.clear()

# Helper: Check if paid and active
async def is_paid_active(user_id):
    user = await get_user_cached(user_id)
    if not user:
        return False
    if not user[3]:  # is_paid
        return False
    if user[4]:  # paid_until
        paid_until = datetime.strptime(user[4], "%Y-%m-%d %H:%M:%S")
        return paid_until > datetime.now()
    return False

# Fast reset daily count
async def fast_reset_daily_count():
    await reset_daily_count()
    user_cache.clear()  # Clear cache after reset

# --- Command Handlers (Optimized) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await add_user(user.id, user.username, user.first_name)
    await update.message.reply_html(START_MSG)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(HELP_MSG)

async def subscription_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{SUBSCRIPTION_PLANS[k][1]}", callback_data=f"plan_{k}")]
        for k in SUBSCRIPTION_PLANS
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(SUBSCRIPTION_MSG, reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = query.data.replace("plan_", "")
    desc = SUBSCRIPTION_PLANS[plan][1]
    await query.edit_message_text(
        f"✅ You selected: <b>{desc}</b>\n\n"
        "📞 <b>Contact @YourAdminUsername to buy.</b>\n"
        "After payment, you'll get an access key to activate your plan.",
        parse_mode='HTML'
    )

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /claim <access_key>")
        return
    key = context.args[0].strip().upper()
    
    db_key = await get_key_cached(key)
    if not db_key:
        await update.message.reply_text("❌ Invalid access key.")
        return
    if db_key[2] is not None:
        await update.message.reply_text("❌ This key has already been used.")
        return

    duration_days = db_key[1]
    paid_until = datetime.now() + timedelta(days=duration_days)
    user_id = update.effective_user.id

    await update_user(user_id, is_paid=True, paid_until=paid_until.strftime("%Y-%m-%d %H:%M:%S"))
    await mark_key_used(key, user_id)
    
    # Update cache
    if user_id in user_cache:
        user_cache[user_id] = await get_user(user_id)

    await update.message.reply_html(PAID_SUCCESS.format(days=duration_days))

async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(CONTACT_MSG)

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user_cached(user_id)
    if not user:
        await update.message.reply_text("❌ User not found.")
        return

    if await is_paid_active(user_id):
        paid_until = datetime.strptime(user[4], "%Y-%m-%d %H:%M:%S")
        days_left = (paid_until - datetime.now()).days
        msg = f"✅ You are a <b>paid user</b>.\n<b>{days_left} days</b> remaining."
    else:
        msg = "❌ You are a <b>free user</b> (5 downloads/day).\nUpgrade for unlimited access."
    await update.message.reply_html(msg)

# --- HIGH SPEED Terabox Link Handler ---
async def handle_terabox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with download_semaphore:  # Limit concurrent downloads
        await process_terabox_download(update, context)

async def process_terabox_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    url = update.message.text.strip()

    if not TERABOX_REGEX.match(url):
        await update.message.reply_text("❌ Please send a valid Terabox link")
        return

    # Fast reset check
    await fast_reset_daily_count()

    user_data = await get_user_cached(user_id)
    if not user_data:
        await add_user(user_id, user.username, user.first_name)
        user_data = await get_user_cached(user_id)

    daily_count = user_data[5]
    is_paid = await is_paid_active(user_id)

    if not is_paid and daily_count >= FREE_DAILY_LIMIT:
        await update.message.reply_html(FREE_LIMIT_MSG)
        return

    status_msg = await update.message.reply_text("🔍 Fetching...")

    # Use faster session
    async with ClientSession(connector=connector) as session:
        info = await get_terabox_download_info(url, session)
        if not info["success"]:
            await status_msg.edit_text(f"❌ Failed: {info['error']}")
            return

        if info["size_mb"] > MAX_VIDEO_SIZE_MB:
            await status_msg.edit_text(
                f"❌ Too large: {info['size_mb']:.1f} MB. Max: {MAX_VIDEO_SIZE_MB} MB."
            )
            return

        # Send thumbnail if available
        if info["thumbnail"]:
            try:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=info["thumbnail"],
                    caption=f"🎥 {info['filename'][:30]}...\n📏 {info['size_mb']:.1f} MB"
                )
            except:
                pass  # Non-critical

        # Create file path
        file_path = f"downloads/{user_id}_{int(datetime.now().timestamp())}_{os.path.basename(info['filename'])}"
        os.makedirs("downloads", exist_ok=True)

        try:
            # Fast download with progress
            success = await download_video_with_progress(
                info["download_link"], file_path, update, context, status_msg, session
            )
            if not success:
                return

            await status_msg.edit_text("📤 Uploading...")
            
            # Fast upload
            with open(file_path, 'rb') as f:
                await context.bot.send_video(
                    chat_id=user_id,
                    video=InputFile(f, filename=info["filename"]),
                    caption=f"🎥 {info['filename'][:50]}...",
                    supports_streaming=True,
                    read_timeout=300,
                    write_timeout=300
                )

            # Update count for free users
            if not is_paid:
                await update_user(user_id, daily_count=daily_count + 1)
                # Update cache
                if user_id in user_cache:
                    user_cache[user_id] = await get_user(user_id)

            await status_msg.delete()

        except Exception as e:
            logger.error(f"Upload failed: {e}")
            await status_msg.edit_text("❌ Upload failed. Try again.")
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)

# --- Admin Commands (Optimized) ---
async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /genkey <plan>")
        return
    plan = context.args[0].lower()
    if plan not in SUBSCRIPTION_PLANS:
        await update.message.reply_text("❌ Invalid plan.")
        return
    duration_days = SUBSCRIPTION_PLANS[plan][0]
    key = generate_key()
    await add_key(key, duration_days)
    await update.message.reply_text(f"✅ Key:\n<code>{key}</code>\nPlan: {plan}", parse_mode='HTML')

async def listkeys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    keys = await get_all_keys()
    if not keys:
        await update.message.reply_text("📭 No keys found.")
        return
    msg = "🔑 <b>Keys:</b>\n\n"
    for k in keys[:20]:  # Limit to 20 for speed
        used = "Used" if k[2] else "Available"
        msg += f"<code>{k[0]}</code> ({k[1]}d) - {used}\n"
    await update.message.reply_html(msg)

async def delkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /delkey <key>")
        return
    key = context.args[0].strip().upper()
    db_key = await get_key_cached(key)
    if not db_key:
        await update.message.reply_text("❌ Key not found.")
        return
    await delete_key(key)
    if key in key_cache:
        del key_cache[key]
    await update.message.reply_text(f"✅ Key <code>{key}</code> deleted.", parse_mode='HTML')

async def adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /adduser <user_id> <plan>")
        return
    try:
        user_id = int(context.args[0])
        plan = context.args[1].lower()
        if plan not in SUBSCRIPTION_PLANS:
            await update.message.reply_text("❌ Invalid plan.")
            return
        duration_days = SUBSCRIPTION_PLANS[plan][0]
        paid_until = datetime.now() + timedelta(days=duration_days)
        await update_user(user_id, is_paid=True, paid_until=paid_until.strftime("%Y-%m-%d %H:%M:%S"))
        if user_id in user_cache:
            user_cache[user_id] = await get_user(user_id)
        await update.message.reply_text(f"✅ User {user_id} added to {plan} plan.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeuser <user_id>")
        return
    try:
        user_id = int(context.args[0])
        await update_user(user_id, is_paid=False, paid_until=None)
        if user_id in user_cache:
            del user_cache[user_id]
        await update.message.reply_text(f"✅ User {user_id} removed.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = ' '.join(context.args)
    async with aiosqlite.connect("users.db") as db:
        async with db.execute("SELECT user_id FROM users LIMIT 1000") as cursor:  # Limit for speed
            users = await cursor.fetchall()
    sent = 0
    for (user_id,) in users:
        try:
            await context.bot.send_message(chat_id=user_id, text=msg, read_timeout=10, write_timeout=10)
            sent += 1
        except:
            pass  # Skip failed users
    await update.message.reply_text(f"✅ Sent to {sent} users.")

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# --- Main ---
def main():
    # Start cache cleaner task
    loop = asyncio.get_event_loop()
    loop.create_task(clear_cache_periodically())
    
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscription", subscription_menu))
    application.add_handler(CommandHandler("claim", claim))
    application.add_handler(CommandHandler("contact", contact))
    application.add_handler(CommandHandler("myplan", check_subscription))

    application.add_handler(CommandHandler("genkey", genkey))
    application.add_handler(CommandHandler("listkeys", listkeys))
    application.add_handler(CommandHandler("delkey", delkey))
    application.add_handler(CommandHandler("adduser", adduser))
    application.add_handler(CommandHandler("removeuser", removeuser))
    application.add_handler(CommandHandler("broadcast", broadcast))

    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_terabox))

    application.add_error_handler(error_handler)

    print("🚀 HIGH-SPEED Terabox Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(init_db())
    main()
