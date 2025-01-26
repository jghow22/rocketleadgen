import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import logging
import sqlite3
import os
from datetime import datetime
from threading import Thread
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
TWIML_APP_SID = "AP3e887681a7ea924ad732e46b00cd04c4"  # TwiML Application SID
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
            name TEXT,
            phone TEXT,
            status TEXT DEFAULT 'new',
            notes TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("Database setup completed.")

# API: Generate Twilio Capability Token
@app.route('/generate-token', methods=['GET'])
def generate_token():
    agent_name = request.args.get("agent_name")
    logging.info(f"Received token request for agent: {agent_name}")

    if not agent_name:
        logging.error("Agent name is required.")
        return jsonify({"error": "Agent name is required"}), 400

    try:
        capability = ClientCapabilityToken(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        capability.allow_client_incoming(agent_name)
        capability.allow_client_outgoing(TWIML_APP_SID)  # Use TwiML App SID
        token = capability.to_jwt()

        logging.info(f"Generated token for agent: {agent_name}")
        return jsonify({"token": token}), 200
    except Exception as e:
        logging.error(f"Error generating token: {e}")
        return jsonify({"error": str(e)}), 500

# API: TwiML for handling calls
@app.route('/handle-call', methods=['POST'])
def handle_call():
    response = VoiceResponse()
    caller = request.form.get("From")  # Caller phone number
    agent_name = request.form.get("agent_name")

    logging.info(f"Incoming call from: {caller}")
    logging.info(f"Routing to agent: {agent_name}")

    if agent_name:
        response.dial().client(agent_name)
        logging.info(f"Routing call to agent: {agent_name}")
    else:
        response.say("No agent is available to take your call.")
        logging.warning("No agent available to handle the call.")

    return str(response)

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
