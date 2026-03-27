"""
WebRTC Offer Handler

Handles incoming SDP offers from the browser client via the signaling server.
Creates peer connections and generates SDP answers.
"""

from aiortc import RTCSessionDescription
from tools.logger import log_info, log_debug, log_error, log_warning
from tools.contract_validation import (
    StringType,
    BASE_MESSAGE,
    validate_contract_with_error_response,
)
from ..types import SessionState
from ..data_channel import DataChannelHandler, DebugChannelHandler


NAME = "webrtc:offer"
ICE_TOPIC = "webrtc:ice"

MESSAGE_CONTRACT = {
    **BASE_MESSAGE,
    "session_id": StringType,
    "device_id": StringType,
    "sdp": StringType,
    "sdp_type": StringType,  # "offer"
}


def init(client, session_manager, client_registry, http_client,
         *, http_client_factory=None, debug_socket_factory=None,
         debug_session_manager=None):
    """
    Initialize the WebRTC offer handler.

    Args:
        client: Socket.IO client
        session_manager: WebRTCSessionManager instance
        client_registry: ClientRepo instance for device lookups
        http_client: HTTPClientRepo instance for command execution
        http_client_factory: Callable returning a new HTTPClientRepo (for debug sessions)
        debug_socket_factory: Callable returning a new DebugSocketRepo (for debug sessions)
        debug_session_manager: DebugSessionManager for debug session lifecycle
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
        log_debug(f"Available devices: {list(client_registry.list_clients().keys())}")

        # Verify device exists
        if not client_registry.contains(device_id):
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

            # Set up data channel handler (browser creates the channels)
            @pc.on("datachannel")
            def on_datachannel(channel):
                label = channel.label
                log_info(f"========== Data Channel Received ==========")
                log_info(f"Session: {session_id}")
                log_info(f"Channel label: {label}")
                log_info(f"Channel state: {channel.readyState}")

                if label == "data":
                    session_manager.set_data_channel(session_id, channel)
                    log_info(f"Creating DataChannelHandler for session {session_id}")
                    handler = DataChannelHandler(
                        channel, session_id, session_manager, client_registry, http_client,
                        debug_session_manager=debug_session_manager,
                    )
                    session_manager.set_channel_handler(session_id, handler)
                    log_info(f"DataChannelHandler created successfully")
                elif label == "debug":
                    session_manager.set_debug_channel(session_id, channel)
                    if debug_session_manager is None:
                        log_warning(f"Debug channel received for session {session_id} but "
                                    f"debug_session_manager is None, "
                                    f"skipping DebugChannelHandler creation")
                    else:
                        log_info(f"Creating DebugChannelHandler for session {session_id}")
                        handler = DebugChannelHandler(
                            channel, session_id, session_manager, device_id,
                            debug_session_manager=debug_session_manager,
                        )
                        session_manager.set_debug_channel_handler(session_id, handler)
                        log_info(f"DebugChannelHandler created successfully")
                else:
                    log_warning(f"Unknown data channel label '{label}' for session {session_id}, ignoring")

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
