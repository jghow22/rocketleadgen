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

# Debugging endpoint to inspect database content
@app.route('/debug-database', methods=['GET'])
def debug_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads")
    leads = cursor.fetchall()
    cursor.execute("SELECT * FROM agent_sales")
    agent_sales = cursor.fetchall()
    conn.close()
    return jsonify({"leads": leads, "agent_sales": agent_sales})

# Reads leads from CSV file
def read_leads_from_csv(file_path):
    try:
        df = pd.read_csv(file_path)
        logging.info(f"Loaded {len(df)} leads from CSV.")
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

@app.route('/agent-dashboard', methods=['GET'])
def get_dashboard_metrics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Log counts for debugging
        cursor.execute("SELECT COUNT(*) FROM leads")
        total_leads_count = cursor.fetchone()[0]
        logging.info(f"Total leads in database: {total_leads_count}")
        cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'called'")
        called_leads_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'sold/booked'")
        sold_leads_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'")
        uncalled_leads_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM leads WHERE lead_type = 'hot'")
        hot_leads_count = cursor.fetchone()[0]

        # Calculate metrics
        closed_percentage = (sold_leads_count / total_leads_count * 100) if total_leads_count > 0 else 0
        cursor.execute("SELECT AVG(age) FROM leads WHERE age IS NOT NULL")
        average_age = cursor.fetchone()[0] or 0

        return jsonify({
            "called_leads_count": called_leads_count,
            "sold_leads_count": sold_leads_count,
            "total_leads_count": total_leads_count,
            "uncalled_leads_count": uncalled_leads_count,
            "closed_percentage": round(closed_percentage, 2),
            "average_age": round(average_age, 1)
        })
    finally:
        conn.close()

@app.route('/leads', methods=['GET'])
def get_leads():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT name, phone, gender, age, zip_code, status, lead_type, created_at FROM leads')
    leads = cursor.fetchall()
    conn.close()
    return jsonify([
        {"Name": lead[0], "Phone": lead[1], "Gender": lead[2], "Age": lead[3],
         "Zip Code": lead[4], "Status": lead[5], "Type": lead[6], "Created At": lead[7]}
        for lead in leads
    ])

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
