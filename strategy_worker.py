#!/usr/bin/env python3
"""Strategy subprocess worker for the referee protocol.

This script runs inside each strategy subprocess. It:
  1. Loads the strategy module.
  2. Enters a JSON-line protocol loop on stdin/stdout.
  3. Handles begin, play, result, and end commands.

It is spawned by the referee (referee.py) — never run directly.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import traceback
from pathlib import Path

# Ensure project root is on sys.path
_project_root = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from strategy import Strategy, GameConfig


def _load_strategy(source: str, cls_name: str) -> Strategy:
    """Load and instantiate a Strategy class."""
    if source == "__builtin__":
        from strategies import _discover_builtin
        for cls in _discover_builtin():
            if cls.__name__ == cls_name:
                return cls()
        raise RuntimeError(f"Built-in strategy class {cls_name} not found")
    else:
        spec = importlib.util.spec_from_file_location(f"_worker_{cls_name}", source)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {source}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if (isinstance(obj, type) and issubclass(obj, Strategy)
                    and obj is not Strategy and obj.__name__ == cls_name):
                return obj()
        raise RuntimeError(f"Class {cls_name} not found in {source}")


def _send(msg: dict) -> None:
    """Write a JSON line to stdout."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _recv() -> dict:
    """Read a JSON line from stdin."""
    line = sys.stdin.readline()
    if not line:
        raise EOFError("stdin closed")
    return json.loads(line)


def main() -> None:
    """Main protocol loop."""
    # First message must be the strategy loading info
    init = _recv()
    source = init["source"]
    cls_name = init["cls_name"]

    try:
        strat = _load_strategy(source, cls_name)
        _send({"status": "ready", "name": strat.name})
    except Exception as e:
        _send({"status": "error", "error": str(e)})
        sys.exit(1)

    # Protocol loop
    while True:
        try:
            msg = _recv()
        except (EOFError, json.JSONDecodeError):
            break

        cmd = msg.get("cmd")

        if cmd == "begin":
            config = GameConfig(
                board_size=msg["config"]["board_size"],
                variant=msg["config"]["variant"],
                initial_board=tuple(tuple(row) for row in msg["config"]["initial_board"]),
                player=msg["config"]["player"],
                opponent=msg["config"]["opponent"],
                time_limit=msg["config"]["time_limit"],
            )
            try:
                strat.begin_game(config)
                _send({"status": "ok"})
            except Exception as e:
                _send({"status": "error", "error": str(e)})

        elif cmd == "play":
            board = tuple(tuple(row) for row in msg["board"])
            last_move = tuple(msg["last_move"]) if msg.get("last_move") is not None else None
            try:
                move = strat.play(board, last_move)
                _send({"move": [int(move[0]), int(move[1])]})
            except Exception as e:
                _send({"error": str(e), "traceback": traceback.format_exc()})

        elif cmd == "result":
            move = tuple(msg["move"])
            success = msg["success"]
            try:
                strat.on_move_result(move, success)
            except Exception:
                pass  # Non-critical

        elif cmd == "end":
            board = tuple(tuple(row) for row in msg["board"])
            winner = msg["winner"]
            your_player = msg["your_player"]
            try:
                strat.end_game(board, winner, your_player)
            except Exception:
                pass  # Non-critical
            break

        else:
            break


if __name__ == "__main__":
    main()
