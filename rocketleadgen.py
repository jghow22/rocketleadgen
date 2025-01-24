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
TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"

# Initialize Flask app and set CORS
app = Flask(__name__)
CORS(app)

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
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

    # Insert leads from CSV
    df = read_leads_from_csv(CSV_FILE_PATH)
    if df is not None:
        for _, row in df.iterrows():
            try:
                cursor.execute('''
                    INSERT INTO leads (name, phone, gender, age, zip_code, status, lead_type, agent)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (row['Name'], row['Phone'], row['Gender'], row['Age'], row['Zip Code'], 'new', 'warm', 'Test Agent'))
            except sqlite3.IntegrityError:
                logging.info(f"Lead {row['Name']} already exists in the database.")
        conn.commit()

    # Insert test agent sales
    cursor.execute('''
        INSERT OR IGNORE INTO agent_sales (agent, sales_count)
        VALUES ('Test Agent', 10)
    ''')
    conn.commit()
    conn.close()
    logging.info("Database initialized, leads loaded, and test data inserted.")

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
        return df
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return None

# Debugging endpoint to inspect database content
@app.route('/debug-database', methods=['GET'])
def debug_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads")
    leads = cursor.fetchall()
    cursor.execute("SELECT * FROM agent_sales")
    sales = cursor.fetchall()
    conn.close()
    return jsonify({"leads": leads, "agent_sales": sales})

# Fetches dashboard metrics
@app.route('/agent-dashboard', methods=['GET'])
def get_dashboard_metrics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'called'")
        called_leads_count = cursor.fetchone()[0]
        logging.info(f"Called leads count: {called_leads_count}")

        cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'sold/booked'")
        sold_leads_count = cursor.fetchone()[0]
        logging.info(f"Sold leads count: {sold_leads_count}")

        cursor.execute("SELECT COUNT(*) FROM leads")
        total_leads_count = cursor.fetchone()[0]
        logging.info(f"Total leads count: {total_leads_count}")

        cursor.execute("SELECT COUNT(*) FROM leads WHERE status = 'new'")
        uncalled_leads_count = cursor.fetchone()[0]
        logging.info(f"Uncalled leads count: {uncalled_leads_count}")

        cursor.execute("SELECT COUNT(*) FROM leads WHERE lead_type = 'hot'")
        hot_leads_count = cursor.fetchone()[0]
        logging.info(f"Hot leads count: {hot_leads_count}")

        return jsonify({
            "called_leads_count": called_leads_count,
            "sold_leads_count": sold_leads_count,
            "total_leads_count": total_leads_count,
            "uncalled_leads_count": uncalled_leads_count,
            "hot_leads_count": hot_leads_count
        })
    finally:
        conn.close()

# Fetches leaderboard data
@app.route('/agent-leaderboard', methods=['GET'])
def get_leaderboard():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT agent, COUNT(*) FROM leads WHERE status = 'called' GROUP BY agent")
        leads_called = cursor.fetchall()
        logging.info(f"Leads called per agent: {leads_called}")

        cursor.execute("SELECT agent, sales_count FROM agent_sales")
        sales_data = cursor.fetchall()
        logging.info(f"Sales data: {sales_data}")

        leaderboard = [
            {"agent": agent, "leads_called": called, "sales_count": next((s[1] for s in sales_data if s[0] == agent), 0)}
            for agent, called in leads_called
        ]
        leaderboard.sort(key=lambda x: x["sales_count"], reverse=True)
        return jsonify(leaderboard)
    finally:
        conn.close()

# Fetches weekly leaderboard data
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
        weekly_sales = cursor.fetchall()
        leaderboard = [
            {"agent": agent, "sales_count": count, "leads_called": 0} for agent, count in weekly_sales
        ]
        return jsonify(leaderboard)
    finally:
        conn.close()

# Fetches leads data
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

# Discord bot ready event
@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')

# Run Flask app
def run_flask_app():
    app.run(host='0.0.0.0', port=10000)

# Run Discord bot
def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    setup_database()
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
