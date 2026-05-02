"""
Stress Monitor - Python Server
================================
Reads JSON from Arduino over Serial and broadcasts to the web dashboard via WebSocket.

SETUP:
  pip install flask flask-socketio pyserial

RUN:
  python server.py

Then open your browser at: http://localhost:5000
Make sure to set the correct COM port below (check Arduino IDE → Tools → Port)
"""

import serial
import json
import threading
import time
from flask import Flask, render_template, send_from_directory
from flask_socketio import SocketIO
import os

# ─────────────────────────────────────────
#  CONFIG — change COM port to match yours
# ─────────────────────────────────────────
SERIAL_PORT = "COM8"       # Windows: "COM3", "COM4" etc.
                            # Mac/Linux: "/dev/ttyUSB0" or "/dev/ttyACM0"
BAUD_RATE   = 115200

# ─────────────────────────────────────────
app = Flask(__name__, static_folder=".")
app.config["SECRET_KEY"] = "stressmonitor"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Latest data snapshot (thread-safe enough for this use case)
latest_data = {
    "bpm": 0,
    "stress": "NO DATA",
    "temp": 0.0,
    "hum": 0,
    "ecg": 0.0,
    "connected": False
}

# ─────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

# ─────────────────────────────────────────
def read_serial():
    """Background thread: reads Arduino serial, parses JSON, emits to clients."""
    global latest_data

    while True:
        try:
            print(f"[Server] Connecting to {SERIAL_PORT} at {BAUD_RATE} baud...")
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
            time.sleep(2)  # Wait for Arduino to reset
            print(f"[Server] Connected! Listening for data...")
            latest_data["connected"] = True

            while True:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                # Only process lines that look like JSON
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        latest_data.update(data)
                        latest_data["connected"] = True
                        socketio.emit("sensor_data", latest_data)
                    except json.JSONDecodeError:
                        pass  # Skip malformed lines

        except serial.SerialException as e:
            print(f"[Server] Serial error: {e}")
            latest_data["connected"] = False
            socketio.emit("sensor_data", latest_data)
            time.sleep(3)  # Retry after 3 seconds

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
    # Start serial reading in background thread
    serial_thread = threading.Thread(target=read_serial, daemon=True)
    serial_thread.start()

    print("[Server] Dashboard running at http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)

