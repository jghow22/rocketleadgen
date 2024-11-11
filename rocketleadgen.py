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
    logging.debug(f"Attempting to save lead: Name={name}, Phone={phone}, Gender={gender}, Age={age}, Zip Code={zip_code}")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO leads (name, phone, gender, age, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, phone, gender, age, zip_code))
        conn.commit()
        logging.info(f"Lead successfully saved to database: {name}")
    except Exception as e:
        logging.error(f"Error saving lead to database: {e}")
    finally:
        conn.close()

# Temporary function to manually add a test lead
def add_manual_test_lead():
    logging.info("Adding a manual test lead to the database.")
    save_lead_to_db("Test User", "555-5555", "Unknown", 30, "30301")

@app.route('/agent-dashboard', methods=['GET'])
def get_dashboard_metrics():
    logging.info("Handling request to /agent-dashboard for dashboard metrics.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'called'")
    called_leads_count = cursor.fetchone()[0]
    logging.debug(f"Called Leads Count: {called_leads_count}")

    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'sold/booked'")
    sold_leads_count = cursor.fetchone()[0]
    logging.debug(f"Sold Leads Count: {sold_leads_count}")

    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads_count = cursor.fetchone()[0]
    logging.debug(f"Total Leads Count: {total_leads_count}")

    cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'")
    uncalled_leads_count = cursor.fetchone()[0]
    logging.debug(f"Uncalled Leads Count: {uncalled_leads_count}")

    closed_percentage = (sold_leads_count / total_leads_count * 100) if total_leads_count > 0 else 0.0
    logging.debug(f"Closed Percentage: {closed_percentage}")

    cursor.execute("SELECT AVG(age) FROM leads WHERE age IS NOT NULL")
    average_age = cursor.fetchone()[0] or 0
    logging.debug(f"Average Age: {average_age}")

    cursor.execute("SELECT zip_code, COUNT(*) as count FROM leads GROUP BY zip_code ORDER BY count DESC LIMIT 1")
    popular_zip = cursor.fetchone()
    popular_zip = popular_zip[0] if popular_zip else "Unknown"
    logging.debug(f"Popular Zip Code: {popular_zip}")

    cursor.execute("SELECT gender, COUNT(*) as count FROM leads GROUP BY gender ORDER BY count DESC LIMIT 1")
    popular_gender = cursor.fetchone()
    popular_gender = popular_gender[0] if popular_gender else "Unknown"
    logging.debug(f"Popular Gender: {popular_gender}")

    cursor.execute("SELECT strftime('%H', created_at), COUNT(*) as count FROM leads GROUP BY strftime('%H', created_at) ORDER BY count DESC LIMIT 1")
    hottest_time = cursor.fetchone()
    hottest_time = f"{int(hottest_time[0]):02d}:00 - {int(hottest_time[0])+2:02d}:59" if hottest_time else "Unknown"
    logging.debug(f"Hottest Time: {hottest_time}")

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
    logging.info("Handling request to /agent-leaderboard for leaderboard data.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()

    # Fetch all distinct agents who have leads
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
        logging.debug(f"Agent: {agent}, Sales Count: {sales_count}, Leads Called: {leads_called}")

    conn.close()

    leaderboard_data.sort(key=lambda x: x["sales_count"], reverse=True)
    logging.debug("Final sorted leaderboard data: " + str(leaderboard_data))
    return jsonify(leaderboard_data)

@app.route('/debug-database', methods=['GET'])
def debug_database():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads")
    leads = cursor.fetchall()
    conn.close()

    formatted_leads = [
        {"id": row[0], "name": row[1], "phone": row[2], "gender": row[3], "age": row[4], "zip_code": row[5], "status": row[6], "created_at": row[7]}
        for row in leads
    ]
    logging.debug("Database contents: " + str(formatted_leads))
    return jsonify(formatted_leads)

def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    # Call the test lead function once to verify database functionality
    add_manual_test_lead()

    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
