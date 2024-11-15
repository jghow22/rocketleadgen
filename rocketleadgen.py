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
import time

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
            logging.error("Missing required columns in CSV.")
            return None
        df['Name'] = df['FirstName'] + ' ' + df['LastName']
        df = df.rename(columns={'Zip': 'Zip Code'})[['Name', 'Phone', 'Gender', 'Age', 'Zip Code']]
        logging.info(f"Read {len(df)} leads from CSV.")
        return df
    except Exception as e:
        logging.error(f"Error reading CSV: {e}")
        return None

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
    await channel.send(embed=embed)
    current_lead_index = (current_lead_index + 1) % len(leads)
    logging.info(f"Sent warm lead {lead['Name']} from CSV to Discord.")

@tasks.loop(minutes=10)
async def send_lead_from_csv():
    # Check if we are in business hours or test mode
    current_time = datetime.now(pytz.timezone(TIME_ZONE))
    in_business_hours = 8 <= current_time.hour < 18
    if in_business_hours or TEST_MODE:
        logging.info("Attempting to send a warm lead from CSV.")
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        await send_lead(channel)
    else:
        logging.info("Outside business hours and not in test mode; skipping lead send.")

async def fetch_discord_agents():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    guild = channel.guild
    global discord_agents
    discord_agents = [member.name for member in guild.members if not member.bot]
    logging.info(f"Fetched {len(discord_agents)} agents from Discord.")

async def scan_past_messages():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    await fetch_discord_agents()
    async for message in channel.history(limit=None):
        if message.embeds:
            embed = message.embeds[0]
            fields = {field.name.lower(): field.value for field in embed.fields}
            name = fields.get("name", "N/A")
            phone = fields.get("phone number", "N/A")
            gender = fields.get("gender", "N/A")
            age = fields.get("age", "N/A")
            zip_code = fields.get("zip code", "N/A")
            age = int(age) if age.isdigit() else None
            lead_type = "hot" if embed.title == "Hot Lead" else "warm"
            status = "new"
            agent = "unknown"
            for reaction in message.reactions:
                async for user in reaction.users():
                    if user != bot.user:
                        agent = user.name
                        if str(reaction.emoji) == "🔥":
                            status = "sold/booked"
                        elif str(reaction.emoji) == "📵":
                            status = "do-not-call"
                        elif str(reaction.emoji) == "✅":
                            status = "called"
            save_or_update_lead(message.id, name, phone, gender, age, zip_code, status, agent, lead_type)
    logging.info("Completed scanning past messages for lead data.")

def save_or_update_lead(discord_message_id, name, phone, gender, age, zip_code, status, agent, lead_type="warm"):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (discord_message_id, name, phone, gender, age, zip_code, status, created_at, agent, lead_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_message_id) DO UPDATE SET status=excluded.status, agent=excluded.agent
    ''', (discord_message_id, name, phone, gender, age, zip_code, status, datetime.now(), agent, lead_type))
    if status == "sold/booked":
        cursor.execute('''
            INSERT INTO agent_sales (agent, sales_count)
            VALUES (?, 1)
            ON CONFLICT(agent) DO UPDATE SET sales_count = sales_count + 1
        ''', (agent,))
    conn.commit()
    conn.close()
    logging.info(f"Saved or updated lead {name} in database with status '{status}'.")

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    try:
        data = request.json
        submissions = data.get('data', {}).get('submissions', [])
        submission_data = {item['label'].lower(): item['value'] for item in submissions}
        name = submission_data.get('name', data.get('data', {}).get('field:first_name_379d', 'N/A'))
        phone = submission_data.get('phone', data.get('data', {}).get('field:phone_23b2', 'N/A'))
        gender = submission_data.get('gender', data.get('data', {}).get('field:gender', 'N/A'))
        age = data.get('data', {}).get('field:age', 'N/A')
        zip_code = data.get('data', {}).get('field:zip_code', 'N/A')
        embed = discord.Embed(title="Hot Lead", color=0xff0000)
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Phone Number", value=phone, inline=True)
        embed.add_field(name="Gender", value=gender, inline=True)
        embed.add_field(name="Age", value=age, inline=True)
        embed.add_field(name="Zip Code", value=zip_code, inline=True)
        channel = bot.get_channel(DISCORD_CHANNEL_ID)
        asyncio.run_coroutine_threadsafe(channel.send(embed=embed), bot.loop)
        return jsonify({"status": "success", "message": "Lead sent to Discord"}), 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_counts():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # Called leads count
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'called'")
    called_leads_count = cursor.fetchone()[0]
    
    # Sold leads count
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'sold/booked'")
    sold_leads_count = cursor.fetchone()[0]
    
    # Total leads count
    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads_count = cursor.fetchone()[0]
    
    # Uncalled leads count
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'")
    uncalled_leads_count = cursor.fetchone()[0]
    
    # Hot leads count
    cursor.execute("SELECT COUNT(*) FROM leads WHERE lead_type = 'hot'")
    hot_leads_count = cursor.fetchone()[0]
    
    # Closed percentage
    closed_percentage = (sold_leads_count / total_leads_count * 100) if total_leads_count > 0 else 0
    
    # Average age
    cursor.execute("SELECT AVG(age) FROM leads WHERE age IS NOT NULL")
    average_age = cursor.fetchone()[0] or 0
    
    # Most popular zip code
    cursor.execute("SELECT zip_code, COUNT(*) AS zip_count FROM leads GROUP BY zip_code ORDER BY zip_count DESC LIMIT 1")
    popular_zip = cursor.fetchone()
    popular_zip = popular_zip[0] if popular_zip else "N/A"
    
    # Most popular gender
    cursor.execute("SELECT gender, COUNT(*) AS gender_count FROM leads GROUP BY gender ORDER BY gender_count DESC LIMIT 1")
    popular_gender = cursor.fetchone()
    popular_gender = popular_gender[0] if popular_gender else "N/A"

    conn.close()
    
    return jsonify({
        "called_leads_count": called_leads_count,
        "sold_leads_count": sold_leads_count,
        "total_leads_count": total_leads_count,
        "uncalled_leads_count": uncalled_leads_count,
        "closed_percentage": round(closed_percentage, 2),
        "average_age": round(average_age, 1),
        "popular_zip": popular_zip,
        "popular_gender": popular_gender,
        "hot_leads_count": hot_leads_count
    })

@app.route('/agent-leaderboard', methods=['GET'])
def get_agent_leaderboard():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    leaderboard = {agent: {"sales_count": 0, "leads_called": 0} for agent in discord_agents}
    cursor.execute("SELECT agent, sales_count FROM agent_sales")
    sales_counts = cursor.fetchall()
    for agent, count in sales_counts:
        leaderboard[agent]["sales_count"] = count
    cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' GROUP BY agent")
    leads_called_counts = cursor.fetchall()
    for agent, count in leads_called_counts:
        if agent in leaderboard:
            leaderboard[agent]["leads_called"] = count
    sorted_leaderboard = [{"agent": agent, **data} for agent, data in sorted(leaderboard.items(), key=lambda x: x[1]["sales_count"], reverse=True)]
    conn.close()
    return jsonify(sorted_leaderboard)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
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
