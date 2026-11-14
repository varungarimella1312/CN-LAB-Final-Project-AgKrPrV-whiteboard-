# LAN-Based Multi-User Collaborative Whiteboard

**Computer Networks Lab Project**  
*Pure Python 3.10+ Standard Library Implementation (Zero External Dependencies)*

---

## 1. Project Overview & Architecture

This project is a high-performance, real-time collaborative whiteboard designed for local area networks (LANs). It operates **completely offline** with no internet connection, external web frameworks, or third-party packages.

```
                    +------------------------------------+
                    |        Authoritative Server        |
                    |  - Global Sequence Number (seq)    |
                    |  - Thread-Safe Rooms (RLock)       |
                    |  - Inactivity Reaper & Persistence |
                    +------------------------------------+
                                ^     |     ^
                         TCP    |     |     | TCP
                      Sockets   |     |     | Sockets
                                v     v     v
             +------------------+     |     +------------------+
             |                        |                        |
             v                        v                        v
+-----------------------+  +-----------------------+  +-----------------------+
|    Client A (Host)    |  |   Client B (Editor)   |  |   Client C (Viewer)   |
| - Tkinter GUI (View)  |  | - Tkinter GUI (View)  |  | - Tkinter GUI (View)  |
| - BoardState (Model)  |  | - BoardState (Model)  |  | - BoardState (Model)  |
| - Net Client (Worker) |  | - Net Client (Worker) |  | - Net Client (Worker) |
+-----------------------+  +-----------------------+  +-----------------------+
```

### File Hierarchy
```
whiteboard/
├── protocol.py         # Wire protocol constants, framing, encode/decode routines
├── boardstate.py       # Client-side canvas replica (pure data, zero GUI code)
├── netclient.py        # Non-blocking TCP client worker threads (zero GUI code)
├── server.py           # Multi-threaded authoritative TCP server (runnable)
├── client.py           # Tkinter graphical user interface client (runnable)
├── test_integration.py # Headless integration tests using real loopback sockets
└── README.md           # Architecture specification, setup guide, and viva Q&A
```

---

## 2. Network Protocol Specification & Framing

### Why TCP Over UDP?
1. **Reliability (No Lost Strokes)**: Canvas operations represent discrete state mutations. In UDP, packet loss results in permanent canvas divergence between clients. TCP guarantees delivery via acknowledgments and automatic retransmission.
2. **Strict In-Order Delivery**: Whiteboard operations must be applied sequentially (e.g., drawing, drawing over, clearing, undoing). TCP sequence numbers enforce strict byte-stream ordering.
3. **Flow & Congestion Control**: TCP sliding windows prevent sender bursts from overflowing receiving buffers or saturating the LAN switch.

