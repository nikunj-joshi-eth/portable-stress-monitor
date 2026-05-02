"""
Stress Monitor - Python Server
================================
Reads JSON from Pico over Serial, broadcasts to:
  1. Local dashboard via WebSocket (localhost:5000)
  2. Public MQTT broker (HiveMQ) → viewable on GitHub Pages

SETUP:
  pip install flask flask-socketio pyserial eventlet paho-mqtt

RUN:
  python server.py

Local dashboard : http://localhost:5000
Public dashboard: https://YOUR_USERNAME.github.io/YOUR_REPO
"""

import serial
import json
import threading
import time
import csv
import os
from datetime import datetime
from flask import Flask, send_from_directory, Response, jsonify
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt

# ═════════════════════════════════════════════════════
#  CONFIG — change these
# ═════════════════════════════════════════════════════
SERIAL_PORT  = "COM7"           # Your Pico's COM port
BAUD_RATE    = 115200
SESSIONS_DIR = "sessions"

# MQTT — HiveMQ free public broker (no account needed)
MQTT_BROKER  = "broker.hivemq.com"
MQTT_PORT    = 1883
# ⚠ Make this unique — e.g. "stressmonitor/harsh_abc123"
# Anyone who knows this topic can read your data
MQTT_TOPIC   = "stressmonitor/harsh_unique123"

# ═════════════════════════════════════════════════════
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = Flask(__name__, static_folder=".")
app.config["SECRET_KEY"] = "stressmonitor"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

latest_data = {
    "bpm": 0, "stress": "NO DATA",
    "temp": 0.0, "hum": 0,
    "ecg": 0.0, "connected": False
}

# ═════════════════════════════════════════════════════
#  MQTT CLIENT SETUP
# ═════════════════════════════════════════════════════
mqtt_client   = mqtt.Client(client_id="stress_monitor_server", protocol=mqtt.MQTTv5)
mqtt_connected = False

def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print(f"[MQTT] Connected to {MQTT_BROKER}")
        print(f"[MQTT] Publishing to topic: {MQTT_TOPIC}")
    else:
        mqtt_connected = False
        print(f"[MQTT] Connection failed, code: {rc}")

def on_mqtt_disconnect(client, userdata, rc, properties=None):
    global mqtt_connected
    mqtt_connected = False
    print(f"[MQTT] Disconnected (code {rc}) — will retry...")

mqtt_client.on_connect    = on_mqtt_connect
mqtt_client.on_disconnect = on_mqtt_disconnect

