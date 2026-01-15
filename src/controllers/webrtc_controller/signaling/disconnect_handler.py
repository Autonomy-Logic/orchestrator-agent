"""
WebRTC Disconnect Handler

Handles session disconnection requests from browser or cloud.
Cleans up peer connections and PTY sessions.
"""

from tools.logger import log_info, log_debug, log_error, log_warning
from tools.contract_validation import (
    StringType,
    OptionalType,
    BASE_MESSAGE,
    validate_contract_with_error_response,
)


NAME = "webrtc:disconnect"

MESSAGE_CONTRACT = {
    **BASE_MESSAGE,
    "session_id": StringType,
    "reason": OptionalType(StringType),
}


def init(client, session_manager):
    """
    Initialize the WebRTC disconnect handler.

    Args:
        client: Socket.IO client
        session_manager: WebRTCSessionManager instance
    """
    log_info(f"Registering topic: {NAME}")

    @client.on(NAME)
    async def handle_disconnect(message):
        """
        Handle WebRTC session disconnect request.

        Closes peer connection and cleans up associated resources.
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
        reason = message.get("reason", "client requested")

        log_info(f"WebRTC disconnect request for session {session_id}: {reason}")

        # Close the session
        closed = await session_manager.close_session(session_id)

        if closed:
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "session_id": session_id,
                "message": "Session closed",
            }
        else:
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "warning",
                "session_id": session_id,
                "message": "Session not found (may already be closed)",
            }
