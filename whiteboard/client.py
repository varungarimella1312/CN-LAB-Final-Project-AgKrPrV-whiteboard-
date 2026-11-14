"""Tkinter GUI client for the LAN Collaborative Whiteboard.

Computer Networks Lab - LAN Collaborative Whiteboard
Module: whiteboard.client

Role & Architecture:
--------------------
This module implements the user-facing graphical whiteboard application.
It integrates the pure-data canvas model (`BoardState`) with the non-blocking
background network thread (`Net`).

Key Architectural Principles:
-----------------------------
1. Non-Blocking Event-Driven GUI:
   All socket operations (connect, send, receive, reconnect) execute exclusively
   on background threads managed by `Net`. The Tkinter main thread remains 100%
   responsive at all times. It consumes messages via `root.after(15, self._pump_events)`
   from a thread-safe `queue.Queue`.
2. Model-View-Controller (MVC) Pattern:
   - Model: `BoardState` (`boardstate.py`) manages strokes, sequence tracking,
     gap buffering, and optimistic echo.
   - Controller: `Net` (`netclient.py`) handles TCP framing, automatic reconnects,
     and periodic heartbeats.
   - View: `WhiteboardApp` (`client.py`) renders canvas items, tools, participant
     rosters, and chat dialogs.
3. Live Interactive Overlays:
   - While dragging, partial strokes (`part`) are streamed every 40 ms so peers
     see real-time drawing previews before mouse release.
   - Mouse movements stream `cursor` coordinates (throttled to 50 ms) showing
     labeled, color-coded user pointers that fade after 3 seconds of inactivity.
4. Role-Based Permissions:
   - "Host": Full editing, canvas clearing, version saving, and participant role assignment.
   - "Editor": Collaborative drawing, undo/redo of personal strokes, and chat.
   - "Viewer": Read-only observation with drawing tools disabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import secrets
import sys
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Tuple

# Support running directly (`python client.py`) or as a module
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
        TOOL_ERASER,
        TOOL_LINE,
        TOOL_OVAL,
        TOOL_PEN,
        TOOL_RECTANGLE,
    )
    from whiteboard.boardstate import BoardState
    from whiteboard.netclient import Net
except ImportError:
    from protocol import (  # type: ignore
        CANVAS_H,
        CANVAS_W,
        PORT_DEFAULT,
        TOOL_ERASER,
        TOOL_LINE,
        TOOL_OVAL,
        TOOL_PEN,
        TOOL_RECTANGLE,
    )
    from boardstate import BoardState  # type: ignore
    from netclient import Net  # type: ignore

# Palette of 8 quick-select color swatches
QUICK_PALETTE: list[str] = [
    "#000000",  # Black
    "#E6194B",  # Red
    "#3CB44B",  # Green
    "#4363D8",  # Blue
    "#F58231",  # Orange
    "#911EB4",  # Purple
    "#46F0F0",  # Cyan
    "#FFE119",  # Yellow
]


def _session_token_file(
    host: str,
    port: int,
    username: str,
    base_dir: Optional[str] = None,
) -> str:
    if base_dir is None:
        if os.name == "nt":
            base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        elif sys.platform == "darwin":
            base_dir = os.path.join(
                os.path.expanduser("~"), "Library", "Application Support"
            )
        else:
            base_dir = os.environ.get("XDG_STATE_HOME") or os.path.join(
                os.path.expanduser("~"), ".local", "state"
            )

    identity = json.dumps([host, port, username], separators=(",", ":"))
    identity_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return os.path.join(
        base_dir,
        "LANCollaborativeWhiteboard",
        "session_tokens",
        f"{identity_key}.json",
    )


def _load_saved_session_token(
    host: str,
    port: int,
    username: str,
    base_dir: Optional[str] = None,
) -> Optional[str]:
    path = _session_token_file(host, port, username, base_dir)
    try:
        with open(path, "r", encoding="utf-8") as token_file:
            data = json.load(token_file)
    except FileNotFoundError:
        return None

    token = data.get("token") if isinstance(data, dict) else None
    if token is None:
        return None
    if not isinstance(token, str) or len(token) != 32 or any(
        char not in "0123456789abcdef" for char in token
    ):
        raise ValueError(f"Invalid saved session token in {path}")
    return token


def _save_session_token(
    host: str,
    port: int,
    username: str,
    token: str,
    base_dir: Optional[str] = None,
) -> None:
    if len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
        raise ValueError("The server returned an invalid session token")

    path = _session_token_file(host, port, username, base_dir)
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temp_path = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as token_file:
            json.dump({"token": token}, token_file)
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except OSError:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise


class WhiteboardApp:
    """Main Tkinter Collaborative Whiteboard GUI Application."""

    def __init__(self, root: tk.Tk, default_host: str = "127.0.0.1", default_port: int = PORT_DEFAULT) -> None:
        self.root = root
        self.root.title("LAN Collaborative Whiteboard")
        self.root.geometry("1400x820")
        self.root.minsize(1000, 650)

        # Networking & Canvas Models
        self.default_host = default_host
        self.default_port = default_port
        self.events_queue: queue.Queue[Tuple[str, Any]] = queue.Queue()
        self.net: Optional[Net] = None
        self.board: BoardState = BoardState(CANVAS_W, CANVAS_H)

        # Session & Identity Credentials
        self.room_code: str = ""
        self.username: str = ""
        self.password: str = ""
        self.login_is_host: bool = False
        self.host_code: str = ""
        self.session_token: Optional[str] = None
        self._session_token_context: Optional[Tuple[str, int, str, str]] = None
        self._connection_context: Optional[Tuple[str, int, str, str]] = None
        self._activity_join_logged: bool = False
        self.my_role: str = "editor"  # "host", "editor", "viewer"
        self.my_color: str = "#000000"
        self.presentation_mode: bool = False

        # Active Drawing Settings
        self.current_tool: str = "pen"  # pen, eraser, line, rect, oval, text
        self.current_color: str = "#000000"
        self.current_width: int = 3
        self.lbl_width_val: Optional[ttk.Label] = None

        # Ephemeral Local Drawing State
        self.is_drawing: bool = False
        self.current_stroke_id: Optional[str] = None
        self.drag_points: List[List[int]] = []
        self.last_part_sent_time: float = 0.0
        self.last_cursor_sent_time: float = 0.0
        self.last_sync_time: float = 0.0
        self.round_trip_latency_ms: float = 0.0

        # Ephemeral Peer Overlays tracking: peer_username -> last_seen_timestamp
        self.peer_cursor_times: Dict[str, float] = {}
        self.peer_cursor_items: Dict[str, Tuple[int, int]] = {}

        # Build Login & Main View Containers
        self.main_container = ttk.Frame(self.root)
        self.login_frame = ttk.Frame(self.root)

        self._build_login_screen()
        self._build_main_whiteboard_layout()

        # Show login screen initially
        self.main_container.pack_forget()
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        # Window protocols & background polling timer
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)
        self.root.after(15, self._pump_network_events)
        self.root.after(1000, self._reap_stale_cursors)

    # =========================================================================
    # LOGIN / CONNECTION SCREEN
    # =========================================================================

    def _build_login_screen(self) -> None:
        """Constructs the initial connection and room join dialog."""
        card = ttk.LabelFrame(self.login_frame, text=" Connect to LAN Whiteboard ", padding=25)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Server Address
        ttk.Label(card, text="Server IP Address:").grid(row=0, column=0, sticky=tk.W, pady=6)
        self.entry_host = ttk.Entry(card, width=28)
        self.entry_host.insert(0, self.default_host)
        self.entry_host.grid(row=0, column=1, pady=6, padx=8)

        # Port
        ttk.Label(card, text="Port:").grid(row=1, column=0, sticky=tk.W, pady=6)
        self.entry_port = ttk.Entry(card, width=28)
        self.entry_port.insert(0, str(self.default_port))
        self.entry_port.grid(row=1, column=1, pady=6, padx=8)

        # Select participant role
        ttk.Label(card, text="Join as:").grid(row=2, column=0, sticky=tk.W, pady=6)
        self.login_role_var = tk.StringVar(value="participant")
        role_frame = ttk.Frame(card)
        role_frame.grid(row=2, column=1, sticky=tk.W, pady=6, padx=8)
        ttk.Radiobutton(
            role_frame,
            text="Host",
            variable=self.login_role_var,
            value="host",
            command=self._update_login_role_fields,
        ).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(
            role_frame,
            text="Participant",
            variable=self.login_role_var,
            value="participant",
            command=self._update_login_role_fields,
        ).pack(side=tk.LEFT)

        self.lbl_login_room = ttk.Label(
            card, text="Room Code: displayed after connecting"
        )
        self.lbl_login_room.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=6)

        # Username
        ttk.Label(card, text="Your Name:").grid(row=4, column=0, sticky=tk.W, pady=6)
        self.entry_user = ttk.Entry(card, width=28)
        self.entry_user.insert(0, f"User_{secrets.token_hex(2)}")
        self.entry_user.grid(row=4, column=1, pady=6, padx=8)

        # Host code (shown only for the host role)
        self.lbl_host_code = ttk.Label(card, text="Host Code:")
        self.lbl_host_code.grid(row=5, column=0, sticky=tk.W, pady=6)
        self.entry_host_code = ttk.Entry(card, width=28)
        self.entry_host_code.grid(row=5, column=1, pady=6, padx=8)

        # Password
        ttk.Label(card, text="Room Password:").grid(row=6, column=0, sticky=tk.W, pady=6)
        self.entry_pass = ttk.Entry(card, width=28)
        self.entry_pass.insert(0, "")
        self.entry_pass.grid(row=6, column=1, pady=6, padx=8)

        # Connect Button & Status Message
        self.btn_connect = ttk.Button(card, text="Connect & Enter", command=self.on_click_connect)
        self.btn_connect.grid(row=7, column=0, columnspan=2, pady=12, sticky=tk.EW)

        self.lbl_login_status = ttk.Label(card, text="", foreground="red")
        self.lbl_login_status.grid(row=8, column=0, columnspan=2, pady=4)
        ttk.Label(card, text="Use the room password printed in the server terminal.").grid(
            row=9, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )
        ttk.Label(card, text="Host code is only needed when joining as the host.").grid(
            row=10, column=0, columnspan=2, sticky=tk.W, pady=(2, 0)
        )
        self._update_login_role_fields()

    def _update_login_role_fields(self) -> None:
        """Shows the host verification field only when the host role is selected."""
        if self.login_role_var.get() == "host":
            self.lbl_host_code.grid()
            self.entry_host_code.grid()
        else:
            self.lbl_host_code.grid_remove()
            self.entry_host_code.grid_remove()

    def on_click_connect(self) -> None:
        """Validates login fields and initializes the Net background connection."""
        host = self.entry_host.get().strip()
        port_str = self.entry_port.get().strip()
        user = self.entry_user.get().strip()
        pw = self.entry_pass.get()
        login_is_host = self.login_role_var.get() == "host"
        host_code = self.entry_host_code.get().strip() if login_is_host else ""

        if not host:
            self.lbl_login_status.config(text="Server address is required")
            return
        try:
            port = int(port_str)
        except ValueError:
            self.lbl_login_status.config(text="Port must be a valid number")
            return

        if not user or len(user) < 1:
            self.lbl_login_status.config(text="Username is required")
            return

        if len(pw) != 4 or not pw.isdigit():
            self.lbl_login_status.config(text="Room password must be the 4-digit code from the server")
            return

        if login_is_host and (len(host_code) != 4 or not host_code.isdigit()):
            self.lbl_login_status.config(text="Host code must be the 4-digit code from the server")
            return

        self.room_code = ""
        self.username = user
        self.password = pw
        self.login_is_host = login_is_host
        self.host_code = host_code
        connection_context = (host, port, user, pw)
        self._connection_context = connection_context
        if not (
            self.session_token
            and self._session_token_context == connection_context
        ):
            try:
                self.session_token = _load_saved_session_token(host, port, user)
            except (OSError, ValueError) as exc:
                self.session_token = None
                messagebox.showwarning(
                    "Saved Session",
                    f"Could not restore the saved session token:\n{exc}",
                    parent=self.root,
                )
            self._session_token_context = (
                connection_context if self.session_token else None
            )
        self._activity_join_logged = False
        self.lbl_login_room.config(text="Room Code: connecting to server...")

        self.lbl_login_status.config(text="Connecting to server...", foreground="blue")
        self.btn_connect.config(state=tk.DISABLED)

        # Define dynamic hello payload generator for initial join and reconnections
        def get_hello() -> Dict[str, Any]:
            hello = {
                "t": "hello",
                "user": self.username,
                "pw": self.password,
                "is_host": self.login_is_host,
            }
            if self.login_is_host:
                hello["host_code"] = self.host_code
            if (
                self.session_token
                and self._session_token_context == connection_context
            ):
                hello["token"] = self.session_token
                hello["last_seq"] = self.board.seq
            return hello

        # Stop any existing network thread and start fresh Net client
        if self.net:
            self.net.stop()

        self.net = Net(
            events_queue=self.events_queue,
            host=host,
            port=port,
            get_hello=get_hello,
            reconnect_delay=2.0,
        )

    def return_to_login(self, error_message: str = "") -> None:
        """Transitions back to the connection screen upon fatal error or disconnect."""
        if self.net:
            self.net.stop()
            self.net = None

        # Reset local canvas and replica state for a clean slate
        self.presentation_mode = False
        try:
            self.banner_present.pack_forget()
        except Exception:
            pass
        self.board = BoardState(CANVAS_W, CANVAS_H)
        self.canvas.delete("all")
        self.tree_users.delete(*self.tree_users.get_children())
        self.lbl_active_users.config(text="Active Users (0)")
        self.chat_recipient_var.set("Everyone")
        self.chat_recipient_combo.configure(values=("Everyone",))
        self.text_activity.config(state=tk.NORMAL)
        self.text_activity.delete("1.0", tk.END)
        self.text_activity.config(state=tk.DISABLED)
        self.text_chat.config(state=tk.NORMAL)
        self.text_chat.delete("1.0", tk.END)
        self.text_chat.config(state=tk.DISABLED)

        self.main_container.pack_forget()
        self.login_frame.pack(fill=tk.BOTH, expand=True)
        self.btn_connect.config(state=tk.NORMAL)
        if error_message:
            self.lbl_login_status.config(text=error_message, foreground="red")
        else:
            self.lbl_login_status.config(text="")
        self.lbl_login_room.config(text="Room Code: displayed after connecting")

    # =========================================================================
    # MAIN WHITEBOARD LAYOUT
    # =========================================================================

    def _build_main_whiteboard_layout(self) -> None:
        """Builds toolbar, canvas, participant roster, chat, and status bar."""
        # Top Container holds Toolbar, Canvas, and Right Sidebar
        top_body = ttk.Frame(self.main_container)
        top_body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 1. Left Toolbar
        toolbar = ttk.Frame(top_body, padding=6, width=160)
        toolbar.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        self._build_toolbar(toolbar)

        # 2. Center Canvas Viewport with Scrollbars
        canvas_frame = ttk.Frame(top_body, padding=2)

        self.banner_present = tk.Label(
            canvas_frame,
            text="PRESENTATION MODE - VIEW ONLY",
            bg="#D9534F",
            fg="white",
            font=("Helvetica", 11, "bold"),
            pady=4,
        )

        self.canvas = tk.Canvas(
            canvas_frame,
            width=CANVAS_W,
            height=CANVAS_H,
            bg="white",
            cursor="crosshair",
            highlightthickness=1,
            highlightbackground="#CCCCCC",
        )
        self.lbl_room_code_top = ttk.Label(
            canvas_frame,
            text="Room Code: --",
            font=("Helvetica", 9, "bold"),
        )
        self.lbl_room_code_top.pack(side=tk.TOP, anchor=tk.W, padx=4, pady=(0, 2))
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Canvas Mouse Event Bindings
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Motion>", self.on_canvas_motion)

        # Keyboard shortcuts for undo/redo
        self.root.bind("<Control-z>", lambda e: self.on_click_undo())
        self.root.bind("<Control-y>", lambda e: self.on_click_redo())
        self.root.bind("<Command-z>", lambda e: self.on_click_undo())
        self.root.bind("<Command-Shift-Z>", lambda e: self.on_click_redo())
        self.root.bind("<Command-y>", lambda e: self.on_click_redo())

        # 3. Right Sidebar (Participants & Chat)
        sidebar = ttk.Frame(top_body, padding=6, width=270)
        sidebar.pack_propagate(False)
        sidebar.pack(side=tk.RIGHT, fill=tk.BOTH, padx=4, pady=4)
        self._build_sidebar(sidebar)

        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 4. Bottom Status Bar
        self.status_bar = ttk.Frame(self.main_container, padding=4, relief=tk.SUNKEN)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.lbl_status_conn = ttk.Label(self.status_bar, text="Status: Connected")
        self.lbl_status_conn.pack(side=tk.LEFT, padx=10)

        self.lbl_status_room = ttk.Label(self.status_bar, text="Room: -")
        self.lbl_status_room.pack(side=tk.LEFT, padx=10)

        self.lbl_status_role = ttk.Label(self.status_bar, text="Role: Editor")
        self.lbl_status_role.pack(side=tk.LEFT, padx=10)

        self.lbl_status_seq = ttk.Label(self.status_bar, text="Seq: 0")
        self.lbl_status_seq.pack(side=tk.RIGHT, padx=10)

        self.lbl_status_ping = ttk.Label(self.status_bar, text="Latency: - ms")
        self.lbl_status_ping.pack(side=tk.RIGHT, padx=10)

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        """Constructs drawing tools, color swatches, stroke width, and control buttons."""
        # Tool Selection Buttons
        ttk.Label(parent, text="Tools", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(0, 4))

        self.tool_buttons: Dict[str, ttk.Button] = {}
        tools = [
            ("Pen", "pen"),
            ("Eraser", "eraser"),
            ("Line", "line"),
            ("Rectangle", "rect"),
            ("Oval", "oval"),
            ("Text", "text"),
            ("Note", "note"),
        ]
        for label, tool_id in tools:
            btn = ttk.Button(parent, text=label, command=lambda t=tool_id: self.select_tool(t))
            btn.pack(fill=tk.X, pady=2)
            self.tool_buttons[tool_id] = btn

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Colors Palette
        ttk.Label(parent, text="Palette", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, pady=(0, 4))

        swatch_frame = ttk.Frame(parent)
        swatch_frame.pack(fill=tk.X, pady=2)

        for idx, color_hex in enumerate(QUICK_PALETTE):
            row = idx // 4
            col = idx % 4
            lbl = tk.Label(
                swatch_frame,
                bg=color_hex,
                width=3,
                height=1,
                relief=tk.RAISED,
                cursor="hand2",
            )
            lbl.grid(row=row, column=col, padx=2, pady=2)
            lbl.bind("<Button-1>", lambda e, c=color_hex: self.select_color(c))

        btn_more_color = ttk.Button(parent, text="More...", command=self.on_click_more_colors)
        btn_more_color.pack(fill=tk.X, pady=4)

        self.color_preview = tk.Label(
            parent, text="Current Color", bg=self.current_color, fg="white", relief=tk.SUNKEN
        )
        self.color_preview.pack(fill=tk.X, pady=4)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Line Width Slider
        ttk.Label(parent, text="Stroke Width", font=("Helvetica", 10, "bold")).pack(anchor=tk.W)
        self.lbl_width_val = ttk.Label(parent, text=f"Width: {self.current_width}px")
        self.slider_width = ttk.Scale(
            parent, from_=1, to=30, orient=tk.HORIZONTAL, command=self.on_change_width
        )
        self.slider_width.set(self.current_width)
        self.slider_width.pack(fill=tk.X, pady=2)
        self.lbl_width_val.pack(anchor=tk.W)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Action Buttons (Undo, Redo, Clear)
        self.btn_undo = ttk.Button(parent, text="Undo (Ctrl+Z)", command=self.on_click_undo)
        self.btn_undo.pack(fill=tk.X, pady=2)

        self.btn_redo = ttk.Button(parent, text="Redo (Ctrl+Y)", command=self.on_click_redo)
        self.btn_redo.pack(fill=tk.X, pady=2)

        self.btn_clear = ttk.Button(parent, text="Clear Canvas", command=self.on_click_clear)
        self.btn_clear.pack(fill=tk.X, pady=2)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Host Version Management & File Export
        self.btn_present = ttk.Button(
            parent, text="Present: OFF", command=self.on_toggle_present
        )
        self.btn_present.pack(fill=tk.X, pady=2)

        self.btn_save_ver = ttk.Button(
            parent, text="Save Version", command=self.on_click_save_version
        )
        self.btn_save_ver.pack(fill=tk.X, pady=2)

        self.btn_load_ver = ttk.Button(
            parent, text="Versions...", command=self.on_click_list_versions
        )
        self.btn_load_ver.pack(fill=tk.X, pady=2)

        self.btn_export = ttk.Button(parent, text="Export (.ps)", command=self.on_click_export)
        self.btn_export.pack(fill=tk.X, pady=2)

        self.btn_leave = ttk.Button(parent, text="Leave Session", command=self.on_click_leave)
        self.btn_leave.pack(fill=tk.X, pady=(12, 2))

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        """Constructs the active-user roster, activity log, and chat panel."""
        self.lbl_active_users = ttk.Label(
            parent, text="Active Users (0)", font=("Helvetica", 10, "bold")
        )
        self.lbl_active_users.pack(anchor=tk.W)

        roster_frame = ttk.Frame(parent)
        roster_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 6))

        self.tree_users = ttk.Treeview(
            roster_frame, columns=("role",), show="tree headings", selectmode="browse"
        )
        self.tree_users.heading("#0", text="User")
        self.tree_users.heading("role", text="Role")
        self.tree_users.column("#0", width=150)
        self.tree_users.column("role", width=85)
        self.tree_users.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        user_scroll = ttk.Scrollbar(roster_frame, orient=tk.VERTICAL, command=self.tree_users.yview)
        self.tree_users.configure(yscrollcommand=user_scroll.set)
        user_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Host Right-Click Role Assignment Menu
        self.menu_user_role = tk.Menu(self.root, tearoff=0)
        self.menu_user_role.add_command(
            label="Make Editor", command=lambda: self.on_set_user_role("editor")
        )
        self.menu_user_role.add_command(
            label="Make Viewer", command=lambda: self.on_set_user_role("viewer")
        )
        self.menu_user_role.add_separator()
        self.menu_user_role.add_command(
            label="Kick User", command=self.on_kick_user
        )
        self.tree_users.bind("<Button-2>", self.on_user_right_click)  # macOS
        self.tree_users.bind("<Button-3>", self.on_user_right_click)  # Windows / Linux

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)

        ttk.Label(parent, text="Recent Activity", font=("Helvetica", 10, "bold")).pack(
            anchor=tk.W
        )
        activity_frame = ttk.Frame(parent)
        activity_frame.pack(fill=tk.X, pady=(2, 6))

        self.text_activity = tk.Text(
            activity_frame,
            wrap=tk.WORD,
            width=30,
            height=5,
            state=tk.DISABLED,
            bg="#FFFFFF",
            fg="#1A202C",
            font=("Helvetica", 9),
        )
        self.text_activity.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        activity_scroll = ttk.Scrollbar(
            activity_frame, orient=tk.VERTICAL, command=self.text_activity.yview
        )
        self.text_activity.configure(yscrollcommand=activity_scroll.set)
        activity_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)

        # Bottom Half: Group and Private Chat
        chat_panel = ttk.Frame(parent)
        chat_panel.pack(fill=tk.BOTH, expand=True, pady=2)
        chat_panel.columnconfigure(0, weight=1)
        chat_panel.rowconfigure(1, weight=1)

        ttk.Label(chat_panel, text="Chat", font=("Helvetica", 10, "bold")).grid(
            row=0, column=0, sticky=tk.W
        )

        chat_frame = ttk.Frame(chat_panel)
        chat_frame.grid(row=1, column=0, sticky=tk.NSEW, pady=(2, 0))

        self.text_chat = tk.Text(
            chat_frame,
            wrap=tk.WORD,
            width=30,
            height=6,
            state=tk.DISABLED,
            bg="#FFFFFF",
            fg="#1A202C",
            insertbackground="#1A202C",
            selectbackground="#CBD5E0",
            selectforeground="#1A202C",
            font=("Helvetica", 9),
        )
        self.text_chat.tag_configure("time", foreground="#718096", font=("Helvetica", 8))
        self.text_chat.tag_configure("msg", foreground="#1A202C", font=("Helvetica", 9))
        self.text_chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        chat_scroll = ttk.Scrollbar(chat_frame, orient=tk.VERTICAL, command=self.text_chat.yview)
        self.text_chat.configure(yscrollcommand=chat_scroll.set)
        chat_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        recipient_frame = ttk.Frame(chat_panel)
        recipient_frame.grid(row=2, column=0, sticky=tk.EW, pady=(4, 0))
        ttk.Label(recipient_frame, text="To:").pack(side=tk.LEFT, padx=(0, 4))
        self.chat_recipient_var = tk.StringVar(value="Everyone")
        self.chat_recipient_combo = ttk.Combobox(
            recipient_frame,
            textvariable=self.chat_recipient_var,
            values=("Everyone",),
            state="readonly",
            width=18,
        )
        self.chat_recipient_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Chat Entry & Send
        send_frame = ttk.Frame(chat_panel)
        send_frame.grid(row=3, column=0, sticky=tk.EW, pady=4)

        self.entry_chat = ttk.Entry(send_frame)
        self.entry_chat.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.entry_chat.bind("<Return>", self.on_send_chat)
        self.entry_chat.bind("<KP_Enter>", self.on_send_chat)

        btn_send = ttk.Button(send_frame, text="Send", width=6, command=self.on_send_chat)
        btn_send.pack(side=tk.RIGHT)

    # =========================================================================
    # TOOLBAR & ACTION HANDLERS
    # =========================================================================

    def select_tool(self, tool_id: str) -> None:
        """Switches active drawing tool."""
        self.current_tool = tool_id
        for tid, btn in self.tool_buttons.items():
            btn.state(["!pressed"])
        if tool_id in self.tool_buttons:
            self.tool_buttons[tool_id].state(["pressed"])

    def select_color(self, hex_color: str) -> None:
        """Sets active drawing color."""
        self.current_color = hex_color
        fg = "white" if hex_color not in {"#FFE119", "#46F0F0", "#AAFFC3"} else "black"
        self.color_preview.config(bg=hex_color, fg=fg)

    def on_click_more_colors(self) -> None:
        """Opens native OS color chooser dialog."""
        chosen = colorchooser.askcolor(color=self.current_color, title="Select Stroke Color", parent=self.root)
        if chosen and chosen[1]:
            self.select_color(chosen[1])

    def on_change_width(self, val: str) -> None:
        """Updates line thickness from slider."""
        self.current_width = int(float(val))
        if hasattr(self, "lbl_width_val") and self.lbl_width_val is not None:
            self.lbl_width_val.config(text=f"Width: {self.current_width}px")

    def on_click_undo(self) -> None:
        """Sends undo request to server."""
        if self.my_role == "viewer":
            return
        if self.net:
            self.net.send({"t": "undo"})

    def on_click_redo(self) -> None:
        """Sends redo request to server."""
        if self.my_role == "viewer":
            return
        if self.net:
            self.net.send({"t": "redo"})

    def on_click_clear(self) -> None:
        """Sends clear canvas request to server (host only)."""
        if self.my_role != "host":
            messagebox.showinfo("Clear", "Only the host can clear the whiteboard canvas.")
            return
        if messagebox.askyesno("Clear Canvas", "Are you sure you want to clear the canvas?"):
            if self.net:
                self.net.send({"t": "clear"})

    def on_click_save_version(self) -> None:
        """Prompts host for a version label and requests server snapshot."""
        if self.my_role != "host":
            messagebox.showinfo("Save Version", "Only the host can save version snapshots.", parent=self.root)
            return
        label = simpledialog.askstring("Save Version", "Enter version label (letters, numbers, underscores):", parent=self.root)
        if label and label.strip():
            clean_label = "".join(c for c in label.strip() if c.isalnum() or c in "_-")
            if self.net:
                self.net.send({"t": "save", "label": clean_label})

    def on_click_list_versions(self) -> None:
        """Queries server for saved version files."""
        if self.net:
            self.net.send({"t": "versions"})

    def on_click_export(self) -> None:
        """Exports the canvas to an Encapsulated PostScript (.ps) file."""
        filepath = filedialog.asksaveasfilename(
            defaultextension=".ps",
            filetypes=[("PostScript Files", "*.ps"), ("All Files", "*.*")],
            title="Export Canvas to PostScript",
        )
        if filepath:
            try:
                self.canvas.postscript(file=filepath, colormode="color")
                messagebox.showinfo("Export Successful", f"Canvas exported to:\n{filepath}")
            except Exception as exc:
                messagebox.showerror("Export Failed", f"Could not export canvas:\n{exc}")

    def on_click_leave(self) -> None:
        """Leaves the session and returns to the login screen."""
        if messagebox.askyesno("Leave", "Are you sure you want to leave the session?"):
            if self.net:
                self.net.send({"t": "leave"})
            self.return_to_login()

    def on_user_right_click(self, event: tk.Event) -> None:
        """Displays context menu for the host to change user role."""
        if self.my_role != "host":
            return
        item_id = self.tree_users.identify_row(event.y)
        if item_id:
            self.tree_users.selection_set(item_id)
            self.menu_user_role.post(event.x_root, event.y_root)

    def on_set_user_role(self, new_role: str) -> None:
        """Sends role modification command to the server."""
        selected = self.tree_users.selection()
        if not selected:
            return
        target_user = selected[0]
        if target_user == self.username:
            messagebox.showwarning("Role", "You cannot modify your own host role.")
            return
        if self.net:
            self.net.send({"t": "setrole", "user": target_user, "role": new_role})

    def on_kick_user(self) -> None:
        """Kicks selected participant from the room (host only)."""
        if self.my_role != "host":
            return
        selected = self.tree_users.selection()
        if not selected:
            return
        target_user = selected[0]
        if target_user == self.username:
            messagebox.showwarning("Kick", "You cannot kick yourself.")
            return
        if messagebox.askyesno("Confirm Kick", f"Are you sure you want to kick '{target_user}' from the room?"):
            if self.net:
                self.net.send({"t": "kick", "user": target_user})

    def on_toggle_present(self) -> None:
        """Toggles presentation mode (host only)."""
        if self.my_role != "host":
            return
        new_on = not self.presentation_mode
        if self.net:
            self.net.send({"t": "present", "on": new_on})

    def _update_presentation_ui(self) -> None:
        """Updates GUI presentation banner and tool states."""
        if self.presentation_mode:
            self.banner_present.pack(side=tk.TOP, fill=tk.X, before=self.canvas)
            if self.my_role == "host":
                self.btn_present.config(text="Present: ON")
            else:
                self.btn_present.config(text="Present: OFF")
        else:
            self.banner_present.pack_forget()
            self.btn_present.config(text="Present: OFF")
        self.update_role_permissions()

    def on_send_chat(self, event: Optional[tk.Event] = None) -> Optional[str]:
        """Sends chat text to server and clears entry field."""
        text = self.entry_chat.get().strip()
        if not text:
            return "break"
        chat_message: Dict[str, Any] = {"t": "chat", "text": text}
        recipient = self.chat_recipient_var.get()
        if recipient.startswith("@"):
            chat_message["to"] = recipient[1:]
        if self.net:
            self.net.send(chat_message)
        self.entry_chat.delete(0, tk.END)
        return "break"

    def update_role_permissions(self) -> None:
        """Enables/disables GUI controls based on current member role and presentation mode."""
        is_host = (self.my_role == "host")
        is_view_only = (self.my_role == "viewer") or (self.presentation_mode and not is_host)

        # Disable drawing controls if viewer or presentation mode active
        state_draw = tk.DISABLED if is_view_only else tk.NORMAL
        for btn in self.tool_buttons.values():
            btn.config(state=state_draw)
        self.slider_width.config(state=state_draw)
        self.btn_undo.config(state=state_draw)
        self.btn_redo.config(state=state_draw)

        # Host-only controls
        self.btn_present.config(state=tk.NORMAL if is_host else tk.DISABLED)
        self.btn_clear.config(state=tk.NORMAL if (is_host and not self.presentation_mode) else tk.DISABLED)
        self.btn_save_ver.config(state=tk.NORMAL if is_host else tk.DISABLED)
        self.btn_load_ver.config(state=tk.NORMAL if is_host else tk.DISABLED)

        if self.presentation_mode and not is_host:
            role_str = "Viewer (Presentation Mode)"
        elif self.my_role == "viewer":
            role_str = "Viewer (View-Only)"
        elif is_host:
            role_str = "Host"
        else:
            role_str = "Editor"
        self.lbl_status_role.config(text=f"Role: {role_str}")

    # =========================================================================
    # CANVAS DRAWING & EPHEMERAL STREAMING
    # =========================================================================

    def on_canvas_press(self, event: tk.Event) -> None:
        """Handles initial mouse click to start drawing."""
        if self.my_role == "viewer" or (self.presentation_mode and self.my_role != "host"):
            return

        x, y = round(event.x), round(event.y)

        # Text Tool Handling
        if self.current_tool == "text":
            text = simpledialog.askstring("Text Tool", "Enter text to place on canvas:", parent=self.root)
            if text and text.strip():
                sid = f"s_{self.username}_{int(time.time()*1000)}_{secrets.token_hex(3)}"
                stroke_obj = {
                    "tool": "text",
                    "color": self.current_color,
                    "width": self.current_width,
                    "pts": [[x, y]],
                    "text": text.strip()[:300],
                }
                msg = {"t": "stroke", "id": sid, "s": stroke_obj}
                self.board.add_local(stroke_obj, msg)
                self.render_stroke(sid, stroke_obj)
                if self.net:
                    self.net.send(msg)
            return

        # Sticky Note Tool Handling
        if self.current_tool == "note":
            text = simpledialog.askstring("Sticky Note", "Enter sticky note text:", parent=self.root)
            if text and text.strip():
                sid = f"s_{self.username}_{int(time.time()*1000)}_{secrets.token_hex(3)}"
                stroke_obj = {
                    "tool": "text",
                    "color": "#111111",
                    "bg": "#FFF9A6",
                    "width": 1,
                    "pts": [[x, y], [x + 160, y + 110]],
                    "text": text.strip()[:300],
                }
                msg = {"t": "stroke", "id": sid, "s": stroke_obj}
                self.board.add_local(stroke_obj, msg)
                self.render_stroke(sid, stroke_obj)
                if self.net:
                    self.net.send(msg)
            return

        self.is_drawing = True
        self.current_stroke_id = f"s_{self.username}_{int(time.time()*1000)}_{secrets.token_hex(3)}"
        self.drag_points = [[x, y]]
        self.last_part_sent_time = time.time()

    def on_canvas_drag(self, event: tk.Event) -> None:
        """Handles mouse drag, rendering locally and streaming live 'part' fragments."""
        if not self.is_drawing or self.my_role == "viewer" or (self.presentation_mode and self.my_role != "host"):
            return

        x, y = round(event.x), round(event.y)
        now = time.time()

        if self.current_tool in {"pen", "eraser"}:
            self.drag_points.append([x, y])
            # Draw incremental local segment
            if len(self.drag_points) >= 2:
                p1 = self.drag_points[-2]
                p2 = self.drag_points[-1]
                color = "#FFFFFF" if self.current_tool == "eraser" else self.current_color
                width = self.current_width * 3 if self.current_tool == "eraser" else self.current_width
                self.canvas.create_line(
                    p1[0], p1[1], p2[0], p2[1],
                    fill=color,
                    width=width,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    tags="local_drag_preview",
                )

            # Stream incremental part every ~40ms
            if now - self.last_part_sent_time >= 0.040 and self.net:
                self.last_part_sent_time = now
                self.net.send({
                    "t": "part",
                    "sid": self.current_stroke_id,
                    "tool": self.current_tool,
                    "color": "#FFFFFF" if self.current_tool == "eraser" else self.current_color,
                    "width": self.current_width * 3 if self.current_tool == "eraser" else self.current_width,
                    "mode": "append",
                    "pts": [[x, y]],
                })

        elif self.current_tool in {"line", "rect", "oval"}:
            self.canvas.delete("local_shape_preview")
            start = self.drag_points[0]
            if self.current_tool == "line":
                self.canvas.create_line(
                    start[0], start[1], x, y,
                    fill=self.current_color,
                    width=self.current_width,
                    capstyle=tk.ROUND,
                    tags="local_shape_preview",
                )
            elif self.current_tool == "rect":
                self.canvas.create_rectangle(
                    start[0], start[1], x, y,
                    outline=self.current_color,
                    width=self.current_width,
                    tags="local_shape_preview",
                )
            elif self.current_tool == "oval":
                self.canvas.create_oval(
                    start[0], start[1], x, y,
                    outline=self.current_color,
                    width=self.current_width,
                    tags="local_shape_preview",
                )

            # Stream shape preview (mode "replace") every ~40ms
            if now - self.last_part_sent_time >= 0.040 and self.net:
                self.last_part_sent_time = now
                self.net.send({
                    "t": "part",
                    "sid": self.current_stroke_id,
                    "tool": self.current_tool,
                    "color": self.current_color,
                    "width": self.current_width,
                    "mode": "replace",
                    "pts": [start, [x, y]],
                })

    def on_canvas_release(self, event: tk.Event) -> None:
        """Finishes drawing, commits stroke locally, and transmits over network."""
        if not self.is_drawing or self.my_role == "viewer":
            return

        self.is_drawing = False
        self.canvas.delete("local_drag_preview")
        self.canvas.delete("local_shape_preview")

        end_x, end_y = round(event.x), round(event.y)
        sid = self.current_stroke_id
        if not sid or not self.drag_points:
            return

        tool = self.current_tool
        color = "#FFFFFF" if tool == "eraser" else self.current_color
        width = self.current_width * 3 if tool == "eraser" else self.current_width

        if tool in {"pen", "eraser"}:
            self.drag_points.append([end_x, end_y])
            pts = list(self.drag_points)
        else:
            # Shapes keep first and last point
            pts = [self.drag_points[0], [end_x, end_y]]

        stroke_dict = {
            "tool": tool,
            "color": color,
            "width": width,
            "pts": pts,
        }
        msg = {"t": "stroke", "id": sid, "s": stroke_dict}

        # Optimistic local addition to BoardState
        self.board.add_local(stroke_dict, msg)
        self.render_stroke(sid, stroke_dict)

        # Transmit to server
        if self.net:
            self.net.send(msg)

    def on_canvas_motion(self, event: tk.Event) -> None:
        """Streams user cursor coordinates to peers (throttled to 50ms)."""
        now = time.time()
        if now - self.last_cursor_sent_time >= 0.050 and self.net:
            self.last_cursor_sent_time = now
            self.net.send({
                "t": "cursor",
                "x": round(event.x),
                "y": round(event.y),
            })

    # =========================================================================
    # CANVAS RENDERING
    # =========================================================================

    def render_stroke(self, stroke_id: str, s: Dict[str, Any]) -> None:
        """Renders a single stroke on the Tkinter canvas with appropriate tag."""
        if s.get("h", False):
            return

        tool = s.get("tool", "pen")
        color = s.get("color", "#000000")
        width = s.get("width", 2)
        pts = s.get("pts", [])
        tag = f"stroke_{stroke_id}"

        if not pts:
            return

        if tool in {"pen", "eraser"}:
            if len(pts) == 1:
                x, y = pts[0]
                r = max(1, width // 2)
                self.canvas.create_oval(
                    x - r, y - r, x + r, y + r, fill=color, outline=color, tags=tag
                )
            else:
                flat_pts = [coord for pt in pts for coord in pt]
                self.canvas.create_line(
                    flat_pts,
                    fill=color,
                    width=width,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    smooth=True,
                    tags=tag,
                )

        elif tool == "line":
            if len(pts) >= 2:
                p1, p2 = pts[0], pts[-1]
                self.canvas.create_line(
                    p1[0], p1[1], p2[0], p2[1],
                    fill=color,
                    width=width,
                    capstyle=tk.ROUND,
                    tags=tag,
                )

        elif tool == "rect":
            if len(pts) >= 2:
                p1, p2 = pts[0], pts[-1]
                self.canvas.create_rectangle(
                    p1[0], p1[1], p2[0], p2[1],
                    outline=color,
                    width=width,
                    tags=tag,
                )

        elif tool == "oval":
            if len(pts) >= 2:
                p1, p2 = pts[0], pts[-1]
                self.canvas.create_oval(
                    p1[0], p1[1], p2[0], p2[1],
                    outline=color,
                    width=width,
                    tags=tag,
                )

        elif tool == "text":
            text = s.get("text", "")
            bg = s.get("bg")
            if bg:
                # Render as Sticky Note with background box and header bar
                if len(pts) >= 2:
                    x1, y1 = pts[0]
                    x2, y2 = pts[-1]
                else:
                    x1, y1 = pts[0]
                    x2, y2 = x1 + 160, y1 + 110
                # Main note card
                self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill=bg, outline="#E0D060", width=1, tags=tag
                )
                # Header tab
                self.canvas.create_rectangle(
                    x1, y1, x2, y1 + 16, fill="#F2E680", outline="#E0D060", width=1, tags=tag
                )
                # Note body text
                self.canvas.create_text(
                    x1 + 8, y1 + 22,
                    text=text,
                    fill=color,
                    font=("Helvetica", 9),
                    width=max(80, x2 - x1 - 16),
                    anchor=tk.NW,
                    tags=tag,
                )
            else:
                p = pts[0]
                font_size = int(max(10, width * 3))
                self.canvas.create_text(
                    p[0], p[1],
                    text=text,
                    fill=color,
                    font=("Helvetica", font_size),
                    anchor=tk.NW,
                    tags=tag,
                )

    def redraw_canvas(self) -> None:
        """Clears canvas items and redraws all visible committed strokes."""
        # Delete committed strokes and drag previews, preserving cursor pointers
        self.canvas.delete("local_drag_preview")
        self.canvas.delete("local_shape_preview")
        for sid in list(self.board.strokes.keys()):
            self.canvas.delete(f"stroke_{sid}")

        for s in self.board.visible():
            sid = s.get("id", "")
            self.render_stroke(sid, s)

    def apply_board_effects(self, effects: List[Tuple[str, Any]]) -> None:
        """Processes delta visual changes emitted by BoardState."""
        for eff_type, payload in effects:
            if eff_type == "add":
                sid = payload
                stroke = self.board.strokes.get(sid)
                if stroke:
                    self.render_stroke(sid, stroke)
            elif eff_type == "hide":
                for sid in payload:
                    self.canvas.delete(f"stroke_{sid}")
            elif eff_type == "redraw":
                self.redraw_canvas()

    def render_peer_part(self, msg: Dict[str, Any]) -> None:
        """Renders live in-progress drawing preview from a remote peer."""
        user = msg.get("u", "peer")
        sid = msg.get("sid", user)
        tool = msg.get("tool", "pen")
        color = msg.get("color", "#000000")
        width = msg.get("width", 2)
        mode = msg.get("mode", "append")
        pts = msg.get("pts", [])
        tag = f"part_{user}_{sid}"

        if not pts:
            return

        if mode == "replace":
            self.canvas.delete(tag)

        if tool in {"pen", "eraser"}:
            if len(pts) >= 2:
                flat_pts = [coord for pt in pts for coord in pt]
                self.canvas.create_line(
                    flat_pts,
                    fill=color,
                    width=width,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    tags=tag,
                )
            elif len(pts) == 1:
                x, y = pts[0]
                r = max(1, width // 2)
                self.canvas.create_oval(
                    x - r, y - r, x + r, y + r, fill=color, outline=color, tags=tag
                )
        elif tool == "line" and len(pts) >= 2:
            self.canvas.create_line(
                pts[0][0], pts[0][1], pts[-1][0], pts[-1][1],
                fill=color, width=width, capstyle=tk.ROUND, tags=tag
            )
        elif tool == "rect" and len(pts) >= 2:
            self.canvas.create_rectangle(
                pts[0][0], pts[0][1], pts[-1][0], pts[-1][1],
                outline=color, width=width, tags=tag
            )
        elif tool == "oval" and len(pts) >= 2:
            self.canvas.create_oval(
                pts[0][0], pts[0][1], pts[-1][0], pts[-1][1],
                outline=color, width=width, tags=tag
            )

    def render_peer_cursor(self, msg: Dict[str, Any]) -> None:
        """Draws or updates a peer's mouse cursor dot and username badge."""
        user = msg.get("u")
        if not user or user == self.username:
            return

        x = msg.get("x")
        y = msg.get("y")
        color = msg.get("color", "#4363D8")
        if x is None or y is None:
            return

        tag = f"cursor_{user}"
        r = 4
        item_ids = self.peer_cursor_items.get(user)
        if item_ids is None:
            cursor_dot = self.canvas.create_oval(
                x - r, y - r, x + r, y + r, fill=color, outline="white", width=1, tags=tag
            )
            cursor_label = self.canvas.create_text(
                x + 8, y + 2, text=user, fill=color, font=("Helvetica", 8, "bold"), anchor=tk.W, tags=tag
            )
            self.peer_cursor_items[user] = (cursor_dot, cursor_label)
        else:
            cursor_dot, cursor_label = item_ids
            self.canvas.coords(cursor_dot, x - r, y - r, x + r, y + r)
            self.canvas.itemconfig(cursor_dot, fill=color)
            self.canvas.coords(cursor_label, x + 8, y + 2)
            self.canvas.itemconfig(cursor_label, text=user, fill=color)

        self.peer_cursor_times[user] = time.time()

    def _reap_stale_cursors(self) -> None:
        """Periodically removes peer cursors that haven't sent updates in 3 seconds."""
        now = time.time()
        for user, last_seen in list(self.peer_cursor_times.items()):
            if now - last_seen > 3.0:
                self.canvas.delete(f"cursor_{user}")
                del self.peer_cursor_times[user]
                self.peer_cursor_items.pop(user, None)
        self.root.after(1000, self._reap_stale_cursors)

    # =========================================================================
    # NETWORK EVENT PUMP (POLLING QUEUE ON GUI THREAD)
    # =========================================================================

    def _pump_network_events(self) -> None:
        """Main event polling loop scheduled via root.after(15)."""
        pending_cursors: Dict[str, Dict[str, Any]] = {}
        while True:
            try:
                ev_type, payload = self.events_queue.get_nowait()
            except queue.Empty:
                break

            if ev_type == "msg" and payload.get("t") == "cursor":
                user = payload.get("u")
                if user:
                    pending_cursors[user] = payload
                continue

            try:
                if ev_type == "conn":
                    self.lbl_status_conn.config(text="Status: Connected")
                elif ev_type == "disc":
                    reason = str(payload)
                    self.lbl_status_conn.config(text=f"Status: Reconnecting... ({reason})")
                elif ev_type == "fail":
                    reason = str(payload)
                    messagebox.showerror("Connection Error", f"Failed to connect:\n{reason}")
                    self.return_to_login(f"Connection failed: {reason}")
                elif ev_type == "msg":
                    self._dispatch_server_message(payload)
            except Exception as exc:
                print(f"[Client] Exception processing network event: {exc}", file=sys.stderr)

        for cursor_msg in pending_cursors.values():
            try:
                self.render_peer_cursor(cursor_msg)
            except Exception as exc:
                print(f"[Client] Exception processing network event: {exc}", file=sys.stderr)

        self.root.after(15, self._pump_network_events)

    def _dispatch_server_message(self, msg: Dict[str, Any]) -> None:
        """Handles framed protocol dictionaries received from the server."""
        t = msg.get("t")

        if t == "welcome":
            self._handle_welcome(msg)
        elif t == "op":
            self._handle_op(msg)
        elif t == "ack":
            self.board.ack(msg.get("id", ""))
        elif t == "part":
            self.render_peer_part(msg)
        elif t == "cursor":
            self.render_peer_cursor(msg)
        elif t == "users":
            self._handle_users_list(msg)
        elif t == "chat":
            self._handle_chat_message(msg)
        elif t == "notice":
            notice_text = str(msg.get("msg", ""))
            self.lbl_status_conn.config(text=f"Notice: {notice_text}")
            activity_text = notice_text
            if activity_text.endswith(" went offline"):
                activity_text = f"{activity_text[:-len(' went offline')]} left the room"
            self._append_activity(activity_text)
        elif t == "saved":
            filename = msg.get("file", "")
            messagebox.showinfo("Version Saved", f"Board version successfully saved:\n{filename}")
        elif t == "versions":
            self._handle_versions_list(msg)
        elif t == "present":
            self.presentation_mode = bool(msg.get("on", False))
            self._update_presentation_ui()
        elif t == "pong":
            ts = msg.get("ts")
            if ts:
                self.round_trip_latency_ms = round((time.time() - ts) * 1000, 1)
                self.lbl_status_ping.config(text=f"Latency: {self.round_trip_latency_ms} ms")
        elif t == "err":
            self._handle_server_error(msg)
        elif t in {"delta", "snapshot"}:
            self._handle_sync_reply(msg)

    def _handle_welcome(self, msg: Dict[str, Any]) -> None:
        """Processes server welcome payload, switching to main whiteboard."""
        self.room_code = str(msg.get("room", ""))
        self.lbl_login_room.config(text=f"Room Code: {self.room_code}")
        self.lbl_room_code_top.config(text=f"Room Code: {self.room_code}")
        received_token = msg.get("you", {}).get("token")
        self.session_token = received_token if isinstance(received_token, str) else None
        self._session_token_context = (
            self._connection_context if self.session_token else None
        )
        if self.session_token and self._connection_context:
            host, port, username, _ = self._connection_context
            try:
                _save_session_token(host, port, username, self.session_token)
            except (OSError, ValueError) as exc:
                messagebox.showwarning(
                    "Saved Session",
                    f"Could not save the session token for future reconnects:\n{exc}",
                    parent=self.root,
                )
        self.my_role = msg.get("you", {}).get("role", "editor")
        self.my_color = msg.get("you", {}).get("color", "#000000")
        self.select_color(self.my_color)

        seq = msg.get("seq", 0)
        mode = msg.get("mode", "full")

        if mode == "full":
            strokes = msg.get("strokes", [])
            effects = self.board.load_snapshot(seq, strokes)
            self.apply_board_effects(effects)
        elif mode == "delta":
            for op in msg.get("ops", []):
                effects, _ = self.board.apply_op(op)
                self.apply_board_effects(effects)

        # Re-transmit any pending strokes that server missed
        for unsent in self.board.unsent_pending():
            if self.net:
                self.net.send(unsent)

        # Populate users roster
        self._handle_users_list(msg)
        if not self._activity_join_logged:
            role_text = "Host" if self.my_role == "host" else "Participant"
            action = "reconnected to" if msg.get("reconnected") else "joined"
            self._append_activity(f"You {action} the room as {role_text}.")
            self._activity_join_logged = True

        # Populate chat history
        self.text_chat.config(state=tk.NORMAL)
        self.text_chat.delete("1.0", tk.END)
        for chat_item in msg.get("chat", []):
            self._append_chat_item(chat_item)
        self.text_chat.config(state=tk.DISABLED)

        # Switch GUI view from Login Screen to Whiteboard
        self.login_frame.pack_forget()
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.lbl_status_room.config(text=f"Room: {self.room_code}")
        self.lbl_status_seq.config(text=f"Seq: {self.board.seq}")
        self.presentation_mode = bool(msg.get("present", False))
        self._update_presentation_ui()

    def _handle_op(self, op: Dict[str, Any]) -> None:
        """Applies sequenced server operation and triggers gap synchronization if needed."""
        # Peer committed stroke: delete their live preview
        sid = op.get("id")
        user = op.get("u")
        if sid and user:
            self.canvas.delete(f"part_{user}_{sid}")

        effects, need_sync = self.board.apply_op(op)
        self.apply_board_effects(effects)
        self.lbl_status_seq.config(text=f"Seq: {self.board.seq}")

        # Gap detection: rate-limit sync requests to 1 per second
        now = time.time()
        if need_sync and (now - self.last_sync_time >= 1.0) and self.net:
            self.last_sync_time = now
            self.net.send({"t": "sync", "last_seq": self.board.seq})

    def _handle_sync_reply(self, msg: Dict[str, Any]) -> None:
        """Handles delta ops or snapshot returned from a sync request."""
        t = msg.get("t")
        seq = msg.get("seq", 0)

        if t == "delta":
            for op in msg.get("ops", []):
                effects, _ = self.board.apply_op(op)
                self.apply_board_effects(effects)
        elif t == "snapshot":
            strokes = msg.get("strokes", [])
            effects = self.board.load_snapshot(seq, strokes)
            self.apply_board_effects(effects)

        self.lbl_status_seq.config(text=f"Seq: {self.board.seq}")

    def _handle_users_list(self, msg: Dict[str, Any]) -> None:
        """Updates the participants treeview."""
        users = msg.get("users", [])
        active_users = [user for user in users if user.get("online", True)]
        self.tree_users.delete(*self.tree_users.get_children())
        self.lbl_active_users.config(text=f"Active Users ({len(active_users)})")

        for u in active_users:
            uname = u.get("user", "")
            role = u.get("role", "editor")
            role_text = (
                "Host"
                if role == "host"
                else "Viewer"
                if role == "viewer"
                else "Participant"
            )
            display_name = f"{uname} (you)" if uname == self.username else uname

            self.tree_users.insert(
                "", tk.END, iid=uname, text=display_name, values=(role_text,)
            )

            # If our own role changed, update permissions
            if uname == self.username and role != self.my_role:
                self.my_role = role
                self.update_role_permissions()

        recipients = ["Everyone"] + [
            f"@{user.get('user', '')}"
            for user in active_users
            if user.get("user") and user.get("user") != self.username
        ]
        self.chat_recipient_combo.configure(values=recipients)
        if self.chat_recipient_var.get() not in recipients:
            self.chat_recipient_var.set("Everyone")

    def _append_activity(self, message: str) -> None:
        """Adds a join, leave, or role event to the bounded activity log."""
        self.text_activity.config(state=tk.NORMAL)
        timestamp = time.strftime("%H:%M:%S")
        self.text_activity.insert(tk.END, f"[{timestamp}] {message}\n")
        line_count = int(self.text_activity.index("end-1c").split(".")[0])
        if line_count > 51:
            self.text_activity.delete("1.0", f"{line_count - 51}.0")
        self.text_activity.config(state=tk.DISABLED)
        self.text_activity.see(tk.END)

    def _handle_chat_message(self, msg: Dict[str, Any]) -> None:
        """Appends incoming chat message to display widget."""
        self.text_chat.config(state=tk.NORMAL)
        self._append_chat_item(msg)
        self.text_chat.config(state=tk.DISABLED)

    def _append_chat_item(self, chat_item: Dict[str, Any]) -> None:
        """Formats and inserts a single chat item with timestamp and author color."""
        ts = chat_item.get("ts", time.time())
        t_str = time.strftime("%H:%M:%S", time.localtime(ts))
        user = chat_item.get("user", chat_item.get("u", "User"))
        text = chat_item.get("text", "")
        color = chat_item.get("color", "#2B6CB0")
        recipient = chat_item.get("to")

        # Dynamic user tag with their allocated palette color
        user_tag = f"user_{user}"
        self.text_chat.tag_configure(user_tag, foreground=color, font=("Helvetica", 9, "bold"))

        self.text_chat.insert(tk.END, f"[{t_str}] ", "time")
        message_author = f"{user} [private to {recipient}]" if recipient else user
        self.text_chat.insert(tk.END, f"{message_author}: ", user_tag)
        self.text_chat.insert(tk.END, f"{text}\n", "msg")
        self.text_chat.see(tk.END)

    def _handle_versions_list(self, msg: Dict[str, Any]) -> None:
        """Presents a version selection modal dialog to the host for restoration."""
        files = msg.get("files", [])
        if not files:
            messagebox.showinfo("Versions", "No saved versions found for this room.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Restore Board Version")
        dialog.geometry("450x320")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="Select a version snapshot to restore:").pack(
            anchor=tk.W, padx=12, pady=(12, 4)
        )

        listbox = tk.Listbox(dialog)
        listbox.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        for f in files:
            listbox.insert(tk.END, f)

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill=tk.X, padx=12, pady=10)

        def on_restore_selected():
            sel = listbox.curselection()
            if sel:
                chosen_file = listbox.get(sel[0])
                if messagebox.askyesno("Confirm Restore", f"Restore canvas from version:\n{chosen_file}?"):
                    if self.net:
                        self.net.send({"t": "load", "file": chosen_file})
                    dialog.destroy()

        ttk.Button(btn_frame, text="Restore Selected", command=on_restore_selected).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

    def _handle_server_error(self, msg: Dict[str, Any]) -> None:
        """Handles server error codes (fatal and non-fatal)."""
        code = msg.get("code", "unknown_error")
        err_msg = msg.get("msg", code)
        fatal = bool(msg.get("fatal", False))

        error_map = {
            "room_exists": "Room already exists. Enter the configured room code to join.",
            "no_room": "Room not found. Check the room code configured on the server.",
            "bad_password": "Incorrect room password. Please try again.",
            "bad_host_code": "Incorrect host code. Only the host can use this code.",
            "chat_recipient_unavailable": "That participant is no longer active.",
            "chat_self_message": "You cannot send a private message to yourself.",
            "name_taken": "Username is already taken by another participant.",
            "room_full": "The room has reached maximum capacity (30 members).",
            "readonly": "Action denied: Viewers cannot draw or edit.",
            "denied": "Action denied: Only the room host can perform this operation.",
            "kicked": "You were kicked from the room by the host.",
        }
        user_facing_msg = error_map.get(code, err_msg)

        if fatal:
            messagebox.showerror("Join Failed", user_facing_msg)
            self.return_to_login(user_facing_msg)
        else:
            messagebox.showwarning("Notice", user_facing_msg)

    def on_window_close(self) -> None:
        """Gracefully disconnects network threads and closes application window."""
        if self.net:
            try:
                self.net.send({"t": "leave"})
            except Exception:
                pass
            self.net.stop()
        self.root.destroy()


def main() -> None:
    """CLI entry point for the Tkinter Collaborative Whiteboard Client."""
    parser = argparse.ArgumentParser(description="LAN Collaborative Whiteboard Client")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Server IP address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=PORT_DEFAULT, help=f"Server port (default: {PORT_DEFAULT})"
    )
    args = parser.parse_args()

    root = tk.Tk()
    app = WhiteboardApp(root, default_host=args.host, default_port=args.port)
    root.mainloop()


if __name__ == "__main__":
    main()

