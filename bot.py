from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
import requests
import json
import logging

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Replace 'YOUR_TELEGRAM_BOT_TOKEN' with your actual bot token
TOKEN = '8356383599:AAH5xQrrUiDz1NXKqJi8-DLC8MDzaP8JT9Y'

# Replace 'YOUR_TERABOX_API_KEY' with your actual Terabox API key (if needed)
TERABOX_API_URL = 'https://weathered-mouse-6d3e.gaurav281833.workers.dev/api?url={TERABOX_LINK}'

# Dictionary to store user data
user_data = {}

# Admin ID
ADMIN_ID = '5016461081'  # Replace with your actual admin ID

def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    user_data[user_id] = {'subscription': 'free', 'daily_count': 0}
    update.message.reply_text('Welcome to the Terabox Video Downloader Bot! Send me a Terabox video link to download.')

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Send me a Terabox video link, and I will download it for you.')

def download_video(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id not in user_data:
        user_data[user_id] = {'subscription': 'free', 'daily_count': 0}

    if user_data[user_id]['subscription'] == 'free' and user_data[user_id]['daily_count'] >= 5:
        update.message.reply_text('You have reached your daily limit of 5 videos. Upgrade to a paid subscription for unlimited downloads.')
        return

    terabox_link = update.message.text
    try:
        # Use the Terabox API to get the video details
        api_url = TERABOX_API_URL.format(TERABOX_LINK=terabox_link)
        response = requests.get(api_url)
        response.raise_for_status()  # Raise an error for bad status codes

        # Parse the JSON response
        data = response.json()
        if 'files' not in data or not data['files']:
            update.message.reply_text('No files found in the response. Please check the link and try again.')
            return

        # Extract the direct download link
        direct_download_link = data['files'][0].get('direct_download_link')
        if not direct_download_link:
            update.message.reply_text('Failed to find the direct download link. Please check the link and try again.')
            return

        # Download the video from the direct download link
        video_response = requests.get(direct_download_link)
        video_response.raise_for_status()

        video_data = video_response.content
        # Save the video data to a file
        with open('video.mp4', 'wb') as f:
            f.write(video_data)
        # Upload the video to Telegram
        with open('video.mp4', 'rb') as f:
            update.message.reply_video(video=f)
        user_data[user_id]['daily_count'] += 1
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download the video: {e}")
        update.message.reply_text('Failed to download the video. Please check the link and try again.')
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse the API response: {e}")
        update.message.reply_text('Failed to parse the API response. Please check the link and try again.')

def subscribe(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Monthly Subscription", callback_data='monthly')],
        [InlineKeyboardButton("Yearly Subscription", callback_data='yearly')],
        [InlineKeyboardButton("Contact Owner", callback_data='contact_owner')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Choose a subscription plan:', reply_markup=reply_markup)

def button_click(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    if query.data == 'monthly':
        query.edit_message(text="You selected Monthly Subscription. Contact the owner for payment details.")
    elif query.data == 'yearly':
        query.edit_message(text="You selected Yearly Subscription. Contact the owner for payment details.")
    elif query.data == 'contact_owner':
        query.edit_message(text="Contact the owner at: owner@example.com")

def admin_panel(update: Update, context: CallbackContext) -> None:
    if str(update.effective_user.id) != ADMIN_ID:
        update.message.reply_text('You are not authorized to access the admin panel.')
        return

    keyboard = [
        [InlineKeyboardButton("Change Subscription Plans", callback_data='change_plans')],
        [InlineKeyboardButton("View Users", callback_data='view_users')],
        [InlineKeyboardButton("Customize Bot", callback_data='customize_bot')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Admin Panel:', reply_markup=reply_markup)

def admin_button_click(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    if query.data == 'change_plans':
        query.edit_message(text="Subscription plans can be customized here.")
    elif query.data == 'view_users':
        query.edit_message(text="List of users and their statuses.")
    elif query.data == 'customize_bot':
        query.edit_message(text="Customize the bot settings here.")

def main() -> None:
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("subscribe", subscribe))
    dispatcher.add_handler(CommandHandler("admin", admin_panel))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, download_video))
    dispatcher.add_handler(CallbackQueryHandler(button_click))
    dispatcher.add_handler(CallbackQueryHandler(admin_button_click))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
