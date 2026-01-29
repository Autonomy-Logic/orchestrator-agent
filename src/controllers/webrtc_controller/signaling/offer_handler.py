"""
WebRTC Offer Handler

Handles incoming SDP offers from the browser client via the signaling server.
Creates peer connections and generates SDP answers.
"""

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from tools.logger import log_info, log_debug, log_error, log_warning
from tools.contract_validation import (
    StringType,
    NumberType,
    OptionalType,
    BASE_MESSAGE,
    validate_contract_with_error_response,
)
from use_cases.docker_manager import CLIENTS
from .. import SessionState


NAME = "webrtc:offer"
ANSWER_TOPIC = "webrtc:answer"
ICE_TOPIC = "webrtc:ice"

MESSAGE_CONTRACT = {
    **BASE_MESSAGE,
    "session_id": StringType,
    "device_id": StringType,
    "sdp": StringType,
    "sdp_type": StringType,  # "offer"
}


def init(client, session_manager):
    """
    Initialize the WebRTC offer handler.

    Args:
        client: Socket.IO client
        session_manager: WebRTCSessionManager instance
    """
    log_info(f"Registering topic: {NAME}")

    @client.on(NAME)
    async def handle_offer(message):
        """
        Handle incoming WebRTC offer.

        Flow:
        1. Validate message and device existence
        2. Create new RTCPeerConnection
        3. Set up ICE candidate handler to emit candidates back
        4. Set remote description (offer)
        5. Create and set local description (answer)
        6. Return answer SDP
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
        device_id = message["device_id"]
        sdp = message["sdp"]
        sdp_type = message.get("sdp_type", "offer")

        log_info(f"========== WebRTC Offer Received ==========")
        log_info(f"Session ID: {session_id}")
        log_info(f"Device ID: {device_id}")
        log_info(f"SDP type: {sdp_type}")
        log_info(f"SDP length: {len(sdp)} chars")
        log_debug(f"Available devices: {list(CLIENTS.keys())}")

        # Verify device exists
        if device_id not in CLIENTS:
            log_warning(f"Device {device_id} not found for WebRTC session")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": f"Device {device_id} not found",
                "session_id": session_id,
            }

        try:
            # Create peer connection for this session
            log_info(f"Creating peer connection for session {session_id}")
            pc = await session_manager.create_session(session_id, device_id)
            log_info(f"Peer connection created successfully")
            session_manager.update_session_state(session_id, SessionState.CONNECTING)

            # Set up ICE candidate handler - emit local candidates to browser
            @pc.on("icecandidate")
            async def on_ice_candidate(candidate):
                if candidate:
                    log_debug(f"Emitting ICE candidate for session {session_id}")
                    await client.emit(ICE_TOPIC, {
                        "session_id": session_id,
                        "candidate": candidate.candidate,
                        "sdp_mid": candidate.sdpMid,
                        "sdp_mline_index": candidate.sdpMLineIndex,
                    })

            # Set up connection state handler
            @pc.on("connectionstatechange")
            async def on_connection_state_change():
                state = pc.connectionState
                log_info(f"Session {session_id} connection state: {state}")
                session_manager.update_connection_state(session_id, state)

                if state == "failed":
                    log_warning(f"Session {session_id} connection failed")
                    await session_manager.close_session(session_id, reason="connection_failed")
                elif state == "closed":
                    await session_manager.close_session(session_id, reason="connection_closed")

            # Set up ICE connection state handler
            @pc.on("iceconnectionstatechange")
            async def on_ice_connection_state_change():
                ice_state = pc.iceConnectionState
                log_debug(f"Session {session_id} ICE state: {ice_state}")
                session_manager.update_connection_state(
                    session_id,
                    pc.connectionState,
                    ice_state
                )

            # Set up data channel handler (browser creates the channel)
            @pc.on("datachannel")
            def on_datachannel(channel):
                log_info(f"========== Data Channel Received ==========")
                log_info(f"Session: {session_id}")
                log_info(f"Channel label: {channel.label}")
                log_info(f"Channel state: {channel.readyState}")
                session_manager.set_data_channel(session_id, channel)

                # Import here to avoid circular imports
                from ..data_channel import KeepaliveChannel
                log_info(f"Creating KeepaliveChannel for session {session_id}")
                keepalive = KeepaliveChannel(channel, session_id, session_manager)
                session_manager.set_keepalive_channel(session_id, keepalive)
                log_info(f"KeepaliveChannel created successfully")

            # Set remote description (the offer from browser)
            log_info(f"Setting remote description (browser's offer)")
            offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
            await pc.setRemoteDescription(offer)
            log_info(f"Remote description set successfully")
            log_debug(f"Signaling state after setRemoteDescription: {pc.signalingState}")

            # Create answer
            log_info(f"Creating SDP answer")
            answer = await pc.createAnswer()
            log_info(f"Answer created, setting local description")
            await pc.setLocalDescription(answer)
            log_info(f"Local description set")
            log_debug(f"Signaling state after setLocalDescription: {pc.signalingState}")
            log_debug(f"Answer SDP length: {len(pc.localDescription.sdp)} chars")

            log_info(f"========== WebRTC Session Ready ==========")
            log_info(f"Session {session_id} established, sending answer to browser")

            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "success",
                "session_id": session_id,
                "sdp": pc.localDescription.sdp,
                "sdp_type": pc.localDescription.type,
            }

        except Exception as e:
            log_error(f"Error handling WebRTC offer: {e}")
            # Clean up on error
            await session_manager.close_session(session_id, reason="error")
            return {
                "action": NAME,
                "correlation_id": correlation_id,
                "status": "error",
                "error": str(e),
                "session_id": session_id,
            }
