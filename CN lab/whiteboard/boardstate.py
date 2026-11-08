"""Client-side canvas replica and drawing state model (pure data, zero GUI code).

Computer Networks Lab - LAN Collaborative Whiteboard
Module: whiteboard.boardstate

Role & Architecture:
--------------------
In a distributed event-driven collaborative application, the Model-View-Controller
(MVC) pattern requires a strict decoupling of network state management from the
graphical user interface.

`boardstate.py` implements `BoardState`, the pure data Model:
1. Canonical Local Replica:
   Maintains the client's local mirror of the whiteboard canvas without any GUI
   dependencies (no Tkinter, no widgets, no display code).
2. Optimistic Local Echo:
   When the local user draws a stroke, `add_local()` renders it immediately with a
   pending flag (`"p": True`) and saves the message in `pending`. The GUI does not
   freeze or wait for a round-trip network acknowledgment.
3. Authoritative Sequential Reconciliation:
   Consumes sequenced `op` events from the server:
   - Duplicate ops (`seq <= self.seq`): safely ignored (idempotent).
   - In-order ops (`seq == self.seq + 1`): applied immediately, then drains any
     contiguous out-of-order successors from `buffer`.
   - Gap detection (`seq > self.seq + 1`): stored in `buffer` and flags `need_sync=True`.
4. Effect Emission:
   `apply_op()` returns a list of UI delta actions (e.g. `[("add", sid)]`,
   `[("hide", sids)]`, or `[("redraw", None)]`) so the view layer redraws only
   what actually changed.
5. Fingerprinting:
   Provides a cryptographic hash of all visible strokes and drawing order to
   verify state convergence across distributed replicas in automated tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Set, Tuple

# Support running directly or as a module
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from whiteboard.protocol import CANVAS_H, CANVAS_W
except ImportError:
    from protocol import CANVAS_H, CANVAS_W  # type: ignore


class BoardState:
    """The client's replica of the canvas state and drawing operations."""

    def __init__(self, width: int = CANVAS_W, height: int = CANVAS_H) -> None:
        self.width: int = width
        self.height: int = height

        # Authoritative sequence tracking
        self.seq: int = 0

        # Committed & optimistic strokes: id -> stroke dict (OrderedDict preserves z-order)
        self.strokes: OrderedDict[str, Dict[str, Any]] = OrderedDict()

        # Out-of-order operation buffer: seq -> op dict
        self.buffer: Dict[int, Dict[str, Any]] = {}

        # Local unacknowledged strokes awaiting server confirmation: id -> original msg
        self.pending: Dict[str, Dict[str, Any]] = {}

    def load_snapshot(
        self, seq: int, strokes: List[Dict[str, Any]]
    ) -> List[Tuple[str, Any]]:
        """Replaces the entire local state with an authoritative server snapshot.

        Drops pending entries that the server already committed and clears the
        out-of-order buffer.

        Args:
            seq: The sequence number of the snapshot.
            strokes: Full list of committed stroke dictionaries from server.

        Returns:
            list: Effects list `[("redraw", None)]` directing the GUI to repaint.
        """
        self.seq = seq
        self.strokes.clear()
        self.buffer.clear()

        for s in strokes:
            sid = s.get("id", "")
            stroke_copy = dict(s)
            stroke_copy.setdefault("h", False)
            self.strokes[sid] = stroke_copy
            # Drop from pending if server already has it
            self.pending.pop(sid, None)

        return [("redraw", None)]

    def unsent_pending(self) -> List[Dict[str, Any]]:
        """Returns pending stroke messages not yet acknowledged by the server.

        Used upon reconnecting to re-transmit strokes that may have been lost
        during a network interruption.

        Returns:
            list of dict: Outgoing stroke messages to re-send.
        """
        return list(self.pending.values())

    def add_local(
        self, stroke: Dict[str, Any], msg: Dict[str, Any]
    ) -> None:
        """Optimistically adds a locally drawn stroke before server confirmation.

        Marks the stroke with `"p": True` and records the outbound message in
        `self.pending`.

        Args:
            stroke: Stroke definition dictionary (must have 'id').
            msg: The complete network message dictionary to transmit.
        """
        sid = stroke.get("id") or msg.get("id")
        if not sid:
            return

        stroke_copy = dict(stroke)
        stroke_copy["p"] = True
        stroke_copy.setdefault("h", False)
        stroke_copy.setdefault("id", sid)

        self.strokes[sid] = stroke_copy
        self.pending[sid] = msg

    def ack(self, stroke_id: str) -> None:
        """Acknowledges a local stroke, clearing its pending status."""
        self.pending.pop(stroke_id, None)
        if stroke_id in self.strokes:
            self.strokes[stroke_id].pop("p", None)

    def apply_op(
        self, op: Dict[str, Any]
    ) -> Tuple[List[Tuple[str, Any]], bool]:
        """Applies an authoritative sequenced operation from the server.

        Handles duplicates, out-of-order buffering, gap detection, and draining.

        Args:
            op: Operation dictionary with at least 'seq', 'k' (kind), and payload fields.

        Returns:
            tuple: (effects, need_sync)
                   - effects: list of tuples such as [("add", id)], [("hide", [ids])], [("redraw", None)]
                   - need_sync: bool, True if a sequence gap was detected requiring resync
        """
        op_seq = op.get("seq", 0)

        # 1. Duplicate / already applied -> ignore
        if op_seq <= self.seq:
            return ([], False)

        # 2. Sequence gap detected -> buffer op and signal resync requirement
        if op_seq > self.seq + 1:
            self.buffer[op_seq] = op
            return ([], True)

        # 3. Exactly next in-order op -> apply and drain consecutive buffered successors
        effects: List[Tuple[str, Any]] = []
        need_redraw = self._apply_single_op(op, effects)

        self.seq = op_seq

        # Drain buffered ops that are now contiguous
        while (self.seq + 1) in self.buffer:
            next_op = self.buffer.pop(self.seq + 1)
            sub_redraw = self._apply_single_op(next_op, effects)
            if sub_redraw:
                need_redraw = True
            self.seq += 1

        if need_redraw:
            # Consolidate to a single redraw effect if any operation required full repaint
            effects = [("redraw", None)]

        return (effects, False)

    def _apply_single_op(
        self, op: Dict[str, Any], effects: List[Tuple[str, Any]]
    ) -> bool:
        """Internal helper to apply a single in-order op.

        Returns:
            bool: True if this op requires a full canvas redraw, False otherwise.
        """
        k = op.get("k")
        need_redraw = False

        if k == "stroke":
            sid = op.get("id", "")
            stroke_dict = dict(op.get("s", {}))
            stroke_dict.setdefault("h", False)
            stroke_dict.setdefault("id", sid)
            stroke_dict.setdefault("u", op.get("u", ""))

            if sid in self.strokes:
                # This was our own optimistically echoed stroke
                self.pending.pop(sid, None)
                stroke_dict.pop("p", None)

                # Check if server assigned an ordering different from our local optimistic order
                current_keys = list(self.strokes.keys())
                if current_keys and current_keys[-1] == sid:
                    # Already at the tail; local draw order matches server order
                    self.strokes[sid] = stroke_dict
                    effects.append(("add", sid))
                else:
                    # Reorder stroke to reflect authoritative server sequence
                    self.strokes[sid] = stroke_dict
                    self.strokes.move_to_end(sid)
                    need_redraw = True
            else:
                # Stroke from a peer
                self.strokes[sid] = stroke_dict
                effects.append(("add", sid))

        elif k == "vis":
            hide_ids = op.get("hide", [])
            show_ids = op.get("show", [])

            for hid in hide_ids:
                if hid in self.strokes:
                    self.strokes[hid]["h"] = True

            for sid in show_ids:
                if sid in self.strokes:
                    self.strokes[sid]["h"] = False

            if show_ids:
                # Showing previously hidden strokes requires rebuilding z-order
                need_redraw = True
            elif hide_ids:
                effects.append(("hide", list(hide_ids)))

        elif k == "reset":
            if "strokes" in op:
                # Restore version
                self.strokes = OrderedDict(
                    (s.get("id", f"s_{idx}"), dict(s))
                    for idx, s in enumerate(op["strokes"])
                )
            else:
                # Full clear
                self.strokes.clear()
            self.pending.clear()
            need_redraw = True

        return need_redraw

    def visible(self) -> List[Dict[str, Any]]:
        """Returns all non-hidden strokes in ascending draw order."""
        return [s for s in self.strokes.values() if not s.get("h", False)]

    def fingerprint(self) -> str:
        """Returns a deterministic cryptographic SHA-256 hash of the canvas state.

        Used by integration tests to mathematically verify that independent
        client replicas have converged to the identical visual state.
        """
        canonical_items = [
            (
                sid,
                s.get("tool"),
                s.get("color"),
                s.get("bg"),
                s.get("width"),
                s.get("pts"),
                s.get("text"),
                s.get("h", False),
            )
            for sid, s in self.strokes.items()
            if not s.get("h", False)
        ]
        serialized = json.dumps(canonical_items, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
