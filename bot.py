# bot.py — MAXIMUM SPEED EDITION
import asyncio
import time
import orjson
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import httpx
from config import (
    TELEGRAM_BOT_TOKEN, ADMIN_IDS, TERABOX_API_URL,
    FREE_USER_DAILY_LIMIT, ACCESS_KEY, TEXTS,
    ENABLE_LOGGING, USE_STREAMING_UPLOAD
)

# ============= 🚀 GLOBAL STATE (IN-MEMORY CACHE) =============
_user_cache = {}
_db_path = "db.json"
_last_save_time = time.time()
_dirty = False

# Load DB into memory once at startup
def load_db():
    global _user_cache
    try:
        with open(_db_path, "rb") as f:
            data = orjson.loads(f.read())
            _user_cache = data.get("users", {})
    except FileNotFoundError:
        _user_cache = {}

def save_db_background():
    """Save only if dirty and not too frequently"""
    global _dirty, _last_save_time
    if not _dirty:
        return
    if time.time() - _last_save_time < 2:  # Throttle saves
        return
    try:
        with open(_db_path, "wb") as f:
            f.write(orjson.dumps({"users": _user_cache}))
        _dirty = False
        _last_save_time = time.time()
        if ENABLE_LOGGING:
            print("💾 Database saved")
    except Exception as e:
        if ENABLE_LOGGING:
            print(f"❌ Error saving database: {e}")

def get_user(user_id):
    uid = str(user_id)
    if uid not in _user_cache:
        _user_cache[uid] = {
            "is_paid": False,
            "access_key": "",
            "subscription_expiry": "",
            "downloads_today": 0,
            "last_download_date": ""
        }
    return _user_cache[uid]

def update_user(user_id, data):
    uid = str(user_id)
    user = get_user(user_id)
    _user_cache[uid] = {**user, **data}
    global _dirty
    _dirty = True
    # Schedule background save
    asyncio.create_task(asyncio.sleep(0))
    save_db_background()

def is_paid_user(user_id):
    user = get_user(user_id)
    now = datetime.utcnow()
    if user["is_paid"]:
        if user["subscription_expiry"]:
            try:
                expiry = datetime.fromisoformat(user["subscription_expiry"])
                return now < expiry
            except:
                return True
        else:
            return True
    return False

def reset_daily_downloads():
    today = datetime.utcnow().date().isoformat()
    for user_id in _user_cache:
        user = _user_cache[user_id]
        if user["last_download_date"] != today:
            user["downloads_today"] = 0
            user["last_download_date"] = today
    global _dirty
    _dirty = True
    if ENABLE_LOGGING:
        print("🔄 Daily download counters reset")

# ============= 🚀 ASYNC HTTP CLIENT (REUSED) =============
_http_client = None

async def get_http_client():
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            http2=True
        )
    return _http_client

# ============= ⚡ CORE HANDLERS (OPTIMIZED) =============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_data = get_user(user_id)
    is_paid = is_paid_user(user_id)

    keyboard = [[InlineKeyboardButton("📥 Download Video", callback_data="menu")]]
    
    if not is_paid:
        keyboard.append([InlineKeyboardButton("💎 Upgrade to Premium", callback_data="premium")])
    
    if user_id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
    else:
        keyboard.append([InlineKeyboardButton("📞 Contact Admin", callback_data="contact_admin")])

    text = TEXTS["start"]
    
    if not is_paid:
        remaining = FREE_USER_DAILY_LIMIT - user_data["downloads_today"]
        text += f"\n\nDownloads left today: {remaining}/{FREE_USER_DAILY_LIMIT}"
        if user_data["downloads_today"] >= FREE_USER_DAILY_LIMIT:
            text += f"\n{TEXTS['limit_reached']}"
    else:
        text += "\n\n✅ You have unlimited downloads!"

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        "📤 Send me any Terabox video link to download:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Back to Home", callback_data="start")
        ]])
    )

async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        f"💎 Premium Upgrade\n\n{TEXTS['contact_admin']}\n\nAfter payment, admin will activate your account with unlimited downloads.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Back", callback_data="start")
        ]])
    )

async def contact_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.edit_message_text(
        f"{TEXTS['contact_admin']}\n\nClick below to message admin directly:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Message Admin", url=f"tg://user?id={ADMIN_IDS[0]}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="start")]
        ])
    )

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.callback_query.edit_message_text(
        "🔐 Admin Panel\n\nSelect an option below:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Set Access Key", callback_data="admin_set_key")],
            [InlineKeyboardButton("👤 Add Premium User", callback_data="admin_add_user")],
            [InlineKeyboardButton("📊 View Users", callback_data="admin_view_users")],
            [InlineKeyboardButton("🏠 Back to Home", callback_data="start")]
        ])
    )

# ============= 📥 VIDEO DOWNLOAD HANDLER (ULTRA FAST) =============

