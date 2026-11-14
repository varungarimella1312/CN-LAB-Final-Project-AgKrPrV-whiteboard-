# LAN Collaborative Whiteboard

A real-time, multi-user whiteboard for computers on the same local area network. The application uses a Python TCP server as the authority for shared board state and a Tkinter desktop client for each participant.

The project is implemented with the Python standard library. It does not need a web server, third-party Python packages, or an internet connection to run. The client does require a Python installation that includes Tkinter.

## Features

- Shared 1200 x 700 canvas with pen, white-stroke eraser, line, rectangle, oval, text, and sticky-note tools.
- Adjustable stroke width, quick color palette, and native color picker.
- Live drawing previews, participant cursors, and group or private chat.
- Host, editor, and viewer roles. The host can also enable presentation mode, clear the board, manage participants, and save or load board versions.
- Per-user undo and redo. The host can undo and redo a canvas clear.
- Automatic reconnect attempts and board-state synchronization after a network interruption.
- Server-side autosaves and labeled version snapshots.

## Project files

| File | Purpose |
|---|---|
| `client.py` | Tkinter graphical application and user interactions |
| `netclient.py` | Client TCP connection, sender/receiver threads, heartbeat, and reconnect logic |
| `boardstate.py` | Client-side board replica, pending strokes, sequence tracking, and resynchronization |
| `server.py` | Authoritative TCP server, room membership, validation, persistence, and operation sequencing |
| `protocol.py` | Length-prefixed JSON framing and shared network/canvas constants |
| `test_integration.py` | Headless framing, client, and real-socket server integration tests |
| `README.md` | Setup and project documentation |

## Requirements

- Python 3.10 or later.
- Tkinter for the graphical client. It is included with most Windows Python installations; on some Linux distributions it is provided by a separate system package.
- A TCP connection between each client and the computer running the server.

The server and test suite can run without opening a GUI. No `pip install` step is required.

## Run the application

Run the following commands from the directory containing `server.py`, `client.py`, and this README. On Windows, use `python` or the Python launcher `py` if that is how Python is installed.

### 1. Start the server

Open a terminal and run:

```powershell
python server.py --host 0.0.0.0 --port 5050
```

The server prints its LAN IP address, listening port, and three generated four-digit codes:

- **Room code** identifies the room for display and is shown in the client after connecting.
- **Host code** is for the person joining with the Host role. Do not share it with participants.
- **Room password** is required by both the host and participants.

The GUI does not ask users to type a room code: clients connecting to this server join the generated room. The three codes are distinct within that server run. The server chooses a room code that does not already have a directory under its boards folder.

### 2. Start the host client

Open a second terminal on the server computer and run:

```powershell
python client.py --host 127.0.0.1 --port 5050
```

In the client, select **Host**, enter a display name, the room password, and the host code printed by the server, then connect.

### 3. Join from other devices

On each other computer, run the client with the server's LAN IP address and port. For example:

```powershell
python client.py --host 192.168.1.50 --port 5050
```

Replace `192.168.1.50` with the address printed by the server. Select **Participant**, enter a display name and the room password, then connect. Participants do not need the host code.

For devices on the same computer, use `127.0.0.1`. For devices on other computers, use the server computer's reachable LAN address, not `127.0.0.1`. If clients cannot connect, allow inbound TCP traffic on the selected port through the server computer's firewall for the trusted/private network profile.

Stop the server with **Ctrl+C**. Start the server before connecting clients.

### Command-line options

#### Server

| Option | Default | Description |
|---|---:|---|
| `--host` | `0.0.0.0` | IPv4 interface to bind to. `0.0.0.0` listens on all local IPv4 interfaces. |
| `--port` | `5050` | TCP listening port. |
| `--boards` | `boards` | Directory for autosaves and version files. A relative path is resolved from the directory containing `server.py`. |
| `--timeout` | `15` seconds | Inactivity timeout for a connected client. |
| `--grace` | `120` seconds | How long an offline member is retained for reconnecting before being removed. |

Example:

```powershell
python server.py --host 0.0.0.0 --port 5050 --timeout 20 --grace 180
```

#### Client

| Option | Default | Description |
|---|---:|---|
| `--host` | `127.0.0.1` | Server IP address to prefill in the connection window. |
| `--port` | `5050` | Server port to prefill in the connection window. |

Example:

```powershell
python client.py --host 192.168.1.50 --port 5050
```

## Using the whiteboard

### Tools and canvas behavior

- **Pen, line, rectangle, oval, text, and note** are available in the toolbar.
- The width control ranges from 1 to 30. The eraser sends a white stroke three times the selected width (up to 90 px); it paints over content on the white canvas rather than deleting earlier strokes.
- The text tool places text at the selected point. The note tool creates a sticky note. Text is limited to 300 characters.
- The canvas is white and 1200 x 700 logical pixels. Server-side coordinate validation allows values with an absolute value below 10,000; the protocol's coordinate range is wider than the visible canvas.
- Use **Export (.ps)** to export the visible Tkinter canvas as a PostScript file.

### Roles and permissions

| Role | Permissions |
|---|---|
| Host | Draw and chat; clear the canvas; enable or disable presentation mode; change participant roles; kick participants; save and restore versions. |
| Editor | Draw, use personal undo/redo, and chat. |
| Viewer | Observe the board and chat; drawing and editing actions are denied by the server. |

Participants join as editors by default. The host can change a participant to editor or viewer from the participant list. In presentation mode, non-host participants are read-only; the host retains editing access.

Undo and redo apply to the caller's own drawing actions. Erasing is stored as a white stroke, so undoing it removes that white stroke from view. A host clear hides all currently visible strokes as one operation; the host can undo or redo that clear.

### Chat

Chat supports room-wide messages and private messages to an active participant. Messages are limited to 500 characters. The server keeps a bounded chat history and includes recent messages when a client joins.

## How synchronization works

The server is authoritative for committed canvas changes:

1. While a user draws, the client renders locally and sends occasional uncommitted preview (`part`) messages to peers.
2. On release, the client submits a completed stroke. The server validates it, assigns the next room sequence number, records the operation, broadcasts it, and acknowledges the sender.
3. Clients apply sequenced operations in order. Duplicate operations are ignored; operations received across a sequence gap are buffered while the client requests a delta or a full snapshot.

The local preview keeps drawing responsive, but the server-assigned sequence determines the shared committed order. Cursor positions and in-progress previews are transient and are not part of the committed operation log. The GUI schedules its network event pump every 15 ms and coalesces redundant cursor updates per participant; drawing previews and committed operations are not coalesced.

### TCP message framing

TCP is a byte stream and does not preserve application message boundaries. Each protocol message is compact UTF-8 JSON preceded by a four-byte unsigned big-endian payload length:

```text
+-------------------------------+----------------------------------+
| 4-byte length prefix ('>I')   | UTF-8 JSON payload               |
+-------------------------------+----------------------------------+
```

The receiver reads the full header and then the number of payload bytes specified by the header. The protocol rejects empty or oversized frames; the maximum payload is 4 MiB. `TCP_NODELAY` is enabled on client and accepted server sockets to avoid Nagle buffering on interactive messages.

### Message families

| Direction | Message types | Purpose |
|---|---|---|
| Client to server | `hello` | Join or reconnect, with credentials and, when available, a session token and last applied sequence. |
| Client to server | `stroke`, `undo`, `redo`, `clear` | Submit completed drawing or board-edit operations. |
| Client to server | `part`, `cursor` | Send transient drawing previews and cursor positions. |
| Client to server | `chat`, `save`, `versions`, `load` | Chat and host version-management requests. |
| Client to server | `setrole`, `present`, `kick`, `sync`, `ping`, `leave` | Participant management, presentation mode, state recovery, heartbeat, and disconnect. |
| Server to client | `welcome`, `users`, `notice` | Join result, room snapshot/delta, roster, and room notices. |
| Server to client | `op`, `ack`, `part`, `cursor` | Sequenced committed operations, stroke acknowledgement, and transient peer updates. |
| Server to client | `chat`, `versions`, `saved`, `delta`, `snapshot`, `pong`, `err` | Chat, version results, synchronization/heartbeat responses, and errors. |

## Architecture and limits

### Server

- A listener accepts TCP connections. Each client session has a reader thread and a writer thread.
- Each room uses a re-entrant lock to serialize state changes, sequence assignment, and broadcasts.
- Each client has a bounded outgoing queue of 5,000 messages. If a slow client fills its queue, that client is disconnected rather than allowing its backlog to grow without limit.
- A background reaper checks client activity every 0.2 seconds. With the default settings, inactive connections time out after 15 seconds and offline members are retained for 120 seconds for reconnection.
- A room supports up to 30 members. A connection is limited to 400 incoming messages per second.

