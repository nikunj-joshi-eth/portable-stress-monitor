"""
Stress Monitor - Python Server
================================
Reads JSON from Pico over Serial and broadcasts to the web dashboard via WebSocket.
Also logs every session to a CSV file in the sessions/ folder.

SETUP:
  pip install flask flask-socketio pyserial

RUN:
  python server.py

Then open your browser at: http://localhost:5000
Make sure to set the correct COM port below.
"""

import serial
import json
import threading
import time
import csv
import os
from datetime import datetime
from flask import Flask, render_template, send_from_directory, Response, jsonify
from flask_socketio import SocketIO

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
SERIAL_PORT  = "COM8"       # Windows: "COM3" etc. Mac/Linux: "/dev/ttyACM0"
BAUD_RATE    = 115200
SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")  # Folder where CSV session logs are saved

# ─────────────────────────────────────────
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=".")
app.config["SECRET_KEY"] = "stressmonitor"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

latest_data = {
    "bpm": 0, "stress": "NO DATA",
    "temp": 0.0, "hum": 0,
    "ecg": 0.0, "connected": False
}

# ── Session log state ─────────────────────────────────
_session_file    = None     # Current open CSV file handle
_session_writer  = None     # csv.writer for current session
_session_path    = None     # Path of current session file
_session_rows    = 0        # Rows written this session
_session_start   = None     # datetime of session start

def _start_session():
    """Open a new timestamped CSV file for this session."""
    global _session_file, _session_writer, _session_path, _session_rows, _session_start
    _session_start = datetime.now()
    fname = _session_start.strftime("session_%Y%m%d_%H%M%S.csv")
    _session_path = os.path.join(SESSIONS_DIR, fname)
    _session_file = open(_session_path, 'w', newline='')
    _session_writer = csv.writer(_session_file)
    _session_writer.writerow(["timestamp", "elapsed_s", "bpm", "stress", "temp_c", "humidity_pct", "ecg"])
    _session_file.flush()
    _session_rows = 0
    print(f"[Logger] New session: {_session_path}")

def _log_row(data):
    """Append one row to the current session CSV."""
    global _session_rows
    if _session_writer is None:
        return
    elapsed = (datetime.now() - _session_start).total_seconds()
    _session_writer.writerow([
        datetime.now().strftime("%H:%M:%S"),
        round(elapsed, 1),
        data.get("bpm", 0),
        data.get("stress", "NO DATA"),
        data.get("temp", 0.0),
        data.get("hum", 0),
        round(data.get("ecg", 0.0), 3),
    ])
    _session_file.flush()   # Ensure data is written even if server crashes
    _session_rows += 1

def _end_session():
    """Close the current session file."""
    global _session_file, _session_writer
    if _session_file:
        _session_file.close()
        _session_file   = None
        _session_writer = None
        print(f"[Logger] Session saved: {_session_rows} rows → {_session_path}")

# ─────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/download/current")
def download_current():
    """Download the current live session CSV."""
    if not _session_path or not os.path.exists(_session_path):
        return "No active session", 404
    with open(_session_path, 'r') as f:
        content = f.read()
    fname = os.path.basename(_session_path)
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )

@app.route("/download/<filename>")
def download_session(filename):
    """Download a specific past session CSV by filename."""
    safe = os.path.basename(filename)   # Prevent path traversal
    path = os.path.join(SESSIONS_DIR, safe)
    if not os.path.exists(path):
        return "Session not found", 404
    with open(path, 'r') as f:
        content = f.read()
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe}"}
    )

@app.route("/sessions")
def list_sessions():
    """Return JSON list of all saved session files with metadata."""
    files = []
    for fname in sorted(os.listdir(SESSIONS_DIR), reverse=True):
        if not fname.endswith('.csv'):
            continue
        path = os.path.join(SESSIONS_DIR, fname)
        size = os.path.getsize(path)
        # Count data rows (subtract header)
        with open(path, 'r') as f:
            rows = sum(1 for _ in f) - 1
        # Parse datetime from filename: session_YYYYMMDD_HHMMSS.csv
        try:
            dt_str = fname.replace("session_", "").replace(".csv", "")
            dt = datetime.strptime(dt_str, "%Y%m%d_%H%M%S")
            display = dt.strftime("%d %b %Y  %H:%M:%S")
        except Exception:
            display = fname
        files.append({
            "filename": fname,
            "display":  display,
            "rows":     rows,
            "size_kb":  round(size / 1024, 1),
            "current":  fname == os.path.basename(_session_path) if _session_path else False
        })
    return jsonify(files)

@app.route("/session/stats")
def session_stats():
    """Return live stats for the current session."""
    return jsonify({
        "rows":    _session_rows,
        "active":  _session_file is not None,
        "file":    os.path.basename(_session_path) if _session_path else None,
        "started": _session_start.strftime("%H:%M:%S") if _session_start else None,
    })

# ─────────────────────────────────────────
def read_serial():
    """Background thread: reads Pico serial, parses JSON, emits to clients."""
    global latest_data
    _start_session()

    while True:
        try:
            print(f"[Server] Connecting to {SERIAL_PORT} at {BAUD_RATE} baud...")
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
            time.sleep(2)
            print(f"[Server] Connected!")
            latest_data["connected"] = True

            while True:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        latest_data.update(data)
                        latest_data["connected"] = True
                        # Log row to CSV
                        _log_row(latest_data)
                        # Emit to dashboard
                        socketio.emit("sensor_data", {
                            **latest_data,
                            "session_rows": _session_rows,
                            "session_file": os.path.basename(_session_path) if _session_path else None
                        })
                    except json.JSONDecodeError:
                        pass

        except serial.SerialException as e:
            print(f"[Server] Serial error: {e}")
            latest_data["connected"] = False
            socketio.emit("sensor_data", latest_data)
            _end_session()
            time.sleep(3)
            _start_session()

        except Exception as e:
            print(f"[Server] Unexpected error: {e}")
            time.sleep(3)

# ─────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    print("[Server] Browser client connected")
    socketio.emit("sensor_data", latest_data)

@socketio.on("disconnect")
def on_disconnect():
    print("[Server] Browser client disconnected")

# ─────────────────────────────────────────
if __name__ == "__main__":
    serial_thread = threading.Thread(target=read_serial, daemon=True)
    serial_thread.start()
    print("[Server] Dashboard running at http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
