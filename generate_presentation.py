#!/usr/bin/env python3
"""Script to generate the 15-slide Presentation for the LAN Whiteboard.

Uses python-pptx to produce a clean, modern, 16:9 widescreen presentation
with structured content, diagrams, code blocks, and screenshot placeholders.
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_presentation(filename="docs/LAN_Whiteboard_Presentation.pptx"):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]  # completely blank layout

    # Color Palette
    c_navy = RGBColor(26, 54, 93)       # #1A365D - Title / Header
    c_blue = RGBColor(43, 108, 176)     # #2B6CB0 - Accent
    c_charcoal = RGBColor(45, 55, 72)   # #2D3748 - Body Text
    c_light_bg = RGBColor(247, 250, 252)# #F7FAFC - Card Background
    c_border = RGBColor(226, 232, 240)  # #E2E8F0 - Card Border
    c_white = RGBColor(255, 255, 255)
    c_red = RGBColor(197, 48, 48)       # #C53030 - Error / Alert
    c_green = RGBColor(40, 167, 69)     # #28A745 - Success
    c_muted = RGBColor(113, 128, 150)   # #718096 - Muted gray
    c_placeholder = RGBColor(237, 242, 247)

    def add_header(slide, title_text, category="COMPUTER NETWORKS LAB PROJECT"):
        # Header banner
        tx_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.9))
        tf = tx_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

        p0 = tf.paragraphs[0]
        p0.text = category.upper()
        p0.font.size = Pt(10)
        p0.font.bold = True
        p0.font.color.rgb = c_blue

        p1 = tf.add_paragraph()
        p1.text = title_text
        p1.font.size = Pt(22)
        p1.font.bold = True
        p1.font.color.rgb = c_navy

    def add_card(slide, left, top, width, height, title="", fill_color=c_light_bg, border_color=c_border):
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_color
        shape.line.color.rgb = border_color
        shape.line.width = Pt(1)

        if title:
            tb = slide.shapes.add_textbox(left + Inches(0.2), top + Inches(0.15), width - Inches(0.4), Inches(0.4))
            tf = tb.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
            p = tf.paragraphs[0]
            p.text = title
            p.font.size = Pt(13)
            p.font.bold = True
            p.font.color.rgb = c_navy
        return shape

    # =========================================================================
    # SLIDE 1: TITLE SLIDE
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)
    bg1 = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
    bg1.fill.solid()
    bg1.fill.fore_color.rgb = c_navy
    bg1.line.fill.background()

    tb = s1.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(11.0), Inches(4.0))
    tf = tb.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.text = "LAN Multi-User Collaborative Whiteboard"
    p.font.size = Pt(36)
    p.font.bold = True
    p.font.color.rgb = c_white

    p2 = tf.add_paragraph()
    p2.text = "Real-Time Distributed Canvas Architecture Using Standard Python TCP Sockets"
    p2.font.size = Pt(18)
    p2.font.color.rgb = RGBColor(190, 227, 248)
    p2.space_before = Pt(12)

    p3 = tf.add_paragraph()
    p3.text = "\n• Zero Internet Required (LAN / Ad-hoc Hotspot Only)\n• 100% Python 3.10+ Standard Library (Zero External Dependencies)\n• Multi-Threaded State Machine Replication with Strict Ordering\n• Per-User Isolated Undo/Redo & Real-Time Ephemeral Streaming"
    p3.font.size = Pt(13)
    p3.font.color.rgb = RGBColor(226, 232, 240)
    p3.space_before = Pt(18)

    p4 = tf.add_paragraph()
    p4.text = "\nUniversity Computer Networks Lab Project  |  Team Presentation"
    p4.font.size = Pt(11)
    p4.font.color.rgb = RGBColor(160, 174, 192)
    p4.space_before = Pt(18)

    # =========================================================================
    # SLIDE 2: PROBLEM & MOTIVATION
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    add_header(s2, "Problem Statement & Project Motivation")

    add_card(s2, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3), "The Engineering Challenge")
    tb = s2.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.2), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    bullets = [
        "<b>No Internet Dependency:</b> Collaboration tools like Miro, Figma, or Google Drawings fail in air-gapped lab environments, field stations, or offline LANs.",
        "<b>Zero Third-Party Libraries:</b> Hard rule to use standard library only (no Flask, Twisted, WebSockets, or async frameworks).",
        "<b>Real-Time Interactive Constraint:</b> Drawing requires < 30 ms latency to feel natural without visual stutter or rubber-banding.",
        "<b>Consistency in Distributed Systems:</b> When 4 users draw at the exact same millisecond, how does every screen converge to the exact same canvas state?"
    ]
    for idx, b in enumerate(bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    add_card(s2, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.3), "Our Technical Objectives")
    tb = s2.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    objectives = [
        "<b>Low-Level Socket Programming:</b> Implement robust TCP stream framing, backpressure handling, and socket lifecycle control from scratch.",
        "<b>Multi-Threaded Server:</b> Decouple network I/O from room sequencing so slow clients never stall fast clients.",
        "<b>Authoritative State Machine Replication:</b> Centralized monotonic log ensuring identical deterministic draw order.",
        "<b>Per-User Undo Stacks:</b> A user undoing their stroke must never erase another participant's work.",
        "<b>Autonomous Session Recovery:</b> Automatic token-based delta synchronization across network drops."
    ]
    for idx, b in enumerate(objectives):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    # =========================================================================
    # SLIDE 3: SYSTEM ARCHITECTURE
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    add_header(s3, "System Architecture & Star Topology")

    add_card(s3, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.3), "Centralized Server & Decoupled Client Architecture")
    tb = s3.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(11.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    arch_bullets = [
        "• <b>Star Topology:</b> Central TCP server on port 5050 manages multiple isolated rooms without cross-room lock contention.",
        "• <b>Server Concurrency Pipeline:</b>",
        "   - <i>Acceptor Thread:</i> Listens for new client handshakes, assigns TCP_NODELAY.",
        "   - <i>Reader Thread (per client):</i> Reads framed incoming messages, dispatches under Room.lock.",
        "   - <i>Writer Thread (per client):</i> Drains an outbound bounded Queue(maxsize=5000); disconnects slow clients to prevent bufferbloat.",
        "   - <i>Reaper Thread:</i> Periodic scan every 1s closes idle sockets exceeding 15s timeout.",
        "• <b>Client Thread Isolation:</b>",
        "   - Background <i>Net</i> worker handles framed socket I/O and keepalive pings.",
        "   - Thread-safe <i>Queue</i> passes events to main thread.",
        "   - Tkinter GUI polls queue every 30ms via root.after(), guaranteeing zero GUI freezing."
    ]
    for idx, b in enumerate(arch_bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('• ', '').replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
        p.font.size = Pt(12)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(8)

    # =========================================================================
    # SLIDE 4: PROTOCOL & FRAMING (WHY TCP)
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    add_header(s4, "Transport Protocol & Binary Framing")

    add_card(s4, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3), "Why TCP Over UDP?")
    tb = s4.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.2), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    why_tcp = [
        "1. <b>Strict State Accumulation:</b> Canvas strokes are persistent data. A dropped UDP packet causes permanent canvas desynchronization.",
        "2. <b>Ordered Delivery:</b> Creation, shape drawing, and clear operations must occur in exact order.",
        "3. <b>Flow Control:</b> TCP sliding windows protect slow clients from being overwhelmed during heavy drawing.",
        "4. <b>Latency Mitigation:</b> Enabling <code>TCP_NODELAY</code> disables Nagle's algorithm, eliminating buffering delay and achieving sub-10 ms interactive speeds on LAN."
    ]
    for idx, b in enumerate(why_tcp):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    add_card(s4, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.3), "Explicit Length-Prefix Framing")
    tb = s4.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    framing_expl = [
        "<b>The Stream Problem:</b> TCP has no concept of message boundaries. Packets may arrive coalesced ('sticky packets') or fragmented across multiple reads.",
        "<b>Our 4-Byte Binary Header:</b> Every message is preceded by a 4-byte big-endian unsigned integer (<code>>I</code>) encoding payload length N, followed by N bytes of UTF-8 JSON.",
        "<b>Deterministic Loop:</b> <code>recv_exact(sock, n)</code> loops until exactly n bytes arrive, completely preventing JSON parse errors.",
        "<b>Oversize Defense:</b> Messages > 4 MiB (<code>MAX_MSG</code>) immediately raise <code>ProtocolError</code>, protecting server RAM."
    ]
    for idx, b in enumerate(framing_expl):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    # =========================================================================
    # SLIDE 5: MESSAGE FLOW DIAGRAM (ONE STROKE)
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    add_header(s5, "Message Flow: Lifecycle of a Committed Stroke")

    add_card(s5, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.3), "End-to-End Sequence: User Drag to Canvas Convergence")
    tb = s5.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(11.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    flow_steps = [
        "1. <b>Local Drawing & Optimistic Echo:</b> User drags mouse on Canvas. Client immediately renders stroke marked as 'pending' for zero-latency user feedback.",
        "2. <b>Live Ephemeral Streaming:</b> While dragging, client sends lightweight 'part' messages every 40ms; server broadcasts these to peers without writing to the room log.",
        "3. <b>Mouse Release & Commit:</b> On release, client generates unique ID and sends framed {'t': 'stroke', 'id': sid, 's': {...}}.",
        "4. <b>Server Authoritative Commit:</b> Server reader thread validates stroke schema, checks deduplication (Room.seen), acquires Room.lock, increments room.seq, appends to room.log, and updates user undo stack.",
        "5. <b>Acknowledgment & Broadcast:</b>",
        "   - Server replies to author with {'t': 'ack', 'id': sid, 'seq': N}.",
        "   - Server broadcasts {'t': 'op', 'seq': N, 'k': 'stroke', 'id': sid, 's': {...}} to all room members.",
        "6. <b>Peer Render & Author Reconcile:</b> Peers render stroke; author marks pending stroke as confirmed."
    ]
    for idx, b in enumerate(flow_steps):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(8)

    # =========================================================================
    # SLIDE 6: SYNCHRONISATION & STATE MACHINE REPLICATION
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    add_header(s6, "State Machine Replication & Global Sequencing")

    add_card(s6, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3), "Authoritative Total Ordering")
    tb = s6.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.2), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    smr_bullets = [
        "<b>Monotonic Sequence Numbers:</b> The central server assigns a strictly increasing integer (seq = 1, 2, 3...) to every permanent canvas mutation.",
        "<b>Deterministic State Function:</b> The visual state of the canvas at sequence N is a deterministic replay of operations op_1 through op_N.",
        "<b>Z-Order Determinism:</b> In 2D drawing, the order in which overlapping shapes are drawn dictates visibility. Server sequencing guarantees identical visual Z-order on every client."
    ]
    for idx, b in enumerate(smr_bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(12)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(14)

    add_card(s6, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.3), "Gap Detection & Out-of-Order Buffering")
    tb = s6.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    gap_bullets = [
        "<b>Sequence Verification on Client:</b> When an operation with sequence S arrives:",
        "• <b>S <= local_seq:</b> Duplicate message, ignored.",
        "• <b>S == local_seq + 1:</b> Next expected operation, applied immediately.",
        "• <b>S > local_seq + 1:</b> Missing updates detected! Staged in buffer, and client requests delta sync.",
        "<b>Contiguous Drain:</b> Once missing operations arrive, BoardState automatically drains buffered successors in sequence.",
        "<b>Deterministic State Fingerprint:</b> Client computes SHA-256 hash over visible stroke IDs to cryptographically verify canvas convergence."
    ]
    for idx, b in enumerate(gap_bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(10)

    # =========================================================================
    # SLIDE 7: CONCURRENCY HANDLING & THREADING MODEL
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    add_header(s7, "Concurrency Control & Thread Safety")

    add_card(s7, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.3), "Lock Scoping & Deadlock Avoidance Architecture")
    tb = s7.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(11.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    conc_details = [
        "• <b>Room-Level Granularity (Room.lock = threading.RLock):</b>",
        "   - All mutations to a room (seq increment, stroke appending, undo stack updates, roster changes) require holding that room's lock.",
        "   - Different rooms execute entirely concurrently without cross-room blocking.",
        "• <b>Server-Level Registry Lock (_rooms_lock):</b>",
        "   - Protects room creation and directory scanning.",
        "• <b>Never Send While Holding Room Locks:</b>",
        "   - Broadcaster calls session.send_msg() which puts messages into an in-memory queue.Queue. No blocking socket I/O is ever performed under lock.",
        "• <b>Slow Client Isolation (Bufferbloat Defense):</b>",
        "   - If a client's send_queue reaches maxsize=5000 (e.g. frozen Wi-Fi interface), the server closes that client socket immediately, preserving memory and performance for others.",
        "• <b>Graceful Shutdown Sentinel:</b>",
        "   - Reader and writer threads coordinate termination using a None sentinel to flush pending fatal error messages before tearing down sockets."
    ]
    for idx, b in enumerate(conc_details):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('• ', '').replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(12)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(8)

    # =========================================================================
    # SLIDE 8: RELIABILITY, HEARTBEATS & RECOVERY
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    add_header(s8, "Fault Tolerance & Connection Recovery")

    add_card(s8, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3), "Heartbeat & Inactivity Reaper")
    tb = s8.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.2), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    hb_bullets = [
        "<b>Keepalive Pings:</b> Client sends ping every 4.0 seconds; server echoes pong with original timestamp.",
        "<b>Live Latency Measurement:</b> GUI computes round-trip latency (RTT) and displays it on status bar (typically 2-8 ms on LAN).",
        "<b>Inactivity Reaper:</b> Server reaper thread scans every 1.0s. Sockets with no inbound traffic for > 15s are closed.",
        "<b>Grace Period (120s):</b> Disconnected members are retained in room roster for 120s, allowing them to reconnect without losing state."
    ]
    for idx, b in enumerate(hb_bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    add_card(s8, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.3), "Autonomous Token-Based Reconnect")
    tb = s8.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    rec_bullets = [
        "<b>Cryptographic Session Tokens:</b> On join, server issues a secure 16-byte hex token (secrets.token_hex(16)).",
        "<b>Auto-Reconnect Loop:</b> When Net detects socket disconnect, it sleeps 2s and attempts reconnection automatically.",
        "<b>Delta Catch-Up:</b> Reconnection handshake includes token and client's last_seq. Server verifies token, re-attaches existing Member, and sends delta ops log[last_seq:] rather than full snapshot.",
        "<b>Unsent Local Resend:</b> Any unacknowledged local strokes are automatically re-transmitted upon reconnection."
    ]
    for idx, b in enumerate(rec_bullets):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    # =========================================================================
    # SLIDE 9: PER-USER UNDO/REDO & HOST CLEAR
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    add_header(s9, "Collaborative Undo/Redo & Host Clear Semantics")

    add_card(s9, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.3), "Isolated Stacks & Non-Destructive Visibility Operations")
    tb = s9.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(11.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    undo_details = [
        "• <b>The Collaborative Undo Dilemma:</b> In a multi-user app, global LIFO undo causes Alice to accidentally erase Bob's work.",
        "• <b>Per-User Isolated Undo Stacks:</b>",
        "   - Server maintains separate undo_stacks[username] and redo_stacks[username].",
        "   - When Alice presses Ctrl+Z, server pops only Alice's most recent action: ('s', stroke_id) or ('c', [clear_ids]).",
        "• <b>Non-Destructive 'vis' Operations:</b>",
        "   - Strokes are NEVER deleted from server history log.",
        "   - Undo broadcasts {'k': 'vis', 'hide': [stroke_id], 'show': []}; clients flag stroke as hidden.",
        "   - Redo broadcasts {'k': 'vis', 'hide': [], 'show': [stroke_id]}, restoring original geometry and Z-order.",
        "• <b>Host Canvas Clear with Atomic Undo:</b>",
        "   - Only host can clear canvas (non-hosts receive 'denied').",
        "   - Clear hides all currently visible stroke IDs in one atomic vis op and pushes ('c', [ids]) on host's undo stack.",
        "   - Host can press Ctrl+Z to undo clear, restoring all strokes instantly."
    ]
    for idx, b in enumerate(undo_details):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('• ', '').replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(12)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(8)

    # =========================================================================
    # SLIDE 10: COLLABORATIVE FEATURES
    # =========================================================================
    s10 = prs.slides.add_slide(blank_layout)
    add_header(s10, "Application Feature Set")

    add_card(s10, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3), "Drawing & Visual Tools")
    tb = s10.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.2), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    tools = [
        "<b>Drawing Tools:</b> Freehand Pen, Eraser, Line, Rectangle, Oval, and Text annotations.",
        "<b>Sticky Notes:</b> Colored note cards with header tab and wrapped multi-line text (stored as text stroke with bg color).",
        "<b>Palette:</b> 8 quick color swatches + OS native RGB color picker dialog.",
        "<b>Live Ephemeral Cursors:</b> Colored pointer dots and username badges streaming at 50ms intervals.",
        "<b>Canvas Export:</b> Vector PostScript (.ps) export directly from Tkinter canvas."
    ]
    for idx, b in enumerate(tools):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    add_card(s10, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.3), "Room Governance & Persistence")
    tb = s10.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    gov = [
        "<b>Role-Based Access Control (RBAC):</b> Host, Editor, and Viewer. Host can right-click any user in roster to change permissions.",
        "<b>Presentation Mode:</b> Host toggles 'Present: ON'. All non-hosts are locked into view-only mode with a prominent red banner.",
        "<b>Group Chat:</b> Real-time chat panel with server timestamps and author colors.",
        "<b>Atomic Persistence:</b> Snapshots written via temporary files and os.replace() to prevent corruption; autosaves every 30s.",
        "<b>Named Version History:</b> Host can save checkpoints and restore historical snapshots on demand."
    ]
    for idx, b in enumerate(gov):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    # =========================================================================
    # SLIDE 11: SECURITY & KNOWN LIMITATIONS
    # =========================================================================
    s11 = prs.slides.add_slide(blank_layout)
    add_header(s11, "Security Architecture & Known Limitations")

    add_card(s11, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3), "Implemented Security Defenses")
    tb = s11.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(5.2), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    sec_def = [
        "<b>Path Traversal Prevention:</b> Version load/save requests sanitize paths using os.path.basename() and enforce regex validation (^[a-zA-Z0-9_-]+$). Prevents ../../ attacks.",
        "<b>Flood / DoS Protection:</b> Client sockets throttled to 400 messages/sec. Malicious flooding is dropped before processing.",
        "<b>Strict Schema Validation:</b> Strokes, coordinates, colors, and line widths are validated against bounding constraints; illegal payloads are rejected.",
        "<b>Host Privilege Enforcement:</b> All administrative actions (clear, versions, setrole, present) strictly verified against session identity."
    ]
    for idx, b in enumerate(sec_def):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    add_card(s11, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.3), "Known Lab Environment Limitations")
    tb = s11.shapes.add_textbox(Inches(7.0), Inches(2.1), Inches(5.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True
    sec_lim = [
        "<b>Plaintext Transport (No TLS):</b> Designed for an isolated university LAN. Socket traffic and passwords are not encrypted across the wire.",
        "<b>LAN Eavesdropping Risk:</b> An attacker with Wireshark on the same subnet could sniff packets or inject framed commands.",
        "<b>Production Upgrade Path:</b> Wrap client/server sockets with Python's standard ssl.wrap_socket() using self-signed TLS certificates for encrypted production deployment.",
        "<b>Memory Ceiling:</b> Maximum room capacity bounded to 30 active participants and 500 chat messages."
    ]
    for idx, b in enumerate(sec_lim):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11.5)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(12)

    # =========================================================================
    # SLIDE 12: AUTOMATED TESTING & VERIFICATION
    # =========================================================================
    s12 = prs.slides.add_slide(blank_layout)
    add_header(s12, "Verification & Automated Integration Testing")

    add_card(s12, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.3), "28 Automated Integration Tests on Localhost Sockets (test_integration.py)")
    tb = s12.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(11.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    tests_summary = [
        "• <b>Framing Verification:</b> Exact round-trips, 1-byte incremental read streaming, sticky packet separation, and oversized header rejection.",
        "• <b>Authentication & Room Lifecycle:</b> Correct/incorrect passwords, duplicate username handling, max room capacity rejection.",
        "• <b>Authoritative Deduplication:</b> Re-transmitting identical stroke IDs verifies idempotent sequence assignment.",
        "• <b>High-Concurrency Race Simulation:</b> 4 concurrent client threads emitting 40 strokes simultaneously; verified exact monotonic sequencing and identical SHA-256 canvas fingerprints across all 4 replicas.",
        "• <b>Isolated Undo/Redo & Host Clear:</b> Verified Alice's undo does not alter Bob's canvas state, and verified host clear/undo-clear.",
        "• <b>Inactivity Reaper & Disconnect Recovery:</b> Idle clients reaped after 15s; reconnected clients catch up via delta sync.",
        "• <b>Security & Persistence:</b> Path traversal rejection, atomic snapshot writes, and version restore.",
        "• <b>Pass Rate:</b> 28 / 28 Tests Passed (100% Pass Rate in ~6.5 seconds)."
    ]
    for idx, b in enumerate(tests_summary):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('• ', '').replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(12)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(8)

    # =========================================================================
    # SLIDE 13: SCREENSHOTS & LIVE DEMO PLACEHOLDERS
    # =========================================================================
    s13 = prs.slides.add_slide(blank_layout)
    add_header(s13, "Live Demonstration & System Screenshots")

    # 3 Placeholder Cards
    p1 = add_card(s13, Inches(0.8), Inches(1.5), Inches(3.6), Inches(5.3), "Main Canvas & Multi-Tool Drawing", fill_color=c_placeholder)
    tb1 = s13.shapes.add_textbox(Inches(0.9), Inches(2.2), Inches(3.4), Inches(4.4))
    tf1 = tb1.text_frame
    tf1.word_wrap = True
    p = tf1.paragraphs[0]
    p.text = "[SCREENSHOT PLACEHOLDER 1]\n\nInsert screenshot of active multi-user drawing session:\n• Canvas with pen, shapes, text, sticky notes\n• Color palette & width slider\n• Active participants roster & group chat"
    p.font.size = Pt(11)
    p.font.color.rgb = c_muted

    p2 = add_card(s13, Inches(4.85), Inches(1.5), Inches(3.6), Inches(5.3), "Host Presentation Mode", fill_color=c_placeholder)
    tb2 = s13.shapes.add_textbox(Inches(4.95), Inches(2.2), Inches(3.4), Inches(4.4))
    tf2 = tb2.text_frame
    tf2.word_wrap = True
    p = tf2.paragraphs[0]
    p.text = "[SCREENSHOT PLACEHOLDER 2]\n\nInsert screenshot of Presentation Mode active:\n• Top red banner: 'PRESENTATION MODE - CANVAS IS VIEW-ONLY'\n• Non-host client with disabled tool buttons\n• Host client with 'Present: ON' toggle"
    p.font.size = Pt(11)
    p.font.color.rgb = c_muted

    p3 = add_card(s13, Inches(8.9), Inches(1.5), Inches(3.6), Inches(5.3), "Roster Management & Versions", fill_color=c_placeholder)
    tb3 = s13.shapes.add_textbox(Inches(9.0), Inches(2.2), Inches(3.4), Inches(4.4))
    tf3 = tb3.text_frame
    tf3.word_wrap = True
    p = tf3.paragraphs[0]
    p.text = "[SCREENSHOT PLACEHOLDER 3]\n\nInsert screenshot of Host Administration dialogs:\n• Right-click context menu (Make Editor / Make Viewer)\n• 'Restore Board Version' modal dialog listing timestamped checkpoints"
    p.font.size = Pt(11)
    p.font.color.rgb = c_muted

    # =========================================================================
    # SLIDE 14: KEY DESIGN DECISIONS (VIVA CHEAT SHEET)
    # =========================================================================
    s14 = prs.slides.add_slide(blank_layout)
    add_header(s14, "Key Design Decisions & Viva Highlights")

    add_card(s14, Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.3), "Architecture Rationale for Viva Examination")
    tb = s14.shapes.add_textbox(Inches(1.0), Inches(2.1), Inches(11.3), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    viva_points = [
        "1. <b>Why raw TCP instead of WebSockets?</b> WebSockets add HTTP upgrade overhead, masking keys, and framing bloat. Raw TCP sockets allow direct demonstration of byte-stream framing and socket lifecycle with zero dependencies.",
        "2. <b>Why length-prefix (>I) over delimiter (newline / EOF)?</b> JSON payloads can contain arbitrary newlines or special characters. Escaping delimiters requires byte scanning and buffering; length-prefix allows reading exact byte chunks deterministically.",
        "3. <b>Why dedicated writer threads with bounded queues?</b> If the server executed socket.sendall() synchronously in the broadcast loop, one slow Wi-Fi client would block all other clients. Decoupled writer threads guarantee non-blocking broadcasts.",
        "4. <b>Why State Machine Replication over Operational Transformation (OT)?</b> The canvas is a 2D vector object tree, not a text document. Total ordering via monotonic sequence numbers guarantees convergence without complex character transformation matrices.",
        "5. <b>Why sys.frozen check for persistence?</b> PyInstaller single-file executables run inside a transient temp directory (_MEIxxxxxx). Detecting sys.frozen writes boards/ next to the permanent executable."
    ]
    for idx, b in enumerate(viva_points):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = b.replace('<b>', '').replace('</b>', '')
        p.font.size = Pt(11)
        p.font.color.rgb = c_charcoal
        p.space_after = Pt(8)

    # =========================================================================
    # SLIDE 15: CONCLUSION
    # =========================================================================
    s15 = prs.slides.add_slide(blank_layout)
    bg15 = s15.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
    bg15.fill.solid()
    bg15.fill.fore_color.rgb = c_navy
    bg15.line.fill.background()

    tb = s15.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(11.0), Inches(4.5))
    tf = tb.text_frame
    tf.word_wrap = True

    p = tf.paragraphs[0]
    p.text = "Conclusion & Project Summary"
    p.font.size = Pt(32)
    p.font.bold = True
    p.font.color.rgb = c_white

    p2 = tf.add_paragraph()
    p2.text = "\nKey Achievements:"
    p2.font.size = Pt(16)
    p2.font.bold = True
    p2.font.color.rgb = RGBColor(190, 227, 248)

    concl_points = [
        "• Successfully engineered a real-time collaborative application using strictly the Python standard library.",
        "• Demonstrated foundational networking principles: stream framing, socket tuning (TCP_NODELAY), concurrency, and heartbeat failure detection.",
        "• Implemented robust distributed algorithms: Authoritative SMR sequencing, per-user isolated undo, and automatic delta gap synchronization.",
        "• Verified with 28 automated integration tests and validated across offline laptops on local Wi-Fi / hotspot."
    ]
    for cp in concl_points:
        p = tf.add_paragraph()
        p.text = cp
        p.font.size = Pt(13)
        p.font.color.rgb = RGBColor(226, 232, 240)
        p.space_after = Pt(6)

    p_end = tf.add_paragraph()
    p_end.text = "\nThank You! Open for Questions & Live Demonstration."
    p_end.font.size = Pt(16)
    p_end.font.bold = True
    p_end.font.color.rgb = c_white
    p_end.space_before = Pt(18)

    prs.save(filename)
    print(f"Successfully generated {filename}")

if __name__ == "__main__":
    create_presentation()
