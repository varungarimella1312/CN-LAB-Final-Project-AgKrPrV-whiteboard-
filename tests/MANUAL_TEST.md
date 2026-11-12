# LAN Collaborative Whiteboard - Manual Lab Test Checklist

**Computer Networks Lab Demonstration Protocol**  
*Testing on 2–3 Laptops connected to a Local Wi-Fi Router or Phone Hotspot (INTERNET DISABLED)*

---

## Pre-Test Setup: Offline LAN Environment

1. **Network Connectivity**:
   - Connect Laptop 1 (Server/Host), Laptop 2 (Client), and Laptop 3 (Client) to the same Wi-Fi access point or a smartphone personal hotspot.
   - **Disable Cellular Data / Internet Access** on the hotspot or router: the whiteboard operates completely offline over raw TCP sockets.
2. **Prerequisites**:
   - Python 3.10+ installed on all machines.
   - Zero pip packages needed (uses only standard library).
   - Project files copied to all laptops.

---

## Section A: Server Launch & Firewall Configuration

### Step 1: Start Server & Discover LAN IP
On **Laptop 1**:
```bash
python3 whiteboard/server.py --host 0.0.0.0 --port 5050
```
- **Action**: Observe server terminal banner.
- **Expected Result**:
  - The server automatically queries the routing table via a dummy UDP socket to `10.255.255.255:1` (transmits 0 packets).
  - Displays the machine's local IPv4 address (e.g. `192.168.1.45` or `172.20.10.2`).
  - Terminal prints:
    ```
    ================================================================
    LAN Collaborative Whiteboard Server
    ================================================================
    Local LAN IP Address   : 192.168.1.45
    Listening On Interface : 0.0.0.0:5050

    Share this LAN IP and Port with other computers on your network:
      python client.py --host 192.168.1.45 --port 5050
    ================================================================
    ```

### Step 2: Firewall Troubleshooting (If Clients Cannot Connect)
If Laptop 2 or 3 cannot reach Laptop 1, check OS-specific firewall rules:
- **Windows (Laptop 1)**:
  - If a "Windows Defender Firewall" prompt appears, check **Private networks** and click **Allow access**.
  - Alternatively, run in PowerShell as Administrator:
    ```powershell
    netsh advfirewall firewall add rule name="WhiteboardServer" dir=in action=allow protocol=TCP localport=5050
    ```
- **Linux (Laptop 1)**:
  - Allow port 5050:
    ```bash
    sudo ufw allow 5050/tcp
    # Or with iptables:
    sudo iptables -A INPUT -p tcp --dport 5050 -j ACCEPT
    ```
- **macOS (Laptop 1)**:
  - If prompted, click **Allow** for incoming network connections to Python.
  - Check *System Settings > Network > Firewall* and ensure incoming connections are not blocked.
- **Connectivity Ping Test**:
  - From Laptop 2 or 3 terminal:
    ```bash
    ping 192.168.1.45
    nc -zv 192.168.1.45 5050   # (or: telnet 192.168.1.45 5050)
    ```

---

## Section B: Room Creation, Authentication & Role Enforcement

### Step 3: Host Creates Room (Laptop 1)
1. Run on Laptop 1:
   ```bash
   python3 whiteboard/client.py --host 127.0.0.1 --port 5050
   ```
2. In the Login Dialog:
   - **Server IP**: `127.0.0.1`
   - **Port**: `5050`
   - **Room Code**: `lab-session`
   - **Your Name**: `Alice`
   - **Password**: `secret123`
   - Check **"Create a new session (I am the host)"**.
3. Click **Connect & Enter**.
- **Expected Result**:
  - Main whiteboard window opens immediately.
  - Status bar shows: `Status: Connected`, `Room: lab-session`, `Role: Host ★`, `Seq: 0`.
  - Participants list shows `Alice` with role `Host ★` and `Online`.

### Step 4: Participant Joins with WRONG Password (Laptop 2)
1. Run on Laptop 2:
   ```bash
   python3 whiteboard/client.py --host 192.168.1.45 --port 5050
   ```
2. In the Login Dialog:
   - **Server IP**: `192.168.1.45`
   - **Room Code**: `lab-session`
   - **Your Name**: `Bob`
   - **Password**: `WRONG_PASSWORD`
   - Leave "Create a new session" **unchecked**.
