import os
import logging
import json
import datetime
from typing import Dict, Union, Tuple, Any, Optional, List
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from twilio.jwt.client import ClientCapabilityToken
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables for Twilio
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWIML_APP_SID = "AP3e887681a7ea924ad732e46b00cd04c4"  # TwiML Application SID

# In-memory storage for active calls (replace with database in production)
active_calls = {}

class RocketLeadGenAPI:
    """Lead generation system API for life insurance agents with Twilio integration."""
    
    def __init__(self) -> None:
        """Initialize the Flask application with CORS support."""
        self.app = Flask(__name__)
        
        # Enable CORS with more explicit settings
        CORS(self.app, resources={
            r"/*": {
                "origins": "*",
                "methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization"]
            }
        })
        
        # Initialize Twilio client for API operations
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            self.twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        else:
            logging.warning("Twilio credentials not set. API operations will not work.")
            self.twilio_client = None
            
        self._register_routes()
    
    def _register_routes(self) -> None:
        """Register all API endpoints."""
        self.app.route('/', methods=['GET'])(self.index)
        self.app.route('/test-connection', methods=['GET'])(self.test_connection)
        self.app.route('/generate-token', methods=['GET'])(self.generate_token)
        self.app.route('/handle-call', methods=['POST'])(self.handle_call)
        self.app.route('/call-status', methods=['POST'])(self.call_status)
        self.app.route('/current-calls', methods=['GET'])(self.get_current_calls)
        self.app.route('/answer-call', methods=['POST'])(self.answer_call)
        self.app.route('/end-call', methods=['POST'])(self.end_call)
    
    def index(self) -> str:
        """Simple index route for API status check.
        
        Returns:
            str: Status message
        """
        return "Rocket Lead Gen API is running."
    
    def test_connection(self) -> Tuple[Response, int]:
        """Simple endpoint to test frontend to backend communication.
        
        Returns:
            tuple: JSON response with timestamp and HTTP status code
        """
        timestamp = datetime.datetime.now().isoformat()
        logging.info(f"Test connection endpoint called at {timestamp}")
        
        response = jsonify({
            "status": "ok",
            "message": "Backend is reachable",
            "timestamp": timestamp
        })
        
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        
        return response, 200
    
    def generate_token(self) -> Tuple[Response, int]:
        """Generate a Twilio Capability Token for client authentication.
        
        Query Parameters:
            agent_name (str): Name of the agent for which to generate token
            
        Returns:
            tuple: JSON response with token and HTTP status code
        """
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
            return jsonify({"token": token.decode('utf-8') if isinstance(token, bytes) else token}), 200
        except Exception as e:
            logging.error(f"Error generating token: {e}")
            return jsonify({"error": str(e)}), 500
    
    def handle_call(self) -> Response:
        """Handle incoming calls and direct them to available agents.
        
        Returns:
            Response: TwiML response for Twilio
        """
        try:
            response = VoiceResponse()
            caller = request.form.get("From", "Unknown")
            call_sid = request.form.get("CallSid", "Unknown")
            
            logging.info(f"Incoming call from: {caller} with SID: {call_sid}")
            
            # Store call information
            active_calls[call_sid] = {
                "call_sid": call_sid,
                "caller": caller,
                "status": "ringing",
                "timestamp": request.form.get("Timestamp", "")
            }
            
            # Log the active calls for debugging
            logging.info(f"Active calls after adding: {json.dumps(active_calls)}")
            
            # Add a welcome message and wait for an agent to pick up
            response.say("Thank you for calling Rocket Lead Gen. Please hold while we connect you with an agent.")
            response.pause(length=2)
            
            # Hold music
            response.play("https://demo.twilio.com/docs/classic.mp3")
            
            logging.info("Successfully generated TwiML for the call.")
            return Response(str(response), content_type="application/xml")
        except Exception as e:
            logging.error(f"Error handling call: {e}")
            response = VoiceResponse()
            response.say("An error occurred while processing your call. Please try again later.")
            return Response(str(response), content_type="application/xml")
    
    def call_status(self) -> Response:
        """Handle call status callbacks from Twilio.
        
        Returns:
            Response: Empty response or TwiML
        """
        call_sid = request.form.get("CallSid")
        call_status = request.form.get("CallStatus")
        logging.info(f"Call status update for SID {call_sid}: {call_status}")
        
        # Update call status in our storage
        if call_sid in active_calls:
            active_calls[call_sid]["status"] = call_status
            logging.info(f"Updated call {call_sid} status to {call_status}")
            
            # Remove completed/failed calls from active calls list
            if call_status in ["completed", "failed", "busy", "no-answer", "canceled"]:
                active_calls.pop(call_sid, None)
                logging.info(f"Removed call {call_sid} from active calls due to status {call_status}")
        
        # Log current active calls
        logging.info(f"Active calls after status update: {json.dumps(active_calls)}")
        
        return Response("", content_type="application/xml")
    
    def get_current_calls(self) -> Tuple[Response, int]:
        """Get a list of current active calls for display in the UI.
        
        Returns:
            tuple: JSON response with calls data and HTTP status code
        """
        # Convert active_calls dictionary to a list
        calls_list = list(active_calls.values())
        logging.info(f"Current calls request - Returning {len(calls_list)} active calls: {json.dumps(calls_list)}")
        
        # Create the response with proper CORS headers
        response = jsonify({"calls": calls_list})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        
        return response, 200
    
    def answer_call(self) -> Tuple[Response, int]:
        """Allow an agent to answer a specific call.
        
        Expected JSON body:
            {
                "call_sid": "CA123456789",
                "agent_name": "Agent1"
            }
            
        Returns:
            tuple: JSON response with result and HTTP status code
        """
        data = request.get_json()
        logging.info(f"Answer call request with data: {json.dumps(data)}")
        
        if not data or "call_sid" not in data or "agent_name" not in data:
            logging.error("Missing required parameters in answer call request")
            return jsonify({"error": "Missing required parameters"}), 400
            
        call_sid = data["call_sid"]
        agent_name = data["agent_name"]
        
        logging.info(f"Agent {agent_name} is answering call {call_sid}")
        
        # Make sure the call exists and is still ringing
        if call_sid not in active_calls:
            logging.error(f"Call {call_sid} not found in active calls")
            return jsonify({
                "success": False,
                "error": "Call not found"
            }), 404
            
        if active_calls[call_sid]["status"] != "ringing":
            logging.error(f"Call {call_sid} is no longer ringing (status: {active_calls[call_sid]['status']})")
            return jsonify({
                "success": False,
                "error": "Call no longer ringing"
            }), 400
        
        try:
            # In a real implementation, we would use Twilio API to redirect the call
            # For demo purposes, we'll just update our local state
            active_calls[call_sid]["status"] = "in-progress"
            active_calls[call_sid]["agent"] = agent_name
            
            # If you have Twilio client set up:
            if self.twilio_client:
                # Update the call to connect to the agent
                # This is a simplified example - actual implementation may vary
                self.twilio_client.calls(call_sid).update(
                    twiml=f'<Response><Dial><Client>{agent_name}</Client></Dial></Response>'
                )
                logging.info(f"Updated Twilio call {call_sid} to connect to agent {agent_name}")
            
            response = jsonify({
                "success": True,
                "message": f"Call {call_sid} connected to {agent_name}"
            })
            
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
            
            return response, 200
        except Exception as e:
            logging.error(f"Error answering call: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    def end_call(self) -> Tuple[Response, int]:
        """Allow an agent to end a specific call.
        
        Expected JSON body:
            {
                "call_sid": "CA123456789"
            }
            
        Returns:
            tuple: JSON response with result and HTTP status code
        """
        data = request.get_json()
        logging.info(f"End call request with data: {json.dumps(data)}")
        
        if not data or "call_sid" not in data:
            logging.error("Missing call_sid parameter in end call request")
            return jsonify({"error": "Missing call_sid parameter"}), 400
            
        call_sid = data["call_sid"]
        logging.info(f"Ending call {call_sid}")
        
        if call_sid not in active_calls:
            logging.error(f"Call {call_sid} not found in active calls")
            return jsonify({
                "success": False,
                "error": "Call not found"
            }), 404
        
        try:
            # In a real implementation, we would use Twilio API to end the call
            if self.twilio_client:
                self.twilio_client.calls(call_sid).update(status="completed")
                logging.info(f"Updated Twilio call {call_sid} status to completed")
            
            # Remove from our active calls
            active_calls.pop(call_sid, None)
            logging.info(f"Removed call {call_sid} from active calls")
            
            response = jsonify({
                "success": True,
                "message": f"Call {call_sid} ended"
            })
            
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
            
            return response, 200
        except Exception as e:
            logging.error(f"Error ending call: {e}")
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500
    
    def run(self, host: str = '0.0.0.0', port: int = 10000) -> None:
        """Run the Flask application.
        
        Args:
            host (str): Host address to bind the server
            port (int): Port number to use
        """
        self.app.run(host=host, port=port)


# Application entry point
if __name__ == '__main__':
    api = RocketLeadGenAPI()
    api.run()
