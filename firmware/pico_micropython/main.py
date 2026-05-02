"""
╔══════════════════════════════════════════════════════╗
║   STRESS MONITOR — Raspberry Pi Pico (MicroPython)  ║
║   By Nikunj                                          ║
╠══════════════════════════════════════════════════════╣
║  WIRING GUIDE                                        ║
║                                                      ║
║  I2C Bus (GP4 / GP5) — shared by OLED + MAX30102    ║
║  ┌──────────┬───────────┬──────────────────────┐    ║
║  │ Sensor   │ Pico Pin  │ Notes                │    ║
║  ├──────────┼───────────┼──────────────────────┤    ║
║  │ SSD1306  │ SDA → GP4 │ 3.3V, GND            │    ║
║  │ OLED     │ SCL → GP5 │ addr 0x3C            │    ║
║  ├──────────┼───────────┼──────────────────────┤    ║
║  │ MAX30102 │ SDA → GP4 │ 3.3V, GND            │    ║
║  │ HR sensor│ SCL → GP5 │ addr 0x57            │    ║
║  ├──────────┼───────────┼──────────────────────┤    ║
║  │ DHT11    │ DAT → GP15│ 3.3V, GND            │    ║
║  │ Temp/Hum │           │ 10kΩ pull-up to 3.3V │    ║
║  ├──────────┼───────────┼──────────────────────┤    ║
║  │ Red LED  │ GP14      │ 220Ω to GND          │    ║
║  │ Blue LED │ GP13      │ 220Ω to GND          │    ║
║  └──────────┴───────────┴──────────────────────┘    ║
║                                                      ║
║  PICO 3.3V → Sensor VCC  (NOT 5V — Pico is 3.3V!)  ║
╚══════════════════════════════════════════════════════╝

SETUP — Flash MicroPython then copy these 3 files to Pico:
  main.py     ← this file
  max30102.py ← MAX30102 driver
  ssd1306.py  ← OLED driver

server.py and dashboard.html are UNCHANGED.
"""

import machine
import time
import dht
import json
import sys
import _thread
from max30102 import MAX30102, HeartRateDetector
from ssd1306 import SSD1306_I2C

# ── PIN CONFIGURATION ──────────────────────────────────
I2C_SDA   = 4
I2C_SCL   = 5
DHT_PIN   = 15
RED_LED   = 14
BLUE_LED  = 13

# ── DISPLAY ZONE MAP (two-colour 0.96" OLED) ──────────
# Rows  0–15  → YELLOW zone  (BPM)
# Rows 16–26  → BLUE zone    (Stress + Temp)
# Row     27  → Divider
# Rows 28–63  → BLUE zone    (ECG — 36px)
SCREEN_W    = 128
SCREEN_H    = 64
YELLOW_TOP  = 0
YELLOW_H    = 16
TEXT_ROW    = 17
DIVIDER_ROW = 27
ECG_TOP     = 28
ECG_H       = SCREEN_H - ECG_TOP     # 36
ECG_MID     = ECG_TOP + ECG_H // 2   # 46

# ── ECG AMPLITUDE PER STRESS ──────────────────────────
ECG_AMP = {'NO DATA':10, 'LOW':10, 'NORMAL':13, 'MODERATE':15, 'HIGH':17}

# ── TIMING (milliseconds) ─────────────────────────────
INTERVAL_DHT     = 2000
INTERVAL_STRESS  = 1000
INTERVAL_ECG_BUF = 28
INTERVAL_OLED    = 55
INTERVAL_SERIAL  = 100

# ── LED BLINK PERIODS ─────────────────────────────────
BLINK_HIGH = 200
BLINK_MOD  = 600
BLINK_LOW  = 1500

# ── PQRST WAVEFORM ────────────────────────────────────
PQRST = [
    0.00, 0.00, 0.00, 0.00, 0.00,
    0.08, 0.15, 0.20, 0.15, 0.08,
    0.00, 0.00, 0.00, 0.00,
   -0.10,-0.20,
    0.50, 0.85, 1.00, 0.85, 0.50,
   -0.25,-0.15,
    0.00, 0.00, 0.00,
    0.08, 0.18, 0.28, 0.30, 0.28, 0.18, 0.08,
    0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00,
]
PQRST_LEN = len(PQRST)

STRESS_LABELS = {
    'NO DATA': 'NO DATA',
    'LOW':     'LOW     ',
    'NORMAL':  'NORMAL  ',
    'MODERATE':'MODERATE',
    'HIGH':    'HIGH    ',
}