3. Click **Connect & Enter**.
- **Expected Result**:
  - Connection dialog shows error alert: *"Incorrect room password. Please try again."*
  - Client remains on Login screen; password entry is re-enabled.
  - Server logs rejection with code `"bad_password"`.

### Step 5: Participants Join with CORRECT Password (Laptops 2 & 3)
1. On **Laptop 2 (Bob)**: Enter password `secret123` and click **Connect & Enter**.
2. On **Laptop 3 (Charlie)**:
   ```bash
   python3 whiteboard/client.py --host 192.168.1.45 --port 5050
   ```
   - Room Code: `lab-session`, Name: `Charlie`, Password: `secret123`, Create: Unchecked.
- **Expected Result**:
  - Both Bob and Charlie enter the canvas.
  - On **all 3 screens**, the Participants list immediately updates to display:
    - `Alice` — `Host ★` — `Online`
    - `Bob` — `Editor` — `Online`
    - `Charlie` — `Editor` — `Online`
  - Group chat displays notices: *"Bob joined the room"*, *"Charlie joined the room"*.

---

## Section C: Real-Time Collaborative Drawing & Overlays

### Step 6: Simultaneous Live Drawing by 3 Users
1. **Alice (Laptop 1)**: Selects **Pen** tool, chooses Red, draws freehand curves.
2. **Bob (Laptop 2)**: Selects **Rectangle** tool, chooses Blue, drags a box.
3. **Charlie (Laptop 3)**: Selects **Note** tool, clicks canvas, enters `"Lab Task 1"`.
- **Expected Result**:
  - **Live Streaming**: While Bob and Alice are dragging, other users see their colored partial lines and bounding box outlines updating every 40 ms.
  - **Commit**: On mouse release, the committed stroke renders crisply on all 3 screens.
  - Charlie's Sticky Note appears as a yellow post-it note card with a darker header bar and wrapped text `"Lab Task 1"`.
  - Sequence numbers (`Seq: X`) in status bars advance synchronously on all machines.

### Step 7: Live Mouse Cursors
1. Move the mouse across the canvas on Laptop 2 (Bob) without clicking.
- **Expected Result**:
  - Laptops 1 and 3 display a colored dot and text label `"Bob"` moving smoothly in real time across their canvas viewports.
  - If Bob stops moving for 3 seconds, the cursor dot fades/disappears automatically.

### Step 8: Group Chat Broadcast
1. On Laptop 2 (Bob): Type `"Ready for the demonstration"` in chat entry and press <kbd>Enter</kbd>.
- **Expected Result**:
  - Message appears instantly in the chat panel of all 3 laptops:
    `[HH:MM:SS] Bob: Ready for the demonstration`

---

## Section D: State Consistency, Undo/Redo & Role Permissions

### Step 9: Per-User Undo/Redo Isolation
1. Alice draws a green line (Stroke A).
2. Bob draws a purple circle (Stroke B).
3. Charlie draws an orange rectangle (Stroke C).
4. **Bob presses <kbd>Ctrl+Z</kbd> (or clicks Undo)** on Laptop 2.
- **Expected Result**:
  - **Only Bob's purple circle disappears**.
  - Alice's green line and Charlie's orange rectangle remain completely intact.
5. **Bob presses <kbd>Ctrl+Y</kbd> (or clicks Redo)** on Laptop 2.
- **Expected Result**:
  - Bob's purple circle reappears in its original drawing position on all 3 screens.

### Step 10: Canvas Clear & Undo-Clear (Host vs Editor)
1. On Laptop 2, **Bob clicks "Clear Canvas"**:
   - **Expected Result**: Action is blocked with error: *"Only the host can clear the whiteboard canvas"*. The canvas is not cleared.
2. On Laptop 1, **Alice (Host) clicks "Clear Canvas"** and confirms:
   - **Expected Result**: All visible strokes disappear on all 3 screens.
3. On Laptop 1, **Alice clicks "Undo (Ctrl+Z)"**:
   - **Expected Result**: All cleared strokes reappear instantly on all 3 screens in their exact original z-order.

