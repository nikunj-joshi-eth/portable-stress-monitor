"""
MAX30102 MicroPython Driver for Raspberry Pi Pico
Heart Rate mode — 3 bytes per FIFO sample (IR only).
"""

import time

REG_FIFO_WR_PTR   = 0x04
REG_OVF_COUNTER   = 0x05
REG_FIFO_RD_PTR   = 0x06
REG_FIFO_DATA     = 0x07
REG_FIFO_CONFIG   = 0x08
REG_MODE_CONFIG   = 0x09
REG_SPO2_CONFIG   = 0x0A
REG_LED1_PA       = 0x0C
REG_PILOT_PA      = 0x10
REG_INTR_ENABLE_1 = 0x02
REG_INTR_ENABLE_2 = 0x03
REG_PART_ID       = 0xFF

ADDR = 0x57


class MAX30102:
    def __init__(self, i2c):
        self.i2c      = i2c
        self._last_ir = 0
        self._buf3    = bytearray(3)   # 3 bytes per sample in HR mode
        self._verify()
        self._setup()

    def _w(self, reg, val):
        self.i2c.writeto_mem(ADDR, reg, bytes([val]))

    def _r1(self, reg):
        return self.i2c.readfrom_mem(ADDR, reg, 1)[0]

    def _verify(self):
        pid = self._r1(REG_PART_ID)
        if pid != 0x15:
            raise RuntimeError("MAX30102 not found (ID=0x{:02X})".format(pid))

    def _setup(self):
        # Soft reset
        self._w(REG_MODE_CONFIG, 0x40)
        time.sleep_ms(200)

        # Clear FIFO
        self._w(REG_FIFO_WR_PTR, 0x00)
        self._w(REG_OVF_COUNTER, 0x00)
        self._w(REG_FIFO_RD_PTR, 0x00)

        # FIFO: no sample averaging, rollover enabled, almost-full=15
        self._w(REG_FIFO_CONFIG, 0x0F)

        # Heart Rate mode = 0x02 (IR LED only, 3 bytes per FIFO sample)
        self._w(REG_MODE_CONFIG, 0x02)

        # 100 samples/sec, 411us pulse, 4096nA range
        self._w(REG_SPO2_CONFIG, 0x27)

        # LED power: moderate (~7mA) — prevents ADC saturation
        self._w(REG_LED1_PA,  0x24)
        self._w(REG_PILOT_PA, 0x7F)

        # Disable interrupts
        self._w(REG_INTR_ENABLE_1, 0x00)
        self._w(REG_INTR_ENABLE_2, 0x00)

        time.sleep_ms(100)

    def get_ir(self):
        """
        Drain all pending FIFO samples (3 bytes each in HR mode).
        Returns most recent IR value.
        """
        wr = self._r1(REG_FIFO_WR_PTR)
        rd = self._r1(REG_FIFO_RD_PTR)
        n  = (wr - rd) & 0x1F

        if n == 0:
            return self._last_ir

        ir = 0
        for _ in range(n):
            # Read exactly 3 bytes per sample (HR mode)
            self.i2c.readfrom_mem_into(ADDR, REG_FIFO_DATA, self._buf3)
            b = self._buf3
            ir = ((b[0] & 0x03) << 16) | (b[1] << 8) | b[2]

        self._last_ir = ir
        return ir

    def reset_fifo(self):
        self._w(REG_FIFO_WR_PTR, 0x00)
        self._w(REG_OVF_COUNTER, 0x00)
        self._w(REG_FIFO_RD_PTR, 0x00)


class HeartRateDetector:
    FINGER_THRESHOLD = 30000
    RATE_SIZE        = 4
    REFRACTORY_MS    = 300

    def __init__(self):
        self._rates     = [0] * self.RATE_SIZE
        self._spot      = 0
        self._last_beat = 0
        self._avg       = 0
        self._prev      = 0
        self._dc        = 0
        self._rising    = False
        self._peak      = 0

    def process(self, ir):
        if ir < self.FINGER_THRESHOLD:
            self._rates  = [0] * self.RATE_SIZE
            self._spot   = 0
            self._avg    = 0
            self._dc     = 0
            self._rising = False
            return 0

        # IIR DC removal (slow baseline)
        if self._dc == 0:
            self._dc = ir
        self._dc = int(self._dc * 0.95 + ir * 0.05)
        ac = ir - self._dc

        delta = ac - self._prev
        self._prev = ac
        now = time.ticks_ms()

        if delta > 0:
            self._rising = True
            self._peak   = ac
        elif delta < 0 and self._rising:
            self._rising = False
            elapsed = time.ticks_diff(now, self._last_beat)
            if elapsed > self.REFRACTORY_MS and self._peak > 50:
                bpm = int(60000 / elapsed)
                if 40 <= bpm <= 200:
                    self._rates[self._spot] = bpm
                    self._spot = (self._spot + 1) % self.RATE_SIZE
                    self._avg  = sum(self._rates) // self.RATE_SIZE
                    self._last_beat = now

        return self._avg

    @property
    def bpm(self):
        return self._avg
