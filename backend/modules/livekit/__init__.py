"""LiveKit integration module.

Exposes:
  * REST API for managing rooms and minting participant tokens.
  * An async ``LiveKitService`` that wraps the LiveKit server SDK.
  * An ``AudioTransport`` that connects to a room over WebRTC and
    publishes/subscribes raw audio frames.
"""
