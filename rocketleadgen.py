import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
import asyncio
import logging
import pandas as pd
import requests
from io import StringIO
from threading import Thread
import time

# Configure logging
logging.basicConfig(level=logging.INFO)

# Your Discord bot token (replace with your bot token)
DISCORD_TOKEN = 'MTI3OTkyOTE1OTEzNjU3NTUxOA.GgNms2.CFQewGJ7-7smOxcS6tmPwtOLCtZERzAMvJn9yo'  # Replace with your actual token

# Discord channel ID where the bot will send messages
DISCORD_CHANNEL_ID = 1281081570253475923  # Replace with the actual channel ID

# URL of the CSV file in your GitHub repository
CSV_FILE_URL = 'https://github.com/jghow22/rocketleadgen/blob/main/leadslistseptwenty.csv'  # Update this with the correct URL

# Initialize Flask app
app = Flask(__name__)

# Create an instance of a Discord bot with commands
intents = discord.Intents.default()
intents.message_content = True  # Enable the message content intent
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variable to keep track of the current lead index
current_lead_index = 0

def download_csv_from_github(url):
    """
    Downloads the CSV file from the given GitHub URL and returns it as a DataFrame.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()  # Check for HTTP errors

        # Read the content of the downloaded CSV file into a DataFrame
        df = pd.read_csv(StringIO(response.text))
        logging.info(f"Successfully downloaded {len(df)} leads from the CSV file on GitHub.")
        return df
    except Exception as e:
        logging.error(f"Error downloading CSV file from GitHub: {str(e)}")
        return None

async def send_lead(channel):
    """
    Sends a lead from the CSV file to the specified Discord channel.
    """
    global current_lead_index
    leads = download_csv_from_github(CSV_FILE_URL)

    if leads is None or leads.empty:
        logging.warning("No leads found in the CSV file.")
        return

    # Get the current lead
    lead = leads.iloc[current_lead_index]

    # Prepare the message content
    name = lead.get("Name", "N/A")
    phone_number = lead.get("Phone", "N/A")
    gender = lead.get("Gender", "N/A")
    age = lead.get("Age", "N/A")
    zip_code = lead.get("Zip Code", "N/A")

    # Construct the embed for Discord
    embed = discord.Embed(title="Warm Lead", color=0x0000ff)  # Warm lead color
    embed.add_field(name="Name", value=name, inline=True)
    embed.add_field(name="Phone Number", value=phone_number, inline=True)
    embed.add_field(name="Gender", value=gender, inline=True)
    embed.add_field(name="Age", value=age, inline=True)
    embed.add_field(name="Zip Code", value=zip_code, inline=True)
    embed.set_footer(text="Happy selling!")

    # Send the embed to Discord
    if channel:
        await channel.send(embed=embed)
        logging.info(f"Sent warm lead to Discord: {name}")

        # Update the current lead index for the next run
        current_lead_index = (current_lead_index + 1) % len(leads)
    else:
        logging.error(f"Could not find channel with ID: {DISCORD_CHANNEL_ID}")

@tasks.loop(minutes=30)
async def send_lead_from_csv():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    await send_lead(channel)

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
        zip_code = None

        # Extract specific fields based on the labels in the `submissions` list
        for submission in submissions:
            if submission['label'] == 'Name':
                name = submission['value']
            elif submission['label'] == 'Phone':
                phone_number = submission['value']
            elif submission['label'] == 'Gender':
                gender = submission['value']
            elif submission['label'] == 'Age':
                age = submission['value']
            elif submission['label'] == 'Nicotine use':
                nicotine_use = submission['value']
            elif submission['label'] == 'Zip Code':
                zip_code = submission['value']

        # Ensure required fields are present
        if not name or not phone_number:
            logging.error("Missing essential data fields in the received webhook payload.")
            return jsonify({"status": "error", "message": "Missing essential data fields"}), 400

        # Construct the embed for Discord
        embed = discord.Embed(title="Hot Lead", color=0xff0000)  # Hot lead color
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Phone Number", value=phone_number, inline=True)
        embed.add_field(name="Gender", value=gender, inline=True)
        embed.add_field(name="Age", value=age, inline=True)
        embed.add_field(name="Nicotine Use", value=nicotine_use, inline=True)  # Include Nicotine Use for hot leads
        embed.add_field(name="Zip Code", value=zip_code, inline=True)
        embed.set_footer(text="Lead generated via Wix form | Happy selling!")

        # Send the embed to Discord
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
            logging.info("Embed successfully sent to Discord")
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

    # Send a lead from the CSV immediately when the bot starts
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel:
        bot.loop.create_task(send_lead(channel))

    # Start the task for sending leads from the CSV file every 30 minutes
    send_lead_from_csv.start()

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
            time.sleep(30)  # Wait before retrying

if __name__ == '__main__':
    # Start the Flask app in a separate thread
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()

    # Start the Discord bot in the main thread
    run_discord_bot()
