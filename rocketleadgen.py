import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import logging
import sqlite3
import os
from datetime import datetime, timedelta
import pandas as pd
from threading import Thread
import asyncio
from twilio.rest import Client
from twilio.jwt.client import ClientCapabilityToken
from twilio.twiml.voice_response import VoiceResponse

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
CSV_FILE_PATH = 'leadslistseptwenty.csv'
DB_PATH = 'leads.db'

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
            agent TEXT,
            notes TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

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

# API: Generate Twilio Capability Token
@app.route('/generate-token', methods=['GET'])
def generate_token():
    agent_name = request.args.get("agent_name")
    if not agent_name:
        return jsonify({"error": "Agent name is required"}), 400

    try:
        capability = ClientCapabilityToken(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        capability.allow_client_incoming(agent_name)
        capability.allow_client_outgoing("your_twiml_application_sid")  # Replace with TwiML App SID
        token = capability.to_jwt()

        return jsonify({"token": token}), 200
    except Exception as e:
        logging.error(f"Error generating token: {e}")
        return jsonify({"error": str(e)}), 500

# API: TwiML for handling calls
@app.route('/handle-call', methods=['POST'])
def handle_call():
    response = VoiceResponse()
    agent_name = request.form.get("agent_name")

    if agent_name:
        response.dial().client(agent_name)
    else:
        response.say("No agent is available to take your call.")

    return str(response)

# API: Update Lead Status
@app.route('/update-lead-status', methods=['POST'])
def update_lead_status():
    data = request.json
    lead_id = data.get("lead_id")
    status = data.get("status")
    notes = data.get("notes", "")

    if not lead_id or not status:
        return jsonify({"error": "Missing lead_id or status"}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE leads SET status = ?, notes = ? WHERE id = ?",
            (status, notes, lead_id)
        )
        conn.commit()
        return jsonify({"message": "Lead status updated"}), 200
    except Exception as e:
        logging.error(f"Error updating lead status: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# Discord bot ready event
@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')

# Twilio: Initiate Call Transfer
def initiate_call_transfer(lead_phone, target_phone):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    try:
        call = client.calls.create(
            to=target_phone,
            from_=TWILIO_PHONE_NUMBER,
            url=f"https://your-backend-url.com/voice/{lead_phone}"
        )
        logging.info(f"Call initiated. SID: {call.sid}")
        return {"success": True, "call_sid": call.sid}
    except Exception as e:
        logging.error(f"Failed to initiate call: {e}")
        return {"success": False, "error": str(e)}

# API: Initiate Call Transfer
@app.route('/transfer-call', methods=['POST'])
def transfer_call():
    data = request.json
    lead_id = data.get('lead_id')
    target_phone = data.get('target_phone')

    if not lead_id or not target_phone:
        return jsonify({"error": "Missing lead_id or target_phone"}), 400

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT phone, name FROM leads WHERE id = ?", (lead_id,))
        lead = cursor.fetchone()
        if not lead:
            return jsonify({"error": "Lead not found"}), 404

        lead_phone, lead_name = lead
        result = initiate_call_transfer(lead_phone, target_phone)

        if result["success"]:
            cursor.execute("UPDATE leads SET call_in_progress = 1 WHERE id = ?", (lead_id,))
            conn.commit()
            return jsonify({"message": "Call transfer initiated", "call_sid": result["call_sid"]}), 200
        else:
            return jsonify({"error": result["error"]}), 500
    finally:
        conn.close()

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