async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    user = update.effective_user
    user_id = user.id
    link = update.message.text.strip()

    # Validate link
    if "terabox" not in link.lower():
        await update.message.reply_text(TEXTS["invalid_link"])
        return

    user_data = get_user(user_id)
    is_paid = is_paid_user(user_id)

    # Check daily limit for free users
    if not is_paid and user_data["downloads_today"] >= FREE_USER_DAILY_LIMIT:
        await update.message.reply_text(TEXTS["limit_reached"])
        return

    # Show processing message
    status_msg = await update.message.reply_text(TEXTS["processing"])

    try:
        # Get reusable HTTP client
        client = await get_http_client()
        
        # Fetch video info (async)
        api_url = TERABOX_API_URL.format(link)
        if ENABLE_LOGGING:
            print(f"📡 Fetching from API: {api_url[:100]}...")
            
        response = await client.get(api_url)
        if response.status_code != 200:
            await status_msg.edit_text("❌ API Error. Try again later.")
            return
            
        data = orjson.loads(response.content)
        video_url = data.get("video")
        
        if not video_url:
            await status_msg.edit_text("❌ Could not extract video. Link may be invalid.")
            return

        # Update download counter
        if not is_paid:
            user_data["downloads_today"] += 1
            update_user(user_id, {"downloads_today": user_data["downloads_today"]})

        await status_msg.edit_text(TEXTS["uploading"])

        # STREAM DIRECTLY TO TELEGRAM (NO BUFFERING)
        if USE_STREAMING_UPLOAD:
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_url,
                supports_streaming=True,
                read_timeout=60,
                write_timeout=60,
                connect_timeout=30
            )
        else:
            # Fallback: download then upload
            if ENABLE_LOGGING:
                print("📥 Downloading video content...")
            video_data = await client.get(video_url)
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video_data.content,
                supports_streaming=True
            )

        await status_msg.edit_text(TEXTS["success"])
        
        if ENABLE_LOGGING:
            duration = time.time() - start_time
            print(f"⏱️ Download completed in {duration:.2f}s")

    except Exception as e:
        if ENABLE_LOGGING:
            print(f"❌ Error: {str(e)}")
        await status_msg.edit_text("⚠️ Failed to process video. Please try again.")

# ============= 👑 ADMIN HANDLERS =============

async def admin_set_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.callback_query.edit_message_text(TEXTS["admin_set_key"])
    context.user_data["awaiting_key"] = True

async def admin_add_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.callback_query.edit_message_text(TEXTS["admin_add_user"])
    context.user_data["awaiting_user_id"] = True

async def admin_view_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    user_list = []
    for uid, data in _user_cache.items():
        status = "💎 Premium" if data["is_paid"] else "🆓 Free"
        if data["is_paid"] and data["subscription_expiry"]:
            expiry = data["subscription_expiry"][:10]
            status += f" (until {expiry})"
        downloads = data["downloads_today"]
        user_list.append(f"• {uid}: {status} | Today: {downloads} downloads")
    
    text = "📊 Users List:\n\n" + "\n".join(user_list[:50])  # Limit to 50 users
    if len(_user_cache) > 50:
        text += f"\n\n... and {len(_user_cache) - 50} more users"
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_panel")
        ]])
    )

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return

    text = update.message.text.strip()

    if context.user_data.get("awaiting_key"):
        global ACCESS_KEY
        ACCESS_KEY = text
        del context.user_data["awaiting_key"]
        await update.message.reply_text(TEXTS["admin_key_set"])
        
    elif context.user_data.get("awaiting_user_id"):
        try:
            target_id = int(text)
            expiry = (datetime.utcnow() + timedelta(days=30)).isoformat()
            update_user(target_id, {
                "is_paid": True,
                "access_key": ACCESS_KEY,
                "subscription_expiry": expiry
            })
            await update.message.reply_text(TEXTS["admin_add_success"].format(target_id))
        except Exception as e:
            if ENABLE_LOGGING:
                print(f"Error adding user: {e}")
            await update.message.reply_text(TEXTS["admin_invalid_id"])
        del context.user_data["awaiting_user_id"]

# ============= 🔄 CALLBACK ROUTER =============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    handlers = {
        "start": start,
        "menu": menu_callback,
        "premium": premium_callback,
        "contact_admin": contact_admin_callback,
        "admin_panel": admin_panel_callback,
        "admin_set_key": admin_set_key_callback,
        "admin_add_user": admin_add_user_callback,
        "admin_view_users": admin_view_users_callback,
    }
    
    handler = handlers.get(query.data)
    if handler:
        if asyncio.iscoroutinefunction(handler):
            await handler(update, context)
        else:
            await handler(update, context)

# ============= 🚀 STARTUP & DAILY RESET =============

async def daily_reset_task():
    while True:
        now = datetime.utcnow()
        # Calculate seconds until next UTC midnight
        tomorrow = now.date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, datetime.min.time())
        sleep_seconds = (midnight - now).total_seconds()
        
        if ENABLE_LOGGING:
            print(f"💤 Sleeping for {sleep_seconds:.0f} seconds until next daily reset")
            
        await asyncio.sleep(sleep_seconds)
        reset_daily_downloads()

def main():
    # Load database into memory
    load_db()
    
    # Create bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_video_link))
    application.add_handler(MessageHandler(filters.TEXT, handle_admin_input))
    
    # Start daily reset task
    asyncio.create_task(daily_reset_task())
    
    if ENABLE_LOGGING:
        print("🚀 Bot starting with maximum performance...")
        print(f"👥 Loaded {_user_cache.__len__()} users from database")
    
    # Start polling
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
