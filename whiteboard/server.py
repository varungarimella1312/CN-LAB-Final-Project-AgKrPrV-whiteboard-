"""Multi-user collaborative whiteboard TCP server.

Computer Networks Lab - LAN Collaborative Whiteboard
Module: whiteboard.server

Role:
-----
This module implements the central, authoritative TCP server for the LAN
Collaborative Whiteboard. It coordinates real-time state synchronization,
user roles, drawing operations, and global ordering across all connected clients.

Key Architectural Responsibilities:
-----------------------------------
1. Authoritative Sequencing:
   Maintains a strictly monotonic sequence number (`seq`) and operation log (`log`)
   per room. Every state-altering operation is committed under a room-level `RLock`
   and broadcast in identical order to all online room participants.
2. Threading & Non-blocking I/O:
   - One background accept thread accepting new TCP connections.
   - For every connected client:
     - One reader thread (the socket handler) reading framed incoming messages.
     - One dedicated writer thread draining a bounded `queue.Queue(maxsize=5000)`.
   - Sends never block the server: `queue.put_nowait()` is used. If a client's
     queue overflows, that slow client is dropped to protect overall server health.
3. TCP_NODELAY:
   Enables TCP_NODELAY on all accepted client sockets, disabling Nagle's algorithm
   so interactive drawing strokes and cursor updates are delivered with minimal latency.
4. Deduplication / Idempotence:
   Tracks `Room.seen` mapping `stroke_id -> seq`. Re-sent strokes (e.g., across
   network reconnects) are acknowledged with their original sequence number without
   re-applying or re-broadcasting.
5. Per-User Undo/Redo Architecture:
   - Undo/redo affect ONLY the caller's own actions.
   - Operations are represented as sequenced `vis` operations (`hide: [...]`, `show: [...]`).
   - Stacks store `("s", stroke_id)` or `("c", [ids])`. If a stack entry would produce
     no net state change (e.g. stroke already hidden), it is skipped until an actionable
     mutation is found.
   - Canvas `clear` is restricted to the host; it hides all visible strokes in one
     `vis` op and pushes `("c", ids)` onto the host's undo stack, permitting host undo.
6. Heartbeat, Lifecycle & Reconnection:
   - Fast keepalive with ping/pong echoing timestamps.
   - Inactive clients exceeding `--timeout` seconds are reaped and marked offline.
   - Disconnected members are preserved for `--grace` seconds to allow reconnection
     using secret tokens; reconnecting with `last_seq` receives delta operations.
   - Members purged after `--grace` trigger automatic host re-election if the host left.
7. Persistence & Version History:
   - Atomic board saving (`boards/<room>/<YYYYMMDD-HHMMSS>_<label>.json`) via `.tmp` rename.
   - Path-traversal proof loading via `os.path.basename` and room-folder membership checks.
   - Background autosaving every 30 seconds when dirty and on room exit.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import queue
import re
import secrets
import socket
import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple

# Support running directly (`python server.py`) or as a module (`python -m whiteboard.server`)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from whiteboard.protocol import (
        CANVAS_H,
        CANVAS_W,
        PORT_DEFAULT,
        ProtocolError,
        recv_msg,
        send_msg,
    )
except ImportError:
    from protocol import (  # type: ignore
        CANVAS_H,
        CANVAS_W,
        PORT_DEFAULT,
        ProtocolError,
        recv_msg,
        send_msg,
    )

# --- Configuration & Validation Constants ---
MAX_MEMBERS_PER_ROOM: int = 30
CLIENT_QUEUE_MAXSIZE: int = 5000
HELLO_TIMEOUT_SECONDS: float = 10.0
MAX_CHAT_HISTORY: int = 500
WELCOME_CHAT_HISTORY: int = 200
MAX_MSG_RATE_PER_SEC: int = 400

RE_ROOM_CODE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RE_USERNAME = re.compile(r"^[A-Za-z0-9 ._-]{1,24}$")
RE_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RE_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
VALID_TOOLS = frozenset({"pen", "eraser", "line", "rect", "oval", "text"})

# Palette of 20 distinct, high-contrast colors assigned to joining members
MEMBER_PALETTE: list[str] = [
    "#E6194B", "#3CB44B", "#FFE119", "#4363D8", "#F58231",
    "#911EB4", "#46F0F0", "#F032E6", "#BCF60C", "#FABEBE",
    "#008080", "#E6BEFF", "#9A6324", "#FFFAC8", "#800000",
    "#AAFFC3", "#808000", "#FFD8B1", "#000075", "#808080",
]


def get_base_dir() -> str:
    """Returns the persistent base directory of the server executable or script.

    When packaged with PyInstaller (sys.frozen is True), returns the directory
    containing the standalone executable so the boards/ directory is saved
    permanently next to the binary, rather than inside a transient temp directory.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_lan_ip() -> str:
    """Finds the primary local LAN IP address of this machine.

    Uses a UDP socket connected to an unreachable LAN/WAN IP (10.255.255.255).
    Because UDP is connectionless, this triggers no network packets and requires
    no internet access; the OS kernel simply resolves which local network
    interface routing table entry would handle traffic for that subnet.

    Returns:
        str: Outbound IPv4 address (e.g., '192.168.1.50'), or '127.0.0.1' on failure.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def validate_stroke_dict(s: Any) -> Tuple[bool, str]:
    """Validates the structure, coordinates, and properties of a stroke object.

    Enforces:
    - tool in {'pen', 'eraser', 'line', 'rect', 'oval', 'text'}
    - color matches #rrggbb
    - width is numeric between 1 and 60
    - pts is a list of 1 to 8000 finite [x,y] coordinates with |v| < 10000
    - shapes ('line', 'rect', 'oval') keep only first and last point
    - text tool requires 'text' key with 1-300 characters

    Args:
        s: Raw stroke dictionary.

    Returns:
        tuple[bool, str]: (is_valid, error_description)
    """
    if not isinstance(s, dict):
        return False, "Stroke payload must be a JSON object"

    tool = s.get("tool")
    if tool not in VALID_TOOLS:
        return False, f"Invalid tool '{tool}'; must be one of {sorted(VALID_TOOLS)}"

    color = s.get("color")
    if not isinstance(color, str) or not RE_HEX_COLOR.match(color):
        return False, f"Invalid color '{color}'; must be a valid #rrggbb hex string"

    width = s.get("width")
    if not isinstance(width, (int, float)) or not (1 <= width <= 60):
        return False, f"Invalid width {width}; must be between 1 and 60"

    pts = s.get("pts")
    if not isinstance(pts, list) or not (1 <= len(pts) <= 8000):
        return False, "Points 'pts' must be a list containing 1 to 8000 points"

    for idx, pt in enumerate(pts):
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            return False, f"Point at index {idx} must be a 2-element [x, y] list"
        x, y = pt
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            return False, f"Coordinates at index {idx} must be numeric"
        if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
            return False, f"Coordinates at index {idx} must be finite numbers"
        if abs(x) >= 10000 or abs(y) >= 10000:
            return False, f"Coordinate at index {idx} out of range (|v| must be < 10000)"

    # Shapes retain only the start and end coordinates
    if tool in {"line", "rect", "oval"}:
        if len(pts) < 2:
            return False, f"Shape tool '{tool}' requires at least 2 points (start and end)"
        s["pts"] = [pts[0], pts[-1]]

    if tool == "text":
        text = s.get("text")
        if not isinstance(text, str) or not (1 <= len(text) <= 300):
            return False, "Text tool requires 'text' string of 1 to 300 characters"
        bg = s.get("bg")
        if bg is not None:
            if not isinstance(bg, str) or not RE_HEX_COLOR.match(bg):
                return False, f"Invalid sticky note background color '{bg}'; must be #rrggbb hex"

    return True, ""


class Member:
    """Represents a registered user within a whiteboard room."""

    def __init__(
        self,
        user: str,
        role: str,
        color: str,
        token: str,
        session: Optional[ClientSession] = None,
    ) -> None:
        self.user = user
        self.role = role  # "host", "editor", or "viewer"
        self.color = color
        self.token = token
        self.session = session
        self.online = True
        self.joined_at: float = time.time()
        self.offline_since: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Returns public profile dictionary for broadcast to peers."""
        return {
            "user": self.user,
            "role": self.role,
            "color": self.color,
            "online": self.online,
        }


