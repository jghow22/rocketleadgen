import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import logging
import pandas as pd
import sqlite3
from threading import Thread
import time
import os
from datetime import datetime
import pytz

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Database path
DB_PATH = 'leads.db'

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))

# Time zone for scheduling
TIME_ZONE = 'America/New_York'

# Initialize Flask app and enable CORS
app = Flask(__name__)
CORS(app)

# Create an instance of a Discord bot with commands
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            gender TEXT,
            age INTEGER,
            zip_code TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

# Setup database
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
    logging.info(f"Lead saved to database: {name}")

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

    closed_percentage = (sold_leads_count / total_leads_count * 100) if total_leads_count > 0 else 0.0

    cursor.execute("SELECT AVG(age) FROM leads WHERE age IS NOT NULL")
    average_age = cursor.fetchone()[0] or 0

    cursor.execute("SELECT zip_code, COUNT(*) as count FROM leads GROUP BY zip_code ORDER BY count DESC LIMIT 1")
    popular_zip = cursor.fetchone()
    popular_zip = popular_zip[0] if popular_zip else "Unknown"

    cursor.execute("SELECT gender, COUNT(*) as count FROM leads GROUP BY gender ORDER BY count DESC LIMIT 1")
    popular_gender = cursor.fetchone()
    popular_gender = popular_gender[0] if popular_gender else "Unknown"

    cursor.execute("SELECT strftime('%H', created_at), COUNT(*) as count FROM leads GROUP BY strftime('%H', created_at) ORDER BY count DESC LIMIT 1")
    hottest_time = cursor.fetchone()
    hottest_time = f"{int(hottest_time[0]):02d}:00 - {int(hottest_time[0])+2:02d}:59" if hottest_time else "Unknown"

    logging.debug(f"Dashboard Metrics - Called: {called_leads_count}, Sold: {sold_leads_count}, Total: {total_leads_count}, Uncalled: {uncalled_leads_count}, Closed %: {closed_percentage}, Avg Age: {average_age}, Popular Zip: {popular_zip}, Popular Gender: {popular_gender}, Hottest Time: {hottest_time}")

    conn.close()

    return jsonify({
        "called_leads_count": called_leads_count,
        "sold_leads_count": sold_leads_count,
        "total_leads_count": total_leads_count,
        "uncalled_leads_count": uncalled_leads_count,
        "closed_percentage": round(closed_percentage, 2),
        "average_age": int(average_age),
        "popular_zip": popular_zip,
        "popular_gender": popular_gender,
        "hottest_time": hottest_time
    })

@app.route('/agent-leaderboard', methods=['GET'])
def get_leaderboard():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT name FROM leads WHERE name IS NOT NULL")
    agents = [row[0] for row in cursor.fetchall()]

    leaderboard_data = []
    for agent in agents:
        cursor.execute("SELECT COUNT(*) FROM leads WHERE name = ? AND status = 'sold/booked'", (agent,))
        sales_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM leads WHERE name = ? AND status = 'called'", (agent,))
        leads_called = cursor.fetchone()[0]

        leaderboard_data.append({
            "agent": agent,
            "sales_count": sales_count,
            "leads_called": leads_called
        })

    conn.close()

    leaderboard_data.sort(key=lambda x: x["sales_count"], reverse=True)
    logging.debug("Final sorted leaderboard data: " + str(leaderboard_data))
    return jsonify(leaderboard_data)

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