STRESS_DESC = {
    'NO DATA': 'Place finger...',
    'LOW':     'BPM below 75  ',
    'NORMAL':  '75 to 90 BPM  ',
    'MODERATE':'90 to 110 BPM ',
    'HIGH':    'BPM above 110 ',
}

# ── FLASH LOGGING ─────────────────────────────────────
# Pico has 2MB onboard flash accessible via MicroPython's filesystem.
# We write one CSV row per second to /session.csv.
# At ~50 bytes/row × 10000 rows = ~500KB max — well within flash limits.
LOG_FILE     = '/session.csv'
LOG_MAX_ROWS = 10000    # Rotate (overwrite) after this many rows
LOG_INTERVAL = 1000     # Log every 1000ms
_log_row_count = 0

# ── HARDWARE INIT ─────────────────────────────────────
i2c = machine.I2C(0, sda=machine.Pin(I2C_SDA), scl=machine.Pin(I2C_SCL), freq=400_000)
dht_sensor = dht.DHT11(machine.Pin(DHT_PIN))
red_led    = machine.Pin(RED_LED,  machine.Pin.OUT)
blue_led   = machine.Pin(BLUE_LED, machine.Pin.OUT)

# Startup splash before sensor init
oled = SSD1306_I2C(SCREEN_W, SCREEN_H, i2c)
oled.fill(0)
oled.text("STRESS MONITOR", 8, 2)
oled.text("  By Nikunj   ", 8, 12)
oled.text("  Starting... ", 8, 24)
oled.show()
time.sleep(1.5)

# Init MAX30102
try:
    sensor = MAX30102(i2c)
    detector = HeartRateDetector()
    print("MAX30102 OK")
except Exception as e:
    oled.fill(0)
    oled.text("MAX30102 FAIL", 0, 24)
    oled.show()
    print("MAX30102 error:", e)
    sys.exit()

# ── SHARED STATE ──────────────────────────────────────
# These are read by both cores — Pico MicroPython GIL keeps access safe
class State:
    bpm         = 0
    stress      = 'NO DATA'
    temperature = 0.0
    humidity    = 0
    connected   = True

    # ECG buffer — pre-computed Y pixel positions
    ecg_buf     = bytearray(SCREEN_W)  # 1 byte per column (saves RAM)
    ecg_write   = 0

    # Dirty flags for text regions
    last_bpm    = -1
    last_stress = ''
    last_temp10 = -9999

    # PQRST state
    pqrst_idx   = 0.0
    pqrst_step  = 1.0

    # LED state tracking (avoid unnecessary GPIO writes)
    last_red    = -1
    last_blue   = -1

state = State()

# ── HELPER: ticks ─────────────────────────────────────
def ticks_ms():
    return time.ticks_ms()

def ticks_diff(a, b):
    return time.ticks_diff(a, b)

# ── STRESS CALCULATION ────────────────────────────────
def calculate_stress():
    bpm = state.bpm
    if bpm == 0:
        state.stress = 'NO DATA'
        return
    if bpm < 75:
        state.stress = 'LOW'
    elif bpm < 90:
        state.stress = 'NORMAL'
    elif bpm <= 110:
        state.stress = 'MODERATE'
    else:
        state.stress = 'HIGH'
    # Environmental bump
    if state.temperature > 30 and state.humidity > 70:
        if state.stress == 'LOW':
            state.stress = 'NORMAL'
        elif state.stress == 'NORMAL':
            state.stress = 'MODERATE'
        elif state.stress == 'MODERATE':
            state.stress = 'HIGH'

