"""
WebRTC ICE Candidate Handler

Handles ICE candidate exchange for NAT traversal.
Receives ICE candidates from browser and adds them to the peer connection.
"""

from aiortc.sdp import candidate_from_sdp
from tools.logger import log_info, log_debug, log_error, log_warning
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
    BASE_MESSAGE,
    validate_contract_with_error_response,
)


NAME = "webrtc:ice"

MESSAGE_CONTRACT = {
    **BASE_MESSAGE,
    "session_id": StringType,
    "candidate": OptionalType(StringType),  # Can be null for end-of-candidates
    "sdp_mid": OptionalType(StringType),
    "sdp_mline_index": OptionalType(NumberType),
}


def init(client, session_manager):
    """
    Initialize the WebRTC ICE candidate handler.

    Args:
        client: Socket.IO client
        session_manager: WebRTCSessionManager instance
    """
    log_info(f"Registering topic: {NAME}")

    @client.on(NAME)
    async def handle_ice_candidate(message):
        """
        Handle incoming ICE candidate from browser.

        Adds the candidate to the peer connection for NAT traversal.
        """
        correlation_id = message.get("correlation_id")

        # Validate message
        is_valid, error_response = validate_contract_with_error_response(
            MESSAGE_CONTRACT, message
        )
        if not is_valid:
            error_response["action"] = NAME
            error_response["correlation_id"] = correlation_id
            return error_response

        session_id = message["session_id"]
        candidate_str = message.get("candidate")
        sdp_mid = message.get("sdp_mid")
        sdp_mline_index = message.get("sdp_mline_index")

        # Get peer connection for this session
        pc = session_manager.get_peer_connection(session_id)
        if not pc:
            log_warning(f"No peer connection found for session {session_id}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Session {session_id} not found",
                "session_id": session_id,
            }

        # Handle end-of-candidates signal (null candidate)
        if not candidate_str:
            log_debug(f"End of ICE candidates for session {session_id}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "session_id": session_id,
                "message": "End of candidates acknowledged",
            }

        try:
            # Parse the ICE candidate string using aiortc's parser
            candidate = candidate_from_sdp(candidate_str)

            # Set the sdpMid and sdpMLineIndex
            candidate.sdpMid = sdp_mid
            candidate.sdpMLineIndex = sdp_mline_index

            await pc.addIceCandidate(candidate)
            log_debug(f"Added ICE candidate for session {session_id}: {candidate.type} {candidate.ip}:{candidate.port}")

            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "session_id": session_id,
            }

        except Exception as e:
            log_error(f"Error adding ICE candidate for session {session_id}: {e}")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": str(e),
                "session_id": session_id,
            }
