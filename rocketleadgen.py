import discord
from discord.ext import commands
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import logging
import os
from threading import Thread
from twilio.jwt.client import ClientCapabilityToken
from twilio.twiml.voice_response import VoiceResponse

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWIML_APP_SID = "AP3e887681a7ea924ad732e46b00cd04c4"  # TwiML Application SID

# Initialize Flask app and set CORS
app = Flask(__name__)
CORS(app)

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# API: Generate Twilio Capability Token
@app.route('/generate-token', methods=['GET'])
def generate_token():
    agent_name = request.args.get("agent_name")
    logging.info(f"Token request received for agent: {agent_name}")
    if not agent_name:
        logging.error("Agent name is required.")
        return jsonify({"error": "Agent name is required"}), 400
    try:
        capability = ClientCapabilityToken(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        capability.allow_client_incoming(agent_name)
        capability.allow_client_outgoing(TWIML_APP_SID)
        token = capability.to_jwt()
        logging.info(f"Generated token for agent: {agent_name}")
        return jsonify({"token": token}), 200
    except Exception as e:
        logging.error(f"Error generating token: {e}")
        return jsonify({"error": str(e)}), 500

# API: TwiML for handling calls (routes call to client "Agent1")
@app.route('/handle-call', methods=['POST'])
def handle_call():
    try:
        response = VoiceResponse()
        caller = request.form.get("From")
        logging.info(f"Incoming call from: {caller}")
        dial = response.dial()
        dial.client("Agent1")  # Must match the agent name used in token generation
        logging.info("Successfully generated TwiML for the call.")
        return Response(str(response), content_type="application/xml")
    except Exception as e:
        logging.error(f"Error handling call: {e}")
        error_response = VoiceResponse()
        error_response.say("An error occurred while processing your call. Please try again later.")
        return Response(str(error_response), content_type="application/xml")

# Serve the standalone call page
@app.route('/call-page', methods=['GET'])
def call_page():
    return send_from_directory(directory='static', filename='call.html')

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
