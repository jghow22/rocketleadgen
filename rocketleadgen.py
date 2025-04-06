import os
import logging
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from twilio.jwt.client import ClientCapabilityToken
from twilio.twiml.voice_response import VoiceResponse

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables for Twilio
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWIML_APP_SID = "AP3e887681a7ea924ad732e46b00cd04c4"  # TwiML Application SID

# Initialize Flask app with static folder set to 'static'
app = Flask(__name__, static_folder='static')
CORS(app)

# Simple index route for testing
@app.route('/', methods=['GET'])
def index():
    return "Rocket Lead Gen API is running."

# Debug endpoint to list files in the static folder
@app.route('/debug-static', methods=['GET'])
def debug_static():
    static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    try:
        files = os.listdir(static_folder)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint: Generate Twilio Capability Token
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

# Endpoint: Handle calls via TwiML
@app.route('/handle-call', methods=['POST'])
def handle_call():
    try:
        response = VoiceResponse()
        caller = request.form.get("From")
        logging.info(f"Incoming call from: {caller}")
        dial = response.dial()
        dial.client("Agent1")  # Ensure this matches your desired agent name
        logging.info("Successfully generated TwiML for the call.")
        return Response(str(response), content_type="application/xml")
    except Exception as e:
        logging.error(f"Error handling call: {e}")
        error_response = VoiceResponse()
        error_response.say("An error occurred while processing your call. Please try again later.")
        return Response(str(error_response), content_type="application/xml")

# Endpoint: Serve the standalone call page from the static folder
@app.route('/call-page', methods=['GET'])
def call_page():
    static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    logging.info("Static folder path: " + static_folder)
    file_path = os.path.join(static_folder, "call.html")
    if not os.path.exists(file_path):
        logging.error("call.html not found in static folder: " + static_folder)
        return "call.html not found", 404
    return send_from_directory(static_folder, 'call.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
