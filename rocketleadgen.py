import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import sqlite3
import os
from threading import Thread
import asyncio

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Database path
DB_PATH = 'leads.db'

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://your-wix-site-domain.com"}})  # Replace with your actual Wix domain

# Create a Discord bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Zip code to state mapping (example codes; expand as needed)
ZIP_CODE_TO_STATE = {
    '30301': 'GA', '90001': 'CA', '10001': 'NY',
    '33101': 'FL', '60601': 'IL', '75201': 'TX'
}

def setup_database():
    logging.debug("Setting up the database.")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_message_id INTEGER UNIQUE,
            name TEXT,
            phone TEXT,
            gender TEXT,
            age INTEGER,
            zip_code TEXT,
            state TEXT,
            status TEXT DEFAULT 'new'
        )
    ''')
    conn.commit()
    
    cursor.execute("PRAGMA table_info(leads)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'state' not in columns:
        cursor.execute('ALTER TABLE leads ADD COLUMN state TEXT')
        logging.info("Added 'state' column to 'leads' table.")
    
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

setup_database()

def zip_to_state(zip_code):
    """Map zip code to state if possible and log the result."""
    state = ZIP_CODE_TO_STATE.get(zip_code[:5], "Unknown")
    logging.debug(f"Mapping zip code {zip_code} to state: {state}")
    return state

def debug_print_database():
    """Print all entries in the leads database for debugging."""
    logging.debug("Printing all entries in the leads database.")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads")
    rows = cursor.fetchall()
    for row in rows:
        logging.debug(f"Lead entry: {row}")
    if not rows:
        logging.warning("No entries found in the leads database.")
    conn.close()

def save_or_update_lead(discord_message_id, name, phone, gender, age, zip_code, status):
    # Log zip code and state mapping
    logging.debug(f"Saving lead - ID: {discord_message_id}, Name: {name}, Zip: {zip_code}")
    state = zip_to_state(zip_code) if zip_code else "Unknown"
    logging.debug(f"Derived state for zip code {zip_code}: {state}")
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (discord_message_id, name, phone, gender, age, zip_code, state, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_message_id) DO UPDATE SET status=excluded.status
    ''', (discord_message_id, name, phone, gender, age, zip_code, state, status))
    conn.commit()
    conn.close()
    logging.info(f"Lead {name} saved/updated in database with state: {state}")

async def scan_past_messages():
    logging.info("Scanning past messages in the Discord channel.")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    async for message in channel.history(limit=None):
        if message.embeds:
            embed = message.embeds[0]
            fields = {field.name.lower(): field.value for field in embed.fields}
            
            name = fields.get("name", "N/A")
            phone = fields.get("phone number", "N/A")
            gender = fields.get("gender", "N/A")
            age = fields.get("age", "N/A")
            zip_code = fields.get("zip code", "N/A")
            
            logging.debug(f"Extracted zip code: {zip_code} for lead {name}")
            
            age = int(age) if age.isdigit() else None
            
            status = "new"
            for reaction in message.reactions:
                if reaction.emoji == "🔥":
                    status = "sold/booked"
                elif reaction.emoji == "📵":
                    status = "do-not-call"
                elif reaction.emoji == "✅":
                    status = "called"
            
            save_or_update_lead(message.id, name, phone, gender, age, zip_code, status)

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_counts():
    logging.debug("Handling request to /agent-dashboard for lead counts.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE status = "called"')
    called_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE status = "sold/booked"')
    sold_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads')
    total_count = cursor.fetchone()[0]
    
    closed_percentage = (sold_count / total_count) * 100 if total_count > 0 else 0
    
    cursor.execute('SELECT AVG(age) FROM leads WHERE age IS NOT NULL')
    average_age = cursor.fetchone()[0]
    average_age = round(average_age, 2) if average_age is not None else 0
    
    cursor.execute('SELECT state, COUNT(*) as count FROM leads WHERE state IS NOT NULL GROUP BY state ORDER BY count DESC LIMIT 1')
    most_popular_state = cursor.fetchone()
    popular_state = most_popular_state[0] if most_popular_state else "N/A"
    
    conn.close()
    
    logging.debug(f"Metrics - Called: {called_count}, Sold: {sold_count}, Total: {total_count}, Closed %: {closed_percentage}, Avg Age: {average_age}, Popular State: {popular_state}")
    return jsonify({
        "called_leads_count": called_count,
        "sold_leads_count": sold_count,
        "total_leads_count": total_count,
        "closed_percentage": round(closed_percentage, 2),
        "average_age": average_age,
        "popular_state": popular_state
    })

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    await scan_past_messages()
    debug_print_database()  # Print database entries for debugging on startup

def run_flask_app():
    logging.debug("Starting Flask app.")
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
