#!/usr/bin/env python3
"""Script to generate the comprehensive Technical Documentation PDF for the LAN Whiteboard.

Uses ReportLab Platypus to produce a publication-grade, structured PDF document
with exact code-grounded details across all 14 required sections.
"""

import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable, Preformatted
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print running page numbers and headers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        if self._pageNumber == 1:
            # Suppress header and footer on title cover page
            return

        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#718096"))

        # Running Top Header
        self.drawString(54, 750, "LAN Multi-User Collaborative Whiteboard — Technical Documentation")
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(54, 744, 558, 744)

        # Running Bottom Footer
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 36, page_text)
        self.drawString(54, 36, "Computer Networks Lab Project — Standard Library Implementation")
        self.line(54, 46, 558, 46)

        self.restoreState()


def build_pdf(filename="docs/Technical_Documentation.pdf"):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()

    # Custom Palette
    c_primary = colors.HexColor("#1A365D")    # Dark Navy
    c_secondary = colors.HexColor("#2B6CB0")  # Rich Blue
    c_dark = colors.HexColor("#2D3748")       # Charcoal text
    c_muted = colors.HexColor("#4A5568")      # Muted gray text
    c_bg_light = colors.HexColor("#F7FAFC")   # Light gray background
    c_border = colors.HexColor("#E2E8F0")     # Light border

    # Custom Typography Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=c_primary,
        alignment=0,
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=c_secondary,
        alignment=0,
        spaceAfter=15,
    )
    h1_style = ParagraphStyle(
        'SectionHeading1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=c_primary,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        'SectionHeading2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=c_secondary,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=c_dark,
        spaceAfter=6,
    )
    bullet_style = ParagraphStyle(
        'DocBullet',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=c_dark,
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3,
    )
    code_block_style = ParagraphStyle(
        'CodeBlock',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7.8,
        leading=10.5,
        textColor=colors.HexColor("#1A202C"),
        backColor=c_bg_light,
        borderColor=c_border,
        borderWidth=0.5,
        borderPadding=6,
        spaceBefore=4,
        spaceAfter=6,
    )
    table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=c_dark,
    )
    table_cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=11,
        textColor=c_primary,
    )
    table_cell_code = ParagraphStyle(
        'TableCellCode',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#742A2A"),
    )

    story = []

    # =========================================================================
    # TITLE & METADATA
    # =========================================================================
    story.append(Paragraph("LAN Multi-User Collaborative Whiteboard", title_style))
    story.append(Paragraph("System Architecture, Protocol Specification & Technical Reference Manual", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=c_secondary, spaceBefore=0, spaceAfter=12))

    meta_text = """
    <b>Author / Team:</b> Computer Networks Lab Group &nbsp;|&nbsp;
    <b>Language / Environment:</b> Python 3.10+ (Standard Library Only)<br/>
    <b>Transport:</b> TCP Sockets (LAN) &nbsp;|&nbsp;
    <b>Client UI:</b> Pure Tkinter / ttk &nbsp;|&nbsp;
    <b>Status:</b> Fully Functional, Offline Verified
    """
    story.append(Paragraph(meta_text, body_style))
    story.append(Spacer(1, 10))

    # =========================================================================
    # 1. INTRODUCTION AND GOALS
    # =========================================================================
    story.append(Paragraph("1. Introduction and Goals", h1_style))
    intro_p1 = """
    This project implements an interactive, multi-user, real-time collaborative whiteboard engineered to operate
    on an isolated Local Area Network (LAN) with <b>strictly zero internet connectivity</b>. Built entirely using the
    Python standard library (no pip packages, no external networking frameworks, no HTTP or WebSockets), it demonstrates
    fundamental computer networking principles: low-level socket programming, explicit stream framing, multi-threaded
    concurrency control, state-machine replication, and fault-tolerant session recovery.
    """
    story.append(Paragraph(intro_p1, body_style))

    goals = [
        "<b>Zero Dependency Footprint:</b> Uses only Python 3.10+ built-ins (<code>socket</code>, <code>threading</code>, <code>queue</code>, <code>json</code>, <code>struct</code>, <code>tkinter</code>, <code>hashlib</code>, <code>hmac</code>, <code>secrets</code>).",
        "<b>Interactive Latency:</b> Near-zero perceived lag on local Wi-Fi and Ethernet networks using TCP socket tuning (<code>TCP_NODELAY</code>) and 40 ms live stroke preview streaming.",
        "<b>Authoritative State Consistency:</b> Centralized sequencing guarantees strict total ordering across all distributed canvas replicas.",
        "<b>Per-User Undo/Redo Isolation:</b> Undo actions modify only the issuing user's drawing contributions without interfering with peers.",
        "<b>Robust Fault Tolerance:</b> Token-based session recovery, heartbeat keepalives, and automatic delta synchronization across transient link disruptions."
    ]
    for g in goals:
        story.append(Paragraph(f"• {g}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 2. SYSTEM ARCHITECTURE
    # =========================================================================
    story.append(Paragraph("2. System Architecture", h1_style))
    arch_p = """
    The system follows a star topology centered around a dedicated TCP server. Multiple desktop clients connect over
    raw TCP sockets on default port <code>5050</code>. The server manages isolated whiteboard <b>Rooms</b>, enforcing authorization,
    sequencing operations, and broadcasting canvas events.
    """
    story.append(Paragraph(arch_p, body_style))

    arch_diagram = """
+--------------------------------------------------------------------------------------------------+
|                                    CENTRAL TCP SERVER (server.py)                                 |
|                                                                                                  |
|   +--------------------------+          +----------------------------------------------------+   |
|   |   Acceptor Thread        |          |   Background Inactivity Reaper Thread              |   |
|   |   Listens on 0.0.0.0:5050|          |   Prunes dead sockets (timeout=15s, grace=120s)    |   |
|   +------------+-------------+          +----------------------------------------------------+   |
|                |                                                                                 |
|                v                                                                                 |
|   +------------------------------------------------------------------------------------------+   |
|   |   Room Management & Authoritative Sequencer (Room.lock: threading.RLock)                 |   |
|   |   - Global Log: [op0, op1, ...]   - Strokes: OrderedDict(id -> stroke)                  |   |
|   |   - Undo/Redo Stacks per User     - Members: Dict[uname -> Member]                      |   |
|   +------------------------------------------------------------------------------------------+   |
|                ^                                          ^                                      |
|    TCP Socket  |                              TCP Socket  |                                      |
|    Connection  |                              Connection  |                                      |
+----------------+------------------------------------------+--------------------------------------+
                 |                                          |
                 v                                          v
+------------------------------------+     +------------------------------------+
|         CLIENT 1 (client.py)       |     |         CLIENT 2 (client.py)       |
|                                    |     |                                    |
| +--------------------------------+ |     | +--------------------------------+ |
| |  Tkinter GUI Thread (Main)     | |     | |  Tkinter GUI Thread (Main)     | |
| |  Canvas, Toolbar, Chat, Roster | |     | |  Canvas, Toolbar, Chat, Roster | |
| +----------------+---------------+ |     | +----------------+---------------+ |
|                  ^ Events Queue    |     |                  ^ Events Queue    |
|                  v (queue.Queue)   |     |                  v (queue.Queue)   |
| +----------------+---------------+ |     | +----------------+---------------+ |
| |  Net Background Worker (net.py)| |     | |  Net Background Worker (net.py)| |
| |  - Reader Thread (framed recv) | |     | |  - Reader Thread (framed recv) | |
| |  - Sender Thread (send_queue)  | |     | |  - Sender Thread (send_queue)  | |
| |  - BoardState Canvas Replica   | |     | |  - BoardState Canvas Replica   | |
| +--------------------------------+ |     | +--------------------------------+ |
+------------------------------------+     +------------------------------------+
    """
    story.append(Preformatted(arch_diagram.strip(), code_block_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 3. WHY TCP (VS UDP)
    # =========================================================================
    story.append(Paragraph("3. Transport Protocol Selection: Why TCP vs UDP", h1_style))
    tcp_text = """
    In distributed real-time systems, transport selection represents a fundamental trade-off between throughput latency
    and state consistency. For a collaborative whiteboard, <b>TCP was deliberately chosen</b> over UDP for several critical reasons:
    """
    story.append(Paragraph(tcp_text, body_style))

    tcp_reasons = [
        "<b>Strict State Consistency:</b> A collaborative canvas is an accumulating distributed data structure. If drawing strokes were sent over UDP, lost packets would result in permanently missing stroke geometry, creating irrecoverable desynchronization across users.",
        "<b>In-Order Byte Delivery:</b> Geometric shapes, control messages, and canvas clears must be applied in the exact sequence they were generated. TCP guarantees in-order delivery through transmission sequence numbers and sliding-window acknowledgments.",
        "<b>Flow and Congestion Control:</b> TCP's windowing mechanisms prevent fast drawing clients from overwhelming slow clients or saturating local Wi-Fi bandwidth.",
        "<b>Mitigating Latency via TCP_NODELAY:</b> By default, TCP uses Nagle's algorithm to buffer small packets, introducing a 40–200 ms delay. By explicitly setting <code>sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)</code> on all client and server sockets, small packets are transmitted immediately, yielding sub-10 ms interactive drawing performance."
    ]
    for r in tcp_reasons:
        story.append(Paragraph(f"• {r}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 4. APPLICATION-LEVEL MESSAGE FORMAT & FRAMING
    # =========================================================================
    story.append(Paragraph("4. Application-Level Message Format & Framing", h1_style))
    framing_p = """
    Because TCP operates as an unsegmented continuous stream of bytes without record boundaries, application-level framing
    is required to prevent <i>sticky packets</i> (packet coalescing) and <i>partial reads</i> (fragmentation).
    Every message consists of a <b>4-byte big-endian unsigned integer prefix (<code>>I</code>)</b> encoding payload length $N$,
    followed immediately by $N$ bytes of UTF-8 encoded JSON.
    """
    story.append(Paragraph(framing_p, body_style))

    framing_box = """
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Message Length N (4-byte unsigned int, >I)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                    UTF-8 Encoded JSON Body                    +
|              {"t": "stroke", "id": "...", ...}                |
|                           (N bytes)                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    story.append(Preformatted(framing_box.strip(), code_block_style))

    msg_table_data = [
        [Paragraph("Message Type", table_cell_bold), Paragraph("Direction", table_cell_bold), Paragraph("Key Fields & Schema", table_cell_bold), Paragraph("Purpose / Behavioral Semantics", table_cell_bold)],
        [Paragraph("hello", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("room, user, pw, create, token?, last_seq?", table_cell), Paragraph("First message; authenticates or reconnects within 10s.", table_cell)],
        [Paragraph("welcome", table_cell_code), Paragraph("Srv → Client", table_cell), Paragraph("room, seq, host, you, users, chat, canvas, present, mode, strokes|ops", table_cell), Paragraph("Initial state payload (full snapshot or delta ops).", table_cell)],
        [Paragraph("stroke", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("id, s: {tool, color, width, pts, text?, bg?}", table_cell), Paragraph("Commits finished drawing element with deduplication.", table_cell)],
        [Paragraph("part", table_cell_code), Paragraph("Client ⇄ Srv", table_cell), Paragraph("u, sid, tool, color, width, mode, pts", table_cell), Paragraph("Ephemeral in-progress stroke preview (not saved in log).", table_cell)],
        [Paragraph("cursor", table_cell_code), Paragraph("Client ⇄ Srv", table_cell), Paragraph("u, color, x, y", table_cell), Paragraph("Live cursor streaming (ephemeral, 50ms intervals).", table_cell)],
        [Paragraph("op", table_cell_code), Paragraph("Srv → Broadcast", table_cell), Paragraph("seq, k, id, u, s?, hide?, show?, cause?, strokes?", table_cell), Paragraph("Sequenced canvas mutation (stroke, vis, or reset).", table_cell)],
        [Paragraph("ack", table_cell_code), Paragraph("Srv → Client", table_cell), Paragraph("id, seq", table_cell), Paragraph("Authoritative confirmation of client's committed stroke.", table_cell)],
        [Paragraph("undo / redo", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("(no extra payload)", table_cell), Paragraph("Reverts or restores calling user's most recent stroke.", table_cell)],
        [Paragraph("clear", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("(no extra payload)", table_cell), Paragraph("Host only: hides all visible strokes via sequenced 'vis' op.", table_cell)],
        [Paragraph("sync", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("last_seq", table_cell), Paragraph("Gap recovery request when seq jumps > seq + 1.", table_cell)],
        [Paragraph("delta / snapshot", table_cell_code), Paragraph("Srv → Client", table_cell), Paragraph("seq, ops (delta) | strokes (snapshot)", table_cell), Paragraph("Response to sync containing missed operations.", table_cell)],
        [Paragraph("chat", table_cell_code), Paragraph("Client ⇄ Srv", table_cell), Paragraph("id, user, color, text, ts", table_cell), Paragraph("Group chat message with server-assigned timestamp.", table_cell)],
        [Paragraph("save", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("label?", table_cell), Paragraph("Host only: persists named snapshot to server disk.", table_cell)],
        [Paragraph("saved / versions", table_cell_code), Paragraph("Srv → Client", table_cell), Paragraph("file | files: [str, ...]", table_cell), Paragraph("Confirmation of save or listing of available versions.", table_cell)],
        [Paragraph("load", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("file", table_cell), Paragraph("Host only: restores historical snapshot as reset op.", table_cell)],
        [Paragraph("setrole", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("user, role ('editor'|'viewer')", table_cell), Paragraph("Host only: elevates or restricts client permissions.", table_cell)],
        [Paragraph("present", table_cell_code), Paragraph("Client ⇄ Srv", table_cell), Paragraph("on: bool, by: str", table_cell), Paragraph("Host only: locks non-hosts into view-only presentation mode.", table_cell)],
        [Paragraph("ping / pong", table_cell_code), Paragraph("Client ⇄ Srv", table_cell), Paragraph("ts: float", table_cell), Paragraph("Heartbeat keepalive and round-trip latency measurement.", table_cell)],
        [Paragraph("users / notice", table_cell_code), Paragraph("Srv → Broadcast", table_cell), Paragraph("users: [...] | msg: str", table_cell), Paragraph("Roster updates and room lifecycle announcements.", table_cell)],
        [Paragraph("err", table_cell_code), Paragraph("Srv → Client", table_cell), Paragraph("code, msg, fatal: bool", table_cell), Paragraph("Structured error notification (e.g. bad_password, readonly).", table_cell)],
        [Paragraph("leave", table_cell_code), Paragraph("Client → Srv", table_cell), Paragraph("(no extra payload)", table_cell), Paragraph("Voluntary graceful disconnect notification.", table_cell)],
    ]

    t_msg = Table(msg_table_data, colWidths=[65, 55, 160, 224])
    t_msg.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_msg)
    story.append(Spacer(1, 10))

    # =========================================================================
    # 5. SOCKET COMMUNICATION & THREADING MODEL
    # =========================================================================
    story.append(Paragraph("5. Socket Communication and Threading Model", h1_style))
    thread_p = """
    To prevent slow or stalled network peers from impacting active clients, the server completely isolates network I/O
    from room state computation using a <b>multi-threaded decoupled pipeline</b>:
    """
    story.append(Paragraph(thread_p, body_style))

    thread_points = [
        "<b>Acceptor Thread:</b> Listens continuously on <code>0.0.0.0:5050</code>. For each accepted TCP socket, sets <code>TCP_NODELAY</code> and instantiates an isolated <code>ClientSession</code>.",
        "<b>Dedicated Reader Thread (Handler):</b> Executes a blocking read loop using <code>recv_exact()</code>. Dispatches framed messages to room logic under the protection of <code>Room.lock</code>.",
        "<b>Dedicated Writer Thread:</b> Drains an outbound bounded <code>queue.Queue(maxsize=5000)</code>. Socket writes occur strictly in this thread. If a client's send queue becomes full (bufferbloat / stall), the server severs the socket immediately.",
        "<b>Non-Blocking Broadcasts:</b> Room broadcasts execute <code>session.send_msg()</code> which invokes <code>put_nowait()</code> on the client's queue. Broadcasters never block on socket I/O.",
        "<b>Background Reaper Daemon:</b> Wakes every 1.0 second to inspect <code>ClientSession.last_activity</code>. Sockets with no inbound traffic for <code>--timeout</code> seconds (default 15s) are terminated.",
        "<b>Tkinter GUI Thread Isolation (Client):</b> The Tkinter GUI main thread never touches network sockets. Background worker threads in <code>netclient.py</code> communicate via a thread-safe <code>queue.Queue</code>, which the GUI polls safely every 30 ms using <code>root.after()</code>."
    ]
    for tp in thread_points:
        story.append(Paragraph(f"• {tp}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 6. SYNCHRONISATION STRATEGY
    # =========================================================================
    story.append(Paragraph("6. Synchronisation Strategy & State-Machine Replication", h1_style))
    sync_p = """
    The whiteboard follows the classic <b>State-Machine Replication (SMR)</b> model. The central server acts as the
    authoritative sequencer. The canvas state at sequence $N$ is a deterministic function of the ordered log of operations:
    $$S_N = f(S_0, op_1, op_2, \\dots, op_N)$$
    """
    story.append(Paragraph(sync_p, body_style))

    sync_bullets = [
        "<b>Global Sequence Number (seq):</b> Every committed canvas modification (stroke addition, visibility change, canvas reset) receives a strictly monotonic 64-bit sequence integer under <code>Room.lock</code>.",
        "<b>Optimistic Local Echo:</b> To guarantee instant drawing feedback, the local client renders its own stroke immediately marked as <code>pending</code>. When the server echoes the stroke back inside an <code>op</code>, the client clears the pending flag and reconciles its draw order if necessary.",
        "<b>Separation of Live Part vs Committed Stroke:</b> Mouse drags generate lightweight <code>part</code> messages relayed directly to peers for live rendering. Only upon mouse release is an immutable, validated <code>stroke</code> sent to the sequencer, preventing log bloating."
    ]
    for sb in sync_bullets:
        story.append(Paragraph(f"• {sb}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 7. CONCURRENCY HANDLING
    # =========================================================================
    story.append(Paragraph("7. Concurrency Handling & Thread Safety", h1_style))
    conc_p = """
    Thread safety across multiple concurrent users is maintained using strict lock scoping:
    """
    story.append(Paragraph(conc_p, body_style))

    conc_bullets = [
        "<b>Per-Room Re-entrant Locks (<code>Room.lock: threading.RLock</code>):</b> All operations mutating room state—member rosters, sequence log, strokes map, undo stacks, and versioning—require holding the room's lock.",
        "<b>Fine-Grained Global Server Lock (<code>WhiteboardServer._rooms_lock</code>):</b> Protects the server-wide room registry dictionary during room creation, discovery, and cleanup, preventing cross-room contention.",
        "<b>Lock Inversion & Deadlock Prevention:</b> Network transmissions (<code>send()</code>) are never performed while holding <code>Room.lock</code>. The room logic queues messages into memory buffers, releases the lock, and allows client writer threads to flush concurrently."
    ]
    for cb in conc_bullets:
        story.append(Paragraph(f"• {cb}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 8. ORDERING, DUPLICATES & GAP RESYNC
    # =========================================================================
    story.append(Paragraph("8. Ordering, Duplicates, Missing Updates & Gap Resync", h1_style))
    order_p = """
    In distributed environments, network latency and socket reconnections can introduce duplicated messages or gaps:
    """
    story.append(Paragraph(order_p, body_style))

    order_bullets = [
        "<b>Authoritative Deduplication:</b> Every stroke generates a unique UUID (e.g. <code>s_1731..._a1b2</code>). The server tracks all committed IDs in <code>Room.seen: Dict[stroke_id, seq]</code>. Re-transmitted strokes are acknowledged with their original sequence number and not re-applied.",
        "<b>Client Gap Detection:</b> When a client receives operation with sequence $S$:<br/>"
        "&nbsp;&nbsp;• If $S \\le \\text{local\\_seq}$: Duplicate operation; silently ignored.<br/>"
        "&nbsp;&nbsp;• If $S == \\text{local\\_seq} + 1$: Expected in-order operation; applied immediately.<br/>"
        "&nbsp;&nbsp;• If $S > \\text{local\\_seq} + 1$: Network gap detected! The op is placed in an out-of-order buffer, and the client issues a <code>sync</code> request.",
        "<b>Automatic Gap Drain:</b> Once the missing operations arrive via delta sync, <code>BoardState.apply_op()</code> iteratively drains all contiguous successors from the buffer."
    ]
    for ob in order_bullets:
        story.append(Paragraph(f"• {ob}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 9. UNDO / REDO SEMANTICS UNDER CONCURRENT USERS
    # =========================================================================
    story.append(Paragraph("9. Undo / Redo Semantics Under Concurrent Users", h1_style))
    undo_p = """
    Standard single-user undo stacks fail in collaborative environments because reverting the most recent global stroke
    would destroy another user's artwork. This system implements <b>Isolated Per-User Undo Stacks</b>:
    """
    story.append(Paragraph(undo_p, body_style))

    undo_rules = [
        "<b>User Isolation:</b> Undo and Redo operations affect <i>only</i> the caller's own strokes.",
        "<b>Non-Destructive Visibility Ops:</b> Strokes are never deleted from the authoritative history log. Instead, Undo emits a sequenced <code>vis</code> operation with <code>hide: [stroke_id]</code>, hiding the stroke across all peers.",
        "<b>Redo Restoration:</b> Redo emits a <code>vis</code> operation with <code>show: [stroke_id]</code>, restoring the stroke without altering its original Z-order placement.",
        "<b>Host Canvas Clear & Undo-Clear:</b> A canvas clear by the host emits a <code>vis</code> operation hiding all currently visible stroke IDs and pushes <code>('c', [hidden_ids])</code> onto the host's undo stack. The host can execute Undo to restore the entire canvas atomically."
    ]
    for ur in undo_rules:
        story.append(Paragraph(f"• {ur}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 10. CONNECTION MANAGEMENT & FAULT RECOVERY
    # =========================================================================
    story.append(Paragraph("10. Connection Management, Heartbeat & Fault Recovery", h1_style))
    conn_p = """
    The system gracefully survives physical cable disconnections, Wi-Fi roaming, and brief network outages:
    """
    story.append(Paragraph(conn_p, body_style))

    conn_bullets = [
        "<b>Ping / Pong Heartbeats:</b> Clients send a <code>ping</code> every 4.0 seconds. The server replies immediately with <code>pong</code>, calculating running round-trip latency.",
        "<b>Inactivity Reaper:</b> Clients inactive for 15.0 seconds are marked offline and their sockets closed.",
        "<b>Member Session Grace Period (120s):</b> Disconnected members are retained in <code>Room.members</code> for 120 seconds. Their role, color, and undo stacks are preserved.",
        "<b>Automatic Token Reconnection:</b> Upon reconnecting, the client presents its secret 16-byte session token and <code>last_seq</code> in the <code>hello</code> handshake. The server authenticates the member, re-associates the socket, and transmits only the delta operations missed during the outage."
    ]
    for cb in conn_bullets:
        story.append(Paragraph(f"• {cb}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 11. PERSISTENCE AND VERSION HISTORY
    # =========================================================================
    story.append(Paragraph("11. Persistence and Version History", h1_style))
    persist_p = """
    To ensure data durability across server restarts, the server maintains structured JSON snapshots:
    """
    story.append(Paragraph(persist_p, body_style))

    persist_bullets = [
        "<b>Atomic File Writes:</b> Snapshots are written to a temporary file (<code>.tmp</code>) and committed via <code>os.replace()</code>, ensuring atomic replacement that prevents corruption on power loss.",
        "<b>Automatic Background Autosave:</b> The server periodically checks for uncommitted changes and autosaves active rooms every 30 seconds to <code>boards/{room}/autosave.json</code>.",
        "<b>Named Version History:</b> Room hosts can save named checkpoints (<code>YYYYMMDD-HHMMSS_label.json</code>) and view/restore previous versions via a server-sequenced <code>reset</code> operation."
    ]
    for pb in persist_bullets:
        story.append(Paragraph(f"• {pb}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 12. SECURITY, ACCESS CONTROL & LIMITATIONS
    # =========================================================================
    story.append(Paragraph("12. Security, Access Control & Known Limitations", h1_style))
    sec_p = """
    Security mechanisms are tailored for an offline laboratory LAN environment:
    """
    story.append(Paragraph(sec_p, body_style))

    sec_bullets = [
        "<b>Role-Based Access Control (RBAC):</b> Three distinct roles: <i>Host</i> (full administrative control, versioning, canvas clear, role assignment, presentation mode), <i>Editor</i> (drawing, chat, own undo/redo), and <i>Viewer</i> (read-only canvas observation and chat).",
        "<b>Path Traversal Defense:</b> Filename inputs in version management are sanitized using <code>os.path.basename()</code> and validated to strictly match <code>^[a-zA-Z0-9_-]+$</code>, preventing directory traversal attacks.",
        "<b>Flood / Rate Limiting:</b> Client sockets are throttled to a maximum of 400 messages/second, preventing Denial-of-Service (DoS) attacks from rogue clients.",
        "<b>Known Lab Limitations:</b> Passwords are exchanged in plaintext over the LAN socket (no TLS layer), and data packets are unencrypted. In an untrusted production network, an attacker with a packet sniffer could capture room credentials or drawing coordinates."
    ]
    for sb in sec_bullets:
        story.append(Paragraph(f"• {sb}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 13. AUTOMATED TESTING
    # =========================================================================
    story.append(Paragraph("13. Automated Test Suite", h1_style))
    test_p = """
    The project includes a comprehensive headless integration test suite in <code>whiteboard/test_integration.py</code>
    utilizing loopback TCP sockets:
    """
    story.append(Paragraph(test_p, body_style))

    tests_list = [
        "<code>TestFraming</code>: Verifies exact round-trip framing, boundary isolation of back-to-back packets, 1-byte incremental delivery, and rejection of payloads exceeding <code>MAX_MSG</code> (4 MiB).",
        "<code>TestServerProtocol</code>: Tests room creation, password validation, wrong password rejection, duplicate username detection, and graceful disconnection.",
        "<code>TestDeduplication</code>: Validates that re-sending identical stroke IDs returns matching sequence numbers without duplicating canvas operations.",
        "<code>TestConcurrentStrokes</code>: Simulates 4 concurrent client threads transmitting 40 strokes simultaneously, asserting exact sequence ordering and identical canvas hash convergence across all clients.",
        "<code>TestUndoRedo</code>: Verifies per-user undo isolation, ensuring Alice's undo does not alter Bob's strokes, and verifies host canvas clear and undo-clear.",
        "<code>TestReconnectionAndReaper</code>: Tests automatic delta resync upon client reconnect and verifies that idle clients are pruned by the reaper daemon after timeout.",
        "<code>TestBoardPersistenceAndSecurity</code>: Tests atomic file saving, version restoration, and verifies path traversal rejection against malicious filenames.",
        "<code>TestBoardStateAndNetClient</code>: Tests client-side gap detection, out-of-order buffer reassembly, deterministic SHA-256 fingerprinting, and automatic network reconnection."
    ]
    for tl in tests_list:
        story.append(Paragraph(f"• {tl}", bullet_style))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 14. USER GUIDE
    # =========================================================================
    story.append(Paragraph("14. User Guide & Operating Manual", h1_style))
    ug_p = """
    Follow these instructions to run and operate the collaborative whiteboard across multiple machines:
    """
    story.append(Paragraph(ug_p, body_style))

    ug_steps = [
        "<b>Starting the Server:</b> On the host machine, run <code>python3 whiteboard/server.py</code> (or <code>whiteboard-server.exe</code>). The server binds to port <code>5050</code> and automatically prints its LAN IP address (e.g. <code>192.168.1.105</code>).",
        "<b>Firewall Configuration:</b> Ensure TCP port <code>5050</code> is permitted through the host firewall (Windows: allow prompt or <code>New-NetFirewallRule ... 5050 TCP</code>; Linux: <code>sudo ufw allow 5050/tcp</code>).",
        "<b>Connecting Clients:</b> On client machines, launch <code>python3 whiteboard/client.py</code> (or <code>whiteboard-client.exe</code>). Enter the Server IP, Port <code>5050</code>, Room Code, and Username.",
        "<b>Creating vs Joining:</b> The first user checks <i>'Create a new session (I am the host)'</i>. Subsequent participants leave this unchecked to join the existing room.",
        "<b>Using Tools:</b> Select <i>Pen</i> or <i>Eraser</i> for freehand drawing; <i>Line</i>, <i>Rectangle</i>, or <i>Oval</i> for geometric shapes; <i>Text</i> for annotations; or <i>Note</i> for sticky notes. Pick colors from the palette or click <i>'More...'</i> for the full RGB chooser.",
        "<b>Presentation Mode:</b> The host can click <i>'Present: OFF'</i> to toggle Presentation Mode. All other participants become view-only with a red warning banner until the host turns it off.",
        "<b>Saving & Restoring:</b> The host clicks <i>'Save Version'</i> to record a checkpoint. Clicking <i>'Versions...'</i> opens a list of saved snapshots for instant restoration."
    ]
    for ugs in ug_steps:
        story.append(Paragraph(f"• {ugs}", bullet_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated {filename}")

if __name__ == "__main__":
    build_pdf()

