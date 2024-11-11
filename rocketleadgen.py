import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import sqlite3
import os
from datetime import datetime
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
CORS(app, resources={r"/*": {"origins": "*"}})  # Allow all origins for CORS

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
    
    # Update agent sales count if lead is sold
    if status == "sold/booked":
        cursor.execute('''
            INSERT INTO agent_sales (agent, sales_count)
            VALUES (?, 1)
            ON CONFLICT(agent) DO UPDATE SET sales_count = sales_count + 1
        ''', (agent,))
    
    conn.commit()
    conn.close()

async def fetch_discord_agents():
    """Fetches all Discord members and stores their usernames."""
    logging.info("Fetching all agents (members) in the Discord server.")
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    guild = channel.guild
    global discord_agents
    discord_agents = [member.name for member in guild.members if not member.bot]
    logging.info(f"Fetched {len(discord_agents)} agents from Discord: {discord_agents}")

async def scan_past_messages():
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
            
            # Default status and agent
            status = "new"
            agent = "unknown"
            
            # Determine agent and status based on reactions
            for reaction in message.reactions:
                async for user in reaction.users():
                    if user != bot.user:  # Only consider non-bot users as agents
                        agent = user.name  # Use Discord username as agent name
                        if str(reaction.emoji) == "🔥":
                            status = "sold/booked"
                        elif str(reaction.emoji) == "📵":
                            status = "do-not-call"
                        elif str(reaction.emoji) == "✅":
                            status = "called"
            
            save_or_update_lead(message.id, name, phone, gender, age, zip_code, status, agent)

@app.route('/agent-leaderboard', methods=['GET'])
def get_agent_leaderboard():
    logging.info("Handling request to /agent-leaderboard for sales leaderboard.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    # Initialize leaderboard with all agents from Discord and zero sales
    leaderboard = {agent: {"sales_count": 0, "leads_called": 0} for agent in discord_agents}
    logging.debug(f"Initial leaderboard (all agents with zero counts): {leaderboard}")

    # Get agents with sales counts from agent_sales table
    cursor.execute("SELECT agent, sales_count FROM agent_sales")
    sales_counts = cursor.fetchall()

    # Update leaderboard dictionary with actual sales counts
    for agent, count in sales_counts:
        if agent in leaderboard:
            leaderboard[agent]["sales_count"] = count
        logging.debug(f"Updated {agent}'s sales count to {count}")

    # Count called leads for each agent
    cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' GROUP BY agent")
    called_counts = cursor.fetchall()
    for agent, count in called_counts:
        if agent in leaderboard:
            leaderboard[agent]["leads_called"] = count
        logging.debug(f"Updated {agent}'s leads called to {count}")

    # Convert leaderboard dictionary to a sorted list by sales count
    sorted_leaderboard = [
        {"agent": agent, "sales_count": data["sales_count"], "leads_called": data["leads_called"]}
        for agent, data in sorted(leaderboard.items(), key=lambda x: x[1]["sales_count"], reverse=True)
    ]
    
    logging.debug(f"Final sorted leaderboard data: {sorted_leaderboard}")
    conn.close()
    return jsonify(sorted_leaderboard)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('Bot is online and ready.')
    await scan_past_messages()

def run_flask_app():
    logging.info("Starting Flask app.")
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
