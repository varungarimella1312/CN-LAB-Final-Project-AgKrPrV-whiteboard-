"""Headless integration tests for the LAN Collaborative Whiteboard.

Computer Networks Lab - LAN Collaborative Whiteboard
Module: whiteboard.test_integration

Comprehensive test suite verifying:
1. Low-level framing and protocol validation (TestFraming):
   - Message round-trip using socket.socketpair()
   - Back-to-back sticky packets coalescing
   - 1-byte fragmented packet streams
   - Header size validation (oversized and zero-length handling)
   - Missing required 't' key handling
2. Central TCP server integration over real sockets on port 0 (TestServerIntegration):
   - Room creation and joining
   - Wrong password rejection ("bad_password")
   - Unknown room rejection ("no_room")
   - Duplicate username rejection ("name_taken")
   - State synchronization: late joiners receive existing committed strokes
   - Role enforcement: viewers cannot draw ("readonly")
   - Stroke validation: invalid tools/colors/widths rejected ("bad_op")
   - Concurrent drawing: 4 clients x 40 strokes converge to identical order
   - Per-user undo/redo isolation (user actions do not affect peers)
   - Canvas clear permissions (editor denied, host clear + undo-clear works)
   - Stroke deduplication / idempotence across re-sends
   - Reconnect with secret token: returns delta ops; prevents name spoofing
   - Heartbeat timeout: silent client marked offline
   - Chat history delivered in welcome payload
   - Persistence & versioning: save, list versions, restore, and path traversal rejection
   - Automatic host re-election when host departs past grace period
"""

from __future__ import annotations

import os
import queue
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import Mock

# Ensure imports work whether executed from repo root or inside whiteboard/
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
        HEADER_SIZE,
        MAX_MSG,
        PORT_DEFAULT,
        ProtocolError,
        encode,
        recv_exact,
        recv_msg,
        send_msg,
    )
    from whiteboard.server import WhiteboardServer
    from whiteboard.boardstate import BoardState
    from whiteboard.client import (
        WhiteboardApp,
        _load_saved_session_token,
        _save_session_token,
    )
    from whiteboard.netclient import Net
except ImportError:
    from protocol import (  # type: ignore
        CANVAS_H,
        CANVAS_W,
        HEADER_SIZE,
        MAX_MSG,
        PORT_DEFAULT,
        ProtocolError,
        encode,
        recv_exact,
        recv_msg,
        send_msg,
    )
    from server import WhiteboardServer  # type: ignore
    from boardstate import BoardState  # type: ignore
    from client import (  # type: ignore
        WhiteboardApp,
        _load_saved_session_token,
        _save_session_token,
    )
    from netclient import Net  # type: ignore


class TestSessionTokenPersistence(unittest.TestCase):
    def test_session_token_survives_client_restart_and_is_identity_scoped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wb_test_tokens_") as token_dir:
            _save_session_token(
                "127.0.0.1",
                5050,
                "Alice",
                "0123456789abcdef0123456789abcdef",
                base_dir=token_dir,
            )

            self.assertEqual(
                _load_saved_session_token(
                    "127.0.0.1", 5050, "Alice", base_dir=token_dir
                ),
                "0123456789abcdef0123456789abcdef",
            )
            self.assertIsNone(
                _load_saved_session_token(
                    "127.0.0.1", 5050, "Bob", base_dir=token_dir
                )
            )
            self.assertIsNone(
                _load_saved_session_token(
                    "192.168.1.2", 5050, "Alice", base_dir=token_dir
                )
            )


class TestClientLatencyOptimizations(unittest.TestCase):
    def test_event_pump_coalesces_cursors_without_skipping_other_messages(self) -> None:
        app = WhiteboardApp.__new__(WhiteboardApp)
        app.events_queue = queue.Queue()
        app.root = Mock()
        app.render_peer_cursor = Mock()
        app._dispatch_server_message = Mock()

        old_cursor = {"t": "cursor", "u": "Peer", "x": 1, "y": 2}
        latest_cursor = {"t": "cursor", "u": "Peer", "x": 3, "y": 4}
        operation = {"t": "op", "seq": 1}
        app.events_queue.put(("msg", old_cursor))
        app.events_queue.put(("msg", operation))
        app.events_queue.put(("msg", latest_cursor))

        app._pump_network_events()

        app.render_peer_cursor.assert_called_once_with(latest_cursor)
        app._dispatch_server_message.assert_called_once_with(operation)
        self.assertEqual(app.root.after.call_args.args[0], 15)

    def test_peer_cursor_canvas_items_are_reused(self) -> None:
        app = WhiteboardApp.__new__(WhiteboardApp)
        app.username = "Local"
        app.canvas = Mock()
        app.canvas.create_oval.return_value = 1
        app.canvas.create_text.return_value = 2
        app.peer_cursor_items = {}
        app.peer_cursor_times = {}

        app.render_peer_cursor({"u": "Peer", "x": 10, "y": 20})
        app.render_peer_cursor({"u": "Peer", "x": 30, "y": 40})

        app.canvas.create_oval.assert_called_once()
        app.canvas.create_text.assert_called_once()
        self.assertEqual(app.canvas.coords.call_count, 2)


