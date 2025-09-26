# config.py — Optimized for speed

TELEGRAM_BOT_TOKEN = "8356383599:AAH5xQrrUiDz1NXKqJi8-DLC8MDzaP8JT9Y"

ADMIN_IDS = [5016461081]  # Replace with your Telegram ID

# Terabox API URL
TERABOX_API_URL = "https://weathered-mouse-6d3e.gaurav281833.workers.dev/api?url={}"

# Free user daily limit
FREE_USER_DAILY_LIMIT = 5

# Subscription durations (in days)
SUBSCRIPTION_DAYS = {
    "daily": 1,
    "monthly": 30,
    "yearly": 365
}

# Admin access key (used to activate premium)
ACCESS_KEY = "PAID123KEY"

# Performance settings
ENABLE_LOGGING = False  # Set to False in production for max speed
USE_STREAMING_UPLOAD = True  # Stream directly without buffering

# UI Texts (Fully customizable)
TEXTS = {
    "start": "🚀 Fast Terabox Downloader\nFree: 5/day • Premium: Unlimited",
    "processing": "⚡ Processing...",
    "uploading": "📤 Sending...",
    "success": "✅ Done!",
    "limit_reached": "🚫 Daily limit reached.",
    "invalid_link": "❌ Invalid link.",
    "premium_activated": "💎 Premium activated!",
    "contact_admin": "📞 Contact admin: @youradminhandle",
    "my_sub": "📜 Subscription: {}",
    "admin_set_key": "🔑 Enter new access key:",
    "admin_key_set": "✅ Access key updated.",
    "admin_add_user": "👤 Enter user ID to upgrade:",
    "admin_add_success": "✅ User {} upgraded to premium!",
    "admin_invalid_id": "❌ Invalid user ID."
}
