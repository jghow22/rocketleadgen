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
        logging.info(f"CSV Columns: {df.columns.tolist()}")  # Log the CSV columns for debugging
        required_columns = ['FirstName', 'LastName', 'Phone', 'Gender', 'Age', 'Zip']
        if not all(column in df.columns for column in required_columns):
            logging.error(f"CSV file is missing required columns. Expected: {required_columns}")
            return None
        df['Name'] = df['FirstName'] + ' ' + df['LastName']
        df = df.rename(columns={'Zip': 'Zip Code'})[['Name', 'Phone', 'Gender', 'Age', 'Zip Code']]
        df['Source'] = 'CSV File'
        df['Details'] = 'This lead was sourced from our CSV database and represents historical data.'
        logging.info(f"CSV file read successfully with {len(df)} leads.")
        return df
    except Exception as e:
        logging.error(f"Error reading CSV file: {e}")
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
    embed.add_field(name="Source", value=lead["Source"], inline=False)
    embed.add_field(name="Details", value=lead["Details"], inline=False)
    message = await channel.send(embed=embed)
    save_or_update_lead(message.id, lead["Name"], lead["Phone"], lead["Gender"], lead["Age"], lead["Zip Code"], "new", "unknown", "warm")
    current_lead_index = (current_lead_index + 1) % len(leads)
    logging.info(f"Sent warm lead {lead['Name']} from CSV to Discord.")

@tasks.loop(minutes=10)
async def send_lead_from_csv():
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

    # Define equivalent emojis for each status
    emoji_mappings = {
        "called": {"✅", "✔️", "☑️"},
        "sold/booked": {"🔥"},
        "did not answer": {"❌"},
        "do-not-call": {"📵"}
    }

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
            
            status = "new"
            agent = "unknown"
            reaction_found = False

            for reaction in message.reactions:
                async for user in reaction.users():
                    if user != bot.user:
                        agent = user.name
                        reaction_found = True

                        # Match emoji to a specific category
                        emoji = str(reaction.emoji)
                        if emoji in emoji_mappings["sold/booked"]:
                            status = "sold/booked"
                        elif emoji in emoji_mappings["do-not-call"]:
                            status = "do-not-call"
                        elif emoji in emoji_mappings["did not answer"]:
                            status = "did not answer"
                        elif emoji in emoji_mappings["called"]:
                            status = "called"

            # If no specific emoji status but any reaction exists, mark as "called"
            if reaction_found and status == "new":
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
    # Full webhook handling logic unchanged.
    return jsonify({"status": "success", "message": "Webhook received"}), 200

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_counts():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'called'")
    called_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'sold/booked'")
    sold_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'")
    uncalled_leads_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM leads WHERE lead_type = 'hot'")
    hot_leads_count = cursor.fetchone()[0]
    closed_percentage = (sold_leads_count / total_leads_count * 100) if total_leads_count > 0 else 0
    cursor.execute("SELECT AVG(age) FROM leads WHERE age IS NOT NULL")
    average_age = cursor.fetchone()[0] or 0
    cursor.execute("SELECT zip_code, COUNT(*) AS zip_count FROM leads GROUP BY zip_code ORDER BY zip_count DESC LIMIT 1")
    popular_zip = cursor.fetchone()
    popular_zip = popular_zip[0] if popular_zip else "N/A"
    cursor.execute("SELECT gender, COUNT(*) AS gender_count FROM leads GROUP BY gender ORDER BY gender_count DESC LIMIT 1")
    popular_gender = cursor.fetchone()
    popular_gender = popular_gender[0] if popular_gender else "N/A"
    cursor.execute("SELECT strftime('%H', created_at) AS hour, COUNT(*) FROM leads GROUP BY hour")
    hours = cursor.fetchall()
    hottest_time = "N/A"
    if hours:
        hour_counts = {int(hour): count for hour, count in hours}
        hottest_hour = max(hour_counts, key=hour_counts.get)
        start_hour_12 = datetime.strptime(f"{hottest_hour}", "%H").strftime("%I %p")
        end_hour = (hottest_hour + 3) % 24
        end_hour_12 = datetime.strptime(f"{end_hour}", "%H").strftime("%I %p")
        hottest_time = f"{start_hour_12} - {end_hour_12}"
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
        "hottest_time": hottest_time,
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