### Framing Mechanism (Solving "Sticky Packets" / Fragmentation)
TCP is a byte-stream protocol with no intrinsic application message boundaries. Operating systems segment or coalesce packets (Nagle's algorithm). We enforce **fixed-length length-prefix framing**:

```
+-----------------------------------+---------------------------------------+
|     Length Prefix (4 Bytes)       |       JSON Payload (UTF-8 Bytes)      |
|    Big-Endian uint32 ('>I')       |       {"t": "stroke", ...}            |
+-----------------------------------+---------------------------------------+
```

1. **Sender**: Encodes dictionary to compact UTF-8 JSON; prepends a 4-byte big-endian unsigned integer representing payload byte count $N$; invokes `sock.sendall()`.
2. **Receiver**: Loops `sock.recv()` until exactly 4 bytes are received; unpacks $N$; loops `sock.recv()` until exactly $N$ payload bytes arrive; decodes JSON.

### Message Specification Table

| Type (`t`) | Direction | Key Fields | Description |
|:---|:---:|:---|:---|
| `hello` | $C \to S$ | `room?, user, pw, create?, is_host?, host_code?, token?, last_seq?` | Initial handshake; generated-room clients send host status and host code when applicable. |
| `welcome` | $S \to C$ | `room, seq, host, you, users, chat, canvas, mode, reconnected?, strokes \| ops` | Confirms join; delivers full snapshot or delta ops and identifies returning usernames. |
| `stroke` | $C \to S$ | `id, s: {tool, color, width, pts, text?, bg?}` | Commits finished drawing element or sticky note. |
| `ack` | $S \to C$ | `id, seq` | Unicast acknowledgment to stroke author. |
| `op` | $S \to C$ | `seq, k: "stroke"\|"vis"\|"reset", u, ...` | Authoritative sequenced state change broadcast to all. |
| `part` | $C \rightleftharpoons S$ | `sid, tool, color, width, mode, pts` | Live in-progress preview (echo-suppressed broadcast). |
| `cursor` | $C \rightleftharpoons S$ | `u, color, x, y` | Ephemeral mouse pointer broadcast (throttled). |
| `undo` / `redo` | $C \to S$ | *(none)* | Reverts/restores caller's last drawing action. |
| `clear` | $C \to S$ | *(none)* | Hides all canvas strokes (Host only). |
| `sync` | $C \to S$ | `last_seq` | Requests missing ops on sequence gap detection. |
| `chat` | $C \rightleftharpoons S$ | `id?, user, to?, text, ts` | Group messages are broadcast to the room; private messages are delivered only to the sender and the selected active participant. Both use server timestamps and appear in chronological history. |
| `save` | $C \to S$ | `label` | Atomically writes version snapshot to disk (Host only). |
| `versions` | $C \to S$ | *(none)* | Queries list of saved version files. |
| `load` | $C \to S$ | `file` | Restores canvas from version file (Host only). |
| `setrole` | $C \to S$ | `user, role: "editor"\|"viewer"` | Modifies member permissions (Host only). |
| `ping` / `pong`| $C \rightleftharpoons S$ | `ts` | Keepalive heartbeat and latency calculation. |

---

## 3. Concurrency & Threading Architecture

### Server Concurrency Model
- **Accept Thread**: Continuously accepts new client TCP sockets.
- **Per-Client Reader Thread**: Decodes length-prefixed messages and dispatches handlers.
- **Per-Client Writer Thread**: Drains a bounded `queue.Queue(maxsize=5000)`. Sends use `put_nowait()`; slow or unresponsive clients are disconnected immediately to prevent bufferbloat.
- **TCP_NODELAY**: Enabled on all sockets to disable Nagle's algorithm for low-latency interactive drawing.
- **Room Lock (`threading.RLock`)**: Every state mutation, sequence increment, and broadcast within a room is protected under that room's reentrant lock.
- **Reaper Thread**: Runs every 0.2s:
  - Disconnects clients inactive for `--timeout` seconds (default 15s) and marks them offline.
  - Purges offline members after `--grace` seconds (default 120s).
  - Promotes earliest-joined member if the host departs.
  - Triggers periodic autosaves and deletes empty rooms after 30 minutes.

### Client Concurrency Model
- **Main GUI Thread**: Owns Tkinter canvas and controls; never executes blocking socket calls.
- **Net Client Receiver Thread**: Connects socket, sends dynamic `get_hello()`, reads frames, and pushes `("conn", "msg", "disc", "fail")` events to `events_queue`.
- **Net Client Sender Thread**: Drains outbound queue and transmits keepalive pings every 4s.
- **Event Pump**: Polled every 15 ms via `root.after(15, self._pump_network_events)` to process network events directly on the GUI thread. Redundant cursor updates are coalesced per participant.

---

## 4. Key Distributed Systems Algorithms

### 1. Global Sequencing & Eventual Consistency
The server maintains a strictly monotonic sequence counter (`seq`). When any mutation occurs (`stroke`, `vis`, `reset`), the room lock is acquired, `seq` is incremented, and the resulting `op` is broadcast to all participants. Because every client applies ops in strict sequence order, all canvas replicas are guaranteed to converge.

### 2. Optimistic Local Echo
When a user draws a stroke:
1. `BoardState.add_local()` renders the stroke immediately with a pending flag (`"p": True`).
2. The user sees instant, lag-free visual feedback without waiting for network latency.
3. When the server broadcasts the committed `op`, the pending flag is cleared. If the server assigned an ordering different from local draw order, `strokes.move_to_end(sid)` reorders the canvas and redraws.

### 3. Gap Detection & Successor Draining
Clients verify incoming op sequence numbers:
- `op.seq <= local_seq`: Duplicate message; ignored.
- `op.seq == local_seq + 1`: In-order op; applied immediately, followed by draining any consecutive buffered successors.
- `op.seq > local_seq + 1`: Sequence gap; op is stored in `buffer`, and client issues a `sync` request to retrieve missing delta ops.

### 4. Deduplication & Idempotence
The server tracks `Room.seen` mapping `stroke_id -> seq`. If a client re-transmits a stroke after a network reconnect, the server detects the duplicate, skips re-application, and returns an `ack` containing the original sequence number.

### 5. Isolated Per-User Undo/Redo
- Undo and redo operate exclusively on the caller's actions.
- Stacks store `("s", stroke_id)` or `("c", [ids])` (clear history).
- Operations emit a sequenced `vis` op (`hide: [...]`, `show: [...]`).
- If an entry produces no net visual change (e.g. stroke was already hidden by a clear), the stack skips it iteratively until an actionable stroke is found.
- Clear canvas is restricted to the host; it hides all visible strokes in one `vis` op and pushes `("c", ids)` onto the host's undo stack, enabling undo/redo of the clear.

### 6. Path-Traversal Proof Versioning
When a host saves a version, the state is written to `boards/<room>/<timestamp>_<label>.json` atomically using a temporary file (`.tmp`) and `os.replace`. When restoring, the server uses `os.path.basename()` and verifies that the file exists in the room directory, strictly rejecting path traversal attacks such as `../../etc/passwd`.

---

## 5. How to Run & Verify

### Starting the Server
```bash
python3 whiteboard/server.py --host 0.0.0.0 --port 5050
```
The server starts without terminal input and prints a unique four-digit room code, four-digit host code, and four-digit room password. Share the room password with participants; only the host should use the host code.

The server automatically detects your outbound LAN IP via an unreachable UDP socket to `10.255.255.255` (no packets transmitted). The room code and password are displayed in the client after connection.

### Starting Clients
```bash
# Select Host or Participant in the GUI. The host enters the host code
# and room password; participants enter only the room password.
# Connect to local machine:
python3 whiteboard/client.py --host 127.0.0.1 --port 5050

# Connect across LAN:
python3 whiteboard/client.py --host 192.168.1.X --port 5050
```

### Running the Headless Integration Test Suite
```bash
python3 whiteboard/test_integration.py
```

---

## 6. Lab Viva Q&A Cheat Sheet

### Q1: Why did you choose TCP instead of UDP for the whiteboard?
> **Answer**: Whiteboard operations represent state mutations that cannot be lost or reordered without corrupting the drawing. TCP provides guaranteed delivery via acknowledgments and automatic retransmission, strict sequence ordering, and flow control. UDP provides best-effort delivery with no packet ordering, which would require reimplementing reliability and reassembly buffers at the application layer.

### Q2: Why is length-prefix framing necessary in TCP?
> **Answer**: TCP is a stream-oriented protocol (RFC 793) with no concept of message boundaries. The OS network stack may segment a single large message across multiple packets or coalesce multiple small messages into a single packet via Nagle's algorithm. Length-prefix framing prepends each payload with a fixed 4-byte big-endian integer denoting payload byte count, allowing the receiver to reliably delineate and reconstruct complete messages.

### Q3: How do you prevent the GUI from freezing during network calls?
> **Answer**: All blocking socket operations (`connect`, `recv`, `sendall`) run on background worker threads managed by `Net`. The Tkinter GUI main thread communicates with the network layer via a thread-safe `queue.Queue`. The GUI polls this queue every 15 ms using `root.after()`, keeping window redrawing and user input responsive at all times.

### Q4: How does your architecture ensure all clients see the exact same drawing order?
> **Answer**: We use an authoritative central server. Every drawing action is submitted to the server, which acquires the room's `RLock`, assigns a strictly monotonic sequence number (`seq`), records the op in the room log, and broadcasts the op to all online members. Every client applies operations strictly in sequence order, ensuring eventual consistency across all replicas.

### Q5: What is optimistic UI rendering and how does your client handle it?
> **Answer**: When a user draws a stroke, `BoardState.add_local()` renders the stroke immediately with a pending flag (`"p": True`) before the server acknowledges it, eliminating perceived network latency. When the server's sequenced `op` arrives, the pending flag is cleared. If other clients drew strokes concurrently that were sequenced before this stroke by the server, the client adjusts the z-order and redraws to match authoritative server order.

### Q6: How does per-user undo/redo work without breaking other users' strokes?
> **Answer**: Each user has dedicated `undo_stack` and `redo_stack` structures storing `("s", stroke_id)` or `("c", [ids])`. Undo does not delete data; it commits a sequenced `vis` op with `hide: [stroke_id]`. Redo emits `vis` with `show: [stroke_id]`. Because strokes are toggled rather than deleted, z-order is preserved and peers' strokes are unaffected.

### Q7: How do you handle dead or half-open TCP connections?
> **Answer**: If a client abruptly loses network connectivity (e.g. Wi-Fi dropped), TCP sockets on the server can remain open indefinitely. The server runs a background reaper thread that monitors client activity timestamps: clients with no network traffic for `--timeout` seconds (default 15s) are forcibly closed and marked offline. Clients periodically transmit a keepalive `ping` every 4 seconds to maintain active status when idle.

### Q8: What prevents a malicious client from performing a path-traversal attack during file restoration?
> **Answer**: In `_handle_load`, the requested filename is sanitized using `os.path.basename()` to strip directory paths. The server verifies that the sanitized name exactly matches the input, ends in `.json`, and is present in the whitelist of files returned by `os.listdir(room_dir)`. Traversal strings like `../../etc/passwd` are rejected with error code `"bad_file"`.

### Q9: What happens if a slow client cannot keep up with high-frequency stroke broadcasts?
> **Answer**: Each client connection has a dedicated writer thread draining a bounded `queue.Queue(maxsize=5000)`. When broadcasting, the server uses `send_queue.put_nowait()`. If a client's queue fills up, the server catches `queue.Full` and immediately disconnects that client, preventing bufferbloat and protecting the server and other participants from degradation.

### Q10: How do reconnecting clients recover missed operations without redrawing the entire canvas?
> **Answer**: Reconnecting clients submit their secret session token and their last known sequence number (`last_seq`) in their `hello` handshake. The client stores the token in the current OS user's application-data folder, keyed by server and username (never storing the room password), so the same user can reclaim the session after returning to login or restarting the client. The server also retains the room's username history and labels returning usernames as reconnected. If `last_seq` is valid, the server replies with `mode: "delta"` containing only operations committed since that sequence (`room.log[last_seq:]`), allowing the client to catch up incrementally without requesting a full canvas snapshot.
