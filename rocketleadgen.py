import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import sqlite3
import os
from threading import Thread
import asyncio
from datetime import datetime
import pytz

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Database path
DB_PATH = 'leads.db'

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Time zone for scheduling
TIME_ZONE = 'America/New_York'

# Initialize Flask app
app = Flask(__name__)
# Restrict CORS to allow requests only from your Wix site
CORS(app, resources={r"/*": {"origins": "https://your-wix-site-domain.com"}})  # Replace with your actual Wix domain

# Create a Discord bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True  # Enable reactions intent to check reactions
bot = commands.Bot(command_prefix="!", intents=intents)

# Set up the database
def setup_database():
    logging.debug("Attempting to set up the database.")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_message_id INTEGER UNIQUE,
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

setup_database()

def save_or_update_lead(discord_message_id, name, phone, gender, age, zip_code, status):
    logging.debug(f"Saving or updating lead in DB: ID={discord_message_id}, Name={name}, Status={status}")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (discord_message_id, name, phone, gender, age, zip_code, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_message_id) DO UPDATE SET status=excluded.status
    ''', (discord_message_id, name, phone, gender, age, zip_code, status))
    conn.commit()
    conn.close()
    logging.info(f"Lead {name} saved or updated in database.")

async def scan_past_messages():
    logging.info("Scanning past messages in the Discord channel.")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    async for message in channel.history(limit=None):
        if message.embeds:  # Only process embedded messages with lead data
            embed = message.embeds[0]
            fields = {field.name.lower(): field.value for field in embed.fields}

            # Extract lead information based on field names
            name = fields.get("name", "N/A")
            phone = fields.get("phone number", "N/A")
            gender = fields.get("gender", "N/A")
            age = fields.get("age", "N/A")
            zip_code = fields.get("zip code", "N/A")

            # Determine lead status based on reactions
            status = "new"
            for reaction in message.reactions:
                if reaction.emoji == "🔥":
                    status = "sold/booked"
                elif reaction.emoji == "📵":
                    status = "do-not-call"
                elif reaction.emoji == "✅":
                    status = "called"

            # Save or update the lead in the database
            save_or_update_lead(message.id, name, phone, gender, age, zip_code, status)

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_statuses():
    logging.debug("Handling request to /agent-dashboard.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM leads')
    rows = cursor.fetchall()
    conn.close()
    lead_data = [{'id': row[0], 'name': row[2], 'phone': row[3], 'gender': row[4], 'age': row[5], 'zip_code': row[6], 'status': row[7]} for row in rows]
    
    if not lead_data:
        logging.warning("No data found in the database.")
    else:
        logging.debug(f"Lead data to return: {lead_data}")
    
    return jsonify(lead_data)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    await scan_past_messages()  # Scan past messages on startup

def run_flask_app():
    logging.debug("Starting Flask app.")
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
