import discord
from discord.ext import commands
from flask import Flask, request, jsonify
import asyncio
import logging
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.INFO)

# Your Discord bot token (replace with your bot token)
DISCORD_TOKEN = 'MTI3OTkyOTE1OTEzNjU3NTUxOA.GgNms2.CFQewGJ7-7smOxcS6tmPwtOLCtZERzAMvJn9yo'  # Replace with your actual token

# Discord channel ID where the bot will send messages
DISCORD_CHANNEL_ID = 1281081570253475923  # Replace with the actual channel ID

# Initialize Flask app
app = Flask(__name__)

# Create an instance of a Discord bot with commands
intents = discord.Intents.default()
intents.message_content = True  # Enable the message content intent
bot = commands.Bot(command_prefix="!", intents=intents)

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    try:
        # Log the incoming request headers and body
        logging.info(f"Request received: {request.method} {request.url}")
        logging.info(f"Request headers: {request.headers}")
        logging.info(f"Request body: {request.data}")

        # Get the JSON data sent from Wix
        data = request.json
        logging.info(f"Received data from Wix: {data}")

        # Extract relevant fields from the form submission
        form_data = data.get('data', {})
        submissions = form_data.get('submissions', [])

        # Initialize variables for extracted information
        name = None
        phone_number = None
        gender = None
        age = None
        nicotine_use = None
        estimated_credit = None
        zip_code = None

        # Extract specific fields based on the labels
        for submission in submissions:
            if submission['label'] == 'Name':
                name = submission['value']
            elif submission['label'] == 'Phone number':
                phone_number = submission['value']
            elif submission['label'] == 'Gender':
                gender = submission['value']
            elif submission['label'] == 'Age':
                age = submission['value']
            elif submission['label'] == 'Nicotiene use':
                nicotine_use = submission['value']
            elif submission['label'] == 'Estimated credit':
                estimated_credit = submission['value']
            elif submission['label'] == 'Zip code':
                zip_code = submission['value']

        # Ensure required fields are present
        if not name or not phone_number:
            logging.error("Missing essential data fields in the received webhook payload.")
            return jsonify({"status": "error", "message": "Missing essential data fields"}), 400

        # Construct the message to be sent to Discord
        discord_message = (
            f"New Lead:\n"
            f"Name: {name}\n"
            f"Phone Number: {phone_number}\n"
            f"Gender: {gender}\n"
            f"Age: {age}\n"
            f"Nicotiene Use: {nicotine_use}\n"
            f"Estimated Credit: {estimated_credit}\n"
            f"Zip Code: {zip_code}"
        )
        logging.info(f"Prepared message for Discord: {discord_message}")

        # Send a message to Discord
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            asyncio.run_coroutine_threadsafe(channel.send(discord_message), bot.loop)
            logging.info("Message successfully sent to Discord")
        else:
            logging.error(f"Could not find channel with ID: {DISCORD_CHANNEL_ID}")
            return jsonify({"status": "error", "message": "Invalid Discord channel ID"}), 500

        return jsonify({"status": "success", "message": "Lead sent to Discord"}), 200

    except Exception as e:
        logging.error(f"Error occurred in handle_wix_webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    logging.info('------')

@bot.event
async def on_disconnect():
    logging.warning('Bot disconnected! Attempting to reconnect...')

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)  # Use port 10000 as Render expects apps to run on this port

def run_discord_bot():
    while True:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            logging.error(f"Error occurred while running the bot: {str(e)}")
            logging.info("Retrying in 30 seconds...")
            asyncio.sleep(30)  # Wait before retrying

if __name__ == '__main__':
    # Start the Flask app in a separate thread
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()

    # Start the Discord bot in the main thread
    run_discord_bot()

