import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
import asyncio
import logging
import pandas as pd
from threading import Thread
import time
import os
from datetime import datetime
import pytz  # Importing pytz for time zone handling

# Configure logging
logging.basicConfig(level=logging.INFO)

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')  # Discord bot token
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))  # Discord channel ID

# Path to the local CSV file
CSV_FILE_PATH = 'leadslistseptwenty.csv'

# Time zone for the scheduling (e.g., Eastern Time)
TIME_ZONE = 'America/New_York'

# Initialize Flask app
app = Flask(__name__)

# Create an instance of a Discord bot with commands
intents = discord.Intents.default()
intents.message_content = True  # Enable the message content intent
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variable to keep track of the current lead index
current_lead_index = 0

def read_leads_from_csv(file_path):
    """
    Reads the leads from the given CSV file and filters the necessary columns,
    combining 'FirstName' and 'LastName' into 'Name', and using 'Zip' for 'Zip Code'.
    """
    try:
        # Load the CSV file into a DataFrame
        df = pd.read_csv(file_path)

        # Print the columns of the CSV for debugging purposes
        logging.info(f"Columns in the CSV file: {df.columns.tolist()}")

        # Required columns
        required_columns = ['FirstName', 'LastName', 'Phone', 'Gender', 'Age', 'Zip']

        # Check if all required columns are in the DataFrame
        if not all(column in df.columns for column in required_columns):
            logging.error(f"Missing required columns in the CSV file. Expected columns: {required_columns}")
            return None

        # Combine 'FirstName' and 'LastName' into a single 'Name' column
        df['Name'] = df['FirstName'] + ' ' + df['LastName']

        # Rename 'Zip' to 'Zip Code' for consistency
        df = df.rename(columns={'Zip': 'Zip Code'})

        # Filter the DataFrame to only keep the relevant columns
        df = df[['Name', 'Phone', 'Gender', 'Age', 'Zip Code']]

        logging.info(f"Successfully read {len(df)} leads from the CSV file.")
        return df
    except Exception as e:
        logging.error(f"Error reading leads from CSV file: {str(e)}")
        return None

async def send_lead(channel):
    """
    Sends a lead from the CSV file to the specified Discord channel.
    """
    global current_lead_index
    leads = read_leads_from_csv(CSV_FILE_PATH)

    if leads is None or leads.empty:
        logging.warning("No leads found in the CSV file.")
        return

    # Get the current lead
    lead = leads.iloc[current_lead_index]

    # Extract the fields, handling missing values gracefully
    name = lead.get("Name", "N/A")
    phone_number = lead.get("Phone", "N/A")
    gender = lead.get("Gender", "N/A")
    age = lead.get("Age", "N/A")
    zip_code = lead.get("Zip Code", "N/A")

    # Construct the embed for Discord
    embed = discord.Embed(title="Warm Lead", color=0x0000ff)
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
        current_lead_index = (current_lead_index + 1) % len(leads)
    else:
        logging.error(f"Could not find channel with ID: {DISCORD_CHANNEL_ID}")

@tasks.loop(minutes=10)  # Loop interval set to 10 minutes
async def send_lead_from_csv():
    """
    Sends a lead from the CSV file if the current time is between 8 AM and 6 PM.
    """
    # Get the current time in the specified time zone
    current_time = datetime.now(pytz.timezone(TIME_ZONE))
    current_hour = current_time.hour

    # Only send leads between 8 AM and 6 PM
    if 8 <= current_hour < 18:
        logging.info("Attempting to send a warm lead from the CSV...")
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        await send_lead(channel)
    else:
        logging.info("Current time is outside of sending hours (8 AM - 6 PM). Skipping this cycle.")

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    """
    Handles incoming webhook requests from Wix.
    """
    try:
        # Get the JSON data sent from Wix
        data = request.json
        logging.info(f"Received data from Wix: {data}")

        # Extract relevant fields from the submissions list
        submissions = data.get('data', {}).get('submissions', [])
        submission_data = {item['label'].lower(): item['value'] for item in submissions}

        # Extract fields from the parsed submission data and fallback values from the main data dictionary
        name = submission_data.get('name', data.get('data', {}).get('field:first_name_379d', 'N/A'))
        phone = submission_data.get('phone', data.get('data', {}).get('field:phone_23b2', 'N/A'))
        gender = submission_data.get('gender', data.get('data', {}).get('field:gender', 'N/A'))
        age = data.get('data', {}).get('field:age', 'N/A')  # Assuming 'Age' is directly in data
        zip_code = data.get('data', {}).get('field:zip_code', 'N/A')  # Assuming 'Zip Code' is directly in data

        # Prepare the message content
        embed = discord.Embed(title="Hot Lead", color=0xff0000)  # Hot lead color
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Phone Number", value=phone, inline=True)
        embed.add_field(name="Gender", value=gender, inline=True)
        embed.add_field(name="Age", value=age, inline=True)
        embed.add_field(name="Zip Code", value=zip_code, inline=True)
        embed.set_footer(text="Happy selling!")

        # Send the message to the Discord channel
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
            logging.info(f"Sent hot lead to Discord: {name}")
        else:
            logging.error(f"Could not find channel with ID: {DISCORD_CHANNEL_ID}")

        # Return a success response
        return jsonify({"status": "success", "message": "Lead sent to Discord"}), 200

    except Exception as e:
        logging.error(f"Error processing the Wix webhook: {str(e)}")
        # Return an error response
        return jsonify({"status": "error", "message": str(e)}), 500

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    logging.info('------')
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if channel:
        bot.loop.create_task(send_lead(channel))
    # Start the task for sending leads from the CSV file every 10 minutes
    send_lead_from_csv.start()

@bot.event
async def on_disconnect():
    logging.warning('Bot disconnected! Attempting to reconnect...')

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    while True:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            logging.error(f"Error occurred while running the bot: {str(e)}")
            logging.info("Retrying in 30 seconds...")
            time.sleep(30)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
