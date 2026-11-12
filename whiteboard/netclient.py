"""Client-side TCP networking thread and socket controller (zero GUI code).

Computer Networks Lab - LAN Collaborative Whiteboard
Module: whiteboard.netclient

Role & Architecture:
--------------------
In GUI-driven network applications, blocking network calls (`connect`, `recv`,
`sendall`) must NEVER be executed on the main event thread. Doing so freezes the
user interface and stops window redrawing.

`netclient.py` implements `Net`, a decoupled, thread-safe network client:
1. Thread-Safe Event Queue:
   - Emits structured event tuples onto `events_queue`:
     - `("conn", None)`: TCP connection established.
     - `("msg", dict)`: Incoming framed message from server.
     - `("disc", reason)`: Socket disconnected (e.g. Broken pipe or timeout).
     - `("fail", reason)`: Fatal failure when connection could not be established.
2. Dynamic Re-Handshake (`get_hello`):
   - Accepts a callable `get_hello()` executed dynamically on every connection and
     reconnection attempt. This ensures reconnects transmit the latest secret token
     and highest applied `last_seq` for delta synchronization.
3. Automatic Reconnection:
   - If the connection drops after a successful handshake (`self.welcomed = True`),
     `Net` automatically attempts reconnection every 2 seconds.
   - If the initial connection fails before ever welcoming, `Net` emits `("fail", reason)`
     and halts.
4. Non-Blocking Outbound Sender & Heartbeat:
   - A dedicated sender thread drains `outbound_queue` so `send()` returns immediately.
   - Automatically transmits `{"t": "ping", "ts": ...}` every 4 seconds when idle.
   - Enforces a 12-second read timeout, treating silent sockets as dead links.
"""

from __future__ import annotations

import os
import queue
import socket
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

# Support running directly or as a module
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from whiteboard.protocol import (
        PORT_DEFAULT,
        ProtocolError,
        recv_msg,
        send_msg,
    )
except ImportError:
    from protocol import (  # type: ignore
        PORT_DEFAULT,
        ProtocolError,
        recv_msg,
        send_msg,
    )


class Net:
    """Manages background TCP socket connection, framing, and automatic reconnection."""

    def __init__(
        self,
        events_queue: queue.Queue[tuple[str, Any]],
        host: str,
        port: int,
        get_hello: Callable[[], Dict[str, Any]],
        reconnect_delay: float = 2.0,
    ) -> None:
        """Initializes and starts the network client worker threads.

        Args:
            events_queue: Thread-safe queue where Net deposits ('conn', 'msg', 'disc', 'fail') events.
            host: Server hostname or IP address.
            port: Server TCP port.
            get_hello: Callable returning the hello dictionary for handshakes and reconnects.
            reconnect_delay: Seconds to wait between auto-reconnect attempts (default: 2.0).
        """
        self.events_queue: queue.Queue[tuple[str, Any]] = events_queue
        self.host: str = host
        self.port: int = port
        self.get_hello: Callable[[], Dict[str, Any]] = get_hello
        self.reconnect_delay: float = reconnect_delay

        # Lifecycle & state flags
        self.welcomed: bool = False
        self.connected: bool = False
        self.running: bool = True

        self.sock: Optional[socket.socket] = None
        self._sock_lock = threading.Lock()
        self.outbound_queue: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue(maxsize=2000)

        # Worker threads
        self._receiver_thread = threading.Thread(
            target=self._run_receiver, name="Net-Receiver", daemon=True
        )
        self._sender_thread = threading.Thread(
            target=self._run_sender, name="Net-Sender", daemon=True
        )

        self._receiver_thread.start()
        self._sender_thread.start()

    def send(self, obj: Dict[str, Any]) -> bool:
        """Enqueues an object to be transmitted to the server.

        Args:
            obj: Message dictionary to transmit.

        Returns:
            bool: False if client is currently offline or queue is full; True otherwise.
        """
        if not self.connected or not self.running:
            return False
        try:
            self.outbound_queue.put_nowait(obj)
            return True
        except queue.Full:
            return False

    def stop(self) -> None:
        """Gracefully terminates worker threads and closes socket."""
        self.running = False
        self.connected = False

        with self._sock_lock:
            if self.sock:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None

        try:
            self.outbound_queue.put_nowait(None)
        except Exception:
            pass

    def _run_receiver(self) -> None:
        """Main connection and reception loop with automatic reconnect capability."""
        while self.running:
            # 1. Establish TCP Connection
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(12.0)

            try:
                sock.connect((self.host, self.port))
            except Exception as exc:
                sock.close()
                if not self.welcomed:
                    # Never successfully joined before -> fail immediately
                    self.events_queue.put(("fail", f"Connection failed: {exc}"))
                    break
                else:
                    # Dropped after join -> wait and attempt reconnect
                    self.events_queue.put(("disc", f"Reconnect failed: {exc}"))
                    time.sleep(self.reconnect_delay)
                    continue

            with self._sock_lock:
                self.sock = sock
                self.connected = True

            self.events_queue.put(("conn", None))

            # 2. Dispatch dynamic HELLO handshake
            try:
                hello_payload = self.get_hello()
                send_msg(sock, hello_payload)
            except Exception as exc:
                self._teardown_socket(sock)
                if not self.welcomed:
                    self.events_queue.put(("fail", f"Handshake transmission failed: {exc}"))
                    break
                else:
                    self.events_queue.put(("disc", f"Handshake transmission failed: {exc}"))
                    time.sleep(self.reconnect_delay)
                    continue

            # 3. Read loop with 12s dead-link detection
            disconnect_reason = "Connection terminated"
            while self.running and self.connected:
                try:
                    sock.settimeout(12.0)
                    msg = recv_msg(sock)
                except socket.timeout:
                    disconnect_reason = "Read timeout (12s silent socket)"
                    break
                except (ConnectionError, ProtocolError, OSError) as exc:
                    disconnect_reason = str(exc)
                    break

                if not msg:
                    disconnect_reason = "Server closed socket"
                    break

                # If server sent welcome message, mark joined
                if msg.get("t") == "welcome":
                    self.welcomed = True

                self.events_queue.put(("msg", msg))

            # 4. Handle Disconnection
            self._teardown_socket(sock)

            if not self.running:
                break

            self.events_queue.put(("disc", disconnect_reason))

            if not self.welcomed:
                # Failed before ever being welcomed (e.g. Bad password / room rejected)
                self.events_queue.put(("fail", disconnect_reason))
                break
            else:
                # Reconnect automatically every reconnect_delay seconds
                time.sleep(self.reconnect_delay)

    def _teardown_socket(self, sock: socket.socket) -> None:
        """Closes a socket and resets connection state."""
        with self._sock_lock:
            self.connected = False
            if self.sock == sock:
                self.sock = None
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _run_sender(self) -> None:
        """Drains outbound queue and transmits automatic heartbeats every 4s."""
        while self.running:
            try:
                msg = self.outbound_queue.get(timeout=4.0)
            except queue.Empty:
                # 4-second idle heartbeat ping
                if self.connected:
                    with self._sock_lock:
                        sock = self.sock
                    if sock and self.connected:
                        try:
                            send_msg(sock, {"t": "ping", "ts": time.time()})
                        except OSError:
                            pass
                continue

            if msg is None:
                break

            if self.connected:
                with self._sock_lock:
                    sock = self.sock
                if sock and self.connected:
                    try:
                        send_msg(sock, msg)
                    except OSError:
                        pass