# ── LED CONTROL ───────────────────────────────────────
def handle_leds():
    now  = ticks_ms()
    s    = state.stress
    new_red  = False
    new_blue = False

    if s == 'HIGH':
        new_red = (now % BLINK_HIGH < BLINK_HIGH // 2)
    elif s == 'MODERATE':
        new_red = (now % BLINK_MOD < BLINK_MOD // 2)
    elif s == 'NORMAL':
        new_blue = True
    elif s == 'LOW':
        new_red = (now % BLINK_LOW < BLINK_LOW // 2)

    # Only write GPIO when state changes
    r = 1 if new_red  else 0
    b = 1 if new_blue else 0
    if r != state.last_red:
        red_led.value(r)
        state.last_red = r
    if b != state.last_blue:
        blue_led.value(b)
        state.last_blue = b

# ── ECG BUFFER UPDATE ─────────────────────────────────
def update_ecg_buffer():
    bpm = state.bpm
    if bpm <= 0:
        state.ecg_buf[state.ecg_write] = ECG_MID
        state.pqrst_idx = 0.0
    else:
        # Recompute step if BPM changed significantly
        upb = (60.0 / bpm) * (1000.0 / INTERVAL_ECG_BUF)
        state.pqrst_step = PQRST_LEN / upb

        idx     = int(state.pqrst_idx) % PQRST_LEN
        sample  = PQRST[idx]
        amp     = ECG_AMP.get(state.stress, 10)
        y       = int(ECG_MID - sample * amp)
        y       = max(ECG_TOP, min(ECG_TOP + ECG_H - 1, y))
        state.ecg_buf[state.ecg_write] = y

        state.pqrst_idx += state.pqrst_step
        if state.pqrst_idx >= PQRST_LEN:
            state.pqrst_idx -= PQRST_LEN

    state.ecg_write = (state.ecg_write + 1) % SCREEN_W

# ── FLASH CSV LOGGING ─────────────────────────────────
# Pico has 2MB onboard flash. At ~50 bytes/row x 10000 rows = ~500KB max.
def log_init():
    """Create CSV with header if file doesn't exist. Count existing rows."""
    global _log_row_count
    try:
        import uos
        uos.stat(LOG_FILE)
        with open(LOG_FILE, 'r') as f:
            _log_row_count = sum(1 for _ in f) - 1  # subtract header
        print("Log found, {} existing rows".format(_log_row_count))
    except OSError:
        with open(LOG_FILE, 'w') as f:
            f.write("timestamp_ms,bpm,stress,temp_c,humidity_pct,ecg\n")
        _log_row_count = 0
        print("New log file created:", LOG_FILE)

def log_row():
    """Append one data row. Rotates file at LOG_MAX_ROWS."""
    global _log_row_count
    if _log_row_count >= LOG_MAX_ROWS:
        with open(LOG_FILE, 'w') as f:
            f.write("timestamp_ms,bpm,stress,temp_c,humidity_pct,ecg\n")
        _log_row_count = 0
        print("Log rotated")

    idx     = int(state.pqrst_idx) % PQRST_LEN
    ecg_val = PQRST[idx] if state.bpm > 0 else 0.0
    with open(LOG_FILE, 'a') as f:
        f.write("{},{},{},{:.1f},{},{:.3f}\n".format(
            time.ticks_ms(), state.bpm, state.stress.strip(),
            state.temperature, state.humidity, ecg_val
        ))
    _log_row_count += 1

# ── SERIAL JSON OUTPUT ────────────────────────────────
def send_json():
    # Get ECG value for dashboard
    idx     = int(state.pqrst_idx) % PQRST_LEN
    ecg_val = PQRST[idx] if state.bpm > 0 else 0.0
    stress  = state.stress.strip()

    # print() flushes automatically — required for Thonny + server.py serial reading
    print('{{"bpm":{},"stress":"{}","temp":{:.1f},"hum":{},"ecg":{:.3f},"connected":true}}'.format(
        state.bpm, stress, state.temperature, state.humidity, ecg_val
    ))

# ── OLED RENDER (single show() call per frame) ────────
def render_oled():
    # ── YELLOW ZONE: BPM ──────────────────────────────
    bpm_changed = (state.bpm != state.last_bpm)
    if bpm_changed:
        state.last_bpm = state.bpm
        oled.fill_rect(0, YELLOW_TOP, SCREEN_W, YELLOW_H, 0)
        if state.bpm > 0:
            # MicroPython framebuf text() is 8px wide × 8px tall per char at scale 1
            # For large text simulation, draw the number twice for 2x scale
            bpm_str = "{} BPM".format(state.bpm)
            # Centre it: each char = 8px, space = 8px
            x = max(0, (SCREEN_W - len(bpm_str) * 8) // 2)
            # Draw at 2x scale using manual pixel doubling via text x2
            _draw_text_2x(oled, bpm_str, x, 1)
        else:
            oled.text("-- PLACE FINGER --", 0, 4)

    # ── BLUE TEXT: Stress + Temp ───────────────────────
    stress_changed = (state.stress != state.last_stress)
    temp10 = int(state.temperature * 10)
    temp_changed = (temp10 != state.last_temp10)

    if stress_changed or temp_changed:
        state.last_stress = state.stress
        state.last_temp10 = temp10
        oled.fill_rect(0, TEXT_ROW, SCREEN_W, DIVIDER_ROW - TEXT_ROW, 0)

        # Stress (left)
        oled.text(STRESS_LABELS.get(state.stress, 'NO DATA'), 0, TEXT_ROW)

        # Temp (right aligned, each char = 6px at scale 1)
        if state.temperature > 0:
            temp_str = "{:.1f}C".format(state.temperature)
        else:
            temp_str = "--C"
        tx = SCREEN_W - len(temp_str) * 6
        oled.text(temp_str, tx, TEXT_ROW)

    # ── DIVIDER ────────────────────────────────────────
    oled.hline(0, DIVIDER_ROW, SCREEN_W, 1)

    # ── BLUE ECG ZONE ──────────────────────────────────
    oled.fill_rect(0, ECG_TOP, SCREEN_W, ECG_H, 0)

    if state.bpm <= 0:
        oled.hline(0, ECG_MID, SCREEN_W, 1)
        oled.text("NO SIGNAL", 28, ECG_MID - 9)
    else:
        # drawLine between adjacent points for smooth, gap-free waveform
        wp = state.ecg_write
        for col in range(SCREEN_W - 1):
            y0 = state.ecg_buf[(wp + col)     % SCREEN_W]
            y1 = state.ecg_buf[(wp + col + 1) % SCREEN_W]
            oled.line(col, y0, col + 1, y1, 1)

        # Blinking write-head cursor
        if (ticks_ms() % 600) < 300:
            cy = state.ecg_buf[(wp - 1) % SCREEN_W]
            oled.pixel(wp % SCREEN_W, cy, 1)

    # ── SINGLE show() call ─────────────────────────────
    oled.show()


def _draw_text_2x(fb, text, x, y):
    """
    Draw text at 2× scale using MicroPython framebuf.
    Each character is normally 8×8 — we scale to 16×16 using pixel doubling.
    """
    cx = x
    for ch in text:
        # Get 8x8 bitmap by drawing to a temp 8x8 buffer
        tmp_buf = bytearray(8)
        import framebuf as fb_mod
        tmp_fb = fb_mod.FrameBuffer(tmp_buf, 8, 8, fb_mod.MONO_VLSB)
        tmp_fb.fill(0)
        tmp_fb.text(ch, 0, 0, 1)
        # Scale 2x
        for row in range(8):
            for col in range(8):
                if tmp_fb.pixel(col, row):
                    fb.fill_rect(cx + col*2, y + row*2, 2, 2, 1)
        cx += 16  # 8px char × 2 = 16px


# ── CORE 1: ECG BUFFER ────────────────────────────────
# Runs on the second Pico core, updates ECG buffer at ~35Hz
def core1_ecg():
    last_ecg = ticks_ms()
    while True:
        now = ticks_ms()
        if ticks_diff(now, last_ecg) >= INTERVAL_ECG_BUF:
            last_ecg = now
            update_ecg_buffer()
        time.sleep_ms(5)

_thread.start_new_thread(core1_ecg, ())

# ── MAIN LOOP (Core 0) ────────────────────────────────
def main():
    last_dht    = ticks_ms()
    last_stress = ticks_ms()
    last_oled   = ticks_ms()
    last_serial = ticks_ms()
    last_log    = ticks_ms()

    # Initialise flash log
    log_init()

    print("Stress Monitor Ready — Pico MicroPython")
    oled.fill(0)
    oled.text("STRESS MONITOR", 8, 2)
    oled.text("  By Nikunj", 8, 12)
    oled.text("Ready!", 44, 28)
    oled.hline(0, DIVIDER_ROW, SCREEN_W, 1)
    oled.show()
    time.sleep(1)

    while True:
        now = ticks_ms()

        # ── 1. READ HEART RATE ────────────────────────
        ir_value = sensor.get_ir()
        state.bpm = detector.process(ir_value)

        # ── 2. READ DHT11 ─────────────────────────────
        if ticks_diff(now, last_dht) >= INTERVAL_DHT:
            last_dht = now
            try:
                dht_sensor.measure()
                state.temperature = dht_sensor.temperature()
                state.humidity    = dht_sensor.humidity()
            except Exception:
                pass  # DHT sometimes fails, keep last reading

        # ── 3. LEDs ───────────────────────────────────
        handle_leds()

        # ── 4. STRESS ─────────────────────────────────
        if ticks_diff(now, last_stress) >= INTERVAL_STRESS:
            last_stress = now
            calculate_stress()

        # ── 5. SERIAL JSON ────────────────────────────
        if ticks_diff(now, last_serial) >= INTERVAL_SERIAL:
            last_serial = now
            send_json()

        # ── 6. OLED ───────────────────────────────────
        if ticks_diff(now, last_oled) >= INTERVAL_OLED:
            last_oled = now
            render_oled()

        # ── 7. FLASH CSV LOG (1 row/sec) ──────────────
        if ticks_diff(now, last_log) >= LOG_INTERVAL:
            last_log = now
            try:
                log_row()
            except Exception as e:
                print("Log error:", e)

        # Tiny sleep to yield to core 1
        time.sleep_ms(2)


main()