### Client

- Tkinter owns all GUI and canvas updates on the main thread.
- A receiver thread reads the server connection and puts events into a thread-safe queue; a sender thread transmits queued messages and sends an idle heartbeat about every four seconds.
- After a previously successful connection drops, the client retries after two seconds. Reconnection uses a session token and the last applied sequence to request missed operations where possible.
- The session token is saved in the current user's application-data/state directory, scoped to server address, port, and username. The room password is not saved by the client.

## Validation and persistence

- Generated room, host, and password codes are four digits. Usernames must be 1-24 characters and use letters, digits, spaces, `.`, `_`, or `-`.
- Supported stroke tools are pen, eraser, line, rectangle, oval, and text. Ordinary stroke widths are 1-60; eraser widths are 1-90. A stroke can contain 1-8,000 finite points; coordinates must have absolute values below 10,000.
- Chat text is limited to 500 characters; text and sticky-note content are limited to 300 characters.
- The server stores board data under `boards/<room-code>/` by default. Dirty rooms are autosaved periodically (every 30 seconds), when a room becomes empty, and when the server shuts down. Host-created version snapshots are separate timestamped JSON files and can be listed and loaded during the room session.
- Version loading accepts only JSON files in that room's version directory and rejects path-containing filenames.

**Room lifecycle note:** the command-line server creates a new generated room code on each launch. Existing board files remain on disk, but the GUI does not provide a room-code field for reopening an old generated room, and a new generated room does not automatically load the previous launch's autosave. Keep the `boards` directory if you want to retain saved files.

## Security and network scope

This project is intended for a trusted LAN. The protocol uses TCP JSON without TLS, so network traffic, including room credentials, is not encrypted in transit. Do not expose the server port to the public internet. The server validates incoming messages, limits message/frame sizes and client rates, and restricts version loading to the room's version directory; these checks do not replace transport encryption or network access controls.

The server stores a salted password hash rather than the room password. The LAN IP printed at startup is a best-effort address selected from the machine's network routing; if it is unavailable or incorrect, use the server computer's reachable LAN IPv4 address.

## Tests

From the directory containing `test_integration.py`, run:

```powershell
python -m unittest test_integration
```

The headless suite uses socket pairs and real loopback TCP connections. It covers message framing, joining and authentication, validation and role permissions, state synchronization, concurrent drawing convergence, undo/redo, chat, reconnects, heartbeats, and version persistence/loading.

## Troubleshooting

- **`python` is not recognized:** try `py` in place of `python`, or add the Python installation to `PATH`.
- **Tkinter import/window error:** use a Python installation that includes Tk support. Some Linux installations require their distribution's Tkinter package.
- **Connection refused:** make sure the server is running and the client port matches the server port.
- **Other devices cannot connect:** use the server's LAN IP, check that devices can reach each other, and allow inbound TCP on the server port in the private-network firewall profile.
- **Host cannot connect:** select **Host** and enter both the host code and room password. Participants use the room password but not the host code.
- **A previous board is not listed after restarting the server:** each CLI server launch generates a fresh room. Existing room files are not automatically attached to that new room.

## Lab discussion notes

**Why TCP?** Completed drawing operations must be delivered reliably and in order on each connection. TCP provides reliable ordered byte-stream delivery; the server's sequence numbers provide a single order across concurrent users.

**Why length-prefix framing?** TCP may split or combine writes. The four-byte length prefix lets the receiver read exactly one JSON message regardless of packet boundaries.

**How is the GUI kept responsive?** Socket reads and writes run in worker threads. The GUI thread applies queued events and updates Tkinter widgets; network I/O does not run in the drawing callbacks.

**How do all clients converge?** The server validates and sequences each committed change under the room lock. Clients apply operations by sequence, buffer gaps, and request a delta or snapshot when needed.

**How does undo work?** Undo and redo submit visibility operations for the caller's own strokes. Strokes remain in board history; undo does not remove another participant's work.

**How does reconnect recovery work?** The client retains a per-identity session token and last applied sequence. When reconnecting to the same running room, the server can send the operations committed after that sequence; otherwise it supplies a snapshot.