class Room:
    """Thread-safe authoritative room replica.

    Protected by an RLock. All state mutations and broadcasts must hold this lock.
    """

    def __init__(
        self,
        name: str,
        salt: str,
        password_hash: str,
        boards_dir: str = "boards",
    ) -> None:
        self.lock = threading.RLock()
        self.name = name
        self.salt = salt
        self.password_hash = password_hash
        self.boards_dir = boards_dir
        self.host_user: str = ""
        self.members: Dict[str, Member] = {}
        self.seq: int = 0
        self.log: List[Dict[str, Any]] = []
        self.strokes: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.seen: Dict[str, int] = {}  # stroke_id -> committed sequence number (idempotence)
        self.chat_history: List[Dict[str, Any]] = []
        self.canvas: Dict[str, int] = {"w": CANVAS_W, "h": CANVAS_H}
        self.presentation_mode: bool = False

        # Per-user undo/redo history stacks: user -> list of ("s", sid) or ("c", [sids])
        self.undo_stacks: Dict[str, List[Tuple[str, Any]]] = {}
        self.redo_stacks: Dict[str, List[Tuple[str, Any]]] = {}

        # Lifecycle & Persistence state
        self.dirty = False
        self.last_autosave: float = time.time()
        self.empty_since: Optional[float] = None
        self.room_dir = os.path.join(boards_dir, name)

    def allocate_color(self) -> str:
        """Assigns an unused palette color, or wraps around if palette exhausted."""
        used_colors = {m.color for m in self.members.values()}
        for color in MEMBER_PALETTE:
            if color not in used_colors:
                return color
        return MEMBER_PALETTE[len(self.members) % len(MEMBER_PALETTE)]

    def commit(self, op: Dict[str, Any]) -> None:
        """Applies a state-altering operation under lock, assigns sequence number, and broadcasts.

        Args:
            op: Operation dictionary with at least 'k' (kind) and 'u' (author).
        """
        with self.lock:
            self.seq += 1
            op["seq"] = self.seq
            self.log.append(op)
            self.dirty = True

            k = op.get("k")
            if k == "stroke":
                stroke_dict = dict(op["s"])
                stroke_dict.setdefault("h", False)
                stroke_dict.setdefault("u", op.get("u", ""))
                stroke_dict.setdefault("id", op.get("id", ""))
                sid = op["id"]
                self.strokes[sid] = stroke_dict
                self.seen[sid] = self.seq
            elif k == "vis":
                for sid in op.get("hide", []):
                    if sid in self.strokes:
                        self.strokes[sid]["h"] = True
                for sid in op.get("show", []):
                    if sid in self.strokes:
                        self.strokes[sid]["h"] = False
            elif k == "reset":
                if "strokes" in op:
                    # Replace canvas state from version restore
                    self.strokes = OrderedDict(
                        (s.get("id", f"s_{idx}"), s)
                        for idx, s in enumerate(op["strokes"])
                    )
                else:
                    self.strokes.clear()
                self.undo_stacks.clear()
                self.redo_stacks.clear()

            # Broadcast sequenced operation to ALL online room participants
            broadcast_msg = {"t": "op", **op}
            self.broadcast(broadcast_msg)

    def broadcast(
        self, message: Dict[str, Any], exclude_user: Optional[str] = None
    ) -> None:
        """Broadcasts a message to all online members.

        Must be called while holding self.lock or will acquire it.

        Args:
            message: The message dictionary to transmit.
            exclude_user: Optional username to skip (e.g. For echo suppression).
        """
        with self.lock:
            for username, member in self.members.items():
                if exclude_user is not None and username == exclude_user:
                    continue
                if member.online and member.session is not None:
                    member.session.send_msg(message)

    def autosave(self) -> None:
        """Atomically saves room state to autosave.json in the room directory."""
        with self.lock:
            if not self.dirty:
                return
            os.makedirs(self.room_dir, exist_ok=True)
            filepath = os.path.join(self.room_dir, "autosave.json")
            tmppath = filepath + ".tmp"
            data = {
                "name": self.name,
                "salt": self.salt,
                "password_hash": self.password_hash,
                "host_user": self.host_user,
                "seq": self.seq,
                "log": self.log,
                "strokes": list(self.strokes.values()),
                "chat_history": self.chat_history,
                "canvas": self.canvas,
            }
            try:
                with open(tmppath, "w", encoding="utf-8") as f:
                    json.dump(data, f, separators=(",", ":"))
                os.replace(tmppath, filepath)
                self.dirty = False
                self.last_autosave = time.time()
            except OSError as exc:
                logging.error(f"Autosave failed for room {self.name}: {exc}")
                if os.path.exists(tmppath):
                    try:
                        os.remove(tmppath)
                    except OSError:
                        pass


