# LAN Collaborative Whiteboard — Video Presentation & Demo Script
**University Computer Networks Lab Project**  
**Total Duration:** ~8–10 Minutes (~2 Minutes per Speaker)  
**Format:** Live Screen Recording + Audio Narration / Camera

---

## Overview & Team Allocation Guide

| Member | Primary Module & Area | Core Design Choice Discussed | Tricky Bug & Resolution |
| :--- | :--- | :--- | :--- |
| **Member 1** | `protocol.py` & Network Architecture | Length-prefix binary framing (`>I` uint32) over raw TCP | TCP packet fragmentation / sticky packet stream boundary errors |
| **Member 2** | `server.py` & Multi-threading | Decoupled reader/writer threads with bounded `Queue` & `TCP_NODELAY` | Slow client send queue bufferbloat & graceful socket shutdown race |
| **Member 3** | `boardstate.py` & State Machine Replication | Authoritative sequence numbering (`seq`) + out-of-order gap buffering | Z-order displacement & optimistic unacked stroke race conditions |
| **Member 4** | `netclient.py`, `client.py` & Fault Recovery | Asynchronous event queue decoupled from Tkinter GUI loop | Tkinter thread crash & auto-reconnect delta synchronization |

---

## Video Script

### [00:00 - 02:00] Speaker 1: Architecture, Protocol & Framing
* **Speaker Name:** `[MEMBER 1 NAME]`
* **Roll / ID Number:** `[MEMBER 1 ROLL NUMBER]`
* **Module Owned:** `whiteboard/protocol.py` & Transport Layer Architecture
* **Visual On-Screen:** Architecture diagram (`docs/Technical_Documentation.pdf` Section 2) $\rightarrow$ Code walk in `protocol.py` (`encode`, `recv_exact`, `recv_msg`).

#### Script (Spoken Audio):
> "Hello everyone, my name is **`[MEMBER 1 NAME]`**, and I will kick off our presentation of our LAN-based Multi-User Collaborative Whiteboard.
>
> In our Computer Networks lab, our objective was to build a zero-dependency, real-time collaborative system that runs entirely on an isolated Local Area Network with **zero internet connection**.
>
> **1. Architectural Decision: TCP vs UDP**  
> A fundamental networking decision was choosing our transport protocol. While video games and live streaming often utilize UDP for raw speed, a collaborative whiteboard is a **strictly state-dependent application**. A dropped stroke packet in UDP would corrupt the shared canvas for all participants. Therefore, we selected **TCP sockets** to leverage connection-oriented reliability, end-to-end checksum verification, flow control, and in-order byte stream delivery.
>
> **2. The Protocol Framing Problem**  
> Because TCP is a continuous byte stream with no intrinsic record delimiters, the OS network stack may fragment a single large message across multiple TCP segments, or coalesce multiple small JSON messages into a single TCP packet. To solve this, I designed our application-level framing in `protocol.py`. 
>
> Every message is encoded as a **4-byte big-endian unsigned integer prefix (`>I`)** followed immediately by $N$ bytes of UTF-8 encoded JSON. 
>
> **3. Tricky Bug I Solved**  
> During our initial testing on localhost, `recv(4096)` seemed to work. But when we tested across two physical laptops with higher latency, clients crashed with JSON decode errors! The bug occurred because `recv()` returned partial payloads. I solved this by implementing `recv_exact(sock, n)`, which executes in a deterministic loop, maintaining an accumulator buffer until exactly $n$ bytes are received, raising a clean `ConnectionError` on EOF.
>
> I will now hand over to **`[MEMBER 2 NAME]`** to walk through our multi-threaded server architecture."

---

### [02:00 - 04:00] Speaker 2: Server Threading, Room Locks & Scalability
* **Speaker Name:** `[MEMBER 2 NAME]`
* **Roll / ID Number:** `[MEMBER 2 ROLL NUMBER]`
* **Module Owned:** `whiteboard/server.py` & Concurrency Architecture
* **Visual On-Screen:** Server console terminal startup $\rightarrow$ LAN IP detection log $\rightarrow$ Threading diagram in `server.py` (`ClientSession`, `Room.lock`, `reaper_loop`).

