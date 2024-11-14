import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import logging
import pandas as pd
import sqlite3
import os
from threading import Thread
from datetime import datetime, timedelta
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO)

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
CSV_FILE_PATH = 'leadslistseptwenty.csv'
DB_PATH = 'leads.db'
TIME_ZONE = 'America/New_York'

# Initialize Flask app and set CORS
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://your-wix-site-domain.com"}})

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variables
current_lead_index = 0
discord_agents = []

def setup_database():
    """Sets up the database tables."""
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
            status TEXT DEFAULT 'new',
            lead_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            agent TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agent_sales (
            agent TEXT PRIMARY KEY,
            sales_count INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

setup_database()

def read_leads_from_csv(file_path):
    """Reads leads from a CSV file and returns a DataFrame."""
    try:
        df = pd.read_csv(file_path)
        required_columns = ['FirstName', 'LastName', 'Phone', 'Gender', 'Age', 'Zip']
        if not all(column in df.columns for column in required_columns):
            logging.error("Missing required columns in CSV.")
            return None
        df['Name'] = df['FirstName'] + ' ' + df['LastName']
        df = df.rename(columns={'Zip': 'Zip Code'})[['Name', 'Phone', 'Gender', 'Age', 'Zip Code']]
        return df
    except Exception as e:
        logging.error(f"Error reading CSV: {e}")
        return None

async def send_lead(channel):
    """Sends a lead from CSV to the Discord channel."""
    global current_lead_index
    leads = read_leads_from_csv(CSV_FILE_PATH)
    if leads is None or leads.empty:
        logging.warning("No leads found in CSV.")
        return

    lead = leads.iloc[current_lead_index]
    embed = discord.Embed(title="Warm Lead", color=0x0000ff)
    embed.add_field(name="Name", value=lead["Name"], inline=True)
    embed.add_field(name="Phone", value=lead["Phone"], inline=True)
    embed.add_field(name="Gender", value=lead["Gender"], inline=True)
    embed.add_field(name="Age", value=lead["Age"], inline=True)
    embed.add_field(name="Zip Code", value=lead["Zip Code"], inline=True)
    await channel.send(embed=embed)
    current_lead_index = (current_lead_index + 1) % len(leads)

@tasks.loop(minutes=10)
async def send_lead_from_csv():
    """Scheduled task to send a lead every 10 minutes between 8 AM and 6 PM."""
    current_time = datetime.now(pytz.timezone(TIME_ZONE))
    if 8 <= current_time.hour < 18:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        await send_lead(channel)

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    """Handles Wix webhook for incoming hot leads."""
    try:
        data = request.json
        name = data.get('data', {}).get('field:first_name_379d', 'N/A')
        phone = data.get('data', {}).get('field:phone_23b2', 'N/A')
        # other fields...
        embed = discord.Embed(title="Hot Lead", color=0xff0000)
        # add fields to embed...
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_counts():
    """Returns metrics for the agent dashboard."""
    conn = sqlite3.connect(DB_PATH)
    # run SQL queries for metrics
    # return JSON data for dashboard

@app.route('/agent-leaderboard', methods=['GET'])
def get_agent_leaderboard():
    """Returns the leaderboard data."""
    conn = sqlite3.connect(DB_PATH)
    # fetch and return leaderboard data as JSON

@app.route('/weekly-leaderboard', methods=['GET'])
def get_weekly_leaderboard():
    """Returns the weekly leaderboard data."""
    conn = sqlite3.connect(DB_PATH)
    # fetch weekly data and return as JSON

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    send_lead_from_csv.start()
    # Perform initial data scan if needed

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
