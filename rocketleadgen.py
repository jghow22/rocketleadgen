import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import sqlite3
import os
from datetime import datetime, timedelta
import pandas as pd
from threading import Thread
import asyncio
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
CSV_FILE_PATH = 'leadslistseptwenty.csv'
DB_PATH = 'leads.db'
TIME_ZONE = 'America/New_York'
TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"  # Toggle for testing

# Initialize Flask app and set CORS
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["https://your-wix-site-domain.com", "https://quotephish.com"]}})

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variables
current_lead_index = 0
discord_agents = []

# Database setup
def setup_database():
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
    try:
        df = pd.read_csv(file_path)
        required_columns = ['FirstName', 'LastName', 'Phone', 'Gender', 'Age', 'Zip']
        if not all(column in df.columns for column in required_columns):
            logging.error(f"CSV file is missing required columns. Expected: {required_columns}")
            return None
        df['Name'] = df['FirstName'] + ' ' + df['LastName']
        df = df.rename(columns={'Zip': 'Zip Code'})[['Name', 'Phone', 'Gender', 'Age', 'Zip Code']]
        df['Source'] = 'CSV File'
        df['Details'] = 'This lead was sourced from our CSV database and represents historical data.'
        return df
    except Exception as e:
        logging.error(f"Error reading CSV file: {e}")
        return None

async def fetch_discord_agents():
    """Fetch the list of Discord agents from the channel's guild."""
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    guild = channel.guild
    global discord_agents
    discord_agents = [member.name for member in guild.members if not member.bot]
    logging.info(f"Fetched {len(discord_agents)} agents from Discord.")

async def send_lead(channel):
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
    embed.add_field(name="Source", value=lead["Source"], inline=False)
    embed.add_field(name="Details", value=lead["Details"], inline=False)
    message = await channel.send(embed=embed)
    save_or_update_lead(message.id, lead["Name"], lead["Phone"], lead["Gender"], lead["Age"], lead["Zip Code"], "new", "unknown", "warm")
    current_lead_index = (current_lead_index + 1) % len(leads)

@tasks.loop(minutes=10)
async def send_lead_from_csv():
    current_time = datetime.now(pytz.timezone(TIME_ZONE))
    in_business_hours = 8 <= current_time.hour < 18
    if in_business_hours or TEST_MODE:
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        await send_lead(channel)

async def scan_past_messages():
    """Scan past messages in the channel to populate the database."""
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    await fetch_discord_agents()
    async for message in channel.history(limit=None):
        if message.embeds:
            embed = message.embeds[0]
            fields = {field.name.lower(): field.value for field in embed.fields}
            name = fields.get("name", "N/A")
            phone = fields.get("phone", "N/A")
            gender = fields.get("gender", "N/A")
            age = fields.get("age", "N/A")
            zip_code = fields.get("zip code", "N/A")
            age = int(age) if age.isdigit() else None
            lead_type = "hot" if embed.title == "Hot Lead" else ("quote-phish" if embed.title == "Quote Phish Lead" else "warm")
            
            status = "not called"
            agent = "unknown"

            emoji_mappings = {
                "called": ["✅", "\u2705"],
                "did not answer": ["❌", "\u274C"],
                "set/sale": ["🔥", "\U0001F525"],
                "do not call": ["📵", "\U0001F4F5"]
            }

            if message.reactions:
                for reaction in message.reactions:
                    async for user in reaction.users():
                        if user != bot.user:
                            agent = user.name
                            for key, emoji_list in emoji_mappings.items():
                                if str(reaction.emoji) in emoji_list:
                                    status = key
                                    break

            save_or_update_lead(message.id, name, phone, gender, age, zip_code, status, agent, lead_type)

def save_or_update_lead(discord_message_id, name, phone, gender, age, zip_code, status, agent, lead_type="warm"):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (discord_message_id, name, phone, gender, age, zip_code, status, created_at, agent, lead_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_message_id) DO UPDATE SET status=excluded.status, agent=excluded.agent
    ''', (discord_message_id, name, phone, gender, age, zip_code, status, datetime.now(), agent, lead_type))
    if status == "set/sale":
        cursor.execute('''
            INSERT INTO agent_sales (agent, sales_count)
            VALUES (?, 1)
            ON CONFLICT(agent) DO UPDATE SET sales_count = sales_count + 1
        ''', (agent,))
    conn.commit()
    conn.close()

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_counts():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'called'")
    called_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'set/sale'")
    sold_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'")
    uncalled_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads WHERE lead_type = 'hot'")
    hot_leads_count = cursor.fetchone()[0]
    conn.close()
    return jsonify({
        "called_leads_count": called_leads_count,
        "sold_leads_count": sold_leads_count,
        "total_leads_count": total_leads_count,
        "uncalled_leads_count": uncalled_leads_count,
        "hot_leads_count": hot_leads_count
    })

@app.route('/agent-leaderboard', methods=['GET'])
def get_agent_leaderboard():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' GROUP BY agent")
    leads_called = cursor.fetchall()
    leaderboard = [{"agent": agent, "leads_called": leads_called} for agent, leads_called in leads_called]
    conn.close()
    return jsonify(leaderboard)

@bot.event
async def on_ready():
    send_lead_from_csv.start()
    await scan_past_messages()

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