#### Script (Spoken Audio):
> "Thank you, `[MEMBER 1 NAME]`. My name is **`[MEMBER 2 NAME]`**, and I was responsible for designing the centralized multi-threaded server in `server.py`.
>
> **1. Server Threading Model**  
> A major challenge in network programming is ensuring that one slow or malicious client cannot degrade the experience for other participants. If the server broadcasts to 10 clients sequentially on a single thread, a stalled TCP window on client 3 would block packets from reaching clients 4 through 10.
>
> To eliminate this vulnerability, I implemented a **three-tier threading architecture**:
> 1. One dedicated **Acceptor Thread** listening for incoming TCP handshakes on port `5050`.
> 2. For every connected client, a dedicated **Reader Thread** and a separate **Writer Thread** connected via a bounded `queue.Queue(maxsize=5000)`.
> 3. A background **Reaper Daemon** running every second to prune dead connections that exceed our 15-second timeout.
>
> Broadcasters never perform blocking socket calls; they execute `send_queue.put_nowait()`. Furthermore, we enable `TCP_NODELAY` on every accepted socket to disable Nagle’s algorithm, achieving sub-10 millisecond interactive latencies on LAN.
>
> **2. Tricky Bug I Solved**  
> One particularly tricky bug occurred when an offline client had an unstable Wi-Fi adapter. Its send queue filled up, causing memory consumption to spike and triggering lock contention across `Room.lock`. 
>
> To fix this, I made queue enqueue operations non-blocking: if a client's send queue is full, the server immediately severs that specific socket connection without holding any room locks. Additionally, I resolved a graceful shutdown deadlock where reader threads hung waiting for sockets to close before writer threads finished flushing fatal error frames, by introducing a coordinated sentinel flush mechanism.
>
> Next, **`[MEMBER 3 NAME]`** will explain how we ensure identical canvas state across all machines."

---

### [04:00 - 06:00] Speaker 3: Distributed Synchronization & Per-User Undo
* **Speaker Name:** `[MEMBER 3 NAME]`
* **Roll / ID Number:** `[MEMBER 3 ROLL NUMBER]`
* **Module Owned:** `whiteboard/boardstate.py` & Synchronization Engine
* **Visual On-Screen:** Side-by-side terminal / client windows $\rightarrow$ `boardstate.py` data structure $\rightarrow$ Simultaneous drawing convergence demonstration $\rightarrow$ Undo/redo demonstration.

#### Script (Spoken Audio):
> "Thanks, `[MEMBER 2 NAME]`. My name is **`[MEMBER 3 NAME]`**, and I designed the distributed state machine replication engine in `boardstate.py`.
>
> **1. Authoritative Sequencing & State Replication**  
> In a multi-user collaborative environment, network latency causes users to draw strokes at overlapping times. Without strict ordering, peer whiteboards diverge.
>
> We resolved this by adopting an **Authoritative Central Log architecture**:
> - The server assigns a monotonic global sequence number (`seq = 1, 2, 3...`) to every committed operation while holding an internal `threading.RLock`.
> - Clients maintain a local replica containing an `OrderedDict` of strokes, the highest applied sequence number, and a pending queue.
> - When a local user draws, we provide immediate visual responsiveness through **optimistic local echo**. Once the server acknowledges the stroke with an authoritative `seq`, the client confirms its position.
>
> **2. Per-User Undo/Redo Under Concurrency**  
> A classic problem in collaborative drawing is Undo. In a naive implementation, pressing Undo simply deletes the most recent global stroke—meaning user Alice might accidentally delete Bob’s drawing!
>
> We implemented **Per-User Isolated Undo Stacks**. When Alice presses `Ctrl+Z`, the server inspects Alice's private stack and emits a sequenced visibility operation (`vis`) with `hide: [stroke_id]`. This hides only Alice's stroke while preserving the drawing order and other users' artwork. If the host executes a canvas clear, the host can undo the clear to restore all strokes atomically.
>
> **3. Tricky Bug I Solved**  
> When a client experienced transient Wi-Fi packet drops, it occasionally received operation `seq=8` while its local clock was at `seq=6`. In our early prototype, this caused an unhandled gap exception. 
>
> I solved this by adding an out-of-order reassembly buffer in `boardstate.py`. When a gap is detected (`op_seq > self.seq + 1`), the client stages the operation, requests a delta sync from the server (`{"t": "sync", "last_seq": 6}`), and automatically drains all buffered successors once the missing operations arrive.
>
> Now, **`[MEMBER 4 NAME]`** will demonstrate the client GUI and fault recovery."