def mqtt_connect_loop():
    """Keep trying to connect to MQTT broker in background."""
    while True:
        try:
            print(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
            mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            mqtt_client.loop_forever()   # Blocking — handles reconnects
        except Exception as e:
            print(f"[MQTT] Error: {e} — retrying in 5s")
            time.sleep(5)

def publish_mqtt(data):
    """Publish sensor data to MQTT broker."""
    if not mqtt_connected:
        return
    try:
        payload = json.dumps({
            "bpm":       data.get("bpm", 0),
            "stress":    data.get("stress", "NO DATA"),
            "temp":      data.get("temp", 0.0),
            "hum":       data.get("hum", 0),
            "ecg":       data.get("ecg", 0.0),
            "connected": True,
            "ts":        int(time.time() * 1000)  # timestamp in ms
        })
        mqtt_client.publish(MQTT_TOPIC, payload, qos=0, retain=True)
    except Exception as e:
        print(f"[MQTT] Publish error: {e}")

# ═════════════════════════════════════════════════════
#  SESSION LOGGING
# ═════════════════════════════════════════════════════
_session_file   = None
_session_writer = None
_session_path   = None
_session_rows   = 0
_session_start  = None

def _start_session():
    global _session_file, _session_writer, _session_path, _session_rows, _session_start
    _session_start = datetime.now()
    fname = _session_start.strftime("session_%Y%m%d_%H%M%S.csv")
    _session_path = os.path.join(SESSIONS_DIR, fname)
    _session_file = open(_session_path, 'w', newline='')
    _session_writer = csv.writer(_session_file)
    _session_writer.writerow(["timestamp","elapsed_s","bpm","stress","temp_c","humidity_pct","ecg"])
    _session_file.flush()
    _session_rows = 0
    print(f"[Logger] New session: {_session_path}")

def _log_row(data):
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
    _session_file.flush()
    _session_rows += 1

def _end_session():
    global _session_file, _session_writer
    if _session_file:
        _session_file.close()
        _session_file   = None
        _session_writer = None
        print(f"[Logger] Session saved: {_session_rows} rows → {_session_path}")

# ═════════════════════════════════════════════════════
#  FLASK ROUTES
# ═════════════════════════════════════════════════════
@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/download/current")
def download_current():
    if not _session_path or not os.path.exists(_session_path):
        return "No active session", 404
    with open(_session_path, 'r') as f:
        content = f.read()
    fname = os.path.basename(_session_path)
    return Response(content, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"})

@app.route("/download/<filename>")
def download_session(filename):
    safe = os.path.basename(filename)
    path = os.path.join(SESSIONS_DIR, safe)
    if not os.path.exists(path):
        return "Session not found", 404
    with open(path, 'r') as f:
        content = f.read()
    return Response(content, mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={safe}"})

@app.route("/sessions")
def list_sessions():
    files = []
    for fname in sorted(os.listdir(SESSIONS_DIR), reverse=True):
        if not fname.endswith('.csv'):
            continue
        path = os.path.join(SESSIONS_DIR, fname)
        size = os.path.getsize(path)
        with open(path, 'r') as f:
            rows = sum(1 for _ in f) - 1
        try:
            dt_str = fname.replace("session_","").replace(".csv","")
            dt = datetime.strptime(dt_str, "%Y%m%d_%H%M%S")
            display = dt.strftime("%d %b %Y  %H:%M:%S")
        except Exception:
            display = fname
        files.append({
            "filename": fname, "display": display,
            "rows": rows, "size_kb": round(size/1024,1),
            "current": fname == os.path.basename(_session_path) if _session_path else False
        })
    return jsonify(files)

@app.route("/mqtt-config")
def mqtt_config():
    """Expose MQTT config so local dashboard can also read it."""
    return jsonify({
        "broker": MQTT_BROKER,
        "port":   8884,          # WebSocket port (for browser MQTT)
        "topic":  MQTT_TOPIC,
        "connected": mqtt_connected
    })

# ═════════════════════════════════════════════════════
#  SERIAL READER
# ═════════════════════════════════════════════════════
def read_serial():
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

                        # 1. Log to CSV
                        _log_row(latest_data)

                        # 2. Emit to local dashboard (WebSocket)
                        socketio.emit("sensor_data", {
                            **latest_data,
                            "session_rows": _session_rows,
                            "session_file": os.path.basename(_session_path) if _session_path else None
                        })

                        # 3. Publish to MQTT → GitHub Pages
                        publish_mqtt(latest_data)

                    except json.JSONDecodeError:
                        pass

        except serial.SerialException as e:
            print(f"[Server] Serial error: {e}")
            latest_data["connected"] = False
            socketio.emit("sensor_data", latest_data)
            # Publish offline status to MQTT
            try:
                mqtt_client.publish(MQTT_TOPIC,
                    json.dumps({"connected": False, "bpm": 0, "stress": "NO DATA"}),
                    qos=0, retain=True)
            except Exception:
                pass
            _end_session()
            time.sleep(3)
            _start_session()

        except Exception as e:
            print(f"[Server] Unexpected error: {e}")
            time.sleep(3)

# ═════════════════════════════════════════════════════
#  SOCKET.IO EVENTS
# ═════════════════════════════════════════════════════
@socketio.on("connect")
def on_connect():
    print("[Server] Browser client connected")
    socketio.emit("sensor_data", latest_data)

@socketio.on("disconnect")
def on_disconnect():
    print("[Server] Browser client disconnected")

# ═════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════
if __name__ == "__main__":
    # Start MQTT in background thread
    mqtt_thread = threading.Thread(target=mqtt_connect_loop, daemon=True)
    mqtt_thread.start()

    # Start serial reader in background thread
    serial_thread = threading.Thread(target=read_serial, daemon=True)
    serial_thread.start()

    print("[Server] Local dashboard  → http://localhost:5000")
    print(f"[Server] MQTT topic       → {MQTT_TOPIC}")
    print(f"[Server] MQTT broker      → {MQTT_BROKER}")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