class ClientSession:
    """Handles network I/O and message dispatch for a single connected client socket."""

    def __init__(
        self,
        sock: socket.socket,
        addr: Tuple[str, int],
        server: WhiteboardServer,
    ) -> None:
        self.sock = sock
        self.addr = addr
        self.server = server
        self.send_queue: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue(
            maxsize=CLIENT_QUEUE_MAXSIZE
        )
        self.user: Optional[str] = None
        self.room: Optional[Room] = None
        self.is_alive = True
        self._closed = False
        self._graceful_closing = False
        self._close_lock = threading.Lock()

        # Inactivity & flood protection tracking
        self.last_activity: float = time.time()
        self._rate_count: int = 0
        self._rate_window_start: float = time.time()

        # Dedicated I/O threads
        self.writer_thread = threading.Thread(
            target=self._writer_loop, name=f"Writer-{addr}", daemon=True
        )
        self.reader_thread = threading.Thread(
            target=self._reader_loop, name=f"Reader-{addr}", daemon=True
        )

    def start(self) -> None:
        """Initializes socket flags and starts reader and writer threads."""
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.writer_thread.start()
        self.reader_thread.start()

    def send_msg(self, msg: Dict[str, Any]) -> bool:
        """Enqueues a message for the writer thread without blocking.

        If the send queue is full, disconnects the slow client to avoid bufferbloat.

        Args:
            msg: The message dictionary to send.

        Returns:
            bool: True if queued successfully, False if dropped or client closed.
        """
        if not self.is_alive:
            return False
        try:
            self.send_queue.put_nowait(msg)
            return True
        except queue.Full:
            self.close()
            return False

    def close_graceful_and_exit(self) -> None:
        """Sends a None sentinel to allow the writer thread to flush pending messages before closing."""
        if self._closed or self._graceful_closing:
            return
        self._graceful_closing = True
        self.is_alive = False
        try:
            self.send_queue.put(None, timeout=0.5)
        except Exception:
            self.close()

    def close(self) -> None:
        """Immediately closes socket and tears down connection."""
        with self._close_lock:
            self.is_alive = False
            if self._closed:
                return
            self._closed = True
            try:
                self.send_queue.put_nowait(None)
            except Exception:
                pass
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass

    def _writer_loop(self) -> None:
        """Drains send_queue and transmits framed messages over the socket."""
        try:
            while True:
                try:
                    msg = self.send_queue.get(timeout=0.5)
                except queue.Empty:
                    if not self.is_alive or self._closed:
                        break
                    continue
                if msg is None:
                    # Flush sentinel reached: all prior messages transmitted
                    break
                try:
                    send_msg(self.sock, msg)
                except Exception:
                    break
        finally:
            self.close()

    def _reader_loop(self) -> None:
        """Reads framed messages from client socket and dispatches to handler routines."""
        try:
            # 1. Enforce HELLO message within HELLO_TIMEOUT_SECONDS
            self.sock.settimeout(HELLO_TIMEOUT_SECONDS)
            try:
                hello_msg = recv_msg(self.sock)
            except socket.timeout:
                self.send_msg({
                    "t": "err",
                    "code": "timeout",
                    "msg": "Hello message timed out",
                    "fatal": True,
                })
                self.close_graceful_and_exit()
                return
            except (ConnectionError, ProtocolError, OSError):
                self.close()
                return

            if not hello_msg or hello_msg.get("t") != "hello":
                self.send_msg({
                    "t": "err",
                    "code": "bad_hello",
                    "msg": "First message must be 'hello'",
                    "fatal": True,
                })
                self.close_graceful_and_exit()
                return

            if not self._handle_hello(hello_msg):
                return

            # Clear socket-level timeout; the server-level reaper thread monitors inactivity
            self.sock.settimeout(None)

            # 2. Steady-state message dispatch loop
            while self.is_alive:
                try:
                    msg = recv_msg(self.sock)
                except (ConnectionError, ProtocolError, OSError):
                    break
                if not msg:
                    break

                self.last_activity = time.time()

                # Flood protection: drop messages exceeding 400 msgs/second
                now = time.time()
                if now - self._rate_window_start < 1.0:
                    self._rate_count += 1
                    if self._rate_count > MAX_MSG_RATE_PER_SEC:
                        continue
                else:
                    self._rate_window_start = now
                    self._rate_count = 1

                self._dispatch_message(msg)

        finally:
            self._handle_disconnect()
            if self._graceful_closing:
                self.writer_thread.join(timeout=1.0)
            self.close()

    def _handle_hello(self, msg: Dict[str, Any]) -> bool:
        """Validates join credentials, initializes room membership, and sends welcome."""
        startup_room = self.server.startup_room
        requested_room = msg.get("room", "")
        room_name = startup_room.name if startup_room else requested_room
        username = msg.get("user", "")
        password = str(msg.get("pw", ""))
        create = bool(msg.get("create", False))
        is_startup_host = startup_room is not None and bool(msg.get("is_host", False))
        token = msg.get("token")
        last_seq = msg.get("last_seq")

        if (
            startup_room
            and requested_room
            and requested_room != startup_room.name
        ):
            self.send_msg({
                "t": "err",
                "code": "no_room",
                "msg": "The requested room is not available on this server",
                "fatal": True,
            })
            self.close_graceful_and_exit()
            return False

        if not isinstance(room_name, str) or not RE_ROOM_CODE.match(room_name):
            self.send_msg({
                "t": "err",
                "code": "bad_room_code",
                "msg": "Room code must be 3-32 characters of A-Za-z0-9_-",
                "fatal": True,
            })
            self.close_graceful_and_exit()
            return False

        if not isinstance(username, str) or not RE_USERNAME.match(username):
            self.send_msg({
                "t": "err",
                "code": "bad_username",
                "msg": "Username must be 1-24 characters of letters, digits, spaces, or ._-",
                "fatal": True,
            })
            self.close_graceful_and_exit()
            return False

        room = (
            startup_room
            if startup_room is not None
            else self.server.get_or_create_room(room_name, password, create)
        )
        if isinstance(room, str):
            self.send_msg({
                "t": "err",
                "code": room,
                "msg": f"Join failed: {room}",
                "fatal": True,
            })
            self.close_graceful_and_exit()
            return False

        with room.lock:
            if is_startup_host:
                host_code = str(msg.get("host_code", ""))
                host_code_hash = hashlib.sha256(
                    (room.salt + host_code).encode("utf-8")
                ).hexdigest()
                if not hmac.compare_digest(
                    self.server.startup_host_code_hash or "", host_code_hash
                ):
                    self.send_msg({
                        "t": "err",
                        "code": "bad_host_code",
                        "msg": "Incorrect host code",
                        "fatal": True,
                    })
                    self.close_graceful_and_exit()
                    return False

            # Check room password
            salt = room.salt
            computed_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            if not hmac.compare_digest(room.password_hash, computed_hash):
                self.send_msg({
                    "t": "err",
                    "code": "bad_password",
                    "msg": "Incorrect room password",
                    "fatal": True,
                })
                self.close_graceful_and_exit()
                return False

            # Check username collision / reconnection
            if username in room.members:
                existing_member = room.members[username]
                if token and hmac.compare_digest(existing_member.token, str(token)):
                    # Legitimate reconnect using secret token
                    if existing_member.session and existing_member.session != self:
                        # Close stale half-open socket
                        existing_member.session.close()
                    existing_member.session = self
                    existing_member.online = True
                    existing_member.offline_since = None
                    member = existing_member
                else:
                    self.send_msg({
                        "t": "err",
                        "code": "name_taken",
                        "msg": f"Username '{username}' is already taken in this room",
                        "fatal": True,
                    })
                    self.close_graceful_and_exit()
                    return False
            else:
                if len(room.members) >= MAX_MEMBERS_PER_ROOM:
                    self.send_msg({
                        "t": "err",
                        "code": "room_full",
                        "msg": f"Room reached maximum capacity of {MAX_MEMBERS_PER_ROOM}",
                        "fatal": True,
                    })
                    self.close_graceful_and_exit()
                    return False

                if startup_room is not None:
                    role = "host" if is_startup_host else "editor"
                else:
                    role = "host" if not room.members else "editor"
                if role == "host":
                    room.host_user = username

                user_color = room.allocate_color()
                user_token = secrets.token_hex(16)
                member = Member(
                    user=username,
                    role=role,
                    color=user_color,
                    token=user_token,
                    session=self,
                )
                room.members[username] = member

            if is_startup_host:
                previous_host = room.members.get(room.host_user)
                if previous_host and previous_host.user != username:
                    previous_host.role = "editor"
                member.role = "host"
                room.host_user = username

            self.user = username
            self.room = room
            room.empty_since = None

            # Rejoin delta vs full snapshot calculation
            if (
                last_seq is not None
                and isinstance(last_seq, int)
                and 0 <= last_seq <= room.seq
            ):
                mode = "delta"
                welcome_data = {
                    "t": "welcome",
                    "room": room.name,
                    "seq": room.seq,
                    "host": room.host_user,
                    "you": {
                        "user": member.user,
                        "role": member.role,
                        "color": member.color,
                        "token": member.token,
                    },
                    "users": [m.to_dict() for m in room.members.values()],
                    "chat": room.chat_history[-WELCOME_CHAT_HISTORY:],
                    "canvas": room.canvas,
                    "present": room.presentation_mode,
                    "mode": mode,
                    "ops": room.log[last_seq:],
                }
            else:
                mode = "full"
                welcome_data = {
                    "t": "welcome",
                    "room": room.name,
                    "seq": room.seq,
                    "host": room.host_user,
                    "you": {
                        "user": member.user,
                        "role": member.role,
                        "color": member.color,
                        "token": member.token,
                    },
                    "users": [m.to_dict() for m in room.members.values()],
                    "chat": room.chat_history[-WELCOME_CHAT_HISTORY:],
                    "canvas": room.canvas,
                    "present": room.presentation_mode,
                    "mode": mode,
                    "strokes": list(room.strokes.values()),
                }

            self.send_msg(welcome_data)

            # Broadcast updated roster and notice
            room.broadcast({
                "t": "users",
                "users": [m.to_dict() for m in room.members.values()],
            })
            room.broadcast({
                "t": "notice",
                "msg": f"{username} joined the room",
            }, exclude_user=username)

        return True

    def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        """Dispatches an incoming protocol message to the appropriate handler."""
        msg_type = msg.get("t")
        if not self.room or not self.user:
            return

        with self.room.lock:
            member = self.room.members.get(self.user)
            if not member:
                return

            if msg_type == "stroke":
                self._handle_stroke(member, msg)
            elif msg_type == "part":
                self._handle_part(member, msg)
            elif msg_type == "cursor":
                self._handle_cursor(member, msg)
            elif msg_type == "undo":
                self._handle_undo(member)
            elif msg_type == "redo":
                self._handle_redo(member)
            elif msg_type == "clear":
                self._handle_clear(member)
            elif msg_type == "sync":
                self._handle_sync(msg)
            elif msg_type == "chat":
                self._handle_chat(member, msg)
            elif msg_type == "save":
                self._handle_save(member, msg)
            elif msg_type == "versions":
                self._handle_versions()
            elif msg_type == "load":
                self._handle_load(member, msg)
            elif msg_type == "setrole":
                self._handle_setrole(member, msg)
            elif msg_type == "present":
                self._handle_present(member, msg)
            elif msg_type == "kick":
                self._handle_kick(member, msg)
            elif msg_type == "ping":
                self.send_msg({"t": "pong", "ts": msg.get("ts")})
            elif msg_type == "leave":
                self.close()

    def _handle_stroke(self, member: Member, msg: Dict[str, Any]) -> None:
        """Processes and commits a finished drawing element with deduplication."""
        assert self.room is not None
        if member.role == "viewer" or (self.room.presentation_mode and member.role != "host"):
            self.send_msg({
                "t": "err",
                "code": "readonly",
                "msg": "Viewers cannot draw or edit" if member.role == "viewer" else "Room is in presentation mode (view-only)",
                "fatal": False,
            })
            return

        stroke_id = msg.get("id")
        stroke_obj = msg.get("s")
        if not stroke_id or not isinstance(stroke_id, str):
            self.send_msg({
                "t": "err",
                "code": "bad_op",
                "msg": "Missing or invalid stroke 'id'",
                "fatal": False,
            })
            return

        assert self.room is not None

        # 1. Deduplication / Idempotence check
        if stroke_id in self.room.seen:
            orig_seq = self.room.seen[stroke_id]
            self.send_msg({"t": "ack", "id": stroke_id, "seq": orig_seq})
            return

        # 2. Strict stroke validation
        is_valid, err_msg = validate_stroke_dict(stroke_obj)
        if not is_valid:
            self.send_msg({
                "t": "err",
                "code": "bad_op",
                "msg": err_msg,
                "fatal": False,
            })
            return

        op = {
            "k": "stroke",
            "id": stroke_id,
            "u": member.user,
            "s": stroke_obj,
        }
        self.room.commit(op)

        # Update user's undo stack and reset redo stack
        self.room.undo_stacks.setdefault(member.user, []).append(("s", stroke_id))
        self.room.redo_stacks.setdefault(member.user, []).clear()

        # Send acknowledgment to author
        self.send_msg({"t": "ack", "id": stroke_id, "seq": op["seq"]})

    def _handle_part(self, member: Member, msg: Dict[str, Any]) -> None:
        """Relays live in-progress stroke fragments without recording them in the room log."""
        assert self.room is not None
        if member.role == "viewer" or (self.room.presentation_mode and member.role != "host"):
            self.send_msg({
                "t": "err",
                "code": "readonly",
                "msg": "Viewers cannot draw",
                "fatal": False,
            })
            return

        assert self.room is not None
        self.room.broadcast(
            {
                "t": "part",
                "u": member.user,
                "sid": msg.get("sid"),
                "tool": msg.get("tool"),
                "color": msg.get("color"),
                "width": msg.get("width"),
                "mode": msg.get("mode"),
                "pts": msg.get("pts"),
            },
            exclude_user=member.user,
        )

    def _handle_cursor(self, member: Member, msg: Dict[str, Any]) -> None:
        """Relays ephemeral live cursor position to peers."""
        assert self.room is not None
        self.room.broadcast(
            {
                "t": "cursor",
                "u": member.user,
                "color": member.color,
                "x": msg.get("x"),
                "y": msg.get("y"),
            },
            exclude_user=member.user,
        )

    def _handle_undo(self, member: Member) -> None:
        """Performs per-user undo.

        Rule:
        - Undo affects ONLY the caller's own actions.
        - Pulls entries from user's undo stack: ('s', stroke_id) or ('c', [ids]).
        - Skips entries that would produce no net visual change (e.g. Stroke already hidden).
        - Emits a sequenced 'vis' op hiding the stroke or restoring clear.
        """
        assert self.room is not None
        if member.role == "viewer" or (self.room.presentation_mode and member.role != "host"):
            self.send_msg({
                "t": "err",
                "code": "readonly",
                "msg": "Viewers cannot undo",
                "fatal": False,
            })
            return

        assert self.room is not None
        u = member.user
        stack = self.room.undo_stacks.setdefault(u, [])
        redo_stack = self.room.redo_stacks.setdefault(u, [])

        while stack:
            entry_type, val = stack.pop()
            if entry_type == "s":
                stroke_id = val
                stroke = self.room.strokes.get(stroke_id)
                # Only hide if currently visible
                if stroke and not stroke.get("h", False):
                    op = {
                        "k": "vis",
                        "hide": [stroke_id],
                        "show": [],
                        "cause": "undo",
                        "u": u,
                    }
                    self.room.commit(op)
                    redo_stack.append(("s", stroke_id))
                    return
            elif entry_type == "c":
                # Undo of host clear: show the strokes that were hidden
                to_show = [
                    sid
                    for sid in val
                    if sid in self.room.strokes and self.room.strokes[sid].get("h", False)
                ]
                if to_show:
                    op = {
                        "k": "vis",
                        "hide": [],
                        "show": to_show,
                        "cause": "undo",
                        "u": u,
                    }
                    self.room.commit(op)
                    redo_stack.append(("c", to_show))
                    return

    def _handle_redo(self, member: Member) -> None:
        """Performs per-user redo.

        Rule:
        - Redo affects ONLY the caller's own undone actions.
        - Skips entries that would produce no net visual change.
        """
        assert self.room is not None
        if member.role == "viewer" or (self.room.presentation_mode and member.role != "host"):
            self.send_msg({
                "t": "err",
                "code": "readonly",
                "msg": "Viewers cannot redo",
                "fatal": False,
            })
            return

        assert self.room is not None
        u = member.user
        stack = self.room.undo_stacks.setdefault(u, [])
        redo_stack = self.room.redo_stacks.setdefault(u, [])

        while redo_stack:
            entry_type, val = redo_stack.pop()
            if entry_type == "s":
                stroke_id = val
                stroke = self.room.strokes.get(stroke_id)
                if stroke and stroke.get("h", False):
                    op = {
                        "k": "vis",
                        "hide": [],
                        "show": [stroke_id],
                        "cause": "redo",
                        "u": u,
                    }
                    self.room.commit(op)
                    stack.append(("s", stroke_id))
                    return
            elif entry_type == "c":
                # Redo of host clear: hide the strokes again
                to_hide = [
                    sid
                    for sid in val
                    if sid in self.room.strokes and not self.room.strokes[sid].get("h", False)
                ]
                if to_hide:
                    op = {
                        "k": "vis",
                        "hide": to_hide,
                        "show": [],
                        "cause": "redo",
                        "u": u,
                    }
                    self.room.commit(op)
                    stack.append(("c", to_hide))
                    return

    def _handle_clear(self, member: Member) -> None:
        """Hides all visible strokes on canvas. Restricted to HOST ONLY."""
        if member.role != "host":
            self.send_msg({
                "t": "err",
                "code": "denied",
                "msg": "Only the host can clear the whiteboard canvas",
                "fatal": False,
            })
            return

        assert self.room is not None
        visible_ids = [
            sid for sid, s in self.room.strokes.items() if not s.get("h", False)
        ]
        if not visible_ids:
            return

        op = {
            "k": "vis",
            "hide": visible_ids,
            "show": [],
            "cause": "clear",
            "u": member.user,
        }
        self.room.commit(op)

        # Record on host's undo stack so host can undo clear
        self.room.undo_stacks.setdefault(member.user, []).append(("c", visible_ids))
        self.room.redo_stacks.setdefault(member.user, []).clear()

    def _handle_sync(self, msg: Dict[str, Any]) -> None:
        """Handles gap detection resync request from a client."""
        assert self.room is not None
        last_seq = msg.get("last_seq")
        if (
            last_seq is not None
            and isinstance(last_seq, int)
            and 0 <= last_seq <= self.room.seq
        ):
            self.send_msg({
                "t": "delta",
                "ops": self.room.log[last_seq:],
                "seq": self.room.seq,
            })
        else:
            self.send_msg({
                "t": "snapshot",
                "seq": self.room.seq,
                "strokes": list(self.room.strokes.values()),
            })

    def _handle_chat(self, member: Member, msg: Dict[str, Any]) -> None:
        """Records and broadcasts a chat message with server timestamp."""
        text = msg.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return

        assert self.room is not None
        clean_text = text.strip()[:500]
        chat_item = {
            "id": secrets.token_hex(8),
            "user": member.user,
            "color": member.color,
            "text": clean_text,
            "ts": time.time(),
        }
        self.room.chat_history.append(chat_item)
        if len(self.room.chat_history) > MAX_CHAT_HISTORY:
            self.room.chat_history.pop(0)

        self.room.broadcast({"t": "chat", **chat_item})

    def _handle_save(self, member: Member, msg: Dict[str, Any]) -> None:
        """Atomically saves board snapshot with label (HOST ONLY)."""
        if member.role != "host":
            self.send_msg({
                "t": "err",
                "code": "denied",
                "msg": "Only the host can save versions",
                "fatal": False,
            })
            return

        label = msg.get("label", "manual")
        if not isinstance(label, str) or not RE_LABEL.match(label):
            label = "manual"

        assert self.room is not None
        os.makedirs(self.room.room_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}_{label}.json"
        filepath = os.path.join(self.room.room_dir, filename)
        tmppath = filepath + ".tmp"

        data = {
            "name": self.room.name,
            "salt": self.room.salt,
            "password_hash": self.room.password_hash,
            "host_user": self.room.host_user,
            "seq": self.room.seq,
            "log": self.room.log,
            "strokes": list(self.room.strokes.values()),
            "chat_history": self.room.chat_history,
            "canvas": self.room.canvas,
        }
        try:
            with open(tmppath, "w", encoding="utf-8") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(tmppath, filepath)
            self.send_msg({"t": "saved", "file": filename})
        except (OSError, TypeError, ValueError) as exc:
            self.send_msg({
                "t": "err",
                "code": "save_failed",
                "msg": f"Failed to save version: {exc}",
                "fatal": False,
            })

    def _handle_versions(self) -> None:
        """Returns sorted list of saved board version files."""
        assert self.room is not None
        if not os.path.exists(self.room.room_dir):
            files = []
        else:
            files = [
                f
                for f in os.listdir(self.room.room_dir)
                if f.endswith(".json")
                and f != "autosave.json"
                and os.path.isfile(os.path.join(self.room.room_dir, f))
            ]
            files.sort(reverse=True)
        self.send_msg({"t": "versions", "files": files})

    def _handle_load(self, member: Member, msg: Dict[str, Any]) -> None:
        """Restores a saved board version, re-validating strokes (HOST ONLY)."""
        if member.role != "host":
            self.send_msg({
                "t": "err",
                "code": "denied",
                "msg": "Only the host can restore versions",
                "fatal": False,
            })
            return

        requested_file = msg.get("file", "")
        if not isinstance(requested_file, str):
            self.send_msg({
                "t": "err",
                "code": "bad_file",
                "msg": "Invalid file specification",
                "fatal": False,
            })
            return

        # Security: Prevent path traversal attacks (e.g., '../../etc/passwd')
        clean_file = os.path.basename(requested_file)
        if clean_file != requested_file or not clean_file.endswith(".json"):
            self.send_msg({
                "t": "err",
                "code": "bad_file",
                "msg": "Invalid filename or path traversal denied",
                "fatal": False,
            })
            return

        assert self.room is not None
        if not os.path.exists(self.room.room_dir):
            self.send_msg({
                "t": "err",
                "code": "bad_file",
                "msg": "Room version directory does not exist",
                "fatal": False,
            })
            return

        available_files = os.listdir(self.room.room_dir)
        if clean_file not in available_files:
            self.send_msg({
                "t": "err",
                "code": "bad_file",
                "msg": "File not found in room versions",
                "fatal": False,
            })
            return

        filepath = os.path.join(self.room.room_dir, clean_file)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Version payload must be a JSON object")

            raw_strokes = data.get("strokes", [])
            if not isinstance(raw_strokes, list):
                raise ValueError("'strokes' in version file must be a list")

            valid_strokes: list[Dict[str, Any]] = []
            for idx, item in enumerate(raw_strokes):
                s = item[1] if isinstance(item, (list, tuple)) else item
                ok, _ = validate_stroke_dict(s)
                if ok:
                    valid_s = dict(s)
                    valid_s.setdefault("id", f"s_{idx}_{secrets.token_hex(4)}")
                    valid_s["h"] = False   # Always restore strokes as visible
                    valid_strokes.append(valid_s)

            # Replace strokes and broadcast a single sequenced reset op
            op = {
                "k": "reset",
                "strokes": valid_strokes,
                "u": member.user,
            }
            self.room.commit(op)
        except Exception as exc:
            self.send_msg({
                "t": "err",
                "code": "load_failed",
                "msg": f"Failed to parse or restore version file: {exc}",
                "fatal": False,
            })

    def _handle_setrole(self, member: Member, msg: Dict[str, Any]) -> None:
        """Modifies user permissions (host only)."""
        if member.role != "host":
            self.send_msg({
                "t": "err",
                "code": "forbidden",
                "msg": "Only the host can modify member roles",
                "fatal": False,
            })
            return

        target_user = msg.get("user")
        new_role = msg.get("role")
        if new_role not in {"editor", "viewer"}:
            self.send_msg({
                "t": "err",
                "code": "bad_role",
                "msg": "Target role must be 'editor' or 'viewer'",
                "fatal": False,
            })
            return

        assert self.room is not None
        if target_user not in self.room.members:
            self.send_msg({
                "t": "err",
                "code": "no_user",
                "msg": f"User '{target_user}' not found in room",
                "fatal": False,
            })
            return

        target_member = self.room.members[target_user]
        if target_member.role == "host":
            self.send_msg({
                "t": "err",
                "code": "cannot_demote_host",
                "msg": "Cannot modify host role",
                "fatal": False,
            })
            return

        target_member.role = new_role
        self.room.broadcast({
            "t": "users",
            "users": [m.to_dict() for m in self.room.members.values()],
        })
        self.room.broadcast({
            "t": "notice",
            "msg": f"{target_user}'s role updated to {new_role} by host {member.user}",
        })

    def _handle_present(self, member: Member, msg: Dict[str, Any]) -> None:
        """Toggles room presentation mode (host only)."""
        if member.role != "host":
            self.send_msg({
                "t": "err",
                "code": "denied",
                "msg": "Only the host can toggle presentation mode",
                "fatal": False,
            })
            return

        assert self.room is not None
        on = bool(msg.get("on", False))
        self.room.presentation_mode = on
        self.room.broadcast({
            "t": "present",
            "on": on,
            "by": member.user,
        })

    def _handle_kick(self, member: Member, msg: Dict[str, Any]) -> None:
        """Kicks a participant from the room (host only)."""
        if member.role != "host":
            self.send_msg({
                "t": "err",
                "code": "denied",
                "msg": "Only the host can kick participants",
                "fatal": False,
            })
            return

        target_user = msg.get("user")
        assert self.room is not None
        if not target_user or target_user not in self.room.members:
            self.send_msg({
                "t": "err",
                "code": "no_user",
                "msg": f"User '{target_user}' not found in room",
                "fatal": False,
            })
            return

        target_member = self.room.members[target_user]
        if target_member.role == "host":
            self.send_msg({
                "t": "err",
                "code": "cannot_kick_host",
                "msg": "Cannot kick the room host",
                "fatal": False,
            })
            return

        # Notify target client before closing
        if target_member.session:
            target_member.session.send_msg({
                "t": "err",
                "code": "kicked",
                "msg": f"You were kicked from the room by host {member.user}",
                "fatal": True,
            })
            target_member.session.close_graceful_and_exit()

        del self.room.members[target_user]
        self.room.broadcast({
            "t": "users",
            "users": [m.to_dict() for m in self.room.members.values()],
        })
        self.room.broadcast({
            "t": "notice",
            "msg": f"{target_user} was kicked from the room by host {member.user}",
        })

    def _handle_disconnect(self) -> None:
        """Marks member offline upon disconnection and notifies room members."""
        if self.room and self.user:
            with self.room.lock:
                member = self.room.members.get(self.user)
                if member and member.session == self:
                    member.online = False
                    member.offline_since = time.time()
                    member.session = None
                    self.room.broadcast({
                        "t": "users",
                        "users": [m.to_dict() for m in self.room.members.values()],
                    })
                    self.room.broadcast({
                        "t": "notice",
                        "msg": f"{self.user} went offline",
                    })

        self.server.remove_client(self)