class TestFraming(unittest.TestCase):
    """Tests the length-prefix TCP framing implementation using local socket pairs."""

    def setUp(self) -> None:
        self.s1, self.s2 = socket.socketpair()

    def tearDown(self) -> None:
        self.s1.close()
        self.s2.close()

    def test_message_roundtrip(self) -> None:
        msg = {
            "t": "stroke",
            "id": "stroke-001",
            "tool": "pen",
            "color": "#1E90FF",
            "width": 4,
            "pts": [[100, 150], [105, 152], [110, 160]],
        }
        send_msg(self.s1, msg)
        received = recv_msg(self.s2)
        self.assertEqual(received, msg)

    def test_back_to_back_messages(self) -> None:
        msg1 = {"t": "join", "user": "StudentAlice", "color": "#FF0000"}
        msg2 = {"t": "join", "user": "StudentBob", "color": "#00FF00"}

        send_msg(self.s1, msg1)
        send_msg(self.s1, msg2)

        res1 = recv_msg(self.s2)
        res2 = recv_msg(self.s2)

        self.assertEqual(res1, msg1)
        self.assertEqual(res2, msg2)

    def test_fragmented_one_byte_pieces(self) -> None:
        msg = {
            "t": "draw",
            "tool": "rectangle",
            "coords": [50, 50, 300, 200],
            "color": "#000000",
            "fill": False,
        }
        raw_bytes = encode(msg)

        for i in range(len(raw_bytes)):
            self.s1.sendall(raw_bytes[i : i + 1])

        decoded = recv_msg(self.s2)
        self.assertEqual(decoded, msg)

    def test_oversized_header_raises_protocol_error(self) -> None:
        oversized_length = MAX_MSG + 1
        header = struct.pack(">I", oversized_length)
        self.s1.sendall(header)

        with self.assertRaises(ProtocolError) as ctx:
            recv_msg(self.s2)
        self.assertIn("exceeds", str(ctx.exception).lower())

    def test_zero_length_header_raises_protocol_error(self) -> None:
        header = struct.pack(">I", 0)
        self.s1.sendall(header)

        with self.assertRaises(ProtocolError):
            recv_msg(self.s2)

    def test_missing_type_key_raises_protocol_error(self) -> None:
        invalid_payload = {"user": "Alice", "color": "#FF0000"}
        import json

        body = json.dumps(invalid_payload).encode("utf-8")
        header = struct.pack(">I", len(body))
        self.s1.sendall(header + body)

        with self.assertRaises(ProtocolError) as ctx:
            recv_msg(self.s2)
        self.assertIn("missing required 't'", str(ctx.exception))


