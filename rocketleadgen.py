import os
import logging
from typing import Dict, Union, Tuple, Any, Optional
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from twilio.jwt.client import ClientCapabilityToken
from twilio.twiml.voice_response import VoiceResponse

# Configure logging
logging.basicConfig(level=logging.INFO)

# Environment variables for Twilio
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWIML_APP_SID = "AP3e887681a7ea924ad732e46b00cd04c4"  # TwiML Application SID

class RocketLeadGenAPI:
    """Lead generation system API for life insurance agents with Twilio integration."""
    
    def __init__(self) -> None:
        """Initialize the Flask application with CORS support."""
        self.app = Flask(__name__)
        CORS(self.app)
        self._register_routes()
    
    def _register_routes(self) -> None:
        """Register all API endpoints."""
        self.app.route('/', methods=['GET'])(self.index)
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
            
            # Store call information for agents to see (in a real system, use a database)
            # For now we'll use a simple response that can be consumed by your UI
            
            # Add a welcome message and wait for an agent to pick up
            response.say("Thank you for calling Rocket Lead Gen. Please hold while we connect you with an agent.")
            response.pause(length=2)
            # You can add hold music here
            # response.play("https://your-music-url.mp3")
            
            # For now, we'll connect to "Agent1" but in a real system, 
            # you'd want to implement logic to find available agents
            dial = response.dial(callerId=caller)
            dial.client("Agent1")
            
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
        
        # In a real application, you'd update a database with this information
        return Response("", content_type="application/xml")
    
    def get_current_calls(self) -> Tuple[Response, int]:
        """Get a list of current active calls for display in the UI.
        
        Returns:
            tuple: JSON response with calls data and HTTP status code
        """
        # In a real application, you'd retrieve this from a database
        # For demo purposes, return mock data
        mock_calls = [
            {
                "call_sid": "CA123456789",
                "caller": "+1234567890",
                "status": "ringing",
                "timestamp": "2023-06-01T10:30:00Z"
            }
        ]
        return jsonify({"calls": mock_calls}), 200
    
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
        if not data or "call_sid" not in data or "agent_name" not in data:
            return jsonify({"error": "Missing required parameters"}), 400
            
        call_sid = data["call_sid"]
        agent_name = data["agent_name"]
        
        logging.info(f"Agent {agent_name} is answering call {call_sid}")
        
        # In a real application, you'd use Twilio's API to redirect the call to this agent
        # For now, return a success response
        return jsonify({
            "success": True,
            "message": f"Call {call_sid} connected to {agent_name}"
        }), 200
    
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
        if not data or "call_sid" not in data:
            return jsonify({"error": "Missing call_sid parameter"}), 400
            
        call_sid = data["call_sid"]
        logging.info(f"Ending call {call_sid}")
        
        # In a real application, you'd use Twilio's API to end the call
        # For now, return a success response
        return jsonify({
            "success": True,
            "message": f"Call {call_sid} ended"
        }), 200
    
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
