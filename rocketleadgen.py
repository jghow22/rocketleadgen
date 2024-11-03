import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS  # Import CORS for cross-origin support
import asyncio
import logging
import pandas as pd
from threading import Thread
import sqlite3
import time
import os
from datetime import datetime
import pytz

# Configure logging
logging.basicConfig(level=logging.DEBUG)  # Set to DEBUG for detailed logging

# Database path
DB_PATH = 'leads.db'

# Print the current working directory and verify database path
logging.debug(f"Current working directory: {os.getcwd()}")
if os.path.exists(DB_PATH):
    logging.debug(f"Database path verified: {os.path.abspath(DB_PATH)}")
else:
    logging.debug(f"Database path will be created or accessed at: {os.path.abspath(DB_PATH)}")

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Path to the local CSV file
CSV_FILE_PATH = 'leadslistseptwenty.csv'

# Time zone for scheduling
TIME_ZONE = 'America/New_York'

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Create an instance of a Discord bot with commands
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True  # Enable reactions intent
intents.messages = True  # Enable access to message history
bot = commands.Bot(command_prefix="!", intents=intents)

def setup_database():
    logging.debug("Attempting to set up the database.")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                gender TEXT,
                age TEXT,
                zip_code TEXT,
                status TEXT DEFAULT 'new'
            )
        ''')
        conn.commit()
        conn.close()
        logging.info("Database setup completed.")
    except Exception as e:
        logging.error(f"Error during database setup: {str(e)}")

    # Verify database existence
    if os.path.exists(DB_PATH):
        logging.info(f"Database verified at path: {os.path.abspath(DB_PATH)}")
    else:
        logging.error("Database file was not found after setup.")

setup_database()

def save_lead_to_db(name, phone, gender, age, zip_code):
    logging.debug(f"Saving lead to DB: {name}, {phone}, {gender}, {age}, {zip_code}")
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO leads (name, phone, gender, age, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, phone, gender, age, zip_code))
        conn.commit()
        conn.close()
        logging.info(f"Lead saved to database: {name}")
    except Exception as e:
        logging.error(f"Error saving lead to database: {str(e)}")

def update_lead_status_in_db(lead_id, status):
    logging.debug(f"Updating lead status in DB. Lead ID: {lead_id}, New Status: {status}")
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE leads
            SET status = ?
            WHERE id = ?
        ''', (status, lead_id))
        conn.commit()
        conn.close()
        logging.info(f"Lead ID {lead_id} status updated to: {status}")
    except Exception as e:
        logging.error(f"Error updating lead status in database: {str(e)}")

def fetch_all_lead_statuses_from_db():
    logging.debug("Fetching all lead statuses from DB.")
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM leads')
        rows = cursor.fetchall()
        conn.close()
        logging.debug(f"Fetched {len(rows)} rows from DB.")
        return [{'id': row[0], 'name': row[1], 'phone': row[2], 'gender': row[3], 'age': row[4], 'zip_code': row[5], 'status': row[6]} for row in rows]
    except Exception as e:
        logging.error(f"Error fetching data from database: {str(e)}")
        return []

async def send_lead(channel):
    logging.debug("Reading leads from CSV.")
    leads = read_leads_from_csv(CSV_FILE_PATH)
    if leads is None or leads.empty:
        logging.warning("No leads found in the CSV file.")
        return

    lead = leads.iloc[0]  # Change logic as needed for real usage
    logging.debug(f"Preparing to send lead: {lead}")

    embed = discord.Embed(title="New Lead", color=0x00ff00)
    embed.add_field(name="Name", value=lead.get("Name", "N/A"), inline=True)
    embed.add_field(name="Phone", value=lead.get("Phone", "N/A"), inline=True)
    embed.add_field(name="Gender", value=lead.get("Gender", "N/A"), inline=True)
    embed.add_field(name="Age", value=lead.get("Age", "N/A"), inline=True)
    embed.add_field(name="Zip Code", value=lead.get("Zip Code", "N/A"), inline=True)
    embed.set_footer(text="Happy selling!")

    if channel:
        await channel.send(embed=embed)
        logging.info(f"Sent lead to Discord: {lead.get('Name', 'N/A')}")
    else:
        logging.error("Channel not found.")

async def scan_past_messages_for_reactions():
    logging.debug("Starting scan for past messages with reactions.")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        logging.error("Channel not found or bot lacks access.")
        return

    try:
        async for message in channel.history(limit=None):
            for reaction in message.reactions:
                async for user in reaction.users():
                    if user != bot.user:  # Ignore the bot's own reactions
                        logging.debug(f"Processing reaction: {reaction.emoji} by {user}")
                        if str(reaction.emoji) == "🔥":
                            update_lead_status_in_db(message.id, "sold/booked")
                        elif str(reaction.emoji) == "📵":
                            update_lead_status_in_db(message.id, "do-not-call")
                        elif str(reaction.emoji) == "✅":
                            update_lead_status_in_db(message.id, "called")
    except Exception as e:
        logging.error(f"Error scanning messages for reactions: {str(e)}")

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    await scan_past_messages_for_reactions()  # Scan past messages on startup
    send_lead_from_csv.start()

@tasks.loop(minutes=10)
async def send_lead_from_csv():
    logging.debug("Checking if current time is within sending hours.")
    current_time = datetime.now(pytz.timezone(TIME_ZONE))
    current_hour = current_time.hour
    if 8 <= current_hour < 18:
        logging.info("Sending lead during business hours.")
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        await send_lead(channel)
    else:
        logging.info("Outside of business hours, not sending leads.")

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_statuses():
    logging.debug("Handling request to /agent-dashboard.")
    try:
        lead_data = fetch_all_lead_statuses_from_db()
        logging.debug(f"Lead data returned: {lead_data}")
        return jsonify(lead_data)
    except Exception as e:
        logging.error(f"Error handling /agent-dashboard request: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    logging.debug("Received webhook from Wix.")
    try:
        data = request.json
        logging.debug(f"Data received: {data}")

        submissions = data.get('data', {}).get('submissions', [])
        submission_data = {item['label'].lower(): item['value'] for item in submissions}

        name = submission_data.get('name', data.get('data', {}).get('field:first_name_379d', 'N/A'))
        phone = submission_data.get('phone', data.get('data', {}).get('field:phone_23b2', 'N/A'))
        gender = submission_data.get('gender', data.get('data', {}).get('field:gender', 'N/A'))
        age = data.get('data', {}).get('field:age', 'N/A')
        zip_code = data.get('data', {}).get('field:zip_code', 'N/A')

        save_lead_to_db(name, phone, gender, age, zip_code)

        embed = discord.Embed(title="Hot Lead", color=0xff0000)
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Phone Number", value=phone, inline=True)
        embed.add_field(name="Gender", value=gender, inline=True)
        embed.add_field(name="Age", value=age, inline=True)
        embed.add_field(name="Zip Code", value=zip_code, inline=True)
        embed.set_footer(text="Happy selling!")

        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        if channel:
            asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
            logging.info(f"Sent hot lead to Discord: {name}")
        else:
            logging.error("Discord channel not found.")

        return jsonify({"status": "success", "message": "Lead sent to Discord"}), 200
    except Exception as e:
        logging.error(f"Error processing Wix webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask_app():
    logging.debug("Starting Flask app.")
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    logging.debug("Starting Discord bot.")
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
