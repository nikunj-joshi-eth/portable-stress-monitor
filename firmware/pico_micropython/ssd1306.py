"""
SSD1306 OLED MicroPython driver — I2C version
For 128x64 monochrome displays on Raspberry Pi Pico
Framebuffer-based: draw everything, then call show() once.
"""

import framebuf
import time

# Commands
SET_CONTRAST        = 0x81
SET_ENTIRE_ON       = 0xA4
SET_NORM_INV        = 0xA6
SET_DISP            = 0xAE
SET_MEM_ADDR        = 0x20
SET_COL_ADDR        = 0x21
SET_PAGE_ADDR       = 0x22
SET_DISP_START_LINE = 0x40
SET_SEG_REMAP       = 0xA0
SET_MUX_RATIO       = 0xA8
SET_COM_OUT_DIR     = 0xC0
SET_DISP_OFFSET     = 0xD3
SET_COM_PIN_CFG     = 0xDA
SET_DISP_CLK_DIV    = 0xD5
SET_PRECHARGE       = 0xD9
SET_VCOM_DESEL      = 0xDB
SET_CHARGE_PUMP     = 0x8D


class SSD1306_I2C(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C):
        self.width  = width
        self.height = height
        self.i2c    = i2c
        self.addr   = addr
        self.buf    = bytearray(width * height // 8)
        super().__init__(self.buf, width, height, framebuf.MONO_VLSB)
        self._init_display()

    def _write_cmd(self, cmd):
        self.i2c.writeto(self.addr, bytes([0x80, cmd]))

    def _write_data(self, data):
        self.i2c.writeto(self.addr, b'\x40' + data)

    def _init_display(self):
        cmds = [
            SET_DISP,                            # Display off
            SET_MEM_ADDR, 0x00,                  # Horizontal addressing
            SET_DISP_START_LINE,                 # Start line 0
            SET_SEG_REMAP | 0x01,                # Seg remap
            SET_MUX_RATIO, self.height - 1,      # Mux ratio
            SET_COM_OUT_DIR | 0x08,              # COM scan direction
            SET_DISP_OFFSET, 0x00,               # No offset
            SET_COM_PIN_CFG, 0x12,               # COM pins
            SET_DISP_CLK_DIV, 0x80,              # Clock
            SET_PRECHARGE, 0xF1,                 # Precharge
            SET_VCOM_DESEL, 0x30,                # VCOM
            SET_CONTRAST, 0xFF,                  # Max contrast
            SET_ENTIRE_ON,                       # Follow RAM
            SET_NORM_INV,                        # Normal display
            SET_CHARGE_PUMP, 0x14,               # Charge pump on
            SET_DISP | 0x01,                     # Display on
        ]
        for c in cmds:
            self._write_cmd(c)

    def show(self):
        """Push framebuffer to display over I2C."""
        self._write_cmd(SET_COL_ADDR)
        self._write_cmd(0)
        self._write_cmd(self.width - 1)
        self._write_cmd(SET_PAGE_ADDR)
        self._write_cmd(0)
        self._write_cmd(self.height // 8 - 1)
        # Send in 16-byte chunks for I2C reliability
        for i in range(0, len(self.buf), 16):
            self._write_data(self.buf[i:i+16])

    def fill(self, c):
        super().fill(c)

    def pixel(self, x, y, c):
        super().pixel(x, y, c)

    def hline(self, x, y, w, c):
        super().hline(x, y, w, c)

    def vline(self, x, y, h, c):
        super().vline(x, y, h, c)

    def line(self, x1, y1, x2, y2, c):
        super().line(x1, y1, x2, y2, c)

    def rect(self, x, y, w, h, c):
        super().rect(x, y, w, h, c)

    def fill_rect(self, x, y, w, h, c):
        super().fill_rect(x, y, w, h, c)

    def text(self, s, x, y, c=1):
        super().text(s, x, y, c)

    def contrast(self, val):
        self._write_cmd(SET_CONTRAST)
        self._write_cmd(val)

    def invert(self, inv):
        self._write_cmd(SET_NORM_INV | (inv & 1))

    def poweroff(self):
        self._write_cmd(SET_DISP)

    def poweron(self):
        self._write_cmd(SET_DISP | 0x01)