class TestServerIntegration(unittest.TestCase):
    """Integration test suite verifying WhiteboardServer over real loopback sockets."""

    def setUp(self) -> None:
        self.temp_boards_dir = tempfile.mkdtemp(prefix="wb_test_boards_")
        self.server = WhiteboardServer(
            host="127.0.0.1",
            port=0,
            boards_dir=self.temp_boards_dir,
            timeout=15.0,
            grace=120.0,
        )
        self.server.start()
        self.port = self.server.port
        self.client_sockets: list[socket.socket] = []

    def tearDown(self) -> None:
        for s in self.client_sockets:
            try:
                s.close()
            except OSError:
                pass
        self.server.stop()
        if os.path.exists(self.temp_boards_dir):
            shutil.rmtree(self.temp_boards_dir, ignore_errors=True)

    def _connect(self, timeout: float = 3.0) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", self.port))
        self.client_sockets.append(s)
        return s

    def _recv_filtered(
        self, sock: socket.socket, predicate: Callable[[Dict[str, Any]], bool]
    ) -> Dict[str, Any]:
        while True:
            msg = recv_msg(sock)
            if predicate(msg):
                return msg

    def _recv_type(self, sock: socket.socket, target_type: str) -> Dict[str, Any]:
        return self._recv_filtered(sock, lambda m: m.get("t") == target_type)

    def test_join_and_create_room(self) -> None:
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "math-101",
                "user": "Alice",
                "pw": "secret123",
                "create": True,
            },
        )
        welcome = self._recv_type(c1, "welcome")
        self.assertEqual(welcome.get("t"), "welcome")
        self.assertEqual(welcome.get("room"), "math-101")
        self.assertEqual(welcome.get("host"), "Alice")
        self.assertEqual(welcome.get("you", {}).get("user"), "Alice")
        self.assertEqual(welcome.get("you", {}).get("role"), "host")
        self.assertTrue(len(welcome.get("you", {}).get("token", "")) > 0)

    def test_generated_codes_gate_host_and_participant_room_access(self) -> None:
        room_code, host_code, password_code = self.server.generate_startup_codes()
        self.assertRegex(room_code, r"^\d{4}$")
        self.assertRegex(host_code, r"^\d{4}$")
        self.assertRegex(password_code, r"^\d{4}$")
        self.assertEqual(len({room_code, host_code, password_code}), 3)

        host = self._connect()
        send_msg(
            host,
            {
                "t": "hello",
                "user": "HostUser",
                "pw": password_code,
                "is_host": True,
                "host_code": host_code,
            },
        )
        host_welcome = self._recv_type(host, "welcome")
        self.assertEqual(host_welcome.get("you", {}).get("role"), "host")
        self.assertEqual(host_welcome.get("room"), room_code)
        self._recv_type(host, "users")

        invalid_host = self._connect()
        send_msg(
            invalid_host,
            {
                "t": "hello",
                "user": "InvalidHost",
                "pw": password_code,
                "is_host": True,
                "host_code": "0000" if host_code != "0000" else "0001",
            },
        )
        host_error = self._recv_type(invalid_host, "err")
        self.assertEqual(host_error.get("code"), "bad_host_code")

        wrong_password_client = self._connect()
        send_msg(
            wrong_password_client,
            {
                "t": "hello",
                "user": "WrongPasswordUser",
                "pw": "0000" if password_code != "0000" else "0001",
                "is_host": False,
            },
        )
        password_error = self._recv_type(wrong_password_client, "err")
        self.assertEqual(password_error.get("code"), "bad_password")

        participant = self._connect()
        send_msg(
            participant,
            {
                "t": "hello",
                "user": "Participant",
                "pw": password_code,
                "is_host": False,
            },
        )
        participant_welcome = self._recv_type(participant, "welcome")
        self.assertEqual(participant_welcome.get("you", {}).get("role"), "editor")
        self.assertEqual(
            {user["user"] for user in participant_welcome.get("users", [])},
            {"HostUser", "Participant"},
        )
        host_roster = self._recv_type(host, "users")
        self.assertEqual(
            {user["user"] for user in host_roster.get("users", [])},
            {"HostUser", "Participant"},
        )
        join_notice = self._recv_type(host, "notice")
        self.assertIn("Participant joined the room", join_notice.get("msg", ""))

        participant.close()
        leave_roster = self._recv_type(host, "users")
        self.assertTrue(
            any(
                user.get("user") == "Participant" and not user.get("online")
                for user in leave_roster.get("users", [])
            )
        )
        leave_notice = self._recv_type(host, "notice")
        self.assertIn("Participant went offline", leave_notice.get("msg", ""))

    def test_create_existing_room_fails(self) -> None:
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "cs-room",
                "user": "Alice",
                "pw": "pass",
                "create": True,
            },
        )
        w1 = self._recv_type(c1, "welcome")
        self.assertEqual(w1.get("t"), "welcome")

        c2 = self._connect()
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "cs-room",
                "user": "Bob",
                "pw": "pass",
                "create": True,
            },
        )
        err = self._recv_type(c2, "err")
        self.assertEqual(err.get("code"), "room_exists")
        self.assertTrue(err.get("fatal"))

    def test_wrong_password_rejected(self) -> None:
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "chem-lab",
                "user": "Alice",
                "pw": "correct_pass",
                "create": True,
            },
        )
        self._recv_type(c1, "welcome")

        c2 = self._connect()
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "chem-lab",
                "user": "Bob",
                "pw": "wrong_pass",
                "create": False,
            },
        )
        err = self._recv_type(c2, "err")
        self.assertEqual(err.get("code"), "bad_password")
        self.assertTrue(err.get("fatal"))

    def test_unknown_room_rejected(self) -> None:
        c = self._connect()
        send_msg(
            c,
            {
                "t": "hello",
                "room": "ghost_room",
                "user": "Charlie",
                "pw": "any_pass",
                "create": False,
            },
        )
        err = self._recv_type(c, "err")
        self.assertEqual(err.get("code"), "no_room")
        self.assertTrue(err.get("fatal"))

    def test_duplicate_username_rejected(self) -> None:
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "physics-lab",
                "user": "Alice",
                "pw": "pw123",
                "create": True,
            },
        )
        self._recv_type(c1, "welcome")

        c2 = self._connect()
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "physics-lab",
                "user": "Alice",
                "pw": "pw123",
                "create": False,
            },
        )
        err = self._recv_type(c2, "err")
        self.assertEqual(err.get("code"), "name_taken")
        self.assertTrue(err.get("fatal"))

    def test_late_joiner_receives_existing_strokes(self) -> None:
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "drawing-room",
                "user": "HostUser",
                "pw": "drawpw",
                "create": True,
            },
        )
        self._recv_type(c1, "welcome")

        stroke_obj = {
            "tool": "pen",
            "color": "#FF5733",
            "width": 5,
            "pts": [[10, 10], [20, 20], [30, 30]],
        }
        send_msg(c1, {"t": "stroke", "id": "stroke-01", "s": stroke_obj})

        ack = self._recv_type(c1, "ack")
        self.assertEqual(ack.get("id"), "stroke-01")

        c2 = self._connect()
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "drawing-room",
                "user": "LateUser",
                "pw": "drawpw",
                "create": False,
            },
        )
        welcome2 = self._recv_type(c2, "welcome")
        self.assertEqual(welcome2.get("t"), "welcome")
        self.assertEqual(len(welcome2.get("strokes", [])), 1)
        received_stroke = welcome2["strokes"][0]
        self.assertEqual(received_stroke["tool"], "pen")
        self.assertEqual(received_stroke["color"], "#FF5733")

    def test_viewer_cannot_draw(self) -> None:
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "lecture-hall",
                "user": "Professor",
                "pw": "securepw",
                "create": True,
            },
        )
        self._recv_type(c1, "welcome")

        c2 = self._connect()
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "lecture-hall",
                "user": "Student",
                "pw": "securepw",
                "create": False,
            },
        )
        self._recv_type(c2, "welcome")

        send_msg(c1, {"t": "setrole", "user": "Student", "role": "viewer"})

        def is_student_viewer(m: Dict[str, Any]) -> bool:
            if m.get("t") != "users":
                return False
            return any(
                u.get("user") == "Student" and u.get("role") == "viewer"
                for u in m.get("users", [])
            )

        self._recv_filtered(c2, is_student_viewer)

        send_msg(
            c2,
            {
                "t": "stroke",
                "id": "unauthorized-stroke",
                "s": {
                    "tool": "pen",
                    "color": "#000000",
                    "width": 2,
                    "pts": [[50, 50], [60, 60]],
                },
            },
        )
        err = self._recv_type(c2, "err")
        self.assertEqual(err.get("code"), "readonly")

    def test_invalid_strokes_rejected(self) -> None:
        c = self._connect()
        send_msg(
            c,
            {
                "t": "hello",
                "room": "test-room",
                "user": "Tester",
                "pw": "testpw",
                "create": True,
            },
        )
        self._recv_type(c, "welcome")

        # 1. Invalid tool
        send_msg(
            c,
            {
                "t": "stroke",
                "id": "s-bad-tool",
                "s": {
                    "tool": "spraypaint",
                    "color": "#000000",
                    "width": 5,
                    "pts": [[0, 0], [10, 10]],
                },
            },
        )
        err1 = self._recv_type(c, "err")
        self.assertEqual(err1.get("code"), "bad_op")

        # 2. Invalid color format
        send_msg(
            c,
            {
                "t": "stroke",
                "id": "s-bad-color",
                "s": {
                    "tool": "pen",
                    "color": "red",
                    "width": 5,
                    "pts": [[0, 0], [10, 10]],
                },
            },
        )
        err2 = self._recv_type(c, "err")
        self.assertEqual(err2.get("code"), "bad_op")

        # 3. Invalid width (> 60)
        send_msg(
            c,
            {
                "t": "stroke",
                "id": "s-bad-width",
                "s": {
                    "tool": "pen",
                    "color": "#123456",
                    "width": 999,
                    "pts": [[0, 0], [10, 10]],
                },
            },
        )
        err3 = self._recv_type(c, "err")
        self.assertEqual(err3.get("code"), "bad_op")

    def test_eraser_max_width_is_accepted(self) -> None:
        c = self._connect()
        send_msg(
            c,
            {
                "t": "hello",
                "room": "eraser-room",
                "user": "EraserUser",
                "pw": "p",
                "create": True,
            },
        )
        self._recv_type(c, "welcome")

        send_msg(
            c,
            {
                "t": "stroke",
                "id": "eraser-max-width",
                "s": {
                    "tool": "eraser",
                    "color": "#FFFFFF",
                    "width": 90,
                    "pts": [[0, 0], [10, 10]],
                },
            },
        )

        responses: Dict[str, Dict[str, Any]] = {}
        while not {"ack", "op"}.issubset(responses):
            msg = recv_msg(c)
            if msg.get("t") in {"ack", "op"}:
                responses[msg["t"]] = msg
        op = responses["op"]
        self.assertEqual(op.get("s", {}).get("width"), 90)

    def test_sticky_note_stroke_support(self) -> None:
        """Verify sticky note strokes with 'bg' color are validated, committed, and broadcast."""
        c = self._connect()
        send_msg(
            c,
            {
                "t": "hello",
                "room": "notes-room",
                "user": "NoteAuthor",
                "pw": "p",
                "create": True,
            },
        )
        self._recv_type(c, "welcome")

        # 1. Valid sticky note stroke
        note_stroke = {
            "tool": "text",
            "color": "#111111",
            "bg": "#FFF9A6",
            "width": 1,
            "pts": [[50, 50], [210, 160]],
            "text": "Discussion points for lab",
        }
        send_msg(c, {"t": "stroke", "id": "note-01", "s": note_stroke})

        # Drain incoming messages (op and ack)
        msgs = []
        while len(msgs) < 2:
            m = recv_msg(c)
            if m.get("t") in {"ack", "op"}:
                msgs.append(m)

        msg_types = {m.get("t") for m in msgs}
        self.assertIn("ack", msg_types)
        self.assertIn("op", msg_types)

        op = next(m for m in msgs if m.get("t") == "op")
        self.assertEqual(op.get("id"), "note-01")
        self.assertEqual(op.get("s", {}).get("bg"), "#FFF9A6")
        self.assertEqual(op.get("s", {}).get("text"), "Discussion points for lab")

        # 2. Invalid bg color format rejected
        bad_note = {
            "tool": "text",
            "color": "#000000",
            "bg": "not_a_hex_color",
            "width": 1,
            "pts": [[0, 0]],
            "text": "test",
        }
        send_msg(c, {"t": "stroke", "id": "note-bad", "s": bad_note})
        err = self._recv_type(c, "err")
        self.assertEqual(err.get("code"), "bad_op")

    def test_concurrent_drawing_convergence(self) -> None:
        """Verify 4 concurrent clients drawing 40 strokes each converge to identical order."""
        room_name = "concurrent-room"
        num_clients = 4
        strokes_per_client = 40
        total_strokes = num_clients * strokes_per_client

        clients: list[socket.socket] = []
        for i in range(num_clients):
            sock = self._connect()
            send_msg(
                sock,
                {
                    "t": "hello",
                    "room": room_name,
                    "user": f"User_{i}",
                    "pw": "pass123",
                    "create": (i == 0),
                },
            )
            self._recv_type(sock, "welcome")
            clients.append(sock)

        # Worker threads send strokes concurrently
        barrier = threading.Barrier(num_clients)

        def sender_worker(client_idx: int, sock: socket.socket):
            barrier.wait()
            for s_idx in range(strokes_per_client):
                sid = f"c_{client_idx}_s_{s_idx}"
                stroke_data = {
                    "tool": "pen",
                    "color": "#123456",
                    "width": 3,
                    "pts": [[s_idx, s_idx], [s_idx + 1, s_idx + 1]],
                }
                send_msg(sock, {"t": "stroke", "id": sid, "s": stroke_data})

        # Collector threads record received sequenced op messages
        client_ops: list[list[str]] = [[] for _ in range(num_clients)]

        def receiver_worker(client_idx: int, sock: socket.socket):
            sock.settimeout(8.0)
            while len(client_ops[client_idx]) < total_strokes:
                try:
                    m = recv_msg(sock)
                except Exception:
                    break
                if m.get("t") == "op" and m.get("k") == "stroke":
                    client_ops[client_idx].append(m.get("id", ""))

        rec_threads = [
            threading.Thread(target=receiver_worker, args=(i, clients[i]))
            for i in range(num_clients)
        ]
        for t in rec_threads:
            t.start()

        send_threads = [
            threading.Thread(target=sender_worker, args=(i, clients[i]))
            for i in range(num_clients)
        ]
        for t in send_threads:
            t.start()

        for t in send_threads:
            t.join(timeout=10.0)
        for t in rec_threads:
            t.join(timeout=10.0)

        # Verify all clients received all 160 strokes in the exact same sequence
        first_replica = client_ops[0]
        self.assertEqual(len(first_replica), total_strokes)
        for i in range(1, num_clients):
            self.assertEqual(
                client_ops[i],
                first_replica,
                f"Client {i} diverged from canonical global order",
            )

    def test_per_user_undo_redo_isolation(self) -> None:
        """Verify undo/redo affects only the caller's actions without mutating peers' strokes."""
        c1 = self._connect()
        c2 = self._connect()

        # Alice joins as host
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "undo-room",
                "user": "Alice",
                "pw": "pw",
                "create": True,
            },
        )
        self._recv_type(c1, "welcome")

        # Bob joins as editor
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "undo-room",
                "user": "Bob",
                "pw": "pw",
                "create": False,
            },
        )
        self._recv_type(c2, "welcome")

        # Alice draws stroke_A
        send_msg(
            c1,
            {
                "t": "stroke",
                "id": "stroke_A",
                "s": {"tool": "pen", "color": "#111111", "width": 2, "pts": [[0, 0], [1, 1]]},
            },
        )
        self._recv_type(c1, "ack")

        # Bob draws stroke_B
        send_msg(
            c2,
            {
                "t": "stroke",
                "id": "stroke_B",
                "s": {"tool": "pen", "color": "#222222", "width": 2, "pts": [[2, 2], [3, 3]]},
            },
        )
        self._recv_type(c2, "ack")

        # Alice calls UNDO: should hide ONLY stroke_A
        send_msg(c1, {"t": "undo"})

        op_undo = self._recv_filtered(
            c1, lambda m: m.get("t") == "op" and m.get("cause") == "undo"
        )
        self.assertEqual(op_undo.get("hide"), ["stroke_A"])
        self.assertEqual(op_undo.get("u"), "Alice")

        # Verify Bob's stroke_B was untouched
        room = self.server.rooms["undo-room"]
        with room.lock:
            self.assertTrue(room.strokes["stroke_A"]["h"])
            self.assertFalse(room.strokes["stroke_B"]["h"])

        # Alice calls REDO: should unhide stroke_A
        send_msg(c1, {"t": "redo"})
        op_redo = self._recv_filtered(
            c1, lambda m: m.get("t") == "op" and m.get("cause") == "redo"
        )
        self.assertEqual(op_redo.get("show"), ["stroke_A"])

        with room.lock:
            self.assertFalse(room.strokes["stroke_A"]["h"])
            self.assertFalse(room.strokes["stroke_B"]["h"])

    def test_editor_clear_denied_and_host_undo_clear(self) -> None:
        """Verify clear is host-only and host can undo a full clear."""
        c_host = self._connect()
        c_editor = self._connect()

        send_msg(
            c_host,
            {
                "t": "hello",
                "room": "clear-room",
                "user": "HostAlice",
                "pw": "p",
                "create": True,
            },
        )
        self._recv_type(c_host, "welcome")

        send_msg(
            c_editor,
            {
                "t": "hello",
                "room": "clear-room",
                "user": "EditorBob",
                "pw": "p",
                "create": False,
            },
        )
        self._recv_type(c_editor, "welcome")

        # Add a stroke
        send_msg(
            c_host,
            {
                "t": "stroke",
                "id": "s_visible",
                "s": {"tool": "pen", "color": "#333333", "width": 2, "pts": [[0, 0], [1, 1]]},
            },
        )
        self._recv_type(c_host, "ack")

        # Editor attempts clear -> DENIED
        send_msg(c_editor, {"t": "clear"})
        err = self._recv_type(c_editor, "err")
        self.assertEqual(err.get("code"), "denied")

        # Host clears -> SUCCESS
        send_msg(c_host, {"t": "clear"})
        op_clear = self._recv_filtered(
            c_host, lambda m: m.get("t") == "op" and m.get("cause") == "clear"
        )
        self.assertIn("s_visible", op_clear.get("hide", []))

        # Host calls undo -> Restores canvas
        send_msg(c_host, {"t": "undo"})
        op_restore = self._recv_filtered(
            c_host, lambda m: m.get("t") == "op" and m.get("cause") == "undo"
        )
        self.assertIn("s_visible", op_restore.get("show", []))

    def test_duplicate_stroke_deduplication(self) -> None:
        """Verify duplicate stroke ID is applied once and returns original sequence ACK."""
        c = self._connect()
        send_msg(
            c,
            {
                "t": "hello",
                "room": "dedupe-room",
                "user": "Alice",
                "pw": "p",
                "create": True,
            },
        )
        self._recv_type(c, "welcome")

        stroke_msg = {
            "t": "stroke",
            "id": "stroke-dedupe-1",
            "s": {"tool": "pen", "color": "#ABCDEF", "width": 4, "pts": [[10, 10], [20, 20]]},
        }

        # First send
        send_msg(c, stroke_msg)
        ack1 = self._recv_type(c, "ack")
        seq1 = ack1.get("seq")

        # Second send of identical stroke ID
        send_msg(c, stroke_msg)
        ack2 = self._recv_type(c, "ack")
        seq2 = ack2.get("seq")

        self.assertEqual(seq1, seq2)
        room = self.server.rooms["dedupe-room"]
        with room.lock:
            # Committed exactly once
            stroke_ops = [
                op for op in room.log if op.get("id") == "stroke-dedupe-1"
            ]
            self.assertEqual(len(stroke_ops), 1)

    def test_reconnect_delta_and_name_protection(self) -> None:
        """Verify token re-attaches with delta ops and imposter cannot steal username."""
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "reconnect-room",
                "user": "Alice",
                "pw": "pass",
                "create": True,
            },
        )
        welcome1 = self._recv_type(c1, "welcome")
        token = welcome1.get("you", {}).get("token")

        c_observer = self._connect()
        send_msg(
            c_observer,
            {
                "t": "hello",
                "room": "reconnect-room",
                "user": "Bob",
                "pw": "pass",
                "create": False,
            },
        )
        self._recv_type(c_observer, "welcome")
        self._recv_type(c_observer, "users")
        self._recv_type(c1, "users")
        self.assertIn("Bob joined", self._recv_type(c1, "notice").get("msg", ""))

        # Draw 2 strokes
        for i in range(2):
            send_msg(
                c1,
                {
                    "t": "stroke",
                    "id": f"stroke_{i}",
                    "s": {
                        "tool": "pen",
                        "color": "#112233",
                        "width": 2,
                        "pts": [[i, i], [i + 5, i + 5]],
                    },
                },
            )
            self._recv_type(c1, "ack")

        # Imposter attempts to steal Alice's username with invalid token
        c_eve = self._connect()
        send_msg(
            c_eve,
            {
                "t": "hello",
                "room": "reconnect-room",
                "user": "Alice",
                "pw": "pass",
                "create": False,
                "token": "fake_token",
            },
        )
        err = self._recv_type(c_eve, "err")
        self.assertEqual(err.get("code"), "name_taken")

        # Alice leaves from the client UI
        send_msg(c1, {"t": "leave"})
        self._recv_type(c_observer, "users")
        offline_notice = self._recv_type(c_observer, "notice")
        self.assertIn("Alice went offline", offline_notice.get("msg", ""))

        # Alice reconnects with token and last_seq=1 (requesting missed delta ops)
        c_reconnect = self._connect()
        send_msg(
            c_reconnect,
            {
                "t": "hello",
                "room": "reconnect-room",
                "user": "Alice",
                "pw": "pass",
                "create": False,
                "token": token,
                "last_seq": 1,
            },
        )
        welcome_reconnect = self._recv_type(c_reconnect, "welcome")
        self.assertTrue(welcome_reconnect.get("reconnected"))
        self._recv_type(c_observer, "users")
        self.assertEqual(
            self._recv_type(c_observer, "notice").get("msg"),
            "Alice reconnected to the room",
        )
        self.assertEqual(
            self.server.rooms["reconnect-room"].seen_usernames,
            {"Alice", "Bob"},
        )
        self.assertEqual(welcome_reconnect.get("mode"), "delta")
        # Should only contain op 2
        ops = welcome_reconnect.get("ops", [])
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].get("id"), "stroke_1")

    def test_seen_username_history_survives_autosave(self) -> None:
        client = self._connect()
        send_msg(
            client,
            {
                "t": "hello",
                "room": "username-history-room",
                "user": "Alice",
                "pw": "pass",
                "create": True,
            },
        )
        self._recv_type(client, "welcome")

        room = self.server.rooms["username-history-room"]
        room.autosave()
        self.assertIn("Alice", room.seen_usernames)
        with self.server.rooms_lock:
            del self.server.rooms["username-history-room"]

        restored_room = self.server.get_or_create_room(
            "username-history-room", "pass", create=False
        )
        if isinstance(restored_room, str):
            self.fail(f"Room history restore failed: {restored_room}")
        self.assertIn("Alice", restored_room.seen_usernames)

    def test_silent_client_marked_offline_by_reaper(self) -> None:
        """Verify reaper thread marks inactive clients offline after timeout."""
        self.server.stop()
        self.server = WhiteboardServer(
            host="127.0.0.1",
            port=0,
            boards_dir=self.temp_boards_dir,
            timeout=0.8,
            grace=120.0,
        )
        self.server.start()
        self.port = self.server.port

        c_active = self._connect()
        c_silent = self._connect()

        send_msg(
            c_active,
            {
                "t": "hello",
                "room": "timeout-room",
                "user": "ActiveUser",
                "pw": "pw",
                "create": True,
            },
        )
        self._recv_type(c_active, "welcome")

        send_msg(
            c_silent,
            {
                "t": "hello",
                "room": "timeout-room",
                "user": "SilentUser",
                "pw": "pw",
                "create": False,
            },
        )
        self._recv_type(c_silent, "welcome")

        def is_silent_offline(m: Dict[str, Any]) -> bool:
            if m.get("t") != "users":
                return False
            return any(
                u.get("user") == "SilentUser" and not u.get("online")
                for u in m.get("users", [])
            )

        # c_silent remains completely silent; c_active pings every 0.2s to stay alive
        updated_users = None
        start = time.time()
        while time.time() - start < 4.0:
            time.sleep(0.2)
            send_msg(c_active, {"t": "ping", "ts": time.time()})
            while True:
                try:
                    c_active.settimeout(0.15)
                    m = recv_msg(c_active)
                    if is_silent_offline(m):
                        updated_users = m
                        break
                except (socket.timeout, TimeoutError):
                    break
            if updated_users:
                break

        self.assertIsNotNone(updated_users, "Silent user was never marked offline by reaper")

    def test_chat_history_delivered_in_welcome(self) -> None:
        """Verify chat messages are preserved and delivered in the welcome payload."""
        c1 = self._connect()
        send_msg(
            c1,
            {
                "t": "hello",
                "room": "chat-room",
                "user": "Alice",
                "pw": "pw",
                "create": True,
            },
        )
        self._recv_type(c1, "welcome")

        send_msg(c1, {"t": "chat", "text": "Hello Networks Lab!"})
        self._recv_type(c1, "chat")

        c2 = self._connect()
        send_msg(
            c2,
            {
                "t": "hello",
                "room": "chat-room",
                "user": "Bob",
                "pw": "pw",
                "create": False,
            },
        )
        w2 = self._recv_type(c2, "welcome")
        chat_list = w2.get("chat", [])
        self.assertGreaterEqual(len(chat_list), 1)
        self.assertEqual(chat_list[-1]["text"], "Hello Networks Lab!")
        self.assertEqual(chat_list[-1]["user"], "Alice")

    def test_group_and_private_chat_delivery_and_history(self) -> None:
        alice = self._connect()
        send_msg(
            alice,
            {
                "t": "hello",
                "room": "mixed-chat-room",
                "user": "Alice",
                "pw": "pw",
                "create": True,
            },
        )
        self._recv_type(alice, "welcome")
        self._recv_type(alice, "users")

        bob = self._connect()
        send_msg(
            bob,
            {
                "t": "hello",
                "room": "mixed-chat-room",
                "user": "Bob",
                "pw": "pw",
                "create": False,
            },
        )
        bob_welcome = self._recv_type(bob, "welcome")
        self._recv_type(bob, "users")
        self._recv_type(alice, "users")
        self._recv_type(alice, "notice")

        carol = self._connect()
        send_msg(
            carol,
            {
                "t": "hello",
                "room": "mixed-chat-room",
                "user": "Carol",
                "pw": "pw",
                "create": False,
            },
        )
        carol_welcome = self._recv_type(carol, "welcome")
        self._recv_type(carol, "users")
        for existing_client in (alice, bob):
            self._recv_type(existing_client, "users")
            self._recv_type(existing_client, "notice")

        send_msg(alice, {"t": "chat", "text": "Hello everyone"})
        group_messages = [
            self._recv_type(client, "chat") for client in (alice, bob, carol)
        ]
        self.assertTrue(all(message.get("text") == "Hello everyone" for message in group_messages))
        self.assertTrue(all(message.get("user") == "Alice" for message in group_messages))
        self.assertTrue(all("to" not in message for message in group_messages))
        self.assertTrue(all(isinstance(message.get("ts"), (int, float)) for message in group_messages))

        send_msg(
            alice,
            {"t": "chat", "to": "Bob", "text": "Private message"},
        )
        alice_private = self._recv_type(alice, "chat")
        bob_private = self._recv_type(bob, "chat")
        self.assertEqual(alice_private.get("id"), bob_private.get("id"))
        self.assertEqual(alice_private.get("user"), "Alice")
        self.assertEqual(alice_private.get("to"), "Bob")
        self.assertEqual(alice_private.get("text"), "Private message")
        self.assertIsInstance(alice_private.get("ts"), (int, float))

        send_msg(
            alice,
            {"t": "chat", "to": "NotActive", "text": "Should not be delivered"},
        )
        unavailable_error = self._recv_type(alice, "err")
        self.assertEqual(unavailable_error.get("code"), "chat_recipient_unavailable")

        carol.settimeout(0.2)
        try:
            unexpected_message = recv_msg(carol)
        except socket.timeout:
            pass
        else:
            self.fail(f"Private message leaked to another participant: {unexpected_message}")
        finally:
            carol.settimeout(3.0)

        bob_token = bob_welcome.get("you", {}).get("token")
        bob.close()
        bob_reconnected = self._connect()
        send_msg(
            bob_reconnected,
            {
                "t": "hello",
                "room": "mixed-chat-room",
                "user": "Bob",
                "pw": "pw",
                "create": False,
                "token": bob_token,
                "last_seq": 0,
            },
        )
        bob_reconnected_welcome = self._recv_type(bob_reconnected, "welcome")
        bob_history = bob_reconnected_welcome.get("chat", [])
        self.assertEqual(
            [message.get("text") for message in bob_history],
            ["Hello everyone", "Private message"],
        )
        self.assertNotIn("from_identity", bob_history[-1])
        self.assertNotIn("to_identity", bob_history[-1])

        carol_token = carol_welcome.get("you", {}).get("token")
        carol.close()
        carol_reconnected = self._connect()
        send_msg(
            carol_reconnected,
            {
                "t": "hello",
                "room": "mixed-chat-room",
                "user": "Carol",
                "pw": "pw",
                "create": False,
                "token": carol_token,
                "last_seq": 0,
            },
        )
        carol_reconnected_welcome = self._recv_type(carol_reconnected, "welcome")
        carol_history = carol_reconnected_welcome.get("chat", [])
        self.assertEqual(
            [message.get("text") for message in carol_history],
            ["Hello everyone"],
        )

    def test_save_list_restore_and_traversal_refused(self) -> None:
        """Verify saving version snapshots, listing versions, path traversal protection, and restoring."""
        c = self._connect()
        send_msg(
            c,
            {
                "t": "hello",
                "room": "persist-room",
                "user": "HostUser",
                "pw": "pw",
                "create": True,
            },
        )
        self._recv_type(c, "welcome")

        # Draw stroke
        send_msg(
            c,
            {
                "t": "stroke",
                "id": "s_saved",
                "s": {"tool": "pen", "color": "#123456", "width": 3, "pts": [[0, 0], [1, 1]]},
            },
        )
        self._recv_type(c, "ack")

        # Save version
        send_msg(c, {"t": "save", "label": "v1"})
        saved_msg = self._recv_type(c, "saved")
        saved_filename = saved_msg.get("file")
        self.assertTrue(saved_filename.endswith("_v1.json"))

        # List versions
        send_msg(c, {"t": "versions"})
        versions_msg = self._recv_type(c, "versions")
        self.assertIn(saved_filename, versions_msg.get("files", []))

        # Attempt path traversal -> Refused with bad_file
        send_msg(c, {"t": "load", "file": "../../etc/passwd"})
        err = self._recv_type(c, "err")
        self.assertEqual(err.get("code"), "bad_file")

        # Clear canvas
        send_msg(c, {"t": "clear"})
        self._recv_type(c, "op")

        # Restore saved version
        send_msg(c, {"t": "load", "file": saved_filename})
        reset_op = self._recv_filtered(
            c, lambda m: m.get("t") == "op" and m.get("k") == "reset"
        )
        restored_strokes = reset_op.get("strokes", [])
        self.assertEqual(len(restored_strokes), 1)
        self.assertEqual(restored_strokes[0]["id"], "s_saved")

    def test_host_leaving_promotes_another_member(self) -> None:
        """Verify that when host departs and grace period expires, next member is promoted to host."""
        self.server.stop()
        self.server = WhiteboardServer(
            host="127.0.0.1",
            port=0,
            boards_dir=self.temp_boards_dir,
            timeout=15.0,
            grace=0.5,  # 0.5s grace for fast testing
        )
        self.server.start()
        self.port = self.server.port

        c_alice = self._connect()
        c_bob = self._connect()

        send_msg(
            c_alice,
            {
                "t": "hello",
                "room": "election-room",
                "user": "Alice",
                "pw": "pw",
                "create": True,
            },
        )
        self._recv_type(c_alice, "welcome")

        send_msg(
            c_bob,
            {
                "t": "hello",
                "room": "election-room",
                "user": "Bob",
                "pw": "pw",
                "create": False,
            },
        )
        self._recv_type(c_bob, "welcome")

        # Alice leaves
        c_alice.close()

        # Wait past grace period
        time.sleep(1.2)

        # Bob should receive notification of host promotion
        def is_bob_host(m: Dict[str, Any]) -> bool:
            if m.get("t") != "users":
                return False
            return any(
                u.get("user") == "Bob" and u.get("role") == "host"
                for u in m.get("users", [])
            )

        bob_users = self._recv_filtered(c_bob, is_bob_host)
        self.assertIsNotNone(bob_users)

    def test_net_auto_reconnects_and_delta(self) -> None:
        """Verify Net auto-reconnects after server disconnect and receives delta welcome."""
        events_q: queue.Queue = queue.Queue()
        session_info = {"token": None, "last_seq": 0}

        def get_hello():
            payload = {
                "t": "hello",
                "room": "auto-reconnect-room",
                "user": "NetUser",
                "pw": "p",
                "create": (session_info["token"] is None),
            }
            if session_info["token"]:
                payload["token"] = session_info["token"]
                payload["last_seq"] = session_info["last_seq"]
            return payload

        net = Net(events_q, "127.0.0.1", self.port, get_hello, reconnect_delay=0.3)
        self.addCleanup(net.stop)

        # 1. Wait for first welcome
        welcome1 = None
        start = time.time()
        while time.time() - start < 4.0:
            ev, data = events_q.get(timeout=2.0)
            if ev == "msg" and data.get("t") == "welcome":
                welcome1 = data
                break

        self.assertIsNotNone(welcome1)
        self.assertEqual(welcome1.get("mode"), "full")
        token = welcome1.get("you", {}).get("token")
        self.assertIsNotNone(token)
        session_info["token"] = token
        session_info["last_seq"] = welcome1.get("seq", 0)

        # 2. Draw a stroke directly on server so seq increases
        room = self.server.rooms["auto-reconnect-room"]
        with room.lock:
            op = {
                "k": "stroke",
                "id": "stroke_delta_1",
                "u": "NetUser",
                "s": {"tool": "pen", "color": "#000000", "width": 2, "pts": [[1, 1], [2, 2]]},
            }
            room.commit(op)

        # 3. Server forcibly kills NetUser's socket connection
        with self.server.clients_lock:
            for client_session in list(self.server.clients):
                if client_session.user == "NetUser":
                    client_session.close()

        # 4. Wait for Net to auto-reconnect and receive second welcome with delta ops
        welcome2 = None
        start = time.time()
        while time.time() - start < 6.0:
            ev, data = events_q.get(timeout=3.0)
            if ev == "msg" and data.get("t") == "welcome":
                welcome2 = data
                break

        self.assertIsNotNone(welcome2)
        self.assertEqual(welcome2.get("mode"), "delta")
        ops = welcome2.get("ops", [])
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].get("id"), "stroke_delta_1")

    def test_net_emits_err_then_fail_on_wrong_password(self) -> None:
        """Verify Net emits 'msg' with err, then 'fail' on incorrect room password."""
        c_creator = self._connect()
        send_msg(
            c_creator,
            {
                "t": "hello",
                "room": "pw-fail-room",
                "user": "HostAlice",
                "pw": "correct_password",
                "create": True,
            },
        )
        self._recv_type(c_creator, "welcome")

        events_q: queue.Queue = queue.Queue()

        def get_hello():
            return {
                "t": "hello",
                "room": "pw-fail-room",
                "user": "WrongUser",
                "pw": "WRONG_PASSWORD",
                "create": False,
            }

        net = Net(events_q, "127.0.0.1", self.port, get_hello, reconnect_delay=0.3)
        self.addCleanup(net.stop)

        received_events = []
        start = time.time()
        while time.time() - start < 4.0:
            try:
                ev, data = events_q.get(timeout=2.0)
                received_events.append((ev, data))
                if ev == "fail":
                    break
            except queue.Empty:
                break

        event_types = [ev for ev, data in received_events]
        self.assertIn("msg", event_types)
        err_msg = next(data for ev, data in received_events if ev == "msg")
        self.assertEqual(err_msg.get("t"), "err")
        self.assertEqual(err_msg.get("code"), "bad_password")
        self.assertIn("fail", event_types)
        self.assertFalse(net.welcomed)


