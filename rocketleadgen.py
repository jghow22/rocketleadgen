import discord
from discord.ext import commands
from flask import Flask, request, jsonify, Response
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
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
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
        logging.info(f"TWILIO_ACCOUNT_SID: {TWILIO_ACCOUNT_SID}")
        logging.info(f"TWILIO_AUTH_TOKEN: {TWILIO_AUTH_TOKEN}")
        logging.info(f"TWIML_APP_SID: {TWIML_APP_SID}")

        capability = ClientCapabilityToken(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        capability.allow_client_incoming(agent_name)
        capability.allow_client_outgoing(TWIML_APP_SID)
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
    caller = request.form.get("From")
    logging.info(f"Incoming call from: {caller}")

    try:
        response.say("Connecting your call now.")
        response.dial(TWILIO_PHONE_NUMBER)

        logging.info("Successfully generated TwiML for the call.")
        return Response(str(response), content_type="application/xml")
    except Exception as e:
        logging.error(f"Error handling call: {e}")
        response.say("An error occurred while processing your call. Please try again later.")
        return Response(str(response), content_type="application/xml")

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
    flask_thread = Thread(target=run_flask_app)
    flask_thread.start()
    run_discord_bot()
