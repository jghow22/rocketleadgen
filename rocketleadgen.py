import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import sqlite3
import os
from threading import Thread
import time
import asyncio
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

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})  # Adjust the origins as needed

# Create a Discord bot instance
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Set up the database
def setup_database():
    logging.debug("Attempting to set up the database.")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            gender TEXT,
            age TEXT,
            zip_code TEXT,
            status TEXT DEFAULT 'new'
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

setup_database()

def save_lead_to_db(name, phone, gender, age, zip_code):
    logging.debug(f"Attempting to save lead: Name={name}, Phone={phone}, Gender={gender}, Age={age}, Zip={zip_code}")
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO leads (name, phone, gender, age, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, phone, gender, age, zip_code))
        conn.commit()
        inserted_id = cursor.lastrowid
        conn.close()
        logging.info(f"Lead saved to database with ID {inserted_id}: {name}")
    except Exception as e:
        logging.error(f"Error saving lead to database: {str(e)}")

def fetch_all_lead_statuses_from_db():
    logging.debug("Fetching all lead statuses from the database.")
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM leads')
        rows = cursor.fetchall()
        conn.close()
        return [{'id': row[0], 'name': row[1], 'phone': row[2], 'gender': row[3], 'age': row[4], 'zip_code': row[5], 'status': row[6]} for row in rows]
    except Exception as e:
        logging.error(f"Error fetching data from database: {str(e)}")
        return []

@app.route('/agent-dashboard', methods=['GET'])
def get_lead_statuses():
    lead_data = fetch_all_lead_statuses_from_db()
    if not lead_data:
        logging.warning("No data found in the database.")
    else:
        logging.debug(f"Lead data fetched: {lead_data}")
    return jsonify(lead_data)

@app.route('/wix-webhook', methods=['POST'])
def handle_wix_webhook():
    logging.debug("Received webhook from Wix.")
    try:
        data = request.json
        logging.debug(f"Data received from Wix: {data}")

        submissions = data.get('data', {}).get('submissions', [])
        submission_data = {item['label'].lower(): item['value'] for item in submissions}

        name = submission_data.get('name', data.get('data', {}).get('field:first_name_379d', 'N/A'))
        phone = submission_data.get('phone', data.get('data', {}).get('field:phone_23b2', 'N/A'))
        gender = submission_data.get('gender', data.get('data', {}).get('field:gender', 'N/A'))
        age = data.get('data', {}).get('field:age', 'N/A')
        zip_code = data.get('data', {}).get('field:zip_code', 'N/A')

        # Log extracted data before inserting
        logging.debug(f"Extracted data: Name={name}, Phone={phone}, Gender={gender}, Age={age}, Zip={zip_code}")
        
        # Call function to save the lead
        save_lead_to_db(name, phone, gender, age, zip_code)

        return jsonify({"status": "success", "message": "Lead saved to database"}), 200
    except Exception as e:
        logging.error(f"Error processing Wix webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def run_flask_app():
    logging.debug("Starting Flask app.")
    app.run(host='0.0.0.0', port=10000)

def run_discord_bot():
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