class WhiteboardServer:
    """Multi-threaded TCP whiteboard server managing client connections, rooms, and lifecycle."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = PORT_DEFAULT,
        boards_dir: str = "boards",
        timeout: float = 15.0,
        grace: float = 120.0,
    ) -> None:
        self.host = host
        self.port = port
        if not os.path.isabs(boards_dir):
            self.boards_dir = os.path.join(get_base_dir(), boards_dir)
        else:
            self.boards_dir = boards_dir
        self.timeout = timeout
        self.grace = grace

        self.rooms: Dict[str, Room] = {}
        self.rooms_lock = threading.Lock()

        self.clients: Set[ClientSession] = set()
        self.clients_lock = threading.Lock()

        self.running = False
        self.server_sock: Optional[socket.socket] = None
        self.accept_thread: Optional[threading.Thread] = None
        self.reaper_thread: Optional[threading.Thread] = None
        self.startup_room: Optional[Room] = None
        self.startup_host_code_hash: Optional[str] = None

    def start(self) -> None:
        """Starts the TCP server and background reaper thread. Non-blocking."""
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.port = self.server_sock.getsockname()[1]
        self.server_sock.listen(128)

        self.running = True
        self.accept_thread = threading.Thread(
            target=self._accept_loop, name="ServerAcceptThread", daemon=True
        )
        self.accept_thread.start()

        self.reaper_thread = threading.Thread(
            target=self._reaper_loop, name="ServerReaperThread", daemon=True
        )
        self.reaper_thread.start()

    def stop(self) -> None:
        """Stops the server, closes listening socket, and cleanly terminates threads."""
        self.running = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except OSError:
                pass

        with self.clients_lock:
            active_clients = list(self.clients)
        for client in active_clients:
            client.close()

        # Autosave all rooms on server shutdown
        with self.rooms_lock:
            rooms_list = list(self.rooms.values())
        for room in rooms_list:
            try:
                room.autosave()
            except Exception as exc:
                logging.error(f"Shutdown autosave error: {exc}")

        if self.accept_thread and self.accept_thread.is_alive():
            self.accept_thread.join(timeout=1.0)
        if self.reaper_thread and self.reaper_thread.is_alive():
            self.reaper_thread.join(timeout=1.0)

    def _accept_loop(self) -> None:
        """Background loop accepting new TCP client connections."""
        while self.running and self.server_sock:
            try:
                client_sock, addr = self.server_sock.accept()
            except OSError:
                break

            session = ClientSession(client_sock, addr, self)
            with self.clients_lock:
                self.clients.add(session)
            session.start()

    def _reaper_loop(self) -> None:
        """Monitors heartbeat timeouts, offline member grace periods, and room autosaves."""
        while self.running:
            time.sleep(0.2)
            now = time.time()

            # 1. Harvest inactive client connections
            with self.clients_lock:
                clients_list = list(self.clients)

            for client in clients_list:
                if client.is_alive and (now - client.last_activity > self.timeout):
                    client.close()

            # 2. Check room lifecycle: grace periods, host election, autosave, empty rooms
            with self.rooms_lock:
                rooms_list = list(self.rooms.values())

            for room in rooms_list:
                with room.lock:
                    # Remove expired offline members
                    to_remove = []
                    for uname, member in room.members.items():
                        if (
                            not member.online
                            and member.offline_since
                            and (now - member.offline_since > self.grace)
                        ):
                            to_remove.append(uname)

                    host_removed = False
                    for uname in to_remove:
                        if uname == room.host_user:
                            host_removed = True
                        del room.members[uname]

                    if to_remove:
                        # Elect earliest-joined online member if host left
                        if host_removed:
                            online_members = [
                                m for m in room.members.values() if m.online
                            ]
                            if online_members:
                                online_members.sort(key=lambda m: m.joined_at)
                                new_host = online_members[0]
                                new_host.role = "host"
                                room.host_user = new_host.user
                                room.broadcast({
                                    "t": "notice",
                                    "msg": f"{new_host.user} is now host",
                                })
                            else:
                                room.host_user = ""

                        room.broadcast({
                            "t": "users",
                            "users": [m.to_dict() for m in room.members.values()],
                        })

                    # Autosave every 30 seconds when dirty
                    if room.dirty and (now - room.last_autosave >= 30.0):
                        try:
                            room.autosave()
                        except Exception as exc:
                            logging.error(f"Autosave loop error: {exc}")

                    # Empty room handling
                    online_count = sum(1 for m in room.members.values() if m.online)
                    if online_count == 0:
                        if room.empty_since is None:
                            room.empty_since = now
                            try:
                                room.autosave()
                            except Exception as exc:
                                logging.error(f"Empty room autosave error: {exc}")
                        elif now - room.empty_since > 1800:
                            # Reclaim empty room after 30 minutes
                            with self.rooms_lock:
                                self.rooms.pop(room.name, None)
                    else:
                        room.empty_since = None

    def remove_client(self, session: ClientSession) -> None:
        """Removes a client session from active tracking."""
        with self.clients_lock:
            self.clients.discard(session)

    def generate_startup_codes(self) -> Tuple[str, str, str]:
        """Creates a room and generates distinct room, host, and password codes."""
        with self.rooms_lock:
            while True:
                room_code = f"{secrets.randbelow(9000) + 1000:04d}"
                room_path = os.path.join(self.boards_dir, room_code)
                if room_code not in self.rooms and not os.path.exists(room_path):
                    break

            generated_codes = {room_code}
            while len(generated_codes) < 3:
                generated_codes.add(f"{secrets.randbelow(9000) + 1000:04d}")

            remaining_codes = list(generated_codes - {room_code})
            host_code = secrets.choice(remaining_codes)
            remaining_codes.remove(host_code)
            password_code = remaining_codes[0]
            salt = secrets.token_hex(16)
            password_hash = hashlib.sha256(
                (salt + password_code).encode("utf-8")
            ).hexdigest()
            room = Room(
                name=room_code,
                salt=salt,
                password_hash=password_hash,
                boards_dir=self.boards_dir,
            )
            self.rooms[room_code] = room
            self.startup_room = room
            self.startup_host_code_hash = hashlib.sha256(
                (salt + host_code).encode("utf-8")
            ).hexdigest()
            return room_code, host_code, password_code

    def get_or_create_room(
        self, name: str, password: str, create: bool
    ) -> Room | str:
        """Looks up, creates, or reloads a room according to the join/create rules."""
        with self.rooms_lock:
            if create:
                if name in self.rooms:
                    return "room_exists"
                salt = secrets.token_hex(16)
                pw_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
                new_room = Room(
                    name=name,
                    salt=salt,
                    password_hash=pw_hash,
                    boards_dir=self.boards_dir,
                )
                self.rooms[name] = new_room
                return new_room
            else:
                if name in self.rooms:
                    return self.rooms[name]
                # Check if autosaved room exists on disk
                room_dir = os.path.join(self.boards_dir, name)
                autosave_file = os.path.join(room_dir, "autosave.json")
                if os.path.exists(autosave_file):
                    try:
                        with open(autosave_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        room = Room(
                            name=data["name"],
                            salt=data["salt"],
                            password_hash=data["password_hash"],
                            boards_dir=self.boards_dir,
                        )
                        room.host_user = data.get("host_user", "")
                        room.seq = data.get("seq", 0)
                        room.log = data.get("log", [])
                        raw_strokes = data.get("strokes", [])
                        room.strokes = OrderedDict(
                            (s.get("id", f"s_{i}"), s)
                            for i, s in enumerate(raw_strokes)
                        )
                        room.chat_history = data.get("chat_history", [])
                        room.canvas = data.get("canvas", {"w": CANVAS_W, "h": CANVAS_H})
                        self.rooms[name] = room
                        return room
                    except Exception as exc:
                        logging.error(f"Failed to restore autosaved room {name}: {exc}")
                return "no_room"


def main() -> None:
    """CLI entry point for the Whiteboard TCP server."""
    parser = argparse.ArgumentParser(
        description="LAN Collaborative Whiteboard TCP Server"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface to bind on (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=PORT_DEFAULT,
        help=f"TCP port to listen on (default: {PORT_DEFAULT})",
    )
    parser.add_argument(
        "--boards",
        default="boards",
        help="Directory storing serialized whiteboard room state",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Heartbeat timeout in seconds (default: 15.0)",
    )
    parser.add_argument(
        "--grace",
        type=float,
        default=120.0,
        help="Reconnection grace period in seconds (default: 120.0)",
    )
    args = parser.parse_args()

    server = WhiteboardServer(
        host=args.host,
        port=args.port,
        boards_dir=args.boards,
        timeout=args.timeout,
        grace=args.grace,
    )
    room_code, host_code, password_code = server.generate_startup_codes()
    server.start()

    lan_ip = get_lan_ip()
    print("=" * 64)
    print("LAN Collaborative Whiteboard Server")
    print("=" * 64)
    print(f"Local LAN IP Address   : {lan_ip}")
    print(f"Listening On Interface : {args.host}:{server.port}")
    print(f"Room Code              : {room_code}")
    print(f"Host Code              : {host_code}  (host only)")
    print(f"Room Password          : {password_code}  (share with participants)")
    print("\nShare this LAN IP and Port with other computers on your network:")
    print(f"  python client.py --host {lan_ip} --port {server.port}")
    print("=" * 64)
    print("Server running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.stop()
        print("Server stopped cleanly.")


if __name__ == "__main__":
    main()
