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

@app.route('/agent-dashboard', methods=['GET'])
def get_dashboard_metrics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Fetch metrics data
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

        # Return as JSON
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
    finally:
        conn.close()

@app.route('/agent-leaderboard', methods=['GET'])
def get_leaderboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' GROUP BY agent")
        leads_called = cursor.fetchall()

        cursor.execute("SELECT agent, sales_count FROM agent_sales")
        sales_data = cursor.fetchall()

        leaderboard = [
            {"agent": agent, "leads_called": called, "sales_count": next((s[1] for s in sales_data if s[0] == agent), 0)}
            for agent, called in leads_called
        ]

        leaderboard.sort(key=lambda x: x["sales_count"], reverse=True)

        return jsonify(leaderboard)
    finally:
        conn.close()

@app.route('/weekly-leaderboard', methods=['GET'])
def get_weekly_leaderboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        last_week = datetime.now() - timedelta(days=7)
        cursor.execute('''
            SELECT agent, COUNT(*) FROM leads
            WHERE status = 'sold/booked' AND created_at > ?
            GROUP BY agent
        ''', (last_week,))
        sales_data = cursor.fetchall()

        leaderboard = [
            {"agent": agent, "sales_count": sales_count, "leads_called": 0} for agent, sales_count in sales_data
        ]

        return jsonify(leaderboard)
    finally:
        conn.close()

@app.route('/leads', methods=['GET'])
def get_leads():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT name, phone, gender, age, zip_code, status, lead_type, created_at
        FROM leads
    ''')
    leads = cursor.fetchall()
    conn.close()
    # Convert database rows to a JSON-friendly format
    leads_list = [
        {
            "Name": lead[0],
            "Phone": lead[1],
            "Gender": lead[2],
            "Age": lead[3],
            "Zip Code": lead[4],
            "Status": lead[5],
            "Type": lead[6],
            "Created At": lead[7]
        }
        for lead in leads
    ]
    return jsonify(leads_list)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
