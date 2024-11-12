import discord
from discord.ext import commands
from flask import Flask, jsonify
from flask_cors import CORS
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from threading import Thread
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)

# Database path
DB_PATH = 'leads.db'

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Create a Discord bot instance
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True  # Enable fetching of all members
bot = commands.Bot(command_prefix="!", intents=intents)

# Global variable to store all agent usernames from Discord
discord_agents = []

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

def save_or_update_lead(discord_message_id, name, phone, gender, age, zip_code, status, agent):
    logging.info(f"Saving lead - ID: {discord_message_id}, Name: {name}, Agent: {agent}, Status: {status}")
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO leads (discord_message_id, name, phone, gender, age, zip_code, status, created_at, agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_message_id) DO UPDATE SET status=excluded.status, agent=excluded.agent
    ''', (discord_message_id, name, phone, gender, age, zip_code, status, datetime.now(), agent))
    
    if status == "sold/booked":
        cursor.execute('''
            INSERT INTO agent_sales (agent, sales_count)
            VALUES (?, 1)
            ON CONFLICT(agent) DO UPDATE SET sales_count = sales_count + 1
        ''', (agent,))
    
    conn.commit()
    conn.close()

async def scan_past_messages():
    """Scans past messages in the Discord channel to populate the database."""
    logging.info("Scanning past messages in the Discord channel.")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    await fetch_discord_agents()  # Fetch all members and store in discord_agents
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
            
            save_or_update_lead(message.id, name, phone, gender, age, zip_code, status, agent)

async def fetch_discord_agents():
    """Fetches all Discord members and stores their usernames."""
    logging.info("Fetching all agents (members) in the Discord server.")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    guild = channel.guild
    global discord_agents
    discord_agents = [member.name for member in guild.members if not member.bot]
    logging.info(f"Fetched {len(discord_agents)} agents from Discord.")

@app.route('/agent-dashboard', methods=['GET'])
def get_dashboard_metrics():
    logging.info("Handling request to /agent-dashboard for dashboard metrics.")
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
        hottest_time = f"{hottest_hour:02d}:00 - {hottest_hour + 3:02d}:00"

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
        "hottest_time": hottest_time
    })

@app.route('/agent-leaderboard', methods=['GET'])
def get_leaderboard_data():
    logging.info("Handling request to /agent-leaderboard.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    leaderboard = {agent: {"agent": agent, "sales_count": 0, "leads_called": 0} for agent in discord_agents}
    
    cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' GROUP BY agent")
    leads_called_data = cursor.fetchall()
    
    for agent, count in leads_called_data:
        if agent in leaderboard:
            leaderboard[agent]["leads_called"] = count

    cursor.execute("SELECT agent, sales_count FROM agent_sales")
    sales_data = cursor.fetchall()
    
    for agent, count in sales_data:
        if agent in leaderboard:
            leaderboard[agent]["sales_count"] = count

    leaderboard_list = list(leaderboard.values())
    logging.info(f"Returning leaderboard data: {leaderboard_list}")
    conn.close()
    return jsonify(leaderboard_list)

@app.route('/weekly-leaderboard', methods=['GET'])
def get_weekly_leaderboard():
    logging.info("Handling request to /weekly-leaderboard.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    one_week_ago = datetime.now() - timedelta(days=7)
    leaderboard = {agent: {"agent": agent, "sales_count": 0, "leads_called": 0} for agent in discord_agents}
    
    cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' AND created_at >= ? GROUP BY agent", (one_week_ago,))
    leads_called_data = cursor.fetchall()
    
    for agent, count in leads_called_data:
        if agent in leaderboard:
            leaderboard[agent]["leads_called"] = count

    cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'sold/booked' AND created_at >= ? GROUP BY agent", (one_week_ago,))
    sales_data = cursor.fetchall()
    
    for agent, count in sales_data:
        if agent in leaderboard:
            leaderboard[agent]["sales_count"] = count

    leaderboard_list = list(leaderboard.values())
    logging.info(f"Returning weekly leaderboard data: {leaderboard_list}")
    conn.close()
    return jsonify(leaderboard_list)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await scan_past_messages()

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
