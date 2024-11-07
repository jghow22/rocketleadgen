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
            age INTEGER,
            zip_code TEXT,
            state TEXT,
            status TEXT DEFAULT 'new'
        )
    ''')
    conn.commit()
    
    # Add the 'state' column if it doesn't already exist
    cursor.execute("PRAGMA table_info(leads)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'state' not in columns:
        cursor.execute('ALTER TABLE leads ADD COLUMN state TEXT')
        logging.info("Added 'state' column to 'leads' table.")
    
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

setup_database()

def save_or_update_lead(discord_message_id, name, phone, gender, age, zip_code, state, status):
    logging.debug(f"Saving or updating lead in DB: ID={discord_message_id}, Name={name}, Status={status}")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (discord_message_id, name, phone, gender, age, zip_code, state, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_message_id) DO UPDATE SET status=excluded.status
    ''', (discord_message_id, name, phone, gender, age, zip_code, state, status))
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
            state = fields.get("state", "N/A")  # Assuming 'state' field is in embed

            # Ensure age is an integer if possible
            age = int(age) if age.isdigit() else None

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
            save_or_update_lead(message.id, name, phone, gender, age, zip_code, state, status)

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_counts():
    logging.debug("Handling request to /agent-dashboard for lead counts.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Count for leads with status "called"
    cursor.execute('SELECT COUNT(*) FROM leads WHERE status = "called"')
    called_count = cursor.fetchone()[0]
    
    # Count for leads with status "sold/booked"
    cursor.execute('SELECT COUNT(*) FROM leads WHERE status = "sold/booked"')
    sold_count = cursor.fetchone()[0]
    
    # Count for total leads
    cursor.execute('SELECT COUNT(*) FROM leads')
    total_count = cursor.fetchone()[0]
    
    # Calculate the percentage of leads closed
    if total_count > 0:
        closed_percentage = (sold_count / total_count) * 100
    else:
        closed_percentage = 0
    
    # Calculate the average age of leads
    cursor.execute('SELECT AVG(age) FROM leads WHERE age IS NOT NULL')
    average_age = cursor.fetchone()[0]
    average_age = round(average_age, 2) if average_age is not None else 0
    
    # Find the most popular state
    cursor.execute('SELECT state, COUNT(*) as count FROM leads WHERE state IS NOT NULL GROUP BY state ORDER BY count DESC LIMIT 1')
    most_popular_state = cursor.fetchone()
    popular_state = most_popular_state[0] if most_popular_state else "N/A"
    
    conn.close()
    
    logging.debug(f"Called leads: {called_count}, Sold leads: {sold_count}, Total leads: {total_count}, Closed percentage: {closed_percentage:.2f}%, Average age: {average_age}, Most popular state: {popular_state}")
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