class TestBoardState(unittest.TestCase):
    """Verifies client-side BoardState ordering, buffering, and optimistic echo."""

    def test_apply_op_duplicate_gap_drain(self) -> None:
        board = BoardState()
        board.seq = 10

        # 1. Duplicate op (seq <= 10) -> ignored
        dup_op = {
            "seq": 10,
            "k": "stroke",
            "id": "s10",
            "s": {"tool": "pen", "pts": [[0, 0]]},
        }
        effects, need_sync = board.apply_op(dup_op)
        self.assertEqual(effects, [])
        self.assertFalse(need_sync)
        self.assertEqual(board.seq, 10)

        # 2. Sequence gap (seq == 12 > seq + 1) -> buffered, returns need_sync=True
        gap_op = {
            "seq": 12,
            "k": "stroke",
            "id": "s12",
            "s": {"tool": "pen", "pts": [[2, 2]]},
        }
        effects, need_sync = board.apply_op(gap_op)
        self.assertEqual(effects, [])
        self.assertTrue(need_sync)
        self.assertIn(12, board.buffer)
        self.assertEqual(board.seq, 10)

        # 3. Next in-order op (seq == 11) -> applied, then drains buffered seq 12
        inorder_op = {
            "seq": 11,
            "k": "stroke",
            "id": "s11",
            "s": {"tool": "pen", "pts": [[1, 1]]},
        }
        effects, need_sync = board.apply_op(inorder_op)
        self.assertFalse(need_sync)
        self.assertEqual(board.seq, 12)
        self.assertNotIn(12, board.buffer)
        self.assertIn("s11", board.strokes)
        self.assertIn("s12", board.strokes)
        added_ids = [val for eff, val in effects if eff == "add"]
        self.assertIn("s11", added_ids)
        self.assertIn("s12", added_ids)

    def test_optimistic_echo_and_fingerprint(self) -> None:
        board = BoardState()
        self.assertEqual(board.seq, 0)

        stroke_msg = {
            "t": "stroke",
            "id": "my_stroke",
            "s": {
                "tool": "pen",
                "color": "#000000",
                "width": 2,
                "pts": [[0, 0], [10, 10]],
            },
        }
        board.add_local(stroke_msg["s"], stroke_msg)
        self.assertIn("my_stroke", board.pending)
        self.assertTrue(board.strokes["my_stroke"].get("p"))

        server_op = {
            "seq": 1,
            "k": "stroke",
            "id": "my_stroke",
            "u": "Alice",
            "s": {
                "tool": "pen",
                "color": "#000000",
                "width": 2,
                "pts": [[0, 0], [10, 10]],
            },
        }
        effects, need_sync = board.apply_op(server_op)
        self.assertFalse(need_sync)
        self.assertNotIn("my_stroke", board.pending)
        self.assertFalse(board.strokes["my_stroke"].get("p", False))

        fp1 = board.fingerprint()
        self.assertTrue(isinstance(fp1, str) and len(fp1) == 64)


if __name__ == "__main__":
    unittest.main()