### Step 11: Host Sets Participant to Viewer Role
1. On Laptop 1 (Alice), right-click **Charlie** in the Participants list $\to$ select **"Make Viewer"**.
- **Expected Result**:
  - On Charlie's screen (Laptop 3):
    - Role badge changes to `Role: Viewer (View-Only)`.
    - Toolbar buttons (Pen, Eraser, Line, Rect, Oval, Note, Text, Undo, Redo) are greyed out / disabled.
    - Status bar displays `"Role: Viewer (View-Only)"`.
    - Clicking or dragging on Charlie's canvas produces zero drawing actions.
2. Alice right-clicks Charlie $\to$ selects **"Make Editor"**:
   - Charlie's drawing tools are immediately re-enabled.

---

## Section E: Network Fault Tolerance, Reconnection & Recovery

### Step 12: Abrupt Client Window Close & Rejoining
1. On Laptop 2 (Bob), abruptly close the application window (<kbd>Alt+F4</kbd> or <kbd>Cmd+Q</kbd>).
- **Expected Result**:
  - Within seconds, Alice and Charlie see Bob's status switch to `Offline`.
2. On Laptop 2, restart the client and join `lab-session` as `Bob` with password `secret123`.
- **Expected Result**:
  - Bob is accepted back into the room.
  - The entire existing canvas state (all committed strokes, sticky notes) is downloaded from the server and rendered cleanly.
  - Bob's status returns to `Online` on all screens.

### Step 13: Wi-Fi Disconnection / Cable Unplug for 20 Seconds
1. On Laptop 3 (Charlie), **turn off Wi-Fi** (or unplug network cable).
   - In Charlie's status bar, observe: `Status: Reconnecting...`.
   - The canvas remains completely visible (not wiped).
2. While Charlie is offline, have Alice (Laptop 1) draw **3 new distinct blue strokes**.
3. After 20 seconds, **turn Wi-Fi back on** on Laptop 3.
- **Expected Result**:
  - Charlie's background `Net` worker automatically detects network restoration and reconnects within 2 seconds.
  - Charlie sends `get_hello()` containing his secret session token and `last_seq`.
  - The server transmits a `welcome` message with **`mode: "delta"`** containing **only the 3 missed blue strokes** (not the full canvas).
  - The 3 new strokes appear seamlessly on Charlie's canvas.
  - Status updates to `Status: Connected`.

### Step 14: Server Version Snapshots & Restoration
1. On Laptop 1 (Host Alice), click **"Save Version"** $\to$ enter label `checkpoint1`.
   - Server saves `boards/lab-session/<timestamp>_checkpoint1.json`.
   - Pop-up confirms version saved.
2. Alice clicks **"Clear Canvas"** to wipe the board.
3. Alice clicks **"Versions..."**:
   - Modal dialog opens listing available snapshots.
   - Select `checkpoint1` and click **"Restore Selected"**.
- **Expected Result**:
  - Server reads snapshot, re-validates strokes, and broadcasts a single sequenced `reset` op with the saved strokes.
  - Canvas restores instantly to the `checkpoint1` state on all 3 laptops.

### Step 15: Server Process Restart & Board Persistence
1. Stop the server on Laptop 1 (<kbd>Ctrl+C</kbd> in terminal).
2. Restart the server:
   ```bash
   python3 whiteboard/server.py --host 0.0.0.0 --port 5050
   ```
3. Have Alice, Bob, and Charlie reconnect to `lab-session` (create unchecked).
- **Expected Result**:
  - The server automatically reloads the room state from `boards/lab-session/autosave.json`.
  - All existing strokes are preserved and delivered to all rejoining clients.

---

## Summary Evaluation Matrix

| Capability Tested | Result Observed | Pass/Fail |
|:---|:---|:---:|
| Server IP Auto-Discovery (`10.255.255.255` UDP trick) | Correct LAN IP printed without internet | [ ] |
| Protocol Framing (4-byte length prefix) | No stuck or corrupted packets | [ ] |
| Password Authentication (Salted SHA-256 + HMAC) | Wrong password rejected; right password accepted | [ ] |
| Concurrent 3-Client Drawing | Real-time live previews, identical global order | [ ] |
| Per-User Undo/Redo Isolation | Undo affects only the caller's strokes | [ ] |
| Host-Only Canvas Clear | Non-host denied; host clear + undo works | [ ] |
| Viewer Role Enforcement | Viewers restricted to read-only mode | [ ] |
| Auto-Reconnection & Delta Sync | Wi-Fi toggle recovers missed ops seamlessly | [ ] |
| State Persistence across Server Restart | Autosave restores room state | [ ] |

