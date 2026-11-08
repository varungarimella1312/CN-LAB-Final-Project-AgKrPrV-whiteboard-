"""Protocol framing and constants for the LAN Collaborative Whiteboard.

Computer Networks Lab - LAN Collaborative Whiteboard
Module: whiteboard.protocol

Why TCP was chosen over UDP:
-----------------------------
1. Reliability (No Lost Strokes):
   In a collaborative whiteboard, canvas operations (strokes, shapes, clears,
   and undos) represent discrete state mutations. If an operation packet is lost,
   the client and server canvases will permanently diverge. TCP guarantees reliable
   delivery through acknowledgments (ACKs) and automatic retransmissions. UDP
   provides best-effort delivery and drops packets silently under network congestion.

2. In-Order Delivery:
   Whiteboard operations must be applied in the exact sequence they occurred
   (e.g., drawing a stroke, then drawing over it, then clearing or undoing).
   TCP enforces strict in-order byte stream delivery using sequence numbers.
   With UDP, datagrams can arrive out of order, leading to visual corruption
   unless complex sequence reordering and retransmission buffers are implemented
   at the application layer.

3. Flow and Congestion Control:
   When multiple users draw concurrently, TCP regulates transmission rates
   using sliding windows and congestion control algorithms, preventing sender
   bursts from overflowing receiving socket buffers or saturating the LAN switch.

Why Length-Prefix Framing is Needed:
------------------------------------
TCP is fundamentally a byte-stream protocol (RFC 793). It has no built-in notion
of message boundaries or datagram frames. When an application calls `sendall()`,
the operating system's TCP stack may segment the payload across multiple MTU-sized
IP packets, or merge multiple short application messages into a single packet via
Nagle's algorithm (known as packet coalescing / 'sticky packets' and fragmentation).

Consequently, `sock.recv(1024)` might return:
- Only part of a single message (fragmentation)
- An exact message
- Multiple concatenated messages in one buffer (packet stickiness)

To delineate message boundaries over the stream, we implement length-prefix framing:
  +--------------------------------+---------------------------------------+
  |  Length Prefix (4 bytes)       |  JSON Payload (UTF-8 encoded bytes)   |
  |  Big-Endian unsigned int ('>I')|  {"t": "draw", ...}                   |
  +--------------------------------+---------------------------------------+

1. Sender transmits a fixed-size 4-byte header in network byte order (big-endian),
   encoding the exact byte count N of the following payload.
2. Sender transmits the N payload bytes.
3. Receiver reads exactly 4 bytes to determine N.
4. Receiver loops reading until exactly N payload bytes have been collected.
5. Receiver decodes the UTF-8 JSON payload.
"""

from __future__ import annotations

import json
import struct
import socket
from typing import Any, Dict

# --- Network & Application Constants ---
PORT_DEFAULT: int = 5050
MAX_MSG: int = 4 * 1024 * 1024  # 4 MiB maximum payload size
CANVAS_W: int = 1200
CANVAS_H: int = 700

# Network byte order (big-endian) 4-byte unsigned integer
HEADER_FORMAT: str = ">I"
HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 4 bytes


class ProtocolError(Exception):
    """Raised when protocol framing, size constraints, or message schema validation fails."""
    pass


def encode(obj: Any) -> bytes:
    """Encodes a Python object into a length-prefixed UTF-8 JSON byte sequence.

    Uses compact JSON separators to minimize network bandwidth over the LAN.

    Args:
        obj: The Python object (typically a dict) to encode.

    Returns:
        bytes: 4-byte big-endian length prefix followed by UTF-8 encoded JSON bytes.

    Raises:
        ProtocolError: If JSON serialization fails or the resulting payload exceeds MAX_MSG.
    """
    try:
        raw_json = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"Failed to JSON-encode object: {exc}") from exc

    length = len(raw_json)
    if length > MAX_MSG:
        raise ProtocolError(f"Message size {length} bytes exceeds MAX_MSG limit ({MAX_MSG} bytes)")

    header = struct.pack(HEADER_FORMAT, length)
    return header + raw_json


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Reads exactly n bytes from a blocking TCP socket.

    Because TCP can return fewer bytes than requested in a single recv() call,
    this function accumulates chunks in a loop until all n bytes are received.

    Args:
        sock: Connected TCP socket.
        n: Exact number of bytes required.

    Returns:
        bytes: Buffer containing exactly n bytes.

    Raises:
        ConnectionError: If the remote peer closes the connection before all n bytes arrive.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(
                f"Connection closed by peer prematurely: received {len(buf)} of {n} expected bytes"
            )
        buf.extend(chunk)
    return bytes(buf)


def recv_msg(sock: socket.socket) -> Dict[str, Any]:
    """Receives and decodes the next length-prefixed JSON message from a socket.

    Reads the 4-byte header, verifies size constraints (0 < length <= MAX_MSG),
    retrieves the exact payload, and verifies that the decoded JSON is an object
    containing the required message type key 't'.

    Args:
        sock: Connected TCP socket.

    Returns:
        dict: The decoded JSON message dictionary with key 't'.

    Raises:
        ConnectionError: If the connection breaks during read.
        ProtocolError: If length prefix is out of bounds (<= 0 or > MAX_MSG),
                       JSON decoding fails, or the payload is not a dict with key 't'.
    """
    # 1. Read the 4-byte length header
    header = recv_exact(sock, HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)

    # 2. Validate payload length constraints
    if not (0 < length <= MAX_MSG):
        raise ProtocolError(
            f"Message length {length} bytes exceeds MAX_MSG ({MAX_MSG}) or is non-positive"
        )

    # 3. Read the exact payload body
    body = recv_exact(sock, length)

    # 4. Decode UTF-8 JSON
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"Failed to decode JSON payload: {exc}") from exc

    # 5. Schema check: must be a dict containing key 't'
    if not isinstance(data, dict):
        raise ProtocolError(f"Expected JSON object (dict), received {type(data).__name__}")
    if "t" not in data:
        raise ProtocolError("Invalid protocol message: missing required 't' type key")

    return data


def send_msg(sock: socket.socket, obj: Any) -> None:
    """Encodes and transmits a length-prefixed message over a socket.

    Args:
        sock: Connected TCP socket.
        obj: Python object (must be JSON-serializable) to send.

    Raises:
        ProtocolError: If encoding fails or exceeds MAX_MSG.
        OSError: If socket transmission fails.
    """
    sock.sendall(encode(obj))
