import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
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
logging.basicConfig(level=logging.INFO)

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Path to the local CSV file
CSV_FILE_PATH = 'leadslistseptwenty.csv'

# Time zone for scheduling
TIME_ZONE = 'America/New_York'

# Initialize Flask app
app = Flask(__name__)

# Create an instance of a Discord bot with commands
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True  # Enable reactions intent
bot = commands.Bot(command_prefix="!", intents=intents)

# Database setup
DB_PATH = 'leads.db'

def setup_database():
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

setup_database()

def save_lead_to_db(name, phone, gender, age, zip_code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (name, phone, gender, age, zip_code)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, phone, gender, age, zip_code))
    conn.commit()
    conn.close()

def update_lead_status_in_db(lead_id, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE leads
        SET status = ?
        WHERE id = ?
    ''', (status, lead_id))
    conn.commit()
    conn.close()

def fetch_all_lead_statuses_from_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM leads')
    rows = cursor.fetchall()
    conn.close()
    return [{'id': row[0], 'name': row[1], 'phone': row[2], 'gender': row[3], 'age': row[4], 'zip_code': row[5], 'status': row[6]} for row in rows]

async def send_lead(channel):
    leads = read_leads_from_csv(CSV_FILE_PATH)

    if leads is None or leads.empty:
        logging.warning("No leads found in the CSV file.")
        return

    global current_lead_index
    lead = leads.iloc[current_lead_index]
    name = lead.get("Name", "N/A")
    phone = lead.get("Phone", "N/A")
    gender = lead.get("Gender", "N/A")
    age = lead.get("Age", "N/A")
    zip_code = lead.get("Zip Code", "N/A")

    save_lead_to_db(name, phone, gender, age, zip_code)

    embed = discord.Embed(title="Warm Lead", color=0x0000ff)
    embed.add_field(name="Name", value=name, inline=True)
    embed.add_field(name="Phone Number", value=phone, inline=True)
    embed.add_field(name="Gender", value=gender, inline=True)
    embed.add_field(name="Age", value=age, inline=True)
    embed.add_field(name="Zip Code", value=zip_code, inline=True)
    embed.set_footer(text="Happy selling!")

    if channel:
        await channel.send(embed=embed)
        logging.info(f"Sent warm lead to Discord: {name}")
        current_lead_index = (current_lead_index + 1) % len(leads)

@bot.event
async def on_reaction_add(reaction, user):
    if user == bot.user:
        return

    status_map = {
        "🔥": "sold/booked",
        "📵": "do-not-call",
        "✅": "called"
    }

    if str(reaction.emoji) in status_map:
        lead_id = extract_lead_id_from_message(reaction.message)  # Implement extraction logic
        new_status = status_map[str(reaction.emoji)]
        update_lead_status_in_db(lead_id, new_status)
        logging.info(f"Updated lead {lead_id} to status: {new_status}")

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_statuses():
    lead_data = fetch_all_lead_statuses_from_db()
    return jsonify(lead_data)

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    try:
        data = request.json
        logging.info(f"Received data from Wix: {data}")

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

        return jsonify({"status": "success", "message": "Lead sent to Discord"}), 200
    except Exception as e:
        logging.error(f"Error processing the Wix webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    send_lead_from_csv.start()

@tasks.loop(minutes=10)
async def send_lead_from_csv():
    current_time = datetime.now(pytz.timezone(TIME_ZONE))
    current_hour = current_time.hour

    if 8 <= current_hour < 18:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        await send_lead(channel)

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    while True:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            logging.error(f"Error occurred while running the bot: {str(e)}")
            time.sleep(30)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