---

### [06:00 - 08:00] Speaker 4: Client GUI, Features & Live Fault Recovery
* **Speaker Name:** `[MEMBER 4 NAME]`
* **Roll / ID Number:** `[MEMBER 4 ROLL NUMBER]`
* **Module Owned:** `whiteboard/netclient.py` & `whiteboard/client.py`
* **Visual On-Screen:** Live GUI screen recording: Pen, Shapes, Sticky Notes, Color Picker, Chat, Presentation Mode toggle $\rightarrow$ Abrupt Wi-Fi toggle showing auto-reconnection.

#### Script (Spoken Audio):
> "Thank you, `[MEMBER 3 NAME]`. My name is **`[MEMBER 4 NAME]`**, and I developed the GUI client in `client.py` and the network client worker thread in `netclient.py`.
>
> **1. Zero-Dependency Tkinter & Thread Decoupling**  
> In accordance with our Computer Networks lab constraints, our GUI is built strictly with standard Python `tkinter`—no third-party UI frameworks. 
>
> Because Tkinter is single-threaded and crashes if GUI widgets are manipulated from background worker threads, I designed an event queue architecture. Our `Net` networking thread runs in the background and pushes raw network tuples into a `queue.Queue`. The GUI thread executes `root.after(30, self._pump_network_events)` to safely process network events on the main UI loop without frame drops or lag.
>
> **2. Live Ephemeral Preview vs Committed Strokes**  
> While a user is dragging their mouse, broadcasting full committed objects is too heavy. Instead, we stream lightweight ephemeral `part` packets every 40 milliseconds, alongside cursor position updates every 50 milliseconds. Once the mouse is released, a single immutable `stroke` is committed to the server log.
>
> **3. Standout Features & Reconnection Demo**  
> As you can see on screen, our client supports:
> - Pen, Eraser, Line, Rectangle, Oval, Text, and **Sticky Notes**.
> - Real-time group chat with server-synchronized timestamps.
> - Host privilege management: Setting users to Viewer or Editor, saving board versions, and toggling **Presentation Mode**, which locks non-hosts into view-only mode with a banner.
>
> **4. Tricky Bug I Solved**  
> What happens if a user accidentally unplugs their Ethernet cable or closes their laptop lid? 
>
> I implemented **automatic token-based session recovery** in `netclient.py`. When a client joins, the server issues a cryptographically secure 16-byte session token. If the socket abruptly drops, `netclient.py` intercepts the error, updates the UI to 'Reconnecting...', and re-establishes the TCP connection using the saved token and `last_seq`. The server validates the token, re-attaches the existing member session, and transmits only the delta operations missed while disconnected.
>
> To conclude: our project proves that a production-grade, highly reliable, and responsive collaborative system can be engineered with pure standard library networking primitives. Thank you for your time!"

---

## Technical Q&A / Viva Cheat Sheet (Quick Answers for Speakers)

1. **Why not WebSockets or HTTP?**  
   *Answer:* WebSockets and HTTP introduce significant protocol overhead (framing headers, handshakes, masking keys, HTTP parsing). Raw TCP sockets provide minimal latency and allow us to demonstrate fundamental network layer concepts like byte-stream framing and socket lifecycle management directly.
2. **What happens during simultaneous drawing conflicts?**  
   *Answer:* The central server enforces a strict total ordering via `Room.lock` and assigns a unique, monotonic sequence number (`seq`). Drawing order is determined by server arrival time, guaranteeing deterministic canvas convergence across all clients.
3. **How does Presentation Mode work across the network?**  
   *Answer:* The host sends `{"t": "present", "on": true}`. The server sets `room.presentation_mode = True` and broadcasts `{"t": "present", "on": true}`. On non-host clients, drawing buttons are disabled, mouse drags are ignored, and a red banner appears. Even if a modified client attempts to send strokes, the server drops them with error code `readonly`.

