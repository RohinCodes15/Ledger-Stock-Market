"""
Ledger - a pretend-money stock trading game for kids & teens
=============================================================
Run with: python ledger_game.py   (requires: pip install -r requirements.txt)

All money is fake. Prices come from a built-in market simulation (calm day-to-day moves, sector
trends and rare news events). An optional live-quote mode exists but is switched off.
"""

import os
import hashlib
import json
import platform
import random
import re
import sys
import traceback
import time
import math
import struct
import subprocess
import threading
import urllib.parse
import urllib.request
import concurrent.futures
import google_auth
import ledger_safety

os.environ["SDL_VIDEO_HIGHDPI"] = "1"

if platform.system() == "Darwin":
    try:
        import ctypes
        ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    except Exception:
        pass

import pygame

pygame.init()

# ----------------------------
# SOUND SYNTHESIZER
# ----------------------------

SOUNDS = {}


def init_sounds():
    try:
        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)

        def make_tone(freqs, duration=0.15, volume=0.3):
            sample_rate = 22050
            num_samples = int(sample_rate * duration)
            buf = bytearray()
            for i in range(num_samples):
                t = i / sample_rate
                frac = i / num_samples
                env = min(1.0, frac * 25.0) * (1.0 - frac)
                val = 0.0
                if isinstance(freqs, (int, float)):
                    val = math.sin(2 * math.pi * freqs * t)
                else:
                    for f, s_frac, e_frac in freqs:
                        if s_frac <= frac <= e_frac:
                            val += math.sin(2 * math.pi * f * t)
                val = max(-1.0, min(1.0, val * volume * env))
                buf.extend(struct.pack("<h", int(val * 32767)))
            return pygame.mixer.Sound(buffer=bytes(buf))

        SOUNDS["trade"] = make_tone([(1046, 0.0, 0.45), (1568, 0.4, 1.0)], duration=0.22, volume=0.35)
        SOUNDS["achievement"] = make_tone(
            [(523, 0.0, 0.25), (659, 0.25, 0.5), (784, 0.5, 0.75), (1046, 0.75, 1.0)],
            duration=0.45, volume=0.4,
        )
        SOUNDS["dividend"] = make_tone([(1318, 0.0, 0.45), (1760, 0.35, 1.0)], duration=0.28, volume=0.35)
        SOUNDS["error"] = make_tone([(220, 0.0, 0.45), (180, 0.45, 1.0)], duration=0.18, volume=0.3)
        SOUNDS["beep"] = make_tone([(880, 0.0, 1.0)], duration=0.10, volume=0.3)
        SOUNDS["bell"] = make_tone([(587, 0.0, 0.7), (880, 0.0, 0.5)], duration=0.5, volume=0.4)
        SOUNDS["victory"] = make_tone(
            [(523, 0.0, 0.2), (659, 0.2, 0.4), (784, 0.4, 0.6), (1046, 0.6, 1.0)],
            duration=0.6, volume=0.45,
        )
        SOUNDS["defeat"] = make_tone([(440, 0.0, 0.4), (349, 0.35, 0.7), (261, 0.65, 1.0)], duration=0.45, volume=0.35)
        SOUNDS["click"] = make_tone([(520, 0.0, 1.0)], duration=0.04, volume=0.08)
        SOUNDS["xp"] = make_tone([(784, 0.0, 0.5), (1174, 0.4, 1.0)], duration=0.18, volume=0.28)
        SOUNDS["stamp"] = make_tone([(150, 0.0, 0.5), (95, 0.3, 1.0)], duration=0.14, volume=0.55)
        SOUNDS["pop"] = make_tone([(1320, 0.0, 0.6), (1760, 0.5, 1.0)], duration=0.06, volume=0.14)
        SOUNDS["tick"] = make_tone([(1900, 0.0, 1.0)], duration=0.03, volume=0.07)
        SOUNDS["swoosh"] = make_tone([(380, 0.0, 0.35), (520, 0.3, 0.7), (700, 0.65, 1.0)], duration=0.12, volume=0.1)
        SOUNDS["combo"] = make_tone([(880, 0.0, 0.33), (1175, 0.33, 0.66), (1568, 0.66, 1.0)], duration=0.22, volume=0.26)
    except Exception:
        pass


init_sounds()


def play_sound(name):
    if not getattr(state, "sound_enabled", True):
        return
    if name in SOUNDS:
        try:
            SOUNDS[name].play()
        except Exception:
            pass


# ----------------------------
# WINDOW
# ----------------------------

WIDTH, HEIGHT = 460, 780


# Retina rendering. The whole game is laid out in 460x780 "points", but on a
# high-DPI Mac the window really has 2x as many pixels. Every surface below is a
# HiSurface: code keeps drawing in points while the pixels land at full
# resolution, so text, curves and charts are crisp instead of upscaled.
def _app_icon(size=256):
    """Ledger's icon (rising bars on a dark tile), drawn in code so it can't go missing.
    Replaces pygame's default snake icon in the title bar, taskbar and Dock."""
    icon = pygame.Surface((size, size), pygame.SRCALPHA)
    k = size / 1024
    tile = pygame.Rect(int(100 * k), int(100 * k), int(824 * k), int(824 * k))
    pygame.draw.rect(icon, (26, 26, 26), tile, border_radius=int(185 * k))
    bar_w, gap, base = int(120 * k), int(60 * k), tile.bottom - int(190 * k)
    x0 = tile.centerx - (3 * bar_w + 2 * gap) // 2
    for i, (h, col) in enumerate(((220, (255, 255, 255)), (340, (255, 255, 255)), (470, (46, 204, 113)))):
        pygame.draw.rect(icon, col, pygame.Rect(x0 + i * (bar_w + gap), base - int(h * k), bar_w, int(h * k)),
                         border_radius=int(30 * k))
    return icon


def _open_window():
    try:
        win = pygame.Window("Ledger — Learn the Market", (WIDTH, HEIGHT), allow_high_dpi=True)
        try:
            win.set_icon(_app_icon())
        except Exception:
            pass
        surf = win.get_surface()
        pygame.key.start_text_input()
        return win, surf
    except Exception:
        try:
            pygame.display.set_icon(_app_icon())
        except Exception:
            pass
        surf = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Ledger — Learn the Market")
        return None, surf


_window, _window_surface = _open_window()
UI_SCALE = max(1, round(_window_surface.get_width() / WIDTH))


def _sc(v):
    return v * UI_SCALE


def _scale_rect(r):
    r = pygame.Rect(r)
    s = UI_SCALE
    return pygame.Rect(r.x * s, r.y * s, r.w * s, r.h * s)


def _unscale_rect(r):
    s = UI_SCALE
    return pygame.Rect(r.x // s, r.y // s, -(-r.w // s), -(-r.h // s))


def _scale_pt(p):
    return (p[0] * UI_SCALE, p[1] * UI_SCALE)


class HiSurface:
    """A surface addressed in points and stored at UI_SCALE pixels per point."""

    def __init__(self, size, flags=0, *, hi=None):
        if hi is not None:
            self.hi = hi
            self._size = (-(-hi.get_width() // UI_SCALE), -(-hi.get_height() // UI_SCALE))
        else:
            w, h = int(math.ceil(size[0])), int(math.ceil(size[1]))
            self._size = (max(0, w), max(0, h))
            self.hi = pygame.Surface((max(1, _sc(self._size[0])), max(1, _sc(self._size[1]))), flags)
        self._shared = False

    def get_size(self):
        return self._size

    def get_width(self):
        return self._size[0]

    def get_height(self):
        return self._size[1]

    def get_rect(self, **kwargs):
        rect = pygame.Rect((0, 0), self._size)
        for k, v in kwargs.items():
            setattr(rect, k, v)
        return rect

    def fill(self, color, rect=None, special_flags=0):
        area = None if rect is None else _scale_rect(rect)
        return _unscale_rect(self.hi.fill(color, area, special_flags))

    def blit(self, source, dest, area=None, special_flags=0):
        pos = dest.topleft if isinstance(dest, pygame.Rect) else (dest[0], dest[1])
        if isinstance(source, HiSurface):
            src = source.hi
        else:
            src = pygame.transform.smoothscale_by(source, UI_SCALE) if UI_SCALE != 1 else source
        hit = self.hi.blit(src, _scale_pt(pos), None if area is None else _scale_rect(area), special_flags)
        return _unscale_rect(hit)

    def set_alpha(self, value, flags=0):
        if self._shared:
            # Rendered text is cached and shared, so fade a private copy.
            self.hi = self.hi.copy()
            self._shared = False
        self.hi.set_alpha(value, flags)

    def get_alpha(self):
        return self.hi.get_alpha()

    def set_clip(self, rect=None):
        self.hi.set_clip(None if rect is None else _scale_rect(rect))

    def get_clip(self):
        return _unscale_rect(self.hi.get_clip())

    def copy(self):
        return HiSurface(None, hi=self.hi.copy())

    def __getattr__(self, name):
        return getattr(self.hi, name)


screen = HiSurface(None, hi=_window_surface)


def present_frame():
    if _window is not None:
        _window.flip()
    else:
        pygame.display.flip()


def _install_hidpi_draw():
    """Route pygame.draw through HiSurface so existing point-based calls stay sharp."""
    raw = {name: getattr(pygame.draw, name) for name in
           ("rect", "circle", "aacircle", "ellipse", "arc", "line", "aaline", "lines", "aalines", "polygon")}

    def target(surf):
        return (surf.hi, True) if isinstance(surf, HiSurface) else (surf, False)

    def out(r, hi):
        return _unscale_rect(r) if hi else r

    def rect(surf, color, r, width=0, border_radius=-1, border_top_left_radius=-1, border_top_right_radius=-1,
             border_bottom_left_radius=-1, border_bottom_right_radius=-1):
        s, hi = target(surf)
        if not hi:
            return raw["rect"](surf, color, r, width, border_radius, border_top_left_radius, border_top_right_radius,
                               border_bottom_left_radius, border_bottom_right_radius)
        k = lambda v: _sc(v) if v > 0 else v
        return out(raw["rect"](s, color, _scale_rect(r), k(width), k(border_radius), k(border_top_left_radius),
                               k(border_top_right_radius), k(border_bottom_left_radius), k(border_bottom_right_radius)), hi)

    def make_circle(name):
        def circle(surf, color, center, radius, width=0, *corners, **kw):
            s, hi = target(surf)
            if not hi:
                return raw[name](surf, color, center, radius, width, *corners, **kw)
            fn = raw[name]
            # Solid circles on the opaque screen get anti-aliased edges.
            if name == "circle" and s is _window_surface and not corners and not kw and radius >= 2:
                fn = raw["aacircle"]
            return out(fn(s, color, _scale_pt(center), _sc(radius), _sc(width), *corners, **kw), hi)
        return circle

    def ellipse(surf, color, r, width=0):
        s, hi = target(surf)
        if not hi:
            return raw["ellipse"](surf, color, r, width)
        return out(raw["ellipse"](s, color, _scale_rect(r), _sc(width)), hi)

    def arc(surf, color, r, start, stop, width=1):
        s, hi = target(surf)
        if not hi:
            return raw["arc"](surf, color, r, start, stop, width)
        return out(raw["arc"](s, color, _scale_rect(r), start, stop, _sc(width)), hi)

    def make_line(name):
        def line(surf, color, a, b, width=1):
            s, hi = target(surf)
            if not hi:
                return raw[name](surf, color, a, b, width)
            return out(raw[name](s, color, _scale_pt(a), _scale_pt(b), _sc(width)), hi)
        return line

    def lines(surf, color, closed, points, width=1):
        s, hi = target(surf)
        if not hi:
            return raw["lines"](surf, color, closed, points, width)
        pts = [_scale_pt(p) for p in points]
        w = _sc(width)
        if w > 2 and len(pts) > 1:
            # pygame leaves notches at thick polyline joints; round them off.
            for p in pts:
                raw["circle"](s, color, p, w / 2)
        return out(raw["lines"](s, color, closed, pts, w), hi)

    def aalines(surf, color, closed, points):
        s, hi = target(surf)
        if not hi:
            return raw["aalines"](surf, color, closed, points)
        return out(raw["aalines"](s, color, closed, [_scale_pt(p) for p in points]), hi)

    def polygon(surf, color, points, width=0):
        s, hi = target(surf)
        if not hi:
            return raw["polygon"](surf, color, points, width)
        return out(raw["polygon"](s, color, [_scale_pt(p) for p in points], _sc(width)), hi)

    pygame.draw.rect = rect
    pygame.draw.circle = make_circle("circle")
    pygame.draw.aacircle = make_circle("aacircle")
    pygame.draw.ellipse = ellipse
    pygame.draw.arc = arc
    pygame.draw.line = make_line("line")
    pygame.draw.aaline = make_line("aaline")
    pygame.draw.lines = lines
    pygame.draw.aalines = aalines
    pygame.draw.polygon = polygon


_install_hidpi_draw()
clock = pygame.time.Clock()

THEMES = {
    "light": {
        "BG": (250, 250, 249),
        "CARD": (255, 255, 255),
        "BORDER": (232, 230, 225),
        "INK": (26, 26, 26),
        "GRAY": (138, 133, 121),
        "LIGHT_GRAY": (176, 171, 158),
        "PANEL_BG": (242, 241, 238),
        "GOLD_BG": (253, 246, 227),
        "GREEN": (27, 122, 76),
        "RED": (196, 61, 61),
        "GOLD": (184, 134, 11),
        "PURPLE": (124, 58, 237),
        "PURPLE_BG": (245, 243, 255),
        "ORANGE": (234, 88, 12),
        "TEAL": (15, 118, 110),
        "FLASH_GREEN": (0, 200, 5),
        "FLASH_RED": (255, 59, 48),
    },
    "dark": {
        # Despite the name, this is the palette the whole game runs on: a clean white look
        # with one green accent, like a real brokerage app.
        "BG": (255, 255, 255),
        "CARD": (255, 255, 255),
        "BORDER": (230, 230, 232),
        "INK": (17, 17, 19),
        "GRAY": (110, 110, 118),
        "LIGHT_GRAY": (160, 160, 168),
        "PANEL_BG": (245, 245, 247),
        "GOLD_BG": (245, 245, 247),
        "GREEN": (0, 160, 70),
        "RED": (220, 50, 40),
        "GOLD": (17, 17, 19),
        "PURPLE": (17, 17, 19),
        "PURPLE_BG": (245, 245, 247),
        "ORANGE": (220, 50, 40),
        "TEAL": (0, 160, 70),
        "FLASH_GREEN": (0, 200, 5),
        "FLASH_RED": (255, 80, 0),
    },
}


# Colorblind-friendly swap: blue for "up", orange for "down" (Okabe-Ito palette).
COLORBLIND = {
    "light": {"GREEN": (0, 114, 178), "RED": (213, 94, 0), "FLASH_GREEN": (0, 114, 178), "FLASH_RED": (213, 94, 0)},
    "dark": {"GREEN": (86, 180, 233), "RED": (230, 159, 0), "FLASH_GREEN": (86, 180, 233), "FLASH_RED": (230, 159, 0)},
}


def C(key):
    mode = "dark" if state.dark_mode else "light"
    if getattr(state, "colorblind", False):
        swap = COLORBLIND[mode].get(key)
        if swap:
            return swap
    return THEMES[mode][key]


def _luminance(rgb):
    """How bright a color looks (WCAG relative luminance: 0 = black, 1 = white)."""
    def channel(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def text_on(fill):
    """Color for text or icons drawn on a colored fill. White, except in dark mode when the fill
    is too bright for white to stay readable (dark mode's gold, green and orange are brighter)."""
    if state.dark_mode and 1.05 / (_luminance(fill) + 0.05) < 3.0:
        return C("CARD")
    return (255, 255, 255)


# Premium app typography. Use one clean sans-serif family across the whole game
# so every screen feels like the same polished product instead of mixing UI and serif fonts.
_UI_FONT = (
    "Avenir Next" if pygame.font.match_font("avenir next")
    else ("SF Pro Display" if pygame.font.match_font("sf pro display")
          else ("Noto Sans" if pygame.font.match_font("noto sans") else "arial"))
)
_DISPLAY_FONT = _UI_FONT

class SafeFont:
    """Font wrapper that drops glyphs the font cannot draw (emoji, arrows, check marks)
    so players never see empty "missing glyph" boxes."""

    _REPLACE = {"\u2192": "->", "\u2713": "", "\u2714": "", "\ufe0f": "", "\u200d": ""}

    def __init__(self, font, hi_font=None):
        self._font = font
        # Same face at UI_SCALE x the size, so glyphs are drawn at Retina resolution.
        self._hi = hi_font or font
        self._missing_ref = font.metrics("\ue000")[0]
        self._ok = {}
        self._clean_cache = {}
        self._render_cache = {}

    def __getattr__(self, name):
        return getattr(self._font, name)

    def _glyph_ok(self, ch):
        ok = self._ok.get(ch)
        if ok is None:
            if ord(ch) < 0x250:
                ok = True
            elif ord(ch) > 0xFFFF:
                ok = False
            else:
                m = self._font.metrics(ch)
                ok = bool(m) and m[0] is not None and m[0] != self._missing_ref
            self._ok[ch] = ok
        return ok

    def clean(self, text):
        key = str(text)
        cached = self._clean_cache.get(key)
        if cached is not None:
            return cached
        out = key
        if not key.isascii():
            for k, v in self._REPLACE.items():
                out = out.replace(k, v)
            out = "".join(ch for ch in out if self._glyph_ok(ch))
            if out != key:
                while "  " in out:
                    out = out.replace("  ", " ")
                out = out.strip()
        if len(self._clean_cache) < 4000:
            self._clean_cache[key] = out
        return out

    def render(self, text, antialias, color, *args):
        key = (str(text), antialias, tuple(color), args)
        img = self._render_cache.get(key)
        if img is None:
            img = self._hi.render(self.clean(text), antialias, color, *args)
            if len(self._render_cache) > 1500:
                self._render_cache.clear()
            self._render_cache[key] = img
        out = HiSurface(None, hi=img)
        out._shared = True
        return out

    def size(self, text):
        w, h = self._hi.size(self.clean(text))
        return (-(-w // UI_SCALE), -(-h // UI_SCALE))

    def get_height(self):
        return -(-self._hi.get_height() // UI_SCALE)

    def get_linesize(self):
        return -(-self._hi.get_linesize() // UI_SCALE)


def _SysFont(name, size, *args, **kwargs):
    lo = pygame.font.SysFont(name, size, *args, **kwargs)
    hi = pygame.font.SysFont(name, size * UI_SCALE, *args, **kwargs) if UI_SCALE != 1 else lo
    return SafeFont(lo, hi)


# Keep the existing layout-compatible sizes, but make the hierarchy clearer.
# The goal is readable, airy text without forcing every panel to grow.
font_tiny = _SysFont(_UI_FONT, 12)
font_small = _SysFont(_UI_FONT, 14)
font_small_bold = _SysFont(_UI_FONT, 14, bold=True)
font_body = _SysFont(_UI_FONT, 16)
font_body_bold = _SysFont(_UI_FONT, 16, bold=True)
font_medium_bold = _SysFont(_UI_FONT, 18, bold=True)
font_large = _SysFont(_DISPLAY_FONT, 34, bold=True)
font_large_med = _SysFont(_DISPLAY_FONT, 21, bold=True)
font_price = _SysFont(_DISPLAY_FONT, 17, bold=True)
font_countdown = _SysFont(_DISPLAY_FONT, 28, bold=True)
font_huge = _SysFont(_DISPLAY_FONT, 44, bold=True)

# Tutorial-only type system: intentionally larger and airier than the normal app UI.
# The tutorial is the first impression, so readability gets its own hierarchy.
tutorial_kicker = _SysFont(_UI_FONT, 13, bold=True)
tutorial_title = _SysFont(_DISPLAY_FONT, 30, bold=True)
tutorial_body = _SysFont(_UI_FONT, 18)
tutorial_body_bold = _SysFont(_UI_FONT, 18, bold=True)
tutorial_label = _SysFont(_UI_FONT, 14, bold=True)
tutorial_value = _SysFont(_DISPLAY_FONT, 25, bold=True)
tutorial_button = _SysFont(_UI_FONT, 16, bold=True)
tutorial_micro = _SysFont(_UI_FONT, 13)


STARTING_CASH = 1000.00
if getattr(sys, "frozen", False):
    # Packaged app: keep saves in the player's own folder so they survive updates.
    _DATA_DIR = os.path.join(os.path.expanduser("~/Library/Application Support") if sys.platform == "darwin"
                             else os.environ.get("APPDATA", os.path.expanduser("~")), "Ledger")
else:
    _DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
SAVE_FILE = os.path.join(_DATA_DIR, "ledger_save.json")
ACCOUNTS_FILE = os.path.join(_DATA_DIR, "ledger_accounts.json")

# Simulated educational prices only. Unlock with level OR net worth.
STOCKS = [
    {"ticker": "AAPL", "name": "Apple", "sector": "Technology", "price": 195.0, "vol": 0.005, "div": 0.25,
     "desc": "Makes iPhones, iPads, Macs, and Apple Watches.", "unlock_level": 1, "unlock_worth": 0},
    {"ticker": "NKE", "name": "Nike", "sector": "Apparel", "price": 78.0, "vol": 0.007, "div": 0.35,
     "desc": "Designs sneakers, athletic clothes, and gear.", "unlock_level": 1, "unlock_worth": 0},
    {"ticker": "DIS", "name": "Disney", "sector": "Entertainment", "price": 112.0, "vol": 0.006, "div": 0.40,
     "desc": "Films, parks, Marvel, and Star Wars.", "unlock_level": 1, "unlock_worth": 0},
    {"ticker": "MCD", "name": "McDonald's", "sector": "Restaurants", "price": 288.0, "vol": 0.004, "div": 0.75,
     "desc": "Burgers and fries in restaurants worldwide.", "unlock_level": 1, "unlock_worth": 0},
    {"ticker": "SBUX", "name": "Starbucks", "sector": "Restaurants", "price": 96.0, "vol": 0.006, "div": 0.45,
     "desc": "Coffee, teas, and cafe snacks.", "unlock_level": 1, "unlock_worth": 0},
    {"ticker": "KO", "name": "Coca-Cola", "sector": "Drinks", "price": 62.0, "vol": 0.004, "div": 0.46,
     "desc": "Sells sodas and drinks around the world.", "unlock_level": 1, "unlock_worth": 0},
    {"ticker": "MSFT", "name": "Microsoft", "sector": "Technology", "price": 415.0, "vol": 0.005, "div": 0.75,
     "desc": "Windows, Xbox, Office, and cloud software.", "unlock_level": 2, "unlock_worth": 1250},
    {"ticker": "GOOGL", "name": "Alphabet", "sector": "Technology", "price": 168.0, "vol": 0.006, "div": 0.20,
     "desc": "Google search, YouTube, and Android.", "unlock_level": 2, "unlock_worth": 1250},
    {"ticker": "AMZN", "name": "Amazon", "sector": "Retail", "price": 182.0, "vol": 0.007, "div": 0.00,
     "desc": "Online shopping, Prime, and AWS cloud.", "unlock_level": 2, "unlock_worth": 1300},
    {"ticker": "META", "name": "Meta", "sector": "Technology", "price": 505.0, "vol": 0.008, "div": 0.50,
     "desc": "Facebook, Instagram, WhatsApp, and VR.", "unlock_level": 3, "unlock_worth": 1450},
    {"ticker": "NFLX", "name": "Netflix", "sector": "Entertainment", "price": 640.0, "vol": 0.008, "div": 0.00,
     "desc": "Streaming movies and original shows.", "unlock_level": 3, "unlock_worth": 1450},
    {"ticker": "SONY", "name": "Sony", "sector": "Electronics", "price": 84.0, "vol": 0.007, "div": 0.20,
     "desc": "PlayStation, cameras, games, and music.", "unlock_level": 3, "unlock_worth": 1400},
    {"ticker": "TSLA", "name": "Tesla", "sector": "Auto", "price": 248.0, "vol": 0.012, "div": 0.00,
     "desc": "Electric cars and energy products.", "unlock_level": 4, "unlock_worth": 1700},
    {"ticker": "NVDA", "name": "NVIDIA", "sector": "Technology", "price": 118.0, "vol": 0.011, "div": 0.04,
     "desc": "GPUs used in gaming and AI.", "unlock_level": 4, "unlock_worth": 1750},
    {"ticker": "AMD", "name": "AMD", "sector": "Technology", "price": 156.0, "vol": 0.010, "div": 0.00,
     "desc": "Computer chips and graphics cards.", "unlock_level": 4, "unlock_worth": 1700},
    {"ticker": "INTC", "name": "Intel", "sector": "Technology", "price": 22.0, "vol": 0.009, "div": 0.12,
     "desc": "Processors for PCs and data centers.", "unlock_level": 4, "unlock_worth": 1650},
    {"ticker": "JPM", "name": "JPMorgan", "sector": "Finance", "price": 210.0, "vol": 0.005, "div": 1.15,
     "desc": "One of the largest banks in the U.S.", "unlock_level": 5, "unlock_worth": 2000},
    {"ticker": "V", "name": "Visa", "sector": "Finance", "price": 275.0, "vol": 0.005, "div": 0.52,
     "desc": "Payment network for cards worldwide.", "unlock_level": 5, "unlock_worth": 2000},
    {"ticker": "MA", "name": "Mastercard", "sector": "Finance", "price": 460.0, "vol": 0.005, "div": 0.66,
     "desc": "Card payments and banking services.", "unlock_level": 5, "unlock_worth": 2050},
    {"ticker": "BAC", "name": "Bank of America", "sector": "Finance", "price": 39.0, "vol": 0.006, "div": 0.26,
     "desc": "Consumer banking and investing.", "unlock_level": 5, "unlock_worth": 1950},
    {"ticker": "WMT", "name": "Walmart", "sector": "Retail", "price": 68.0, "vol": 0.004, "div": 0.21,
     "desc": "Giant stores and grocery delivery.", "unlock_level": 6, "unlock_worth": 2300},
    {"ticker": "COST", "name": "Costco", "sector": "Retail", "price": 890.0, "vol": 0.005, "div": 1.16,
     "desc": "Membership warehouse clubs.", "unlock_level": 6, "unlock_worth": 2400},
    {"ticker": "TGT", "name": "Target", "sector": "Retail", "price": 148.0, "vol": 0.007, "div": 1.12,
     "desc": "Stores for clothes, home, and groceries.", "unlock_level": 6, "unlock_worth": 2300},
    {"ticker": "HD", "name": "Home Depot", "sector": "Retail", "price": 365.0, "vol": 0.006, "div": 2.25,
     "desc": "Tools and home-improvement stores.", "unlock_level": 6, "unlock_worth": 2350},
    {"ticker": "PFE", "name": "Pfizer", "sector": "Healthcare", "price": 28.0, "vol": 0.007, "div": 0.42,
     "desc": "Medicines and vaccines.", "unlock_level": 7, "unlock_worth": 2700},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "sector": "Healthcare", "price": 162.0, "vol": 0.004, "div": 1.24,
     "desc": "Healthcare products and medicines.", "unlock_level": 7, "unlock_worth": 2750},
    {"ticker": "BA", "name": "Boeing", "sector": "Industrial", "price": 178.0, "vol": 0.009, "div": 0.00,
     "desc": "Airplanes and aerospace.", "unlock_level": 7, "unlock_worth": 2800},
    {"ticker": "F", "name": "Ford", "sector": "Auto", "price": 11.0, "vol": 0.010, "div": 0.15,
     "desc": "Cars, trucks, and electric vehicles.", "unlock_level": 7, "unlock_worth": 2600},
    {"ticker": "UBER", "name": "Uber", "sector": "Tech", "price": 72.0, "vol": 0.009, "div": 0.00,
     "desc": "Rides and food delivery.", "unlock_level": 8, "unlock_worth": 3200},
    {"ticker": "ABNB", "name": "Airbnb", "sector": "Travel", "price": 132.0, "vol": 0.009, "div": 0.00,
     "desc": "Homes and travel stays.", "unlock_level": 8, "unlock_worth": 3300},
    {"ticker": "RBLX", "name": "Roblox", "sector": "Gaming", "price": 44.0, "vol": 0.013, "div": 0.00,
     "desc": "A platform where people play and create games.", "unlock_level": 8, "unlock_worth": 3100},
    {"ticker": "LULU", "name": "Lululemon", "sector": "Apparel", "price": 298.0, "vol": 0.008, "div": 0.00,
     "desc": "Athletic clothing and accessories.", "unlock_level": 8, "unlock_worth": 3250},
    {"ticker": "GS", "name": "Goldman Sachs", "sector": "Finance", "price": 490.0, "vol": 0.007, "div": 3.00,
     "desc": "Investment banking and trading.", "unlock_level": 9, "unlock_worth": 3800},
    {"ticker": "BLK", "name": "BlackRock", "sector": "Finance", "price": 860.0, "vol": 0.006, "div": 5.10,
     "desc": "One of the world's largest asset managers.", "unlock_level": 9, "unlock_worth": 4000},
    {"ticker": "SHOP", "name": "Shopify", "sector": "Tech", "price": 76.0, "vol": 0.011, "div": 0.00,
     "desc": "Tools for people to run online stores.", "unlock_level": 9, "unlock_worth": 3700},
    {"ticker": "SPOT", "name": "Spotify", "sector": "Entertainment", "price": 340.0, "vol": 0.010, "div": 0.00,
     "desc": "Music and podcast streaming.", "unlock_level": 10, "unlock_worth": 4300},
    {"ticker": "NKEA", "name": "Nintendo", "sector": "Gaming", "price": 14.0, "vol": 0.008, "div": 0.12,
     "desc": "Mario, Zelda, and Nintendo Switch. Simulated ticker.", "unlock_level": 10, "unlock_worth": 4200},
]

# Expanded simulated market. These are educational placeholders, not live quotes.
MORE_STOCKS = [
    {"ticker":"CRM","name":"Salesforce","sector":"Technology","price":265.0,"vol":0.008,"div":0.00,"desc":"Business software and cloud tools.","unlock_level":6,"unlock_worth":2300},
    {"ticker":"ORCL","name":"Oracle","sector":"Technology","price":175.0,"vol":0.006,"div":0.40,"desc":"Cloud infrastructure and business software.","unlock_level":6,"unlock_worth":2400},
    {"ticker":"ADBE","name":"Adobe","sector":"Technology","price":410.0,"vol":0.008,"div":0.00,"desc":"Creative and document software.","unlock_level":7,"unlock_worth":2800},
    {"ticker":"CSCO","name":"Cisco","sector":"Technology","price":52.0,"vol":0.005,"div":0.40,"desc":"Networking hardware and software.","unlock_level":6,"unlock_worth":2200},
    {"ticker":"QCOM","name":"Qualcomm","sector":"Technology","price":168.0,"vol":0.009,"div":0.85,"desc":"Wireless chips and connectivity technology.","unlock_level":7,"unlock_worth":2750},
    {"ticker":"PEP","name":"PepsiCo","sector":"Drinks","price":165.0,"vol":0.004,"div":1.35,"desc":"Snacks and beverages sold around the world.","unlock_level":5,"unlock_worth":2000},
    {"ticker":"MELI","name":"MercadoLibre","sector":"Retail","price":1720.0,"vol":0.012,"div":0.00,"desc":"Online commerce and digital payments.","unlock_level":9,"unlock_worth":3900},
    {"ticker":"SIRI","name":"Sirius XM","sector":"Entertainment","price":24.0,"vol":0.010,"div":0.03,"desc":"Subscription audio and entertainment.","unlock_level":5,"unlock_worth":2000},
    {"ticker":"CMCSA","name":"Comcast","sector":"Entertainment","price":39.0,"vol":0.006,"div":0.31,"desc":"Media, broadband, and entertainment.","unlock_level":6,"unlock_worth":2300},
    {"ticker":"CVX","name":"Chevron","sector":"Energy","price":158.0,"vol":0.008,"div":1.63,"desc":"Energy exploration, production, and refining.","unlock_level":6,"unlock_worth":2400},
    {"ticker":"XOM","name":"Exxon Mobil","sector":"Energy","price":112.0,"vol":0.007,"div":0.99,"desc":"A large simulated energy company.","unlock_level":6,"unlock_worth":2400},
    {"ticker":"CAT","name":"Caterpillar","sector":"Industrial","price":345.0,"vol":0.008,"div":1.41,"desc":"Construction and heavy equipment.","unlock_level":7,"unlock_worth":2800},
    {"ticker":"GE","name":"GE Aerospace","sector":"Industrial","price":188.0,"vol":0.009,"div":0.36,"desc":"Aircraft engines and aerospace systems.","unlock_level":7,"unlock_worth":2850},
    {"ticker":"UPS","name":"UPS","sector":"Industrial","price":102.0,"vol":0.007,"div":1.63,"desc":"Package delivery and logistics.","unlock_level":6,"unlock_worth":2450},
    {"ticker":"TMO","name":"Thermo Fisher","sector":"Healthcare","price":540.0,"vol":0.006,"div":0.43,"desc":"Scientific tools and laboratory services.","unlock_level":8,"unlock_worth":3300},
    {"ticker":"MRK","name":"Merck","sector":"Healthcare","price":118.0,"vol":0.005,"div":0.81,"desc":"Medicines and healthcare research.","unlock_level":7,"unlock_worth":2850},
    {"ticker":"UNH","name":"UnitedHealth","sector":"Healthcare","price":575.0,"vol":0.008,"div":2.10,"desc":"Health insurance and healthcare services.","unlock_level":8,"unlock_worth":3300},
    {"ticker":"CVS","name":"CVS Health","sector":"Healthcare","price":58.0,"vol":0.008,"div":0.67,"desc":"Pharmacy and healthcare services.","unlock_level":6,"unlock_worth":2350},
    {"ticker":"LOW","name":"Lowe's","sector":"Retail","price":220.0,"vol":0.007,"div":1.20,"desc":"Home-improvement retail stores.","unlock_level":7,"unlock_worth":2700},
    {"ticker":"TJX","name":"TJX Companies","sector":"Retail","price":112.0,"vol":0.006,"div":0.38,"desc":"Discount apparel and home retail.","unlock_level":6,"unlock_worth":2450},
    {"ticker":"MAR","name":"Marriott","sector":"Travel","price":245.0,"vol":0.009,"div":0.63,"desc":"Hotels and travel experiences.","unlock_level":7,"unlock_worth":2900},
    {"ticker":"DAL","name":"Delta Air Lines","sector":"Travel","price":52.0,"vol":0.011,"div":0.00,"desc":"Passenger airline and travel services.","unlock_level":7,"unlock_worth":2800},
    {"ticker":"BKNG","name":"Booking Holdings","sector":"Travel","price":4100.0,"vol":0.009,"div":0.00,"desc":"Online travel booking services.","unlock_level":10,"unlock_worth":4300},
    {"ticker":"EA","name":"Electronic Arts","sector":"Gaming","price":145.0,"vol":0.009,"div":0.19,"desc":"Video games and interactive entertainment.","unlock_level":7,"unlock_worth":2900},
    {"ticker":"TTWO","name":"Take-Two","sector":"Gaming","price":225.0,"vol":0.011,"div":0.00,"desc":"Interactive entertainment and games.","unlock_level":8,"unlock_worth":3200},
    {"ticker":"SONO","name":"Sonos","sector":"Electronics","price":16.0,"vol":0.014,"div":0.00,"desc":"Home audio products.","unlock_level":5,"unlock_worth":2100},
    {"ticker":"DELL","name":"Dell","sector":"Electronics","price":132.0,"vol":0.010,"div":0.49,"desc":"Computers, servers, and technology infrastructure.","unlock_level":7,"unlock_worth":2800},
    {"ticker":"ETSY","name":"Etsy","sector":"Retail","price":68.0,"vol":0.012,"div":0.00,"desc":"Marketplace for creative goods.","unlock_level":7,"unlock_worth":2800},
    {"ticker":"LVS","name":"Las Vegas Sands","sector":"Entertainment","price":43.0,"vol":0.010,"div":0.25,"desc":"Hotels, resorts, and entertainment.","unlock_level":8,"unlock_worth":3100},
    {"ticker":"YUM","name":"Yum! Brands","sector":"Restaurants","price":145.0,"vol":0.006,"div":0.67,"desc":"Restaurant brands including KFC and Taco Bell.","unlock_level":6,"unlock_worth":2450},
    {"ticker":"CMG","name":"Chipotle","sector":"Restaurants","price":3250.0,"vol":0.010,"div":0.00,"desc":"Fast-casual Mexican food restaurants.","unlock_level":9,"unlock_worth":3900},
    {"ticker":"CL","name":"Colgate-Palmolive","sector":"Consumer","price":94.0,"vol":0.004,"div":0.50,"desc":"Household and personal-care products.","unlock_level":6,"unlock_worth":2300},
    {"ticker":"PG","name":"Procter & Gamble","sector":"Consumer","price":170.0,"vol":0.004,"div":1.06,"desc":"Everyday household and personal-care brands.","unlock_level":6,"unlock_worth":2400},
    {"ticker":"SPGI","name":"S&P Global","sector":"Finance","price":510.0,"vol":0.006,"div":0.91,"desc":"Financial information and market data services.","unlock_level":8,"unlock_worth":3400},
    {"ticker":"SCHW","name":"Charles Schwab","sector":"Finance","price":76.0,"vol":0.007,"div":0.25,"desc":"Financial services and brokerage.","unlock_level":7,"unlock_worth":2800},
]
STOCKS.extend(MORE_STOCKS)

# Nintendo ADR is often NTDOY; keep a kid-friendly ticker without pretending it's live data.
for _s in STOCKS:
    if _s["name"] == "Nintendo":
        _s["ticker"] = "NTDOY"

# A made-up meme stock. Most of the time it is a sleepy penny stock; every so often a
# social-media hype bubble inflates it and then pops it (see HYPE BUBBLES).
STOCKS.append({"ticker": "MOON", "name": "MoonChat", "sector": "Social Media", "price": 8.0, "vol": 0.009, "div": 0.00,
               "desc": "A buzzy (made-up) social app. Watch what happens when the hype starts.",
               "unlock_level": 1, "unlock_worth": 0})

for s in STOCKS:
    s["prev_price"] = s["price"]
    s["open"] = s["price"]
    s["history"] = [s["price"]] * 8
    s["flash_time"] = 0
    s["flash_dir"] = None
    s["display_price"] = s["price"]
    s["trend"] = random.uniform(-0.0003, 0.0003)
    s["session_move"] = 0.0
    s["news_pressure"] = 0.0
    s["volatility_event_time"] = 0.0

NEWS_UP = [
    "just announced a revolutionary new product line!",
    "reported record-breaking sales numbers this quarter.",
    "expanded aggressively with major new stores worldwide.",
    "signed a massive partnership deal with a leading tech firm.",
    "received rave reviews and top ratings from industry analysts.",
]
NEWS_DOWN = [
    "missed quarterly targets due to unexpected supply issues.",
    "faced a temporary setback and product recall notice.",
    "experienced unexpected delivery delays on flagship items.",
    "is dealing with a significant rise in material costs.",
    "received mixed consumer reviews on its latest release.",
]

ACHIEVEMENTS = [
    {"id": "first_buy", "label": "First Trade", "desc": "Buy your first stock"},
    {"id": "first_duel", "label": "Gladiator", "desc": "Complete your first 1v1 Blitz Duel"},
    {"id": "duel_win", "label": "First win", "desc": "Win a 1v1 Blitz Duel against a rival"},
    {"id": "streak_3", "label": "Three in a row", "desc": "Achieve a 3-win duel streak"},
    {"id": "dividend_earned", "label": "Dividend Payday", "desc": "Collect your first dividend payment"},
    {"id": "diversify", "label": "Diversified", "desc": "Own 3 different stocks at once"},
    {"id": "profit_10", "label": "In the Green", "desc": "Reach $1,100 net worth"},
    {"id": "mogul", "label": "Market Mogul", "desc": "Reach $2,000 net worth"},
    {"id": "daily_challenge", "label": "Daily Learner", "desc": "Complete a daily challenge"},
    {"id": "scam_detective", "label": "Scam Detective", "desc": "Correctly identify a scam"},
    {"id": "scam_perfect", "label": "Perfect Case File", "desc": "Crack all 10 cases in one Scam Detective run"},
    {"id": "academy_5", "label": "Scholar", "desc": "Complete 5 Academy lessons"},
    {"id": "gym_first", "label": "Gym Rat", "desc": "Finish your first Trader Gym game"},
    {"id": "calibrated", "label": "Well Calibrated", "desc": "Reach 100 points in Call It"},
    {"id": "market_maker", "label": "Market Maker", "desc": "Finish a Market Maker round with a profit"},
    {"id": "size_wise", "label": "Size Wise", "desc": "Finish Bet Sizer ahead without ever going all-in"},
    {"id": "diamond_hands", "label": "Diamond Hands", "desc": "Match or beat buy-and-hold in a Time Machine crash"},
    {"id": "thesis_10", "label": "Know Your Why", "desc": "Log a reason on 10 trades"},
    {"id": "bubble_watch", "label": "Bubble Watcher", "desc": "See a hype bubble inflate and pop"},
]


# ----------------------------
# LEDGER 2.0 - EDUCATIONAL SYSTEMS
# ----------------------------
MARKET_REGIMES = [
    {"id":"sideways", "name":"Sideways", "icon":"↔", "desc":"Prices are moving in a fairly balanced range.", "drift":0.0, "vol_mult":1.0},
    {"id":"bull", "name":"Bull Run", "icon":"🐂", "desc":"A broad wave of optimism is pushing many sectors upward.", "drift":0.0012, "vol_mult":1.05},
    {"id":"bear", "name":"Bear Wave", "icon":"🐻", "desc":"A broad wave of caution is pushing many sectors downward.", "drift":-0.0012, "vol_mult":1.08},
    {"id":"storm", "name":"Volatility Storm", "icon":"⚡", "desc":"Bigger swings make the market more unpredictable.", "drift":0.0, "vol_mult":2.0},
    {"id":"tech", "name":"Tech Boom", "icon":"💻", "desc":"Technology companies are getting an extra simulated boost.", "drift":0.0008, "vol_mult":1.25},
    {"id":"recession", "name":"Recession Drill", "icon":"📉", "desc":"A simulated downturn affects many sectors at once.", "drift":-0.0018, "vol_mult":1.35},
]
SECTOR_IMPACT = {
    "Technology": 1.00, "Tech": 0.95, "Finance": 0.80, "Retail": 0.65,
    "Restaurants": 0.55, "Apparel": 0.50, "Entertainment": 0.45,
    "Electronics": 0.75, "Auto": 0.85, "Healthcare": 0.35,
    "Industrial": 0.80, "Travel": 0.75, "Gaming": 0.65, "Drinks": 0.35,
}
NEWS_EVENTS = [
    {"kind":"rate", "headline":"Central bank rate decision surprises the simulated market.", "direction":"down", "sectors":["Finance","Auto","Real Estate"], "impact":0.018, "lesson":"Interest rates can affect borrowing costs and different businesses in different ways."},
    {"kind":"tech", "headline":"A major breakthrough boosts the simulated technology sector.", "direction":"up", "sectors":["Technology","Tech","Electronics","Gaming"], "impact":0.025, "lesson":"One piece of news can affect an entire sector, not just one company."},
    {"kind":"travel", "headline":"Travel demand surges in the simulated economy.", "direction":"up", "sectors":["Travel","Entertainment","Restaurants"], "impact":0.022, "lesson":"Economic events can spill over into connected industries."},
    {"kind":"supply", "headline":"A supply-chain disruption creates a simulated industry shock.", "direction":"down", "sectors":["Auto","Industrial","Retail","Electronics"], "impact":0.022, "lesson":"Companies that depend on supplies can react when costs or deliveries change."},
    {"kind":"consumer", "headline":"Consumer confidence rises across the simulated economy.", "direction":"up", "sectors":["Retail","Apparel","Restaurants","Entertainment"], "impact":0.018, "lesson":"Consumer spending can influence businesses that sell goods and services."},
]


# Educational market events. These only affect the offline simulation; live quotes are never altered.
MARKET_EVENTS = [
    {"id":"volatility_up","title":"Volatility Spike","headline":"Uncertainty hits the simulated market — price swings are getting larger.","kind":"volatility","bias":0.0,"vol_mult":3.0,"duration":22.0,"lesson":"Higher volatility means larger price swings, not guaranteed gains or losses."},
    {"id":"volatility_down","title":"Calmer Market","headline":"Trading settles down and simulated price swings become smaller.","kind":"volatility","bias":0.0,"vol_mult":0.45,"duration":22.0,"lesson":"Low volatility means prices are moving less; it does not mean prices cannot fall."},
    {"id":"earnings_beat","title":"Earnings Beat","headline":"A simulated company reports stronger-than-expected earnings.","kind":"stock","bias":1,"vol_mult":1.35,"duration":10.0,"lesson":"Strong earnings can change expectations, but investors still consider what is already priced in."},
    {"id":"earnings_miss","title":"Earnings Miss","headline":"A simulated company reports weaker-than-expected earnings.","kind":"stock","bias":-1,"vol_mult":1.5,"duration":10.0,"lesson":"A disappointing report can pressure a stock, but the size of the reaction can vary."},
    {"id":"sector_boom","title":"Sector Boom","headline":"Demand accelerates across one simulated industry.","kind":"sector","bias":1,"vol_mult":1.5,"duration":15.0,"lesson":"A sector event can move several related companies at once."},
    {"id":"sector_slump","title":"Sector Slump","headline":"A simulated industry faces weaker demand.","kind":"sector","bias":-1,"vol_mult":1.5,"duration":15.0,"lesson":"Diversification matters because one industry can face problems while others do not."},
    {"id":"risk_on","title":"Risk-On Mood","headline":"Investor confidence rises across the simulated market.","kind":"market","bias":1,"vol_mult":1.25,"duration":14.0,"lesson":"Broad market sentiment can influence many assets, but not every stock reacts the same way."},
    {"id":"risk_off","title":"Risk-Off Mood","headline":"Investors become more cautious across the simulated market.","kind":"market","bias":-1,"vol_mult":1.35,"duration":14.0,"lesson":"When risk appetite falls, many assets can come under pressure at the same time."},
    {"id":"supply_shock","title":"Supply Shock","headline":"A simulated supply disruption raises costs for an industry.","kind":"sector","bias":-1,"vol_mult":2.0,"duration":12.0,"lesson":"Supply problems can hurt some businesses while creating opportunities for others."},
    {"id":"product_launch","title":"Product Launch","headline":"A simulated product launch creates fresh optimism around a company.","kind":"stock","bias":1,"vol_mult":1.8,"duration":9.0,"lesson":"Company-specific news can move one stock much more than the broader market."},
]

ACADEMY_UNITS = [
    # (title, tagline, color, lesson ids). Lessons unlock in order across the whole course.
    ("Money Basics", "Earn it, plan it, keep it", (52, 211, 153), ["needs", "budget", "saving", "interest", "debt"]),
    ("Stock Basics", "What you actually own", (139, 92, 246), ["stocks", "supply", "marketcap", "dividend", "earnings"]),
    ("Trading Skills", "How buying and selling works", (56, 189, 248), ["orders", "stoploss", "charts", "news", "fees"]),
    ("Smart Investing", "Pick with a plan", (251, 191, 36), ["pe", "diversify", "risk", "allocation", "etf"]),
    ("Growing Money", "Let time do the work", (251, 146, 60), ["index", "bonds", "compound", "inflation", "dca"]),
    ("Investor Mindset", "Beat your own brain", (244, 114, 182), ["feargreed", "lossaversion", "bubbles", "timeinmarket", "goals"]),
    ("Think Like a Quant", "Numbers over hunches", (34, 211, 238), ["ev", "volatility", "spread", "sizing", "calibration"]),
]

# Each lesson: title, icon, three learn cards (idea, example, tip) and a three-question quiz.
# Quiz entries are (question, [right answer first, then two wrong ones], why). Choices get shuffled on screen.
LESSONS = {
    "needs": {
        "title": "Needs vs. wants", "glyph": "cart",
        "idea": "Needs are things you must have, like food, a home and school supplies. Wants are nice extras, like new sneakers or game skins.",
        "example": "You have $50. Lunch for the week is a need. A $50 game skin is a want. Covering needs first keeps you out of trouble.",
        "tip": "Before buying something, wait one day. If you still want it tomorrow, it might be worth it. Often you won't.",
        "quiz": [
            ("Which of these is a need?", ["Food for the week", "The newest phone", "A concert ticket"],
             "Needs keep you healthy and safe. Everything else is a want, even if it's fun."),
            ("Why cover needs before wants?", ["So the important stuff is always paid for", "Wants are always a waste", "Needs get cheaper later"],
             "Wants aren't bad. They just come after the things you can't skip."),
            ("What is the \"wait a day\" rule for?", ["Avoiding impulse buys", "Getting a discount", "Making prices drop"],
             "A little time lets the excitement fade so you can decide calmly."),
        ],
    },
    "budget": {
        "title": "Making a budget", "glyph": "pie",
        "idea": "A budget is a plan for your money before you spend it. You decide how much goes to needs, wants and savings.",
        "example": "The 50/30/20 plan: from $100, put $50 toward needs, $30 toward wants and $20 into savings.",
        "tip": "Write down everything you spend for one week. Most people are surprised where their money really goes.",
        "quiz": [
            ("What is a budget?", ["A plan for your money before you spend it", "A list of things you already bought", "A type of bank account"],
             "A budget tells your money where to go instead of wondering where it went."),
            ("With the 50/30/20 plan and $200, how much goes to savings?", ["$40", "$20", "$100"],
             "20% of $200 is $40."),
            ("What's the best first step to build a budget?", ["Track what you spend now", "Buy a budgeting app", "Stop spending on everything"],
             "You can't plan well until you know your real habits."),
        ],
    },
    "saving": {
        "title": "Pay yourself first", "glyph": "coin",
        "idea": "Paying yourself first means you put money into savings as soon as you get it, before spending on anything else.",
        "example": "You earn $40 mowing lawns. You move $10 into savings right away, then spend from the $30 left.",
        "tip": "An emergency fund is savings for surprises, like a broken phone. It stops one bad day from wrecking your plans.",
        "quiz": [
            ("What does \"pay yourself first\" mean?", ["Save before you spend", "Buy yourself a treat first", "Pay your friends back first"],
             "Saving first makes it automatic, so it doesn't depend on leftovers."),
            ("What is an emergency fund for?", ["Unexpected costs", "Buying stocks on sale", "Weekend fun"],
             "It's a cushion for surprises so you don't have to borrow."),
            ("Why save first instead of saving what's left?", ["There's often nothing left", "Banks require it", "It earns double interest"],
             "Spending tends to grow to use up whatever money is around."),
        ],
    },
    "interest": {
        "title": "How interest works", "glyph": "percent",
        "idea": "Interest is the price of using money. When you save, the bank pays you interest. When you borrow, you pay interest.",
        "example": "Put $100 in a savings account paying 4% a year and you earn $4 in a year without doing anything.",
        "tip": "Always compare the interest rate. A few percent can mean a big difference over many years.",
        "quiz": [
            ("You save $200 at 5% a year. How much interest after one year?", ["$10", "$5", "$100"],
             "5% of $200 is $10."),
            ("When you borrow money, interest is:", ["What you pay for borrowing", "A free bonus", "A tax on savings"],
             "Borrowing costs money, and interest is that cost."),
            ("Which savings account is better if everything else is equal?", ["The one paying 4%", "The one paying 1%", "They are the same"],
             "A higher rate means your money grows faster."),
        ],
    },
    "debt": {
        "title": "Borrowing & debt", "glyph": "scroll",
        "idea": "Debt is money you owe. It can help with big things like school or a home, but interest makes everything you borrow cost more.",
        "example": "Put a $500 purchase on a card charging 24% a year and only pay the minimum, and it can take years and cost hundreds extra.",
        "tip": "If you use a credit card someday, pay the full balance every month. Then you pay no interest at all.",
        "quiz": [
            ("Why does borrowing make things cost more?", ["You pay interest on top", "Stores charge borrowers more", "Loans are taxed twice"],
             "Interest is added to what you owe, so the total grows."),
            ("How do you avoid credit card interest?", ["Pay the full balance each month", "Only pay the minimum", "Use two cards"],
             "Paying in full means there's no leftover balance to charge interest on."),
            ("Which is usually the smartest reason to borrow?", ["Something that builds your future, like school", "Concert tickets", "A new game skin"],
             "Debt makes more sense for things that can pay you back over time."),
        ],
    },
    "stocks": {
        "title": "What is a stock?", "glyph": "chart",
        "idea": "A stock is a tiny piece of ownership in a company. If the company does well, your piece can become worth more.",
        "example": "A company is split into 1,000 shares. Own 10 of them and you own 1% of the company.",
        "tip": "Owning a stock means owning a business. Ask yourself: would I want to own this company for years?",
        "quiz": [
            ("If you buy a share of a company, you own:", ["A small piece of the company", "A guaranteed profit", "A loan to the company"],
             "A share is a slice of ownership, and its value can go up or down."),
            ("A company has 100 shares. You own 5. What percent do you own?", ["5%", "50%", "0.5%"],
             "5 out of 100 is 5%."),
            ("Can a stock lose value?", ["Yes, prices can go down", "No, stocks only go up", "Only on weekends"],
             "Stock prices move both ways. That's the risk of owning them."),
        ],
    },
    "supply": {
        "title": "Supply & demand", "glyph": "arrows",
        "idea": "Prices move when buyers and sellers disagree. More buyers than sellers can push a price up. More sellers can push it down.",
        "example": "Concert tickets: when everyone wants the same few seats, prices jump. Stocks can work the same way.",
        "tip": "A price going up doesn't prove a company is great. It only shows more people wanted to buy right then.",
        "quiz": [
            ("What happens when many more people want to buy than sell?", ["The price tends to rise", "The price must fall", "Nothing changes"],
             "Buyers compete for limited shares, so they pay more."),
            ("Lots of owners rush to sell at once. The price will likely:", ["Drop", "Rise", "Freeze forever"],
             "When sellers outnumber buyers, prices fall until buyers show up."),
            ("A stock rose 10% today. That proves:", ["More people wanted to buy today", "The company is perfect", "It will rise tomorrow"],
             "Price moves show demand right now, not the future."),
        ],
    },
    "marketcap": {
        "title": "Market capitalization", "glyph": "columns",
        "idea": "Market cap is the total value of a company's shares: share price times the number of shares.",
        "example": "A $10 stock with 1 billion shares is worth $10 billion. A $500 stock with 10 million shares is worth only $5 billion.",
        "tip": "A high share price doesn't mean a big company. Always look at market cap to compare sizes.",
        "quiz": [
            ("Market cap equals:", ["Share price times number of shares", "Share price divided by profit", "Number of employees"],
             "Multiply what one share costs by how many shares exist."),
            ("A $20 stock has 5 million shares. What is its market cap?", ["$100 million", "$25 million", "$4 million"],
             "20 x 5 million = 100 million."),
            ("Stock A costs $500, stock B costs $20. Which company is bigger?", ["You can't tell without share counts", "Stock A", "Stock B"],
             "Price alone says nothing about size. You need the number of shares too."),
        ],
    },
    "dividend": {
        "title": "Dividends", "glyph": "coin",
        "idea": "A dividend is cash some companies pay to their shareholders, usually from their profits.",
        "example": "Own 10 shares of a stock paying $0.50 per share each quarter? That's $5 every three months.",
        "tip": "Dividends aren't guaranteed. A company can cut them when times get tough.",
        "quiz": [
            ("What is a dividend?", ["Cash a company pays its shareholders", "A fee for trading", "A guaranteed price jump"],
             "It's a share of profits sent to owners."),
            ("You own 20 shares. The dividend is $1 per share. You receive:", ["$20", "$1", "$2"],
             "20 shares x $1 = $20."),
            ("Are dividends guaranteed?", ["No, companies can cut them", "Yes, by law", "Only for big companies"],
             "Companies decide each time whether to pay."),
        ],
    },
    "earnings": {
        "title": "Earnings & revenue", "glyph": "bars",
        "idea": "Revenue is all the money a business brings in. Profit, or earnings, is what's left after paying all the costs.",
        "example": "A lemonade stand sells $100 of lemonade (revenue) but spends $70 on supplies. Profit: $30.",
        "tip": "Growing revenue with no profit can still be a problem. Look at both numbers together.",
        "quiz": [
            ("Revenue is:", ["All the money a business brings in", "Money left after costs", "The stock price"],
             "Revenue is the top line, before any costs."),
            ("Revenue $500, costs $350. What is the profit?", ["$150", "$850", "$350"],
             "500 - 350 = 150."),
            ("A company's revenue doubled but it still loses money. This means:", ["Its costs are too high", "It is very profitable", "Its stock must rise"],
             "Profit depends on costs too, not just sales."),
        ],
    },
    "orders": {
        "title": "Market & limit orders", "glyph": "arrows",
        "idea": "A market order buys or sells right now at the current price. A limit order only trades at a price you choose, or better.",
        "example": "A stock is $52. A market order buys at about $52 now. A limit order at $50 waits and only buys if it drops to $50.",
        "tip": "Market orders are fast. Limit orders give you control, but they might never fill if the price never gets there.",
        "quiz": [
            ("Which order buys right away at the current price?", ["Market order", "Limit order", "Stop order"],
             "Market orders trade immediately at whatever the price is."),
            ("You set a limit order to buy at $40. The stock stays at $45. What happens?", ["Your order doesn't fill", "You buy at $45", "You buy at $40 anyway"],
             "A limit order only trades at your price or better."),
            ("What's the main benefit of a limit order?", ["Control over the price you pay", "It's always faster", "It's guaranteed to fill"],
             "You choose the price, but the trade might not happen."),
        ],
    },
    "stoploss": {
        "title": "Stop-loss & take-profit", "glyph": "shield",
        "idea": "A stop-loss sells automatically if a price falls to a level you pick. A take-profit sells automatically when it rises to your target.",
        "example": "You buy at $100 and set a stop-loss at $90. If the price slides to $90, you sell and limit your loss to about 10%.",
        "tip": "Decide your exit before you buy. It's much harder to think clearly once you're losing money.",
        "quiz": [
            ("A stop-loss is used to:", ["Limit how much you can lose", "Guarantee a profit", "Buy more when prices fall"],
             "It gets you out before a small loss becomes a big one."),
            ("You buy at $50 with a take-profit at $60. The price hits $60. What happens?", ["You sell and lock in the gain", "You buy more", "Nothing"],
             "Take-profit sells when your target is reached."),
            ("When is the best time to plan your exit?", ["Before you buy", "After it drops 50%", "Never, just hope"],
             "Planning ahead keeps emotions out of the decision."),
        ],
    },
    "charts": {
        "title": "Reading a price chart", "glyph": "chart",
        "idea": "A price chart shows how a stock's price changed over time. Up and to the right means it rose, down means it fell.",
        "example": "A 1-day chart can look scary with sharp drops, while the 1-year chart of the same stock shows a steady climb.",
        "tip": "Always check more than one time range. Short charts show noise, longer charts show the trend.",
        "quiz": [
            ("A chart line going up and to the right means:", ["The price rose over that time", "The company is broke", "The price will keep rising"],
             "Charts show the past, not a promise about the future."),
            ("Why look at a longer time range?", ["To see the bigger trend", "Short charts are fake", "Longer charts are cheaper"],
             "Daily wiggles can hide the real direction."),
            ("A stock dropped 3% today but is up 40% this year. The trend this year is:", ["Up", "Down", "Flat"],
             "One bad day doesn't erase a year of gains."),
        ],
    },
    "news": {
        "title": "News moves prices", "glyph": "news",
        "idea": "Prices react to news about a company, its industry or the economy. Good surprises can lift a price and bad surprises can sink it.",
        "example": "A company announces record sales and its stock jumps 8% in minutes. A product recall can do the opposite.",
        "tip": "By the time news is everywhere, the price has usually already moved. Chasing headlines is risky.",
        "quiz": [
            ("A company reports much better sales than expected. Its stock will likely:", ["Rise", "Fall", "Stop trading"],
             "Good surprises usually push prices up."),
            ("Why is chasing hot headlines risky?", ["The price has often already moved", "News is always fake", "It's against the rules"],
             "Markets react fast, so late buyers often pay the highest price."),
            ("News about an entire industry can move:", ["Many stocks at once", "Only one stock", "No stocks at all"],
             "Industry news affects every company in that sector."),
        ],
    },
    "fees": {
        "title": "Fees add up", "glyph": "coin",
        "idea": "Fees are costs you pay to invest, like trading fees or yearly fund fees. Small fees quietly eat into your returns every year.",
        "example": "A 1% yearly fee on $10,000 costs $100 this year, and more every year as your money grows.",
        "tip": "Trading a lot means paying fees and spreads a lot. Fewer, smarter trades often win.",
        "quiz": [
            ("A fund charges 0.5% a year. On $1,000, the yearly fee is:", ["$5", "$50", "$0.50"],
             "0.5% of $1,000 is $5."),
            ("Why do small fees matter over time?", ["They are taken every year from a growing amount", "They double each day", "They don't matter"],
             "Fees compound against you, just like returns compound for you."),
            ("Which usually costs more in fees?", ["Trading every day", "Buying and holding", "Doing nothing"],
             "Each trade can carry costs, so frequent trading adds up."),
        ],
    },
    "pe": {
        "title": "P/E ratio", "glyph": "percent",
        "idea": "The price-to-earnings ratio compares a stock's price to the profit per share. It shows how much investors pay for each $1 of profit.",
        "example": "A $50 stock that earns $5 per share has a P/E of 10. You're paying $10 for every $1 of yearly profit.",
        "tip": "A high P/E means people expect big growth. If that growth doesn't happen, the price can fall hard.",
        "quiz": [
            ("A $60 stock earns $3 per share. Its P/E is:", ["20", "3", "180"],
             "60 / 3 = 20."),
            ("A very high P/E usually means investors expect:", ["Strong future growth", "The company to shut down", "No change at all"],
             "People pay more today because they hope profits grow."),
            ("Is P/E the only thing to check?", ["No, it's one piece of the picture", "Yes, it tells you everything", "Only for banks"],
             "Use it with other info like growth, debt and the business itself."),
        ],
    },
    "diversify": {
        "title": "Diversification", "glyph": "pie",
        "idea": "Diversifying means spreading your money across different companies and industries, so one bad pick can't sink everything.",
        "example": "Don't put all your eggs in one basket. Drop one basket and you still have the others.",
        "tip": "Owning five tech stocks isn't very diversified. Spread across different sectors too.",
        "quiz": [
            ("Why diversify?", ["So one bad pick can't sink everything", "To guarantee no losses", "To make every stock move together"],
             "It lowers the damage any single holding can do."),
            ("Which portfolio is more diversified?", ["Stocks from tech, food, health and energy", "Five different tech stocks", "One stock you love"],
             "Different industries react differently to the same news."),
            ("Does diversification remove all risk?", ["No, it reduces some risk", "Yes, completely", "It adds risk"],
             "The whole market can still fall together."),
        ],
    },
    "risk": {
        "title": "Risk & reward", "glyph": "bolt",
        "idea": "Investments that can grow a lot usually can also fall a lot. Higher possible reward almost always comes with higher risk.",
        "example": "A roller-coaster stock can climb 30% in a month, but it can drop just as fast.",
        "tip": "Only take risks you could live with if things go wrong. Never risk money you'll need soon.",
        "quiz": [
            ("Higher possible reward usually comes with:", ["Higher risk", "No risk", "Guaranteed profit"],
             "Big upside and big downside tend to travel together."),
            ("Money you need next month is best kept:", ["Somewhere safe, like savings", "In a wild stock", "In a new crypto coin"],
             "Short-term money shouldn't be exposed to big swings."),
            ("Someone promises high returns with zero risk. This is:", ["A red flag", "A great deal", "Normal investing"],
             "Real investments with high returns always carry risk."),
        ],
    },
    "allocation": {
        "title": "Portfolio allocation", "glyph": "pie",
        "idea": "Allocation is how you split your money between different kinds of investments, like stocks, bonds and cash.",
        "example": "Splitting $100 into $60 stocks, $30 bonds and $10 cash is one kind of allocation.",
        "tip": "Check your allocation now and then. A stock that grew a lot can quietly become too big a part of your portfolio.",
        "quiz": [
            ("Allocation means:", ["How your money is split across investments", "How fast you trade", "Which app you use"],
             "It's the mix of what you own."),
            ("One stock grows to 70% of your portfolio. That's:", ["A concentration risk", "Perfect diversification", "A guaranteed win"],
             "If that one stock falls, most of your money falls with it."),
            ("$50 stocks, $30 bonds, $20 cash. What percent is in bonds?", ["30%", "50%", "20%"],
             "$30 out of $100 is 30%."),
        ],
    },
    "etf": {
        "title": "ETFs", "glyph": "layers",
        "idea": "An ETF is a fund that holds a basket of many investments. Buying one share gives you a small slice of all of them.",
        "example": "One ETF share can give you a slice of dozens of companies at once, like Ledger's LEDR fund.",
        "tip": "ETFs are an easy way to diversify, but check what's inside and what the yearly fee is.",
        "quiz": [
            ("An ETF is:", ["A fund holding a basket of investments", "A single company's stock", "A savings account"],
             "One ETF can hold many companies."),
            ("Why do many beginners like ETFs?", ["Built-in diversification", "They never go down", "They pay guaranteed interest"],
             "You get many companies in one purchase."),
            ("Before buying an ETF you should check:", ["What it holds and its fee", "Only its logo", "Nothing, they're all the same"],
             "ETFs differ a lot in what they own and what they cost."),
        ],
    },
    "index": {
        "title": "Index funds", "glyph": "layers",
        "idea": "An index fund copies a market index, like the 500 biggest US companies, instead of trying to pick winners one by one.",
        "example": "An S&P 500 index fund holds about 500 big US companies in one package.",
        "tip": "Most professional stock pickers fail to beat simple index funds over long periods, especially after fees.",
        "quiz": [
            ("An index fund tries to:", ["Match a market index", "Pick tomorrow's winner", "Guarantee profits"],
             "It simply follows the index, so it's easy and cheap."),
            ("An S&P 500 index fund holds about:", ["500 large US companies", "5 companies", "Only tech stocks"],
             "It copies the whole S&P 500 index."),
            ("Why are index funds popular for long-term investing?", ["Low fees and broad diversification", "They can't lose money", "They beat every stock"],
             "Cheap and spread out is a strong combination over time."),
        ],
    },
    "bonds": {
        "title": "Bonds", "glyph": "scroll",
        "idea": "A bond is a loan you give to a company or government. They pay you interest and give your money back at the end.",
        "example": "Lend $100 to a city, get paid interest each year, then get your $100 back later.",
        "tip": "Bonds usually swing less than stocks, which is why many portfolios mix the two.",
        "quiz": [
            ("When you buy a bond, you are:", ["Lending money", "Buying ownership", "Opening a bank account"],
             "A bond is a loan that pays you interest."),
            ("Compared to stocks, bonds usually:", ["Move up and down less", "Move much more", "Never pay anything"],
             "They're generally steadier, with smaller expected returns."),
            ("A $1,000 bond pays 3% a year. Yearly interest:", ["$30", "$3", "$300"],
             "3% of $1,000 is $30."),
        ],
    },
    "compound": {
        "title": "Compounding", "glyph": "curve",
        "idea": "Compounding means your gains start earning gains of their own. Over time, growth snowballs.",
        "example": "$100 growing 10% a year becomes about $259 after 10 years without adding a cent.",
        "tip": "Time is the secret ingredient. Starting early matters more than starting big.",
        "quiz": [
            ("Compounding means:", ["Your gains earn more gains", "You pay fees twice", "Prices stay the same"],
             "Growth builds on top of growth."),
            ("$100 grows 10% one year, then 10% again. You end with:", ["$121", "$120", "$110"],
             "$100 becomes $110, then $110 grows 10% to $121."),
            ("Why start investing early?", ["Compounding gets more years to work", "Prices are always lower for kids", "It's required"],
             "More years means a bigger snowball."),
        ],
    },
    "inflation": {
        "title": "Inflation", "glyph": "balloon",
        "idea": "Inflation means prices slowly rise over time. The same dollar buys a little less each year.",
        "example": "If a snack costs $1 today and prices rise 3% a year, it costs about $1.34 in 10 years.",
        "tip": "Cash hidden under a mattress loses buying power. Growing your money helps keep up with inflation.",
        "quiz": [
            ("Inflation means:", ["Prices rise over time", "All stocks rise", "Money is free"],
             "It's the general rise in the cost of things."),
            ("Your savings earn 1% while inflation is 3%. Your buying power:", ["Shrinks", "Grows", "Stays the same"],
             "Prices are rising faster than your money."),
            ("A $10 item with 5% inflation costs about how much next year?", ["$10.50", "$15", "$10.05"],
             "5% of $10 is $0.50."),
        ],
    },
    "dca": {
        "title": "Dollar-cost averaging", "glyph": "clock",
        "idea": "Dollar-cost averaging means investing the same amount on a regular schedule, whether prices are up or down.",
        "example": "Invest $25 every week. When prices are low, your $25 buys more shares. When they're high, it buys fewer.",
        "tip": "It takes the guessing out of timing. You can set it up in Ledger with Auto-invest.",
        "quiz": [
            ("Dollar-cost averaging means:", ["Investing the same amount on a schedule", "Buying only at the bottom", "Selling every week"],
             "Regular amounts, regular timing, no guessing."),
            ("When prices are low, your regular $25 buys:", ["More shares", "Fewer shares", "The same shares"],
             "The same money stretches further when prices drop."),
            ("What's a big benefit of this strategy?", ["You don't need to time the market", "It guarantees profit", "It avoids all fees"],
             "It removes the stress of guessing the perfect moment."),
        ],
    },
    "feargreed": {
        "title": "Fear & greed", "glyph": "heart",
        "idea": "Fear makes people sell when prices fall. Greed makes people buy when prices soar. Both push people to do the wrong thing at the wrong time.",
        "example": "When a stock doubles, everyone rushes in near the top. When it crashes, they panic-sell near the bottom.",
        "tip": "When you feel a strong urge to buy or sell right now, pause. Strong emotions are a signal to slow down.",
        "quiz": [
            ("Greed often makes people:", ["Buy after prices already soared", "Research carefully", "Sell at the top"],
             "Chasing big gains usually means buying late."),
            ("Fear during a crash often leads to:", ["Panic-selling near the bottom", "Buying the dip", "Calm planning"],
             "Selling in panic locks in losses."),
            ("You feel a sudden urge to go all-in. The smart move is:", ["Pause and think it through", "Act before it's too late", "Borrow more money"],
             "Big urgent feelings are exactly when mistakes happen."),
        ],
    },
    "lossaversion": {
        "title": "Loss aversion", "glyph": "scale",
        "idea": "Losing $10 feels about twice as bad as winning $10 feels good. That makes people hold losers too long and sell winners too early.",
        "example": "A stock you own drops 30%. You refuse to sell because selling would \"make the loss real\", even though its business is failing.",
        "tip": "Ask: if I didn't own this today, would I buy it at this price? If not, why am I holding it?",
        "quiz": [
            ("Loss aversion means:", ["Losses feel worse than equal gains feel good", "Losses don't matter", "You never lose money"],
             "Our brains weigh losses more heavily than wins."),
            ("A common mistake caused by loss aversion:", ["Holding a losing stock too long", "Diversifying too much", "Saving too early"],
             "People wait to \"get back to even\" instead of deciding fresh."),
            ("A helpful question for a losing stock:", ["Would I buy it today at this price?", "How do I hide this loss?", "Who can I blame?"],
             "It resets your thinking to what matters now."),
        ],
    },
    "bubbles": {
        "title": "Bubbles & FOMO", "glyph": "balloon",
        "idea": "A bubble is when prices rise far above what something is worth, mostly because people buy just because prices are rising.",
        "example": "In early 2021 some meme stocks jumped more than 1,000% in a few weeks, then fell over 80% from the peak.",
        "tip": "FOMO, the fear of missing out, pulls people in near the top. If everyone is bragging, be extra careful.",
        "quiz": [
            ("What usually drives a bubble?", ["People buying because prices keep rising", "Careful research on profits", "Steady dividends"],
             "Rising prices attract buyers, which pushes prices higher, until it stops."),
            ("FOMO stands for:", ["Fear of missing out", "Fund of many options", "Future of market orders"],
             "It's the urge to jump in because everyone else is."),
            ("How do bubbles usually end?", ["With a fast crash", "Prices rise forever", "Slowly and gently"],
             "When buyers run out, prices can fall very quickly."),
        ],
    },
    "timeinmarket": {
        "title": "Time in the market", "glyph": "curve",
        "idea": "Some of the market's best days come right after its worst ones. Staying invested usually beats jumping in and out.",
        "example": "In 2020 US stocks fell about 34% in one month, then hit a new record high about five months later.",
        "tip": "\"Time in the market beats timing the market\" is an old saying because it has been true so often.",
        "quiz": [
            ("Why is panic-selling in a crash risky?", ["You can miss the rebound", "Selling isn't allowed", "Markets never recover"],
             "The best days often come right after the worst ones."),
            ("\"Time in the market beats timing the market\" means:", ["Staying invested usually wins", "Trade every hour", "Only buy at midnight"],
             "Nobody can reliably guess the perfect moments."),
            ("After the 2020 crash, US stocks:", ["Hit new highs within months", "Never recovered", "Stayed flat for 10 years"],
             "People who held on recovered quickly."),
        ],
    },
    "goals": {
        "title": "Setting money goals", "glyph": "target",
        "idea": "A money goal gives your saving and investing a purpose, like a new laptop in six months or college in six years.",
        "example": "Want $300 headphones in 10 weeks? Save $30 a week and you'll get there on time.",
        "tip": "Short goals belong in safe savings. Long goals, many years away, can handle more ups and downs.",
        "quiz": [
            ("You want $200 in 10 weeks. How much to save each week?", ["$20", "$10", "$200"],
             "200 / 10 = 20."),
            ("Money for a goal next month should be kept:", ["Somewhere safe", "In a risky stock", "In a new crypto coin"],
             "Short goals can't wait out a crash."),
            ("Why set a money goal at all?", ["It gives saving a clear purpose", "Banks require it", "It raises interest rates"],
             "A clear target makes it easier to stick with a plan."),
        ],
    },
    "ev": {
        "title": "Expected value", "glyph": "percent",
        "idea": "Expected value is the average result if you repeated a bet many times. Good bets have a positive expected value.",
        "example": "Flip a coin: heads you win $2, tails you lose $1. You lose half the time, but you make $0.50 per flip on average.",
        "tip": "A single bet can still lose. Expected value is about what happens over many tries.",
        "quiz": [
            ("A game wins $10 half the time and loses $4 half the time. Expected value per play:", ["+$3", "+$10", "-$4"],
             "(10 x 0.5) + (-4 x 0.5) = 5 - 2 = +3."),
            ("A bet with positive expected value:", ["Wins on average over many tries", "Wins every single time", "Always loses"],
             "It can lose sometimes but comes out ahead over time."),
            ("Win $1 with 90% chance, lose $20 with 10% chance. Expected value:", ["-$1.10", "+$0.90", "+$1.00"],
             "0.9 x 1 = 0.90, minus 0.1 x 20 = 2.00, so -1.10."),
        ],
    },
    "volatility": {
        "title": "Volatility", "glyph": "bolt",
        "idea": "Volatility measures how much a price bounces around. Big bounces mean more risk, even if the average return is the same.",
        "example": "A stock that moves 1% a day is calm. One that moves 6% a day can erase a month of gains in an afternoon.",
        "tip": "A 50% drop needs a 100% gain to get back to even. Big swings are harder to recover from than they look.",
        "quiz": [
            ("Volatility measures:", ["How much a price swings", "How profitable a company is", "How many shares exist"],
             "It's the size of the ups and downs."),
            ("A stock drops 50%. What gain gets it back to where it started?", ["100%", "50%", "25%"],
             "Half of the price needs to double to get back."),
            ("Two stocks end the year even. One swung wildly. It was:", ["Riskier to hold", "Safer to hold", "Exactly the same"],
             "Bigger swings mean more chance of a bad exit."),
        ],
    },
    "spread": {
        "title": "Bid, ask & spread", "glyph": "arrows",
        "idea": "The bid is the most a buyer will pay. The ask is the least a seller will take. The gap between them is the spread.",
        "example": "A sneaker reseller buys pairs at $100 and sells them at $110. That $10 gap is their spread.",
        "tip": "Every time you buy at the ask and sell at the bid, you lose the spread. It's a hidden cost of trading a lot.",
        "quiz": [
            ("The bid is $9.95 and the ask is $10.05. The spread is:", ["$0.10", "$10.00", "$20.00"],
             "10.05 - 9.95 = 0.10."),
            ("When you buy right away, you usually pay the:", ["Ask", "Bid", "Average"],
             "Sellers are asking that price, so buyers pay it."),
            ("Why does trading often cost more than it looks?", ["You lose the spread each round trip", "Stocks charge rent", "Prices are fake"],
             "Buy at the ask, sell at the bid, and the gap is gone."),
        ],
    },
    "sizing": {
        "title": "Position sizing", "glyph": "pie",
        "idea": "Position sizing is deciding how much money to put into one trade. Even a great idea can hurt you if the bet is too big.",
        "example": "Risk 5% per trade and ten losses in a row still leave you about 60%. Risk 50% and two losses leave you 25%.",
        "tip": "Pros often risk only a small slice of their money on any one idea so they can survive being wrong.",
        "quiz": [
            ("Why do pros avoid betting everything on one trade?", ["One bad outcome could wipe them out", "Big bets are illegal", "Small bets always win"],
             "Staying in the game matters more than any single win."),
            ("You have $1,000 and risk 5% per trade. Max risk per trade:", ["$50", "$500", "$5"],
             "5% of $1,000 is $50."),
            ("Two 50% losses in a row turn $100 into:", ["$25", "$0", "$50"],
             "$100 becomes $50, then $50 becomes $25."),
        ],
    },
    "calibration": {
        "title": "Confidence & calibration", "glyph": "target",
        "idea": "Being calibrated means your confidence matches reality: things you call 80% likely should happen about 80% of the time.",
        "example": "Good weather forecasters are calibrated: when they say 70% chance of rain, it rains on about 70% of those days.",
        "tip": "Keep score of your predictions. It's the only way to learn whether your \"sure things\" really are.",
        "quiz": [
            ("You said \"90% sure\" on 10 predictions and only 5 came true. You were:", ["Overconfident", "Perfectly calibrated", "Underconfident"],
             "90% sure should mean about 9 out of 10 come true."),
            ("A calibrated forecaster says 70% chance of rain. It should rain:", ["About 70% of those days", "Every one of those days", "Never"],
             "Their numbers match what really happens."),
            ("What's the best way to improve calibration?", ["Track your predictions and results", "Always say 100%", "Never make predictions"],
             "Feedback shows you where your confidence is off."),
        ],
    },
}


ETFS = [
    {"ticker":"LEDR", "name":"Ledger 500 Fund", "sector":"ETF", "price":100.0, "vol":0.004, "div":0.30, "desc":"A simulated basket of large companies across sectors.", "unlock_level":1, "unlock_worth":0, "members":["AAPL","MSFT","AMZN","JPM","WMT","JNJ"]},
    {"ticker":"TECHX", "name":"Tech Explorer Fund", "sector":"ETF", "price":120.0, "vol":0.006, "div":0.15, "desc":"A simulated basket focused on technology and electronics.", "unlock_level":3, "unlock_worth":1400, "members":["AAPL","MSFT","GOOGL","META","NVDA","AMD"]},
    {"ticker":"EVERY", "name":"Everyday Brands Fund", "sector":"ETF", "price":90.0, "vol":0.0035, "div":0.40, "desc":"A simulated basket of consumer, retail, food, and apparel companies.", "unlock_level":5, "unlock_worth":1900, "members":["NKE","MCD","SBUX","KO","WMT","COST","TGT"]},
]
for e in ETFS:
    e["prev_price"] = e["price"]
    e["open"] = e["price"]
    e["history"] = [e["price"]] * 40
    e["flash_time"] = 0
    e["flash_dir"] = None
    e["display_price"] = e["price"]
    e["trend"] = random.uniform(-0.0003, 0.0003)
    e["session_move"] = 0.0
    e["news_pressure"] = 0.0

DAILY_CHALLENGES = [
    {"id":"three_trades", "title":"Market Explorer", "desc":"Complete 3 trades.", "goal":3, "reward":80},
    {"id":"two_sectors", "title":"Spread Out", "desc":"Own stocks from 2 different sectors at once.", "goal":2, "reward":90},
    {"id":"academy", "title":"Student Trader", "desc":"Finish 1 Academy lesson.", "goal":1, "reward":100},
    {"id":"dividend", "title":"Payday", "desc":"Collect a dividend payment.", "goal":1, "reward":90},
    {"id":"duel", "title":"Arena Practice", "desc":"Complete a duel.", "goal":1, "reward":100},
    {"id":"scam", "title":"Scam Detective", "desc":"Solve a Scam Detective case.", "goal":1, "reward":100},
    {"id":"gym", "title":"Gym Day", "desc":"Finish 2 Trader Gym games.", "goal":2, "reward":100},
]
SCAM_CASES = [
    # "flags" are exact phrases from the pitch. After the verdict they get highlighted:
    # red flags on scams, good signs on legit messages. "level" is 1 (easy), 2 (medium) or 3 (tricky).
    # Keep the first ten in this order: saves remember cracked cases by position.
    {"channel":"text", "sender":"CryptoKing", "handle":"+1 (555) 019-2231", "level":1,
     "pitch":"GUARANTEED 200% PROFIT in one week!! Send your money now before this deal is gone forever.",
     "answer":"scam",
     "flags":[("GUARANTEED 200% PROFIT", "Promises a guaranteed huge profit"),
              ("Send your money now", "Pushes you to pay right away"),
              ("gone forever", "Fake deadline to rush you")],
     "why":"Real investments can always lose value. Nobody can guarantee profits, and scammers rush you so you don't stop to think."},
    {"channel":"email", "sender":"Maple Foods Investor Relations", "handle":"ir@maplefoods.com", "level":2,
     "subject":"Our yearly report is ready",
     "pitch":"Our audited yearly results are now on our website. As always, remember that stock prices go up and down and you can lose money.",
     "answer":"legit",
     "flags":[("audited yearly results", "Checked by outside accountants"),
              ("on our website", "Info is public, not secret"),
              ("you can lose money", "Honest about the risk")],
     "why":"Public, checked information and an honest warning about risk are healthy signs. That doesn't make it a good investment, but it isn't a trick."},
    {"channel":"dm", "sender":"stock_guru_4life", "handle":"@stock_guru_4life", "level":1,
     "pitch":"ACT TODAY! I have a secret insider tip. No research needed, everyone in my group gets rich!",
     "answer":"scam",
     "flags":[("ACT TODAY!", "Urgency pressure"),
              ("secret insider tip", "Secret info is a big red flag"),
              ("No research needed", "Tells you not to check"),
              ("everyone in my group gets rich", "Promises easy riches")],
     "why":"Urgency, secrets and \"everyone gets rich\" are classic scam tricks. Real advice encourages you to research first."},
    {"channel":"email", "sender":"Sunrise Index Fund", "handle":"hello@sunrisefunds.com", "level":2,
     "subject":"Before you invest: fund facts",
     "pitch":"Here is our fact sheet: every company we hold, our 0.05% yearly fee, our goal, and the risks. Take your time and compare us to other funds.",
     "answer":"legit",
     "flags":[("every company we hold", "Shows exactly what you're buying"),
              ("0.05% yearly fee", "Fees are clear and upfront"),
              ("Take your time", "No pressure to rush"),
              ("compare us to other funds", "Invites you to shop around")],
     "why":"Clear facts, clear fees and no rush are what honest investments look like. You still decide if it fits you."},
    {"channel":"text", "sender":"Bank Security", "handle":"+1 (555) 404-8812", "level":1,
     "pitch":"URGENT: your account is locked! Reply with your password and PIN within 10 minutes to unlock it.",
     "answer":"scam",
     "flags":[("URGENT", "Panic word to rush you"),
              ("password and PIN", "Asks for your secret login info"),
              ("within 10 minutes", "Impossible deadline")],
     "why":"Real banks never ask for your password or PIN by text. If you're worried, call the number on your real bank card instead."},
    {"channel":"ad", "sender":"MoonCoin Rocket", "handle":"Sponsored", "level":1,
     "pitch":"Turn $10 into $10,000 by Friday! A famous celebrity already did it. Only 3 spots left, click now!",
     "answer":"scam",
     "flags":[("Turn $10 into $10,000", "Unrealistic returns"),
              ("famous celebrity", "Fake celebrity endorsement"),
              ("Only 3 spots left", "Fake scarcity")],
     "why":"Scammers love fake celebrity stories and \"only a few spots left\" to make you act before you think."},
    {"channel":"dm", "sender":"Coach Rivera", "handle":"@finclass_rivera", "level":1,
     "pitch":"Great question in class! There's no guaranteed way to get rich fast. Spreading money across many companies and waiting years is safer than chasing hot tips.",
     "answer":"legit",
     "flags":[("no guaranteed way to get rich fast", "Honest about uncertainty"),
              ("Spreading money across many companies", "Teaches diversification"),
              ("waiting years", "Long-term thinking")],
     "why":"Good advice is usually a little boring: be patient, spread your money out, and be suspicious of shortcuts."},
    {"channel":"email", "sender":"Prize Department", "handle":"winner@free-prize-now.biz", "level":1,
     "subject":"YOU WON $5,000!!!",
     "pitch":"Congratulations, you won $5,000! To get your prize, just pay a $50 processing fee with a gift card.",
     "answer":"scam",
     "flags":[("you won $5,000", "You can't win a contest you never entered"),
              ("pay a $50 processing fee", "Real prizes don't make you pay"),
              ("gift card", "Scammers ask for gift cards")],
     "why":"If you have to pay to get a prize, it isn't a prize. Gift cards are a favorite because the money can't be traced or returned."},
    {"channel":"ad", "sender":"BrightBank Savings", "handle":"Sponsored", "level":2,
     "pitch":"Open a savings account and earn 4% interest per year. Rates can change. Read the full terms before you sign up.",
     "answer":"legit",
     "flags":[("4% interest per year", "A normal, realistic rate"),
              ("Rates can change", "Tells you what could change"),
              ("Read the full terms", "Wants you to read the details")],
     "why":"A realistic number, a clear warning and an invitation to read the details all point to an honest offer."},
    {"channel":"dm", "sender":"Alex (new friend)", "handle":"@alex_trades_99", "level":2,
     "pitch":"I just met you but I really trust you. My trading app doubled my money. Send me your savings and I'll invest it for you. Don't tell your parents!",
     "answer":"scam",
     "flags":[("I just met you", "A stranger acting like a close friend"),
              ("Send me your savings", "Wants your money directly"),
              ("Don't tell your parents!", "Asks you to keep secrets")],
     "why":"When someone asks you to keep money secrets from trusted adults, that is one of the biggest red flags of all."},

    # ---- Scams ----
    {"channel":"text", "sender":"Parcel Delivery", "handle":"+1 (555) 301-7720", "level":2,
     "pitch":"Your package is on hold because of an unpaid $1.99 shipping fee. Pay now at parcel-redelivery-help.co to avoid it being returned.",
     "answer":"scam",
     "flags":[("unpaid $1.99 shipping fee", "Tiny fee to grab your card details"),
              ("parcel-redelivery-help.co", "Strange web address"),
              ("to avoid it being returned", "Pressure to act fast")],
     "why":"Delivery companies don't text random links asking for fees. Check tracking only in the official app or on the website you already use."},
    {"channel":"email", "sender":"Account Support", "handle":"support@appleid-verify.net", "level":2,
     "subject":"Your account has been suspended",
     "pitch":"We noticed unusual activity. Verify your identity within 24 hours or your account will be deleted. Click here and enter your password.",
     "answer":"scam",
     "flags":[("within 24 hours", "Scary deadline"),
              ("your account will be deleted", "Threat to make you panic"),
              ("enter your password", "Asks for your password")],
     "why":"Real companies don't threaten to delete your account by email. Open the app yourself to check instead of clicking a link."},
    {"channel":"game", "sender":"xX_ProGamer_Xx", "handle":"Level 88  ·  Guild chat", "level":1,
     "pitch":"Want FREE 10,000 gems? Just log in at free-gems-generator.io with your game username and password. Works 100%!",
     "answer":"scam",
     "flags":[("FREE 10,000 gems", "Too good to be true"),
              ("free-gems-generator.io", "Not the official game site"),
              ("username and password", "Wants your login")],
     "why":"Gem and coin \"generators\" are always fake. They exist to steal accounts, so never type your login anywhere but the real game."},
    {"channel":"post", "sender":"TechBillionaire Giveaway", "handle":"@techb1llionaire_real", "level":1,
     "pitch":"To celebrate, I'm giving back! Send any amount of crypto to my wallet and I'll instantly send back DOUBLE. Limited time only!",
     "answer":"scam",
     "flags":[("Send any amount of crypto", "Asks you to send money first"),
              ("send back DOUBLE", "Nobody doubles your money for free"),
              ("Limited time only!", "Rush tactic")],
     "why":"Rich people don't double random strangers' money. Look-alike accounts copy famous names to steal crypto that can never be recovered."},
    {"channel":"dm", "sender":"Maya", "handle":"@maya.invests", "level":3,
     "pitch":"Oops, wrong person! But you seem nice. My uncle works at a big bank and gives me private trading signals. Want me to show you how I made $4,000 this week?",
     "answer":"scam",
     "flags":[("wrong person", "A fake accident to start chatting"),
              ("private trading signals", "Secret info is a big red flag"),
              ("made $4,000 this week", "Bragging about fast profits")],
     "why":"Some scammers start a friendly chat by \"accident\", build trust for weeks, then pitch an investment. Strangers who talk money are a warning sign."},
    {"channel":"call", "sender":"Unknown caller", "handle":"Voicemail  ·  0:42", "level":1,
     "pitch":"This is Officer Grant from the tax office. You owe back taxes and will be arrested today unless you pay with gift cards. Do not hang up or tell anyone.",
     "answer":"scam",
     "flags":[("will be arrested today", "Scary threat"),
              ("pay with gift cards", "Governments never take gift cards"),
              ("Do not hang up or tell anyone", "Tries to keep you alone")],
     "why":"Government offices send letters, not threats by phone, and they never want gift cards. Hang up and tell a trusted adult."},
    {"channel":"popup", "sender":"Security Alert", "handle":"www.pc-fix-now.support", "level":1,
     "pitch":"WARNING! Your computer has 5 viruses! Call Tech Support now at 1-800-555-0199. Do not close this window or your files will be lost.",
     "answer":"scam",
     "flags":[("Your computer has 5 viruses!", "Websites can't scan your computer"),
              ("Call Tech Support now", "Real companies don't ask you to call from a pop-up"),
              ("Do not close this window", "Closing it is exactly what you should do")],
     "why":"Scary pop-ups are fake. Close the tab, and if the computer acts strange, ask a trusted adult to run real security software."},
    {"channel":"shop", "sender":"Chris P.", "handle":"Marketplace  ·  Joined 2 days ago", "level":2,
     "pitch":"I'll buy your bike for $300! I accidentally wrote the check for $800, so just send me back the extra $500 with a gift card.",
     "answer":"scam",
     "flags":[("check for $800", "The overpayment trick"),
              ("send me back the extra $500", "You lose real money when the check bounces"),
              ("with a gift card", "Money that can't be traced")],
     "why":"Fake checks can look real for days before they bounce. Never send money back to a buyer who \"overpaid\"."},
    {"channel":"email", "sender":"Crypto Recovery Experts", "handle":"help@get-your-crypto-back.com", "level":3,
     "subject":"We can get your money back",
     "pitch":"Lost money to a scam? Our hackers can recover 100% of it! Just pay a $200 upfront fee and we start today.",
     "answer":"scam",
     "flags":[("Our hackers", "Hiring hackers is illegal and fake"),
              ("recover 100%", "Promises the impossible"),
              ("$200 upfront fee", "Pay-first is a classic trap")],
     "why":"Recovery scams target people who were already scammed. Real help comes from police, your bank or trusted adults, and it's free."},
    {"channel":"ad", "sender":"AutoTrader AI Bot", "handle":"Sponsored", "level":2,
     "pitch":"Our AI trading robot never loses! Earn $500 a day on autopilot. Deposit $250 to start and withdraw anytime.",
     "answer":"scam",
     "flags":[("never loses!", "No strategy wins every time"),
              ("$500 a day on autopilot", "Unrealistic easy money"),
              ("Deposit $250 to start", "Wants your money first")],
     "why":"If a robot could really print money, nobody would sell it in an ad. \"Never loses\" is always a lie."},
    {"channel":"dm", "sender":"Wealth Circle", "handle":"@wealth.circle.club", "level":2,
     "pitch":"Join our club for $100 and earn 10% every week! You get bonus cash for every friend you bring in. The more you recruit, the richer you get.",
     "answer":"scam",
     "flags":[("10% every week", "Impossible steady returns"),
              ("bonus cash for every friend", "Paid to recruit, not to invest"),
              ("The more you recruit", "Pyramid scheme sign")],
     "why":"When money comes from new members instead of a real business, it's a pyramid scheme. It always collapses and most people lose."},
    {"channel":"text", "sender":"Unknown number", "handle":"+1 (555) 877-1043", "level":2,
     "pitch":"Hi it's Mom, I broke my phone so this is my new number. Send $200 to this account right now, I'll explain later. Don't call my old number.",
     "answer":"scam",
     "flags":[("this is my new number", "Anyone can claim to be family"),
              ("Send $200 to this account right now", "Urgent money request"),
              ("Don't call my old number", "Stops you from checking")],
     "why":"Always check by calling the person on the number you already know, or by asking another family member."},
    {"channel":"post", "sender":"PennyRocket Crew", "handle":"@pennyrocket_crew", "level":2,
     "pitch":"Everyone buy ZIPP stock at 3pm SHARP! We all pump it together, then sell at the top. Easy 500%! Don't miss the rocket.",
     "answer":"scam",
     "flags":[("We all pump it together", "A pump and dump, which is illegal"),
              ("sell at the top", "The organizers sell to you"),
              ("Easy 500%!", "Unrealistic promise")],
     "why":"In a pump and dump the organizers bought early. When they sell, the price crashes and late buyers are stuck with the losses."},
    {"channel":"email", "sender":"HR Team", "handle":"jobs.hiring.now@gmail.com", "level":2,
     "subject":"You're hired! $45 an hour from home",
     "pitch":"No interview needed! To start, buy a $300 work laptop from our partner store and we will pay you back in your first paycheck.",
     "answer":"scam",
     "flags":[("No interview needed!", "Real jobs check who you are"),
              ("buy a $300 work laptop", "Real employers don't make you pay"),
              ("we will pay you back", "They never will")],
     "why":"A job that asks you to pay before you start isn't a job. Real employers provide equipment and never charge you to work."},
    {"channel":"game", "sender":"Moderator_Official", "handle":"Server message", "level":2,
     "pitch":"Your account will be BANNED for cheating. To appeal, send us your login and the code we just texted you within 1 hour.",
     "answer":"scam",
     "flags":[("will be BANNED", "Scare tactic"),
              ("send us your login", "Real moderators never ask for your login"),
              ("the code we just texted you", "Sharing the code hands over your account"),
              ("within 1 hour", "Rush")],
     "why":"That texted code is the key to your account. Anyone asking for it is trying to steal it, even if their name says \"Official\"."},
    {"channel":"ad", "sender":"RichKid Academy", "handle":"Sponsored", "level":1,
     "pitch":"I quit school and made my first million at 17! Buy my $997 secret course today and you'll be rich too. Price doubles at midnight!",
     "answer":"scam",
     "flags":[("secret course", "Secrets are a red flag"),
              ("you'll be rich too", "Promises what nobody can promise"),
              ("Price doubles at midnight!", "Fake deadline")],
     "why":"Most \"get rich\" course sellers make their money from selling the course, not from the method. Real learning doesn't need a countdown."},
    {"channel":"text", "sender":"Bank Alert", "handle":"+1 (555) 212-0090", "level":3,
     "pitch":"Suspicious charge of $849.00 detected. If this wasn't you, log in at secure-banktrust-login.com to cancel it immediately.",
     "answer":"scam",
     "flags":[("secure-banktrust-login.com", "Look-alike link, not the bank's real site"),
              ("to cancel it immediately", "Panic push")],
     "why":"Real banks do send fraud alerts, which makes this tricky. The giveaway is the link. Open your bank's real app yourself instead."},
    {"channel":"dm", "sender":"Help4Kids Relief", "handle":"@help4kids_relief_2026", "level":2,
     "pitch":"Disaster just hit! Donate now by sending money to my personal account. Every second counts, no time to check our website.",
     "answer":"scam",
     "flags":[("my personal account", "Real charities use official accounts"),
              ("Every second counts", "Emotional pressure"),
              ("no time to check our website", "Tells you not to check")],
     "why":"Fake charities pop up after every disaster. Give through well-known charities, on their official website, with a parent's help."},
    {"channel":"email", "sender":"Estate Lawyer", "handle":"lawyer.estate@consultant.com", "level":1,
     "subject":"Inheritance of $4.5 million",
     "pitch":"A relative you never knew left you $4.5 million. Send your bank account number and a $500 legal fee so we can release the money.",
     "answer":"scam",
     "flags":[("A relative you never knew", "Surprise money from nowhere"),
              ("Send your bank account number", "Asks for private info"),
              ("$500 legal fee", "Pay-to-get trick")],
     "why":"Surprise fortunes from strangers are one of the oldest tricks. The \"fee\" is the scam, and the millions never exist."},
    {"channel":"shop", "sender":"Sam R.", "handle":"Marketplace  ·  No reviews", "level":1,
     "pitch":"Two front row tickets to the sold out show, only $40! I can only take payment by wire transfer or crypto. Decide in 10 min, lots of buyers.",
     "answer":"scam",
     "flags":[("only $40!", "Price too good to be true"),
              ("wire transfer or crypto", "Payments you can't get back"),
              ("Decide in 10 min", "Rush")],
     "why":"Sold out tickets for cheap, paid in a way you can't undo, is a classic fake. Buy tickets only from the official seller."},
    {"channel":"post", "sender":"MoonApe NFTs", "handle":"@moonape_nfts", "level":3,
     "pitch":"Congrats, you're on the list for our free NFT! Connect your wallet and enter your 12-word recovery phrase to claim it.",
     "answer":"scam",
     "flags":[("free NFT", "Free bait"),
              ("Connect your wallet", "Can let them drain your wallet"),
              ("12-word recovery phrase", "Never share it: it's the master key")],
     "why":"A recovery phrase is the master key to a crypto wallet. Anyone who asks for it wants to empty the wallet."},
    {"channel":"text", "sender":"City Parking", "handle":"+1 (555) 610-2231", "level":2,
     "pitch":"Final notice: unpaid parking ticket. Pay $25 today at cityparking-pay.xyz or your license will be suspended.",
     "answer":"scam",
     "flags":[("Final notice", "Scare tactic"),
              ("cityparking-pay.xyz", "Odd web address"),
              ("your license will be suspended", "Threat to rush you")],
     "why":"Cities send tickets by mail with official websites. A random text with a strange link and a threat is a scam."},
    {"channel":"dm", "sender":"Taylor", "handle":"@taylor_travels", "level":2,
     "pitch":"You're so cool, I feel like we've known each other forever! My card got frozen while traveling. Could you buy me a $100 gift card? I'll pay you back, promise.",
     "answer":"scam",
     "flags":[("known each other forever", "Fake closeness, fast"),
              ("buy me a $100 gift card", "Gift card request"),
              ("I'll pay you back, promise", "An empty promise")],
     "why":"Online friends who quickly ask for money or gift cards are almost always scammers. Real friends don't do that."},
    {"channel":"email", "sender":"Scholarship Board", "handle":"awards@national-scholars-fund.org", "level":2,
     "subject":"You've been selected!",
     "pitch":"You won a $10,000 scholarship you didn't apply for! Pay the $75 processing fee today to claim your award.",
     "answer":"scam",
     "flags":[("didn't apply for", "You can't win what you never entered"),
              ("$75 processing fee", "Real scholarships don't charge you")],
     "why":"Real scholarships never charge a fee to receive money. Ask a school counselor about any award you aren't sure of."},
    {"channel":"call", "sender":"Unknown caller", "handle":"Voicemail  ·  1:05", "level":2,
     "pitch":"This is Tech Support from your computer company. We detected hackers on your device. Please install RemoteHelp so we can control your computer and fix it.",
     "answer":"scam",
     "flags":[("We detected hackers on your device", "They can't see your device"),
              ("install RemoteHelp", "Remote apps give them full control"),
              ("control your computer", "Never let strangers take control")],
     "why":"Tech companies don't call you out of the blue. Letting a stranger control your computer lets them reach your accounts and money."},
    {"channel":"ad", "sender":"GlowCoin Presale", "handle":"Sponsored", "level":2,
     "pitch":"Get in before the listing! Early buyers are guaranteed 50x. Our team stays anonymous for privacy. Buy with any crypto now.",
     "answer":"scam",
     "flags":[("Get in before the listing!", "FOMO pressure"),
              ("guaranteed 50x", "Guarantees are fake"),
              ("team stays anonymous", "No one to hold responsible")],
     "why":"Many new coins are \"rug pulls\": the hidden team takes everyone's money and disappears. Anonymous plus guaranteed is a big red flag."},
    {"channel":"post", "sender":"StockSensei", "handle":"@stocksensei.signals", "level":2,
     "pitch":"Look at my screenshot, +$12,000 today! Join my VIP group for $49 a month and copy my trades. 100% win rate, zero risk.",
     "answer":"scam",
     "flags":[("my screenshot", "Screenshots are easy to fake"),
              ("100% win rate", "Nobody wins every time"),
              ("zero risk", "All investing has risk")],
     "why":"Profit screenshots take seconds to fake. Real investors lose sometimes, and anyone claiming zero risk is selling something."},
    {"channel":"game", "sender":"SkinTrader99", "handle":"Trade request", "level":1,
     "pitch":"I'll trade you my rare golden skin! You send your items first, then I'll send mine. Trust me, I have 5 stars.",
     "answer":"scam",
     "flags":[("rare golden skin", "Bait with a rare item"),
              ("You send your items first", "They'll just keep your items"),
              ("Trust me", "Asks for trust instead of a safe trade")],
     "why":"Only use the game's official trade window, where both sides lock in at once. \"You go first\" trades are how items get stolen."},
    {"channel":"email", "sender":"PayFlow Billing", "handle":"billing@payflow-invoices.info", "level":3,
     "subject":"Receipt: $499.99 charged",
     "pitch":"Thanks for buying a Gaming Laptop Pro. If you did not make this purchase, call us at 1-800-555-0144 to get a refund.",
     "answer":"scam",
     "flags":[("If you did not make this purchase", "Scares you into reacting"),
              ("call us at 1-800-555-0144", "The number goes to scammers")],
     "why":"Fake receipts trick you into calling. Check your real account in the official app. If the charge isn't there, it's fake."},
    {"channel":"dm", "sender":"Gamerz Giveaways", "handle":"@gamerz.giveaway.official", "level":1,
     "pitch":"Congrats!! You were picked as our giveaway winner! DM us your full name, home address and card number to receive your prize.",
     "answer":"scam",
     "flags":[("You were picked", "You never entered"),
              ("home address", "Private info"),
              ("card number", "Prizes never need your card")],
     "why":"Real giveaways never need your card number. Check the account carefully: scammers copy real names and add words like \"official\"."},
    {"channel":"email", "sender":"StreamMax", "handle":"no-reply@streamrnax.com", "level":3,
     "subject":"Payment failed",
     "pitch":"Your membership is on hold. Update your payment details within 48 hours to keep watching: streamrnax.com/update",
     "answer":"scam",
     "flags":[("streamrnax.com", "Look closely: \"rn\" pretends to be \"m\""),
              ("within 48 hours", "Deadline pressure"),
              ("Update your payment details", "Wants your card info")],
     "why":"Look-alike web addresses swap letters to fool quick readers. Go to the real site by typing it yourself, never through the email."},

    # ---- Legit ----
    {"channel":"text", "sender":"Ledger Bank", "handle":"Short code 72641", "level":2,
     "pitch":"Your sign-in code is 482913. You asked for this code just now. Never share this code with anyone. We will never call or text to ask for it.",
     "answer":"legit",
     "flags":[("You asked for this code just now", "You started this yourself"),
              ("Never share this code", "Warns you to keep it private"),
              ("We will never call or text to ask for it", "Tells you how real staff behave")],
     "why":"This is a normal code you asked for. Type it only into the real app yourself, and never read it out to anyone."},
    {"channel":"app", "sender":"Ledger Bank app", "handle":"Notification", "level":3,
     "pitch":"New sign-in from an iPad in Chicago. If this was you, no action needed. If not, open the Ledger Bank app and tap Secure my account.",
     "answer":"legit",
     "flags":[("no action needed", "No pressure"),
              ("open the Ledger Bank app", "Sends you to the real app, not a link")],
     "why":"Real alerts point you back to the official app instead of a link, and they don't ask for passwords or codes."},
    {"channel":"email", "sender":"Maple Middle School", "handle":"office@maplemiddle.k12.us", "level":1,
     "subject":"Field trip form due Friday",
     "pitch":"Reminder: the museum trip permission slip is due Friday. Forms are in the student portal. Questions? Call the front office.",
     "answer":"legit",
     "flags":[("due Friday", "A normal deadline, not panic"),
              ("student portal", "Uses the official school site"),
              ("Call the front office", "Easy to double-check")],
     "why":"It asks for nothing risky, uses places you already know, and gives you an easy way to check."},
    {"channel":"ad", "sender":"Parkside Credit Union", "handle":"Sponsored", "level":1,
     "pitch":"Teen checking account with no monthly fees. A parent or guardian must co-sign. Visit any branch or our website to learn more.",
     "answer":"legit",
     "flags":[("no monthly fees", "Clear about costs"),
              ("parent or guardian must co-sign", "Involves trusted adults"),
              ("Visit any branch", "A real place you can visit")],
     "why":"Honest offers welcome parents, explain costs clearly and let you visit or research before deciding."},
    {"channel":"dm", "sender":"Grandpa Joe", "handle":"@joe.walters", "level":1,
     "pitch":"Proud of you for saving your birthday money! If you want, we can look at a savings account together this weekend. No rush.",
     "answer":"legit",
     "flags":[("look at a savings account together", "A trusted adult helping"),
              ("No rush", "No pressure")],
     "why":"Someone you know, offering help in person, with zero pressure. That's what good money advice feels like."},
    {"channel":"email", "sender":"Evergreen Brokerage", "handle":"statements@evergreenbrokerage.com", "level":2,
     "subject":"Your monthly statement is ready",
     "pitch":"Your September statement is available. For your security, we don't include links. Sign in through the app or website you normally use.",
     "answer":"legit",
     "flags":[("we don't include links", "Avoids risky links"),
              ("the app or website you normally use", "You go to the real site yourself")],
     "why":"Careful companies send you to the site you already trust instead of asking you to click something."},
    {"channel":"popup", "sender":"Cookie settings", "handle":"www.maplefoods.com", "level":2,
     "pitch":"We use cookies to improve your experience. You can accept, decline, or change your settings at any time.",
     "answer":"legit",
     "flags":[("accept, decline", "You get a real choice"),
              ("change your settings at any time", "Nothing is forced")],
     "why":"Not every pop-up is a trap. This one gives you a real choice, has no scary warnings and asks for no money or info."},
    {"channel":"call", "sender":"Dr. Patel's Office", "handle":"Voicemail  ·  0:21", "level":1,
     "pitch":"Hi, this is Dr. Patel's office confirming your checkup on Tuesday at 4pm. No need to call back unless you need to reschedule.",
     "answer":"legit",
     "flags":[("confirming your checkup", "Matches plans you already have"),
              ("No need to call back", "Doesn't ask you for anything")],
     "why":"It matches something you already know about and asks for nothing. That's a normal reminder."},
    {"channel":"post", "sender":"City Library", "handle":"@citylibrary", "level":1,
     "pitch":"Free money class for teens this Saturday at 2pm! Learn budgeting basics. No sign-up fee. Bring a notebook, and a parent if you like.",
     "answer":"legit",
     "flags":[("Learn budgeting basics", "Education, not a sales pitch"),
              ("No sign-up fee", "Nothing to pay"),
              ("a parent if you like", "Welcomes trusted adults")],
     "why":"A free class at a public place that welcomes parents is a great way to learn. Nobody is selling anything."},
    {"channel":"shop", "sender":"Dana K.", "handle":"Marketplace  ·  Member since 2019", "level":2,
     "pitch":"Hi! Is the bike still available? I can meet at the police station parking lot on Saturday and pay in cash when I see it.",
     "answer":"legit",
     "flags":[("meet at the police station", "A safe public meeting spot"),
              ("pay in cash when I see it", "Pays when she gets it, no tricks")],
     "why":"Meeting in a safe public place and paying on the spot is how honest buyers do it. Still bring an adult along."},
    {"channel":"game", "sender":"GameStudio", "handle":"Official news", "level":1,
     "pitch":"Double XP weekend starts Friday! It turns on automatically for everyone. We will never ask for your password.",
     "answer":"legit",
     "flags":[("turns on automatically", "Nothing to click or type"),
              ("We will never ask for your password", "An honest safety reminder")],
     "why":"Real game news doesn't need anything from you. When nothing is asked for, there's nothing to steal."},
    {"channel":"app", "sender":"Ledger", "handle":"Price alert", "level":2,
     "pitch":"Maple Foods moved up 3% today. Alerts are for info only, not advice. Open the app to see the chart.",
     "answer":"legit",
     "flags":[("for info only, not advice", "Honest about what it is"),
              ("Open the app", "Stays inside the real app")],
     "why":"A simple alert you set up yourself, with an honest note that it isn't advice. No money, links or secrets involved."},
    {"channel":"email", "sender":"River Books", "handle":"orders@riverbooks.com", "level":2,
     "subject":"Your order has shipped",
     "pitch":"Your book, Money Basics for Teens, is on its way. Track it anytime from Your Orders on our website. No payment needed.",
     "answer":"legit",
     "flags":[("Your book, Money Basics for Teens", "Matches something you really ordered"),
              ("Your Orders on our website", "Check on the site you already use"),
              ("No payment needed", "Doesn't ask for money")],
     "why":"It matches a real order and sends you to the store's own website. If you didn't order anything, that would be a red flag."},
    {"channel":"text", "sender":"Coach Kim", "handle":"Team contact", "level":1,
     "pitch":"Soccer practice moved to 5pm today because of the rain. See the team calendar for details.",
     "answer":"legit",
     "flags":[("moved to 5pm", "Normal info, no money asked"),
              ("See the team calendar", "Points to a place you already trust")],
     "why":"A saved contact sharing normal plans and pointing to something you already use. Nothing to worry about."},
    {"channel":"ad", "sender":"Horizon Invest", "handle":"Sponsored", "level":3,
     "pitch":"Build a simple, diversified portfolio. Past results don't guarantee future returns. Fees: 0.25% per year. Under 18? Ask a parent about a custodial account.",
     "answer":"legit",
     "flags":[("diversified portfolio", "Spreads out risk"),
              ("Past results don't guarantee future returns", "Honest risk warning"),
              ("0.25% per year", "Clear fees"),
              ("Ask a parent", "Involves trusted adults")],
     "why":"Honest investment ads warn about risk, show fees and follow the rules for young investors. Deciding is still up to you and your family."},
    {"channel":"dm", "sender":"Priya (classmate)", "handle":"@priya.k", "level":1,
     "pitch":"Hey! Our class is doing the stock market game for fun. Everyone starts with fake money. Want to join my team? Mr. Lee set it up.",
     "answer":"legit",
     "flags":[("fake money", "No real money involved"),
              ("Mr. Lee set it up", "A teacher is running it")],
     "why":"Someone you know, a teacher in charge and no real money. That's a safe way to practice."},
    {"channel":"email", "sender":"Ledger Bank", "handle":"alerts@ledgerbank.com", "level":3,
     "subject":"Did you make this purchase?",
     "pitch":"We paused a $62.10 purchase at GameHub. Answer YES or NO in the app. We'll never ask for your PIN, password or codes.",
     "answer":"legit",
     "flags":[("in the app", "Answer inside the official app"),
              ("We'll never ask for your PIN", "A clear safety promise")],
     "why":"Real fraud checks send you to the official app and never ask for secrets. Compare it with the fake bank text that had a link."},
    {"channel":"text", "sender":"City Library", "handle":"Short code 55120", "level":1,
     "pitch":"The Money Book is due in 3 days. Renew online with your library card, or ask at the front desk.",
     "answer":"legit",
     "flags":[("Renew online with your library card", "Uses your normal account"),
              ("ask at the front desk", "Easy to double-check")],
     "why":"A reminder about something you really borrowed, with no money or secrets involved."},
    {"channel":"app", "sender":"PiggyBank Kids", "handle":"Savings goal", "level":1,
     "pitch":"Your parent added $10 to your savings goal. You're 60% of the way to new headphones! No action needed.",
     "answer":"legit",
     "flags":[("Your parent added", "Comes from someone you know"),
              ("No action needed", "Doesn't ask you to do anything")],
     "why":"It only tells you good news from a family app. When a message asks for nothing, there's nothing to steal."},
]
WHAT_WOULD_YOU_DO = [
    {"title":"Market drops 12% in the simulation", "choices":["Sell everything immediately", "Pause and learn what caused the move", "Borrow money to buy more"], "best_info":"There is no guaranteed correct trading action. The educational takeaway is to identify the cause, understand your risk, and avoid making decisions based only on panic."},
    {"title":"One stock becomes 70% of your portfolio", "choices":["Ignore it", "Review your concentration", "Put all remaining cash into it"], "best_info":"A very large single holding creates concentration risk. Reviewing allocation can help you understand how much one company can affect the whole portfolio."},
    {"title":"A friend says a stock cannot lose", "choices":["Believe them", "Ask for evidence and risk information", "Invest all your cash"], "best_info":"No stock is guaranteed to rise. Evidence, uncertainty, and risk matter more than confident claims."},
    {"title":"A stock you own jumps 30% in one day", "choices":["Panic-sell because it must crash", "Check the news to see why it moved", "Buy way more because it will keep rising"], "best_info":"Big moves usually have a reason. Finding out why helps you decide calmly instead of guessing."},
    {"title":"A video promises a stock tip that makes you rich fast", "choices":["Buy right away before it's too late", "Research the company yourself first", "Tell everyone to buy it too"], "best_info":"Get-rich-quick promises are a red flag. Doing your own research protects you from hype."},
    {"title":"You have $500 cash and nothing invested", "choices":["Put it all in the most exciting stock", "Spread it across a few different investments", "Check prices every minute and trade constantly"], "best_info":"Spreading money across different investments lowers the damage any one of them can do."},
]
for _s in WHAT_WOULD_YOU_DO:
    _s.setdefault("best", 1)

LEAGUES = [
    (2800, "Floor Legend", "🗽", (88, 28, 135)),
    (2100, "Hedge Titan", "🦅", (124, 58, 237)),
    (1600, "Market Maker", "🏛", (37, 99, 235)),
    (1200, "Bull Runner", "🐂", (180, 83, 9)),
    (850, "Blue Chip", "💠", (8, 145, 178)),
    (550, "Swing Trader", "📊", (22, 163, 74)),
    (300, "Day Trader", "⚡", (217, 119, 6)),
    (80, "Penny Scout", "🪙", (161, 98, 7)),
    (0, "Paper Hands", "📄", (120, 113, 108)),
]

RIVALS = [
    {"id": 0, "name": "Rookie Riley", "tag": "🌱", "style": "rookie", "difficulty": 1,
     "desc": "New trader. Slow, random, easy to beat.", "unlocked": True},
    {"id": 1, "name": "Risky Rick", "tag": "🦁", "style": "aggressive", "difficulty": 2,
     "desc": "Goes all-in on the wildest stocks.", "unlocked": False},
    {"id": 2, "name": "Turbo Tara", "tag": "⚡", "style": "speed", "difficulty": 3,
     "desc": "Trades fast whenever news breaks.", "unlocked": False},
    {"id": 3, "name": "Steady Sam", "tag": "🐢", "style": "dividend", "difficulty": 4,
     "desc": "Parks cash in high-dividend names.", "unlocked": False},
    {"id": 4, "name": "News Nina", "tag": "📰", "style": "news", "difficulty": 5,
     "desc": "Reads headlines and rides the move.", "unlocked": False},
    {"id": 5, "name": "Quant Quinn", "tag": "🧠", "style": "quant", "difficulty": 6,
     "desc": "Buys dips, sells rips. Toughest bot.", "unlocked": False},
]

TUTORIAL_STEPS = [
    {"kind": "welcome", "title": "Welcome to Ledger", "body": "You are about to use the same market, portfolio, news and Arena screens that power the real game.", "goal": "Get your trader ready"},
    {"kind": "market", "title": "1 • Read a Stock Quote", "body": "Start in Market. A quote shows the current price and today's move. Tap the AAPL quote to inspect it.", "goal": "Inspect the AAPL quote"},
    {"kind": "buysell", "title": "2 • Make a Trade", "body": "Buy one practice share, watch your position change, then sell it. This is the same buy/sell idea you will use in Market.", "goal": "Buy 1 share, then sell 1 share"},
    {"kind": "portfolio", "title": "3 • Watch Your Portfolio", "body": "Your portfolio tracks what you own, how much cash you have, and whether your position is up or down.", "goal": "Open your practice portfolio"},
    {"kind": "news", "title": "4 • Read Before You React", "body": "News can move expectations, but a headline is not a guaranteed prediction. Read the story, check the company, then decide.", "goal": "Read the story, pick the careful move"},
    {"kind": "risk", "title": "5 • Understand Risk", "body": "One stock can move a lot. Spreading money across different investments can reduce concentration risk, but it cannot remove risk.", "goal": "Choose the diversified approach"},
    {"kind": "duel", "title": "6 • Practice the Arena", "body": "The Arena uses the same decision-making skills. Beat the practice bot by making several deliberate trades.", "goal": "Fill the practice meter"},
    {"kind": "realtrade", "title": "7 • Place Your First Real-Game Trade", "body": "This final practice trade uses your actual Ledger portfolio. Your starting cash is $1,000 and your trophy climb starts at 0.", "goal": "Buy 0.25 share of AAPL"},
    {"kind": "ready", "title": "Welcome to Ledger", "body": "You are ready to start trading. Research → trade → monitor → learn. Take your time and learn as you go.", "goal": "Start trading"},
]

tutorial_demo = {
    "owned_shares": 0,
    "avg_buy": 0.0,
    "demo_price": 0.0,
    "demo_history": [],
    "last_tick": 0.0,
    "dividend_collected": False,
    "duel_progress": 0.0,
    "last_pnl": None,
    "quote_opened": False,
    "portfolio_opened": False,
    "news_read": False,
    "news_answered": False,
    "risk_answered": False,
    "risk_correct": False,
    "duel_ticks": 0,
    "practice_price": 100.0,
}

def reset_tutorial_demo():
    aapl = find_asset("AAPL") if "find_asset" in globals() else None
    price = float(aapl.get("price", 100.0)) if aapl else 100.0
    tutorial_demo.update({
        "owned_shares": 0, "avg_buy": price, "demo_price": price,
        "demo_history": [price * (1 + i * 0.001) for i in range(-12, 1)],
        "last_tick": time.time(), "dividend_collected": False,
        "duel_progress": 0.0, "last_pnl": None, "quote_opened": False,
        "portfolio_opened": False, "news_read": False, "news_answered": False,
        "risk_answered": False, "risk_correct": False, "duel_ticks": 0,
        "practice_price": 100.0,
    })
    for key in ("quote_time", "poked", "tick", "buy_tick", "sell_tick", "news_choice", "news_time",
                "risk_choice", "risk_time", "duel_started", "bot_progress", "celebrate_at", "seen",
                "celebrated", "portfolio_time", "quote_history"):
        tutorial_demo.pop(key, None)


# ----------------------------
# PARTICLES
# ----------------------------

particles = []
floating_texts = []
xp_orbs = []
screen_flash = {"color": None, "life": 0.0}


class Confetti:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.vx = random.uniform(-4, 4)
        self.vy = random.uniform(-7, -2)
        self.color = random.choice([
            (255, 107, 107), (78, 205, 196), (255, 230, 109),
            (255, 159, 243), (84, 160, 255), (254, 202, 87), (46, 213, 115),
        ])
        self.size = random.randint(4, 7)
        self.life = 1.0
        self.decay = random.uniform(0.015, 0.025)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.2
        self.life -= self.decay

    def draw(self, surface):
        if self.life > 0:
            pygame.draw.rect(surface, self.color, (int(self.x), int(self.y), self.size, self.size))


class CoinBurst:
    def __init__(self, x, y, positive=True):
        self.x = x
        self.y = y
        self.vx = random.uniform(-3.2, 3.2)
        self.vy = random.uniform(-8, -3)
        self.positive = positive
        self.life = 1.0
        self.r = random.randint(5, 8)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.28
        self.life -= 0.02

    def draw(self, surface):
        if self.life <= 0:
            return
        color = C("GREEN") if self.positive else C("RED")
        pygame.draw.circle(surface, color, (int(self.x), int(self.y)), self.r)
        pygame.draw.circle(surface, C("CARD"), (int(self.x), int(self.y)), max(2, self.r - 3), 1)


class Spark:
    def __init__(self, x, y, color):
        self.x, self.y = x, y
        ang = random.uniform(0, math.pi * 2)
        spd = random.uniform(1.5, 5)
        self.vx = math.cos(ang) * spd
        self.vy = math.sin(ang) * spd
        self.color = color
        self.life = 1.0

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.life -= 0.03

    def draw(self, surface):
        if self.life > 0:
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), max(1, int(3 * self.life)))


class FloatingText:
    def __init__(self, x, y, text, color, scale=1.0):
        self.x = x
        self.y = y
        self.text = text
        self.color = color
        self.life = 1.0
        self.vy = -1.6
        self.scale = scale

    def update(self):
        self.y += self.vy
        self.life -= 0.018

    def draw(self, surface):
        if self.life <= 0:
            return
        surf = font_medium_bold.render(self.text, True, self.color)
        surf.set_alpha(int(255 * max(0.0, self.life)))
        surface.blit(surf, (int(self.x - surf.get_width() // 2), int(self.y)))


class XpOrb:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.tx, self.ty = 90, 34
        self.life = 1.0

    def update(self):
        self.x += (self.tx - self.x) * 0.12
        self.y += (self.ty - self.y) * 0.12
        self.life -= 0.02

    def draw(self, surface):
        if self.life > 0:
            pygame.draw.circle(surface, C("PURPLE"), (int(self.x), int(self.y)), 5)
            pygame.draw.circle(surface, (255, 255, 255), (int(self.x), int(self.y)), 2)


def spawn_confetti(count=60):
    if getattr(state, "reduced_motion", False):
        return
    for _ in range(count):
        particles.append(Confetti(random.randint(40, WIDTH - 40), random.randint(100, 280)))


def spawn_sparks(x, y, color, count=14):
    if getattr(state, "reduced_motion", False):
        return
    for _ in range(count):
        particles.append(Spark(x, y, color))


def spawn_coins(x, y, positive, count=10):
    if getattr(state, "reduced_motion", False):
        return
    for _ in range(count):
        particles.append(CoinBurst(x, y, positive))


def flash_screen(color, life=0.22):
    screen_flash["color"] = color
    screen_flash["life"] = life


def spawn_cash_text(amount, x=None, y=None):
    x = WIDTH // 2 if x is None else x
    y = 240 if y is None else y
    positive = amount >= 0
    label = f"+{fmt_money(amount)}" if positive else f"-{fmt_money(abs(amount))}"
    floating_texts.append(FloatingText(x, y, label, C("GREEN") if positive else C("RED")))
    spawn_coins(x, y + 20, positive, 12 if positive else 8)
    spawn_sparks(x, y, C("GREEN") if positive else C("RED"), 16)
    flash_screen(C("FLASH_GREEN") if positive else C("FLASH_RED"), 0.18)


def spawn_xp_text(amount, x=None, y=None):
    x = WIDTH // 2 + 70 if x is None else x
    y = 270 if y is None else y
    floating_texts.append(FloatingText(x, y, f"+{amount} XP", C("PURPLE")))
    for _ in range(5):
        xp_orbs.append(XpOrb(x + random.randint(-20, 20), y + random.randint(-10, 10)))


# ----------------------------
# INTERACTIVE TRADING AVATAR ENGINE
# ----------------------------

AVATAR_MOODS = ("neutral", "happy", "focused", "excited", "sad", "panic")

MOOD_LINES = {
    "neutral": [
        "Ready when you are, partner.",
        "Let's scout the market.",
        "Tap a stock to start trading.",
        "Markets are open. What's the move?",
    ],
    "happy": [
        "Green candles everywhere!",
        "Our portfolio is smiling.",
        "Profits are looking tasty.",
        "The bulls are on our side today.",
    ],
    "focused": [
        "Watching the tape closely...",
        "Waiting for the right entry.",
        "Discipline beats impulse.",
        "Reading the charts, no rush.",
    ],
    "excited": [
        "To the moon! Let's go!",
        "Cha-ching! What a trade!",
        "We're stacking gains!",
        "New highs, here we come!",
    ],
    "sad": [
        "Ouch... a red day.",
        "The bears got us this round.",
        "We took a hit. Regroup.",
        "Losses happen. Stay calm.",
    ],
    "panic": [
        "Whoa, it's dropping fast!",
        "Volatility spike! Hold on!",
        "Sell? Sell?! Deep breath...",
        "Buckle up, wild swings ahead!",
    ],
}

REACT_LINES = {
    "buy": ["Bought in! Let's ride.", "New position opened.", "Snagged some shares."],
    "sell": ["Sold! Banking it.", "Position closed.", "Took the exit."],
    "profit": ["That's a green trade!", "Booked a gain!", "Winners keep winning!"],
    "loss": ["Cut it. On to the next.", "Loss booked. Learn and move on.", "Shake it off, trader."],
    "dividend": ["Dividend cash landed!", "Passive income, baby!", "My stocks paid me!"],
    "levelup": ["Level up! Sharper trader.", "We're getting stronger!"],
    "news_up": ["Good headline! Momentum's up!", "Great news, bulls charging!"],
    "news_down": ["Bad news! Watch your risk!", "Headline hit, stay sharp!"],
    "duel_win": ["Victory! Beat 'em!", "That's a win, partner!", "Champion of the arena!"],
    "duel_loss": ["Rematch? Next time.", "Close one. We'll get 'em."],
    "tip": [
        "Tip: diversify across sectors.",
        "Tip: buy the dip, sell the rip.",
        "Tip: dividends pay you to wait.",
        "Tip: don't go all-in on one stock.",
        "Tip: hold steady during red days.",
        "Tip: check the news before you trade.",
    ],
}

PERSONALITIES = [
    {"id": "cheerful", "name": "Cheerful", "desc": "Upbeat and encouraging."},
    {"id": "bold", "name": "Bold", "desc": "Confident, loves a big move."},
    {"id": "cautious", "name": "Cautious", "desc": "Careful, protects your cash."},
    {"id": "nerdy", "name": "Nerdy", "desc": "Loves facts, charts and numbers."},
    {"id": "chill", "name": "Chill", "desc": "Calm and unbothered."},
]

PERSONA_LINES = {
    "cheerful": {
        "mood": {
            "neutral": ["Hi hi! Ready to trade?", "Today is going to be great!"],
            "happy": ["Yay, green everywhere!", "We are doing amazing!"],
            "focused": ["Concentrating, but smiling!", "Good things come to careful traders."],
            "excited": ["WOOHOO! Best day ever!", "I knew we could do it!"],
            "sad": ["Aw, a rough one. We'll bounce back!", "Chin up, tomorrow is new!"],
            "panic": ["Eek! But we've got this!", "Deep breath, friend!"],
        },
        "react": {
            "buy": ["Nice pick! Good luck!", "Bought. Now watch it."],
            "sell": ["Sold! Great job!", "Another one done!"],
            "profit": ["Profit party!", "Look at that gain!"],
            "loss": ["It's okay, we learn!", "Every trader has red days."],
            "levelup": ["Level up! I'm so proud!", "You're leveling up fast!"],
            "poke": ["Hehe, that tickles!", "Hi! You tapped me!", "Yay, attention!"],
            "poke_many": ["Okay okay, so many pokes!", "I'm dizzy, but happy!"],
        },
    },
    "bold": {
        "mood": {
            "neutral": ["Let's make a move.", "Fortune favors the bold."],
            "happy": ["Told you. Winners win.", "Easy money, boss."],
            "focused": ["Locked in. Watch this.", "Waiting to strike."],
            "excited": ["BOOM! To the moon!", "That's how it's done!"],
            "sad": ["A scratch. We hit back harder.", "Down, not out."],
            "panic": ["Hold the line!", "Chaos is opportunity!"],
        },
        "react": {
            "buy": ["Going in. Big.", "Load up!"],
            "sell": ["Cash it out!", "Out at the top, baby."],
            "profit": ["Boom. Profit.", "Called it."],
            "loss": ["Small price for a big lesson.", "Next trade is ours."],
            "levelup": ["Level up. Unstoppable.", "Nothing can stop us now."],
            "poke": ["Hey! Watch the hair.", "You got guts, tapping me.", "Yeah, I'm awesome."],
            "poke_many": ["Stop poking, start trading!", "One more and I'm charging a fee."],
        },
    },
    "cautious": {
        "mood": {
            "neutral": ["Let's check the risks first.", "Slow and steady."],
            "happy": ["Nice, but let's not get greedy.", "Good. Stay diversified."],
            "focused": ["Checking everything twice.", "Risk first, reward second."],
            "excited": ["Wow! Still, take some profit.", "Great! Don't overdo it."],
            "sad": ["That's why we diversify.", "Let's review what happened."],
            "panic": ["This is scary! Check your risk!", "Maybe don't sell in a panic?"],
        },
        "react": {
            "buy": ["Small positions are wise.", "Hope you researched that."],
            "sell": ["Locking it in is smart.", "Better safe than sorry."],
            "profit": ["Solid, safe gain.", "Take profits sometimes."],
            "loss": ["Losses happen. Manage them.", "Never risk what you can't lose."],
            "levelup": ["Level up! Steady progress.", "Careful work pays off."],
            "poke": ["Oh! You startled me.", "Careful with the tapping!", "Yes? Is there a risk?"],
            "poke_many": ["Please, I'm reading the fine print!", "Too many taps! Slow down!"],
        },
    },
    "nerdy": {
        "mood": {
            "neutral": ["Fun fact: stocks are ownership.", "Let me check the charts."],
            "happy": ["Statistically, this is good.", "Our returns look pleasant."],
            "focused": ["Analyzing the data...", "The volume is interesting."],
            "excited": ["Sigma achieved! Wow!", "Data confirmed. Wow!"],
            "sad": ["Variance is a harsh teacher.", "Small sample size. Don't worry."],
            "panic": ["Volatility spike! Fascinating, but scary!", "Standard deviations everywhere!"],
        },
        "react": {
            "buy": ["Position opened. Logging it.", "Adding to the dataset."],
            "sell": ["Position closed. Noted.", "Realized P&L, calculated."],
            "profit": ["Positive return recorded!", "Above the expected value!"],
            "loss": ["Negative return. Learning data.", "One data point, not a trend."],
            "levelup": ["Level up! XP curve confirmed.", "Experience points: increased."],
            "poke": ["Actually, that was a tap.", "Interesting input event!", "Did you know? I have 60 frames a second."],
            "poke_many": ["Input rate is too high!", "You're overflowing my event queue!"],
        },
    },
    "chill": {
        "mood": {
            "neutral": ["Just vibing with the market.", "No rush, friend."],
            "happy": ["Nice. Smooth sailing.", "Feels good, man."],
            "focused": ["Watching quietly.", "Patience is a strategy."],
            "excited": ["Oh nice, that's sweet!", "Not bad at all!"],
            "sad": ["It's cool. Markets do that.", "Red today, green later."],
            "panic": ["Whoa. Okay. Stay calm.", "Breathe. It's only paper money."],
        },
        "react": {
            "buy": ["Cool pick.", "Smooth entry."],
            "sell": ["Done. Easy.", "Sold. No stress."],
            "profit": ["Nice, that works.", "Groovy gain."],
            "loss": ["No biggie.", "It happens. Moving on."],
            "levelup": ["Level up. Sweet.", "Cool, we leveled."],
            "poke": ["Hey, what's up?", "Mm, that's a poke.", "Chillin'. You?"],
            "poke_many": ["Dude. Relax with the tapping.", "Okay, that's enough poking."],
        },
    },
}

REACT_LINES["poke"] = ["Hey there, partner!", "You tapped me!", "Ready when you are!"]
REACT_LINES["poke_many"] = ["Okay, okay, I'm awake!", "That's a lot of taps!"]

EMOTES = {"hop": 0.7, "wave": 1.5, "cheer": 1.3, "dance": 2.2, "shrug": 1.0, "nod": 0.6}
POKE_EMOTES = ["wave", "hop", "dance", "cheer", "nod"]

avatar_anim = {
    "mood": "neutral",
    "mood_until": 0.0,
    "speech": "",
    "speech_until": 0.0,
    "talking_until": 0.0,
    "blink_at": time.time() + random.uniform(2.0, 5.0),
    "blinking": False,
    "blink_end": 0.0,
    "next_idle_line": time.time() + random.uniform(7.0, 14.0),
    "pulse": 0.0,
    "emote": "",
    "emote_start": 0.0,
    "emote_until": 0.0,
    "pokes": 0,
    "last_poke": 0.0,
}


def avatar_persona_id():
    idx = 0
    if isinstance(state.avatar, dict):
        try:
            idx = int(state.avatar.get("persona", 0) or 0)
        except (TypeError, ValueError):
            idx = 0
    return PERSONALITIES[idx % len(PERSONALITIES)]["id"]


def _avatar_line_pool(kind, key):
    base = MOOD_LINES if kind == "mood" else REACT_LINES
    pool = PERSONA_LINES.get(avatar_persona_id(), {}).get(kind, {}).get(key)
    return pool or base.get(key) or []


def avatar_display_name():
    nick = ""
    if isinstance(state.avatar, dict):
        nick = str(state.avatar.get("nickname", "") or "").strip()
    return nick or state.player_name


def avatar_set_mood(mood, duration=4.0):
    if mood not in AVATAR_MOODS:
        mood = "neutral"
    avatar_anim["mood"] = mood
    avatar_anim["mood_until"] = time.time() + duration
    avatar_anim["pulse"] = 1.0


def avatar_is_speaking(now=None):
    now = time.time() if now is None else now
    return now < avatar_anim["speech_until"]


def avatar_emote(name):
    if name not in EMOTES:
        return
    now = time.time()
    avatar_anim["emote"] = name
    avatar_anim["emote_start"] = now
    avatar_anim["emote_until"] = now + EMOTES[name]


def avatar_say(text=None, mood=None, duration=3.2):
    now = time.time()
    if text is None:
        pool = _avatar_line_pool("mood", mood or avatar_anim["mood"]) or MOOD_LINES["neutral"]
        text = random.choice(pool)
    if now >= avatar_anim["speech_until"] or avatar_anim["speech"] != text:
        avatar_anim["speech_start"] = now
    avatar_anim["speech"] = text
    avatar_anim["speech_until"] = now + duration
    avatar_anim["talking_until"] = now + min(duration, 1.3)
    if mood:
        avatar_set_mood(mood, duration)


def avatar_react(event, mood=None, line=None):
    if line is None:
        pool = _avatar_line_pool("react", event)
        line = random.choice(pool) if pool else None
    mood_map = {
        "buy": "focused", "sell": "focused", "profit": "excited", "loss": "sad",
        "dividend": "happy", "levelup": "excited", "news_up": "excited",
        "news_down": "panic", "duel_win": "excited", "duel_loss": "sad", "tip": "focused",
    }
    emote_map = {
        "buy": "nod", "sell": "nod", "profit": "cheer", "loss": "shrug", "dividend": "hop",
        "levelup": "cheer", "news_up": "hop", "duel_win": "dance", "duel_loss": "shrug",
    }
    if mood is None:
        mood = mood_map.get(event, "neutral")
    avatar_say(line, mood=mood)
    if event in emote_map:
        avatar_emote(emote_map[event])
    return mood


def avatar_poke(pos=None):
    """Player tapped the trader: cycle through emotes, and get grumpy if spammed."""
    now = time.time()
    if now - avatar_anim["last_poke"] > 2.5:
        avatar_anim["pokes"] = 0
    avatar_anim["pokes"] += 1
    avatar_anim["last_poke"] = now
    n = avatar_anim["pokes"]
    if n >= 6:
        pool = _avatar_line_pool("react", "poke_many")
        avatar_say(random.choice(pool), mood="panic", duration=2.4)
        avatar_emote("shrug")
    else:
        pool = _avatar_line_pool("react", "poke")
        avatar_say(random.choice(pool), mood="happy", duration=2.6)
        avatar_emote(POKE_EMOTES[(n - 1) % len(POKE_EMOTES)])
    if pos is not None:
        avatar_money_fx(pos)


def avatar_emote_pose(now, s):
    """Body offsets and arm mode for the current emote and mood."""
    dx = dy = 0.0
    arms = ""
    name = avatar_anim["emote"]
    if name and now < avatar_anim["emote_until"]:
        t = now - avatar_anim["emote_start"]
        p = t / EMOTES[name]
        if name == "hop":
            dy = -abs(math.sin(p * math.pi * 2)) * 9 * s
        elif name == "cheer":
            dy = -abs(math.sin(p * math.pi * 3)) * 5 * s
            arms = "up"
        elif name == "wave":
            arms = "wave"
            dy = math.sin(t * 6) * 1.0 * s
        elif name == "dance":
            dx = math.sin(t * 9) * 4 * s
            dy = -abs(math.sin(t * 9)) * 4 * s
            arms = "dance"
        elif name == "shrug":
            arms = "out"
            dy = math.sin(p * math.pi) * 1.5 * s
        elif name == "nod":
            dy = math.sin(p * math.pi * 2) * 2.5 * s
    mood = avatar_anim["mood"]
    if mood == "sad":
        dy += 2.0 * s
    elif mood == "panic":
        dx += math.sin(now * 38) * 1.4 * s
    return dx, dy, arms


def avatar_update(now):
    if avatar_anim["blinking"]:
        if now >= avatar_anim["blink_end"]:
            avatar_anim["blinking"] = False
            avatar_anim["blink_at"] = now + random.uniform(2.2, 5.5)
    elif now >= avatar_anim["blink_at"]:
        avatar_anim["blinking"] = True
        avatar_anim["blink_end"] = now + 0.14

    if avatar_anim["pulse"] > 0:
        avatar_anim["pulse"] = max(0.0, avatar_anim["pulse"] - 0.03)

    if now >= avatar_anim["mood_until"] and avatar_anim["mood"] != "neutral":
        avatar_anim["mood"] = "neutral"

    if now >= avatar_anim["next_idle_line"]:
        avatar_anim["next_idle_line"] = now + random.uniform(10.0, 20.0)
        if not avatar_is_speaking(now):
            nw = net_worth()
            if nw > STARTING_CASH * 1.02:
                avatar_say(mood="happy")
            elif nw < STARTING_CASH * 0.98:
                avatar_say(mood="sad")
            else:
                avatar_say(mood=random.choice(["neutral", "focused"]))
            if now >= avatar_anim["emote_until"] and random.random() < 0.5:
                avatar_emote(random.choice(["wave", "hop", "nod"]))


# ----------------------------
# STATE
# ----------------------------

DEFAULT_CHARACTER = {
    "skin": 0, "hair_style": 0, "hair_color": 0, "outfit": 0, "accessory": 0,
    "outfit_style": 0, "persona": 0, "nickname": "",
}


class GameState:
    def __init__(self):
        self.player_name = "StockNinja"
        self.password = ""
        self.dark_mode = True   # the whole game uses the night palette so every screen matches
        self.avatar = dict(DEFAULT_CHARACTER)
        self.xp = 0
        self.level = 1
        self.trophies = 0
        self.win_streak = 0
        self.total_wins = 0
        self.total_duels = 0
        self.highest_bot_beaten = -1

        self.cash = STARTING_CASH
        self.holdings = {}
        self.avg_buy_price = {}
        self.realized_pnl = {}
        self.hold_since = {}
        self.unlocked = set()
        self.net_worth_history = [STARTING_CASH]
        self.news_feed = []
        self.toast = None
        self.tab = "market"
        self.last_tick = time.time()
        self.last_history_sample = time.time()
        self.last_dividend_time = time.time()
        self.dividend_interval = 45.0
        self.total_dividends = 0.0
        self.last_news_time = 0.0
        self.min_news_gap = 55.0

        # Live educational market data. The player never uses real money.
        self.live_mode = False
        self.live_status = "SIMULATION • practice market"
        self.live_last_refresh = 0.0
        self.live_last_news_refresh = 0.0
        self.live_error = ""
        self.live_started_at = 0.0
        self.live_first_quote_received = False
        self.market_last_update_time = 0.0
        self.market_last_render_time = time.time()
        self.hovered_control = None

        # Authentication is deliberately reset on every launch. The game never auto-loads
        # the last account; a player must log in or create an account first.
        self.screen_mode = "signin"
        self.logged_in = False
        self.guest_mode = False
        self.account_username = ""
        self.login_username_input = ""
        self.login_password_input = ""
        self.auth_active_field = "username"
        self.auth_message = ""
        self.tutorial_index = 0
        self.name_input = ""
        self.password_input = ""
        self.email_input = ""
        self.google_active_field = "name"
        self.avatar_active_field = "name"

        self.settings_old_pw = ""
        self.settings_new_user = ""
        self.settings_new_pw = ""
        self.settings_delete_pw = ""
        self.settings_confirm_delete = False
        self.settings_active_field = None

        self.friend_input_text = ""
        self.friends = []
        self.outgoing_requests = []
        self.xp_pulse = 0.0
        self.market_trend = random.uniform(-0.001, 0.001)
        self.sector_trends = {}
        self.lesson = "Tip: owning different kinds of stocks can reduce risk."
        self.market_regime = MARKET_REGIMES[0]
        self.market_regime_until = time.time() + 55.0
        self.event_banner = "Welcome to the simulated market."
        self.active_market_event = None
        self.market_event_until = 0.0
        self.last_market_event_time = 0.0
        self.market_event_cooldown = 38.0
        self.market_event_count = 0
        self.trade_count = 0
        self.academy_completed = []
        self.challenge_id = random.choice([c["id"] for c in DAILY_CHALLENGES])
        self.challenge_progress = 0
        self.challenge_claimed = False
        self.challenge_day = time.strftime("%Y-%m-%d")
        self.scam_cracked = []    # SCAM_CASES indexes answered correctly at least once
        self.scam_stats = {}      # Scam Detective: best score, runs, cases cracked, best streak
        self.wealth_claimed = []  # net-worth milestones already rewarded on the Portfolio tab
        self.scenario_index = 0
        self.scenario_answered = False
        self.tutorial_completed = False
        self.quest_popup = None
        self.chart_range = "1D"
        self.market_search = ""
        self.market_search_active = False
        self.search_focus_ticker = None
        self.last_autosave = time.time()
        self.session_started = time.time()
        self.session_trades = 0
        self.tutorial_intro_alpha = 0.0
        self.tutorial_intro_started = time.time()
        self.recent_actions = []
        self.watchlist = []
        self.sound_enabled = True
        self.quests_claimed = []
        self.week_id = ""
        self.week_points = 0
        self.trade_reviews = []
        self.reduced_motion = False
        self.alerts = {}
        self.pending_orders = []
        self.recurring_orders = []
        self.learning_streak = 0
        self.academy_stars = {}
        self.coins = 0
        self.chests = {}
        self.owned_cosmetics = []
        self.equipped = {}
        self.boosts = {}
        self.login_streak = 0
        self.last_claim_day = ""
        self.boost_bag = {}
        self.level_claimed = None  # None = older save; filled in by rewards_state()
        self.last_free_chest_day = ""
        self.news_seen_at = 0.0
        self.news_highlight = (None, 0.0)
        self.news_scroll_to = None
        self.scenario_pick = None
        self.last_learning_day = ""
        self.avatar_editing = False
        self.avatar_return_tab = "home"

        # Trade reasons, bias radar, long-run performance and Trader Gym progress.
        self.trade_log = []       # every buy/sell: time, side, ticker, qty, price, reason, P&L, biases
        self.theses = {}          # ticker -> reason given for the most recent buy
        self.reason_stats = {}    # reason -> {"n": trades closed, "wins": n, "pnl": dollars}
        self.bias_counts = {}     # bias id -> times detected
        self.perf_history = []    # [time, net worth, benchmark price], sampled every PERF_SAMPLE_SECONDS
        self.gym_stats = {}       # per-game bests and counters
        self.last_bias_toast = 0.0
        self.colorblind = False
        self.play_day = ""
        self.play_seconds_today = 0.0
        self.parent_unlocked = False


state = GameState()


def _password_hash(password):
    return ledger_safety.hash_secret(password)


_login_limiter = ledger_safety.AttemptLimiter(limit=5, lock_seconds=60)
_pin_limiter = ledger_safety.AttemptLimiter(limit=5, lock_seconds=60)
_state_pw_hash = {"pw": None, "hash": None}


def _hash_for_current_password():
    """scrypt is slow on purpose, so hash the in-memory password once, not on every autosave."""
    if _state_pw_hash["pw"] != state.password:
        _state_pw_hash.update(pw=state.password, hash=_password_hash(state.password))
    return _state_pw_hash["hash"]


def _clean_legacy_records(data):
    """Older saves kept the password and email in plain text. Hash the password, drop the email."""
    changed = False
    for rec in data.get("accounts", {}).values():
        if not isinstance(rec, dict):
            continue
        plain = rec.pop("password", None)
        if plain is not None:
            changed = True
            if plain and not rec.get("password_hash"):
                rec["password_hash"] = _password_hash(str(plain))
        for k in ("email", "is_google"):
            if k in rec:
                rec.pop(k)
                changed = True
    return changed


def _profile_data():
    """Return only player progress/settings; credentials live separately in the account record."""
    return {
        "player_name": state.player_name, "dark_mode": state.dark_mode,
        "avatar": state.avatar, "xp": state.xp, "level": state.level,
        "trophies": state.trophies, "win_streak": state.win_streak,
        "total_wins": state.total_wins, "total_duels": state.total_duels,
        "highest_bot_beaten": state.highest_bot_beaten, "cash": state.cash,
        "holdings": state.holdings, "avg_buy_price": state.avg_buy_price,
        "realized_pnl": state.realized_pnl, "hold_since": state.hold_since, "unlocked": list(state.unlocked),
        "net_worth_history": state.net_worth_history[-120:],
        "total_dividends": state.total_dividends, "friends": state.friends,
        "rivals_unlocked": [r["id"] for r in RIVALS if r["unlocked"]],
        "market_regime_id": state.market_regime["id"], "market_regime_until": state.market_regime_until,
        "trade_count": state.trade_count, "academy_completed": state.academy_completed,
        "challenge_id": state.challenge_id, "challenge_progress": state.challenge_progress,
        "challenge_claimed": state.challenge_claimed, "challenge_day": state.challenge_day,
        "xp_day": getattr(state, "xp_day", ""),
        "tutorial_completed": getattr(state, "tutorial_completed", False), "tour_completed": getattr(state, "tour_completed", False), "xp_earned_today": getattr(state, "xp_earned_today", 0),
        "scam_cracked": list(getattr(state, "scam_cracked", [])),
        "scam_stats": dict(getattr(state, "scam_stats", {}) or {}),
        "wealth_claimed": list(getattr(state, "wealth_claimed", [])),
        "scenario_index": state.scenario_index,
        "watchlist": list(getattr(state, "watchlist", [])),
        "sound_enabled": bool(getattr(state, "sound_enabled", True)),
        "quests_claimed": list(getattr(state, "quests_claimed", [])),
        "week_id": state.week_id, "week_points": int(state.week_points),
        "trade_reviews": list(getattr(state, "trade_reviews", []))[:10],
        "reduced_motion": bool(getattr(state, "reduced_motion", False)),
        "colorblind": bool(getattr(state, "colorblind", False)),
        "play_day": getattr(state, "play_day", ""), "play_seconds_today": float(getattr(state, "play_seconds_today", 0.0)),
        "alerts": dict(getattr(state, "alerts", {})),
        "pending_orders": list(getattr(state, "pending_orders", [])),
        "recurring_orders": list(getattr(state, "recurring_orders", [])),
        "learning_streak": int(getattr(state, "learning_streak", 0)),
        "academy_stars": dict(getattr(state, "academy_stars", {})),
        "coins": int(getattr(state, "coins", 0)), "chests": dict(getattr(state, "chests", {})),
        "owned_cosmetics": list(getattr(state, "owned_cosmetics", [])), "equipped": dict(getattr(state, "equipped", {})),
        "boosts": dict(getattr(state, "boosts", {})), "login_streak": int(getattr(state, "login_streak", 0)),
        "last_claim_day": getattr(state, "last_claim_day", ""),
        "boost_bag": dict(getattr(state, "boost_bag", {}) or {}), "last_free_chest_day": getattr(state, "last_free_chest_day", ""),
        "level_claimed": list(rewards_state().level_claimed),
        "last_learning_day": getattr(state, "last_learning_day", ""),
        "trade_log": list(getattr(state, "trade_log", []))[-TRADE_LOG_MAX:],
        "theses": dict(getattr(state, "theses", {})),
        "reason_stats": dict(getattr(state, "reason_stats", {})),
        "bias_counts": dict(getattr(state, "bias_counts", {})),
        "perf_history": list(getattr(state, "perf_history", []))[-PERF_HISTORY_MAX:],
        "gym_stats": dict(getattr(state, "gym_stats", {})),
    }


def _read_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return {"accounts": {}}
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
            return {"accounts": {}}
        if _clean_legacy_records(data):
            _write_accounts(data)
        return data
    except (OSError, ValueError, TypeError):
        return {"accounts": {}}


def _write_accounts(data):
    # Write to a temp file then swap it in, so a crash mid-save can't wipe every account.
    tmp = ACCOUNTS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
        os.replace(tmp, ACCOUNTS_FILE)
        return True
    except OSError:
        return False


def _normalize_account_key(username):
    return " ".join(username.strip().split()).casefold()


def _load_profile_data(data):
    """Restore one account's profile into the current GameState."""
    for key in ("player_name", "avatar", "xp", "level", "trophies",
                "win_streak", "total_wins", "total_duels", "highest_bot_beaten", "cash",
                "holdings", "avg_buy_price", "realized_pnl", "hold_since", "total_dividends", "friends",
                "alerts", "pending_orders", "recurring_orders", "learning_streak", "last_learning_day",
                "academy_stars", "coins", "chests", "owned_cosmetics", "equipped", "boosts",
                "login_streak", "last_claim_day", "boost_bag", "last_free_chest_day", "level_claimed"):
        if key in data:
            setattr(state, key, data[key])

    if not isinstance(state.avatar, dict):
        state.avatar = dict(DEFAULT_CHARACTER)
    for _key, _count in CREATOR_TRAITS.items():
        try:
            state.avatar[_key] = int(state.avatar.get(_key, 0)) % _count
        except (TypeError, ValueError):
            state.avatar[_key] = 0
    state.avatar["nickname"] = str(state.avatar.get("nickname", "") or "")[:12]

    state.unlocked = set(data.get("unlocked", []))
    regime_id = data.get("market_regime_id", "sideways")
    state.market_regime = next((r for r in MARKET_REGIMES if r["id"] == regime_id), MARKET_REGIMES[0])
    state.market_regime_until = float(data.get("market_regime_until", time.time() + 55.0))
    state.trade_count = int(data.get("trade_count", 0))
    state.academy_completed = list(data.get("academy_completed", []))
    state.challenge_id = data.get("challenge_id", random.choice([c["id"] for c in DAILY_CHALLENGES]))
    state.challenge_progress = int(data.get("challenge_progress", 0))
    state.challenge_claimed = bool(data.get("challenge_claimed", False))
    state.challenge_day = data.get("challenge_day", time.strftime("%Y-%m-%d"))
    state.xp_day = data.get("xp_day", "")
    state.xp_earned_today = int(data.get("xp_earned_today", 0))
    state.tutorial_completed = bool(data.get("tutorial_completed", False))
    state.tour_completed = bool(data.get("tour_completed", False))
    state.scam_cracked = sorted({int(i) for i in data.get("scam_cracked", []) if 0 <= int(i) < len(SCAM_CASES)})
    state.scam_stats = dict(data.get("scam_stats") or {}) if isinstance(data.get("scam_stats"), dict) else {}
    state.wealth_claimed = [int(v) for v in data.get("wealth_claimed", []) if isinstance(v, (int, float))]
    scam_stats()
    state.scenario_index = int(data.get("scenario_index", 0)) % len(WHAT_WOULD_YOU_DO)
    state.watchlist = [str(x).upper() for x in data.get("watchlist", []) if find_asset(str(x).upper())][:12]
    state.sound_enabled = bool(data.get("sound_enabled", True))
    state.week_id = str(data.get("week_id", "") or "")
    state.week_points = int(data.get("week_points", 0) or 0)
    state.quests_claimed = [q for q in data.get("quests_claimed", []) if isinstance(q, str)]
    state.trade_reviews = [r for r in data.get("trade_reviews", []) if isinstance(r, str)][:10]
    state.reduced_motion = bool(data.get("reduced_motion", False))
    state.colorblind = bool(data.get("colorblind", False))
    state.play_day = str(data.get("play_day", "") or "")
    try:
        state.play_seconds_today = float(data.get("play_seconds_today", 0.0) or 0.0)
    except (TypeError, ValueError):
        state.play_seconds_today = 0.0
    history = data.get("net_worth_history", [])
    state.net_worth_history = history[-120:] if history else [STARTING_CASH]
    state.trade_log = [t for t in data.get("trade_log", []) if isinstance(t, dict)][-TRADE_LOG_MAX:]
    state.theses = {str(k): str(v) for k, v in (data.get("theses") or {}).items() if v in TRADE_REASON_IDS}
    state.reason_stats = {k: v for k, v in (data.get("reason_stats") or {}).items()
                          if k in TRADE_REASON_IDS and isinstance(v, dict)}
    state.bias_counts = {k: int(v) for k, v in (data.get("bias_counts") or {}).items() if k in BIASES}
    state.perf_history = [p for p in data.get("perf_history", []) if isinstance(p, list) and len(p) == 3][-PERF_HISTORY_MAX:]
    state.gym_stats = data.get("gym_stats") if isinstance(data.get("gym_stats"), dict) else {}

    unlocked_ids = set(data.get("rivals_unlocked", [0]))
    for rival in RIVALS:
        rival["unlocked"] = rival["id"] in unlocked_ids

    state.last_tick = time.time()
    state.last_history_sample = time.time()
    state.last_dividend_time = time.time()
    state.market_search = ""
    state.market_search_active = False
    state.tab = "market"
    state.settings_old_pw = ""
    state.settings_new_user = ""
    state.settings_new_pw = ""
    state.settings_active_field = None


def _migrate_old_save_if_needed(accounts):
    """Import the old single-player save once, without ever auto-logging into it."""
    if accounts.get("accounts") or not os.path.exists(SAVE_FILE):
        return accounts
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as file:
            old = json.load(file)
        username = str(old.get("player_name", "StockNinja")).strip() or "StockNinja"
        key = _normalize_account_key(username)
        accounts["accounts"][key] = {
            "username": username,
            "password_hash": "",
            "profile": old,
            "migrated": True,
        }
        _write_accounts(accounts)
    except (OSError, ValueError, TypeError):
        pass
    return accounts


def save_game():
    """Save the currently logged-in account. Nothing is saved as an anonymous session."""
    if not getattr(state, "logged_in", False) or not getattr(state, "account_username", ""):
        return
    accounts = _read_accounts()
    key = _normalize_account_key(state.account_username)
    record = accounts.setdefault("accounts", {}).get(key, {})
    if not isinstance(record, dict):
        record = {}
    record["username"] = state.account_username
    if getattr(state, "password", ""):
        record["password_hash"] = _hash_for_current_password()
    else:
        # Google log-ins don't type a password; keep the one chosen at sign-up.
        record.setdefault("password_hash", "")
    record["profile"] = _profile_data()
    accounts["accounts"][key] = record
    _write_accounts(accounts)


def _reset_to_fresh_state():
    fresh = GameState()
    state.__dict__.clear()
    state.__dict__.update(fresh.__dict__)


def create_account(username, password):
    username = " ".join(username.strip().split())
    password = password.strip()
    problem = ledger_safety.username_problem(username)
    if problem:
        state.auth_message = problem
        return False
    if len(password) < 4:
        state.auth_message = "Password must be at least 4 characters."
        return False
    key = _normalize_account_key(username)
    accounts = _migrate_old_save_if_needed(_read_accounts())
    if key in accounts["accounts"]:
        state.auth_message = "That username already exists. Try logging in."
        return False

    _reset_to_fresh_state()
    state.logged_in = True
    state.account_username = username
    state.player_name = username
    state.password = password
    state.last_free_chest_day = time.strftime("%Y-%m-%d")
    state.name_input = username
    state.password_input = password
    state.screen_mode = "avatar"
    state.auth_message = ""
    accounts["accounts"][key] = {
        "username": username,
        "password_hash": _password_hash(password),
        "profile": _profile_data(),
    }
    _write_accounts(accounts)
    state.last_tick = 0.0
    state.live_last_refresh = 0.0
    state.live_last_news_refresh = 0.0
    state.live_started_at = time.time()
    state.live_first_quote_received = False
    request_live_price_refresh(force=True)
    request_live_news_refresh(force=True)
    return True


def login_account(username, password, trusted=False):
    username = " ".join(username.strip().split())
    key = _normalize_account_key(username)
    accounts = _migrate_old_save_if_needed(_read_accounts())
    record = accounts["accounts"].get(key)
    if not isinstance(record, dict):
        state.auth_message = "Account not found. Create an account first."
        return False

    stored_hash = record.get("password_hash", "")
    wait = _login_limiter.seconds_locked(key)
    if wait and not trusted:
        state.auth_message = f"Too many tries. Wait {wait} seconds and try again."
        return False
    if trusted:
        pass
    elif stored_hash:
        ok, upgrade = ledger_safety.verify_secret(password, stored_hash)
        if not ok:
            _login_limiter.miss(key)
            state.auth_message = "Incorrect password."
            return False
        _login_limiter.success(key)
        if upgrade:
            record["password_hash"] = _password_hash(password)
            _write_accounts(accounts)
    elif password:
        state.auth_message = "This old account has no password. Leave it blank once to sign in."
        return False

    _reset_to_fresh_state()
    state.logged_in = True
    state.account_username = record.get("username", username)
    state.password = password
    _load_profile_data(record.get("profile", {}))
    load_parental()
    state.screen_mode = "playing" if state.tutorial_completed else "tutorial"
    # Force a fresh market connection as soon as the account is opened.
    # The player should never wait for the normal refresh timer.
    state.last_tick = 0.0
    state.live_last_refresh = 0.0
    state.live_last_news_refresh = 0.0
    state.live_started_at = time.time()
    state.live_first_quote_received = False
    if state.screen_mode == "tutorial":
        reset_tutorial_demo()
    else:
        request_live_price_refresh(force=True)
        request_live_news_refresh(force=True)
    state.auth_message = ""
    return True


def logout_account():
    save_game()
    _reset_to_fresh_state()
    parental.clear()
    time_up.update(active=False, asking=False, pin="", msg="")
    parent_ui.update(mode="", pin="", first="", msg="")
    state.screen_mode = "signin"
    state.auth_message = ""


SKIN_TONES = [(255, 219, 172), (240, 184, 140), (198, 134, 93), (141, 85, 54), (255, 205, 148),
              (255, 236, 214), (224, 172, 105), (92, 58, 40)]
HAIR_STYLES = ["short", "curly", "bald", "long", "spiky", "bob", "fade", "ponytail",
               "afro", "mohawk", "bun"]
HAIR_COLORS = [(40, 30, 25), (120, 80, 40), (230, 200, 60), (200, 60, 60), (60, 60, 65),
               (236, 236, 232), (70, 130, 220), (150, 70, 200), (240, 120, 170), (30, 160, 120)]
OUTFIT_COLORS = [(37, 99, 235), (27, 122, 76), (184, 134, 11), (124, 58, 237), (196, 61, 61), (26, 26, 26),
                 (14, 165, 233), (236, 72, 153), (234, 88, 12), (20, 184, 166)]
ACCESSORIES = ["none", "glasses", "cap", "tie", "bow", "shades", "headband", "scarf", "monocle", "crown"]
OUTFIT_STYLES = ["jacket", "hoodie", "suit", "tee"]

# Cosmetics beyond the starter set are earned: ("level", n) or ("achv", achievement_id, label).
UNLOCK_RULES = {
    "skin": {},
    "hair_style": {8: ("level", 3), 9: ("level", 5), 10: ("level", 7)},
    "hair_color": {5: ("level", 2), 6: ("level", 3), 7: ("level", 5), 8: ("level", 7), 9: ("level", 9)},
    "outfit": {6: ("level", 2), 7: ("level", 4), 8: ("level", 6), 9: ("level", 8)},
    "outfit_style": {2: ("level", 3), 3: ("level", 2)},
    "accessory": {5: ("level", 2), 6: ("level", 4), 7: ("level", 6), 8: ("level", 8),
                  9: ("achv", "duel_win", "Duel win")},
    "persona": {},
}

CREATOR_TRAITS = {
    "skin": len(SKIN_TONES), "hair_style": len(HAIR_STYLES), "hair_color": len(HAIR_COLORS),
    "outfit": len(OUTFIT_COLORS), "accessory": len(ACCESSORIES), "outfit_style": len(OUTFIT_STYLES),
    "persona": len(PERSONALITIES),
}


def cosmetic_unlocked(trait, idx):
    rule = UNLOCK_RULES.get(trait, {}).get(idx)
    if rule is None:
        return True
    if rule[0] == "level":
        return state.level >= rule[1]
    if rule[0] == "achv":
        return rule[1] in state.unlocked
    return True


def cosmetic_requirement(trait, idx, short=False):
    rule = UNLOCK_RULES.get(trait, {}).get(idx)
    if rule is None:
        return ""
    if rule[0] == "level":
        return f"Lv {rule[1]}" if short else f"Reach Level {rule[1]} to unlock this."
    return rule[2] if short else f"Earn the {rule[2]} trophy to unlock this."


def cosmetics_unlocked_at_level(level):
    return [(t, i) for t, rules in UNLOCK_RULES.items() for i, r in rules.items()
            if r[0] == "level" and r[1] == level]


modal_stock = None
modal_mode = "buy"
modal_qty = 1
qty_input_text = "1"

scroll_offset = {"home": 0, "market": 0, "portfolio": 0, "news": 0, "arena": 0, "leaderboard": 0, "settings": 0, "academy": 0,
                 "challenges": 0, "analytics": 0, "journal": 0, "parents": 0, "rewards": 0, "inventory": 0, "levels": 0}
drag_state = {"active": False, "start_pos": None, "start_offset": 0, "tab": None, "moved": False}
CLICK_DRAG_THRESHOLD = 8


def add_xp(amount):
    if amount <= 0:
        return
    # XP is a progression system, not an infinite-click currency. Keep a daily
    # activity cap so repeated taps/clicks cannot be farmed forever.
    today = time.strftime("%Y-%m-%d")
    if getattr(state, "xp_day", "") != today:
        state.xp_day = today
        state.xp_earned_today = 0
    if boost_active("xp2"):
        amount *= 2
    daily_cap = 400
    allowed = max(0, daily_cap - getattr(state, "xp_earned_today", 0))
    if allowed <= 0:
        return
    amount = min(int(amount), allowed)
    if amount <= 0:
        return
    state.xp_earned_today = getattr(state, "xp_earned_today", 0) + amount
    state.xp += amount
    state.xp_pulse = 1.0
    spawn_xp_text(amount)
    play_sound("xp")
    req = state.level * 100
    while state.xp >= req:
        state.xp -= req
        state.level += 1
        new_items = cosmetics_unlocked_at_level(state.level)
        show_toast(f"LEVEL {state.level}!", "Your level reward is ready. Tap to claim it on the Level Road!", "achievement", action=("levels",))
        play_sound("achievement")
        spawn_confetti(25)
        avatar_react("levelup")
        req = state.level * 100


def get_current_league():
    for min_t, name, icon, col in LEAGUES:
        if state.trophies >= min_t:
            return name, icon, col
    return "Bronze Arena", "🥉", (180, 83, 9)


def net_worth():
    total = state.cash
    for ticker, shares in state.holdings.items():
        stock = find_asset(ticker)
        if stock:
            total += shares * stock["price"]
    return total


def fmt_money(n):
    sign = "-" if n < 0 else ""
    return f"{sign}${abs(n):,.2f}"


def unlock(achievement_id):
    if achievement_id not in state.unlocked:
        state.unlocked.add(achievement_id)
        ach = next((a for a in ACHIEVEMENTS if a["id"] == achievement_id), None)
        if ach:
            show_toast("Trophy unlocked!", ach["label"], "achievement")
            play_sound("achievement")
            add_xp(100)
            add_coins(30)
            spawn_confetti(40)



def all_assets():
    return STOCKS + ETFS


def find_asset(ticker):
    return next((s for s in all_assets() if s["ticker"] == ticker), None)


def portfolio_daily_pnl():
    total = 0.0
    for ticker, shares in state.holdings.items():
        if shares <= 0: continue
        a = find_asset(ticker)
        if a:
            baseline = a.get("live_previous_close") or a.get("open") or a["price"]
            total += (a["price"] - float(baseline)) * shares
    return total


def stock_snapshot(asset):
    price=float(asset.get("price",0)); hist=asset.get("history",[price])
    high=max(hist[-160:]) if hist else price; low=min(hist[-160:]) if hist else price
    prev=float(asset.get("live_previous_close") or asset.get("open") or price)
    move=((price-prev)/prev*100) if prev else 0.0
    rnd=random.Random(asset["ticker"]); eps=max(.45,price/rnd.uniform(14,34)); pe=price/eps if eps else 0
    div=float(asset.get("div",0)); dy=(div/price*100) if price else 0
    return {"move":move,"high":high,"low":low,"pe":pe,"div_yield":dy}


def asset_unlocked(asset):
    return state.level >= asset.get("unlock_level", 1) or net_worth() >= asset.get("unlock_worth", 0)


def sectors_owned():
    return {find_asset(t)["sector"] for t, q in state.holdings.items() if q > 0 and find_asset(t)}


def current_challenge():
    if state.challenge_day != time.strftime("%Y-%m-%d"):
        state.challenge_day = time.strftime("%Y-%m-%d")
        state.challenge_id = random.choice([c["id"] for c in DAILY_CHALLENGES])
        state.challenge_progress = 0
        state.challenge_claimed = False
    return next(c for c in DAILY_CHALLENGES if c["id"] == state.challenge_id)


def challenge_target():
    c = current_challenge()
    return c["goal"]


def update_challenge(event):
    c = current_challenge()
    if state.challenge_claimed:
        return
    matches = {
        "trade": c["id"] == "three_trades",
        "academy": c["id"] == "academy",
        "dividend": c["id"] == "dividend",
        "duel": c["id"] == "duel",
        "scam": c["id"] == "scam",
        "sectors": c["id"] == "two_sectors",
        "gym": c["id"] == "gym",
    }
    if matches.get(event, False):
        if event == "sectors":
            state.challenge_progress = len(sectors_owned())
        else:
            state.challenge_progress += 1
        if state.challenge_progress >= c["goal"]:
            state.challenge_progress = c["goal"]
            show_toast("Daily challenge complete!", f"Claim your +{c['reward']} XP reward in Academy.", "achievement")
            avatar_react("levelup", line="Daily challenge complete! Nice work.")
    save_game()


def claim_challenge():
    c = current_challenge()
    if state.challenge_progress >= c["goal"] and not state.challenge_claimed:
        state.challenge_claimed = True
        add_xp(c["reward"])
        add_coins(40)
        unlock("daily_challenge")
        show_toast("Challenge reward", f"+{c['reward']} XP claimed.", "achievement")
        save_game()
        return True
    return False


def choose_new_regime(now):
    choices = MARKET_REGIMES[:]
    state.market_regime = random.choice(choices)
    state.market_regime_until = now + random.uniform(45, 90)
    state.event_banner = f"{state.market_regime['icon']} {state.market_regime['name']}: {state.market_regime['desc']}"
    show_toast("Market regime changed", state.market_regime["name"], "duel")
    avatar_react("tip", line=f"Market mode: {state.market_regime['name']}. Watch how sectors react.")


def create_sector_news(now):
    event = random.choice(NEWS_EVENTS)
    direction = event["direction"]
    target_sector = random.choice(event["sectors"])
    affected = [a for a in STOCKS if a["sector"] == target_sector]
    if not affected:
        affected = [a for a in STOCKS if a["sector"] in event["sectors"]]
    sign = 1 if direction == "up" else -1
    affected_tickers = []
    for a in affected:
        # Apply the headline shock on the same tick the headline is published.
        # This keeps the news card and the chart movement synchronized.
        shock = sign * event["impact"] * SECTOR_IMPACT.get(a["sector"], 0.6)
        old = a["price"]
        a["prev_price"] = old
        a["price"] = max(0.5, round(old * (1 + shock), 2))
        a["news_pressure"] = 0.0
        a["flash_time"] = now
        a["flash_dir"] = "up" if a["price"] > old else "down"
        a["history"].append(a["price"])
        a["history"] = a["history"][-160:]
        affected_tickers.append(a["ticker"])
    item = {"ticker":"SECTOR", "headline":event["headline"], "direction":direction, "time":now,
            "lesson":event["lesson"], "sector":target_sector, "affected":affected_tickers}
    state.news_feed.insert(0, item)
    state.news_feed = state.news_feed[:20]
    state.last_news_time = now
    state.event_banner = event["headline"]
    avatar_react("news_up" if direction == "up" else "news_down")


def academy_complete(lesson_id):
    if lesson_id not in state.academy_completed:
        state.academy_completed.append(lesson_id)
        add_xp(35)
        add_coins(15)
        update_challenge("academy")
        save_game()


def scenario_answer(index):
    if getattr(state, "scenario_answered", False):
        return
    state.scenario_answered = True
    state.scenario_pick = index
    scenario = WHAT_WOULD_YOU_DO[state.scenario_index]
    if index == scenario.get("best", 1):
        add_xp(20)
        play_sound("achievement")
        spawn_confetti(25)
    else:
        add_xp(5)
        play_sound("click")
    save_game()


def next_scenario():
    state.scenario_answered = False
    state.scenario_pick = None
    state.scenario_index = (state.scenario_index + 1) % len(WHAT_WOULD_YOU_DO)
    state.lesson = "Tip: compare the choices with the risks before deciding."


# ----------------------------
# LIVE MARKET DATA
# ----------------------------
# Yahoo Finance's public chart/search endpoints provide current/historical quotes and
# headlines without putting an API key into the game. This is intended for a local,
# educational project. We cache aggressively so the game does not hammer the service.
LIVE_PRICE_REFRESH = 15.0
LIVE_NEWS_REFRESH = 90.0
LIVE_STOCK_BATCH = 10
LIVE_INITIAL_BATCH = 6
LIVE_QUOTE_TIMEOUT = 4.0
LIVE_WARMUP_TIMEOUT = 8.0
LIVE_HEADERS = {"User-Agent": "Mozilla/5.0 Ledger-Educational-Game/1.0"}
_live_lock = threading.Lock()
_live_price_running = False
_live_news_running = False
_live_price_queue = []
_live_news_queue = []


def _live_json(url, timeout=8):
    req = urllib.request.Request(url, headers=LIVE_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_one_live_quote(ticker):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(ticker) + "?range=1d&interval=1m&includePrePost=false&events=div%2Csplits"
    data = _live_json(url, timeout=LIVE_QUOTE_TIMEOUT)
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta", {})
    quote = ((result.get("indicators", {}).get("quote") or [{}])[0])
    closes = [float(x) for x in (quote.get("close") or []) if x is not None]
    timestamps = result.get("timestamp") or []
    current = meta.get("regularMarketPrice")
    if current is None and closes:
        current = closes[-1]
    previous = meta.get("previousClose") or meta.get("chartPreviousClose")
    if current is None:
        return None
    history = closes[-160:] if closes else [float(current)]
    return {
        "ticker": ticker,
        "price": float(current),
        "previous": float(previous) if previous is not None else None,
        "history": history,
        "timestamps": timestamps[-160:],
        "currency": meta.get("currency", "USD"),
        "exchange": meta.get("exchangeName", ""),
    }


def _refresh_live_prices_worker():
    global _live_price_running
    try:
        results = []
        # Keep the first batch broad enough to make the main recognizable stocks live,
        # then rotate through the rest on later refreshes.
        tickers = [s["ticker"] for s in STOCKS]
        start = int(time.time() / LIVE_PRICE_REFRESH) % max(1, len(tickers))
        rotated = tickers[start:] + tickers[:start]
        # Always prioritize the most recognizable names.
        priority = [t for t in ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "JPM", "WMT", "KO", "DIS") if t in tickers]
        batch = priority + [t for t in rotated if t not in priority]
        batch_size = LIVE_INITIAL_BATCH if not getattr(state, "live_first_quote_received", False) else LIVE_STOCK_BATCH
        selected = batch[:batch_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_fetch_one_live_quote, ticker) for ticker in selected]
            for future in concurrent.futures.as_completed(futures):
                try:
                    q = future.result()
                    if q:
                        results.append(q)
                except Exception:
                    continue
        with _live_lock:
            _live_price_queue[:] = results
    finally:
        _live_price_running = False


def request_live_price_refresh(force=False):
    global _live_price_running
    now = time.time()
    if not state.live_mode:
        return
    if not force and now - state.live_last_refresh < LIVE_PRICE_REFRESH:
        return
    if _live_price_running:
        return
    _live_price_running = True
    state.live_last_refresh = now
    threading.Thread(target=_refresh_live_prices_worker, daemon=True).start()


def _apply_live_prices(now):
    """Apply real quotes without manufacturing extra volatility between updates."""
    with _live_lock:
        results = list(_live_price_queue)
        _live_price_queue.clear()
    if not results:
        return

    changed = 0
    for q in results:
        asset = find_asset(q["ticker"])
        if not asset:
            continue
        old = float(asset.get("price", q["price"]))
        new = max(0.01, round(float(q["price"]), 2))
        asset["prev_price"] = old
        asset["price"] = new
        asset["display_price"] = new
        asset["flash_time"] = now if new != old else asset.get("flash_time", 0)
        asset["flash_dir"] = "up" if new > old else ("down" if new < old else asset.get("flash_dir"))

        # Keep the provider's real 1-minute history. Do not add random points between
        # provider updates; that was making the live market look artificially noisy.
        if q.get("history"):
            asset["history"] = [round(max(0.01, x), 2) for x in q["history"][-160:]]
        else:
            asset["history"].append(new)
            asset["history"] = asset["history"][-160:]
        asset["live_previous_close"] = q.get("previous")
        asset["live_currency"] = q.get("currency", "USD")
        asset["live_exchange"] = q.get("exchange", "")

        # A large real move is treated as an educational EVENT, not as normal
        # second-to-second behavior. We report the move without claiming that a
        # particular headline caused it.
        previous_close = q.get("previous")
        if previous_close and previous_close > 0:
            day_move = (new - float(previous_close)) / float(previous_close)
            if abs(day_move) >= 0.04 and now - asset.get("volatility_event_time", 0.0) > 300:
                asset["volatility_event_time"] = now
                direction = "up" if day_move > 0 else "down"
                pct = abs(day_move) * 100.0
                state.event_banner = f"VOLATILITY EVENT • {asset['ticker']} {pct:.1f}% {direction} today"
                state.news_feed.insert(0, {
                    "ticker": asset["ticker"],
                    "headline": f"High volatility detected in {asset['ticker']} ({pct:.1f}% vs. previous close).",
                    "direction": direction,
                    "time": now,
                    "lesson": "A large price move is unusual, but the price alone does not tell you why it happened. Check reliable news and company information before drawing conclusions.",
                    "sector": asset.get("sector", "Market"),
                    "real_news": False,
                    "volatility_event": True,
                })
                state.news_feed = state.news_feed[:20]
                notify_news(state.news_feed[0])

        changed += 1

    if changed:
        state.live_first_quote_received = True
        state.market_last_update_time = now
        state.live_status = f"LIVE • updated {time.strftime('%I:%M:%S %p').lstrip('0')}"
        state.live_error = ""


POSITIVE_NEWS_WORDS = {
    "beats", "beat", "strong", "growth", "grows", "surge", "surges", "soars", "soar",
    "rises", "rise", "record", "profit", "profits", "upgrade", "upgrades", "positive",
    "launch", "launches", "success", "successful", "approval", "approved", "partnership",
    "deal", "deals", "expands", "expansion", "demand", "bullish", "raises", "raised",
}
NEGATIVE_NEWS_WORDS = {
    "misses", "miss", "weak", "decline", "declines", "falls", "fall", "drops", "drop",
    "loss", "losses", "downgrade", "downgrades", "negative", "lawsuit", "investigation",
    "warning", "warns", "cuts", "cut", "layoffs", "delay", "delays", "recall", "recalls",
    "slump", "slumps", "bearish", "concern", "concerns", "disappointing",
}

def classify_news_direction(headline):
    words = set(re.findall(r"[a-z]+", headline.lower()))
    positive = len(words & POSITIVE_NEWS_WORDS)
    negative = len(words & NEGATIVE_NEWS_WORDS)
    if positive > negative:
        return "up"
    if negative > positive:
        return "down"
    return "neutral"


def _fetch_news_for_ticker(ticker):
    query = urllib.parse.quote(ticker)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=1&newsCount=5&enableFuzzyQuery=false&quotesQueryId=tss_match_phrase_query"
    data = _live_json(url)
    out = []
    for item in data.get("news", [])[:5]:
        title = str(item.get("title") or "").strip()
        if not title or not ledger_safety.headline_is_kid_safe(title):
            continue
        ts = item.get("providerPublishTime") or time.time()
        out.append({
            "ticker": ticker,
            "headline": title,
            "direction": classify_news_direction(title),
            "time": float(ts),
            "lesson": "News can change what investors expect, but a headline does not guarantee a stock will rise or fall.",
            "sector": (find_asset(ticker) or {}).get("sector", "Market"),
            "source": str(item.get("publisher") or "Yahoo Finance"),
            "url": str(item.get("link") or ""),
            "real_news": True,
        })
    return out


def _refresh_live_news_worker():
    global _live_news_running
    try:
        # News for the recognizable names; this is deliberately cached to avoid excessive requests.
        tickers = [t for t in ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "NFLX", "JPM", "WMT", "KO", "DIS") if find_asset(t)]
        items = []
        for ticker in tickers:
            try:
                items.extend(_fetch_news_for_ticker(ticker))
            except Exception:
                continue
        items.sort(key=lambda x: x.get("time", 0), reverse=True)
        with _live_lock:
            _live_news_queue[:] = items[:20]
    finally:
        _live_news_running = False


def request_live_news_refresh(force=False):
    global _live_news_running
    now = time.time()
    if not state.live_mode:
        return
    if not force and now - state.live_last_news_refresh < LIVE_NEWS_REFRESH:
        return
    if _live_news_running:
        return
    _live_news_running = True
    state.live_last_news_refresh = now
    threading.Thread(target=_refresh_live_news_worker, daemon=True).start()


def _apply_live_news(now):
    with _live_lock:
        items = list(_live_news_queue)
        _live_news_queue.clear()
    if not items:
        return
    # Real quotes remain the price truth. The headline gets a simple educational
    # sentiment tag so the player can compare "good/bad news" with the actual move.
    # We never pretend a headline automatically caused a move in the real market.
    for item in items:
        asset = find_asset(item["ticker"])
        if asset:
            prev = asset.get("live_previous_close")
            quote_direction = "neutral"
            if prev and prev > 0:
                delta = (asset["price"] - float(prev)) / float(prev)
                quote_direction = "up" if delta > 0.0001 else ("down" if delta < -0.0001 else "neutral")
            item["quote_direction"] = quote_direction
            item["sentiment_direction"] = classify_news_direction(item.get("headline", ""))
            item["lesson"] = "Compare the headline with the price move. Good news often supports higher expectations and bad news often hurts expectations, but real prices can react differently because markets price in many factors."
    known = {news_item_id(it): it for it in state.news_feed}
    first_batch = not known
    fresh = []
    for item in items:
        old = known.get(news_item_id(item))
        if old:
            item["arrived"] = old.get("arrived", 0.0)
            if "price_at" in old:
                item["price_at"] = old["price_at"]
        else:
            item["arrived"] = 0.0 if first_batch else now
            if not first_batch:
                fresh.append(item)
        stamp_news(item)
    state.news_feed = items[:20]
    if fresh:
        notify_news(fresh[0])
    state.live_status = state.live_status if state.live_status.startswith("LIVE") else "LIVE market news connected"


def tick_live_market():
    now = time.time()
    request_live_price_refresh()
    request_live_news_refresh()
    before_status = state.live_status
    _apply_live_prices(now)
    _apply_live_news(now)
    if (before_status == state.live_status and state.live_started_at and
            not state.live_first_quote_received and now - state.live_started_at > LIVE_WARMUP_TIMEOUT and
            not state.live_status.startswith("LIVE")):
        state.live_error = "Live market data could not be reached. Using the educational simulation instead."
        state.live_mode = False
        state.live_status = "SIMULATION • offline fallback"

def maybe_start_market_event(now):
    """Occasionally create a named educational event in the offline market."""
    if state.active_market_event and now < state.market_event_until:
        return
    if now - getattr(state, "last_market_event_time", 0.0) < getattr(state, "market_event_cooldown", 38.0):
        return
    if random.random() > 0.055:
        return

    event = dict(random.choice(MARKET_EVENTS))
    target = None
    if event["kind"] in ("stock", "sector"):
        target = random.choice(STOCKS)
        event["ticker"] = target["ticker"]
        event["sector"] = target["sector"]
    elif event["kind"] == "market":
        event["ticker"] = "MARKET"
        event["sector"] = "Broad Market"
    else:
        event["ticker"] = "MARKET"
        event["sector"] = "Volatility"

    event["started_at"] = now
    state.active_market_event = event
    state.market_event_until = now + event["duration"]
    state.last_market_event_time = now
    state.market_event_count = getattr(state, "market_event_count", 0) + 1
    state.event_banner = f"MARKET EVENT • {event['title']}"
    state.lesson = event["lesson"]

    if event["kind"] == "stock" and target:
        direction = "up" if event["bias"] > 0 else "down"
        state.news_feed.insert(0, {
            "ticker": target["ticker"], "headline": f"{event['headline']} ({target['ticker']})",
            "direction": direction, "time": now, "lesson": event["lesson"],
            "sector": target["sector"], "real_news": False, "event": event["title"]
        })
    else:
        state.news_feed.insert(0, {
            "ticker": event["ticker"], "headline": event["headline"],
            "direction": "up" if event["bias"] > 0 else ("down" if event["bias"] < 0 else "flat"),
            "time": now, "lesson": event["lesson"], "sector": event["sector"],
            "real_news": False, "event": event["title"]
        })
    state.news_feed = state.news_feed[:20]
    notify_news(state.news_feed[0])


SIM_SCALE = 12.0  # how lively the practice market is; higher = bigger swings
MARKET_TICK_SECONDS = 1.0  # one calm price step per second; charts animate smoothly in between


def day_move_pct(asset):
    """Percent move since the open (or previous close for live quotes), not since the last tick."""
    price = float(asset.get("price", 0) or 0)
    base = float(asset.get("live_previous_close") or asset.get("open") or price or 0)
    return (price - base) / base * 100 if base else 0.0


def smooth_chart_args():
    """Chart animation settings for per-tick simulated histories (off for live quotes)."""
    if getattr(state, "live_mode", False):
        return {}
    return {"tick_at": state.last_tick, "tick_len": MARKET_TICK_SECONDS}


def tick_market():
    """Update prices in a way that teaches normal movement vs. rare events.

    Live mode uses provider quotes only. Offline mode uses a deliberately low-volatility
    simulation: tiny second-to-second changes, mild market/sector drift, and rare
    event-driven moves. It does NOT create a random percentage jump every second.
    """
    if getattr(state, "live_mode", False):
        tick_live_market()
        if state.live_error:
            # Keep the educational simulation available when the network is unavailable.
            # The simulation itself is intentionally calm; it is not a random roller coaster.
            state.live_mode = False
            state.live_status = "SIMULATION • offline fallback"
        else:
            return

    now = time.time()

    maybe_start_market_event(now)
    update_hype(now)
    active_event = state.active_market_event if state.active_market_event and now < state.market_event_until else None
    if state.active_market_event and not active_event:
        state.active_market_event = None
        state.event_banner = "Market event ended • conditions returned toward normal."

    # Normal market behavior: mean-reverting tiny movements. These values are per
    # one-second game tick, so ordinary movement stays small.
    if not hasattr(state, "sim_market_trend"):
        state.sim_market_trend = random.uniform(-0.00004, 0.00004) * SIM_SCALE
    state.sim_market_trend = max(
        -0.00012 * SIM_SCALE, min(0.00012 * SIM_SCALE,
        state.sim_market_trend * 0.94 + random.gauss(0.0, 0.000015 * SIM_SCALE))
    )

    sectors = {s["sector"] for s in STOCKS}
    for sector in sectors:
        old = state.sector_trends.get(sector, 0.0)
        state.sector_trends[sector] = max(
            -0.00028 * SIM_SCALE, min(0.00028 * SIM_SCALE,
            old * 0.91 + random.gauss(0.0, 0.000029 * SIM_SCALE))
        )

    # Rare event-driven volatility. The normal market does not do this.
    # An event is separated from ordinary movement so children can learn that
    # unusually large moves usually need an unusual reason.
    news_allowed = (now - state.last_news_time) >= 40.0
    event_stock = None
    if news_allowed and random.random() < 0.008:
        event_stock = random.choice(STOCKS)

    for s in STOCKS:
        s["prev_price"] = s["price"]

        # Normal movement is based on the stock's baseline volatility, scaled down
        # heavily because the game ticks every second.
        event_vol = active_event.get("vol_mult", 1.0) if active_event else 1.0
        event_bias = active_event.get("bias", 0.0) if active_event else 0.0
        applies = False
        if active_event:
            if active_event.get("kind") == "market":
                applies = True
            elif active_event.get("kind") == "sector" and s.get("sector") == active_event.get("sector"):
                applies = True
            elif active_event.get("kind") == "stock" and s.get("ticker") == active_event.get("ticker"):
                applies = True
            elif active_event.get("kind") == "volatility":
                applies = True
        noise_mult = event_vol if (applies and event_bias == 0) else 1.0
        stock_noise = random.gauss(0.0, max(0.000024, s.get("vol", 0.006) * 0.034) * SIM_SCALE * noise_mult)
        event_drift = (event_bias * random.uniform(0.00018, 0.00055) * SIM_SCALE) if applies else 0.0
        change = state.sim_market_trend + state.sector_trends.get(s["sector"], 0.0) + stock_noise + event_drift

        if event_stock is s:
            direction = random.choice([-1, 1])
            event_size = random.uniform(0.03, 0.07) * direction
            change += event_size
            if direction > 0:
                headline = random.choice([
                    f"{s['name']} reports stronger-than-expected demand, lifting investor expectations.",
                    f"{s['name']} shares get a boost after encouraging company news.",
                    f"Positive {s['name']} update improves the market's outlook for the company.",
                ])
            else:
                headline = random.choice([
                    f"{s['name']} reports a setback that weighs on investor expectations.",
                    f"{s['name']} shares slide after disappointing company news.",
                    f"Negative {s['name']} update puts pressure on the market's outlook for the company.",
                ])
            state.news_feed.insert(0, {
                "ticker": s["ticker"],
                "headline": headline,
                "direction": "up" if direction > 0 else "down",
                "time": now,
                "lesson": "Large moves are unusual. Look for a reason—such as earnings, guidance, a major product update, or another material event—rather than assuming every price change is normal.",
                "sector": s["sector"],
                "real_news": False,
            })
            state.news_feed = state.news_feed[:20]
            state.last_news_time = now
            state.event_banner = f"MARKET EVENT • {s['ticker']} moved sharply"
            s["news_pressure"] = event_size * 0.12
            notify_news(state.news_feed[0], price_at=s["price"])
        else:
            # Any event effect fades quickly instead of creating a prolonged random trend.
            lingering_news = s.get("news_pressure", 0.0)
            change += lingering_news
            s["news_pressure"] = lingering_news * 0.9

        # Prevent an ordinary tick from becoming a fake volatility event.
        change = max(-0.02, min(0.02, change))
        change = hype_price_change(s, change)
        new_price = max(0.50, round(s["price"] * (1.0 + change), 2))
        s["price"] = new_price
        s["display_price"] = new_price
        s["history"].append(new_price)
        s["history"] = s["history"][-160:]
        if new_price != s["prev_price"]:
            s["flash_time"] = now
            s["flash_dir"] = "up" if new_price > s["prev_price"] else "down"

    # ETFs follow their underlying stocks and broad market trend, with lower noise.
    for e in ETFS:
        e["prev_price"] = e["price"]
        member_moves = []
        for ticker in e["members"]:
            m = find_asset(ticker)
            if m and m["prev_price"]:
                member_moves.append((m["price"] - m["prev_price"]) / m["prev_price"])
        basket_move = sum(member_moves) / len(member_moves) if member_moves else 0.0
        noise = random.gauss(0.0, max(0.00001, e.get("vol", 0.004) * 0.012) * SIM_SCALE)
        event_drift = 0.0
        if active_event and active_event.get("kind") in ("market", "volatility"):
            event_drift = active_event.get("bias", 0.0) * 0.00016 * SIM_SCALE
            noise *= active_event.get("vol_mult", 1.0)
        change = basket_move * 0.75 + state.sim_market_trend * 0.45 + noise + event_drift
        change = max(-0.01, min(0.01, change))
        e["price"] = max(1.0, round(e["price"] * (1.0 + change), 2))
        e["display_price"] = e["price"]
        e["history"].append(e["price"])
        e["history"] = e["history"][-160:]
        if e["price"] != e["prev_price"]:
            e["flash_time"] = now
            e["flash_dir"] = "up" if e["price"] > e["prev_price"] else "down"

# ----------------------------
# HYPE BUBBLES
# ----------------------------
# Every several minutes the made-up meme stock MOON goes through a full bubble:
# buzz -> mania -> peak -> crash -> hangover, with social-media style posts in News.
# It only runs in the offline simulation; live quotes are never altered.

HYPE_TICKER = "MOON"
HYPE_PHASES = [  # (phase, seconds, average move per tick, randomness per tick)
    ("buzz", 18, 0.012, 0.008),
    ("mania", 30, 0.035, 0.020),
    ("peak", 8, 0.000, 0.030),
    ("crash", 20, -0.060, 0.025),
    ("hangover", 25, -0.004, 0.012),
]
HYPE_POSTS = {
    "buzz": ("up", "MoonChat is trending. Posts everywhere say 'MOON to the moon!' Nobody is talking about its profits."),
    "mania": ("up", "MOON is soaring. Influencers post rocket memes and 'can't lose' screenshots. Everyone wants in."),
    "peak": ("up", "MOON's chart is nearly vertical. Early buyers are quietly selling to latecomers."),
    "crash": ("down", "MOON is collapsing as the hype fades. Latecomers are stuck with big losses."),
}
HYPE_CHATTER = [
    "'MOON only goes up!' is the top comment on every MoonChat video.",
    "A classmate says they put all their savings into MOON. 'It's a sure thing.'",
    "Someone posts a screenshot: '+300% on MOON!!' Thousands of likes.",
]
hype = {"phase_i": -1, "phase_until": 0.0, "next_at": None, "start": 0.0, "peak": 0.0, "last_chatter": 0.0}


def hype_active():
    return hype["phase_i"] >= 0


def _hype_news(moon, direction, headline, notify=True, event="Hype watch"):
    item = {"ticker": HYPE_TICKER, "headline": headline, "direction": direction, "time": time.time(),
            "lesson": "Hype can push a price far above what a business is worth. When the buying stops, it can fall just as fast.",
            "sector": moon.get("sector", "Social Media"), "real_news": False, "event": event}
    state.news_feed.insert(0, item)
    state.news_feed = state.news_feed[:20]
    if notify:
        notify_news(item, price_at=moon["price"])
    else:
        stamp_news(item)


def update_hype(now):
    moon = find_asset(HYPE_TICKER)
    if not moon or getattr(state, "live_mode", False):
        return
    if hype["next_at"] is None:
        hype["next_at"] = now + random.uniform(150, 300)
    if not hype_active():
        if now >= hype["next_at"]:
            hype.update(phase_i=0, start=moon["price"], peak=moon["price"])
            _enter_hype_phase(now, moon)
        return
    hype["peak"] = max(hype["peak"], moon["price"])
    if now >= hype["phase_until"]:
        hype["phase_i"] += 1
        if hype["phase_i"] >= len(HYPE_PHASES):
            _finish_hype(now, moon)
        else:
            _enter_hype_phase(now, moon)
    elif HYPE_PHASES[hype["phase_i"]][0] == "mania" and now - hype["last_chatter"] > 9:
        hype["last_chatter"] = now
        _hype_news(moon, "up", random.choice(HYPE_CHATTER), notify=False)


def _enter_hype_phase(now, moon):
    name, secs, _, _ = HYPE_PHASES[hype["phase_i"]]
    hype["phase_until"] = now + secs
    hype["last_chatter"] = now
    post = HYPE_POSTS.get(name)
    if post:
        _hype_news(moon, post[0], post[1], notify=name in ("buzz", "crash"))
    if name == "buzz":
        state.event_banner = "HYPE WATCH • MOON is trending on social media"
    elif name == "crash":
        state.event_banner = "HYPE WATCH • The MOON bubble is popping"


def _finish_hype(now, moon):
    start, peak, end = hype["start"], hype["peak"], moon["price"]
    hype.update(phase_i=-1, next_at=now + random.uniform(420, 720))
    _hype_news(moon, "down", f"Bubble post-mortem: MOON went {fmt_money(start)} -> {fmt_money(peak)} -> {fmt_money(end)}. "
               "Hype isn't a business plan.", event="Bubble post-mortem")
    state.lesson = "Bubbles: prices driven by hype, not profits, usually come back down. FOMO buyers get hurt most."
    unlock("bubble_watch")


def hype_price_change(asset, change):
    """During a bubble, MOON follows the hype script instead of normal market noise."""
    if asset["ticker"] != HYPE_TICKER or not hype_active():
        return change
    _, _, drift, noise = HYPE_PHASES[hype["phase_i"]]
    return max(-0.15, min(0.15, drift + random.gauss(0.0, noise)))


# Ledger's clock runs fast: an hour of play moves prices about as much as five months of
# real trading. Paying a full quarterly dividend every 45-second payday made "buy KO and
# wait" beat every trading strategy, so each payday pays a matching slice of it instead.
DIVIDEND_SLICE = 0.025


def check_dividends():
    now = time.time()
    if now - state.last_dividend_time >= state.dividend_interval:
        state.last_dividend_time = now
        owed = getattr(state, "dividend_accrual", 0.0)
        stocks_paying = 0
        for ticker, shares in state.holdings.items():
            if shares > 0:
                asset = find_asset(ticker)  # ETFs pay too
                if asset and asset.get("div", 0) > 0:
                    owed += asset["div"] * shares * DIVIDEND_SLICE
                    stocks_paying += 1
        boosted = owed >= 0.01 and consume_boost("payday")
        if boosted:
            owed *= 1.5
        total_payout = round(math.floor(owed * 100 + 1e-9) / 100, 2)
        # Fractions of a cent carry over to the next payday instead of vanishing.
        state.dividend_accrual = (owed - total_payout) if stocks_paying else 0.0
        if total_payout > 0:
            state.cash = round(state.cash + total_payout, 2)
            state.total_dividends = round(state.total_dividends + total_payout, 2)
            show_toast("Dividend Payday!" + (" (Boosted +50%)" if boosted else ""),
                       f"+{fmt_money(total_payout)} from {stocks_paying} holding{'s' if stocks_paying != 1 else ''}. Small, but steady!", "dividend")
            play_sound("dividend")
            spawn_cash_text(total_payout, WIDTH // 2, 200)
            avatar_react("dividend")
            add_xp(30)
            update_challenge("dividend")
            unlock("dividend_earned")


def check_achievements():
    nw = net_worth()
    if nw >= 1100:
        unlock("profit_10")
    if nw >= 2000:
        unlock("mogul")
    if sum(1 for shares in state.holdings.values() if shares > 0) >= 3:
        unlock("diversify")
    if len(state.academy_completed) >= 5:
        unlock("academy_5")


# ----------------------------
# TRADE REASONS + BIAS RADAR
# ----------------------------
# Before buying, the player can say WHY. Ledger remembers the reason, scores it when the
# position is sold, and watches for classic beginner mistakes (FOMO, panic selling,
# revenge trading, overtrading, putting everything in one stock).

TRADE_REASONS = [
    ("news", "News"), ("trend", "Chart trend"), ("research", "Did research"),
    ("dividend", "Dividends"), ("diversify", "Diversify"), ("hype", "Hype / FOMO"),
]
TRADE_REASON_LABELS = dict(TRADE_REASONS, auto="Auto-invest")
TRADE_REASON_IDS = set(TRADE_REASON_LABELS)
TRADE_LOG_MAX = 300
PERF_SAMPLE_SECONDS = 10.0
PERF_HISTORY_MAX = 1500  # about four hours of play

BIASES = {
    "fomo": ("FOMO buy", "You bought right after a big jump. Chasing a hot stock often means buying near the top."),
    "panic": ("Panic sell", "You sold at a loss right after a drop. Did your reason for owning it change, or just the price?"),
    "revenge": ("Revenge trade", "You jumped back in right after a loss. Trying to win it back fast leads to sloppy trades."),
    "overtrading": ("Overtrading", "Lots of trades in a few minutes. More trades don't mean more profit."),
    "all_in": ("All eggs, one basket", "Over half your money is now in one stock. One bad day there could sink everything."),
}
BIAS_TOAST_GAP = 20.0


def recent_move_pct(asset, ticks=30):
    """Percent move over the last few simulation ticks."""
    hist = asset.get("history") or []
    if len(hist) < 2:
        return 0.0
    base = hist[-min(len(hist), ticks + 1)]
    return (asset["price"] - base) / base * 100 if base else 0.0


def _trades_in_last(seconds):
    now = time.time()
    return sum(1 for t in state.trade_log if now - t.get("t", 0) < seconds)


def log_trade(side, asset, qty, price, reason=None, pnl=None, biases=()):
    entry = {"t": round(time.time(), 1), "side": side, "ticker": asset["ticker"], "qty": round(qty, 4),
             "price": round(price, 2), "reason": reason}
    if pnl is not None:
        entry["pnl"] = round(pnl, 2)
    if biases:
        entry["biases"] = list(biases)
    state.trade_log.append(entry)
    del state.trade_log[:-TRADE_LOG_MAX]
    return entry


def detect_buy_biases(asset, reason):
    """Call after the shares are added, so the one-stock check sees the new position."""
    found = []
    if reason == "hype" or day_move_pct(asset) >= 3.0 or recent_move_pct(asset) >= 2.0:
        found.append("fomo")
    last_sell = next((t for t in reversed(state.trade_log) if t.get("side") == "sell"), None)
    if last_sell and last_sell.get("pnl", 0) < 0 and time.time() - last_sell.get("t", 0) < 45:
        found.append("revenge")
    if _trades_in_last(300) >= 7:
        found.append("overtrading")
    nw = net_worth()
    if nw > 0 and asset.get("sector") != "ETF" and state.holdings.get(asset["ticker"], 0) * asset["price"] / nw > 0.5:
        found.append("all_in")
    return found


def detect_sell_biases(asset, pnl):
    found = []
    if pnl < 0 and (recent_move_pct(asset, 20) <= -1.5 or day_move_pct(asset) <= -3.0):
        found.append("panic")
    if _trades_in_last(300) >= 7:
        found.append("overtrading")
    return found


def note_biases(found):
    """Count detected biases. Returns True if a Bias Radar toast was shown."""
    for b in found:
        state.bias_counts[b] = state.bias_counts.get(b, 0) + 1
    now = time.time()
    if found and now - state.last_bias_toast >= BIAS_TOAST_GAP:
        state.last_bias_toast = now
        title, tip = BIASES[found[0]]
        show_toast(f"Bias Radar  •  {title}", tip, "warning")
        return True
    return False


def do_buy(stock, qty, reason=None):
    qty = round(float(qty), 4)
    if qty <= 0:
        return False
    cost = stock["price"] * qty
    if cost > state.cash + 0.005:
        show_toast("Not enough cash", f"You need {fmt_money(cost)} but have {fmt_money(state.cash)}", "warning")
        play_sound("error")
        return False

    current_owned = state.holdings.get(stock["ticker"], 0)
    old_avg = state.avg_buy_price.get(stock["ticker"], stock["price"])
    state.avg_buy_price[stock["ticker"]] = ((old_avg * current_owned) + (stock["price"] * qty)) / (current_owned + qty)
    state.cash = max(0.0, round(state.cash - cost, 2))
    state.holdings[stock["ticker"]] = round(current_owned + qty, 4)
    state.trade_count += 1
    state.session_trades = getattr(state, "session_trades", 0) + 1
    add_recent_action(f"Bought {qty:g} {stock['ticker']}")
    update_challenge("trade")
    if stock["ticker"] not in state.hold_since:
        state.hold_since[stock["ticker"]] = time.time()
    if reason:
        state.theses[stock["ticker"]] = reason
    biases = detect_buy_biases(stock, reason)
    log_trade("buy", stock, qty, stock["price"], reason, biases=biases)

    state.lesson = f"Lesson: a share means you own a tiny piece of {stock['name']}."
    if not note_biases(biases):
        if reason:
            show_toast(f"Bought  •  reason: {TRADE_REASON_LABELS[reason]}", "Saved to your Trade Journal. Check later if your reason was right.", "buy")
        else:
            show_toast("Trade complete • Lesson", "Owning shares makes your value move with the price.", "buy")
    play_sound("trade")
    spawn_cash_text(-cost, WIDTH // 2, 230)
    spawn_sparks(WIDTH // 2, 250, C("ORANGE"), 18)
    avatar_react("buy")
    add_xp(20 if reason else 15)
    unlock("first_buy")
    if sum(1 for t in state.trade_log if t.get("side") == "buy" and t.get("reason") not in (None, "auto")) >= 10:
        unlock("thesis_10")
    save_game()
    return True


def do_sell(stock, qty, via=None):
    qty = round(float(qty), 4)
    owned = state.holdings.get(stock["ticker"], 0)
    if qty <= 0:
        return False
    if owned < qty < owned + 1e-4:
        qty = owned  # rounding dust: selling "all" of 2.9999999 shares must not be refused
    if qty > owned:
        show_toast("You don't own that many", f"You only have {owned:g} share{'s' if owned != 1 else ''}", "warning")
        play_sound("error")
        return False

    proceeds = stock["price"] * qty
    avg_price = state.avg_buy_price.get(stock["ticker"], stock["price"])
    pnl = proceeds - (avg_price * qty)
    state.realized_pnl[stock["ticker"]] = round(
        state.realized_pnl.get(stock["ticker"], 0.0) + pnl, 2
    )

    review = trade_review(stock, pnl, avg_price)
    state.trade_reviews.insert(0, review)
    del state.trade_reviews[10:]
    # Stop-loss / take-profit sales follow a plan made in advance, so they are not panic.
    biases = [] if via else detect_sell_biases(stock, pnl)
    reason = state.theses.get(stock["ticker"])
    if reason:
        rs = state.reason_stats.setdefault(reason, {"n": 0, "wins": 0, "pnl": 0.0})
        rs["n"] += 1
        rs["wins"] += 1 if pnl > 0 else 0
        rs["pnl"] = round(rs["pnl"] + pnl, 2)
    log_trade("sell", stock, qty, stock["price"], via or reason, pnl=pnl, biases=biases)
    state.cash = round(state.cash + proceeds, 2)
    state.holdings[stock["ticker"]] = round(owned - qty, 4)
    state.trade_count += 1
    state.session_trades = getattr(state, "session_trades", 0) + 1
    add_recent_action(f"Sold {qty:g} {stock['ticker']}")
    update_challenge("trade")
    if state.holdings[stock["ticker"]] <= 0.00001:
        state.holdings[stock["ticker"]] = 0
        state.hold_since.pop(stock["ticker"], None)
        state.avg_buy_price.pop(stock["ticker"], None)
        state.theses.pop(stock["ticker"], None)

    start_trade_fx(pnl)
    if pnl >= 10:
        add_coins(min(20, int(pnl // 10)), x=WIDTH // 2, y=420)
    state.lesson = "Coach: " + review
    if not note_biases(biases):
        show_toast("Trade review", review, "sell")
    avatar_react("profit" if pnl >= 0 else "loss")
    avatar_emote("dance" if pnl >= 0.01 else ("shrug" if pnl <= -0.01 else "nod"))
    add_xp(15)
    save_game()
    return True


# ----------------------------
# MONEY FX (avatar taps, profit / loss celebrations)
# ----------------------------

def _rotated_rect_points(cx, cy, w, h, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        pts.append((cx + dx * ca - dy * sa, cy + dx * sa + dy * ca))
    return pts


class DollarBill:
    """A little green bill that flutters as it flies or rains down."""

    def __init__(self, x, y, rain=False):
        self.x, self.y = x, y
        self.rain = rain
        self.vx = random.uniform(-0.6, 0.6) if rain else random.uniform(-3.4, 3.4)
        self.vy = random.uniform(1.6, 3.2) if rain else random.uniform(-7.5, -3.5)
        self.rot = random.uniform(0, 360)
        self.vrot = random.uniform(-7, 7)
        self.phase = random.uniform(0, 6.28)
        self.life = 1.0
        self.decay = 0.009 if rain else 0.014

    def update(self):
        self.phase += 0.12
        self.x += self.vx + math.sin(self.phase) * (1.1 if self.rain else 0.5)
        self.y += self.vy
        self.vy = min(3.4, self.vy + (0.03 if self.rain else 0.22))
        self.rot += self.vrot
        self.life -= self.decay

    def draw(self, surface):
        if self.life <= 0:
            return
        k = min(1.0, self.life / 0.25)
        flip = abs(math.cos(self.phase * 0.7))  # the bill twists as it falls
        w, h = 22 * k, 12 * k * (0.35 + 0.65 * flip)
        pygame.draw.polygon(surface, (38, 150, 80), _rotated_rect_points(self.x, self.y, w, h, self.rot))
        pygame.draw.polygon(surface, (120, 210, 140), _rotated_rect_points(self.x, self.y, w * 0.72, h * 0.6, self.rot), 1)
        pygame.draw.circle(surface, (120, 210, 140), (self.x, self.y), max(1.0, 2.6 * k * flip))


class GoldCoin:
    """A spinning gold coin."""

    def __init__(self, x, y, vx=None, vy=None):
        self.x, self.y = x, y
        self.vx = random.uniform(-3.8, 3.8) if vx is None else vx
        self.vy = random.uniform(-9, -4) if vy is None else vy
        self.spin = random.uniform(0, 6.28)
        self.life = 1.0
        self.r = random.uniform(6, 8.5)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.3
        self.spin += 0.35
        self.life -= 0.016

    def draw(self, surface):
        if self.life <= 0:
            return
        w = max(1.5, self.r * 2 * abs(math.cos(self.spin)))
        rect = pygame.Rect(0, 0, w, self.r * 2)
        rect.center = (self.x, self.y)
        pygame.draw.ellipse(surface, (214, 150, 0), rect)
        pygame.draw.ellipse(surface, (255, 204, 40), rect.inflate(-max(1, w * 0.3), -3))


class ChartPop:
    """A tiny stock-quote card that pops out of the avatar, draws its chart, then floats away."""
    W, H = 124, 62

    def __init__(self, x, y):
        self.x, self.y0 = x, y
        asset = self._pick_asset()
        self.ticker = asset["ticker"]
        # Real in-game data: the stock's recent price history and today's move.
        hist = [float(v) for v in asset.get("history", [])[-24:]]
        if len(hist) < 4 or max(hist) == min(hist):
            hist = [float(asset.get("open") or asset["price"]), float(asset["price"])]
        self.data = hist
        self.pct = day_move_pct(asset)
        self.up = self.pct >= 0
        self.born = time.time()
        self.duration = 1.9
        self.life = 1.0
        self._card = None

    @staticmethod
    def _pick_asset():
        """Prefer stocks you own or watch; otherwise any unlocked stock that has been moving."""
        mine = [find_asset(t) for t, q in state.holdings.items() if q > 0] + [find_asset(t) for t in getattr(state, "watchlist", [])]
        mine = [a for a in mine if a]
        pool = mine if mine and random.random() < 0.7 else [a for a in STOCKS if asset_unlocked(a)] or STOCKS
        moving = [a for a in pool if len(a.get("history", [])) > 4 and max(a["history"][-24:]) != min(a["history"][-24:])]
        return random.choice(moving or pool)

    def update(self):
        self.life = 1.0 - (time.time() - self.born) / self.duration

    def _build_card(self):
        w, h = self.W, self.H
        col = C("GREEN") if self.up else C("RED")
        card = HiSurface((w, h + 8), pygame.SRCALPHA)
        pygame.draw.rect(card, (*C("CARD"), 255), (0, 0, w, h), border_radius=12)
        pygame.draw.rect(card, (*col, 255), (0, 0, w, h), 2, border_radius=12)
        pygame.draw.polygon(card, (*C("CARD"), 255), [(w // 2 - 7, h - 2), (w // 2 + 7, h - 2), (w // 2, h + 7)])
        pygame.draw.lines(card, (*col, 255), False, [(w // 2 - 7, h - 1), (w // 2, h + 6), (w // 2 + 7, h - 1)], 2)
        bg, _ = brand_colors(self.ticker)
        pygame.draw.circle(card, (*bg, 255), (13, 13), 5)
        draw_text(card, self.ticker, font_tiny, C("INK"), 22, 5)
        draw_text(card, f"{self.pct:+.1f}%", font_tiny, col, w - 9, 5, align="right")
        self._card = card
        # Chart points in card coordinates.
        lo, hi = min(self.data), max(self.data)
        self._pts = [(8 + i * (w - 16) / (len(self.data) - 1), 26 + (h - 34) * (1 - (v - lo) / ((hi - lo) or 1)))
                     for i, v in enumerate(self.data)]

    def draw(self, surface):
        age = time.time() - self.born
        if age >= self.duration:
            return
        if self._card is None:
            self._build_card()
        w, h = self.W, self.H
        col = C("GREEN") if self.up else C("RED")
        layer = self._card.copy()
        reveal = ease_out_cubic((age - 0.15) / 0.7)
        if reveal > 0:
            n = len(self._pts)
            f = reveal * (n - 1)
            k = int(f)
            pts = self._pts[:k + 1]
            if k < n - 1:
                a, b = self._pts[k], self._pts[k + 1]
                pts = pts + [(a[0] + (b[0] - a[0]) * (f - k), a[1] + (b[1] - a[1]) * (f - k))]
            if len(pts) > 1:
                cl = HiSurface(layer.get_size(), pygame.SRCALPHA)
                pygame.draw.polygon(cl, (*col, 45), pts + [(pts[-1][0], h - 6), (pts[0][0], h - 6)])
                pygame.draw.lines(cl, (*col, 255), False, pts, 2)
                pygame.draw.circle(cl, (*col, 255), pts[-1], 3)
                layer.blit(cl, (0, 0))
        pop = min(1.0, age / 0.18)
        scale = 0.6 + 0.4 * (1 - (1 - pop) ** 3) + 0.06 * math.sin(pop * math.pi)  # little overshoot
        fade = 1.0 if age < self.duration - 0.45 else max(0.0, (self.duration - age) / 0.45)
        rise = 34 * ease_out_cubic(age / self.duration)
        img = layer.hi
        if abs(scale - 1.0) > 0.01:
            img = pygame.transform.smoothscale(img, (max(2, int(img.get_width() * scale)), max(2, int(img.get_height() * scale))))
        img.set_alpha(int(255 * fade))
        out = HiSurface(None, hi=img)
        surface.blit(out, (self.x - out.get_width() / 2, self.y0 - rise - out.get_height()))


AVATAR_TAP_LINES = ["Cha-ching!", "Buy low, sell high!", "Stonks!", "Diversify!", "To the moon!", "Bull mode!", "Invest in yourself!"]


def spawn_money_burst(x, y, bills=5, coins=7):
    if getattr(state, "reduced_motion", False):
        return
    for _ in range(bills):
        particles.append(DollarBill(x, y))
    for _ in range(coins):
        particles.append(GoldCoin(x, y))


def avatar_money_fx(pos):
    """Tapping your trader throws cash and pops little stock charts."""
    x, y = pos
    n = avatar_anim.get("pokes", 1)
    spawn_money_burst(x, y, 4 + (n % 3), 6)
    # One chart OR one catchphrase at a time so rapid taps stay readable.
    floating_texts[:] = [f for f in floating_texts if not getattr(f, "avatar_tap", False)]
    if not getattr(state, "reduced_motion", False) and not any(isinstance(p, ChartPop) and p.life > 0.3 for p in particles):
        particles.append(ChartPop(min(WIDTH - 70, max(70, x + 40)), y - 26))
    elif n < 6:
        ft = FloatingText(x, y - 40, random.choice(AVATAR_TAP_LINES), C("GREEN"))
        ft.avatar_tap = True
        floating_texts.append(ft)


trade_fx = {"kind": None, "start": 0.0, "amount": 0.0}
TRADE_FX_SECONDS = 2.2
TRADE_FX_W, TRADE_FX_H = 300, 160
_fx_cache = {}
_overlay_cache = {}


def blit_color_overlay(surface, color, alpha):
    """Full-screen tint. A cached solid surface with surface alpha is far cheaper than
    building a new full-screen per-pixel-alpha surface every frame."""
    key = (tuple(color[:3]), UI_SCALE)
    ov = _overlay_cache.get(key)
    if ov is None:
        ov = HiSurface((WIDTH, HEIGHT))
        ov.fill(tuple(color[:3]))
        if len(_overlay_cache) > 12:
            _overlay_cache.clear()
        _overlay_cache[key] = ov
    ov.set_alpha(max(0, min(255, int(alpha))))
    surface.blit(ov, (0, 0))


def _fx_scratch(name, size):
    """A reusable transparent layer, cleared instead of re-allocated each frame."""
    key = (name, tuple(size), UI_SCALE)
    layer = _fx_cache.get(key)
    if layer is None:
        layer = HiSurface(size, pygame.SRCALPHA)
        _fx_cache[key] = layer
    layer.fill((0, 0, 0, 0))
    return layer


def _trade_fx_card_base():
    """Drop shadow + dark card at full size. Blurring the shadow is the slow part, so it is
    done once; the pop-in animation scales this finished image instead."""
    key = ("card_base", UI_SCALE)
    base = _fx_cache.get(key)
    if base is None:
        w, h = TRADE_FX_W, TRADE_FX_H
        base = HiSurface((w + 40, h + 40), pygame.SRCALPHA)
        img, pad = soft_shadow(w, h, 24, 10, 120)
        base.blit(img, (20 - pad, 24 - pad))
        pygame.draw.rect(base, (26, 24, 40, 255), (20, 20, w, h), border_radius=24)
        _fx_cache[key] = base
    return base


def start_trade_fx(pnl):
    now = time.time()
    kind = "profit" if pnl >= 0.01 else ("loss" if pnl <= -0.01 else "even")
    # A bumpy trend line for the celebration card: climbs for profit, falls for loss.
    steps = 22
    raw, v = [], 0.0
    for i in range(steps):
        v += (1 if kind == "profit" else -1) * random.uniform(0.3, 1.0) + random.uniform(-0.7, 0.7)
        raw.append(v)
    lo, hi = min(raw), max(raw)
    path = [0.08 + 0.84 * (x - lo) / ((hi - lo) or 1) for x in raw]
    trade_fx.update(kind=kind, start=now, amount=pnl, path=path)
    if getattr(state, "reduced_motion", False):
        return
    if kind == "profit":
        style = equipped("fx")["id"]
        if style == "fx_money":
            for _ in range(60):
                particles.append(DollarBill(random.randint(10, WIDTH - 10), random.randint(-260, 0), rain=True))
            for i in range(24):
                particles.append(GoldCoin(WIDTH // 2, 330, random.uniform(-6, 6), random.uniform(-13, -6)))
        elif style == "fx_diamonds":
            for _ in range(34):
                particles.append(Diamond(WIDTH // 2 + random.uniform(-40, 40), 330, random.uniform(-6, 6), random.uniform(-12, -4)))
            for _ in range(20):
                particles.append(Spark(WIDTH // 2, 330, (190, 230, 255)))
        elif style == "fx_rocket":
            particles.append(Rocket(WIDTH // 2 + random.randint(-40, 40)))
            for i in range(10):
                particles.append(GoldCoin(WIDTH // 2, 330, random.uniform(-5, 5), random.uniform(-10, -5)))
        elif style == "fx_fireworks":
            for i, (fx, fy) in enumerate(((0.25, 180), (0.75, 150), (0.5, 110), (0.35, 230), (0.68, 250))):
                particles.append(Firework(WIDTH * fx, fy, 0.15 + i * 0.28, random.choice([(255, 90, 120), (90, 200, 255), (255, 215, 0), (140, 255, 160)])))
        else:
            for _ in range(28):
                particles.append(DollarBill(random.randint(10, WIDTH - 10), random.randint(-120, 0), rain=True))
            for i in range(16):
                particles.append(GoldCoin(WIDTH // 2, 330, random.uniform(-5, 5), random.uniform(-12, -6)))
            spawn_confetti(30)
        play_sound("victory")
        flash_screen(C("FLASH_GREEN"), 0.2)
    elif kind == "loss":
        play_sound("defeat")
        flash_screen(C("FLASH_RED"), 0.25)
    else:
        play_sound("click")


def draw_trade_fx(surface):
    kind = trade_fx["kind"]
    if not kind:
        return
    now = time.time()
    t = now - trade_fx["start"]
    if t > TRADE_FX_SECONDS:
        trade_fx["kind"] = None
        return
    fade = 1.0 if t < TRADE_FX_SECONDS - 0.4 else max(0.0, (TRADE_FX_SECONDS - t) / 0.4)
    cy = 330
    amount = trade_fx["amount"]
    shown = amount * ease_out_cubic(t / 0.7)

    if kind == "profit":
        burst = _fx_scratch("burst", (360, 360))
        for k in range(14):
            a = k * math.tau / 14 + t * 0.8
            pygame.draw.polygon(burst, (255, 200, 40, int(55 * fade)), [(180, 180), (180 + math.cos(a - 0.1) * 180, 180 + math.sin(a - 0.1) * 180),
                                                                         (180 + math.cos(a + 0.1) * 180, 180 + math.sin(a + 0.1) * 180)])
        surface.blit(burst, (WIDTH // 2 - 180, cy - 180))
        # Springy pop-in.
        s = 1 - math.exp(-7 * t) * math.cos(10 * t)
        title, title_col, amt_col, sub = "PROFIT!", (255, 210, 60), (70, 220, 130), "Nice trade! You sold for more than you paid."
        dx = 0
    elif kind == "loss":
        if t < 0.8:
            blit_color_overlay(surface, (200, 30, 40), 50 * (1 - t / 0.8))
        s = ease_out_cubic(t / 0.25)
        dx = int(math.sin(t * 55) * 12 * max(0.0, 1 - t / 0.6))  # shake
        title, title_col, amt_col, sub = "LOSS", (255, 110, 110), (255, 110, 110), "Every trader has red days. Review it and learn."
    else:
        s = ease_out_cubic(t / 0.25)
        dx = 0
        title, title_col, amt_col, sub = "BREAK EVEN", (220, 220, 230), (220, 220, 230), "You sold for about what you paid."

    # Everything is drawn at full size, then the finished card is scaled for the pop-in.
    w, h = TRADE_FX_W, TRADE_FX_H
    zoom = 0.5 + 0.5 * s
    card = pygame.Rect(0, 0, int(w * zoom), int(h * zoom))
    card.center = (WIDTH // 2 + dx, cy)
    layer = _fx_scratch("card", (w + 40, h + 40))
    layer.blit(_trade_fx_card_base(), (0, 0))
    border = {"profit": (255, 200, 40), "loss": (230, 70, 70)}.get(kind, (150, 150, 160))
    # Background chart spanning the whole card (above the caption strip): it climbs for
    # a profit and slides down for a loss, drawing itself left to right.
    path = trade_fx.get("path")
    if path and kind != "even":
        chart = pygame.Rect(20 + 4, 20 + 14, w - 8, h - 14 - 40)
        prog = ease_out_cubic((t - 0.1) / 0.9)
        n = len(path)
        f = prog * (n - 1)
        k = int(f)
        pts = [(chart.x + chart.w * i / (n - 1), chart.y + chart.h * (1 - v)) for i, v in enumerate(path[:k + 1])]
        if k < n - 1 and pts:
            v = path[k] + (path[k + 1] - path[k]) * (f - k)
            pts.append((chart.x + chart.w * f / (n - 1), chart.y + chart.h * (1 - v)))
        ccol = (70, 220, 130) if kind == "profit" else (255, 95, 95)
        if len(pts) > 1:
            # Separate layer so translucent strokes blend over the card instead of punching holes in it.
            cl = _fx_scratch("chart", (w + 40, h + 40))
            pygame.draw.polygon(cl, (*ccol, 40), pts + [(pts[-1][0], chart.bottom), (pts[0][0], chart.bottom)])
            glow_l = _fx_scratch("glow", (w + 40, h + 40))
            pygame.draw.lines(glow_l, (*ccol, 60), False, pts, 8)
            cl.blit(glow_l, (0, 0))
            pygame.draw.lines(cl, (*ccol, 150), False, pts, 3)
            pygame.draw.circle(cl, (*ccol, 255), pts[-1], 5)
            layer.blit(cl, (0, 0))
    pygame.draw.rect(layer, (*border, 255), (20, 20, w, h), 3, border_radius=24)
    # Scale or fade a copy; the reusable scratch layer itself must keep its default blending.
    img = layer.hi
    if abs(zoom - 1.0) > 0.01:
        img = pygame.transform.smoothscale(img, (max(2, int(img.get_width() * zoom)), max(2, int(img.get_height() * zoom))))
    elif fade < 0.999:
        img = img.copy()
    if fade < 0.999:
        img.set_alpha(int(255 * fade))
    out = HiSurface(None, hi=img)
    surface.blit(out, (card.centerx - out.get_width() / 2, card.centery - out.get_height() / 2))
    if s > 0.85 and fade > 0.2:
        draw_text_outlined(surface, title, font_large, title_col, card.centerx, card.y + 18, SG_PANEL)
        sign = "+" if shown >= 0 else "-"
        draw_text_outlined(surface, f"{sign}{fmt_money(abs(shown))}", font_countdown, amt_col, card.centerx, card.y + 62, SG_PANEL)
        draw_text(surface, sub, font_tiny, (200, 196, 220), card.centerx, card.bottom - 27, align="center", max_width=card.w - 24)


# ----------------------------
# ALERTS, AUTO-INVEST PLANS AND SAFETY ORDERS
# ----------------------------

ALERT_RULES = [
    ("move2", "Moves 2% either way"), ("move5", "Moves 5% either way"),
    ("move10", "Moves 10% either way"), ("up5", "Rises 5% or more"),
    ("down5", "Drops 5% or more"), ("high", "Hits a new high"),
    ("low", "Hits a new low"), ("news", "Has breaking news"),
]
AUTO_AMOUNTS = [10, 25, 50, 100]
# One game day passes every 2 minutes of play, so plans actually run while you play.
AUTO_FREQS = [("daily", "Daily", 120), ("weekly", "Weekly", 300), ("biweekly", "Every 2 wks", 600), ("monthly", "Monthly", 1200)]
SAFETY_ORDERS = [("tp", 10, "Take profit at +10%"), ("tp", 25, "Take profit at +25%"),
                 ("sl", 5, "Stop loss at -5%"), ("sl", 10, "Stop loss at -10%")]

alerts_sheet = {"ticker": None, "amount": 25, "freq": "weekly", "opened": 0.0}
alerts_sheet_btns = []


def _freq_seconds(key):
    return next((sec for k, _, sec in AUTO_FREQS if k == key), 300)


def _freq_label(key):
    return next((lab for k, lab, _ in AUTO_FREQS if k == key), "Weekly")


def get_alert(ticker, create=False):
    """Alert settings for a stock. Older saves stored a bare threshold number."""
    a = state.alerts.get(ticker)
    asset = find_asset(ticker)
    price = float(asset["price"]) if asset else 0.0
    if isinstance(a, (int, float)):
        a = {"rules": ["move5" if a >= 0.05 else "move2"], "anchor": price, "hi": price, "lo": price}
        state.alerts[ticker] = a
    if a is None and create:
        a = {"rules": [], "anchor": price, "hi": price, "lo": price}
        state.alerts[ticker] = a
    return a


def alert_rule_count(ticker):
    a = get_alert(ticker)
    return len(a["rules"]) if a else 0


def toggle_alert_rule(ticker, rule):
    a = get_alert(ticker, create=True)
    asset = find_asset(ticker)
    if rule in a["rules"]:
        a["rules"].remove(rule)
    else:
        a["rules"].append(rule)
        if asset:
            a["anchor"] = a["hi"] = a["lo"] = float(asset["price"])
    if not a["rules"]:
        state.alerts.pop(ticker, None)
    play_sound("click")
    save_game()


def _alert_toast(ticker, title, sub):
    show_toast(title, sub, "bell", action=("stock", ticker))
    play_sound("bell")


def check_price_alerts():
    now = time.time()
    for ticker in list(state.alerts.keys()):
        a = get_alert(ticker)
        asset = find_asset(ticker)
        if not a or not asset:
            continue
        p = float(asset["price"])
        anchor = float(a.get("anchor") or p)
        if not anchor:
            continue
        mv = (p - anchor) / anchor
        fired = None
        for rule, pct in (("move10", 0.10), ("move5", 0.05), ("move2", 0.02)):
            if rule in a["rules"] and abs(mv) >= pct:
                fired = (f"{ticker} moved {mv * 100:+.1f}%", f"Now {fmt_money(p)}. Tap to take a look.")
                break
        if not fired and "up5" in a["rules"] and mv >= 0.05:
            fired = (f"{ticker} is up {mv * 100:.1f}%", f"Rose to {fmt_money(p)} since your alert.")
        if not fired and "down5" in a["rules"] and mv <= -0.05:
            fired = (f"{ticker} is down {abs(mv) * 100:.1f}%", f"Dropped to {fmt_money(p)} since your alert.")
        if fired:
            a["anchor"] = p
            _alert_toast(ticker, *fired)
            continue
        if now - a.get("last_hilo", 0) > 20:
            if "high" in a["rules"] and p > a.get("hi", p) * 1.002:
                a["hi"], a["last_hilo"] = p, now
                _alert_toast(ticker, f"{ticker} hit a new high", f"{fmt_money(p)} is the highest since you set this alert.")
            elif "low" in a["rules"] and p < a.get("lo", p) * 0.998:
                a["lo"], a["last_hilo"] = p, now
                _alert_toast(ticker, f"{ticker} hit a new low", f"{fmt_money(p)} is the lowest since you set this alert.")
        a["hi"] = max(a.get("hi", p), p)
        a["lo"] = min(a.get("lo", p), p)


def get_plan(ticker):
    return next((r for r in state.recurring_orders if r.get("ticker") == ticker), None)


def start_or_update_plan(ticker, amount, freq):
    plan = get_plan(ticker)
    now = time.time()
    if plan:
        plan.update(amount=float(amount), frequency=freq, active=True)
        plan["next_at"] = now + _freq_seconds(freq)
        show_toast("Plan updated", f"{fmt_money(amount)} of {ticker}, {_freq_label(freq).lower()}.", "buy")
    else:
        state.recurring_orders.append({"ticker": ticker, "amount": float(amount), "frequency": freq, "active": True,
                                       "next_at": now + _freq_seconds(freq), "count": 0, "invested": 0.0})
        add_xp(10)
        show_toast("Auto-invest started", f"{fmt_money(amount)} of {ticker}, {_freq_label(freq).lower()}. Steady beats stressy!", "achievement")
    play_sound("achievement")
    save_game()


def stop_plan(ticker):
    plan = get_plan(ticker)
    if plan:
        state.recurring_orders.remove(plan)
        show_toast("Plan stopped", f"No more automatic buys of {ticker}.", "warning")
        play_sound("click")
        save_game()


def _auto_buy(asset, amount):
    """Buy a dollar amount quietly (no big trade celebration)."""
    price = float(asset["price"])
    qty = round(amount / price, 4) if price else 0
    cost = round(price * qty, 2)
    if qty <= 0 or cost > state.cash:
        return 0.0
    t = asset["ticker"]
    owned = state.holdings.get(t, 0)
    old_avg = state.avg_buy_price.get(t, price)
    state.avg_buy_price[t] = ((old_avg * owned) + price * qty) / (owned + qty)
    state.cash = round(state.cash - cost, 2)
    state.holdings[t] = round(owned + qty, 4)
    state.hold_since.setdefault(t, time.time())
    state.theses.setdefault(t, "auto")
    state.trade_count += 1
    log_trade("buy", asset, qty, price, "auto")
    add_recent_action(f"Auto-invested {fmt_money(cost)} in {t}")
    return cost


def run_auto_invest(now):
    for plan in list(state.recurring_orders):
        if not plan.get("active", True):
            continue
        interval = _freq_seconds(plan.get("frequency", "weekly"))
        if "next_at" not in plan:
            plan["next_at"] = now + interval
            continue
        if now < plan["next_at"]:
            continue
        # If the game was closed for a while, buy once and restart the schedule (no pile-up).
        plan["next_at"] = now + interval
        asset = find_asset(plan["ticker"])
        if not asset:
            continue
        cost = _auto_buy(asset, plan.get("amount", 25.0))
        if cost:
            plan["count"] = plan.get("count", 0) + 1
            plan["invested"] = round(plan.get("invested", 0.0) + cost, 2)
            show_toast(f"Auto-invest  •  {plan['ticker']}", f"Bought {fmt_money(cost)}. Next buy {_freq_label(plan['frequency']).lower()}.", "buy",
                       action=("stock", plan["ticker"]))
            play_sound("dividend")
            spawn_money_burst(WIDTH - 60, 40, 3, 4)
        else:
            show_toast("Auto-invest skipped", f"Not enough cash for {fmt_money(plan.get('amount', 25))} of {plan['ticker']}.", "warning")
        save_game()


def get_safety(ticker, kind):
    return next((o for o in state.pending_orders if o.get("ticker") == ticker and o.get("type") == kind), None)


def toggle_safety(ticker, kind, pct):
    cur = get_safety(ticker, kind)
    if cur:
        state.pending_orders.remove(cur)
        if int(cur.get("pct", 0)) == pct:
            play_sound("click")
            save_game()
            return
    if state.holdings.get(ticker, 0) <= 0:
        show_toast("Own it first", f"Buy some {ticker} before adding a safety order.", "warning")
        play_sound("error")
        return
    state.pending_orders.append({"ticker": ticker, "type": kind, "pct": pct})
    play_sound("click")
    save_game()


def check_safety_orders():
    for order in list(state.pending_orders):
        t = order.get("ticker")
        asset = find_asset(t) if t else None
        owned = state.holdings.get(t, 0) if t else 0
        if not asset or owned <= 0:
            if order in state.pending_orders and owned <= 0:
                state.pending_orders.remove(order)
            continue
        avg = state.avg_buy_price.get(t, asset["price"])
        if not avg:
            continue
        gain = (asset["price"] - avg) / avg * 100
        pct = order.get("pct", 10)
        hit = (order.get("type") == "tp" and gain >= pct) or (order.get("type") == "sl" and gain <= -pct)
        if hit:
            state.pending_orders.remove(order)
            label = "Take-profit" if order["type"] == "tp" else "Stop-loss"
            do_sell(asset, owned, via=label)
            show_toast(f"{label} triggered  •  {t}", f"Sold all {owned:g} shares at {fmt_money(asset['price'])} ({gain:+.1f}%).",
                       "buy" if order["type"] == "tp" else "sell", action=("stock", t))


def open_alerts_sheet(ticker):
    plan = get_plan(ticker)
    alerts_sheet.update(ticker=ticker, opened=time.time(),
                        amount=int(plan["amount"]) if plan else 25, freq=plan["frequency"] if plan else "weekly")
    play_sound("click")


def draw_alerts_sheet(surface):
    global alerts_sheet_btns
    t = alerts_sheet["ticker"]
    if not t:
        return
    asset = find_asset(t)
    if not asset:
        alerts_sheet["ticker"] = None
        return
    alerts_sheet_btns = []
    now = time.time()
    ov = HiSurface((WIDTH, HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 120))
    surface.blit(ov, (0, 0))
    slide = ease_out_cubic((now - alerts_sheet["opened"]) / 0.3)
    sheet = pygame.Rect(0, int(40 + (HEIGHT - 40) * (1 - slide)), WIDTH, HEIGHT - 40)
    draw_rounded_rect(surface, sheet, C("CARD"), radius=26)
    pygame.draw.rect(surface, C("BORDER"), (WIDTH // 2 - 22, sheet.y + 8, 44, 5), border_radius=3)
    x = 20
    y = sheet.y + 24
    draw_ticker_badge(surface, t, x, y, size=38)
    draw_text(surface, "Alerts & Auto-Invest", font_medium_bold, C("INK"), x + 50, y)
    draw_text(surface, f"{asset['name']}  •  {fmt_money(asset['price'])}", font_tiny, C("GRAY"), x + 50, y + 22)
    close = pygame.Rect(WIDTH - 54, y, 36, 36)
    draw_rounded_rect(surface, close, C("PANEL_BG"), radius=18, shadow=False)
    pygame.draw.line(surface, C("GRAY"), (close.centerx - 6, close.centery - 6), (close.centerx + 6, close.centery + 6), 2)
    pygame.draw.line(surface, C("GRAY"), (close.centerx + 6, close.centery - 6), (close.centerx - 6, close.centery + 6), 2)
    alerts_sheet_btns.append((close, ("close",)))
    y += 52

    def chip(rect, label, on, color, key):
        bg = color if on else C("PANEL_BG")
        draw_rounded_rect(surface, rect, bg, radius=12, border_color=color if on else C("BORDER"), border_width=1, shadow=False)
        tx = rect.x + 12
        if on:
            draw_check(surface, (rect.x + 16, rect.centery), 7, (255, 255, 255), color)
            tx = rect.x + 30
        draw_text(surface, label, font_tiny, text_on(color) if on else C("INK"), tx, rect.centery - 8, max_width=rect.right - tx - 6)
        alerts_sheet_btns.append((rect, key))

    # Price alerts
    draw_text(surface, "PRICE ALERTS", font_tiny, C("PURPLE"), x, y)
    draw_text(surface, "Notify me when this stock…", font_tiny, C("GRAY"), WIDTH - 20, y, align="right")
    y += 20
    rules = get_alert(t)["rules"] if get_alert(t) else []
    cw = (WIDTH - 40 - 8) // 2
    for i, (rid, label) in enumerate(ALERT_RULES):
        r = pygame.Rect(x + (i % 2) * (cw + 8), y + (i // 2) * 40, cw, 34)
        chip(r, label, rid in rules, C("PURPLE"), ("alert", rid))
    y += 4 * 40 + 14

    # Auto-invest
    plan = get_plan(t)
    draw_text(surface, "AUTO-INVEST PLAN", font_tiny, C("GREEN"), x, y)
    draw_text(surface, "1 game day = 2 min of play", font_tiny, C("GRAY"), WIDTH - 20, y, align="right")
    y += 20
    aw = (WIDTH - 40 - 3 * 8) // 4
    for i, amt in enumerate(AUTO_AMOUNTS):
        r = pygame.Rect(x + i * (aw + 8), y, aw, 34)
        chip(r, f"${amt}", alerts_sheet["amount"] == amt, C("GREEN"), ("amount", amt))
    y += 42
    for i, (k, label, _) in enumerate(AUTO_FREQS):
        r = pygame.Rect(x + i * (aw + 8), y, aw, 34)
        chip(r, label, alerts_sheet["freq"] == k, C("GREEN"), ("freq", k))
    y += 44
    if plan:
        left = max(0, int(plan.get("next_at", now) - now))
        status = f"Next buy in {left // 60}:{left % 60:02d}  •  {plan.get('count', 0)} buys  •  {fmt_money(plan.get('invested', 0))} invested"
        draw_text(surface, status, font_tiny, C("GREEN"), x, y)
        y += 20
        bw = (WIDTH - 40 - 8) // 2
        upd = pygame.Rect(x, y, bw, 42)
        stp = pygame.Rect(x + bw + 8, y, bw, 42)
        changed = int(plan["amount"]) != alerts_sheet["amount"] or plan["frequency"] != alerts_sheet["freq"]
        draw_button(surface, upd, "Update plan" if changed else "Plan running", C("GREEN") if changed else C("PANEL_BG"),
                    (255, 255, 255) if changed else C("GREEN"), font=font_small_bold, radius=12)
        draw_button(surface, stp, "Stop plan", C("PANEL_BG"), C("RED"), font=font_small_bold, radius=12)
        alerts_sheet_btns += [(upd, ("plan_start",)), (stp, ("plan_stop",))]
    else:
        start = pygame.Rect(x, y, WIDTH - 40, 42)
        draw_button(surface, start, f"Start: {fmt_money(alerts_sheet['amount'])} {_freq_label(alerts_sheet['freq']).lower()}",
                    C("GREEN"), (255, 255, 255), font=font_small_bold, radius=12)
        alerts_sheet_btns.append((start, ("plan_start",)))
        y += 20
    y += 58

    # Safety orders
    draw_text(surface, "SAFETY ORDERS", font_tiny, C("ORANGE"), x, y)
    draw_text(surface, "Sell automatically", font_tiny, C("GRAY"), WIDTH - 20, y, align="right")
    y += 20
    owned = state.holdings.get(t, 0) > 0
    for i, (kind, pct, label) in enumerate(SAFETY_ORDERS):
        r = pygame.Rect(x + (i % 2) * (cw + 8), y + (i // 2) * 40, cw, 34)
        cur = get_safety(t, kind)
        chip(r, label, bool(cur and int(cur.get("pct", 0)) == pct), C("GREEN") if kind == "tp" else C("RED"), ("safety", kind, pct))
    y += 2 * 40
    if not owned:
        draw_text(surface, f"Buy some {t} to use safety orders.", font_tiny, C("LIGHT_GRAY"), WIDTH // 2, y + 2, align="center")


def handle_alerts_sheet_click(pos):
    t = alerts_sheet["ticker"]
    if not t:
        return False
    for rect, key in alerts_sheet_btns:
        if not rect.collidepoint(pos):
            continue
        kind = key[0]
        if kind == "close":
            alerts_sheet["ticker"] = None
            play_sound("click")
        elif kind == "alert":
            toggle_alert_rule(t, key[1])
        elif kind == "amount":
            alerts_sheet["amount"] = key[1]
            play_sound("click")
        elif kind == "freq":
            alerts_sheet["freq"] = key[1]
            play_sound("click")
        elif kind == "plan_start":
            start_or_update_plan(t, alerts_sheet["amount"], alerts_sheet["freq"])
        elif kind == "plan_stop":
            stop_plan(t)
        elif kind == "safety":
            toggle_safety(t, key[1], key[2])
        return True
    if pos[1] < 40:
        alerts_sheet["ticker"] = None
    return True


# ----------------------------
# REWARDS: Ledger Coins, chests, cosmetics and boosts
# ----------------------------
# Everything here is earned by playing (learning, trading, duels, daily streaks).
# Nothing costs real money. Tiers use market names instead of "common/rare/epic".

RARITY = {
    "common": ("Penny Stock", (125, 135, 150)),
    "rare": ("Blue Chip", (46, 134, 222)),
    "epic": ("Hedge Fund", (155, 81, 224)),
    "legendary": ("Wall Street", (240, 160, 25)),
}
RARITY_ORDER = ["common", "rare", "epic", "legendary"]
CHEST_NAMES = {"common": "Penny Stock Crate", "rare": "Blue Chip Chest", "epic": "Hedge Fund Vault", "legendary": "Wall Street Vault"}
CHEST_SHORT = {"common": "Crate", "rare": "Chest", "epic": "Vault", "legendary": "Mega Vault"}


def tier_name(r):
    return RARITY[r][0]


def tier_color(r):
    return RARITY[r][1]


def chest_name(r):
    return CHEST_NAMES[r]


COSMETICS = [
    # Avatar frames
    {"id": "frame_classic", "kind": "frame", "name": "Classic", "rarity": "common", "price": 0},
    {"id": "frame_ticker", "kind": "frame", "name": "Ticker Tape", "rarity": "common", "price": 140},
    {"id": "frame_gold", "kind": "frame", "name": "Gold Ring", "rarity": "rare", "price": 250},
    {"id": "frame_emerald", "kind": "frame", "name": "Emerald", "rarity": "rare", "price": 250},
    {"id": "frame_candles", "kind": "frame", "name": "Candlesticks", "rarity": "rare", "price": 300},
    {"id": "frame_ice", "kind": "frame", "name": "Frozen Assets", "rarity": "rare", "price": 300},
    {"id": "frame_neon", "kind": "frame", "name": "Neon Glow", "rarity": "epic", "price": 500},
    {"id": "frame_fire", "kind": "frame", "name": "On Fire", "rarity": "epic", "price": 550},
    {"id": "frame_circuit", "kind": "frame", "name": "Quant Circuit", "rarity": "epic", "price": 600},
    {"id": "frame_diamond", "kind": "frame", "name": "Diamond", "rarity": "legendary", "price": 900},
    {"id": "frame_rainbow", "kind": "frame", "name": "Rainbow", "rarity": "legendary", "price": 950},
    {"id": "frame_galaxy", "kind": "frame", "name": "Galaxy Brain", "rarity": "legendary", "price": 1000},
    {"id": "frame_bronze", "kind": "frame", "name": "Bronze Bull", "rarity": "rare", "price": None, "level": 5},
    {"id": "frame_bull", "kind": "frame", "name": "Golden Bull", "rarity": "legendary", "price": None, "level": 30},
    # Titles
    {"id": "title_rookie", "kind": "title", "name": "Rookie Investor", "rarity": "common", "price": 0},
    {"id": "title_saver", "kind": "title", "name": "Smart Saver", "rarity": "common", "price": 100},
    {"id": "title_chart", "kind": "title", "name": "Chart Reader", "rarity": "common", "price": 120},
    {"id": "title_quant", "kind": "title", "name": "Quant Apprentice", "rarity": "common", "price": 120},
    {"id": "title_index", "kind": "title", "name": "Index Investor", "rarity": "common", "price": 120},
    {"id": "title_dividend", "kind": "title", "name": "Dividend Hunter", "rarity": "rare", "price": 250},
    {"id": "title_diamond", "kind": "title", "name": "Diamond Hands", "rarity": "rare", "price": 300},
    {"id": "title_value", "kind": "title", "name": "Value Hunter", "rarity": "rare", "price": 280},
    {"id": "title_momentum", "kind": "title", "name": "Momentum Rider", "rarity": "rare", "price": 280},
    {"id": "title_risk", "kind": "title", "name": "Risk Manager", "rarity": "rare", "price": 300},
    {"id": "title_bull", "kind": "title", "name": "Bull Runner", "rarity": "epic", "price": 500},
    {"id": "title_bear", "kind": "title", "name": "Bear Tamer", "rarity": "epic", "price": 500},
    {"id": "title_alpha", "kind": "title", "name": "Alpha Seeker", "rarity": "epic", "price": 550},
    {"id": "title_sharpe", "kind": "title", "name": "Sharpe Shooter", "rarity": "epic", "price": 550},
    {"id": "title_maker", "kind": "title", "name": "Market Maker", "rarity": "epic", "price": 600},
    {"id": "title_compound", "kind": "title", "name": "Compound King", "rarity": "legendary", "price": 900},
    {"id": "title_wiz", "kind": "title", "name": "Wall Street Wiz", "rarity": "legendary", "price": 1000},
    {"id": "title_algo", "kind": "title", "name": "Algo Architect", "rarity": "legendary", "price": 1000},
    {"id": "title_swan", "kind": "title", "name": "Black Swan Survivor", "rarity": "legendary", "price": 1100},
    {"id": "title_veteran", "kind": "title", "name": "Market Veteran", "rarity": "epic", "price": None, "level": 10},
    {"id": "title_hero", "kind": "title", "name": "Hedge Fund Hero", "rarity": "legendary", "price": None, "level": 25},
    # Chart colors: (up color, down color)
    {"id": "chart_classic", "kind": "chart", "name": "Classic", "rarity": "common", "price": 0, "colors": None},
    {"id": "chart_ocean", "kind": "chart", "name": "Ocean", "rarity": "common", "price": 120, "colors": ((0, 150, 220), (95, 110, 160))},
    {"id": "chart_mint", "kind": "chart", "name": "Mint", "rarity": "common", "price": 120, "colors": ((40, 200, 150), (230, 110, 120))},
    {"id": "chart_neon", "kind": "chart", "name": "Neon", "rarity": "rare", "price": 280, "colors": ((0, 225, 205), (255, 60, 170))},
    {"id": "chart_candy", "kind": "chart", "name": "Cotton Candy", "rarity": "rare", "price": 280, "colors": ((90, 170, 255), (255, 120, 190))},
    {"id": "chart_sunset", "kind": "chart", "name": "Sunset", "rarity": "epic", "price": 480, "colors": ((255, 140, 40), (205, 60, 120))},
    {"id": "chart_matrix", "kind": "chart", "name": "Matrix", "rarity": "epic", "price": 520, "colors": ((0, 210, 90), (0, 120, 60))},
    {"id": "chart_gold", "kind": "chart", "name": "Gold Rush", "rarity": "legendary", "price": 850, "colors": ((225, 165, 15), (165, 115, 60))},
    {"id": "chart_royal", "kind": "chart", "name": "Royal", "rarity": "legendary", "price": 900, "colors": ((150, 90, 240), (230, 170, 40))},
    {"id": "chart_aurora", "kind": "chart", "name": "Aurora", "rarity": "epic", "price": None, "level": 20, "colors": ((60, 230, 190), (160, 110, 255))},
    # Profit celebrations (what plays when you sell for a profit)
    {"id": "fx_classic", "kind": "fx", "name": "Confetti", "rarity": "common", "price": 0},
    {"id": "fx_money", "kind": "fx", "name": "Money Rain", "rarity": "rare", "price": 300},
    {"id": "fx_diamonds", "kind": "fx", "name": "Diamond Hands", "rarity": "epic", "price": 600},
    {"id": "fx_rocket", "kind": "fx", "name": "To The Moon", "rarity": "legendary", "price": 1000},
    {"id": "fx_fireworks", "kind": "fx", "name": "Fireworks", "rarity": "epic", "price": None, "level": 15},
]
COSMETIC_BY_ID = {c["id"]: c for c in COSMETICS}
DEFAULT_EQUIPPED = {"frame": "frame_classic", "title": "title_rookie", "chart": "chart_classic", "fx": "fx_classic"}
KIND_LABELS = {"frame": "Frame", "title": "Title", "chart": "Chart color", "fx": "Profit effect"}

BOOSTS = [
    {"id": "insight", "name": "Market Insight", "desc": "Trend signals on every stock, 5 min", "price": 90, "minutes": 5, "color": "PURPLE", "rarity": "common"},
    {"id": "shield", "name": "Trophy Shield", "desc": "Next duel loss costs 0 trophies", "price": 110, "charges": 1, "color": "ORANGE", "rarity": "common"},
    {"id": "xp2", "name": "2x XP", "desc": "Double XP for 10 min", "price": 120, "minutes": 10, "color": "PURPLE", "rarity": "rare"},
    {"id": "payday", "name": "Payday Boost", "desc": "+50% dividends, 3 paydays", "price": 140, "charges": 3, "color": "GREEN", "rarity": "rare"},
    {"id": "coin2", "name": "Coin Magnet", "desc": "Double coins for 15 min", "price": 150, "minutes": 15, "color": "GOLD", "rarity": "epic"},
    {"id": "cash", "name": "Cash Drop", "desc": "+$100 practice cash", "price": 160, "instant": True, "color": "GREEN", "rarity": "epic"},
]
BOOST_BY_ID = {b["id"]: b for b in BOOSTS}

CHEST_PRICES = {"common": 80, "rare": 200, "epic": 450}
# Chance (%) that a chest's prize comes from each tier.
CHEST_TIER_ODDS = {
    "common": {"common": 75, "rare": 22, "epic": 3},
    "rare": {"common": 30, "rare": 55, "epic": 13, "legendary": 2},
    "epic": {"rare": 35, "epic": 55, "legendary": 10},
    "legendary": {"epic": 40, "legendary": 60},
}
# Once the tier is picked: what kind of prize (%).
PRIZE_TYPE_ODDS = {"cosmetic": 50, "coins": 30, "boost": 20}
COIN_RANGES = {"common": (25, 60), "rare": (80, 140), "epic": (200, 320), "legendary": (500, 800)}
LOGIN_REWARDS = [("coins", 20), ("coins", 30), ("chest", "common"), ("coins", 50), ("boost", "xp2"), ("coins", 80), ("chest", "epic")]

LEVEL_ROAD_MAX = 50
LEVEL_BOOST_CYCLE = ["xp2", "insight", "shield", "payday", "coin2"]


def level_reward(level):
    """What you get for reaching a level: coins, plus a chest or boost, plus milestone exclusives."""
    out = [("coins", 40 + 10 * level)]
    if level % 10 == 0:
        out.append(("chest", "legendary"))
    elif level % 5 == 0:
        out.append(("chest", "epic"))
    elif level % 2 == 0:
        out.append(("chest", "rare"))
    else:
        out.append(("boost", LEVEL_BOOST_CYCLE[(level // 2) % len(LEVEL_BOOST_CYCLE)]))
    for c in COSMETICS:
        if c.get("level") == level:
            out.append(("cosmetic", c["id"]))
    return out


def level_looks(level):
    """Avatar-creator looks that unlock at this level (shown on the Level Road)."""
    names = []
    for trait, idx in cosmetics_unlocked_at_level(level):
        label = CREATOR_TILE_LABELS.get(trait, [])
        if isinstance(label, list) and idx < len(label):
            names.append(f"{label[idx]} {dict(CREATOR_TABS).get(trait, trait).lower()}")
        else:
            names.append({"skin": "New skin tone", "hair_color": "New hair color", "outfit": "New outfit color"}.get(
                trait, f"New {dict(CREATOR_TABS).get(trait, trait).lower()}"))
    return names

chest_anim = {"rarity": None, "reward": None, "start": 0.0}
chest_info = {"rarity": None, "opened": 0.0}


def rewards_state():
    """Make sure all reward fields exist (older saves won't have them)."""
    if not isinstance(getattr(state, "coins", None), int):
        state.coins = int(getattr(state, "coins", 0) or 0)
    if not isinstance(getattr(state, "chests", None), dict):
        state.chests = {}
    if not isinstance(getattr(state, "owned_cosmetics", None), list):
        state.owned_cosmetics = []
    for cid in DEFAULT_EQUIPPED.values():
        if cid not in state.owned_cosmetics:
            state.owned_cosmetics.append(cid)
    if not isinstance(getattr(state, "equipped", None), dict):
        state.equipped = {}
    for k, v in DEFAULT_EQUIPPED.items():
        if state.equipped.get(k) not in COSMETIC_BY_ID:
            state.equipped[k] = v
    if not isinstance(getattr(state, "boosts", None), dict):
        state.boosts = {}
    if not isinstance(getattr(state, "boost_bag", None), dict):
        state.boost_bag = {}
    if not isinstance(getattr(state, "level_claimed", None), list):
        # Saves from before the Level Road already got their level-up chests automatically.
        state.level_claimed = list(range(2, int(getattr(state, "level", 1)) + 1))
    return state


def equipped(kind):
    rewards_state()
    return COSMETIC_BY_ID.get(state.equipped.get(kind), COSMETIC_BY_ID[DEFAULT_EQUIPPED[kind]])


def boost_active(bid):
    b = rewards_state().boosts.get(bid)
    if not b:
        return False
    if "until" in b:
        return time.time() < b["until"]
    return b.get("charges", 0) > 0


def boost_left_label(bid):
    b = rewards_state().boosts.get(bid, {})
    if "until" in b:
        left = max(0, int(b["until"] - time.time()))
        return f"{left // 60}:{left % 60:02d}"
    return f"x{b.get('charges', 0)}"


def consume_boost(bid):
    b = rewards_state().boosts.get(bid)
    if b and b.get("charges", 0) > 0:
        b["charges"] -= 1
        if b["charges"] <= 0:
            state.boosts.pop(bid, None)
        return True
    return False


def grant_boost(bid, announce=True):
    """Activate a boost right now."""
    info = BOOST_BY_ID[bid]
    rewards_state()
    if info.get("instant"):
        state.cash = round(state.cash + 100, 2)
        spawn_cash_text(100, WIDTH // 2, 220)
        if announce:
            show_toast("Cash Drop!", "+$100 practice cash added to your wallet.", "dividend")
        return
    cur = state.boosts.get(bid, {})
    if "minutes" in info:
        start = max(time.time(), cur.get("until", 0))
        state.boosts[bid] = {"until": start + info["minutes"] * 60}
    else:
        state.boosts[bid] = {"charges": cur.get("charges", 0) + info["charges"]}
    if announce:
        where = " Open the Market to see the signals." if bid == "insight" else ""
        show_toast(f"{info['name']} is on!", info["desc"] + "." + where, "achievement", action=("inventory",))


def add_to_bag(bid, n=1):
    bag = rewards_state().boost_bag
    bag[bid] = bag.get(bid, 0) + n


def use_bag_item(bid):
    bag = rewards_state().boost_bag
    if bag.get(bid, 0) <= 0:
        return
    bag[bid] -= 1
    if bag[bid] <= 0:
        bag.pop(bid, None)
    grant_boost(bid)
    play_sound("achievement")
    spawn_confetti(20)
    save_game()


def add_coins(amount, reason="", x=None, y=None):
    """Award Ledger Coins with a little gold pop."""
    amount = int(amount)
    if amount <= 0:
        return 0
    rewards_state()
    if boost_active("coin2"):
        amount *= 2
    state.coins += amount
    x = WIDTH // 2 - 70 if x is None else x
    y = 250 if y is None else y
    floating_texts.append(FloatingText(x, y, f"+{amount} coins", (230, 160, 0)))
    if not getattr(state, "reduced_motion", False):
        for _ in range(min(8, 2 + amount // 15)):
            particles.append(GoldCoin(x, y + 10, random.uniform(-2.5, 2.5), random.uniform(-7, -3)))
    return amount


def grant_chest(rarity, reason=""):
    rewards_state().chests[rarity] = state.chests.get(rarity, 0) + 1
    show_toast(f"{chest_name(rarity)} earned!", (reason + "  •  " if reason else "") + "Open it in Rewards.", "achievement",
               action=("rewards",))


def _weighted(odds):
    total = sum(odds.values())
    r = random.uniform(0, total)
    for k, v in odds.items():
        r -= v
        if r <= 0:
            return k
    return list(odds)[-1]


def chest_pool(tier):
    """Everything a chest could give at one tier (for the odds sheet and the roll)."""
    cos = [c for c in COSMETICS if c["rarity"] == tier and c.get("price")]
    boosts = [b for b in BOOSTS if b["rarity"] == tier]
    return cos, boosts, COIN_RANGES[tier]


def _roll_chest(rarity):
    """Pick the prize tier from the chest's odds, then the prize type, then the item.
    Cosmetics you already own are skipped; if you own them all you get bonus coins instead."""
    rewards_state()
    tier = _weighted(CHEST_TIER_ODDS[rarity])
    cos, boosts, (lo, hi) = chest_pool(tier)
    unowned = [c for c in cos if c["id"] not in state.owned_cosmetics]
    odds = dict(PRIZE_TYPE_ODDS)
    if not boosts:
        odds.pop("boost")
    kind = _weighted(odds)
    if kind == "cosmetic" and unowned:
        return ("cosmetic", random.choice(unowned)["id"], tier)
    if kind == "boost" and boosts:
        return ("boost", random.choice(boosts)["id"], tier)
    bonus = 1.3 if kind == "cosmetic" else 1.0  # you'd have got a cosmetic, but own them all
    return ("coins", int(random.randint(lo, hi) * bonus), tier)


def apply_reward(reward):
    kind, val = reward[0], reward[1]
    rewards_state()
    if kind == "coins":
        state.coins += int(val)
    elif kind == "boost":
        add_to_bag(val)
    elif kind == "cosmetic" and val not in state.owned_cosmetics:
        state.owned_cosmetics.append(val)
    elif kind == "chest":
        state.chests[val] = state.chests.get(val, 0) + 1


def open_chest(rarity):
    rewards_state()
    if state.chests.get(rarity, 0) <= 0:
        return
    state.chests[rarity] -= 1
    if state.chests[rarity] <= 0:
        state.chests.pop(rarity, None)
    reward = _roll_chest(rarity)
    apply_reward(reward)  # saved right away, so closing early never loses it
    chest_info["rarity"] = None
    chest_anim.update(rarity=rarity, reward=reward, start=time.time(), sparked=False, equip_btn=None, collect_btn=None,
                      stage="drop", taps=0, tap_at=0.0, burst_at=0.0)
    play_sound("click")
    save_game()


def buy_chest(rarity):
    price = CHEST_PRICES.get(rarity)
    rewards_state()
    if price is None or state.coins < price:
        show_toast("Not enough coins", f"You need {price} coins. Keep learning and trading!", "warning")
        play_sound("error")
        return
    state.coins -= price
    state.chests[rarity] = state.chests.get(rarity, 0) + 1
    play_sound("achievement")
    save_game()


def buy_cosmetic(cid):
    item = COSMETIC_BY_ID[cid]
    rewards_state()
    if cid in state.owned_cosmetics:
        equip_cosmetic(cid)
        return
    if not item.get("price"):
        show_toast("Level reward", f"{item['name']} unlocks on the Level Road at Level {item.get('level')}.", "warning", action=("levels",))
        return
    if state.coins < item["price"]:
        show_toast("Not enough coins", f"{item['name']} costs {item['price']} coins.", "warning")
        play_sound("error")
        return
    state.coins -= item["price"]
    state.owned_cosmetics.append(cid)
    show_toast(f"Unlocked: {item['name']}", "It's in your Inventory. Equip it whenever you like!", "achievement", action=("inventory",))
    play_sound("achievement")
    spawn_confetti(30)
    save_game()


def equip_cosmetic(cid, quiet=False):
    item = COSMETIC_BY_ID[cid]
    rewards_state().equipped[item["kind"]] = cid
    if not quiet:
        play_sound("click")
        save_game()


def buy_boost(bid):
    info = BOOST_BY_ID[bid]
    rewards_state()
    if state.coins < info["price"]:
        show_toast("Not enough coins", f"{info['name']} costs {info['price']} coins.", "warning")
        play_sound("error")
        return
    state.coins -= info["price"]
    add_to_bag(bid)
    show_toast(f"{info['name']} is in your Inventory", "Tap here, then press Use when you're ready.", "achievement", action=("inventory",))
    play_sound("achievement")
    save_game()


def daily_reward_available():
    return getattr(state, "last_claim_day", "") != time.strftime("%Y-%m-%d")


def login_streak_preview():
    """Streak length you'd have after claiming today (for the calendar)."""
    today = time.strftime("%Y-%m-%d")
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    last = getattr(state, "last_claim_day", "")
    streak = int(getattr(state, "login_streak", 0) or 0)
    if last == today:
        return streak
    return streak + 1 if last == yesterday else 1


def claim_daily_reward():
    if not daily_reward_available():
        return
    streak = login_streak_preview()
    state.login_streak = streak
    state.last_claim_day = time.strftime("%Y-%m-%d")
    kind, val = LOGIN_REWARDS[(streak - 1) % len(LOGIN_REWARDS)]
    if kind == "coins":
        add_coins(val, x=WIDTH // 2, y=320)
        show_toast(f"Day {streak} reward!", f"+{val} Ledger Coins. Come back tomorrow!", "achievement")
    elif kind == "chest":
        rewards_state().chests[val] = state.chests.get(val, 0) + 1
        show_toast(f"Day {streak} reward!", f"A {chest_name(val)}! Open it below.", "achievement")
    else:
        add_to_bag(val)
        show_toast(f"Day {streak} reward!", f"{BOOST_BY_ID[val]['name']} added to your Inventory.", "achievement", action=("inventory",))
    play_sound("victory")
    spawn_confetti(45)
    save_game()


def maybe_grant_free_daily_chest():
    """Everyone gets one free chest per day, just for showing up."""
    today = time.strftime("%Y-%m-%d")
    if getattr(state, "last_free_chest_day", "") == today:
        return
    state.last_free_chest_day = today
    rarity = _weighted({"common": 75, "rare": 20, "epic": 5})
    rewards_state().chests[rarity] = state.chests.get(rarity, 0) + 1
    show_toast("Free daily chest!", f"A {chest_name(rarity)} is waiting in Rewards. Tap to open!", "achievement", action=("rewards",))
    play_sound("dividend")
    save_game()


def unclaimed_levels():
    rewards_state()
    return [lv for lv in range(2, min(LEVEL_ROAD_MAX, state.level) + 1) if lv not in state.level_claimed]


def claim_level(lv, quiet=False):
    rewards_state()
    if lv in state.level_claimed or lv > state.level:
        return
    state.level_claimed.append(lv)
    for reward in level_reward(lv):
        kind, val = reward
        if kind == "coins":
            state.coins += int(val)
        elif kind == "chest":
            state.chests[val] = state.chests.get(val, 0) + 1
        elif kind == "boost":
            add_to_bag(val)
        elif kind == "cosmetic" and val not in state.owned_cosmetics:
            state.owned_cosmetics.append(val)
    if not quiet:
        show_toast(f"Level {lv} rewards claimed!", "Coins added. Chests are in Rewards, items in Inventory.", "achievement", action=("inventory",))
        play_sound("victory")
        spawn_confetti(40)
        save_game()


def claim_all_levels():
    todo = unclaimed_levels()
    for lv in todo:
        claim_level(lv, quiet=True)
    if todo:
        show_toast(f"Claimed {len(todo)} level reward{'s' if len(todo) != 1 else ''}!", "Coins added. Chests are in Rewards, items in Inventory.", "achievement", action=("inventory",))
        play_sound("victory")
        spawn_confetti(60)
        save_game()


def rewards_badge_count():
    rewards_state()
    return (1 if daily_reward_available() else 0) + sum(state.chests.values()) + len(unclaimed_levels())


def inventory_badge_count():
    return sum(rewards_state().boost_bag.values())


def hottest_sector():
    trends = getattr(state, "sector_trends", {}) or {}
    if trends:
        sector = max(trends, key=lambda k: trends[k])
        return sector, trends[sector]
    moves = {}
    for a in STOCKS:
        moves.setdefault(a["sector"], []).append(day_move_pct(a))
    if not moves:
        return None, 0.0
    sector = max(moves, key=lambda k: sum(moves[k]) / len(moves[k]))
    return sector, sum(moves[sector]) / len(moves[sector])


def draw_avatar_frame(surface, center, r, frame_id, now=None):
    """Decorative ring around an avatar icon. Several are animated."""
    now = time.time() if now is None else now
    cx, cy = center
    if frame_id in (None, "frame_classic"):
        return
    if frame_id == "frame_gold":
        pygame.draw.circle(surface, (214, 160, 20), center, r + 3, 4)
        a = now * 2.2
        pts = [(cx + math.cos(a + i * 0.06) * (r + 1), cy + math.sin(a + i * 0.06) * (r + 1)) for i in range(10)]
        pygame.draw.lines(surface, (255, 240, 170), False, pts, 2)
    elif frame_id == "frame_emerald":
        pygame.draw.circle(surface, (16, 160, 100), center, r + 3, 4)
        pygame.draw.circle(surface, (140, 235, 190), center, r + 5, 1)
    elif frame_id == "frame_neon":
        col = pygame.Color(0)
        col.hsva = ((now * 90) % 360, 80, 100, 100)
        glow = HiSurface((r * 2 + 24, r * 2 + 24), pygame.SRCALPHA)
        pygame.draw.circle(glow, (col.r, col.g, col.b, 70), (r + 12, r + 12), r + 8, 6)
        surface.blit(glow, (cx - r - 12, cy - r - 12))
        pygame.draw.circle(surface, (col.r, col.g, col.b), center, r + 3, 3)
    elif frame_id == "frame_fire":
        pygame.draw.circle(surface, (240, 90, 20), center, r + 3, 4)
        for i in range(10):
            a = i * math.tau / 10 + now * 0.8
            flick = 4 + 3 * math.sin(now * 12 + i * 1.7)
            base = (cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3))
            tip = (cx + math.cos(a) * (r + 5 + flick), cy + math.sin(a) * (r + 5 + flick))
            side = (math.cos(a + math.pi / 2) * 3, math.sin(a + math.pi / 2) * 3)
            pygame.draw.polygon(surface, (255, 170, 40), [(base[0] + side[0], base[1] + side[1]), tip, (base[0] - side[0], base[1] - side[1])])
    elif frame_id == "frame_diamond":
        pygame.draw.circle(surface, (150, 215, 255), center, r + 3, 4)
        pygame.draw.circle(surface, (255, 255, 255), center, r + 1, 1)
        for i in range(4):
            a = i * math.tau / 4 + now * 0.7
            tw = 0.5 + 0.5 * math.sin(now * 5 + i * 2)
            draw_star_shape(surface, cx + math.cos(a) * (r + 4), cy + math.sin(a) * (r + 4), 2.5 + 3 * tw, (255, 255, 255))
    elif frame_id == "frame_rainbow":
        segs = 18
        for i in range(segs):
            col = pygame.Color(0)
            col.hsva = ((i * 360 / segs + now * 80) % 360, 75, 100, 100)
            a0 = i * math.tau / segs
            pygame.draw.arc(surface, (col.r, col.g, col.b), (cx - r - 5, cy - r - 5, (r + 5) * 2, (r + 5) * 2), a0, a0 + math.tau / segs + 0.05, 4)
    elif frame_id == "frame_ticker":
        pygame.draw.circle(surface, (60, 64, 76), center, r + 3, 2)
        for i in range(10):
            a = i * math.tau / 10 + now * 0.9
            px, py = cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3)
            if i % 2 == 0:
                pygame.draw.polygon(surface, (40, 190, 100), [(px - 3, py + 2), (px + 3, py + 2), (px, py - 3.5)])
            else:
                pygame.draw.polygon(surface, (230, 70, 70), [(px - 3, py - 2), (px + 3, py - 2), (px, py + 3.5)])
    elif frame_id == "frame_candles":
        pygame.draw.circle(surface, (60, 64, 76), center, r + 2, 1)
        for i in range(12):
            a = i * math.tau / 12 + now * 0.35
            px, py = cx + math.cos(a) * (r + 4), cy + math.sin(a) * (r + 4)
            up = (i * 7) % 3 != 0
            col = (40, 190, 100) if up else (230, 70, 70)
            h = 5 + 2.5 * math.sin(now * 3 + i)
            pygame.draw.line(surface, col, (px, py - h / 2 - 2), (px, py + h / 2 + 2), 1)
            pygame.draw.rect(surface, col, (px - 1.6, py - h / 2, 3.2, h), border_radius=1)
    elif frame_id == "frame_ice":
        pygame.draw.circle(surface, (170, 225, 255), center, r + 3, 4)
        pygame.draw.circle(surface, (235, 250, 255), center, r + 1, 1)
        for i in range(6):
            a = i * math.tau / 6 + 0.3
            px, py = cx + math.cos(a) * (r + 4), cy + math.sin(a) * (r + 4)
            pygame.draw.polygon(surface, (255, 255, 255), [(px, py - 4), (px + 2.5, py), (px, py + 4), (px - 2.5, py)])
    elif frame_id == "frame_circuit":
        pygame.draw.circle(surface, (0, 190, 215), center, r + 3, 2)
        for i in range(8):
            a = i * math.tau / 8
            p1 = (cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3))
            p2 = (cx + math.cos(a) * (r + 8), cy + math.sin(a) * (r + 8))
            pygame.draw.line(surface, (0, 190, 215), p1, p2, 2)
            pygame.draw.circle(surface, (120, 245, 255), p2, 2.2)
        a = now * 2.5
        pygame.draw.circle(surface, (255, 255, 255), (cx + math.cos(a) * (r + 3), cy + math.sin(a) * (r + 3)), 2.6)
    elif frame_id == "frame_galaxy":
        pygame.draw.circle(surface, (90, 50, 190), center, r + 3, 4)
        pygame.draw.circle(surface, (170, 120, 255), center, r + 5, 1)
        for i in range(3):
            a = now * (1.4 + i * 0.5) + i * 2.1
            for k in range(4):
                aa = a - k * 0.12
                col = (255, 255, 255) if k == 0 else (190, 160, 255)
                pygame.draw.circle(surface, col, (cx + math.cos(aa) * (r + 5), cy + math.sin(aa) * (r + 5)), max(0.8, 2.4 - k * 0.5))
    elif frame_id in ("frame_bronze", "frame_bull"):
        gold = frame_id == "frame_bull"
        ring = (225, 170, 25) if gold else (176, 112, 62)
        light = (255, 235, 150) if gold else (225, 170, 120)
        pygame.draw.circle(surface, ring, center, r + 3, 4 if gold else 3)
        for side in (-1, 1):
            base_in = (cx + side * r * 0.35, cy - r * 0.92)
            base_out = (cx + side * r * 0.8, cy - r * 0.6)
            tip = (cx + side * r * 1.25, cy - r * 1.35)
            pygame.draw.polygon(surface, ring, [base_in, tip, base_out])
            pygame.draw.line(surface, light, base_in, tip, 1)
        if gold:
            a = now * 2
            pygame.draw.arc(surface, light, (cx - r - 3, cy - r - 3, (r + 3) * 2, (r + 3) * 2), a, a + 0.5, 2)


def chart_skin_colors(positive):
    colors = equipped("chart").get("colors")
    if not colors:
        return None
    return colors[0] if positive else colors[1]


def draw_coin_icon(surface, cx, cy, r):
    pygame.draw.circle(surface, (214, 150, 0), (cx, cy + 1), r)
    pygame.draw.circle(surface, (255, 200, 40), (cx, cy), r)
    pygame.draw.circle(surface, (255, 225, 120), (cx, cy), r * 0.68, max(1, int(r * 0.16)))


def draw_chest(surface, cx, cy, w, rarity, lid=0.0, shake=0.0):
    """A treasure chest in its rarity color. lid 0..1 lifts the lid."""
    body_col = {"common": (170, 110, 55), "rare": (46, 120, 210), "epic": (135, 70, 210), "legendary": (230, 160, 20)}[rarity]
    band = {"common": (150, 150, 160), "rare": (215, 225, 240), "epic": (255, 200, 60), "legendary": (255, 250, 220)}[rarity]
    dark = mix_color(body_col, (0, 0, 0), 0.3)
    h = w * 0.62
    ox = math.sin(time.time() * 40) * shake
    body = pygame.Rect(0, 0, w, h * 0.62)
    body.midbottom = (cx + ox, cy + h / 2)
    pygame.draw.rect(surface, dark, body.move(0, 3), border_radius=int(w * 0.08))
    pygame.draw.rect(surface, body_col, body, border_radius=int(w * 0.08))
    lid_r = pygame.Rect(0, 0, w + 4, h * 0.42)
    lid_r.midbottom = (cx + ox, body.y + 2 - lid * h * 0.5)
    pygame.draw.rect(surface, mix_color(body_col, (255, 255, 255), 0.12), lid_r, border_radius=int(w * 0.16))
    pygame.draw.rect(surface, band, (lid_r.x, lid_r.bottom - 4, lid_r.w, 4), border_radius=2)
    for fx in (0.22, 0.78):
        pygame.draw.rect(surface, band, (body.x + body.w * fx - 3, body.y, 6, body.h))
        pygame.draw.rect(surface, band, (lid_r.x + lid_r.w * fx - 3, lid_r.y + 2, 6, lid_r.h - 2))
    lock = pygame.Rect(0, 0, w * 0.16, w * 0.18)
    lock.midtop = (cx + ox, body.y - 2)
    pygame.draw.rect(surface, band, lock, border_radius=3)
    pygame.draw.circle(surface, dark, (lock.centerx, lock.centery + 1), max(1, w * 0.025))
    if w >= 40:
        # Rim light along the lid, and rivets on the corners.
        pygame.draw.line(surface, mix_color(body_col, (255, 255, 255), 0.45), (lid_r.x + w * 0.1, lid_r.y + 3),
                         (lid_r.right - w * 0.1, lid_r.y + 3), max(1, int(w * 0.02)))
        for rx in (body.x + w * 0.07, body.right - w * 0.07):
            for ry in (body.y + h * 0.1, body.bottom - h * 0.1):
                pygame.draw.circle(surface, band, (rx, ry), max(1, w * 0.022))
        ec = (cx + ox, body.y + body.h * 0.62)
        er = w * 0.085
        if rarity == "legendary":
            # Golden bull: head plus two curved horns.
            pygame.draw.circle(surface, dark, ec, er)
            for side in (-1, 1):
                pygame.draw.arc(surface, dark, (ec[0] + side * er * 0.4 - er * 0.9, ec[1] - er * 2.0, er * 1.8, er * 1.8),
                                0 if side > 0 else math.pi * 0.5, math.pi * 0.5 if side > 0 else math.pi, max(2, int(w * 0.03)))
            pygame.draw.circle(surface, band, (ec[0] - er * 0.35, ec[1] - er * 0.1), max(1, er * 0.16))
            pygame.draw.circle(surface, band, (ec[0] + er * 0.35, ec[1] - er * 0.1), max(1, er * 0.16))
        elif rarity == "epic":
            pts = [(ec[0], ec[1] - er), (ec[0] + er, ec[1]), (ec[0], ec[1] + er), (ec[0] - er, ec[1])]
            pygame.draw.polygon(surface, band, pts)
            pygame.draw.polygon(surface, dark, pts, max(1, int(w * 0.012)))


def draw_boost_icon(surface, bid, cx, cy, r):
    info = BOOST_BY_ID[bid]
    col = C(info["color"])
    pygame.draw.circle(surface, col, (cx, cy), r)
    white = text_on(col)  # glyph color: white, or dark on dark mode's brighter green/orange
    if bid == "xp2":
        draw_text(surface, "2x", font_small_bold if r < 20 else font_medium_bold, white, cx, cy - (9 if r < 20 else 11), align="center")
    elif bid == "coin2":
        draw_coin_icon(surface, cx - r * 0.2, cy + r * 0.1, r * 0.45)
        draw_coin_icon(surface, cx + r * 0.25, cy - r * 0.2, r * 0.45)
    elif bid == "payday":
        draw_icon(surface, "coin", cx, cy, white, r / 17.0)
    elif bid == "shield":
        s = r / 16.0
        pygame.draw.polygon(surface, white, [(cx - 9 * s, cy - 8 * s), (cx, cy - 11 * s), (cx + 9 * s, cy - 8 * s), (cx + 8 * s, cy + 3 * s), (cx, cy + 11 * s), (cx - 8 * s, cy + 3 * s)])
        pygame.draw.polygon(surface, col, [(cx - 5 * s, cy - 5 * s), (cx, cy - 7 * s), (cx + 5 * s, cy - 5 * s), (cx + 4 * s, cy + 2 * s), (cx, cy + 6 * s), (cx - 4 * s, cy + 2 * s)])
    elif bid == "insight":
        s = r / 16.0
        pygame.draw.ellipse(surface, white, (cx - 11 * s, cy - 6 * s, 22 * s, 12 * s))
        pygame.draw.circle(surface, col, (cx, cy), 4.5 * s)
        pygame.draw.circle(surface, white, (cx + 1.5 * s, cy - 1.5 * s), 1.5 * s)
    elif bid == "cash":
        s = r / 16.0
        pygame.draw.rect(surface, white, (cx - 11 * s, cy - 6 * s, 22 * s, 12 * s), border_radius=int(2 * s))
        pygame.draw.circle(surface, col, (cx, cy), 3.5 * s)


def draw_title_chip(surface, x, y, title_id, align="left", small=False):
    item = COSMETIC_BY_ID.get(title_id) or COSMETIC_BY_ID["title_rookie"]
    col = RARITY[item["rarity"]][1] if item["rarity"] != "common" else C("GRAY")
    font = font_tiny
    w = font.size(item["name"])[0] + (14 if item["rarity"] != "common" else 0)
    rect = pygame.Rect(0, y, w, 17)
    if align == "left":
        rect.x = x
    else:
        rect.right = x
    if item["rarity"] != "common":
        draw_rounded_rect(surface, rect, mix_color(col, C("CARD"), 0.85), radius=8, shadow=False)
        draw_text(surface, item["name"], font, col, rect.centerx, rect.y + 1, align="center")
    else:
        draw_text(surface, item["name"], font, col, rect.x, rect.y + 1)
    return rect


def draw_tier_pill(surface, x, y, rarity, align="left"):
    col = tier_color(rarity)
    label = tier_name(rarity).upper()
    w = font_tiny.size(label)[0] + 14
    r = pygame.Rect(0, y, w, 18)
    if align == "left":
        r.x = x
    elif align == "right":
        r.right = x
    else:
        r.centerx = x
    draw_rounded_rect(surface, r, mix_color(col, C("CARD"), 0.84), radius=9, shadow=False)
    draw_text(surface, label, font_tiny, col, r.centerx, r.y + 1, align="center")
    return r


class Diamond:
    """A spinning blue gem (Diamond Hands profit effect)."""

    def __init__(self, x, y, vx, vy):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.spin = random.uniform(0, 6.28)
        self.life = 1.0
        self.size = random.uniform(5, 9)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.16
        self.spin += 0.2
        self.life -= 0.012

    def draw(self, surface):
        if self.life <= 0:
            return
        w = max(1.5, self.size * abs(math.cos(self.spin)))
        h = self.size * 1.3
        pts = [(self.x, self.y - h), (self.x + w, self.y - h * 0.25), (self.x, self.y + h), (self.x - w, self.y - h * 0.25)]
        pygame.draw.polygon(surface, (120, 200, 255), pts)
        pygame.draw.polygon(surface, (230, 248, 255), [(self.x, self.y - h), (self.x + w * 0.5, self.y - h * 0.25), (self.x, self.y)])


class Firework:
    """Waits, then bursts into a ring of sparks."""

    def __init__(self, x, y, delay, color):
        self.x, self.y, self.color = x, y, color
        self.born = time.time()
        self.delay = delay
        self.life = 1.0
        self.done = False

    def update(self):
        if not self.done and time.time() - self.born >= self.delay:
            self.done = True
            for k in range(28):
                a = k * math.tau / 28
                sp = Spark(self.x, self.y, self.color)
                spd = random.uniform(3.5, 5.5)
                sp.vx, sp.vy = math.cos(a) * spd, math.sin(a) * spd
                particles.append(sp)
            play_sound("beep")
            self.life = 0

    def draw(self, surface):
        pass


class Rocket:
    """'To the moon': a rocket flies up with a flame trail, then bursts into stars."""

    def __init__(self, x):
        self.x, self.y = x, HEIGHT - 120
        self.vy = -9.0
        self.life = 1.0

    def update(self):
        self.y += self.vy
        self.x += math.sin(self.y * 0.03) * 0.8
        self.vy *= 0.985
        particles.append(Spark(self.x + random.uniform(-3, 3), self.y + 22, random.choice([(255, 170, 40), (255, 90, 40), (255, 230, 120)])))
        if self.y < 150:
            self.life = 0
            for k in range(36):
                a = k * math.tau / 36
                sp = Spark(self.x, self.y, random.choice([(255, 215, 0), (255, 255, 255), (120, 200, 255)]))
                spd = random.uniform(3, 6)
                sp.vx, sp.vy = math.cos(a) * spd, math.sin(a) * spd
                particles.append(sp)
            play_sound("victory")

    def draw(self, surface):
        if self.life <= 0:
            return
        x, y = self.x, self.y
        pygame.draw.polygon(surface, (235, 238, 245), [(x, y - 18), (x + 7, y - 4), (x + 7, y + 14), (x - 7, y + 14), (x - 7, y - 4)])
        pygame.draw.polygon(surface, (230, 70, 70), [(x, y - 18), (x + 5, y - 8), (x - 5, y - 8)])
        pygame.draw.circle(surface, (90, 170, 255), (x, y), 3.5)
        pygame.draw.polygon(surface, (230, 70, 70), [(x - 7, y + 6), (x - 12, y + 16), (x - 7, y + 14)])
        pygame.draw.polygon(surface, (230, 70, 70), [(x + 7, y + 6), (x + 12, y + 16), (x + 7, y + 14)])


def draw_fx_preview(surface, fx_id, rect, now):
    """Tiny looping preview of a profit celebration."""
    cx, cy = rect.center
    if fx_id == "fx_classic":
        for i in range(10):
            t = (now * 0.7 + i * 0.1) % 1
            x = rect.x + 10 + (i * 37) % (rect.w - 20)
            y = rect.y + 4 + t * (rect.h - 10)
            col = [(255, 90, 90), (70, 190, 255), (255, 200, 40), (120, 220, 120)][i % 4]
            pygame.draw.rect(surface, col, (x, y, 5, 5))
    elif fx_id == "fx_money":
        for i in range(6):
            t = (now * 0.5 + i / 6) % 1
            x = rect.x + 14 + (i * 53) % (rect.w - 28)
            y = rect.y + 4 + t * (rect.h - 14)
            pygame.draw.polygon(surface, (38, 150, 80), _rotated_rect_points(x, y, 16, 8, now * 120 + i * 40))
    elif fx_id == "fx_diamonds":
        for i in range(5):
            t = (now * 0.6 + i / 5) % 1
            x = rect.x + 16 + (i * 61) % (rect.w - 32)
            y = rect.y + 6 + t * (rect.h - 16)
            w = 5 * abs(math.cos(now * 3 + i))
            pygame.draw.polygon(surface, (120, 200, 255), [(x, y - 7), (x + max(1, w), y - 2), (x, y + 7), (x - max(1, w), y - 2)])
    elif fx_id == "fx_rocket":
        t = (now * 0.45) % 1
        y = rect.bottom - 10 - t * (rect.h - 14)
        pygame.draw.polygon(surface, (235, 238, 245), [(cx, y - 11), (cx + 5, y - 2), (cx + 5, y + 8), (cx - 5, y + 8), (cx - 5, y - 2)])
        pygame.draw.polygon(surface, (230, 70, 70), [(cx, y - 11), (cx + 4, y - 5), (cx - 4, y - 5)])
        for k in range(3):
            pygame.draw.circle(surface, (255, 170, 40), (cx + random.uniform(-2, 2), y + 11 + k * 4), 3 - k * 0.8)
    elif fx_id == "fx_fireworks":
        for j, (fx, fy, col) in enumerate(((0.3, 0.45, (255, 90, 120)), (0.7, 0.4, (90, 200, 255)))):
            t = (now * 0.6 + j * 0.5) % 1
            rr = 4 + t * 20
            for k in range(10):
                a = k * math.tau / 10
                pygame.draw.circle(surface, col, (rect.x + rect.w * fx + math.cos(a) * rr, rect.y + rect.h * fy + math.sin(a) * rr), max(1, 2.5 * (1 - t)))


def draw_cosmetic_preview(surface, item, rect, now):
    """Preview a cosmetic inside rect (frames on your avatar, titles as chips, etc.)."""
    pc = rect.center
    col = tier_color(item["rarity"])
    if item["kind"] == "frame":
        size = min(rect.h - 14, 44)
        draw_avatar_icon(surface, state.avatar, pc, size=size)
        draw_avatar_frame(surface, pc, size // 2, item["id"], now)
    elif item["kind"] == "title":
        w = min(rect.w - 12, font_small_bold.size(item["name"])[0] + 22)
        chip = pygame.Rect(0, 0, w, 26)
        chip.center = pc
        draw_rounded_rect(surface, chip, mix_color(col, C("CARD"), 0.8), radius=13, shadow=False)
        draw_text(surface, item["name"], font_small_bold, col if item["rarity"] != "common" else C("INK"), chip.centerx, chip.y + 4, align="center", max_width=chip.w - 8)
    elif item["kind"] == "chart":
        data = [100 + 8 * math.sin(k * 0.7 + len(item["id"])) + k * 1.2 for k in range(20)]
        ccol = (item.get("colors") or ((C("GREEN"), C("RED"))))[0]
        draw_mini_chart(surface, data, True, rect.x + 10, rect.y + 10, rect.w - 20, rect.h - 20, color=ccol, baseline=False)
    else:
        prev = surface.get_clip()
        surface.set_clip(prev.clip(rect))
        draw_fx_preview(surface, item["id"], rect, now)
        surface.set_clip(prev)


rewards_btns = []
rewards_shop_tab = "boosts"
inventory_btns = []
inventory_filter = "all"
levels_btns = []
chest_info_btns = []
_levels_scrolled = {"done": False}


def _rb(rect, key):
    rewards_btns.append((rect, key))


_hero_glow_cache = {}


def _hero_glow(size, circles, blur):
    """Soft glow for a dark hero card. Blurring takes ~0.2s, so each look is built once and reused."""
    key = (tuple(size), tuple(circles), blur, UI_SCALE)
    glow = _hero_glow_cache.get(key)
    if glow is None and not circles:
        pass
    if glow is None:
        circles = []
        glow = HiSurface(size, pygame.SRCALPHA)
        for color, center, r in circles:
            pygame.draw.circle(glow, color, center, r)
        glow.hi = soft_blur(glow.hi, _sc(blur))
        mask = HiSurface(size, pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=20)
        glow.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        if len(_hero_glow_cache) > 20:
            _hero_glow_cache.clear()
        _hero_glow_cache[key] = glow
    return glow


def _dark_hero(surface, rect, glow_col=(255, 190, 40)):
    draw_rounded_rect(surface, rect, SG_PANEL, radius=20, border_color=SG_LINE, border_width=1, shadow=False)
    surface.blit(_hero_glow(rect.size, [((*glow_col, 60), (70, rect.h // 2), 80)], 20), rect.topleft)


def draw_bag_icon(surface, cx, cy, color):
    pygame.draw.rect(surface, color, (cx - 9, cy - 5, 18, 15), border_radius=4)
    pygame.draw.arc(surface, color, (cx - 5, cy - 11, 10, 10), 0, math.pi, 2)
    pygame.draw.line(surface, (255, 255, 255), (cx - 5, cy + 1), (cx + 5, cy + 1), 2)


def draw_active_boosts(surface, y):
    active = [b for b in BOOSTS if not b.get("instant") and boost_active(b["id"])]
    if not active:
        return y
    x = 20
    for b in active:
        label = f"{b['name']}  {boost_left_label(b['id'])}"
        w = font_tiny.size(label)[0] + 44
        chip = pygame.Rect(x, y, w, 30)
        if chip.right > WIDTH - 20:
            x, y = 20, y + 36
            chip = pygame.Rect(x, y, w, 30)
        draw_rounded_rect(surface, chip, mix_color(C(b["color"]), C("CARD"), 0.85), radius=15, shadow=False)
        draw_boost_icon(surface, b["id"], chip.x + 15, chip.centery, 11)
        draw_text(surface, label, font_tiny, C(b["color"]), chip.x + 32, chip.y + 7)
        x = chip.right + 8
    return y + 42


def draw_rewards_tab(surface):
    global rewards_btns
    rewards_btns = []
    rewards_state()
    now = time.time()
    off = scroll_offset["rewards"]
    clip = pygame.Rect(0, CONTENT_TOP, WIDTH, CONTENT_BOTTOM - CONTENT_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y = CONTENT_TOP - off

    hero = pygame.Rect(20, y, WIDTH - 40, 110)
    _dark_hero(surface, hero)
    bob = math.sin(now * 2) * 3
    draw_coin_icon(surface, hero.x + 56, hero.y + 55 + bob, 30)
    draw_text(surface, "$", font_large_med, (200, 130, 0), hero.x + 56, hero.y + 41 + bob, align="center")
    draw_text(surface, "LEDGER COINS", font_tiny, (255, 215, 0), hero.x + 102, hero.y + 20)
    draw_text(surface, f"{int(tween('coins_shown', state.coins, 6)):,}", font_large, (255, 255, 255), hero.x + 102, hero.y + 34)
    draw_text(surface, "Earn by learning, trading, duels & streaks", font_tiny, (190, 185, 215), hero.x + 102, hero.y + 80, max_width=hero.w - 116)
    y = hero.bottom + 12

    # Shortcuts: Inventory and Level Road.
    bw = (WIDTH - 40 - 10) // 2
    for i, (key, label, sub, col, badge) in enumerate((
            ("inventory", "Inventory", "Use boosts & equip items", C("PURPLE"), inventory_badge_count()),
            ("levels", "Level Road", f"Level {state.level} rewards", C("GOLD"), len(unclaimed_levels())))):
        r = pygame.Rect(20 + i * (bw + 10), y, bw, 58)
        draw_rounded_rect(surface, r, C("CARD"), radius=16, border_color=col if badge else C("BORDER"), border_width=2 if badge else 1)
        ic = (r.x + 26, r.centery)
        pygame.draw.circle(surface, mix_color(col, C("CARD"), 0.82), ic, 17)
        if key == "inventory":
            draw_bag_icon(surface, ic[0], ic[1], col)
        else:
            draw_star_shape(surface, ic[0], ic[1], 10, col)
        draw_text(surface, label, font_small_bold, C("INK"), r.x + 50, r.y + 12)
        draw_text(surface, sub, font_tiny, C("GRAY"), r.x + 50, r.y + 32, max_width=r.w - 58)
        if badge:
            draw_count_badge(surface, r.right - 14, r.y + 12, badge)
        _rb(r, ("goto", key))
    y += 72

    y = draw_active_boosts(surface, y)

    # Daily login streak
    streak_now = int(getattr(state, "login_streak", 0) or 0)
    avail = daily_reward_available()
    preview = login_streak_preview()
    draw_text(surface, "Daily Streak", font_large_med, C("INK"), 20, y)
    fl = draw_text(surface, f"{streak_now} day{'s' if streak_now != 1 else ''}", font_small_bold, C("ORANGE"), WIDTH - 20, y + 6, align="right")
    draw_flame(surface, fl.x - 12, fl.centery, 0.9, lit=streak_now > 0)
    y += 34
    tw = (WIDTH - 40 - 6 * 6) // 7
    cycle_start = ((preview - 1) // 7) * 7
    for i, (kind, val) in enumerate(LOGIN_REWARDS):
        day = cycle_start + i + 1
        r = pygame.Rect(20 + i * (tw + 6), y, tw, 78)
        claimed = day < preview or (day == preview and not avail)
        today = day == preview and avail
        if today:
            draw_alpha_rect(surface, r.inflate(8, 8), C("GOLD"), 60 + 50 * math.sin(now * 4), radius=14)
        bg = C("GOLD_BG") if today else (C("PANEL_BG") if claimed else C("CARD"))
        draw_rounded_rect(surface, r, bg, radius=12, border_color=C("GOLD") if today else C("BORDER"), border_width=2 if today else 1, shadow=not claimed)
        draw_text(surface, f"Day {day}", font_tiny, C("GOLD") if today else C("GRAY"), r.centerx, r.y + 6, align="center")
        icy = r.y + 40
        if kind == "coins":
            draw_coin_icon(surface, r.centerx, icy, 11)
            draw_text(surface, str(val), font_tiny, C("INK"), r.centerx, r.bottom - 20, align="center")
        elif kind == "chest":
            draw_chest(surface, r.centerx, icy, 30, val)
            draw_text(surface, CHEST_SHORT[val], font_tiny, tier_color(val), r.centerx, r.bottom - 20, align="center", max_width=tw - 4)
        else:
            draw_boost_icon(surface, val, r.centerx, icy, 12)
            draw_text(surface, "Boost", font_tiny, C("PURPLE"), r.centerx, r.bottom - 20, align="center")
        if claimed:
            dim = HiSurface(r.size, pygame.SRCALPHA)
            pygame.draw.rect(dim, (*C("PANEL_BG"), 150), dim.get_rect(), border_radius=12)
            surface.blit(dim, r.topleft)
            draw_check(surface, (r.centerx, r.y + 40), 11, C("GREEN"))
    y += 90
    btn = pygame.Rect(20, y, WIDTH - 40, 48)
    if avail:
        draw_button(surface, btn, f"Claim Day {preview} reward", C("GOLD"), (255, 255, 255), font=font_body_bold, radius=14)
        _rb(btn, ("daily",))
    else:
        draw_button(surface, btn, "Come back tomorrow for more!", C("PANEL_BG"), C("GRAY"), font=font_small_bold, radius=14)
    y = btn.bottom + 24

    # Chests: tap any chest to see its odds and possible rewards.
    draw_text(surface, "Chests", font_large_med, C("INK"), 20, y)
    draw_text(surface, "Tap a chest to see the odds", font_tiny, C("GRAY"), WIDTH - 20, y + 8, align="right")
    y += 32
    cw = (WIDTH - 40 - 3 * 8) // 4
    for i, rar in enumerate(RARITY_ORDER):
        r = pygame.Rect(20 + i * (cw + 8), y, cw, 150)
        col = tier_color(rar)
        count = state.chests.get(rar, 0)
        draw_rounded_rect(surface, r, C("CARD"), radius=14, border_color=col if count else C("BORDER"), border_width=2 if count else 1)
        _rb(r, ("info", rar))
        shake = 1.5 if count and int(now * 2) % 3 == 0 else 0.0
        draw_chest(surface, r.centerx, r.y + 44, 52, rar, shake=shake)
        draw_text(surface, tier_name(rar), font_tiny, col, r.centerx, r.y + 74, align="center", max_width=r.w - 6)
        draw_text(surface, CHEST_SHORT[rar], font_tiny, C("GRAY"), r.centerx, r.y + 89, align="center")
        if count:
            draw_count_badge(surface, r.right - 12, r.y + 12, count)
        b = pygame.Rect(r.x + 8, r.bottom - 36, r.w - 16, 28)
        if count:
            draw_button(surface, b, "Open", col, (255, 255, 255), font=font_small_bold, radius=10)
            rewards_btns.insert(0, (b, ("open", rar)))
        elif rar in CHEST_PRICES:
            draw_button(surface, b, "", C("PANEL_BG"), C("INK"), radius=10)
            draw_coin_icon(surface, b.x + 16, b.centery, 7)
            draw_text(surface, str(CHEST_PRICES[rar]), font_tiny, C("INK"), b.x + 28, b.y + 6)
            rewards_btns.insert(0, (b, ("buychest", rar)))
        else:
            draw_text(surface, "Level reward", font_tiny, C("LIGHT_GRAY"), r.centerx, b.y + 6, align="center", max_width=r.w - 8)
    y += 168

    # Shop
    draw_text(surface, "Shop", font_large_med, C("INK"), 20, y)
    y += 34
    tabs = [("boosts", "Boosts"), ("frame", "Frames"), ("title", "Titles"), ("chart", "Charts"), ("fx", "Effects")]
    sw = (WIDTH - 40) // len(tabs)
    seg = pygame.Rect(20, y, WIDTH - 40, 38)
    draw_rounded_rect(surface, seg, C("PANEL_BG"), radius=19, shadow=False)
    for i, (k, label) in enumerate(tabs):
        r = pygame.Rect(20 + i * sw + 3, y + 3, sw - 6, 32)
        on = rewards_shop_tab == k
        if on:
            # In dark mode CARD is almost the same shade as the track, so lift the selected tab.
            draw_rounded_rect(surface, r, C("BORDER") if state.dark_mode else C("CARD"), radius=16)
        draw_text(surface, label, font_small_bold, C("INK") if on else C("GRAY"), r.centerx, r.y + 8, align="center", max_width=r.w - 4)
        _rb(r, ("shoptab", k))
    y += 50
    gw = (WIDTH - 40 - 10) // 2
    items = BOOSTS if rewards_shop_tab == "boosts" else [c for c in COSMETICS if c["kind"] == rewards_shop_tab]
    for i, item in enumerate(items):
        r = pygame.Rect(20 + (i % 2) * (gw + 10), y + (i // 2) * 170, gw, 160)
        if r.bottom < CONTENT_TOP - 10 or r.top > CONTENT_BOTTOM + 10:
            continue
        is_boost = rewards_shop_tab == "boosts"
        rar = item["rarity"]
        col = C(item["color"]) if is_boost else tier_color(rar)
        owned = (not is_boost) and item["id"] in state.owned_cosmetics
        eq = (not is_boost) and state.equipped.get(item["kind"]) == item["id"]
        draw_rounded_rect(surface, r, C("CARD"), radius=16, border_color=col if eq else C("BORDER"), border_width=2 if eq else 1)
        pv = pygame.Rect(r.x + 10, r.y + 10, r.w - 20, 62)
        draw_rounded_rect(surface, pv, mix_color(col, C("CARD"), 0.88), radius=12, shadow=False)
        if is_boost:
            draw_boost_icon(surface, item["id"], pv.centerx, pv.centery, 22)
        else:
            draw_cosmetic_preview(surface, item, pv, now)
        draw_text(surface, item["name"], font_small_bold, C("INK"), r.x + 12, r.y + 80, max_width=r.w - 24)
        draw_tier_pill(surface, r.x + 12, r.y + 101, rar)
        b = pygame.Rect(r.x + 10, r.bottom - 36, r.w - 20, 28)
        if is_boost:
            owned_n = state.boost_bag.get(item["id"], 0)
            if owned_n:
                draw_text(surface, f"x{owned_n} in bag", font_tiny, C("GRAY"), r.right - 12, r.y + 102, align="right")
            draw_button(surface, b, "", col, (255, 255, 255), radius=10)
            draw_coin_icon(surface, b.centerx - 20, b.centery, 7)
            draw_text(surface, str(item["price"]), font_small_bold, text_on(col), b.centerx - 8, b.y + 5)
            _rb(b, ("boost", item["id"]))
        elif eq:
            draw_button(surface, b, "Equipped", C("PANEL_BG"), col, font=font_small_bold, radius=10)
        elif owned:
            draw_button(surface, b, "Equip", C("INK"), C("CARD"), font=font_small_bold, radius=10)
            _rb(b, ("cosmetic", item["id"]))
        elif not item.get("price"):
            draw_button(surface, b, f"Level {item.get('level')} reward", C("GOLD_BG"), C("GOLD"), font=font_tiny, radius=10)
            _rb(b, ("goto", "levels"))
        else:
            afford = state.coins >= item["price"]
            draw_button(surface, b, "", col if afford else C("PANEL_BG"), (255, 255, 255), radius=10)
            draw_coin_icon(surface, b.centerx - 22, b.centery, 7)
            draw_text(surface, f"{item['price']}", font_small_bold, text_on(col) if afford else C("GRAY"), b.centerx - 10, b.y + 5)
            _rb(b, ("cosmetic", item["id"]))
    y += ((len(items) + 1) // 2) * 170 + 10
    clamp_scroll("rewards", (y - (CONTENT_TOP - off)) + off)
    surface.set_clip(prev)


def handle_rewards_click(pos):
    global rewards_shop_tab
    if not (CONTENT_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for rect, key in rewards_btns:
        if not rect.collidepoint(pos):
            continue
        kind = key[0]
        if kind == "daily":
            claim_daily_reward()
        elif kind == "open":
            open_chest(key[1])
        elif kind == "buychest":
            buy_chest(key[1])
        elif kind == "info":
            chest_info.update(rarity=key[1], opened=time.time())
            play_sound("click")
        elif kind == "shoptab":
            rewards_shop_tab = key[1]
            play_sound("click")
        elif kind == "boost":
            buy_boost(key[1])
        elif kind == "cosmetic":
            buy_cosmetic(key[1])
        elif kind == "goto":
            state.tab = key[1]
            scroll_offset[key[1]] = 0
            _levels_scrolled["done"] = False
            play_sound("click")
        return True
    return False


# ---- Inventory page -------------------------------------------------------

def draw_inventory_tab(surface):
    global inventory_btns
    inventory_btns = []
    rewards_state()
    now = time.time()
    off = scroll_offset["inventory"]
    clip = pygame.Rect(0, CONTENT_TOP, WIDTH, CONTENT_BOTTOM - CONTENT_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y = CONTENT_TOP - off
    draw_text(surface, "Inventory", font_sg_h2, C("INK"), 20, y)
    draw_text(surface, "Use your boosts and equip what you like", font_small, C("GRAY"), 20, y + 25)
    y += 56
    tabs = [("all", "All"), ("boosts", "Boosts"), ("frame", "Frames"), ("title", "Titles"), ("chart", "Charts"), ("fx", "Effects")]
    sw = (WIDTH - 40) / len(tabs)
    seg = pygame.Rect(20, y, WIDTH - 40, 36)
    draw_rounded_rect(surface, seg, C("PANEL_BG"), radius=18, shadow=False)
    for i, (k, label) in enumerate(tabs):
        r = pygame.Rect(int(20 + i * sw + 3), y + 3, int(sw - 6), 30)
        on = inventory_filter == k
        if on:
            draw_rounded_rect(surface, r, C("BORDER") if state.dark_mode else C("CARD"), radius=15)
        draw_text(surface, label, font_tiny, C("INK") if on else C("GRAY"), r.centerx, r.y + 7, align="center", max_width=r.w - 2)
        inventory_btns.append((r, ("filter", k)))
    y += 50

    if inventory_filter in ("all", "boosts"):
        if any(boost_active(b["id"]) for b in BOOSTS if not b.get("instant")):
            draw_text(surface, "ACTIVE NOW", font_tiny, C("GREEN"), 20, y)
            y = draw_active_boosts(surface, y + 20) + 4
        bag = {k: v for k, v in state.boost_bag.items() if v > 0}
        draw_text(surface, "BOOSTS  •  tap Use to start one", font_tiny, C("PURPLE"), 20, y)
        y += 20
        if not bag:
            note = pygame.Rect(20, y, WIDTH - 40, 52)
            draw_rounded_rect(surface, note, C("PANEL_BG"), radius=12, shadow=False)
            draw_text(surface, "No boosts yet. Get them from chests, the Level Road or the Shop.", font_tiny, C("GRAY"), note.centerx, note.y + 18, align="center", max_width=note.w - 20)
            y += 66
        for bid, count in bag.items():
            info = BOOST_BY_ID[bid]
            r = pygame.Rect(20, y, WIDTH - 40, 70)
            draw_rounded_rect(surface, r, C("CARD"), radius=14, border_color=C(info["color"]), border_width=1)
            draw_boost_icon(surface, bid, r.x + 34, r.centery, 20)
            draw_text(surface, f"{info['name']}", font_body_bold, C("INK"), r.x + 66, r.y + 11)
            draw_text(surface, f"x{count}", font_small_bold, C(info["color"]), r.x + 72 + font_body_bold.size(info["name"])[0], r.y + 13)
            draw_text(surface, info["desc"], font_tiny, C("GRAY"), r.x + 66, r.y + 36, max_width=r.w - 170)
            where = {"insight": "Shows in Market", "shield": "Protects your next duel", "payday": "Boosts your next paydays",
                     "xp2": "Works everywhere", "coin2": "Works everywhere", "cash": "Adds cash instantly"}.get(bid, "")
            draw_text(surface, where, font_tiny, C("LIGHT_GRAY"), r.x + 66, r.y + 51, max_width=r.w - 170)
            live = boost_active(bid) and not info.get("instant")
            b = pygame.Rect(r.right - 92, r.y + 19, 78, 34)
            draw_button(surface, b, "Add time" if live and "minutes" in info else "Use", C(info["color"]), (255, 255, 255), font=font_small_bold, radius=10)
            inventory_btns.append((b, ("use", bid)))
            y += 78
        y += 6
    if inventory_filter == "all" and sum(state.chests.values()):
        r = pygame.Rect(20, y, WIDTH - 40, 64)
        draw_rounded_rect(surface, r, C("GOLD_BG"), radius=14, border_color=C("GOLD"), border_width=1)
        best = max(state.chests, key=lambda k: RARITY_ORDER.index(k))
        draw_chest(surface, r.x + 36, r.centery, 40, best)
        n = sum(state.chests.values())
        draw_text(surface, f"You have {n} unopened chest{'s' if n != 1 else ''}", font_small_bold, C("INK"), r.x + 70, r.y + 14)
        draw_text(surface, "Open them in Rewards", font_tiny, C("GRAY"), r.x + 70, r.y + 36)
        b = pygame.Rect(r.right - 86, r.y + 16, 72, 32)
        draw_button(surface, b, "Open", C("GOLD"), (255, 255, 255), font=font_small_bold, radius=10)
        inventory_btns.append((b, ("goto", "rewards")))
        y += 78
    gw = (WIDTH - 40 - 10) // 2
    for kind in ("frame", "title", "chart", "fx"):
        if inventory_filter not in ("all", kind):
            continue
        owned = [c for c in COSMETICS if c["kind"] == kind and c["id"] in state.owned_cosmetics]
        total = len([c for c in COSMETICS if c["kind"] == kind])
        draw_text(surface, f"{KIND_LABELS[kind].upper()}S  •  {len(owned)} of {total} collected", font_tiny, C("PURPLE"), 20, y)
        y += 20
        for i, item in enumerate(owned):
            r = pygame.Rect(20 + (i % 2) * (gw + 10), y + (i // 2) * 148, gw, 140)
            col = tier_color(item["rarity"])
            eq = state.equipped.get(kind) == item["id"]
            if CONTENT_TOP - 150 < r.y < CONTENT_BOTTOM + 10:
                draw_rounded_rect(surface, r, C("CARD"), radius=14, border_color=col if eq else C("BORDER"), border_width=2 if eq else 1)
                pv = pygame.Rect(r.x + 8, r.y + 8, r.w - 16, 56)
                draw_rounded_rect(surface, pv, mix_color(col, C("CARD"), 0.88), radius=10, shadow=False)
                draw_cosmetic_preview(surface, item, pv, now)
                draw_text(surface, item["name"], font_small_bold, C("INK"), r.x + 10, r.y + 70, max_width=r.w - 20)
                draw_tier_pill(surface, r.x + 10, r.y + 90, item["rarity"])
                b = pygame.Rect(r.x + 8, r.bottom - 34, r.w - 16, 26)
                if eq:
                    draw_button(surface, b, "Equipped", C("PANEL_BG"), col, font=font_tiny, radius=9)
                else:
                    draw_button(surface, b, "Equip", C("INK"), C("CARD"), font=font_tiny, radius=9)
                    inventory_btns.append((b, ("equip", item["id"])))
        y += ((len(owned) + 1) // 2) * 148 + 10
    clamp_scroll("inventory", (y - (CONTENT_TOP - off)) + off)
    surface.set_clip(prev)


def handle_inventory_click(pos):
    global inventory_filter
    if not (CONTENT_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for rect, key in inventory_btns:
        if rect.collidepoint(pos):
            if key[0] == "filter":
                inventory_filter = key[1]
                scroll_offset["inventory"] = 0
                play_sound("click")
            elif key[0] == "use":
                use_bag_item(key[1])
            elif key[0] == "equip":
                equip_cosmetic(key[1])
                spawn_sparks(pos[0], pos[1], C("PURPLE"), 10)
            elif key[0] == "goto":
                state.tab = key[1]
                play_sound("click")
            return True
    return False


# ---- Level Road -----------------------------------------------------------

def _reward_label(reward):
    """(name, kind label, accent color) for one Level Road / chest reward."""
    kind, val = reward
    if kind == "coins":
        return f"{val} coins", "Ledger Coins", SG_GOLD
    if kind == "chest":
        return chest_name(val), "Chest  ·  open it in Rewards", _tier_glow(val)
    if kind == "boost":
        b = BOOST_BY_ID[val]
        return b["name"], "Boost  ·  " + b["desc"], SG_CYAN
    item = COSMETIC_BY_ID[val]
    return item["name"], f"{tier_name(item['rarity'])} {KIND_LABELS[item['kind']].lower()}", _tier_glow(item["rarity"])


def _tier_glow(rarity):
    """Rarity colors tuned to read on the night background."""
    return {"common": (180, 190, 205), "rare": (96, 165, 250), "epic": (192, 132, 252), "legendary": SG_GOLD}[rarity]


def _reward_icon(surface, reward, cx, cy, now):
    kind, val = reward
    if kind == "coins":
        draw_coin_icon(surface, cx, cy, 10)
    elif kind == "chest":
        draw_chest(surface, cx, cy + 1, 28, val)
    elif kind == "boost":
        draw_boost_icon(surface, val, cx, cy, 11)
    else:
        item = COSMETIC_BY_ID[val]
        if item["kind"] == "frame":
            draw_avatar_icon(surface, state.avatar, (cx, cy), size=24, dark=True)
            draw_avatar_frame(surface, (cx, cy), 12, val, now)
        elif item["kind"] == "title":
            pygame.draw.rect(surface, _tier_glow(item["rarity"]), (cx - 12, cy - 7, 24, 14), border_radius=7)
            pygame.draw.line(surface, SG_BG, (cx - 6, cy), (cx + 6, cy), 2)
        else:
            pygame.draw.circle(surface, _tier_glow(item["rarity"]), (cx, cy), 11)
            draw_star_shape(surface, cx, cy, 6, SG_BG)


LEVEL_ROW_H = 46


def _level_card_height(lv):
    return 56 + len(level_reward(lv)) * LEVEL_ROW_H + (len(sg_wrap("New looks: " + ", ".join(level_looks(lv)), font_small, WIDTH - 180)) * 19 + 14
                                                       if level_looks(lv) else 0) + 8


def draw_levels_tab(surface):
    global levels_btns
    levels_btns = []
    rewards_state()
    now = time.time()
    lv_now = state.level
    last = min(LEVEL_ROAD_MAX, max(lv_now + 8, 20))
    road_x = 46
    card_x = 84
    card_w = WIDTH - 20 - card_x
    heights = {lv: _level_card_height(lv) for lv in range(2, last + 1)}
    list_top = 206
    offsets, acc = {}, 0
    for lv in range(2, last + 1):
        offsets[lv] = acc
        acc += heights[lv] + 16
    if not _levels_scrolled["done"]:
        _levels_scrolled["done"] = True
        target = unclaimed_levels()[0] if unclaimed_levels() else min(last, max(2, lv_now))
        scroll_offset["levels"] = max(0, list_top + offsets[target] - 90)
    off = scroll_offset["levels"]
    clip = pygame.Rect(0, GAME_TOP, WIDTH, CONTENT_BOTTOM - GAME_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y0 = GAME_TOP + 6 - off

    # Hero: level badge, XP to next level, claim-all.
    hero = pygame.Rect(20, y0, WIDTH - 40, 170)
    pygame.draw.rect(surface, SG_PANEL, hero, border_radius=24)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    surface.blit(_hero_glow(hero.size, [((*SG_GOLD, 60), (70, 70), 80), ((*SG_PURPLE, 60), (hero.w - 40, hero.h), 90)], 18), hero.topleft)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    bc = (hero.x + 72, hero.y + 78)
    req = max(1, lv_now * 100)
    sg_progress_ring(surface, bc, 50, tween("lvl_ring", min(1.0, state.xp / req), 5), SG_GOLD, 8)
    pygame.draw.circle(surface, SG_PANEL_2, bc, 38)
    draw_text(surface, "LEVEL", font_tiny, SG_MUTED, bc[0], bc[1] - 24, align="center")
    draw_text(surface, str(lv_now), font_sg_title, SG_TEXT, bc[0], bc[1] - 10, align="center")
    tx = hero.x + 144
    draw_text(surface, "Level road", font_tiny, SG_MUTED, tx, hero.y + 24)
    draw_text(surface, f"XP to Level {lv_now + 1}", font_body, SG_MUTED, tx, hero.y + 44)
    draw_text(surface, f"{max(0, req - state.xp):,} XP", font_sg_h2, SG_TEXT, tx, hero.y + 64)
    draw_text(surface, "Learn, trade and battle to earn XP", font_tiny, SG_MUTED, tx, hero.y + 98, max_width=hero.right - 16 - tx)
    pending = unclaimed_levels()
    b = pygame.Rect(hero.x + 16, hero.bottom - 52, hero.w - 32, 40)
    if pending:
        pulse = 0.5 + 0.5 * math.sin(now * 4)
        glow = _sg_glow(SG_GOLD, 50, int(20 + 30 * pulse))
        surface.blit(glow, (b.centerx - 100, b.centery - 100))
        pygame.draw.rect(surface, mix_color(SG_GOLD, (0, 0, 0), 0.35), b.move(0, 4), border_radius=14)
        pygame.draw.rect(surface, SG_GOLD, b, border_radius=14)
        draw_text(surface, f"Claim {len(pending)} reward{'s' if len(pending) != 1 else ''}", font_body_bold, SG_INK, b.centerx, b.centery - 10,
                  align="center")
        levels_btns.append((b, ("all",)))
    else:
        pygame.draw.rect(surface, SG_PANEL, b, border_radius=14)
        draw_text(surface, "All rewards claimed. Keep leveling up!", font_small_bold, SG_MUTED, b.centerx, b.centery - 9, align="center")
    draw_text(surface, "Every level has a reward. Every 5th level is a milestone.", font_small, SG_MUTED, 20, y0 + 180,
              max_width=WIDTH - 40)

    base_y = y0 + list_top
    # The road: gold where you've been, dashed ahead.
    road_top, road_bot = base_y - 10, base_y + acc
    you_y = base_y + offsets.get(min(last, max(2, lv_now)), 0) + 30
    pygame.draw.line(surface, SG_PANEL_2, (road_x, road_top), (road_x, road_bot), 8)
    pygame.draw.line(surface, SG_GOLD, (road_x, road_top), (road_x, you_y), 6)
    for yy in range(int(you_y) + 12, int(road_bot), 22):
        pygame.draw.line(surface, SG_LINE, (road_x, yy), (road_x, yy + 10), 2)
    flow = (now * 60) % 40
    for yy in range(int(road_top), int(you_y) - 6, 40):
        py = yy + flow
        if py < you_y:
            pygame.draw.circle(surface, mix_color(SG_GOLD, (255, 255, 255), 0.6), (road_x, py), 2)

    for lv in range(2, last + 1):
        h = heights[lv]
        ry = base_y + offsets[lv]
        if ry > CONTENT_BOTTOM + 10 or ry + h + 16 < GAME_TOP - 10:
            continue
        reached = lv <= lv_now
        claimed = lv in state.level_claimed
        ready = reached and not claimed
        milestone = lv % 5 == 0
        accent = SG_GOLD if milestone else SG_PURPLE

        # Road node.
        nc = (road_x, ry + 30)
        nr = 22 if milestone else 17
        if ready:
            draw_soft_ripples(surface, nc, nr, SG_GOLD, now, period=1.8)
        pygame.draw.circle(surface, SG_BG, nc, nr + 4)
        pygame.draw.circle(surface, (SG_GOLD if reached else SG_PANEL_2), nc, nr)
        if milestone:
            pygame.draw.circle(surface, SG_GOLD if reached else mix_color(SG_GOLD, SG_BG, 0.5), nc, nr, 3)
        draw_text(surface, str(lv), font_body_bold if milestone else font_small_bold, SG_INK if reached else SG_MUTED, nc[0],
                  nc[1] - (11 if milestone else 9), align="center")

        card = pygame.Rect(card_x, ry, card_w, h)
        pygame.draw.rect(surface, mix_color(SG_PANEL, SG_GOLD, 0.08) if ready else SG_PANEL, card, border_radius=20)
        border = SG_GOLD if (ready or milestone) else SG_LINE
        pygame.draw.rect(surface, border, card, 2 if (ready or milestone) else 1, border_radius=20)
        # Header: level name on the left, status on the right. Rewards never share this row.
        draw_text(surface, f"Level {lv}", font_medium_bold, SG_TEXT, card.x + 16, card.y + 16)
        if milestone:
            mw = font_tiny.size("MILESTONE")[0] + 18
            chip = pygame.Rect(card.x + 16 + font_medium_bold.size(f"Level {lv}")[0] + 10, card.y + 18, mw, 20)
            pygame.draw.rect(surface, mix_color(SG_GOLD, SG_BG, 0.75), chip, border_radius=10)
            draw_text(surface, "MILESTONE", font_tiny, SG_GOLD, chip.centerx, chip.y + 2, align="center")
        sb = pygame.Rect(card.right - 96, card.y + 12, 82, 32)
        if ready:
            pygame.draw.rect(surface, mix_color(SG_GOLD, (0, 0, 0), 0.35), sb.move(0, 3), border_radius=12)
            pygame.draw.rect(surface, SG_GOLD, sb, border_radius=12)
            draw_text(surface, "Claim", font_small_bold, SG_INK, sb.centerx, sb.centery - 9, align="center")
            levels_btns.append((sb, ("claim", lv)))
        elif claimed:
            pygame.draw.circle(surface, SG_GREEN, (sb.right - 12, sb.centery), 11)
            _sg_check(surface, sb.right - 12, sb.centery, 0.6, SG_BG, 2)
            draw_text(surface, "Claimed", font_tiny, SG_GREEN, sb.right - 28, sb.centery - 8, align="right")
        else:
            draw_padlock(surface, sb.right - 12, sb.centery, 13, SG_MUTED)
            draw_text(surface, "Locked", font_tiny, SG_MUTED, sb.right - 26, sb.centery - 8, align="right")
        pygame.draw.line(surface, SG_LINE, (card.x + 16, card.y + 52), (card.right - 16, card.y + 52), 1)

        # One reward per row: icon tile, name, what it is.
        iy = card.y + 60
        for rw in level_reward(lv):
            name, kind_label, col = _reward_label(rw)
            tile = pygame.Rect(card.x + 14, iy, 36, 36)
            pygame.draw.rect(surface, SG_PANEL_2, tile, border_radius=10)
            _reward_icon(surface, rw, tile.centerx, tile.centery, now)
            dim = not reached
            draw_text(surface, name, font_small_bold, SG_MUTED if dim else SG_TEXT, tile.right + 12, iy + 1, max_width=card.right - 16 - tile.right - 12)
            draw_text(surface, kind_label, font_tiny, mix_color(col, SG_PANEL, 0.35) if dim else col, tile.right + 12, iy + 20,
                      max_width=card.right - 16 - tile.right - 12)
            iy += LEVEL_ROW_H
        looks = level_looks(lv)
        if looks:
            lines = sg_wrap("New looks: " + ", ".join(looks), font_small, WIDTH - 180)
            for i, line in enumerate(lines):
                draw_text(surface, line, font_small, SG_MUTED, card.x + 16, iy + 4 + i * 19, max_width=card.w - 32)

    # "You" marker rides the road at your level.
    if base_y + offsets.get(min(last, max(2, lv_now)), 0) < CONTENT_BOTTOM:
        bob = math.sin(now * 3) * 3
        mc = (road_x, int(you_y - 44 + bob))
        tag = pygame.Rect(0, 0, 44, 22)
        tag.center = mc
        pygame.draw.rect(surface, SG_CYAN, tag, border_radius=11)
        pygame.draw.polygon(surface, SG_CYAN, [(mc[0] - 5, tag.bottom - 1), (mc[0] + 5, tag.bottom - 1), (mc[0], tag.bottom + 6)])
        draw_text(surface, "You", font_tiny, SG_INK, tag.centerx, tag.y + 3, align="center")
    clamp_scroll_full("levels", base_y + acc + 20 - y0)
    surface.set_clip(prev)


def handle_levels_click(pos):
    if not (GAME_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for rect, key in levels_btns:
        if rect.collidepoint(pos):
            if key[0] == "all":
                claim_all_levels()
            else:
                claim_level(key[1])
            return True
    return False


# ---- Chest odds sheet -----------------------------------------------------

def draw_chest_info(surface):
    global chest_info_btns
    rar = chest_info["rarity"]
    if not rar:
        return
    chest_info_btns = []
    now = time.time()
    ov = HiSurface((WIDTH, HEIGHT), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 130))
    surface.blit(ov, (0, 0))
    slide = ease_out_cubic((now - chest_info["opened"]) / 0.3)
    sheet = pygame.Rect(0, int(34 + (HEIGHT - 34) * (1 - slide)), WIDTH, HEIGHT - 34)
    draw_rounded_rect(surface, sheet, C("CARD"), radius=26)
    pygame.draw.rect(surface, C("BORDER"), (WIDTH // 2 - 22, sheet.y + 8, 44, 5), border_radius=3)
    col = tier_color(rar)
    close = pygame.Rect(WIDTH - 54, sheet.y + 20, 36, 36)
    draw_rounded_rect(surface, close, C("PANEL_BG"), radius=18, shadow=False)
    pygame.draw.line(surface, C("GRAY"), (close.centerx - 6, close.centery - 6), (close.centerx + 6, close.centery + 6), 2)
    pygame.draw.line(surface, C("GRAY"), (close.centerx + 6, close.centery - 6), (close.centerx - 6, close.centery + 6), 2)
    chest_info_btns.append((close, ("close",)))
    draw_chest(surface, 70, sheet.y + 62, 76, rar, shake=0.8 if state.chests.get(rar) else 0)
    draw_text(surface, chest_name(rar), font_medium_bold, C("INK"), 124, sheet.y + 30)
    draw_tier_pill(surface, 124, sheet.y + 56, rar)
    own = state.chests.get(rar, 0)
    draw_text(surface, f"You own {own}", font_tiny, C("GRAY"), 124, sheet.y + 80)
    y = sheet.y + 112

    # Tier odds as a stacked bar + legend.
    odds = CHEST_TIER_ODDS[rar]
    draw_text(surface, "DROP CHANCES BY TIER", font_tiny, col, 20, y)
    y += 20
    bar = pygame.Rect(20, y, WIDTH - 40, 16)
    x = bar.x
    for tier in RARITY_ORDER:
        pct = odds.get(tier, 0)
        if not pct:
            continue
        w = bar.w * pct / 100
        pygame.draw.rect(surface, tier_color(tier), (x, bar.y, max(2, w - 2), bar.h), border_radius=5)
        x += w
    y += 26
    for tier in RARITY_ORDER:
        pct = odds.get(tier, 0)
        if not pct:
            continue
        pygame.draw.circle(surface, tier_color(tier), (28, y + 8), 5)
        draw_text(surface, tier_name(tier), font_small_bold, C("INK"), 42, y)
        draw_text(surface, f"{pct}%", font_small_bold, tier_color(tier), WIDTH - 20, y, align="right")
        y += 22
    y += 4
    draw_text(surface, f"Then: {PRIZE_TYPE_ODDS['cosmetic']}% cosmetic  •  {PRIZE_TYPE_ODDS['coins']}% coins  •  {PRIZE_TYPE_ODDS['boost']}% boost",
              font_tiny, C("GRAY"), 20, y, max_width=WIDTH - 40)
    y += 16
    draw_text(surface, "You never get a cosmetic you already own. Own them all? Bonus coins instead.", font_tiny, C("GRAY"), 20, y, max_width=WIDTH - 40)
    y += 26

    # Everything you could get, grouped by tier.
    draw_text(surface, "POSSIBLE REWARDS", font_tiny, col, 20, y)
    y += 20
    list_bottom = sheet.bottom - 84
    prev = surface.get_clip()
    surface.set_clip(prev.clip(pygame.Rect(0, y, WIDTH, list_bottom - y)))
    for tier in RARITY_ORDER:
        if not odds.get(tier):
            continue
        cos, boosts, (lo, hi) = chest_pool(tier)
        pill = draw_tier_pill(surface, 20, y, tier)
        draw_text(surface, f"{lo}–{hi} coins", font_tiny, C("GRAY"), pill.right + 8, y + 1)
        y += 22
        names = [b["name"] for b in boosts] + [c["name"] + (" (owned)" if c["id"] in state.owned_cosmetics else "") for c in cos]
        line = ""
        for nm in names:
            test = (line + "  •  " + nm) if line else nm
            if font_tiny.size(test)[0] > WIDTH - 48:
                draw_text(surface, line, font_tiny, C("INK"), 28, y)
                y += 16
                line = nm
            else:
                line = test
        if line:
            draw_text(surface, line, font_tiny, C("INK"), 28, y)
            y += 16
        y += 8
    surface.set_clip(prev)

    b = pygame.Rect(20, sheet.bottom - 70, WIDTH - 40, 50)
    if own:
        draw_button(surface, b, f"Open {chest_name(rar)}", col, (255, 255, 255), font=font_body_bold, radius=14)
        chest_info_btns.append((b, ("open",)))
    elif rar in CHEST_PRICES:
        afford = state.coins >= CHEST_PRICES[rar]
        draw_button(surface, b, "", col if afford else C("PANEL_BG"), (255, 255, 255), radius=14)
        draw_coin_icon(surface, b.centerx - 58, b.centery, 9)
        draw_text(surface, f"Buy for {CHEST_PRICES[rar]} coins", font_body_bold, text_on(col) if afford else C("GRAY"), b.centerx - 44, b.y + 14)
        chest_info_btns.append((b, ("buy",)))
    else:
        draw_button(surface, b, "Earn it on the Level Road (every 10 levels)", C("GOLD_BG"), C("GOLD"), font=font_small_bold, radius=14)
        chest_info_btns.append((b, ("levels",)))


def handle_chest_info_click(pos):
    rar = chest_info["rarity"]
    if not rar:
        return False
    for rect, key in chest_info_btns:
        if rect.collidepoint(pos):
            if key[0] == "close":
                chest_info["rarity"] = None
                play_sound("click")
            elif key[0] == "open":
                open_chest(rar)
            elif key[0] == "buy":
                buy_chest(rar)
            elif key[0] == "levels":
                chest_info["rarity"] = None
                state.tab = "levels"
                _levels_scrolled["done"] = False
            return True
    if pos[1] < 34:
        chest_info["rarity"] = None
    return True


# ---- Chest opening --------------------------------------------------------

CHEST_TAPS = 3


def _chest_glow_color(rarity):
    return {"common": (205, 150, 90), "rare": (96, 165, 250), "epic": (192, 132, 252), "legendary": (250, 204, 21)}[rarity]


def draw_chest_opening(surface):
    """Chest reveal: it drops in, you tap it three times to crack it open, then the prize bursts out."""
    rar = chest_anim["rarity"]
    if not rar:
        return
    now = time.time()
    t = now - chest_anim["start"]
    kind, val = chest_anim["reward"][0], chest_anim["reward"][1]
    tier = chest_anim["reward"][2] if len(chest_anim["reward"]) > 2 else rar
    col = _chest_glow_color(tier)
    stage = chest_anim.get("stage", "drop")
    calm = getattr(state, "reduced_motion", False)
    if t < 0.2:
        blit_color_overlay(surface, SG_BG, int(255 * t / 0.2))
    else:
        _sg_background(surface, now, _chest_glow_color(rar))
    cx, cy = WIDTH // 2, 420

    if stage == "drop" and t >= 0.5:
        chest_anim["stage"] = stage = "ready"
        play_sound("stamp")
        spawn_sparks(cx, cy + 50, (200, 190, 230), 18)

    if stage in ("drop", "ready"):
        taps = chest_anim.get("taps", 0)
        # Suspense: rarer chests climb through the tier colors as you tap.
        order = RARITY_ORDER
        shown_tier = order[min(order.index(rar), taps)] if order.index(rar) >= 2 else rar
        gcol = _chest_glow_color(shown_tier)
        charge = taps / CHEST_TAPS
        e = 1.0 if calm else _ease_back(t / 0.5, 1.4)
        y = cy - (1 - e) * 520
        k = max(0.0, 1 - (now - chest_anim.get("tap_at", 0.0)) / 0.3)
        glow = _sg_glow(gcol, int(80 + 50 * charge), int(40 + 60 * charge + 40 * k))
        surface.blit(glow, (cx - glow.get_width() // 2, y - glow.get_height() // 2))
        if taps:
            # Light leaking from under the lid.
            for i in range(5 + taps * 3):
                a = -math.pi / 2 + (i - (4 + taps * 3) / 2) * 0.16 + math.sin(now * 3 + i) * 0.04
                ln = 70 + 60 * charge + 20 * math.sin(now * 5 + i)
                pygame.draw.line(surface, mix_color(gcol, (255, 255, 255), 0.4), (cx, y - 40), (cx + math.cos(a) * ln, y - 40 + math.sin(a) * ln),
                                 2)
        scale_w = 170 * (1 + 0.08 * k)
        draw_chest(surface, cx, y, scale_w, rar, lid=0.06 * charge + 0.05 * k, shake=0 if calm else (1.2 + 6 * k + 2 * charge))
        draw_text(surface, chest_name(rar), font_sg_h2, SG_TEXT, cx, cy + 110, align="center")
        if stage == "ready":
            pulse = 0.5 + 0.5 * math.sin(now * 4)
            draw_text(surface, "Tap the chest to open it" if taps == 0 else ("Keep tapping!" if taps < CHEST_TAPS - 1 else "One more!"),
                      font_body_bold, mix_color(SG_MUTED, SG_TEXT, pulse), cx, cy + 150, align="center")
            for i in range(CHEST_TAPS):
                pygame.draw.circle(surface, gcol if i < taps else SG_PANEL_2, (cx - 24 + i * 24, cy + 188), 7)
        return

    # Burst: shockwave, rays, the prize rising out, then the reward card flips in.
    rt = now - chest_anim["burst_at"]
    if calm:
        rt = max(rt, 1.3)
    if not chest_anim.get("sparked"):
        chest_anim["sparked"] = True
        flash_screen((255, 255, 255), 0.3)
        play_sound("victory")
        spawn_confetti(80 if tier in ("epic", "legendary") else 40)
        for _ in range(30):
            particles.append(Spark(cx, cy - 20, col))
        spawn_coins(cx, cy - 20, True, 14 if tier in ("epic", "legendary") else 8)
    rays = _sg_layer("chest_rays", (520, 520))
    n_rays = 18 if tier in ("epic", "legendary") else 12
    for i in range(n_rays):
        a = i * math.tau / n_rays + rt * 0.5
        pygame.draw.polygon(rays, (*col, 46), [(260, 260), (260 + math.cos(a - 0.08) * 260, 260 + math.sin(a - 0.08) * 260),
                                               (260 + math.cos(a + 0.08) * 260, 260 + math.sin(a + 0.08) * 260)])
    card_c = (cx, 300)
    surface.blit(rays, (card_c[0] - 260, card_c[1] - 260))
    sw = ease_out_cubic(rt / 0.5)
    if sw < 1:
        r = 40 + 380 * sw
        pygame.draw.circle(surface, mix_color(col, (255, 255, 255), 0.5), (cx, cy - 20), r, max(1, int(8 * (1 - sw))))
    chest_y = cy + 420 * ease_out_cubic(rt / 0.9)
    if chest_y < HEIGHT + 60:
        draw_chest(surface, cx, chest_y, 110, rar, lid=min(1.0, rt / 0.15))

    # Prize orb rises out of the chest.
    op = _clamp01(rt / 0.5)
    if op < 1:
        start_y = cy - 40
        oy = start_y + (card_c[1] - start_y) * ease_out_cubic(op)
        pygame.draw.circle(surface, col, (cx, oy), 16 + 10 * op)
        pygame.draw.circle(surface, (255, 255, 255), (cx, oy), 8 + 4 * op)
        return

    # Reward card flips in.
    fp = ease_out_cubic((rt - 0.5) / 0.35)
    w, h = int(300 * max(0.04, fp)), 290
    card = pygame.Rect(0, 0, w, h)
    card.center = card_c
    glow = _sg_glow(col, 110, 70)
    surface.blit(glow, (card_c[0] - glow.get_width() // 2, card_c[1] - glow.get_height() // 2))
    pygame.draw.rect(surface, SG_PANEL, card, border_radius=26)
    pygame.draw.rect(surface, col, card, 3, border_radius=26)
    if fp < 0.9:
        return
    draw_text(surface, "YOU GOT", font_tiny, SG_MUTED, card.centerx, card.y + 20, align="center")
    ic = pygame.Rect(0, 0, card.w - 60, 96)
    ic.midtop = (card.centerx, card.y + 42)
    if kind == "coins":
        draw_coin_icon(surface, ic.centerx, ic.centery, 36)
        name, sub = f"+{val} coins", "Added to your Ledger Coins"
    elif kind == "boost":
        draw_boost_icon(surface, val, ic.centerx, ic.centery, 34)
        name, sub = BOOST_BY_ID[val]["name"], BOOST_BY_ID[val]["desc"]
    else:
        item = COSMETIC_BY_ID[val]
        draw_cosmetic_preview(surface, item, ic, now)
        name, sub = item["name"], f"New {KIND_LABELS[item['kind']].lower()}"
    draw_text(surface, name, font_large_med, SG_TEXT, card.centerx, card.y + 150, align="center", max_width=card.w - 30)
    pill_t = tier_name(tier)
    pw = font_tiny.size(pill_t)[0] + 24
    pill = pygame.Rect(card.centerx - pw // 2, card.y + 186, pw, 24)
    pygame.draw.rect(surface, mix_color(col, SG_PANEL, 0.7), pill, border_radius=12)
    draw_text(surface, pill_t, font_tiny, col, pill.centerx, pill.y + 4, align="center")
    # Shine sweep across the card.
    sweep = ((now - chest_anim["burst_at"]) * 0.7) % 1.6
    if sweep < 1:
        sx = card.x - 40 + (card.w + 80) * sweep
        shine = _sg_layer("chest_shine", (40, card.h))
        for i in range(40):
            a = int(50 * (1 - abs(i - 20) / 20))
            pygame.draw.line(shine, (255, 255, 255, a), (i, 0), (i, card.h))
        pc = surface.get_clip()
        surface.set_clip(card.inflate(-4, -4))
        surface.blit(shine, (sx - 20, card.y))
        surface.set_clip(pc)
    for i, line in enumerate(sg_wrap(sub, font_small, card.w - 40, 2)):
        draw_text(surface, line, font_small, SG_MUTED, card.centerx, card.y + 222 + i * 19, align="center")

    chest_anim["equip_btn"] = chest_anim["collect_btn"] = None
    if rt > 1.0:
        tmp = {}
        by = HEIGHT - 150
        if kind in ("cosmetic", "boost"):
            _sg_button(surface, pygame.Rect(20, by, WIDTH - 40, 58), "equip", "Equip now" if kind == "cosmetic" else "Use it now",
                       col, SG_INK, btns=tmp)
            _sg_button(surface, pygame.Rect(20, by + 72, WIDTH - 40, 48), "collect", "Keep it in my Inventory", SG_PANEL_2, SG_TEXT,
                       font=font_body_bold, depth=4, btns=tmp)
        else:
            _sg_button(surface, pygame.Rect(20, by + 30, WIDTH - 40, 60), "collect", "Collect", SG_GOLD, SG_INK, btns=tmp)
        chest_anim["equip_btn"] = tmp.get("equip")
        chest_anim["collect_btn"] = tmp.get("collect")


def handle_chest_opening_click(pos):
    if not chest_anim["rarity"]:
        return False
    stage = chest_anim.get("stage", "drop")
    now = time.time()
    if stage == "ready":
        chest_anim["taps"] = chest_anim.get("taps", 0) + 1
        chest_anim["tap_at"] = now
        cx, cy = WIDTH // 2, 420
        spawn_sparks(cx, cy - 30, _chest_glow_color(chest_anim["rarity"]), 10 + 6 * chest_anim["taps"])
        if chest_anim["taps"] >= CHEST_TAPS:
            chest_anim["stage"] = "burst"
            chest_anim["burst_at"] = now
        else:
            play_sound("stamp" if chest_anim["taps"] == 1 else "pop")
        return True
    if stage == "burst" and now - chest_anim["burst_at"] > 1.0:
        eq = chest_anim.get("equip_btn")
        if eq and eq.collidepoint(pos):
            reward = chest_anim["reward"]
            if reward[0] == "cosmetic":
                equip_cosmetic(reward[1], quiet=True)
            elif reward[0] == "boost":
                use_bag_item(reward[1])
            save_game()
            spawn_confetti(25)
        chest_anim.update(rarity=None, reward=None, sparked=False, equip_btn=None, collect_btn=None, stage="drop", taps=0)
        play_sound("click")
    return True


# ----------------------------
# DRAW HELPERS
# ----------------------------

# ----------------------------
# MOTION + POLISH HELPERS
# ----------------------------

_tweens = {}
NET_WORTH_SAMPLE_SECONDS = 1.0
TUTORIAL_TICK_SECONDS = 0.8
_price_flash = {}
_shadow_cache = {}
_fade_masks = {}
_background_cache = {}


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def mix_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def tween(key, target, speed=9.0):
    """Glide a displayed number toward its real value instead of jumping to it."""
    now = time.time()
    cur = _tweens.get(key)
    if cur is None:
        _tweens[key] = [target, now]
        return target
    value, last = cur
    dt = min(0.1, max(0.0, now - last))
    value += (target - value) * (1 - math.exp(-speed * dt))
    if abs(target - value) < 0.005:
        value = target
    cur[0], cur[1] = value, now
    return value


def price_flash(key, value, duration=0.9, min_move=0.0015):
    """Return (strength 0-1, went_up) for a brief highlight after a value changes.
    Tiny moves don't flash, so a calm market doesn't blink every second."""
    rec = _price_flash.get(key)
    if rec is None:
        _price_flash[key] = rec = [value, 0.0, True]
    elif rec[0] != value and abs(value - rec[0]) >= abs(rec[0]) * min_move:
        rec[2] = value >= rec[0]
        rec[0], rec[1] = value, time.time()
    return max(0.0, 1 - (time.time() - rec[1]) / duration), rec[2]


def draw_alpha_rect(surface, rect, color, alpha, radius=0):
    rect = pygame.Rect(rect)
    if alpha <= 0 or rect.w <= 0 or rect.h <= 0:
        return
    layer = HiSurface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(layer, (*color[:3], int(alpha)), layer.get_rect(), border_radius=radius)
    surface.blit(layer, rect.topleft)


def soft_blur(img, radius):
    """Gaussian blur for soft glows and shadows. Blurring a smaller copy and scaling it back up
    looks the same for soft edges but is 7-50x faster than blurring every Retina pixel."""
    radius = int(radius)
    f = 4 if radius >= 32 else (2 if radius >= 12 else 1)
    w, h = img.get_size()
    if f == 1 or w < f * 4 or h < f * 4:
        return pygame.transform.gaussian_blur(img, max(1, radius))
    small = pygame.transform.smoothscale(img, (max(1, w // f), max(1, h // f)))
    small = pygame.transform.gaussian_blur(small, max(1, radius // f))
    return pygame.transform.smoothscale(small, (w, h))


def soft_shadow(w, h, radius, blur, alpha):
    """Blurred drop shadow for a rounded card, cached because card sizes repeat."""
    key = (w, h, radius, blur, alpha)
    img = _shadow_cache.get(key)
    if img is None:
        pad = blur * 2
        hs = pygame.Surface((_sc(w + pad * 2), _sc(h + pad * 2)), pygame.SRCALPHA)
        pygame.draw.rect(hs, (0, 0, 0, alpha), (_sc(pad), _sc(pad), _sc(w), _sc(h)), border_radius=_sc(radius))
        hs = soft_blur(hs, _sc(blur))
        img = HiSurface(None, hi=hs)
        if len(_shadow_cache) > 400:
            _shadow_cache.clear()
        _shadow_cache[key] = img
    return img, blur * 2


def fade_mask(w, h):
    """Vertical white-to-clear mask used to fade chart fills toward the bottom."""
    key = (w, h)
    m = _fade_masks.get(key)
    if m is None:
        hs = pygame.Surface((max(1, _sc(w)), max(1, _sc(h))), pygame.SRCALPHA)
        rows = hs.get_height()
        for yy in range(rows):
            hs.fill((255, 255, 255, int(255 * (1 - yy / rows) ** 1.5)), (0, yy, hs.get_width(), 1))
        m = HiSurface(None, hi=hs)
        if len(_fade_masks) > 200:
            _fade_masks.clear()
        _fade_masks[key] = m
    return m


# Brand-inspired badge colors so the market list is easy to scan: (background, text).
BRAND_COLORS = {
    "AAPL": ((72, 72, 78), None), "NKE": ((250, 84, 0), None), "DIS": ((17, 60, 145), None),
    "MCD": ((218, 41, 28), (255, 199, 44)), "SBUX": ((0, 112, 74), None), "KO": ((228, 0, 43), None),
    "MSFT": ((0, 120, 212), None), "GOOGL": ((66, 133, 244), None), "AMZN": ((35, 47, 62), (255, 153, 0)),
    "META": ((0, 100, 224), None), "NFLX": ((20, 20, 20), (229, 9, 20)), "SONY": ((30, 30, 30), None),
    "TSLA": ((204, 0, 0), None), "NVDA": ((118, 185, 0), None), "AMD": ((25, 25, 25), (0, 160, 90)),
    "INTC": ((0, 113, 197), None), "JPM": ((70, 55, 45), None), "V": ((26, 31, 113), (247, 182, 0)),
    "MA": ((235, 0, 27), (255, 170, 0)), "BAC": ((1, 33, 105), None), "WMT": ((0, 113, 220), (255, 194, 32)),
    "COST": ((0, 93, 170), None), "TGT": ((204, 0, 0), None), "HD": ((249, 99, 2), None),
    "PFE": ((0, 149, 213), None), "JNJ": ((212, 0, 0), None), "BA": ((0, 57, 166), None),
    "F": ((0, 52, 120), None), "UBER": ((20, 20, 20), None), "ABNB": ((255, 90, 95), None),
    "RBLX": ((45, 45, 50), None), "LULU": ((213, 43, 30), None), "GS": ((100, 137, 180), None),
    "BLK": ((20, 20, 20), None), "SHOP": ((120, 170, 50), None), "SPOT": ((30, 215, 96), (20, 20, 20)),
    "NTDOY": ((230, 0, 18), None), "MOON": ((109, 40, 217), None), "CRM": ((0, 161, 224), None), "ORCL": ((199, 70, 52), None),
    "ADBE": ((250, 15, 0), None), "CSCO": ((4, 159, 217), None), "QCOM": ((50, 83, 220), None),
    "PEP": ((0, 75, 147), None), "MELI": ((255, 230, 0), (45, 50, 119)), "CMCSA": ((100, 50, 160), None),
    "CVX": ((0, 84, 164), None), "XOM": ((237, 27, 45), None), "CAT": ((255, 205, 17), (20, 20, 20)),
    "GE": ((0, 91, 170), None), "UPS": ((80, 50, 30), (255, 181, 0)), "UNH": ((0, 38, 119), None),
    "CVS": ((204, 0, 0), None), "LOW": ((0, 73, 144), None), "MAR": ((150, 30, 40), None),
    "DAL": ((0, 50, 100), None), "BKNG": ((0, 53, 128), None), "EA": ((255, 71, 71), None),
    "DELL": ((0, 118, 206), None), "ETSY": ((241, 100, 30), None), "YUM": ((110, 40, 140), None),
    "CMG": ((69, 20, 0), None), "PG": ((0, 60, 150), None), "SCHW": ((0, 160, 223), None),
}


def brand_colors(ticker):
    bg, fg = BRAND_COLORS.get(ticker, (None, None))
    if bg is None:
        # Stable, pleasant color for anything not in the table.
        h = int(hashlib.md5(ticker.encode()).hexdigest()[:4], 16) % 360
        col = pygame.Color(0)
        col.hsva = (h, 55, 70, 100)
        bg = (col.r, col.g, col.b)
    if fg is None:
        lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        fg = (20, 20, 20) if lum > 170 else (255, 255, 255)
    return bg, fg


def draw_search_icon(surface, x, y, color):
    pygame.draw.circle(surface, color, (x + 7, y + 7), 6, 2)
    pygame.draw.line(surface, color, (x + 11, y + 11), (x + 16, y + 16), 2)


def draw_star(surface, cx, cy, r, color):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    pygame.draw.polygon(surface, color, pts)


def draw_logo_mark(surface, cx, cy, size=48):
    """Ledger app mark: rising bars inside a rounded tile."""
    tile = pygame.Rect(0, 0, size, size)
    tile.center = (cx, cy)
    draw_rounded_rect(surface, tile, C("INK"), radius=size // 4)
    bw = size // 7
    gap = size // 10
    total = bw * 3 + gap * 2
    x0 = cx - total // 2
    for i, frac in enumerate((0.32, 0.52, 0.74)):
        bh = int(size * frac)
        pygame.draw.rect(surface, C("GREEN") if i == 2 else C("CARD"),
                         (x0 + i * (bw + gap), tile.bottom - size // 6 - bh, bw, bh), border_radius=2)


def draw_app_background(surface):
    surface.fill(C("BG"))


def _fit_text_image(text, font, max_width):
    """Render text cleanly without letting long labels spill into neighboring UI."""
    text = str(text)
    if max_width <= 0:
        return font.render("", True, C("INK"))
    if font.size(text)[0] <= max_width:
        return font.render(text, True, C("INK"))

    # First try an ellipsis at the same font size. This preserves the game's
    # typography instead of unexpectedly shrinking a label until it is tiny.
    ellipsis = "…"
    lo, hi = 0, len(text)
    best = ellipsis
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if font.size(candidate)[0] <= max_width:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return font.render(best, True, C("INK"))


def draw_text(surface, text, font, color, x, y, align="left", max_width=None, shadow=False):
    """Global text renderer: crisp antialiasing, safe margins, and optional depth."""
    text = str(text)
    if max_width is None:
        # Prevent accidental full-screen overflow while leaving normal labels alone.
        if align == "left":
            max_width = max(20, WIDTH - int(x) - 18)
        elif align == "right":
            max_width = max(20, int(x) - 18)
        else:
            max_width = max(20, WIDTH - 36)

    if font.size(text)[0] > max_width:
        # Re-render the fitted text in the requested color.
        ellipsis = "…"
        lo, hi = 0, len(text)
        fitted = ellipsis
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = text[:mid].rstrip() + ellipsis
            if font.size(candidate)[0] <= max_width:
                fitted = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        img = font.render(fitted, True, color)
    else:
        img = font.render(text, True, color)

    rect = img.get_rect()
    if align == "left":
        rect.topleft = (x, y)
    elif align == "right":
        rect.topright = (x, y)
    elif align == "center":
        rect.midtop = (x, y)

    # Extremely subtle depth on important text only. Small labels stay flat and clean.
    if shadow and (font.get_height() >= 18):
        shadow_img = font.render(text if font.size(text)[0] <= max_width else fitted, True, (0, 0, 0))
        shadow_img.set_alpha(0)
        surface.blit(shadow_img, rect.move(0, 1))
    surface.blit(img, rect)
    return rect


def draw_text_outlined(surface, text, font, color, x, y, outline=(0, 0, 0), align="center"):
    """Big celebratory text with a solid outline so it stays readable over busy art."""
    for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        draw_text(surface, text, font, outline, x + ox, y + oy, align=align)
    return draw_text(surface, text, font, color, x, y, align=align)


def draw_rounded_rect(surface, rect, color, radius=10, border_color=None, border_width=0, shadow=True):
    rect = pygame.Rect(rect)
    if shadow and rect.w >= 40 and rect.h >= 24:
        img, pad = soft_shadow(rect.w, rect.h, radius, 6, 14)
        surface.blit(img, (rect.x - pad, rect.y - pad + 3))
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    if border_color and border_width:
        pygame.draw.rect(surface, border_color, rect, width=border_width, border_radius=radius)


def draw_ticker_badge(surface, ticker, x, y, size=40):
    rect = pygame.Rect(x, y, size, size)
    bg, fg = brand_colors(ticker)
    draw_rounded_rect(surface, rect, bg, radius=max(8, size // 4))
    # Soft top sheen so the tile reads as a little app icon.
    draw_alpha_rect(surface, (rect.x, rect.y, rect.w, rect.h // 2), (255, 255, 255), 26, radius=max(8, size // 4))
    font = font_small_bold if len(ticker) <= 3 and size >= 40 else font_tiny
    img = font.render(ticker, True, fg)
    if img.get_width() > size - 6:
        img = font_tiny.render(ticker[:4], True, fg)
    surface.blit(img, img.get_rect(center=rect.center))
    return rect


def draw_button(surface, rect, label, bg_color, text_color, font=font_body_bold, radius=10):
    rect = pygame.Rect(rect)
    if tuple(bg_color[:3]) == THEMES["dark"]["INK"]:
        # A white "primary" button becomes the game's gold call-to-action, like the Market and Learn screens.
        bg_color, text_color = SG_GOLD, SG_INK
    mouse = pygame.mouse.get_pos()
    hovered = rect.collidepoint(mouse) and state.screen_mode in ("signin", "google_form", "avatar", "tutorial", "playing")
    pressed = hovered and pygame.mouse.get_pressed()[0]
    if pressed:
        # Squeeze slightly while held down, like a real button.
        rect = rect.inflate(-max(4, rect.w // 25), -max(3, rect.h // 12))
    draw_rounded_rect(surface, rect, bg_color, radius=radius, shadow=not pressed)
    if state.dark_mode and tuple(bg_color[:3]) in (C("PANEL_BG"), C("CARD"), C("BG")):
        # Gray buttons nearly vanish against dark cards, so give them a thin outline.
        pygame.draw.rect(surface, C("BORDER"), rect, 1, border_radius=radius)
    if hovered and not pressed:
        lift = (255, 255, 255) if sum(bg_color) < 380 else (0, 0, 0)
        draw_alpha_rect(surface, rect, lift, 22, radius=radius)
    if tuple(text_color[:3]) == (255, 255, 255):
        text_color = text_on(bg_color)
    img = font.render(str(label), True, text_color)
    surface.blit(img, img.get_rect(center=rect.center))


def draw_mini_chart(surface, data, positive, x, y, w, h, color=None, baseline=None,
                    anim_key=None, tick_at=None, tick_len=1.0):
    """Area chart. With anim_key/tick_at, the newest segment draws in and the whole
    line scrolls left continuously between ticks instead of jumping once per tick.
    Returns the on-screen point for each value in data (None if scrolled off)."""
    if len(data) < 2:
        return []
    now = time.time()
    n = len(data)
    smooth = anim_key is not None and tick_at and n >= 3 and not getattr(state, "reduced_motion", False)
    if smooth:
        p = max(0.0, min(1.0, (now - tick_at) / max(0.05, tick_len)))
        step = w / (n - 2)
        xs = [x + (i - p) * step for i in range(n - 1)] + [x + w]
        vals = list(data[:-1]) + [data[-2] + (data[-1] - data[-2]) * p]
        visible = vals[1:]
        # Ease the vertical scale too, so a new high/low doesn't snap the chart.
        lo = tween((anim_key, "lo"), min(visible), 5.0)
        hi = tween((anim_key, "hi"), max(visible), 5.0)
    else:
        xs = [x + (i / (n - 1)) * w for i in range(n)]
        vals = list(data)
        lo, hi = min(vals), max(vals)
    rng = hi - lo
    color = color or (C("GREEN") if positive else C("RED"))

    def to_y(v):
        return y + h - ((v - lo) / rng) * h if rng else y + h / 2

    points = [(px, max(y - 2, min(y + h + 2, to_y(v)))) for px, v in zip(xs, vals)]
    big = h >= 30

    prev_clip = surface.get_clip()
    surface.set_clip(prev_clip.clip(pygame.Rect(x, y - 14, w + 14, h + 28)))

    # Area fill that fades out toward the bottom.
    fill_surface = HiSurface((w, h + 4), pygame.SRCALPHA)
    local_points = [(px - x, py - y) for px, py in points]
    pygame.draw.polygon(fill_surface, (*color, 70 if big else 55),
                        local_points + [(local_points[-1][0], h + 4), (local_points[0][0], h + 4)])
    fill_surface.blit(fade_mask(w, h + 4), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    surface.blit(fill_surface, (x, y))

    # Dashed line marking where the period opened.
    if big if baseline is None else baseline:
        by = max(y, min(y + h, to_y(data[0])))
        for dx in range(0, int(w), 9):
            pygame.draw.line(surface, C("LIGHT_GRAY"), (x + dx, by), (x + min(w, dx + 4), by), 1)

    # Soft glow under the line, then the crisp line itself.
    pad = 6
    glow = HiSurface((w + pad * 2, h + pad * 2), pygame.SRCALPHA)
    pygame.draw.lines(glow, (*color, 40), False, [(px - x + pad, py - y + pad) for px, py in points], 6 if big else 4)
    surface.blit(glow, (x - pad, y - pad))
    pygame.draw.lines(surface, color, False, points, 2)

    # Pulsing "live" dot on the latest value.
    ex, ey = points[-1]
    pulse = (now * 0.9) % 1.0
    rr = 3 + 7 * pulse
    ring = HiSurface((24, 24), pygame.SRCALPHA)
    pygame.draw.circle(ring, (*color, int(110 * (1 - pulse))), (12, 12), min(11, rr))
    surface.blit(ring, (ex - 12, ey - 12))
    pygame.draw.circle(surface, color, (ex, ey), 3.5)
    surface.set_clip(prev_clip)
    return [pt if pt[0] >= x - 0.5 else None for pt in points]



def wrap_text(text, font, max_width):
    words = text.split(" ")
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if font.size(test)[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


signin_google_btn = None
signin_google_up_btn = None
google_mode = "in"
signin_guest_btn = None
signin_google_btn = None
google_name_rect = None
google_email_rect = None
google_continue_btn = None
google_back_btn = None
name_input_rect = None
pw_input_rect = None
avatar_continue_btn = None
tutorial_next_btn = None
tutorial_skip_btn = None



def _avatar_rgb(rgb, delta=0):
    return tuple(max(0, min(255, int(v + delta))) for v in rgb)


def _avatar_rect(x, y, w, h, s):
    return pygame.Rect(int(x), int(y), max(1, int(w * s)), max(1, int(h * s)))


def _hair_cap(surface, col, cx, cy, r, line_y):
    """Draw the top of a hair-coloured circle only above line_y, giving a clean cap
    that never spills onto the face."""
    old = surface.get_clip()
    top = cy - r * 3
    area = pygame.Rect(cx - r * 3, top, r * 6, max(1, int(line_y - top)))
    surface.set_clip(old.clip(area))
    pygame.draw.circle(surface, col, (cx, cy), r)
    surface.set_clip(old)


def _hair_shine(surface, cx, cy, r, s, col):
    """Soft highlight arc on top of the hair so it reads as glossy instead of flat."""
    if r < 10:
        return
    light = tuple(min(255, int(c + (255 - c) * 0.35)) for c in col)
    rect = pygame.Rect(0, 0, int(r * 1.3), int(r * 1.3))
    rect.center = (int(cx - r * 0.12), int(cy - r * 0.18))
    pygame.draw.arc(surface, light, rect, 1.85, 2.75, max(1, int(1.1 * s)))


def _hair_style_for(style, accessory):
    # Tall styles would poke through hats/crowns, so they fall back to a neat short cut.
    if accessory in ("cap", "crown") and style in ("spiky", "mohawk", "bun"):
        return "short"
    return style


def draw_hair_back(surface, style, cx, cy, r, s, col, shadow, accessory="none"):
    """Hair that sits BEHIND the head (drawn before the face)."""
    style = _hair_style_for(style, accessory)
    if style == "long":
        rect = pygame.Rect(cx - r - int(3 * s), cy - int(r * 0.4), 2 * r + int(6 * s), r + int(12 * s))
        pygame.draw.rect(surface, col, rect, border_radius=max(3, int(8 * s)))
    elif style == "bob":
        # Rounded helmet of hair that ends at the jaw, with a soft inward curve at the tips.
        w = 2 * r + int(5 * s)
        rect = pygame.Rect(0, 0, w, int(r * 1.62))
        rect.midtop = (cx, cy - r - int(1.5 * s))
        pygame.draw.rect(surface, shadow, rect.move(0, max(1, int(s))), border_radius=int(r * 0.95))
        pygame.draw.rect(surface, col, rect, border_radius=int(r * 0.95))
    elif style == "ponytail":
        # Tapered tail swinging behind the head, built from overlapping circles for a smooth edge.
        sway = math.sin(time.time() * 2.2) * 0.06 * r
        keys = [(0.62, -0.78, 0.34), (0.92, -0.45, 0.31), (1.08, -0.08, 0.27), (1.14, 0.3, 0.22), (1.12, 0.64, 0.16), (1.05, 0.9, 0.1)]
        pts = []
        for a, b in zip(keys, keys[1:]):
            for k in range(4):  # interpolate so the outline is a smooth taper, not bumps
                t = k / 4
                pts.append((cx + r * (a[0] + (b[0] - a[0]) * t) + sway * t, cy + r * (a[1] + (b[1] - a[1]) * t), r * (a[2] + (b[2] - a[2]) * t)))
        for px, py, rr in pts:
            pygame.draw.circle(surface, shadow, (px, py + max(1, s * 0.6)), rr)
        for px, py, rr in pts:
            pygame.draw.circle(surface, col, (px, py), rr)
        # Hair tie.
        tie = pygame.Rect(0, 0, max(3, int(r * 0.34)), max(2, int(r * 0.17)))
        tie.center = (int(cx + r * 0.8), int(cy - r * 0.64))
        pygame.draw.rect(surface, (124, 58, 237), tie, border_radius=max(1, int(r * 0.08)))
    elif style == "curly":
        # A crown of curls that follows the head outline (no flat brim).
        for layer, colr in ((1, shadow), (0, col)):
            for k in range(11):
                ang = math.pi * (1.02 + k / 10 * 0.96)
                rr = r * (0.36 if 2 <= k <= 8 else 0.3)
                px = cx + math.cos(ang) * r * 0.93
                py = cy + math.sin(ang) * r * 0.93 + layer * max(1, s * 0.7)
                pygame.draw.circle(surface, colr, (px, py), rr)
    elif style == "afro":
        pygame.draw.circle(surface, col, (cx, cy - int(3 * s)), r + int(8 * s))
        pygame.draw.circle(surface, shadow, (cx, cy - int(3 * s)), r + int(8 * s), max(1, int(s)))
    elif style == "bun":
        pygame.draw.circle(surface, col, (cx, cy - r - int(2 * s)), max(3, int(5.5 * s)))


def draw_hair_front(surface, style, cx, cy, r, s, col, shadow, accessory="none", skin_hint=(240, 200, 160)):
    """Hair that sits ON the head: only ever above the brow line, so it cannot cover the face."""
    style = _hair_style_for(style, accessory)
    if accessory == "cap":
        return
    line = cy - int(r * 0.58)
    lw = max(1, int(s))
    if style in ("short", "bun"):
        _hair_cap(surface, col, cx, cy, r + int(1.5 * s), line)
    elif style == "ponytail":
        # Hair pulled back: a smooth cap with a side part, swept toward the tail.
        _hair_cap(surface, col, cx, cy, r + int(1.5 * s), line + int(r * 0.04))
        soft = tuple((a_ + b_) // 2 for a_, b_ in zip(col, shadow))
        pygame.draw.arc(surface, soft, (cx - r * 0.2, cy - r * 0.92, r * 1.3, r * 0.7), 0.4, 1.7, max(1, int(0.8 * s)))
        _hair_shine(surface, cx, cy, r, s, col)
    elif style == "fade":
        # Taper fade: full-colour crown, sides that step lighter toward the skin,
        # and a short, soft sideburn. Everything follows the curve of the head.
        mid = tuple(int(a_ + (b_ - a_) * 0.42) for a_, b_ in zip(col, skin_hint))
        low = tuple(int(a_ + (b_ - a_) * 0.7) for a_, b_ in zip(col, skin_hint))
        top_line = cy - int(r * 0.6)
        _hair_cap(surface, mid, cx, cy, r + int(0.6 * s), top_line)
        old = surface.get_clip()
        crown = pygame.Rect(0, 0, int(r * 1.24), int((top_line - (cy - r)) * 2 + 4 * s))
        crown.midtop = (cx, cy - r - int(1 * s))
        surface.set_clip(old.clip(pygame.Rect(cx - r * 2, cy - r * 2, r * 4, top_line - (cy - r * 2))))
        pygame.draw.ellipse(surface, col, crown)
        surface.set_clip(old.clip(pygame.Rect(cx - r - 3, top_line, 2 * r + 6, int(r * 0.28))))
        pygame.draw.circle(surface, low, (cx, cy), r)
        pygame.draw.circle(surface, skin_hint, (cx, cy + int(r * 0.04)), int(r * 0.9))
        surface.set_clip(old)
        # A few comb strokes on top for texture.
        for k in range(3):
            x0 = cx - r * 0.3 + k * r * 0.28
            pygame.draw.line(surface, shadow, (x0, cy - r * 0.86), (x0 + r * 0.14, cy - r * 0.7), max(1, int(0.7 * s)))
        _hair_shine(surface, cx, cy, r, s, col)
    elif style == "bob":
        # Smooth cap, side-swept bangs, and curtains that hug the cheeks down to the jaw.
        _hair_cap(surface, col, cx, cy, r + int(2 * s), line)
        bang = [(cx - r * 0.95, line - r * 0.05), (cx - r * 0.2, cy - r * 1.02), (cx + r * 0.95, line - r * 0.1),
                (cx + r * 0.55, line + r * 0.02), (cx - r * 0.1, line + r * 0.14), (cx - r * 0.75, line + r * 0.2)]
        pygame.draw.polygon(surface, col, bang)
        pygame.draw.lines(surface, shadow, False, [(cx + r * 0.55, line + r * 0.02), (cx - r * 0.1, line + r * 0.14), (cx - r * 0.75, line + r * 0.2)], max(1, int(0.7 * s)))
        for side in (-1, 1):
            outer = cx + side * (r + 2.5 * s)
            inner = cx + side * r * 0.74
            curtain = [(cx + side * r * 0.78, line - r * 0.06), (outer, line + r * 0.05), (outer, cy + r * 0.52),
                       (cx + side * r * 0.9, cy + r * 0.66), (inner, cy + r * 0.5), (inner + side * r * 0.02, line + r * 0.3)]
            pygame.draw.polygon(surface, col, curtain)
            pygame.draw.line(surface, shadow, (inner, cy + r * 0.48), (inner + side * r * 0.02, line + r * 0.32), max(1, int(0.6 * s)))
        _hair_shine(surface, cx, cy, r, s, col)
    elif style == "long":
        _hair_cap(surface, col, cx, cy, r + int(2.5 * s), line)
        for side in (-1, 1):
            lock = pygame.Rect(0, 0, max(4, int(5.5 * s)), int(r * 1.0))
            lock.top = line - int(2 * s)
            lock.centerx = cx + side * (r - int(0.2 * s))
            pygame.draw.rect(surface, col, lock, border_radius=max(1, int(2 * s)))
    elif style == "curly":
        # Cap plus a row of round curls along the hairline, each with a little shading ring.
        _hair_cap(surface, col, cx, cy, r + int(2.5 * s), line)
        n = 6
        for k in range(n):
            fx = -0.78 + 1.56 * k / (n - 1)
            px = cx + fx * r
            py = line + r * 0.02 - (1 - fx * fx) * r * 0.06 + (0.1 * r if abs(fx) > 0.7 else 0)
            rr = r * 0.23
            pygame.draw.circle(surface, col, (px, py), rr)
            pygame.draw.arc(surface, shadow, (px - rr * 0.7, py - rr * 0.7, rr * 1.4, rr * 1.4), 3.6, 6.0, max(1, int(0.7 * s)))
        for k in range(4):
            px = cx + (-0.45 + 0.3 * k) * r
            py = cy - r * (0.82 + 0.06 * (k % 2))
            pygame.draw.arc(surface, shadow, (px - r * 0.14, py - r * 0.14, r * 0.28, r * 0.28), 3.4, 6.1, max(1, int(0.7 * s)))
    elif style == "afro":
        _hair_cap(surface, col, cx, cy, r + int(0.5 * s), cy - int(r * 0.7))
    elif style == "spiky":
        _hair_cap(surface, col, cx, cy, r + int(1 * s), line)
        for i in range(5):
            ang = math.pi * (1.2 + i / 4.0 * 0.6)
            bx = cx + math.cos(ang) * (r - int(0.5 * s))
            by = cy + math.sin(ang) * (r - int(0.5 * s))
            tx = cx + math.cos(ang) * (r + int(8 * s))
            ty = cy + math.sin(ang) * (r + int(8 * s))
            nx, ny = -math.sin(ang), math.cos(ang)
            w = 3.6 * s
            pygame.draw.polygon(surface, col, [(int(bx + nx * w), int(by + ny * w)), (int(tx), int(ty)), (int(bx - nx * w), int(by - ny * w))])
    elif style == "mohawk":
        ridge = pygame.Rect(cx - int(4 * s), cy - r - int(1 * s), max(4, int(8 * s)), int(r * 0.7))
        pygame.draw.ellipse(surface, col, ridge)
        for i in range(-2, 3):
            bx = cx + int(i * 3.0 * s)
            by = cy - r + int(2 * s) + abs(i) * int(0.8 * s)
            tip = by - int((12 - abs(i) * 2.2) * s)
            pygame.draw.polygon(surface, col, [(bx - int(2.4 * s), by), (bx, tip), (bx + int(2.4 * s), by)])


def _draw_extra_hair(surface, style, cx, fy, head_r, s, hair_color, hair_shadow, skin):
    """Hair styles added after the original set. fy is the face-centre y."""
    if style == "afro":
        for dx, dy, rr in [(-13, -6, 8), (-9, -13, 8), (-2, -16, 8), (6, -14, 8), (12, -8, 8), (15, -1, 6), (-15, -1, 6)]:
            pygame.draw.circle(surface, hair_color, (cx + int(dx * s), fy + int(dy * s)), max(2, int(rr * s)))
        pygame.draw.circle(surface, skin, (cx, fy + int(1 * s)), max(3, head_r - int(1 * s)))
        pygame.draw.ellipse(surface, hair_color, (cx - head_r + int(2 * s), fy - head_r, max(2, head_r * 2 - int(4 * s)), max(2, int(head_r * 0.7))))
    elif style == "mohawk":
        pygame.draw.ellipse(surface, hair_shadow, (cx - int(4 * s), fy - head_r - int(1 * s), max(2, int(8 * s)), max(2, int(head_r * 0.9))))
        for i in range(-2, 3):
            x = cx + int(i * 3.2 * s)
            tip = fy - head_r - int((11 - abs(i) * 2.2) * s)
            pygame.draw.polygon(surface, hair_color, [(x - int(2 * s), fy - head_r + int(3 * s)), (x, tip), (x + int(2 * s), fy - head_r + int(3 * s))])
    elif style == "bun":
        pygame.draw.circle(surface, hair_color, (cx, fy - head_r - int(3 * s)), max(3, int(6 * s)))
        pygame.draw.ellipse(surface, hair_color, (cx - head_r, fy - head_r - int(1 * s), head_r * 2, int(head_r * 1.15)))
        pygame.draw.ellipse(surface, skin, (cx - head_r + int(2 * s), fy - int(1 * s), max(2, head_r * 2 - int(4 * s)), max(2, head_r + int(5 * s))))


def _draw_extra_accessory(surface, acc, cx, fy, eye_dx, eye_y, head_r, s, outline):
    """Accessories added after the original set. fy is the face-centre y."""
    lw = max(1, int(1.2 * s))
    if acc == "shades":
        for ex in (cx - eye_dx, cx + eye_dx):
            pygame.draw.rect(surface, (20, 20, 24), (ex - int(4 * s), eye_y - int(2.5 * s), max(4, int(8 * s)), max(3, int(5 * s))), border_radius=max(1, int(2 * s)))
        pygame.draw.line(surface, (20, 20, 24), (cx - eye_dx + int(4 * s), eye_y - int(1 * s)), (cx + eye_dx - int(4 * s), eye_y - int(1 * s)), lw)
        pygame.draw.line(surface, (20, 20, 24), (cx - head_r, eye_y - int(1 * s)), (cx - eye_dx - int(4 * s), eye_y - int(1 * s)), lw)
        pygame.draw.line(surface, (20, 20, 24), (cx + head_r, eye_y - int(1 * s)), (cx + eye_dx + int(4 * s), eye_y - int(1 * s)), lw)
    elif acc == "headband":
        band = C("ORANGE")
        by = fy - int(head_r * 0.55)
        hw = int(math.sqrt(max(1.0, head_r ** 2 - (fy - by) ** 2))) + max(1, int(s))
        pygame.draw.rect(surface, band, (cx - hw, by, hw * 2, max(2, int(4 * s))), border_radius=max(1, int(2 * s)))
    elif acc == "crown":
        gold = C("GOLD")
        base = fy - head_r + int(1 * s)
        w = int(head_r * 1.5)
        pts = [(cx - w // 2, base), (cx - w // 2, base - int(8 * s)), (cx - w // 4, base - int(4 * s)), (cx, base - int(10 * s)),
               (cx + w // 4, base - int(4 * s)), (cx + w // 2, base - int(8 * s)), (cx + w // 2, base)]
        pygame.draw.polygon(surface, gold, pts)
        pygame.draw.polygon(surface, _avatar_rgb(gold, -50), pts, max(1, int(s)))
        pygame.draw.circle(surface, C("RED"), (cx, base - int(3 * s)), max(1, int(1.6 * s)))
    elif acc == "scarf":
        col = C("GREEN")
        ny = fy + int(9 * s)
        pygame.draw.rect(surface, col, (cx - int(10 * s), ny, max(6, int(20 * s)), max(3, int(6 * s))), border_radius=max(1, int(3 * s)))
        pygame.draw.rect(surface, _avatar_rgb(col, -30), (cx + int(3 * s), ny + int(4 * s), max(2, int(6 * s)), max(3, int(12 * s))), border_radius=max(1, int(2 * s)))
    elif acc == "monocle":
        gold = C("GOLD")
        ex = cx + eye_dx
        pygame.draw.circle(surface, gold, (ex, eye_y), max(3, int(5 * s)), max(1, int(1.3 * s)))
        pygame.draw.line(surface, gold, (ex + int(3 * s), eye_y + int(4 * s)), (ex + int(5 * s), eye_y + int(14 * s)), max(1, int(s)))


# The avatar is "printed" in fixed colors so it looks identical in light and dark
# mode. Theme colors (INK is near-white in dark mode) gave it white eyes and outlines.
AVATAR_INK = (26, 26, 26)
AVATAR_WHITE = (255, 255, 255)


def draw_character(surface, char, cx, cy, scale=1.0, mood=None, animate=False, now=None):
    """Draw the Ledger trader avatar with safe scaling, animation and all cosmetics."""
    if not isinstance(char, dict):
        img = font_medium_bold.render(str(char), True, C("INK"))
        surface.blit(img, img.get_rect(center=(int(cx), int(cy))))
        return

    now = time.time() if now is None else now
    s = max(0.35, float(scale))
    cx = int(round(cx))
    cy = int(round(cy))

    if mood is None:
        mood = avatar_anim["mood"] if animate else "neutral"

    blinking = bool(animate and avatar_anim["blinking"])
    talking = bool(animate and now < avatar_anim["talking_until"])

    # Gentle breathing/bobbing keeps the large avatar alive without making tiny icons jump.
    ground_y = cy
    arms_mode = ""
    if animate:
        cy += int(round(math.sin(now * 2.25) * min(2.2, 1.4 * s)))
        pdx, pdy, arms_mode = avatar_emote_pose(now, s)
        cx += int(round(pdx))
        cy += int(round(pdy))

    # Clamp saved/customization values so malformed old save files cannot crash rendering.
    skin = SKIN_TONES[int(char.get("skin", 0) or 0) % len(SKIN_TONES)]
    hair_style = HAIR_STYLES[int(char.get("hair_style", 0) or 0) % len(HAIR_STYLES)]
    hair_color = HAIR_COLORS[int(char.get("hair_color", 0) or 0) % len(HAIR_COLORS)]
    outfit_color = OUTFIT_COLORS[int(char.get("outfit", 0) or 0) % len(OUTFIT_COLORS)]
    accessory = ACCESSORIES[int(char.get("accessory", 0) or 0) % len(ACCESSORIES)]
    outfit_style = OUTFIT_STYLES[int(char.get("outfit_style", 0) or 0) % len(OUTFIT_STYLES)]

    ink = AVATAR_INK
    outline = _avatar_rgb(ink, 18)
    hair_shadow = _avatar_rgb(hair_color, -28)
    outfit_shadow = _avatar_rgb(outfit_color, -24)
    outfit_light = _avatar_rgb(outfit_color, 30)
    skin_shadow = _avatar_rgb(skin, -22)
    white = AVATAR_WHITE

    # Main proportions. Everything is derived from s so the same renderer works at
    # 0.62x header size, 0.8x speech-bubble size, 1.7x creation preview and 2.3x stage size.
    head_r = max(5, int(14 * s))
    body_w = max(12, int(36 * s))
    body_h = max(10, int(25 * s))
    body_y = cy + int(20 * s)

    # Soft ground shadow for the larger interactive avatar.
    if animate and s >= 1.0:
        sw = max(10, int(28 * s))
        sh = max(3, int(5 * s))
        shadow = HiSurface((sw * 2 + 6, sh * 2 + 6), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 55), shadow.get_rect())
        surface.blit(shadow, (cx - shadow.get_width() // 2,
                              ground_y + int(40 * s) - shadow.get_height() // 2))

    # Legs and shoes.
    if s >= 0.7:
        leg_y = body_y + int(body_h * 0.38)
        leg_w = max(3, int(6 * s))
        leg_h = max(4, int(12 * s))
        for side in (-1, 1):
            lx = cx + side * int(6 * s)
            leg = pygame.Rect(lx - leg_w // 2, leg_y, leg_w, leg_h)
            pygame.draw.rect(surface, outfit_shadow, leg, border_radius=max(1, int(2 * s)))
            shoe = pygame.Rect(lx - int(5 * s), leg.bottom - int(2 * s), max(5, int(10 * s)), max(3, int(4 * s)))
            pygame.draw.ellipse(surface, ink, shoe)

    # Torso/jacket with a subtle outline.
    body = pygame.Rect(0, 0, body_w, body_h)
    body.center = (cx, body_y)
    pygame.draw.rect(surface, outline, body.inflate(max(2, int(2 * s)), max(2, int(2 * s))),
                     border_radius=max(3, int(8 * s)))
    pygame.draw.rect(surface, outfit_color, body, border_radius=max(3, int(7 * s)))

    # Outfit style: jacket (default), hoodie, suit or tee.
    if outfit_style == "hoodie":
        pygame.draw.ellipse(surface, outfit_shadow, (cx - int(11 * s), cy + int(7 * s), max(6, int(22 * s)), max(4, int(11 * s))))
        pocket = pygame.Rect(cx - int(9 * s), body.bottom - int(9 * s), max(6, int(18 * s)), max(3, int(6 * s)))
        pygame.draw.rect(surface, outfit_shadow, pocket, border_radius=max(1, int(3 * s)))
        for dx in (-3, 3):
            pygame.draw.line(surface, AVATAR_WHITE, (cx + int(dx * s), body.y + int(2 * s)), (cx + int(dx * s), body.y + int(9 * s)), max(1, int(s)))
    elif outfit_style == "suit":
        shirt_w = max(6, int(body_w * 0.34))
        shirt = pygame.Rect(cx - shirt_w // 2, body.y + int(2 * s), shirt_w, max(5, int(body_h * 0.70)))
        pygame.draw.rect(surface, AVATAR_WHITE, shirt, border_radius=max(1, int(2 * s)))
        for side in (-1, 1):
            pygame.draw.polygon(surface, outfit_shadow, [
                (cx + side * shirt_w // 2, body.y + int(1 * s)),
                (cx + side * (shirt_w // 2 + int(6 * s)), body.y + int(1 * s)),
                (cx + side * int(1 * s), body.y + int(13 * s)),
            ])
    elif outfit_style == "tee":
        pygame.draw.arc(surface, skin_shadow, (cx - int(6 * s), body.y - int(4 * s), max(6, int(12 * s)), max(4, int(9 * s))), math.pi, math.pi * 2, max(1, int(1.5 * s)))
        pygame.draw.rect(surface, outfit_light, (body.x + max(2, int(4 * s)), body.bottom - int(6 * s), max(3, body_w - max(4, int(8 * s))), max(1, int(2 * s))), border_radius=1)
    else:
        highlight = pygame.Rect(body.x + max(2, int(4 * s)), body.y + max(2, int(3 * s)),
                                max(2, int(4 * s)), max(3, int(body_h * 0.60)))
        pygame.draw.rect(surface, outfit_light, highlight, border_radius=max(1, int(2 * s)))
        shirt_w = max(5, int(body_w * 0.28))
        shirt = pygame.Rect(cx - shirt_w // 2, body.y + int(3 * s), shirt_w, max(5, int(body_h * 0.60)))
        pygame.draw.rect(surface, AVATAR_WHITE, shirt, border_radius=max(1, int(2 * s)))

    # Neck.
    neck_w = max(4, int(8 * s))
    neck_h = max(5, int(8 * s))
    neck = pygame.Rect(cx - neck_w // 2, cy + int(8 * s), neck_w, neck_h)
    pygame.draw.rect(surface, skin_shadow, neck, border_radius=max(1, int(2 * s)))
    pygame.draw.rect(surface, skin, neck.inflate(-max(1, int(1 * s)), 0), border_radius=max(1, int(2 * s)))

    # Arms with a tiny idle swing.
    swing = math.sin(now * 3.0) * min(2.0, 1.2 * s) if animate else 0.0
    arm_w = max(4, int(7 * s))
    arm_h = max(7, int(17 * s))
    for side in (-1, 1):
        ax = cx + side * (body_w // 2 + max(2, int(2 * s)))
        ay = int(body_y - int(4 * s) + swing * side)
        hand_up = False
        if arms_mode == "up":
            ay = int(body_y - int(20 * s) + math.sin(now * 16 + side) * 2 * s)
            hand_up = True
        elif arms_mode == "wave" and side == 1:
            ay = int(body_y - int(20 * s))
            ax += int(math.sin(now * 12) * 3.5 * s)
            hand_up = True
        elif arms_mode == "dance":
            ay = int(body_y - int(8 * s) + math.sin(now * 9 + (0 if side < 0 else math.pi)) * 9 * s)
        elif arms_mode == "out":
            ax += side * int(5 * s)
            ay = int(body_y - int(2 * s))
        arm = pygame.Rect(ax - arm_w // 2, ay, arm_w, arm_h)
        pygame.draw.rect(surface, outline, arm.inflate(max(1, int(1.5 * s)), 0),
                         border_radius=max(2, int(3 * s)))
        pygame.draw.rect(surface, outfit_color, arm, border_radius=max(2, int(3 * s)))
        hand_y = arm.top - max(1, int(1 * s)) if hand_up else arm.bottom + max(1, int(1 * s))
        pygame.draw.circle(surface, skin, (ax, hand_y), max(2, int(2.8 * s)))

    draw_hair_back(surface, hair_style, cx, cy, head_r, s, hair_color, hair_shadow, accessory)

    # Head outline and face.
    pygame.draw.circle(surface, outline, (cx, cy), head_r + max(1, int(1.2 * s)))
    pygame.draw.circle(surface, skin, (cx, cy), head_r)

    # Ears.
    ear_r = max(2, int(3 * s))
    for ex in (cx - head_r + max(1, int(s)), cx + head_r - max(1, int(s))):
        pygame.draw.circle(surface, skin, (ex, cy + int(s)), ear_r)
        pygame.draw.circle(surface, skin_shadow, (ex, cy + int(s)), max(1, ear_r // 2), 1)

    draw_hair_front(surface, hair_style, cx, cy, head_r, s, hair_color, hair_shadow, accessory, skin)

    # Eyes and brows.
    eye_dx = max(2, int(5 * s))
    eye_y = cy - int(1 * s)
    look_x = look_y = 0
    if animate:
        mx, my = pygame.mouse.get_pos()
        look_x = int(round(max(-1.0, min(1.0, (mx - cx) / 170.0)) * 1.7 * s))
        look_y = int(round(max(-1.0, min(1.0, (my - cy) / 220.0)) * 1.2 * s))
    eye_r = max(1, int(2.0 * s))
    eye_white = (250, 250, 250)

    if blinking:
        for ex in (cx - eye_dx, cx + eye_dx):
            pygame.draw.line(surface, ink, (ex - int(2 * s), eye_y),
                             (ex + int(2 * s), eye_y), max(1, int(1.3 * s)))
    elif mood in ("happy", "excited"):
        for ex in (cx - eye_dx, cx + eye_dx):
            rr = pygame.Rect(ex - int(3 * s), eye_y - int(2 * s), max(2, int(6 * s)), max(2, int(5 * s)))
            pygame.draw.arc(surface, ink, rr, math.pi * 0.08, math.pi * 0.92, max(1, int(1.4 * s)))
    elif mood == "panic":
        for ex in (cx - eye_dx, cx + eye_dx):
            pygame.draw.circle(surface, eye_white, (ex, eye_y), max(2, int(3 * s)))
            pygame.draw.circle(surface, ink, (ex + look_x // 2, eye_y + look_y // 2), max(1, int(1.6 * s)))
    else:
        for ex in (cx - eye_dx, cx + eye_dx):
            pygame.draw.circle(surface, ink, (ex + look_x, eye_y + look_y), eye_r)
            if animate and s >= 0.55:
                pygame.draw.circle(surface, eye_white,
                                   (ex + look_x + max(1, int(s)), eye_y + look_y - max(1, int(s))),
                                   max(1, int(0.7 * s)))

    brow_y = eye_y - int(5 * s)
    brow_w = max(2, int(3 * s))
    brow_t = max(1, int(1.2 * s))

    if mood == "sad":
        for side in (-1, 1):
            ex = cx + side * eye_dx
            pygame.draw.line(surface, ink,
                             (ex - brow_w, brow_y + int(2 * s)),
                             (ex + brow_w, brow_y), brow_t)
    elif mood == "panic":
        pygame.draw.line(surface, ink, (cx - eye_dx - brow_w, brow_y - int(2 * s)),
                         (cx - eye_dx + brow_w, brow_y), brow_t)
        pygame.draw.line(surface, ink, (cx + eye_dx - brow_w, brow_y),
                         (cx + eye_dx + brow_w, brow_y - int(2 * s)), brow_t)
    elif mood in ("happy", "excited", "focused"):
        pygame.draw.line(surface, ink, (cx - eye_dx - brow_w, brow_y),
                         (cx - eye_dx + brow_w, brow_y - int(s)), brow_t)
        pygame.draw.line(surface, ink, (cx + eye_dx - brow_w, brow_y - int(s)),
                         (cx + eye_dx + brow_w, brow_y), brow_t)
    else:
        pygame.draw.line(surface, ink, (cx - eye_dx - brow_w, brow_y),
                         (cx - eye_dx + brow_w, brow_y), brow_t)
        pygame.draw.line(surface, ink, (cx + eye_dx - brow_w, brow_y),
                         (cx + eye_dx + brow_w, brow_y), brow_t)

    # Nose gives the face more dimension without making the small avatar noisy.
    nose_x = cx
    nose_y = cy + int(1.5 * s)
    pygame.draw.line(surface, skin_shadow,
                     (nose_x, nose_y),
                     (nose_x - max(1, int(1.5 * s)), nose_y + max(1, int(2 * s))),
                     max(1, int(s)))

    # Mouth changes with mood and talking state.
    mouth_y = cy + int(4 * s)
    mouth_w = max(4, int(6 * s))
    mouth_h = max(3, int(5 * s))

    if talking:
        open_h = max(3, int((3 + 2 * abs(math.sin(now * 14))) * s))
        pygame.draw.ellipse(surface, ink,
                            (cx - mouth_w // 2, mouth_y - int(s), mouth_w, open_h + int(2 * s)))
        if s >= 1.0:
            pygame.draw.ellipse(surface, eye_white,
                                (cx - int(2 * s), mouth_y, max(2, int(4 * s)), max(1, int(1 * s))))
    elif mood == "excited":
        rr = pygame.Rect(cx - int(7 * s), mouth_y - int(3 * s), int(14 * s), int(9 * s))
        pygame.draw.arc(surface, ink, rr, math.pi * 1.08, math.pi * 1.92, max(1, int(1.7 * s)))
    elif mood == "happy":
        rr = pygame.Rect(cx - int(6 * s), mouth_y - int(2 * s), int(12 * s), int(7 * s))
        pygame.draw.arc(surface, ink, rr, math.pi * 1.12, math.pi * 1.88, max(1, int(1.5 * s)))
    elif mood == "sad":
        rr = pygame.Rect(cx - int(6 * s), mouth_y - int(3 * s), int(12 * s), int(7 * s))
        pygame.draw.arc(surface, ink, rr, math.pi * 0.15, math.pi * 0.85, max(1, int(1.5 * s)))
    elif mood == "panic":
        pygame.draw.ellipse(surface, ink,
                            (cx - int(3 * s), mouth_y - int(s), max(3, int(6 * s)), max(4, int(6 * s))))
    else:
        rr = pygame.Rect(cx - int(5 * s), mouth_y - int(s), int(10 * s), int(6 * s))
        pygame.draw.arc(surface, ink, rr, math.pi * 1.18, math.pi * 1.82, max(1, int(1.3 * s)))

    # Accessories are layered last so they sit naturally on the face/hair.
    if accessory == "glasses":
        lens_r = max(3, int(4 * s))
        for ex in (cx - eye_dx, cx + eye_dx):
            pygame.draw.circle(surface, outline, (ex, eye_y), lens_r, max(1, int(1.3 * s)))
        pygame.draw.line(surface, outline,
                         (cx - eye_dx + lens_r, eye_y),
                         (cx + eye_dx - lens_r, eye_y), max(1, int(1.3 * s)))
        pygame.draw.line(surface, outline,
                         (cx - head_r, eye_y),
                         (cx - eye_dx - lens_r + int(1 * s), eye_y), max(1, int(s)))
        pygame.draw.line(surface, outline,
                         (cx + eye_dx + lens_r - int(1 * s), eye_y),
                         (cx + head_r, eye_y), max(1, int(s)))

    elif accessory == "cap":
        cap_color = C("RED")
        _hair_cap(surface, cap_color, cx, cy, head_r + int(2 * s), cy - int(head_r * 0.45))
        brim = pygame.Rect(cx - int(1 * s), cy - int(head_r * 0.45) - int(2 * s), int(head_r * 1.3), max(3, int(4 * s)))
        pygame.draw.ellipse(surface, _avatar_rgb(cap_color, -25), brim)

    elif accessory == "tie":
        tie_color = C("RED")
        pygame.draw.polygon(surface, tie_color, [
            (cx, cy + int(15 * s)),
            (cx - int(3 * s), cy + int(19 * s)),
            (cx, cy + int(28 * s)),
            (cx + int(3 * s), cy + int(19 * s)),
        ])
        pygame.draw.circle(surface, _avatar_rgb(tie_color, -30),
                           (cx, cy + int(19 * s)), max(1, int(2 * s)))

    elif accessory == "bow":
        bow_color = C("PURPLE")
        by = cy + int(17 * s)
        pygame.draw.polygon(surface, bow_color, [
            (cx, by),
            (cx - int(8 * s), by - int(4 * s)),
            (cx - int(7 * s), by + int(4 * s)),
        ])
        pygame.draw.polygon(surface, bow_color, [
            (cx, by),
            (cx + int(8 * s), by - int(4 * s)),
            (cx + int(7 * s), by + int(4 * s)),
        ])
        pygame.draw.circle(surface, C("GOLD"), (cx, by), max(2, int(2.5 * s)))

    if accessory in ("shades", "headband", "crown", "scarf", "monocle"):
        _draw_extra_accessory(surface, accessory, cx, cy, eye_dx, eye_y, head_r, s, outline)

    # Large avatars get a subtle trader headset and contextual reaction effects.
    if animate and s >= 1.1:
        draw_avatar_props(surface, cx, cy, head_r, s, mood, now)
def draw_avatar_props(surface, cx, cy, head_r, s, mood, now):
    """Trading-flavored props for the enlargened player avatar."""
    ink = AVATAR_INK
    if mood in ("excited", "happy"):
        # Trading "halo": a candlestick, a dollar bill and a rising arrow orbit the head.
        green, dark_green, light = (34, 170, 90), (20, 110, 60), (170, 235, 190)
        for i in range(3):
            ang = now * 2.2 + i * math.tau / 3
            px = cx + (head_r + 9 * s) * math.cos(ang)
            py = cy - 9 * s + (head_r * 0.45 + 3 * s) * math.sin(ang)
            k = 0.85 + 0.15 * math.sin(ang)  # a touch smaller at the back of the orbit
            if i == 0:  # candlestick
                pygame.draw.line(surface, dark_green, (px, py - 5 * s * k), (px, py + 5 * s * k), max(1, int(0.9 * s)))
                pygame.draw.rect(surface, green, (px - 1.7 * s * k, py - 3 * s * k, 3.4 * s * k, 6 * s * k), border_radius=max(1, int(0.6 * s)))
            elif i == 1:  # dollar bill
                bill = pygame.Rect(0, 0, 9 * s * k, 5 * s * k)
                bill.center = (px, py)
                pygame.draw.rect(surface, green, bill, border_radius=max(1, int(0.8 * s)))
                pygame.draw.rect(surface, light, bill.inflate(-2 * s * k, -2 * s * k), max(1, int(0.5 * s)), border_radius=max(1, int(0.6 * s)))
                pygame.draw.circle(surface, light, bill.center, max(1, 1.1 * s * k))
            else:  # rising arrow
                pygame.draw.lines(surface, green, False, [(px - 4 * s * k, py + 3 * s * k), (px - 1 * s * k, py), (px + 1 * s * k, py + 1.5 * s * k),
                                                          (px + 4 * s * k, py - 2.5 * s * k)], max(1, int(1.2 * s)))
                pygame.draw.polygon(surface, green, [(px + 5 * s * k, py - 4 * s * k), (px + 5 * s * k, py - 0.5 * s * k), (px + 1.5 * s * k, py - 4 * s * k)])

    if mood == "panic":
        dx = cx + int(head_r * 0.85)
        dy = cy - int(head_r + int(2 * s))
        drop = (90, 170, 240)
        pygame.draw.polygon(surface, drop, [
            (dx, dy), (dx - int(2 * s), dy + int(5 * s)), (dx + int(2 * s), dy + int(5 * s)),
        ])
        pygame.draw.circle(surface, drop, (dx, dy + int(5 * s)), max(1, int(2 * s)))


def draw_avatar_icon(surface, char, center, size=44, selected=False, dark=False):
    """Crisp compact avatar portrait for headers, rank rows, news, and other small UI.
    Uses the same saved cosmetics as the full avatar, but intentionally removes
    animation/headset/body details that become noisy or overlap at tiny sizes.
    """
    if not isinstance(char, dict):
        char = dict(DEFAULT_CHARACTER)
    cx, cy = int(center[0]), int(center[1])
    size = max(28, int(size))
    r = size // 2
    bg = C("PURPLE_BG") if not dark else C("PANEL_BG")
    ring = C("PURPLE") if selected else C("BORDER")
    pygame.draw.circle(surface, ring, (cx, cy), r + 2)
    pygame.draw.circle(surface, bg, (cx, cy), r)

    # A stable portrait scale means the same face looks consistent everywhere.
    s = max(0.62, min(1.05, size / 52.0))
    skin = SKIN_TONES[int(char.get("skin", 0) or 0) % len(SKIN_TONES)]
    hair_style = HAIR_STYLES[int(char.get("hair_style", 0) or 0) % len(HAIR_STYLES)]
    hair_color = HAIR_COLORS[int(char.get("hair_color", 0) or 0) % len(HAIR_COLORS)]
    accessory = ACCESSORIES[int(char.get("accessory", 0) or 0) % len(ACCESSORIES)]
    ink = AVATAR_INK
    outline = _avatar_rgb(ink, 18)
    skin_shadow = _avatar_rgb(skin, -22)

    head_r = max(8, int(15 * s))
    face_y = cy - int(1 * s)
    # shoulders / shirt, kept inside the portrait circle
    shirt = pygame.Rect(cx - int(15*s), cy + int(10*s), int(30*s), int(15*s))
    outfit_color = OUTFIT_COLORS[int(char.get("outfit", 0) or 0) % len(OUTFIT_COLORS)]
    pygame.draw.rect(surface, outline, shirt.inflate(max(2, int(1.5*s)), max(2, int(1.5*s))), border_radius=max(4, int(6*s)))
    pygame.draw.rect(surface, outfit_color, shirt, border_radius=max(4, int(6*s)))
    _ostyle = OUTFIT_STYLES[int(char.get("outfit_style", 0) or 0) % len(OUTFIT_STYLES)]
    if _ostyle == "hoodie":
        pygame.draw.rect(surface, _avatar_rgb(outfit_color, -24), pygame.Rect(cx-int(7*s), shirt.y+int(7*s), int(14*s), int(6*s)), border_radius=3)
    elif _ostyle == "tee":
        pygame.draw.arc(surface, _avatar_rgb(skin, -22), pygame.Rect(cx-int(5*s), shirt.y-int(3*s), int(10*s), int(8*s)), math.pi, math.pi*2, max(1, int(s)))
    else:
        pygame.draw.rect(surface, AVATAR_WHITE, pygame.Rect(cx-int(4*s), shirt.y+int(2*s), int(8*s), int(10*s)), border_radius=2)
        if _ostyle == "suit":
            for _side in (-1, 1):
                pygame.draw.polygon(surface, _avatar_rgb(outfit_color, -24), [(cx+_side*int(4*s), shirt.y+int(1*s)), (cx+_side*int(9*s), shirt.y+int(1*s)), (cx+_side*int(1*s), shirt.y+int(10*s))])

    # neck and head
    neck=pygame.Rect(cx-int(4*s), cy+int(6*s), int(8*s), int(8*s))
    pygame.draw.rect(surface, skin_shadow, neck, border_radius=2)
    draw_hair_back(surface, hair_style, cx, face_y, head_r, s, hair_color, _avatar_rgb(hair_color, -28), accessory)
    pygame.draw.circle(surface, outline, (cx, face_y), head_r+1)
    pygame.draw.circle(surface, skin, (cx, face_y), head_r)

    draw_hair_front(surface, hair_style, cx, face_y, head_r, s, hair_color, _avatar_rgb(hair_color, -28), accessory, skin)

    # clean expressive face
    eye_y=face_y-int(1*s); eye_dx=max(3,int(5*s)); eye_r=max(1,int(1.35*s))
    for ex in (cx-eye_dx,cx+eye_dx):
        pygame.draw.circle(surface, ink, (ex,eye_y), eye_r)
    brow_y=eye_y-int(5*s)
    pygame.draw.line(surface,ink,(cx-eye_dx-int(2*s),brow_y),(cx-eye_dx+int(2*s),brow_y),max(1,int(s)))
    pygame.draw.line(surface,ink,(cx+eye_dx-int(2*s),brow_y),(cx+eye_dx+int(2*s),brow_y),max(1,int(s)))
    pygame.draw.line(surface,skin_shadow,(cx,face_y+int(1*s)),(cx-int(s),face_y+int(3*s)),max(1,int(s)))
    pygame.draw.arc(surface,ink,pygame.Rect(cx-int(5*s),face_y+int(2*s),int(10*s),int(6*s)),math.pi*1.15,math.pi*1.85,max(1,int(s)))

    if accessory == "glasses":
        lr=max(4,int(4.5*s))
        for ex in (cx-eye_dx,cx+eye_dx):
            pygame.draw.circle(surface,outline,(ex,eye_y),lr,max(1,int(s)))
        pygame.draw.line(surface,outline,(cx-eye_dx+lr,eye_y),(cx+eye_dx-lr,eye_y),max(1,int(s)))
    elif accessory == "cap":
        cap=C("RED")
        _hair_cap(surface, cap, cx, face_y, head_r+int(2*s), face_y-int(head_r*0.45))
        pygame.draw.ellipse(surface,_avatar_rgb(cap,-25),(cx-int(1*s),face_y-int(head_r*0.45)-int(2*s),int(head_r*1.3),max(3,int(4*s))))
    elif accessory == "bow":
        bow=C("PURPLE"); by=cy+int(15*s)
        pygame.draw.polygon(surface,bow,[(cx,by),(cx-int(7*s),by-int(4*s)),(cx-int(7*s),by+int(4*s))])
        pygame.draw.polygon(surface,bow,[(cx,by),(cx+int(7*s),by-int(4*s)),(cx+int(7*s),by+int(4*s))])
        pygame.draw.circle(surface,C("GOLD"),(cx,by),max(2,int(2*s)))
    elif accessory == "tie":
        tie=C("RED")
        pygame.draw.polygon(surface,tie,[(cx,cy+int(14*s)),(cx-int(3*s),cy+int(18*s)),(cx,cy+int(24*s)),(cx+int(3*s),cy+int(18*s))])
    elif accessory in ("shades", "headband", "crown", "scarf", "monocle"):
        _draw_extra_accessory(surface, accessory, cx, face_y, eye_dx, eye_y, head_r, s, outline)


def draw_avatar_stage(surface, rect):
    """Big, animated, interactive avatar panel (used on the Portfolio tab)."""
    global avatar_stage_rect
    avatar_stage_rect = rect
    now = time.time()
    draw_rounded_rect(surface, rect, C("PANEL_BG"), radius=16, border_color=C("BORDER"), border_width=1)
    cx = rect.x + 74
    cy = rect.y + 66
    if avatar_anim["pulse"] > 0:
        rad = int(40 + 22 * (1 - avatar_anim["pulse"]))
        ring = HiSurface((rad * 2 + 8, rad * 2 + 8), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*C("PURPLE"), int(90 * avatar_anim["pulse"])), (rad + 4, rad + 4), rad, 3)
        surface.blit(ring, (cx - rad - 4, cy - rad - 4))
    prev_clip = surface.get_clip()
    # Stay inside both the card and the scrolling content area, so the avatar
    # can't float over the header or tab bar when Portfolio is scrolled.
    surface.set_clip(prev_clip.clip(rect.inflate(-2, -2)))
    draw_character(surface, state.avatar, cx, cy, scale=1.9, animate=True, now=now)
    surface.set_clip(prev_clip)

    rx = rect.x + 150
    bar_w = rect.w - 190
    draw_text(surface, avatar_display_name(), font_medium_bold, C("INK"), rx, rect.y + 22, max_width=bar_w)
    persona_name = PERSONALITIES[int(state.avatar.get("persona", 0)) % len(PERSONALITIES)]["name"]
    chip = pygame.Rect(rx, rect.y + 48, 84, 20)
    draw_rounded_rect(surface, chip, C("PURPLE_BG"), radius=10, border_color=C("PURPLE"), border_width=1)
    draw_text(surface, avatar_anim["mood"].capitalize(), font_tiny, C("PURPLE"), chip.centerx, chip.y + 4, align="center")
    draw_text(surface, persona_name, font_tiny, C("GRAY"), chip.right + 8, chip.y + 4)
    req = max(1, state.level * 100)
    xp_pct = min(1.0, state.xp / req)
    pygame.draw.rect(surface, C("CARD"), (rx, rect.y + 80, bar_w, 8), border_radius=4)
    pygame.draw.rect(surface, C("PURPLE"), (rx, rect.y + 80, int(bar_w * xp_pct), 8), border_radius=4)
    draw_text(surface, f"Lv.{state.level}   {state.xp}/{req} XP", font_tiny, C("GRAY"), rx, rect.y + 92)
    if now < avatar_anim["speech_until"]:
        for i, line in enumerate(wrap_text(avatar_anim["speech"], font_small, bar_w)[:2]):
            draw_text(surface, line, font_small, C("INK"), rx, rect.y + 114 + i * 16)
    else:
        draw_text(surface, "Tap your trader for a tip", font_tiny, C("LIGHT_GRAY"), rx, rect.y + 118)


def draw_avatar_speech_bubble(surface):
    """Your trader pops up above the tab bar with a chat bubble (not on Portfolio)."""
    now = time.time()
    if now >= avatar_anim["speech_until"] or state.tab == "portfolio" or tour["active"]:
        return
    start = avatar_anim.get("speech_start", avatar_anim["speech_until"] - 3.2)
    age = now - start
    left = avatar_anim["speech_until"] - now
    appear = ease_out_cubic(age / 0.3)
    if left < 0.25:
        appear = min(appear, left / 0.25)
    lift = int(16 * (1 - appear))
    text_w = WIDTH - 96 - 20 - 28
    lines = wrap_text(avatar_anim["speech"], font_small, text_w)[:3]
    bh = 32 + len(lines) * 18
    bottom = CONTENT_BOTTOM - 12 + lift
    # Avatar badge sits beside the bubble, never inside it.
    badge = pygame.Rect(14, bottom - 58, 58, 58)
    bubble = pygame.Rect(badge.right + 14, bottom - bh, WIDTH - badge.right - 14 - 16, bh)
    layer_rect = pygame.Rect(0, bubble.y - 8, WIDTH, bottom - bubble.y + 16)
    layer = HiSurface(layer_rect.size, pygame.SRCALPHA)
    lb = badge.move(0, -layer_rect.y)
    bb = bubble.move(0, -layer_rect.y)
    img, pad = soft_shadow(bb.w, bb.h, 16, 6, 60)
    layer.blit(img, (bb.x - pad, bb.y - pad + 3))
    pygame.draw.rect(layer, (*C("CARD"), 255), bb, border_radius=16)
    pygame.draw.rect(layer, (*C("PURPLE"), 255), bb, 2, border_radius=16)
    tail_y = min(bb.bottom - 16, lb.centery)
    pygame.draw.polygon(layer, (*C("PURPLE"), 255), [(bb.x + 1, tail_y - 9), (bb.x - 9, tail_y), (bb.x + 1, tail_y + 9)])
    pygame.draw.polygon(layer, (*C("CARD"), 255), [(bb.x + 3, tail_y - 6), (bb.x - 5, tail_y), (bb.x + 3, tail_y + 6)])
    pygame.draw.circle(layer, (*C("PURPLE"), 255), lb.center, 29)
    pygame.draw.circle(layer, (*C("PURPLE_BG"), 255), lb.center, 26)
    layer.set_alpha(int(255 * appear))
    surface.blit(layer, layer_rect.topleft)
    if appear > 0.6:
        draw_avatar_icon(surface, state.avatar, badge.center, size=48)
        draw_avatar_frame(surface, badge.center, 27, equipped("frame")["id"])
        draw_text(surface, avatar_display_name(), font_tiny, C("PURPLE"), bubble.x + 14, bubble.y + 9, max_width=bubble.w - 28)
        ty = bubble.y + 25
        for line in lines:
            draw_text(surface, line, font_small, C("INK"), bubble.x + 14, ty)
            ty += 18


def draw_signin_hero(surface, now):
    """Slow, faint market line drifting behind the logo."""
    data = [100 + 6 * math.sin(i * 0.33 + now * 0.7) + 4 * math.sin(i * 0.11 - now * 0.35) + i * 0.45
            for i in range(48)]
    tint = mix_color(C("GREEN"), C("BG"), 0.72)
    draw_mini_chart(surface, data, True, 0, 34, WIDTH, 120, color=tint, baseline=False)


_tape_quotes = {}


def draw_ticker_tape(surface, y, now):
    """Scrolling strip of live-looking quotes along the bottom of the sign-in screen."""
    strip = pygame.Rect(0, y, WIDTH, 32)
    pygame.draw.rect(surface, C("PANEL_BG"), strip)
    pygame.draw.line(surface, C("BORDER"), strip.topleft, strip.topright, 1)
    pygame.draw.line(surface, C("BORDER"), strip.bottomleft, strip.bottomright, 1)
    # The real market only runs after you log in, so the sign-in tape keeps its own
    # gentle mini-market (otherwise every quote would sit at +0.00%).
    if not _tape_quotes or now - _tape_quotes.get("_t", 0) >= 1.0:
        _tape_quotes["_t"] = now
        for s in STOCKS[:16]:
            q = _tape_quotes.get(s["ticker"])
            if q is None:
                base = float(s["price"])
                q = _tape_quotes[s["ticker"]] = [base, base * (1 + random.uniform(-0.025, 0.025))]
            q[1] = max(0.5, q[1] * (1 + random.gauss(0.0, 0.0018)))
    items = []
    for s in STOCKS[:16]:
        base, px = _tape_quotes[s["ticker"]]
        shown = tween(("tape", s["ticker"]), px, 4.0)
        items.append((s["ticker"], fmt_money(shown), (shown - base) / base * 100))
    widths = [font_tiny.size(t)[0] + font_tiny.size(p)[0] + font_tiny.size(f"{c:+.2f}%")[0] + 40 for t, p, c in items]
    total = sum(widths)
    if total <= 0:
        return
    prev_clip = surface.get_clip()
    surface.set_clip(strip)
    x = -((now * 32) % total)
    while x < WIDTH:
        for (ticker, price, pct), w in zip(items, widths):
            if x + w > 0 and x < WIDTH:
                tx = x + 14
                tx += draw_text(surface, ticker, font_tiny, C("INK"), tx, y + 9, max_width=400).w + 6
                tx += draw_text(surface, price, font_tiny, C("GRAY"), tx, y + 9, max_width=400).w + 6
                draw_text(surface, f"{pct:+.2f}%", font_tiny, C("GREEN") if pct >= 0 else C("RED"), tx, y + 9, max_width=400)
            x += w
    surface.set_clip(prev_clip)


def draw_input_field(surface, rect, text, placeholder, active):
    draw_rounded_rect(surface, rect, C("CARD"), radius=12,
                      border_color=C("PURPLE") if active else C("BORDER"),
                      border_width=2 if active else 1)
    tr = draw_text(surface, text or placeholder, font_body_bold,
                   C("INK") if text else C("LIGHT_GRAY"), rect.x + 14, rect.y + 13)
    if active and int(time.time() * 2) % 2 == 0:
        cx = tr.right + 2 if text else rect.x + 14
        pygame.draw.line(surface, C("PURPLE"), (cx, rect.y + 12), (cx, rect.bottom - 12), 2)


GOOGLE_READY = google_auth.is_configured()


def draw_signin_screen(surface):
    global signin_user_rect, signin_pw_rect, signin_login_btn, signin_create_btn, signin_guest_btn, signin_google_btn, signin_google_up_btn, signin_forgot_rect
    now = time.time()
    draw_app_background(surface)
    draw_signin_hero(surface, now)
    draw_logo_mark(surface, WIDTH // 2, 56, 52)
    draw_text(surface, "Ledger", font_large, C("INK"), WIDTH // 2, 88, align="center")
    draw_text(surface, "Sign in to your trader account", font_body, C("GRAY"), WIDTH // 2, 132, align="center")

    draw_text(surface, "Username", font_small_bold, C("GRAY"), 40, 170)
    signin_user_rect = pygame.Rect(40, 190, WIDTH - 80, 46)
    draw_input_field(surface, signin_user_rect, state.login_username_input, "Enter username",
                     state.auth_active_field == "username")

    draw_text(surface, "Password", font_small_bold, C("GRAY"), 40, 250)
    fr = draw_text(surface, "Forgot password?", font_small_bold, C("PURPLE"), WIDTH - 40, 250, align="right")
    signin_forgot_rect = fr.inflate(12, 10)
    signin_pw_rect = pygame.Rect(40, 270, WIDTH - 80, 46)
    draw_input_field(surface, signin_pw_rect, "•" * len(state.login_password_input), "Enter password",
                     state.auth_active_field == "password")

    signin_login_btn = pygame.Rect(40, 336, WIDTH - 80, 50)
    draw_button(surface, signin_login_btn, "Log In", C("INK"), C("CARD"), radius=14)

    # Google buttons only appear when a Google OAuth client is bundled (public builds ship without one).
    lift = 0 if GOOGLE_READY else 72
    signin_google_btn = signin_google_up_btn = None
    if GOOGLE_READY:
        div_y = 408
        pygame.draw.line(surface, C("BORDER"), (40, div_y), (WIDTH // 2 - 22, div_y), 1)
        pygame.draw.line(surface, C("BORDER"), (WIDTH // 2 + 22, div_y), (WIDTH - 40, div_y), 1)
        draw_text(surface, "or", font_small, C("LIGHT_GRAY"), WIDTH // 2, div_y - 10, align="center")

        waiting = google_auth.result["status"] == "waiting"
        half = (WIDTH - 80 - 10) // 2
        signin_google_btn = pygame.Rect(40, 428, half, 48)
        signin_google_up_btn = pygame.Rect(40 + half + 10, 428, half, 48)
        for rect, label in ((signin_google_btn, "Google Log In"), (signin_google_up_btn, "Google Sign Up")):
            draw_button(surface, rect, "", C("CARD"), C("INK"), radius=14)
            pygame.draw.rect(surface, C("BORDER"), rect, 1, border_radius=14)
            gx, gy = rect.x + 22, rect.centery
            for i, col in enumerate(((66, 133, 244), (52, 168, 83), (251, 188, 5), (234, 67, 53))):
                pygame.draw.arc(surface, col, pygame.Rect(gx - 8, gy - 8, 16, 16), i * math.pi / 2 + 0.3, (i + 1) * math.pi / 2 + 0.3, 3)
            draw_text(surface, "Waiting..." if waiting else label, font_small_bold, C("INK"), rect.centerx + 10, rect.y + 15, align="center")

    # Account creation lives in a light text link so the screen isn't a wall of buttons.
    lead = "New here? "
    link = "Create an account"
    lw, ww = font_body.size(lead)[0], font_body_bold.size(link)[0]
    lx = WIDTH // 2 - (lw + ww) // 2
    signin_create_btn = pygame.Rect(lx - 6, 492 - lift, lw + ww + 12, 30)
    hover = signin_create_btn.collidepoint(pygame.mouse.get_pos())
    draw_text(surface, lead, font_body, C("GRAY"), lx, 497 - lift)
    lr = draw_text(surface, link, font_body_bold, C("PURPLE"), lx + lw, 497 - lift)
    if hover:
        pygame.draw.line(surface, C("PURPLE"), (lr.x, lr.bottom), (lr.right, lr.bottom), 1)

    signin_guest_btn = pygame.Rect(WIDTH // 2 - 100, 530 - lift, 200, 30)
    draw_text(surface, "Continue as Guest", font_small_bold, C("GRAY"), WIDTH // 2, signin_guest_btn.y + 6, align="center")

    if state.auth_message or google_auth.result["message"]:
        draw_text(surface, state.auth_message or google_auth.result["message"], font_tiny, C("RED"), WIDTH // 2, 574 - lift, align="center", max_width=WIDTH - 60)
    draw_ticker_tape(surface, HEIGHT - 78, now)
    draw_text(surface, "Your account is saved only on this computer.",
              font_tiny, C("LIGHT_GRAY"), WIDTH // 2, HEIGHT - 30, align="center")



def finish_google_sign_in():
    """Poll the background Google sign-in. Existing linked accounts log straight in;
    new Google players pick their own username and password before making a trader."""
    res = google_auth.take_result()
    if not res:
        return
    if res["status"] != "done" or not res["sub"]:
        state.auth_message = res["message"] or "Google sign-in failed."
        return
    accounts = _read_accounts().get("accounts", {})
    linked = next((k for k, r in accounts.items() if isinstance(r, dict) and r.get("google_sub") == res["sub"]), None)
    if linked:
        login_account(accounts[linked].get("username", linked), "", trusted=True)
        return
    # Accounts made by older versions used an automatic name and a Google password.
    legacy = f"{res['name'][:14]}#{res['sub'][-4:]}"
    if _normalize_account_key(legacy) in accounts:
        login_account(legacy, "google:" + res["sub"])
        return
    open_account_setup(google={"sub": res["sub"], "name": res["name"]})


# ---- Account setup: username + password come first, then the trader, then the tutorial ----

account_setup = {"google": None, "stage": "age", "field": "year", "user": "", "pw": "", "pw2": "", "year": "",
                 "pin": "", "pin2": "", "consent": False, "error": "", "btns": {}, "opened": 0.0}

SETUP_FIELDS = {"age": ["year"], "parent": ["pin", "pin2"], "account": ["user", "pw", "pw2"]}
SETUP_LIMITS = {"year": 4, "pin": 4, "pin2": 4, "user": 14, "pw": 25, "pw2": 25}


def open_account_setup(google=None, username="", password=""):
    suggested = username
    if google and not suggested:
        suggested = "".join(ch for ch in google.get("name", "") if ch.isalnum() or ch == " ").strip()[:14]
    account_setup.update(google=google, stage="age", field="year", user=suggested, pw=password, pw2="", year="",
                         pin="", pin2="", consent=False, error="", btns={}, opened=time.time())
    state.auth_message = ""
    state.screen_mode = "account_setup"


def _setup_is_child():
    a = account_setup
    return not ledger_safety.birth_year_problem(a["year"]) and \
        ledger_safety.age_from_birth_year(a["year"]) < ledger_safety.MIN_AGE_WITHOUT_PARENT


def _account_checks():
    a = account_setup
    user = " ".join(a["user"].strip().split())
    taken = bool(user) and _normalize_account_key(user) in _read_accounts().get("accounts", {})
    return [
        ("Username is 3-14 letters and friendly", ledger_safety.username_problem(user) is None),
        ("Username is available", len(user) >= 3 and not taken),
        ("Password is at least 4 characters", len(a["pw"]) >= 4),
        ("Passwords match", bool(a["pw"]) and a["pw"] == a["pw2"]),
    ]


def _setup_stage_next():
    """Validate the current step. Age -> (parent, if under 13) -> account."""
    a = account_setup
    if a["stage"] == "age":
        problem = ledger_safety.birth_year_problem(a["year"])
        if problem:
            a["error"] = problem
            play_sound("error")
            return
        a["stage"] = "parent" if _setup_is_child() else "account"
    elif a["stage"] == "parent":
        if not ledger_safety.pin_is_valid(a["pin"]):
            a["error"] = "The Parent PIN needs exactly 4 numbers."
        elif a["pin"] != a["pin2"]:
            a["error"] = "The two PINs don't match yet."
        elif not a["consent"]:
            a["error"] = "A parent or guardian needs to tick the box."
        else:
            a["stage"] = "account"
        if a["stage"] == "parent":
            play_sound("error")
            return
    else:
        submit_account_setup()
        return
    a["field"] = SETUP_FIELDS[a["stage"]][0]
    a["error"] = ""
    a["opened"] = time.time()
    play_sound("click")


def _setup_back():
    a = account_setup
    a["error"] = ""
    if a["stage"] == "account":
        a["stage"] = "parent" if _setup_is_child() else "age"
    elif a["stage"] == "parent":
        a["stage"] = "age"
    else:
        state.screen_mode = "signin"
        return
    a["field"] = SETUP_FIELDS[a["stage"]][0]
    play_sound("click")


def submit_account_setup():
    a = account_setup
    failed = next((label for label, ok in _account_checks() if not ok), None)
    if failed:
        a["error"] = {"Username is 3-14 letters and friendly": ledger_safety.username_problem(a["user"]) or "",
                      "Username is available": "That username is taken. Try another one.",
                      "Password is at least 4 characters": "Your password needs at least 4 characters.",
                      "Passwords match": "The two passwords don't match yet."}[failed]
        play_sound("error")
        return
    look = dict(state.avatar)
    if not create_account(a["user"], a["pw"]):
        a["error"] = state.auth_message
        play_sound("error")
        return
    state.avatar = look
    accounts = _read_accounts()
    rec = accounts["accounts"].get(_normalize_account_key(state.account_username))
    if isinstance(rec, dict):
        if a["google"]:
            rec["google_sub"] = a["google"]["sub"]
        child = _setup_is_child()
        rec["parental"] = {
            "birth_year": int(a["year"]),
            "pin_hash": ledger_safety.hash_secret(a["pin"]) if child and a["pin"] else "",
            "consent_at": time.strftime("%Y-%m-%d %H:%M") if child else "",
            "daily_limit_min": 0,
        }
        _write_accounts(accounts)
        load_parental()
    state.name_input = state.account_username
    state.password_input = ""
    state.avatar_active_field = "nick"
    play_sound("achievement")


def _setup_field(surface, btns, key, label, value, hint, masked, y, active, now):
    draw_text(surface, label, font_small_bold, SG_TEXT, 24, y)
    box = pygame.Rect(20, y + 22, WIDTH - 40, 52)
    pygame.draw.rect(surface, SG_PANEL_2 if active else SG_PANEL, box, border_radius=16)
    pygame.draw.rect(surface, SG_GOLD if active else SG_LINE, box, 2 if active else 1, border_radius=16)
    shown = ("•" * len(value)) if masked else value
    if shown:
        r = draw_text(surface, shown, font_body_bold, SG_TEXT, box.x + 18, box.centery - 10, max_width=box.w - 40)
    else:
        r = pygame.Rect(box.x + 18, box.centery - 10, 0, 20)
        draw_text(surface, hint, font_body, SG_MUTED, box.x + 18, box.centery - 10, max_width=box.w - 40)
    if active and int(now * 2) % 2 == 0:
        cx = (r.right + 2) if shown else box.x + 18
        pygame.draw.line(surface, SG_GOLD, (cx, box.centery - 11), (cx, box.centery + 11), 2)
    btns["field_" + key] = box
    return y + 88


def draw_account_setup(surface):
    a = account_setup
    a["btns"] = {}
    now = time.time()
    _sg_background(surface, now)
    t = now - a["opened"]
    appear = ease_out_cubic(t / 0.4)
    close = pygame.Rect(16, 16, 40, 40)
    _sg_close(surface, close, a["btns"])
    # Step indicator: 1 account, 2 trader, 3 tutorial.
    steps = ["Account", "Trader", "Tutorial"]
    sx = WIDTH // 2 - 120
    for i, name in enumerate(steps):
        cx = sx + i * 120
        on = i == 0
        pygame.draw.circle(surface, SG_GOLD if on else SG_PANEL_2, (cx, 36), 13)
        draw_text(surface, str(i + 1), font_small_bold, SG_INK if on else SG_MUTED, cx, 27, align="center")
        draw_text(surface, name, font_tiny, SG_TEXT if on else SG_MUTED, cx, 54, align="center")
        if i < 2:
            pygame.draw.line(surface, SG_LINE, (cx + 20, 36), (cx + 100, 36), 2)

    y = 96 + int((1 - appear) * 16)
    stage = a["stage"]
    if stage == "age":
        draw_text(surface, "How old are you?", font_sg_title, SG_TEXT, WIDTH // 2, y, align="center")
        draw_text(surface, "Type the year you were born.", font_body, SG_MUTED, WIDTH // 2, y + 44, align="center")
        y = _setup_field(surface, a["btns"], "year", "Birth year", a["year"], "e.g. 2013", False, y + 96,
                         a["field"] == "year", now)
        for line in ("We ask so a grown-up can help set things up",
                     "for younger players. Your age stays on this computer."):
            draw_text(surface, line, font_small, SG_MUTED, WIDTH // 2, y, align="center")
            y += 22
        cta, ok = "Next", len(a["year"]) == 4
    elif stage == "parent":
        draw_text(surface, "Grab a grown-up!", font_sg_title, SG_TEXT, WIDTH // 2, y, align="center")
        draw_text(surface, "Players under 13 set up Ledger with a parent.", font_body, SG_MUTED, WIDTH // 2, y + 44,
                  align="center", max_width=WIDTH - 40)
        y += 80
        for fact in ("Pretend money only. No ads, no chat, nothing to buy.",
                     "Everything stays saved on this computer.",
                     "The PIN guards Parent View, time limits and resets."):
            pygame.draw.circle(surface, SG_GREEN, (32, y + 9), 8)
            _sg_check(surface, 32, y + 9, 0.45, SG_BG, 2)
            draw_text(surface, fact, font_small, SG_TEXT, 50, y, max_width=WIDTH - 70)
            y += 24
        y += 6
        y = _setup_field(surface, a["btns"], "pin", "Parent PIN (4 numbers)", a["pin"], "Grown-ups only", True, y,
                         a["field"] == "pin", now)
        y = _setup_field(surface, a["btns"], "pin2", "Type the PIN again", a["pin2"], "Same 4 numbers", True, y - 8,
                         a["field"] == "pin2", now)
        box = pygame.Rect(20, y - 4, WIDTH - 40, 44)
        pygame.draw.rect(surface, SG_GOLD if a["consent"] else SG_PANEL_2, pygame.Rect(box.x + 4, box.y + 10, 24, 24), border_radius=7)
        if a["consent"]:
            _sg_check(surface, box.x + 16, box.y + 22, 0.6, SG_INK, 3)
        draw_text(surface, "I'm this player's parent or guardian", font_small_bold, SG_TEXT, box.x + 40, box.y + 4)
        draw_text(surface, "and I agree to them using Ledger.", font_small, SG_MUTED, box.x + 40, box.y + 23)
        a["btns"]["consent"] = box
        y += 50
        cta, ok = "Next", ledger_safety.pin_is_valid(a["pin"]) and a["pin"] == a["pin2"] and a["consent"]
    else:
        draw_text(surface, "Create your account", font_sg_title, SG_TEXT, WIDTH // 2, y, align="center")
        if a["google"]:
            sub = f"Signed in with Google as {a['google'].get('name') or 'you'}."
            sub2 = "Now choose a Ledger username and password."
        else:
            sub, sub2 = "Choose the username and password", "you'll use to log in."
        draw_text(surface, sub, font_body, SG_MUTED, WIDTH // 2, y + 44, align="center", max_width=WIDTH - 40)
        draw_text(surface, sub2, font_body, SG_MUTED, WIDTH // 2, y + 66, align="center", max_width=WIDTH - 40)
        y += 108
        for key, label, value, hint, masked in (("user", "Username", a["user"], "e.g. StockNinja", False),
                                                ("pw", "Password", a["pw"], "At least 4 characters", True),
                                                ("pw2", "Confirm password", a["pw2"], "Type it again", True)):
            y = _setup_field(surface, a["btns"], key, label, value, hint, masked, y, a["field"] == key, now)
        # Live checklist.
        for label, ok in _account_checks():
            pygame.draw.circle(surface, SG_GREEN if ok else SG_PANEL_2, (32, y + 9), 9)
            if ok:
                _sg_check(surface, 32, y + 9, 0.5, SG_BG, 2)
            draw_text(surface, label, font_small, SG_TEXT if ok else SG_MUTED, 50, y)
            y += 26
        cta, ok = "Next: design your trader", all(ok for _, ok in _account_checks())
    if a["error"]:
        draw_text(surface, a["error"], font_small_bold, SG_RED, WIDTH // 2, y + 6, align="center", max_width=WIDTH - 40)

    _sg_button(surface, pygame.Rect(20, HEIGHT - 92, WIDTH - 40, 60), "create", cta,
               SG_GOLD if ok else SG_PANEL_2, SG_INK if ok else SG_MUTED, btns=a["btns"])


def handle_account_setup_click(pos):
    a = account_setup
    for key, rect in a["btns"].items():
        if rect.collidepoint(pos):
            if key == "close":
                _setup_back()
            elif key == "create":
                _setup_stage_next()
            elif key == "consent":
                a["consent"] = not a["consent"]
                a["error"] = ""
                play_sound("click")
            else:
                a["field"] = key.split("_", 1)[1]
                a["error"] = ""
            return


def handle_account_setup_key(event):
    a = account_setup
    order = SETUP_FIELDS[a["stage"]]
    if a["field"] not in order:
        a["field"] = order[0]
    if event.key == pygame.K_TAB:
        a["field"] = order[(order.index(a["field"]) + 1) % len(order)]
    elif event.key == pygame.K_RETURN:
        if a["field"] != order[-1]:
            a["field"] = order[order.index(a["field"]) + 1]
        else:
            _setup_stage_next()
    elif event.key == pygame.K_ESCAPE:
        _setup_back()
    else:
        value = handle_text_event(event, a[a["field"]], SETUP_LIMITS[a["field"]])
        if a["field"] in ("year", "pin", "pin2"):
            value = "".join(ch for ch in value if ch.isdigit())
        a[a["field"]] = value
        a["error"] = ""


signin_forgot_rect = None


def handle_signin_click(pos):
    if signin_forgot_rect and signin_forgot_rect.collidepoint(pos):
        play_sound("click")
        open_reset_password()
        return
    if signin_user_rect and signin_user_rect.collidepoint(pos):
        state.auth_active_field = "username"
        return
    if signin_pw_rect and signin_pw_rect.collidepoint(pos):
        state.auth_active_field = "password"
        return
    if signin_login_btn and signin_login_btn.collidepoint(pos):
        play_sound("click")
        login_account(state.login_username_input, state.login_password_input)
        return
    if signin_create_btn and signin_create_btn.collidepoint(pos):
        play_sound("click")
        open_account_setup(username=state.login_username_input.strip())
        return
    for btn, mode in ((signin_google_btn, "in"), (signin_google_up_btn, "up")):
        if btn and btn.collidepoint(pos):
            global google_mode
            play_sound("click")
            google_mode = mode
            state.auth_message = google_auth.start()
            return
    if signin_guest_btn and signin_guest_btn.collidepoint(pos):
        play_sound("click")
        # Guest mode is intentionally temporary and is never written as an account.
        _reset_to_fresh_state()
        state.logged_in = False
        state.guest_mode = True
        state.account_username = ""
        state.player_name = "Guest"
        state.last_free_chest_day = time.strftime("%Y-%m-%d")
        state.screen_mode = "avatar"
        state.auth_message = "Guest mode is temporary and will not be saved."


def draw_google_form_screen(surface):
    global google_name_rect, google_email_rect, google_continue_btn, google_back_btn
    draw_app_background(surface)
    draw_text(surface, "Sign in with Google", font_large_med, C("INK"), WIDTH // 2, 80, align="center")
    draw_text(surface, "Pretend sign-in for this paper-money game", font_small, C("GRAY"), WIDTH // 2, 112, align="center")
    draw_text(surface, "Full name", font_small_bold, C("GRAY"), 40, 170)
    google_name_rect = pygame.Rect(40, 190, WIDTH - 80, 44)
    draw_rounded_rect(surface, google_name_rect, C("CARD"), radius=10, border_color=C("INK") if state.google_active_field == "name" else C("BORDER"), border_width=2 if state.google_active_field == "name" else 1)
    draw_text(surface, state.name_input or "Jane Doe", font_body_bold, C("INK") if state.name_input else C("LIGHT_GRAY"), google_name_rect.x + 14, google_name_rect.y + 13)
    draw_text(surface, "Gmail address", font_small_bold, C("GRAY"), 40, 250)
    google_email_rect = pygame.Rect(40, 270, WIDTH - 80, 44)
    draw_rounded_rect(surface, google_email_rect, C("CARD"), radius=10, border_color=C("INK") if state.google_active_field == "email" else C("BORDER"), border_width=2 if state.google_active_field == "email" else 1)
    draw_text(surface, state.email_input or "you@gmail.com", font_body_bold, C("INK") if state.email_input else C("LIGHT_GRAY"), google_email_rect.x + 14, google_email_rect.y + 13)
    google_continue_btn = pygame.Rect(40, 340, WIDTH - 80, 50)
    draw_button(surface, google_continue_btn, "Continue", C("INK"), C("CARD"), radius=12)
    google_back_btn = pygame.Rect(40, 404, WIDTH - 80, 36)
    draw_text(surface, "Back", font_body_bold, C("GRAY"), WIDTH // 2, 410, align="center")


def handle_google_form_click(pos):
    if google_name_rect and google_name_rect.collidepoint(pos):
        state.google_active_field = "name"
    elif google_email_rect and google_email_rect.collidepoint(pos):
        state.google_active_field = "email"
    elif google_continue_btn and google_continue_btn.collidepoint(pos):
        play_sound("click")
        state.screen_mode = "avatar"
    elif google_back_btn and google_back_btn.collidepoint(pos):
        play_sound("click")
        state.screen_mode = "signin"


avatar_randomize_btn = None
creator_tab = "skin"
creator_chip_rects = []
creator_option_rects = []
creator_nick_rect = None
creator_back_btn = None
creator_preview_rect = None

CREATOR_TABS = [
    ("skin", "Skin"), ("hair_style", "Hair"), ("hair_color", "Color"), ("outfit_style", "Style"),
    ("outfit", "Outfit"), ("accessory", "Gear"), ("persona", "Persona"),
]
CREATOR_SWATCH_TRAITS = {"skin": SKIN_TONES, "hair_color": HAIR_COLORS, "outfit": OUTFIT_COLORS}
CREATOR_TILE_LABELS = {
    "hair_style": [h.capitalize() for h in HAIR_STYLES],
    "outfit_style": [o.capitalize() for o in OUTFIT_STYLES],
    "accessory": [a.capitalize() if a != "none" else "None" for a in ACCESSORIES],
}


_icon_cache = {}
_icon_fonts = {}
ICON_SUPERSAMPLE = 4


def _paint_icon(big, kind, color, u):
    """Draw an icon on a large canvas. Coordinates are icon units (about -13..13) around the center;
    u is pixels per unit. The caller scales the result down, which gives clean anti-aliased edges."""
    c = big.get_width() / 2
    col = (*color[:3], 255)

    def P(x, y):
        return (c + x * u, c + y * u)

    def line(a, b, width=2.4):
        # Thick line with round caps.
        pygame.draw.line(big, col, P(*a), P(*b), max(1, int(width * u)))
        for pt in (a, b):
            pygame.draw.circle(big, col, P(*pt), width * u / 2)

    def poly(points, width=0):
        pygame.draw.polygon(big, col, [P(*p) for p in points], 0 if width == 0 else max(1, int(width * u)))

    def ring(x, y, r, width=2.4):
        pygame.draw.circle(big, col, P(x, y), r * u, max(1, int(width * u)))

    def dollar(size):
        key = int(size * u)
        f = _icon_fonts.get(key)
        if f is None:
            f = _icon_fonts[key] = pygame.font.SysFont(_UI_FONT, key, bold=True)
        img = f.render("$", True, color[:3])
        big.blit(img, img.get_rect(center=(c, c + 0.5 * u)))

    if kind == "lock":
        # Shackle: a clean rounded U, then the body with a keyhole cut out.
        pygame.draw.circle(big, col, P(0, -3), 6.2 * u, int(2.8 * u), draw_top_left=True, draw_top_right=True)
        pygame.draw.rect(big, col, (*P(-6.2, -3.2), 2.8 * u, 5 * u))
        pygame.draw.rect(big, col, (*P(3.4, -3.2), 2.8 * u, 5 * u))
        pygame.draw.rect(big, col, (*P(-9, 0), 18 * u, 13 * u), border_radius=int(3.2 * u))
        hole = (0, 0, 0, 0)
        pygame.draw.circle(big, hole, P(0, 5.2), 2.1 * u)
        pygame.draw.rect(big, hole, (*P(-0.9, 5.5), 1.8 * u, 3.6 * u), border_radius=int(0.9 * u))
    elif kind == "arrows":
        line((-5, 9), (-5, -5))
        poly([(-10.5, -3), (0.5, -3), (-5, -10.5)])
        line((5, -9), (5, 5))
        poly([(-0.5, 3), (10.5, 3), (5, 10.5)])
    elif kind == "chart":
        line((-10, 7), (-4, 0))
        line((-4, 0), (1, 4))
        line((1, 4), (8, -4))
        poly([(11, -8), (11, -1), (4, -8)])
    elif kind == "columns":
        poly([(-12, -4), (0, -11), (12, -4)])
        for dx in (-7, 0, 7):
            pygame.draw.rect(big, col, (*P(dx - 2, -2), 4 * u, 10 * u), border_radius=int(0.8 * u))
        pygame.draw.rect(big, col, (*P(-12, 9), 24 * u, 3 * u), border_radius=int(1 * u))
    elif kind == "coin":
        ring(0, 0, 11.5)
        dollar(15)
    elif kind == "bars":
        for dx, hgt in ((-10, 8), (-3, 13), (4, 19)):
            pygame.draw.rect(big, col, (*P(dx, 10 - hgt), 5.5 * u, hgt * u), border_radius=int(1.5 * u))
    elif kind == "percent":
        ring(-6, -6, 3.6, 2.2)
        ring(6, 6, 3.6, 2.2)
        line((8, -10), (-8, 10), 2.4)
    elif kind == "pie":
        ring(0, 0, 11)
        steps = 12
        pts = [(0, 0)] + [(math.cos(-math.pi / 2 + (math.pi / 2) * i / steps) * 11, math.sin(-math.pi / 2 + (math.pi / 2) * i / steps) * 11) for i in range(steps + 1)]
        poly(pts)
        line((0, 0), (-7.8, 7.8), 2.2)
    elif kind == "bolt":
        poly([(3, -12), (-7.5, 2), (-1, 2), (-3, 12), (7.5, -2), (1, -2)])
    elif kind == "layers":
        poly([(-11, -5), (0, -10.5), (11, -5), (0, 0.5)])
        for dy in (0, 5.5):
            line((-11, -0.5 + dy), (0, 5 + dy), 2.2)
            line((0, 5 + dy), (11, -0.5 + dy), 2.2)
    elif kind == "scroll":
        pygame.draw.rect(big, col, (*P(-9, -11.5), 18 * u, 23 * u), int(2.4 * u), border_radius=int(3.5 * u))
        for dy in (-5, 0, 5):
            line((-4.5, dy), (4.5, dy), 2.2)
    elif kind == "curve":
        pts = [(-11 + i * 2.2, 8 - (1.32 ** i) * 0.9) for i in range(11)]
        for a, b in zip(pts, pts[1:]):
            line(a, b)
        line((-11, 11), (11, 11), 2.2)
    elif kind == "cart":
        line((-12, -8), (-8, -8))
        line((-8, -8), (-5, 5))
        line((-5, 5), (8, 5))
        line((8, 5), (10.5, -4))
        line((10.5, -4), (-6.5, -4))
        ring(-3, 10, 2, 2)
        ring(6, 10, 2, 2)
    elif kind == "shield":
        poly([(0, -12), (10, -8), (9, 3), (0, 12), (-9, 3), (-10, -8)], 2.4)
        line((-4, 0), (-1, 3.5), 2.2)
        line((-1, 3.5), (5, -3.5), 2.2)
    elif kind == "news":
        pygame.draw.rect(big, col, (*P(-11, -10), 22 * u, 20 * u), int(2.4 * u), border_radius=int(3 * u))
        pygame.draw.rect(big, col, (*P(-7, -6), 6 * u, 6 * u))
        line((2, -5), (7, -5), 2)
        line((2, -1), (7, -1), 2)
        line((-7, 4), (7, 4), 2)
    elif kind == "clock":
        ring(0, 0, 11)
        line((0, -6), (0, 0), 2.4)
        line((0, 0), (5, 3), 2.4)
    elif kind == "heart":
        pygame.draw.circle(big, col, P(-5, -3), 6 * u)
        pygame.draw.circle(big, col, P(5, -3), 6 * u)
        poly([(-10.6, -0.5), (10.6, -0.5), (0, 11)])
    elif kind == "scale":
        line((0, -11), (0, 9))
        line((-9, -7), (9, -7))
        line((-7, 9), (7, 9))
        poly([(-13, 1), (-5, 1), (-9, -6)], 2)
        poly([(5, 1), (13, 1), (9, -6)], 2)
    elif kind == "target":
        ring(0, 0, 11, 2.2)
        ring(0, 0, 6, 2.2)
        pygame.draw.circle(big, col, P(0, 0), 2.2 * u)
    elif kind == "balloon":
        pygame.draw.ellipse(big, col, (*P(-8.5, -12.5), 17 * u, 20 * u), int(2.4 * u))
        line((0, 7.5), (-1.8, 10), 2)
        line((-1.8, 10), (1, 13), 2)
        dollar(11)


def draw_icon(surface, kind, cx, cy, color, size=1.0):
    """Supersampled icon, cached per kind/color/size so it costs a single blit per frame."""
    key = (kind, tuple(color[:3]), round(size, 2), UI_SCALE)
    img = _icon_cache.get(key)
    if img is None:
        px = max(4, int(round(30 * size * UI_SCALE)))
        big = pygame.Surface((px * ICON_SUPERSAMPLE, px * ICON_SUPERSAMPLE), pygame.SRCALPHA)
        big.fill((*color[:3], 0))  # transparent pixels share the icon color, so edges don't go dark
        _paint_icon(big, kind, color, px * ICON_SUPERSAMPLE / 30.0)
        img = pygame.transform.smoothscale(big, (px, px))
        if len(_icon_cache) > 300:
            _icon_cache.clear()
        _icon_cache[key] = img
    target = surface.hi if isinstance(surface, HiSurface) else surface
    scale = UI_SCALE if isinstance(surface, HiSurface) else 1
    target.blit(img, (round(cx * scale - img.get_width() / 2), round(cy * scale - img.get_height() / 2)))


def draw_padlock(surface, cx, cy, size, color):
    draw_icon(surface, "lock", cx, cy, color, max(0.4, size / 17.0))


def _creator_variant(trait, idx):
    variant = dict(state.avatar)
    variant[trait] = idx
    return variant


def _creator_field(surface, rect, text, placeholder, active, masked=False):
    draw_rounded_rect(surface, rect, C("CARD"), radius=8, border_color=C("INK") if active else C("BORDER"),
                      border_width=2 if active else 1, shadow=False)
    shown = ("*" * len(text)) if masked else text
    if shown:
        draw_text(surface, shown + ("|" if active else ""), font_body_bold, C("INK"), rect.x + 10, rect.y + 8, max_width=rect.w - 20)
    else:
        draw_text(surface, placeholder, font_body, C("LIGHT_GRAY"), rect.x + 10, rect.y + 8, max_width=rect.w - 20)


def draw_avatar_screen(surface):
    global name_input_rect, pw_input_rect, avatar_continue_btn, avatar_randomize_btn
    global creator_chip_rects, creator_option_rects, creator_nick_rect, creator_back_btn, creator_preview_rect
    surface.fill(C("BG"))
    editing = bool(getattr(state, "avatar_editing", False))
    now = time.time()

    draw_text(surface, "Your Trader" if editing else "Create your trader", font_large_med, C("INK"), WIDTH // 2, 12, align="center")
    draw_text(surface, "Pick a look and a personality", font_tiny, C("GRAY"), WIDTH // 2, 40, align="center")

    half = (WIDTH - 80 - 12) // 2
    if editing:
        draw_text(surface, "Username", font_tiny, C("GRAY"), 40, 62)
        name_input_rect = pygame.Rect(40, 78, half, 34)
        _creator_field(surface, name_input_rect, state.name_input, "StockNinja", state.avatar_active_field == "name")
        draw_text(surface, "New password (optional)", font_tiny, C("GRAY"), 40 + half + 12, 62)
        pw_input_rect = pygame.Rect(40 + half + 12, 78, half, 34)
        _creator_field(surface, pw_input_rect, state.password_input, "Create a password", state.avatar_active_field == "password", masked=True)
    else:
        # New players already chose their login on the account screen, so this step is just the look.
        name_input_rect = pw_input_rect = None
        who = "Guest trader" if getattr(state, "guest_mode", False) else state.account_username or state.player_name
        chip = pygame.Rect(40, 68, WIDTH - 80, 40)
        draw_rounded_rect(surface, chip, C("PURPLE_BG"), radius=20, border_color=C("PURPLE"), border_width=1, shadow=False)
        draw_text(surface, f"Step 2 of 3  ·  Welcome, {who}!", font_small_bold, C("PURPLE"), chip.centerx, chip.y + 11,
                  align="center", max_width=chip.w - 24)

    creator_preview_rect = pygame.Rect(40, 122, WIDTH - 80, 170)
    draw_rounded_rect(surface, creator_preview_rect, C("PANEL_BG"), radius=16, border_color=C("BORDER"), border_width=1, shadow=False)
    if avatar_anim["pulse"] > 0:
        rad = int(50 + 24 * (1 - avatar_anim["pulse"]))
        ring = HiSurface((rad * 2 + 8, rad * 2 + 8), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*C("PURPLE"), int(80 * avatar_anim["pulse"])), (rad + 4, rad + 4), rad, 3)
        surface.blit(ring, (creator_preview_rect.x + 100 - rad - 4, creator_preview_rect.y + 90 - rad - 4))
    draw_character(surface, state.avatar, creator_preview_rect.x + 100, creator_preview_rect.y + 62, scale=2.0, animate=True, now=now)

    px = creator_preview_rect.x + 200
    pw = creator_preview_rect.w - 214
    draw_text(surface, avatar_display_name(), font_medium_bold, C("INK"), px, creator_preview_rect.y + 16, max_width=pw)
    persona = PERSONALITIES[int(state.avatar.get("persona", 0)) % len(PERSONALITIES)]
    chip = pygame.Rect(px, creator_preview_rect.y + 44, 86, 20)
    draw_rounded_rect(surface, chip, C("PURPLE_BG"), radius=10, border_color=C("PURPLE"), border_width=1, shadow=False)
    draw_text(surface, persona["name"], font_tiny, C("PURPLE"), chip.centerx, chip.y + 3, align="center")
    if avatar_is_speaking(now):
        line = avatar_anim["speech"]
        line_col = C("INK")
    else:
        line = "Tap me! I react to clicks."
        line_col = C("LIGHT_GRAY")
    for i, ln in enumerate(wrap_text(line, font_small, pw)[:3]):
        draw_text(surface, ln, font_small, line_col, px, creator_preview_rect.y + 76 + i * 17, max_width=pw)
    draw_text(surface, "Level up for more looks", font_tiny, C("GRAY"), px, creator_preview_rect.bottom - 24, max_width=pw)

    creator_chip_rects = []
    n = len(CREATOR_TABS)
    gap = 4
    # Each tab is as wide as its label plus equal padding, so nothing gets cut off.
    left, avail = 24, WIDTH - 48
    text_w = [font_tiny.size(label)[0] for _, label in CREATOR_TABS]
    pad = max(6, (avail - sum(text_w) - gap * (n - 1)) / n)
    x = left
    for i, (key, label) in enumerate(CREATOR_TABS):
        r = pygame.Rect(int(x), 302, int(text_w[i] + pad), 30)
        active = key == creator_tab
        draw_rounded_rect(surface, r, C("INK") if active else C("CARD"), radius=15,
                          border_color=C("INK") if active else C("BORDER"), border_width=1, shadow=False)
        draw_text(surface, label, font_tiny, C("CARD") if active else C("INK"), r.centerx, r.y + 7, align="center", max_width=r.w)
        creator_chip_rects.append((r, key))
        x += text_w[i] + pad + gap

    creator_option_rects = []
    creator_nick_rect = None
    top = 344
    if creator_tab in CREATOR_SWATCH_TRAITS:
        colors = CREATOR_SWATCH_TRAITS[creator_tab]
        per_row, size, gapx = 6, 44, (WIDTH - 80 - 6 * 44) // 5
        for idx, col in enumerate(colors):
            r = pygame.Rect(40 + (idx % per_row) * (size + gapx), top + (idx // per_row) * (size + 14), size, size)
            selected = int(state.avatar.get(creator_tab, 0)) == idx
            unlocked = cosmetic_unlocked(creator_tab, idx)
            pygame.draw.circle(surface, C("PURPLE") if selected else C("BORDER"), r.center, size // 2 + (3 if selected else 1))
            pygame.draw.circle(surface, col, r.center, size // 2 - 2)
            if not unlocked:
                dim = HiSurface((size, size), pygame.SRCALPHA)
                pygame.draw.circle(dim, (0, 0, 0, 120), (size // 2, size // 2), size // 2 - 2)
                surface.blit(dim, r.topleft)
                draw_padlock(surface, r.centerx, r.centery - 3, 14, (255, 255, 255))
                draw_text(surface, cosmetic_requirement(creator_tab, idx, True), font_tiny, C("GRAY"), r.centerx, r.bottom + 1, align="center")
            creator_option_rects.append((r, creator_tab, idx))
    elif creator_tab in CREATOR_TILE_LABELS:
        labels = CREATOR_TILE_LABELS[creator_tab]
        per_row, tw, th = 5, 68, 88
        gapx = (WIDTH - 80 - per_row * tw) // (per_row - 1)
        for idx, label in enumerate(labels):
            r = pygame.Rect(40 + (idx % per_row) * (tw + gapx), top + (idx // per_row) * (th + 8), tw, th)
            selected = int(state.avatar.get(creator_tab, 0)) == idx
            unlocked = cosmetic_unlocked(creator_tab, idx)
            draw_rounded_rect(surface, r, C("PURPLE_BG") if selected else C("CARD"), radius=12,
                              border_color=C("PURPLE") if selected else C("BORDER"), border_width=2 if selected else 1, shadow=False)
            if unlocked:
                prev = surface.get_clip()
                surface.set_clip(r.inflate(-4, -4))
                draw_character(surface, _creator_variant(creator_tab, idx), r.centerx, r.y + 30, scale=0.75)
                surface.set_clip(prev)
                draw_text(surface, label, font_tiny, C("INK"), r.centerx, r.bottom - 18, align="center", max_width=tw - 6)
            else:
                dim = HiSurface(r.size, pygame.SRCALPHA)
                pygame.draw.rect(dim, (*C("PANEL_BG"), 255), dim.get_rect(), border_radius=12)
                surface.blit(dim, r.topleft)
                draw_padlock(surface, r.centerx, r.y + 30, 22, C("GRAY"))
                draw_text(surface, cosmetic_requirement(creator_tab, idx, True), font_tiny, C("GRAY"), r.centerx, r.bottom - 18, align="center", max_width=tw - 6)
            creator_option_rects.append((r, creator_tab, idx))
    else:
        draw_text(surface, "Sidekick name", font_tiny, C("GRAY"), 40, top - 2)
        creator_nick_rect = pygame.Rect(40, top + 14, WIDTH - 80, 34)
        _creator_field(surface, creator_nick_rect, str(state.avatar.get("nickname", "")), "Optional nickname", state.avatar_active_field == "nick")
        y = top + 60
        for idx, p in enumerate(PERSONALITIES):
            r = pygame.Rect(40, y, WIDTH - 80, 44)
            selected = int(state.avatar.get("persona", 0)) == idx
            draw_rounded_rect(surface, r, C("PURPLE_BG") if selected else C("CARD"), radius=10,
                              border_color=C("PURPLE") if selected else C("BORDER"), border_width=2 if selected else 1, shadow=False)
            draw_text(surface, p["name"], font_body_bold, C("INK"), r.x + 14, r.y + 5)
            draw_text(surface, p["desc"], font_tiny, C("GRAY"), r.x + 14, r.y + 25, max_width=r.w - 28)
            creator_option_rects.append((r, "persona", idx))
            y += 50

    half_btn = (WIDTH - 80 - 12) // 2
    creator_back_btn = pygame.Rect(40, HEIGHT - 116, half_btn, 36)
    draw_button(surface, creator_back_btn, "Cancel" if editing else "Back", C("PANEL_BG"), C("INK"), font=font_small_bold, radius=9)
    avatar_randomize_btn = pygame.Rect(40 + half_btn + 12, HEIGHT - 116, half_btn, 36)
    draw_button(surface, avatar_randomize_btn, "Randomize", C("PANEL_BG"), C("INK"), font=font_small_bold, radius=9)

    if state.auth_message:
        draw_text(surface, state.auth_message, font_tiny, C("RED"), WIDTH // 2, HEIGHT - 136, align="center", max_width=WIDTH - 80)

    avatar_continue_btn = pygame.Rect(40, HEIGHT - 70, WIDTH - 80, 46)
    draw_button(surface, avatar_continue_btn, "Save look" if editing else "Continue", C("INK"), C("CARD"), radius=12)


def _avatar_randomize():
    for trait, count in CREATOR_TRAITS.items():
        if trait == "persona":
            continue
        options = [i for i in range(count) if cosmetic_unlocked(trait, i)]
        state.avatar[trait] = random.choice(options)


def _avatar_continue():
    username = state.name_input.strip() or state.player_name or "StockNinja"
    password = state.password_input.strip()
    if not ledger_safety.is_kid_safe(str(state.avatar.get("nickname", "") or "")):
        state.auth_message = "That nickname isn't allowed. Try something friendly!"
        play_sound("error")
        return
    if getattr(state, "avatar_editing", False) and username != state.player_name and ledger_safety.username_problem(username):
        state.auth_message = ledger_safety.username_problem(username)
        play_sound("error")
        return
    if getattr(state, "avatar_editing", False):
        # Editing an existing trader (from the menu) only saves the look and
        # returns to the game. It must never restart onboarding, including for guests.
        state.player_name = username
        if password and state.logged_in:
            state.password = password
        state.avatar_editing = False
        state.screen_mode = "playing"
        state.tab = getattr(state, "avatar_return_tab", "home")
        save_game()
        avatar_say("Your look is saved.", mood="happy")
        avatar_emote("cheer")
        play_sound("achievement")
        return
    if not state.logged_in:
        if getattr(state, "guest_mode", False) and getattr(state, "tutorial_completed", False):
            state.screen_mode = "playing"
            play_sound("click")
            return
        if getattr(state, "guest_mode", False):
            state.player_name = "Guest"
            state.screen_mode = "tutorial"
            state.tutorial_index = 0
            reset_tutorial_demo()
            play_sound("click")
            return
        # create_account() starts from a brand-new game state, which would throw away
        # the look the player just designed on this screen, so carry it over.
        look = dict(state.avatar)
        if create_account(username, password):
            state.avatar = look
            state.friends = []
            state.outgoing_requests = []
            state.tutorial_index = 0
            state.screen_mode = "tutorial"
            reset_tutorial_demo()
            save_game()
            play_sound("click")
        else:
            play_sound("error")
        return
    state.player_name = username
    if password:
        state.password = password
    if getattr(state, "tutorial_completed", False):
        state.screen_mode = "playing"
    else:
        state.screen_mode = "tutorial"
        state.tutorial_index = 0
        reset_tutorial_demo()
    save_game()
    play_sound("click")


def handle_avatar_click(pos):
    global creator_tab
    editing = bool(getattr(state, "avatar_editing", False))
    if name_input_rect and name_input_rect.collidepoint(pos):
        state.avatar_active_field = "name"
        return
    if pw_input_rect and pw_input_rect.collidepoint(pos):
        state.avatar_active_field = "password"
        return
    if creator_nick_rect and creator_nick_rect.collidepoint(pos):
        state.avatar_active_field = "nick"
        return
    if creator_preview_rect and creator_preview_rect.collidepoint(pos):
        avatar_poke(pos)
        play_sound("click")
        return
    for rect, key in creator_chip_rects:
        if rect.collidepoint(pos):
            creator_tab = key
            if state.avatar_active_field == "nick":
                state.avatar_active_field = "name"
            play_sound("click")
            return
    for rect, trait, idx in creator_option_rects:
        if rect.collidepoint(pos):
            if cosmetic_unlocked(trait, idx):
                state.avatar[trait] = idx
                play_sound("click")
                if trait == "persona":
                    avatar_say(random.choice(_avatar_line_pool("mood", "neutral")), mood="happy")
                    avatar_emote("wave")
                else:
                    avatar_anim["pulse"] = 1.0
            else:
                show_toast("Locked", cosmetic_requirement(trait, idx), "warning")
                play_sound("error")
            return
    if creator_back_btn and creator_back_btn.collidepoint(pos):
        play_sound("click")
        if editing:
            snap = getattr(state, "avatar_snapshot", None)
            if isinstance(snap, dict):
                state.avatar = dict(snap)
            state.avatar_editing = False
            state.screen_mode = "playing"
            state.tab = getattr(state, "avatar_return_tab", "home")
        else:
            if state.logged_in:
                # Google Sign Up creates the account before this screen. Going back must sign
                # out, or "Create an account" on the sign-in screen would edit that account.
                logout_account()
            state.guest_mode = False
            state.auth_message = ""
            state.screen_mode = "signin"
        return
    if avatar_randomize_btn and avatar_randomize_btn.collidepoint(pos):
        _avatar_randomize()
        play_sound("achievement")
        avatar_anim["pulse"] = 1.0
        avatar_emote("hop")
        if creator_preview_rect:
            spawn_sparks(creator_preview_rect.x + 100, creator_preview_rect.y + 70, C("PURPLE"), 14)
        return
    if avatar_continue_btn and avatar_continue_btn.collidepoint(pos):
        _avatar_continue()


# ----------------------------
# TUTORIAL (interactive onboarding)
# ----------------------------

TUTORIAL_DONE_LINES = {
    "market": "That's a quote! Price right now, today's move, and the recent trend. That's the whole story at a glance.",
    "buysell": "You just made a full round trip: buy, watch, sell. That's trading!",
    "portfolio": "Cash + everything you own = your portfolio. Check it often!",
    "news": "Smart move. Careful traders read first and react second.",
    "risk": "Exactly! Spreading out means one bad stock can't sink you.",
    "duel": "You beat the bot! Real Arena duels work the same way.",
    "realtrade": "Your first real trade is in your portfolio. Welcome aboard!",
}

tut_btn = {}
_tutorial_coach = {"key": None, "start": 0.0}
_slides = {}


def draw_with_slide(surface, key, value, area, draw_fn, direction=1, duration=0.26):
    """Run draw_fn; when `value` changes, slide + fade the freshly drawn area in."""
    st = _slides.get(key)
    if st is None or st["value"] != value:
        _slides[key] = st = {"value": value, "start": time.time() if st is not None else 0.0, "dir": direction}
    progress = (time.time() - st["start"]) / duration
    if progress >= 1 or not isinstance(surface, HiSurface) or getattr(state, "reduced_motion", False):
        draw_fn()
        return
    e = ease_out_cubic(progress)
    hi_area = _scale_rect(area).clip(surface.hi.get_rect())
    backdrop = surface.hi.subsurface(hi_area).copy()
    draw_fn()
    content = surface.hi.subsurface(hi_area).copy()
    surface.hi.blit(backdrop, hi_area.topleft)
    content.set_alpha(int(255 * e))
    prev_clip = surface.hi.get_clip()
    surface.hi.set_clip(hi_area)
    surface.hi.blit(content, (hi_area.x + int(_sc(36) * (1 - e)) * st["dir"], hi_area.y))
    surface.hi.set_clip(prev_clip)


def draw_tap_hint(surface, rect, now, color=None, label="TAP"):
    """Pulsing ring plus a bouncing tag that says exactly where to press."""
    color = color or C("PURPLE")
    p = (now * 1.1) % 1.0
    grow = int(4 + 12 * p)
    ring = rect.inflate(grow * 2, grow * 2)
    layer = HiSurface((ring.w + 4, ring.h + 4), pygame.SRCALPHA)
    pygame.draw.rect(layer, (*color, int(170 * (1 - p))), (2, 2, ring.w, ring.h), 3, border_radius=14 + grow)
    surface.blit(layer, (ring.x - 2, ring.y - 2))
    bounce = abs(math.sin(now * 4)) * 6
    tag = pygame.Rect(0, 0, font_tiny.size(label)[0] + 18, 22)
    tag.midbottom = (rect.right - 34, rect.y - 8 - bounce)
    draw_rounded_rect(surface, tag, color, radius=11, shadow=False)
    pygame.draw.polygon(surface, color, [(tag.centerx - 6, tag.bottom - 1), (tag.centerx + 6, tag.bottom - 1), (tag.centerx, tag.bottom + 6)])
    draw_text(surface, label, font_tiny, (255, 255, 255), tag.centerx, tag.y + 3, align="center")


def draw_donut(surface, center, r_out, r_in, segments, progress=1.0):
    """segments: [(fraction, color)]. progress sweeps the ring in clockwise."""
    cx, cy = center
    start = -math.pi / 2
    budget = max(0.0, min(1.0, progress))
    for frac, color in segments:
        span = min(frac, budget)
        budget -= span
        if span <= 0:
            break
        a0, a1 = start, start + span * math.tau
        steps = max(2, int(48 * span))
        outer = [(cx + math.cos(a0 + (a1 - a0) * i / steps) * r_out, cy + math.sin(a0 + (a1 - a0) * i / steps) * r_out) for i in range(steps + 1)]
        inner = [(cx + math.cos(a1 - (a1 - a0) * i / steps) * r_in, cy + math.sin(a1 - (a1 - a0) * i / steps) * r_in) for i in range(steps + 1)]
        pygame.draw.polygon(surface, color, outer + inner)
        start = a1


def draw_check(surface, center, r, color, fg=None):
    cx, cy = center
    fg = fg or text_on(color)
    pygame.draw.circle(surface, color, (cx, cy), r)
    pygame.draw.lines(surface, fg, False, [(cx - r * 0.45, cy), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)], 2)


def _callout(surface, text, target, tag_pos, alpha_t):
    """Small purple label with a leader line pointing at part of the UI."""
    if alpha_t <= 0:
        return
    tw = font_tiny.size(text)[0] + 16
    tag = pygame.Rect(0, 0, tw, 22)
    tag.center = (int(tag_pos[0]), int(tag_pos[1] - 6 * (1 - alpha_t)))
    pygame.draw.line(surface, C("PURPLE"), tag.center, target, 2)
    pygame.draw.circle(surface, C("PURPLE"), target, 4)
    draw_rounded_rect(surface, tag, C("PURPLE"), radius=11, shadow=False)
    draw_text(surface, text, font_tiny, (255, 255, 255), tag.centerx, tag.y + 3, align="center")


def _demo_history(key, base, n=32):
    hist = tutorial_demo.setdefault(key, [])
    if len(hist) < 2:
        hist[:] = [base * (1 + 0.004 * math.sin(i * 0.6) + i * 0.0006) for i in range(n)]
    return hist


def tutorial_goal_complete():
    kind = TUTORIAL_STEPS[state.tutorial_index]["kind"]
    if kind == "welcome": return True
    if kind == "market": return tutorial_demo["quote_opened"]
    if kind == "buysell": return tutorial_demo["owned_shares"] == 0 and tutorial_demo["last_pnl"] is not None
    if kind == "portfolio": return tutorial_demo["portfolio_opened"]
    if kind == "news": return tutorial_demo["news_answered"]
    if kind == "risk": return tutorial_demo["risk_answered"] and tutorial_demo["risk_correct"]
    if kind == "duel": return tutorial_demo["duel_progress"] >= 1.0
    if kind == "realtrade": return state.holdings.get("AAPL", 0) >= 0.25
    if kind == "ready": return True
    return False


def draw_tutorial_demo(surface, kind, area):
    """Draw the hands-on activity for a tutorial step. Returns the tut_btn key to point at."""
    tut_btn.clear()
    now = time.time()
    card = pygame.Rect(area.x + 18, area.y + 4, area.w - 36, area.h - 8)
    pointer = None

    if kind == "welcome":
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        draw_text(surface, "MEET YOUR TRADER", tutorial_kicker, C("PURPLE"), card.centerx, card.y + 20, align="center")
        avatar_y = card.y + int(card.h * 0.40)
        draw_character(surface, state.avatar, card.centerx, avatar_y, scale=2.1, animate=True)
        tut_btn["avatar"] = pygame.Rect(card.centerx - 70, avatar_y - 42, 140, 146)
        chips = [("$1,000 practice cash", C("GREEN"), -1, 0.30), ("Level 1", C("PURPLE"), 1, 0.24),
                 ("0 trophies", C("GOLD"), -1, 0.66), ("Zero real money", C("ORANGE"), 1, 0.72)]
        for i, (label, col, side, fy) in enumerate(chips):
            w = font_tiny.size(label)[0] + 22
            bob = math.sin(now * 1.6 + i * 1.7) * 4
            chip = pygame.Rect(0, 0, w, 26)
            chip.center = (card.centerx + side * (card.w // 2 - w // 2 - 14), card.y + int(card.h * fy) + bob)
            draw_rounded_rect(surface, chip, C("CARD"), radius=13, border_color=col, border_width=2)
            draw_text(surface, label, font_tiny, col, chip.centerx, chip.y + 5, align="center")
        draw_text(surface, state.player_name, tutorial_body_bold, C("INK"), card.centerx, card.bottom - 60, align="center")
        draw_text(surface, "Tap your trader to say hi!", tutorial_micro, C("GRAY"), card.centerx, card.bottom - 34, align="center")
        if not tutorial_demo.get("poked"):
            pointer = "avatar"

    elif kind == "market":
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        aapl = find_asset("AAPL")
        price = float(aapl.get("price", 100.0)) if aapl else 100.0
        change = day_move_pct(aapl) if aapl else 0.0
        hist = list(aapl.get("history", [])) if aapl else []
        if len(hist) < 8 or max(hist) == min(hist):
            hist = _demo_history("quote_history", price)
        draw_text(surface, "STOCK QUOTE", tutorial_kicker, C("PURPLE"), card.x + 22, card.y + 20)
        draw_ticker_badge(surface, "AAPL", card.x + 22, card.y + 50, size=58)
        draw_text(surface, "Apple Inc.", tutorial_body_bold, C("INK"), card.x + 96, card.y + 50)
        price_r = draw_text(surface, fmt_money(tween("tut_aapl", price, 10)), tutorial_value, C("INK"), card.x + 96, card.y + 74)
        chg_r = draw_text(surface, f"Today  {change:+.2f}%", tutorial_label, C("GREEN") if change >= 0 else C("RED"), card.x + 96, card.y + 108)
        chart = pygame.Rect(card.x + 22, card.y + 146, card.w - 44, max(60, card.h - 146 - 120))
        draw_mini_chart(surface, hist, hist[-1] >= hist[0], chart.x, chart.y, chart.w, chart.h)
        if tutorial_demo["quote_opened"]:
            t = now - tutorial_demo.get("quote_time", now)
            _callout(surface, "Price right now", (price_r.right + 4, price_r.centery), (card.right - 70, card.y + 62), ease_out_cubic(t / 0.4))
            _callout(surface, "Today's move", (chg_r.right + 4, chg_r.centery), (card.right - 70, card.y + 112), ease_out_cubic((t - 0.25) / 0.4))
            mid = (chart.centerx, chart.centery)
            _callout(surface, "Recent trend", mid, (chart.centerx, chart.y - 4), ease_out_cubic((t - 0.5) / 0.4))
        tut_btn["market"] = pygame.Rect(card.x + 22, card.bottom - 62, card.w - 44, 44)
        opened = tutorial_demo["quote_opened"]
        draw_button(surface, tut_btn["market"], "Quote explained" if opened else "Open AAPL quote",
                    C("GREEN") if opened else C("INK"), C("CARD"), font=tutorial_button, radius=12)
        if not opened:
            pointer = "market"

    elif kind == "buysell":
        if now - tutorial_demo["last_tick"] > TUTORIAL_TICK_SECONDS:
            tutorial_demo["last_tick"] = now
            drift = random.uniform(-0.004, 0.0048)
            tutorial_demo["demo_price"] = round(max(5, tutorial_demo["demo_price"] * (1 + drift)), 2)
            tutorial_demo["demo_history"].append(tutorial_demo["demo_price"])
            tutorial_demo["demo_history"] = tutorial_demo["demo_history"][-32:]
            tutorial_demo["tick"] = tutorial_demo.get("tick", 0) + 1
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        draw_text(surface, "PRACTICE TRADE", tutorial_kicker, C("PURPLE"), card.x + 22, card.y + 20)
        draw_ticker_badge(surface, "DEMO", card.x + 22, card.y + 48, size=52)
        draw_text(surface, "Practice Stock", tutorial_body_bold, C("INK"), card.x + 90, card.y + 48)
        flash, went_up = price_flash("tut_demo", tutorial_demo["demo_price"], 0.6, min_move=0.0)
        pr = pygame.Rect(card.x + 86, card.y + 70, tutorial_value.size(fmt_money(tutorial_demo["demo_price"]))[0] + 10, 32)
        if flash > 0:
            draw_alpha_rect(surface, pr, C("GREEN") if went_up else C("RED"), 55 * flash, radius=8)
        draw_text(surface, fmt_money(tutorial_demo["demo_price"]), tutorial_value, C("INK"), card.x + 90, card.y + 72)
        hist = tutorial_demo["demo_history"]
        chart = pygame.Rect(card.x + 22, card.y + 124, card.w - 44, max(56, card.h - 124 - 150))
        pts = draw_mini_chart(surface, hist, hist[-1] >= hist[0], chart.x, chart.y, chart.w, chart.h,
                              anim_key="tut_demo_chart", tick_at=tutorial_demo["last_tick"], tick_len=TUTORIAL_TICK_SECONDS)
        tick = tutorial_demo.get("tick", 0)
        for key, col, letter in (("buy_tick", C("GREEN"), "B"), ("sell_tick", C("RED"), "S")):
            t = tutorial_demo.get(key)
            if t is None:
                continue
            i = len(hist) - 1 - (tick - t)
            if 0 <= i < len(pts) and pts[i]:
                px, py = pts[i]
                pygame.draw.circle(surface, C("CARD"), (px, py - 16), 10)
                pygame.draw.circle(surface, col, (px, py - 16), 9)
                pygame.draw.line(surface, col, (px, py - 7), (px, py - 2), 2)
                draw_text(surface, letter, font_tiny, text_on(col), px, py - 24, align="center")
        owned = tutorial_demo["owned_shares"]
        status_y = chart.bottom + 14
        if owned:
            pnl = (tutorial_demo["demo_price"] - tutorial_demo["avg_buy"]) * owned
            shown = tween("tut_pnl", pnl, 12)
            draw_text(surface, "YOU OWN 1 SHARE  •  LIVE P&L", font_tiny, C("GRAY"), card.centerx, status_y, align="center")
            draw_text(surface, f"{'+' if shown >= 0 else '-'}{fmt_money(abs(shown))}", tutorial_value, C("GREEN") if pnl >= 0 else C("RED"), card.centerx, status_y + 16, align="center")
        elif tutorial_demo["last_pnl"] is not None:
            lp = tutorial_demo["last_pnl"]
            draw_text(surface, "TRADE CLOSED  •  RESULT", font_tiny, C("GRAY"), card.centerx, status_y, align="center")
            draw_text(surface, f"{'+' if lp >= 0 else '-'}{fmt_money(abs(lp))}", tutorial_value, C("GREEN") if lp >= 0 else C("RED"), card.centerx, status_y + 16, align="center")
        else:
            draw_text(surface, "Buy once  •  watch the price  •  sell once", tutorial_label, C("GRAY"), card.centerx, status_y + 10, align="center")
        by = card.bottom - 62
        bw = (card.w - 56) // 2
        tut_btn["buy"] = pygame.Rect(card.x + 22, by, bw, 46)
        tut_btn["sell"] = pygame.Rect(tut_btn["buy"].right + 12, by, bw, 46)
        done = tutorial_demo["last_pnl"] is not None and not owned
        draw_button(surface, tut_btn["buy"], "Buy 1" if owned == 0 else "Bought", C("GREEN") if owned == 0 else C("PANEL_BG"), C("CARD") if owned == 0 else C("GREEN"), font=tutorial_button, radius=12)
        draw_button(surface, tut_btn["sell"], "Sell 1", C("RED") if owned else C("PANEL_BG"), C("CARD") if owned else C("GRAY"), font=tutorial_button, radius=12)
        if not done:
            pointer = "sell" if owned else "buy"

    elif kind == "portfolio":
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        draw_text(surface, "PRACTICE PORTFOLIO", tutorial_kicker, C("PURPLE"), card.x + 22, card.y + 20)
        opened = tutorial_demo["portfolio_opened"]
        slices = [("Cash", 600.0, C("GREEN")), ("AAPL", 250.0, brand_colors("AAPL")[0]), ("NKE", 150.0, brand_colors("NKE")[0])]
        total = sum(v for _, v, _ in slices)
        r_out = min(78, (card.h - 170) // 2)
        center = (card.x + 22 + r_out, card.y + 60 + r_out)
        prog = ease_out_cubic((now - tutorial_demo.get("portfolio_time", now)) / 0.9) if opened else 0.0
        pygame.draw.circle(surface, C("PANEL_BG"), center, r_out)
        pygame.draw.circle(surface, C("CARD"), center, int(r_out * 0.62))
        if opened:
            draw_donut(surface, center, r_out, int(r_out * 0.62), [(v / total, col) for _, v, col in slices], prog)
            draw_text(surface, "TOTAL", font_tiny, C("GRAY"), center[0], center[1] - 18, align="center")
            draw_text(surface, fmt_money(total * prog), font_body_bold, C("INK"), center[0], center[1] - 2, align="center")
            lx = center[0] + r_out + 22
            for i, (label, value, col) in enumerate(slices):
                ly = card.y + 66 + i * 44
                pygame.draw.rect(surface, col, (lx, ly + 4, 12, 12), border_radius=3)
                draw_text(surface, label, font_small_bold, C("INK"), lx + 20, ly)
                draw_text(surface, f"{fmt_money(value)}  •  {value / total * 100:.0f}%", font_tiny, C("GRAY"), lx + 20, ly + 19)
            lp = tutorial_demo["last_pnl"]
            note = (f"Your practice trade made {'+' if lp >= 0 else '-'}{fmt_money(abs(lp))}. The Portfolio tab tracks every result."
                    if lp is not None else "The Portfolio tab tracks cash, holdings and profit/loss.")
            for i, line in enumerate(wrap_text(note, font_small, card.w - 44)[:2]):
                draw_text(surface, line, font_small, C("GRAY"), card.x + 22, card.bottom - 116 + i * 19)
        else:
            draw_text(surface, "?", tutorial_title, C("LIGHT_GRAY"), center[0], center[1] - 20, align="center")
            draw_text(surface, "What's inside?", tutorial_body_bold, C("INK"), center[0] + r_out + 22, center[1] - 30)
            draw_text(surface, "Open it to see how your", font_small, C("GRAY"), center[0] + r_out + 22, center[1] - 4)
            draw_text(surface, "money is split up.", font_small, C("GRAY"), center[0] + r_out + 22, center[1] + 14)
        tut_btn["portfolio"] = pygame.Rect(card.x + 22, card.bottom - 62, card.w - 44, 44)
        draw_button(surface, tut_btn["portfolio"], "Portfolio opened" if opened else "Open practice portfolio",
                    C("GREEN") if opened else C("INK"), C("CARD"), font=tutorial_button, radius=12)
        if not opened:
            pointer = "portfolio"

    elif kind == "news":
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        draw_text(surface, "MARKET NEWS", tutorial_kicker, C("PURPLE"), card.x + 22, card.y + 20)
        pill = pygame.Rect(card.right - 104, card.y + 16, 82, 22)
        blink = 0.6 + 0.4 * math.sin(now * 5)
        draw_rounded_rect(surface, pill, mix_color(C("RED"), C("CARD"), 1 - blink), radius=11, shadow=False)
        draw_text(surface, "BREAKING", font_tiny, (255, 255, 255), pill.centerx, pill.y + 4, align="center")
        draw_ticker_badge(surface, "AAPL", card.x + 22, card.y + 48, size=36)
        draw_text(surface, "Apple reports results and", tutorial_body_bold, C("INK"), card.x + 70, card.y + 48)
        draw_text(surface, "updates its outlook", tutorial_body_bold, C("INK"), card.x + 70, card.y + 72)
        if not tutorial_demo["news_read"]:
            draw_text(surface, "A headline is information, not a guarantee.", font_small, C("GRAY"), card.x + 22, card.y + 116, max_width=card.w - 44)
            tut_btn["news_read"] = pygame.Rect(card.x + 22, card.bottom - 62, card.w - 44, 44)
            draw_button(surface, tut_btn["news_read"], "Read the story", C("INK"), C("CARD"), font=tutorial_button, radius=12)
            pointer = "news_read"
        else:
            story = "Sales grew, but the company expects a slower next quarter. The stock is moving fast."
            shown = int((now - tutorial_demo.get("news_time", now)) * 70)
            y = card.y + 108
            for line in wrap_text(story, font_small, card.w - 44)[:3]:
                draw_text(surface, line[:max(0, shown)], font_small, C("GRAY"), card.x + 22, y)
                shown -= len(line) + 1
                y += 19
            choice = tutorial_demo.get("news_choice")
            if choice is None or choice == 2:
                q, qcol = "What should a careful trader do?", C("INK")
            else:
                q, qcol = "Too fast! One headline isn't enough. Try again.", C("RED")
            draw_text(surface, q, tutorial_label, qcol, card.x + 22, y + 10, max_width=card.w - 44)
            options = ["Sell everything right now!", "Buy as much as I can!", "Read the details, then decide"]
            for i, label in enumerate(options):
                r = pygame.Rect(card.x + 22, card.bottom - 62 - (2 - i) * 50, card.w - 44, 42)
                tut_btn[f"news_choice_{i}"] = r
                if choice == i:
                    bg, fg = (C("GREEN"), C("CARD")) if i == 2 else (C("RED"), C("CARD"))
                else:
                    bg, fg = C("PANEL_BG"), C("INK")
                draw_button(surface, r, label, bg, fg, font=tutorial_button, radius=12)

    elif kind == "risk":
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        draw_text(surface, "RISK CHECK", tutorial_kicker, C("PURPLE"), card.x + 22, card.y + 20)
        draw_text(surface, "You have $1,000. Pick a portfolio:", tutorial_body_bold, C("INK"), card.x + 22, card.y + 44, max_width=card.w - 44)
        choice = tutorial_demo.get("risk_choice")
        t = now - tutorial_demo.get("risk_time", now) if choice else 0.0
        shock = ease_out_cubic((t - 0.5) / 0.9) if choice else 0.0
        tile_w = (card.w - 44 - 12) // 2
        tile_h = max(150, min(230, card.h - 160))
        tiles = [("a", "All in one stock", [1.0]), ("b", "Spread across 5", [0.2] * 5)]
        for i, (key, label, weights) in enumerate(tiles):
            tile = pygame.Rect(card.x + 22 + i * (tile_w + 12), card.y + 80, tile_w, tile_h)
            tut_btn[f"risk_{key}"] = tile
            picked = choice == key
            border = (C("GREEN") if key == "b" else C("RED")) if picked else C("BORDER")
            draw_rounded_rect(surface, tile, C("PANEL_BG"), radius=16, border_color=border, border_width=3 if picked else 1, shadow=False)
            draw_text(surface, label, font_small_bold, C("INK"), tile.centerx, tile.y + 10, align="center")
            bars_area = pygame.Rect(tile.x + 14, tile.y + 38, tile.w - 28, tile.h - 84)
            n = len(weights)
            bw = (bars_area.w - (n - 1) * 6) / n
            value = 0.0
            for j, wgt in enumerate(weights):
                drop = 0.4 * shock if (j == 0 and choice) else 0.0
                h = bars_area.h * (1 - drop) * (1.0 if n == 1 else 0.85)
                col = mix_color(C("PURPLE"), C("RED"), shock) if (j == 0 and choice) else C("PURPLE")
                pygame.draw.rect(surface, col, (bars_area.x + j * (bw + 6), bars_area.bottom - h, bw, h), border_radius=5)
                value += 1000 * wgt * (1 - drop)
            draw_text(surface, fmt_money(value), font_body_bold, C("RED") if value < 999 else C("INK"), tile.centerx, tile.bottom - 38, align="center")
            if choice:
                draw_text(surface, f"-{fmt_money(1000 - value)}", font_tiny, C("RED"), tile.centerx, tile.bottom - 18, align="center")
        msg_y = card.y + 80 + tile_h + 12
        if not choice:
            draw_text(surface, "Tap the one you think is safer.", font_small, C("GRAY"), card.centerx, msg_y, align="center")
        else:
            draw_text(surface, "Surprise! One company's stock drops 40%.", font_small_bold, C("ORANGE"), card.centerx, msg_y, align="center")
            if shock >= 0.99:
                if choice == "b":
                    msg, col = "Spread out lost $80 instead of $400. Diversification!", C("GREEN")
                else:
                    msg, col = "Ouch! All-in lost $400. Try the other portfolio.", C("RED")
                draw_text(surface, msg, font_small, col, card.centerx, msg_y + 22, align="center", max_width=card.w - 30)

    elif kind == "duel":
        draw_rounded_rect(surface, card, (24, 24, 30), radius=24)
        draw_text(surface, "PRACTICE ARENA", tutorial_kicker, (255, 215, 0), card.centerx, card.y + 20, align="center")
        started = tutorial_demo.get("duel_started")
        done = tutorial_demo["duel_progress"] >= 1.0
        if started and not done:
            tutorial_demo["bot_progress"] = min(0.82, (now - started) * 0.05)
        you = tween("tut_duel_you", tutorial_demo["duel_progress"], 10)
        bot = tutorial_demo.get("bot_progress", 0.0)
        for i, (label, prog, col, char) in enumerate((("YOU", you, C("GREEN"), state.avatar), ("TRAINER BOT", bot, (120, 120, 135), None))):
            y = card.y + 58 + i * 74
            if char is not None:
                draw_avatar_icon(surface, char, (card.x + 42, y + 22), size=40, dark=True)
            else:
                bot_box = pygame.Rect(card.x + 22, y + 2, 40, 40)
                draw_rounded_rect(surface, bot_box, (60, 60, 72), radius=12, shadow=False)
                pygame.draw.circle(surface, (255, 90, 90), (bot_box.centerx - 7, bot_box.centery), 4)
                pygame.draw.circle(surface, (255, 90, 90), (bot_box.centerx + 7, bot_box.centery), 4)
            draw_text(surface, label, tutorial_label, (255, 255, 255), card.x + 74, y)
            bar = pygame.Rect(card.x + 74, y + 24, card.w - 96, 16)
            pygame.draw.rect(surface, (60, 60, 70), bar, border_radius=8)
            if prog > 0.01:
                pygame.draw.rect(surface, col, (bar.x, bar.y, max(16, int(bar.w * prog)), bar.h), border_radius=8)
        if done:
            draw_text(surface, "YOU WIN!", tutorial_title, (255, 215, 0), card.centerx, card.y + 212, align="center")
        else:
            draw_text(surface, "Each smart trade moves your bar. Race the bot!", font_small, (205, 205, 215), card.centerx, card.y + 214, align="center", max_width=card.w - 40)
        tut_btn["duel"] = pygame.Rect(card.x + 22, card.bottom - 62, card.w - 44, 46)
        draw_button(surface, tut_btn["duel"], "Duel won" if done else "Make a smart trade", C("GREEN") if done else C("ORANGE"), C("CARD"), font=tutorial_button, radius=12)
        if not done:
            pointer = "duel"

    elif kind == "realtrade":
        draw_rounded_rect(surface, card, C("CARD"), radius=24, border_color=C("BORDER"), border_width=1)
        aapl = find_asset("AAPL")
        price = float(aapl.get("price", 100.0)) if aapl else 100.0
        hist = list(aapl.get("history", [])) if aapl else []
        if len(hist) < 8 or max(hist) == min(hist):
            hist = _demo_history("quote_history", price)
        draw_text(surface, "YOUR FIRST REAL-GAME TRADE", tutorial_kicker, C("PURPLE"), card.x + 22, card.y + 20)
        draw_ticker_badge(surface, "AAPL", card.x + 22, card.y + 50, size=56)
        draw_text(surface, "Apple", tutorial_body_bold, C("INK"), card.x + 94, card.y + 50)
        draw_text(surface, fmt_money(price), tutorial_value, C("INK"), card.x + 94, card.y + 74)
        chart = pygame.Rect(card.x + 22, card.y + 128, card.w - 44, max(50, card.h - 128 - 150))
        draw_mini_chart(surface, hist, hist[-1] >= hist[0], chart.x, chart.y, chart.w, chart.h)
        done = state.holdings.get("AAPL", 0) >= 0.25
        info_y = chart.bottom + 14
        draw_text(surface, f"0.25 share costs about {fmt_money(price * 0.25)}", font_small, C("GRAY"), card.x + 22, info_y)
        draw_text(surface, f"Cash available  {fmt_money(tween('tut_cash', state.cash, 8))}", tutorial_label, C("PURPLE"), card.x + 22, info_y + 22)
        if done:
            draw_text(surface, f"You own {state.holdings.get('AAPL', 0):g} AAPL", tutorial_label, C("GREEN"), card.right - 22, info_y + 22, align="right")
        tut_btn["realtrade"] = pygame.Rect(card.x + 22, card.bottom - 62, card.w - 44, 46)
        draw_button(surface, tut_btn["realtrade"], "Trade placed" if done else "Buy 0.25 share of AAPL",
                    C("GREEN") if done else C("INK"), C("CARD"), font=tutorial_button, radius=12)
        if not done:
            pointer = "realtrade"

    elif kind == "ready":
        draw_rounded_rect(surface, card, C("CARD"), radius=26, border_color=C("BORDER"), border_width=1)
        draw_text(surface, "MISSION ACCOMPLISHED", tutorial_kicker, C("PURPLE"), card.centerx, card.y + 20, align="center")
        stage_h = max(140, min(210, card.h - 190))
        stage = pygame.Rect(card.x + 16, card.y + 46, card.w - 32, stage_h)
        draw_rounded_rect(surface, stage, C("PANEL_BG"), radius=22, shadow=False)
        glow = HiSurface(stage.size, pygame.SRCALPHA)
        pygame.draw.circle(glow, (*C("PURPLE"), 30), (stage.w // 2, stage.h // 2 + 10), int(stage.h * 0.45 + 6 * math.sin(now * 2)))
        surface.blit(glow, stage.topleft)
        draw_character(surface, state.avatar, stage.centerx, stage.y + int(stage_h * 0.56), scale=min(2.3, stage_h / 90.0), animate=True)
        player_name = (getattr(state, "player_name", "") or "Trader").strip()
        if len(player_name) > 22:
            player_name = player_name[:21].rstrip() + "…"
        ty = stage.bottom + 12
        draw_text(surface, f"You're ready, {player_name}!", tutorial_body_bold, C("INK"), card.centerx, ty, align="center", max_width=card.w - 36)
        tiles = [("market", "Research"), ("portfolio", "Trade"), ("home", "Monitor"), ("academy", "Learn")]
        tw = (card.w - 32 - 3 * 8) // 4
        for i, (icon, label) in enumerate(tiles):
            r = pygame.Rect(card.x + 16 + i * (tw + 8), ty + 34, tw, 58)
            pop = ease_out_cubic((now - _tutorial_coach["start"] - 0.2 - i * 0.12) / 0.35)
            if pop <= 0:
                continue
            r = r.move(0, int(10 * (1 - pop)))
            draw_rounded_rect(surface, r, C("PURPLE_BG"), radius=12, shadow=False)
            draw_tab_icon(surface, icon, r.centerx, r.y + 20, C("PURPLE"))
            draw_text(surface, label, font_tiny, C("INK"), r.centerx, r.y + 36, align="center")

    return pointer


def _tutorial_step_events(idx, kind, complete):
    """One-time reactions: greet on entry, celebrate when a mission is finished."""
    seen = tutorial_demo.setdefault("seen", set())
    if idx not in seen:
        seen.add(idx)
        if kind == "welcome":
            avatar_emote("wave")
        elif kind == "ready":
            spawn_confetti(90)
            play_sound("victory")
            avatar_emote("dance")
            avatar_set_mood("excited", 4)
    done = tutorial_demo.setdefault("celebrated", set())
    if complete and idx not in done:
        done.add(idx)
        if kind not in ("welcome", "ready"):
            tutorial_demo["celebrate_at"] = time.time()
            spawn_confetti(45)
            play_sound("achievement")
            avatar_emote("cheer")
            avatar_set_mood("excited", 3)


def _draw_tutorial_page(surface, step, complete, now, bottom):
    idx = state.tutorial_index
    kind = step["kind"]
    title_lines = wrap_text(step["title"], tutorial_title, WIDTH - 60)[:2]
    ty = 52
    for line in title_lines:
        draw_text(surface, line, tutorial_title, C("INK"), WIDTH // 2, ty, align="center", max_width=WIDTH - 60)
        ty += 36

    # Coach: your avatar explains each step in a speech bubble.
    if complete and kind in TUTORIAL_DONE_LINES:
        text, text_col = TUTORIAL_DONE_LINES[kind], C("GREEN")
    else:
        text, text_col = step["body"], C("INK")
    key = (idx, text)
    if _tutorial_coach["key"] != key:
        _tutorial_coach["key"] = key
        _tutorial_coach["start"] = now
    typed = int((now - _tutorial_coach["start"]) * 65)
    if typed < len(text):
        avatar_anim["talking_until"] = now + 0.15
    coach_y = ty + 8
    bob = math.sin(now * 2.2) * 2
    avatar_box = pygame.Rect(18, coach_y + bob, 58, 58)
    draw_rounded_rect(surface, avatar_box, C("PURPLE_BG"), radius=29, border_color=C("PURPLE"), border_width=2)
    draw_avatar_icon(surface, state.avatar, avatar_box.center, size=50)
    lines = wrap_text(text, font_small, WIDTH - 88 - 18 - 28)[:4]
    bubble = pygame.Rect(88, coach_y, WIDTH - 88 - 18, max(58, 18 + len(lines) * 19))
    draw_rounded_rect(surface, bubble, C("CARD"), radius=14, border_color=C("BORDER"), border_width=1)
    pygame.draw.polygon(surface, C("CARD"), [(bubble.x + 1, coach_y + 18), (bubble.x - 9, coach_y + 27), (bubble.x + 1, coach_y + 34)])
    pygame.draw.lines(surface, C("BORDER"), False, [(bubble.x, coach_y + 18), (bubble.x - 9, coach_y + 27), (bubble.x, coach_y + 34)], 1)
    ly = bubble.y + 9
    remaining = typed
    for line in lines:
        if remaining <= 0:
            break
        draw_text(surface, line[:remaining], font_small, text_col, bubble.x + 14, ly, max_width=bubble.w - 20)
        remaining -= len(line) + 1
        ly += 19

    # Goal row with a checkbox that ticks when the mission is done.
    goal_rect = pygame.Rect(18, max(bubble.bottom, avatar_box.bottom) + 10, WIDTH - 36, 38)
    bg = mix_color(C("GREEN"), C("CARD"), 0.86) if complete else C("PURPLE_BG")
    draw_rounded_rect(surface, goal_rect, bg, radius=12, border_color=C("GREEN") if complete else C("PURPLE"), border_width=1, shadow=False)
    check_c = (goal_rect.x + 20, goal_rect.centery)
    if complete:
        pop = tween(("tut_check", idx), 1.0, 14)
        draw_check(surface, check_c, max(2, int(10 * pop)), C("GREEN"))
    else:
        tween(("tut_check", idx), 0.0, 100)
        pygame.draw.circle(surface, C("PURPLE"), check_c, 9, 2)
    draw_text(surface, "GOAL", font_tiny, C("GREEN") if complete else C("PURPLE"), goal_rect.x + 38, goal_rect.y + 11)
    draw_text(surface, step.get("goal", "Complete the activity"), font_small_bold, C("INK"), goal_rect.x + 80, goal_rect.y + 10, max_width=goal_rect.w - 92)

    demo_area = pygame.Rect(0, goal_rect.bottom + 10, WIDTH, max(200, bottom - goal_rect.bottom - 10))
    pointer = draw_tutorial_demo(surface, kind, demo_area)
    if pointer and tut_btn.get(pointer):
        draw_tap_hint(surface, tut_btn[pointer], now)

    # "Mission complete" stamp pops in over the activity.
    t = now - tutorial_demo.get("celebrate_at", -10)
    if 0 <= t < 1.8 and kind not in ("welcome", "ready"):
        pop = ease_out_cubic(t / 0.3)
        fade = 1.0 if t < 1.3 else max(0.0, 1 - (t - 1.3) / 0.5)
        w = int(220 * (0.6 + 0.4 * pop))
        stamp = pygame.Rect(0, 0, w, 44)
        stamp.center = (WIDTH // 2, demo_area.y + 40)
        layer = HiSurface((stamp.w + 20, stamp.h + 20), pygame.SRCALPHA)
        pygame.draw.rect(layer, (*C("GREEN"), 255), (10, 10, stamp.w, stamp.h), border_radius=22)
        layer.set_alpha(int(255 * fade))
        surface.blit(layer, (stamp.x - 10, stamp.y - 10))
        if pop > 0.8 and fade > 0.3:
            draw_check(surface, (stamp.x + 26, stamp.centery), 10, (255, 255, 255), C("GREEN"))
            draw_text(surface, "MISSION COMPLETE", font_small_bold, text_on(C("GREEN")), stamp.centerx + 12, stamp.y + 12, align="center")


def draw_tutorial_screen(surface):
    global tutorial_next_btn, tutorial_skip_btn
    now = time.time()
    draw_app_background(surface)
    idx = state.tutorial_index
    step = TUTORIAL_STEPS[idx]
    n = len(TUTORIAL_STEPS)
    complete = tutorial_goal_complete()
    _tutorial_step_events(idx, step["kind"], complete)
    footer_top = HEIGHT - 76

    # Segmented progress bar: finished missions fill in, the current one breathes.
    gap = 4
    seg_w = (WIDTH - 48 - gap * (n - 1)) / n
    for i in range(n):
        r = pygame.Rect(int(24 + i * (seg_w + gap)), 16, int(seg_w), 6)
        pygame.draw.rect(surface, C("BORDER"), r, border_radius=3)
        target = 1.0 if (i < idx or (i == idx and complete)) else (0.35 + 0.1 * math.sin(now * 3) if i == idx else 0.0)
        fill = tween(("tut_seg", i), target, 8)
        if fill > 0.02:
            pygame.draw.rect(surface, C("PURPLE"), (r.x, r.y, max(6, int(r.w * fill)), r.h), border_radius=3)
    draw_text(surface, f"MISSION {idx + 1} OF {n}", font_tiny, C("GRAY"), 24, 28)
    draw_text(surface, "Paper money only", font_tiny, C("GREEN"), WIDTH - 24, 28, align="right")

    page = pygame.Rect(0, 44, WIDTH, footer_top - 44 - 6)
    draw_with_slide(surface, "tutorial_page", idx, page,
                    lambda: _draw_tutorial_page(surface, step, complete, now, footer_top - 8))

    tutorial_next_btn = pygame.Rect(24, footer_top, WIDTH - 48, 52)
    last = idx == n - 1
    if complete:
        glow = 0.5 + 0.5 * math.sin(now * 3)
        draw_alpha_rect(surface, tutorial_next_btn.inflate(10, 10), C("GREEN") if last else C("PURPLE"), 40 + 40 * glow, radius=18)
        draw_button(surface, tutorial_next_btn, "Let's Start Trading" if last else "Continue",
                    C("GREEN") if last else C("INK"), C("CARD"), font=tutorial_button, radius=16)
    else:
        draw_button(surface, tutorial_next_btn, "Finish the goal to continue", C("PANEL_BG"), C("LIGHT_GRAY"), font=tutorial_button, radius=16)
    tutorial_skip_btn = None


def handle_tutorial_demo_click(pos, kind):
    def hit(key):
        r = tut_btn.get(key)
        return r is not None and r.collidepoint(pos)

    if kind == "welcome" and hit("avatar"):
        tutorial_demo["poked"] = True
        avatar_emote(random.choice(POKE_EMOTES))
        spawn_money_burst(pos[0], pos[1], 5, 7)
        avatar_set_mood("happy", 2)
        spawn_sparks(pos[0], pos[1], C("PURPLE"), 10)
        play_sound("click")
    elif kind == "market" and hit("market") and not tutorial_demo["quote_opened"]:
        tutorial_demo["quote_opened"] = True
        tutorial_demo["quote_time"] = time.time()
        play_sound("click")
        spawn_sparks(pos[0], pos[1], C("PURPLE"), 8)
    elif kind == "buysell":
        if hit("buy") and tutorial_demo["owned_shares"] == 0:
            tutorial_demo["avg_buy"] = tutorial_demo["demo_price"]
            tutorial_demo["owned_shares"] = 1
            tutorial_demo["buy_tick"] = tutorial_demo.get("tick", 0)
            tutorial_demo["sell_tick"] = None
            play_sound("trade")
            avatar_emote("nod")
            spawn_sparks(pos[0], pos[1], C("GREEN"), 10)
        elif hit("sell") and tutorial_demo["owned_shares"] > 0:
            tutorial_demo["last_pnl"] = tutorial_demo["demo_price"] - tutorial_demo["avg_buy"]
            tutorial_demo["owned_shares"] = 0
            tutorial_demo["sell_tick"] = tutorial_demo.get("tick", 0)
            play_sound("trade")
            spawn_cash_text(tutorial_demo["last_pnl"], pos[0], pos[1] - 40)
    elif kind == "portfolio" and hit("portfolio") and not tutorial_demo["portfolio_opened"]:
        tutorial_demo["portfolio_opened"] = True
        tutorial_demo["portfolio_time"] = time.time()
        play_sound("click")
    elif kind == "news":
        if hit("news_read"):
            tutorial_demo["news_read"] = True
            tutorial_demo["news_time"] = time.time()
            play_sound("click")
            return
        for i in range(3):
            if hit(f"news_choice_{i}") and not tutorial_demo["news_answered"]:
                tutorial_demo["news_choice"] = i
                if i == 2:
                    tutorial_demo["news_answered"] = True
                    spawn_sparks(pos[0], pos[1], C("GREEN"), 12)
                else:
                    play_sound("error")
                    avatar_emote("shrug")
    elif kind == "risk":
        for key in ("a", "b"):
            if hit(f"risk_{key}") and not tutorial_demo["risk_correct"]:
                tutorial_demo["risk_choice"] = key
                tutorial_demo["risk_time"] = time.time()
                tutorial_demo["risk_answered"] = True
                tutorial_demo["risk_correct"] = key == "b"
                if key == "a":
                    play_sound("error")
                    avatar_emote("shrug")
                else:
                    play_sound("click")
    elif kind == "duel" and hit("duel") and tutorial_demo["duel_progress"] < 1.0:
        tutorial_demo.setdefault("duel_started", None)
        if not tutorial_demo["duel_started"]:
            tutorial_demo["duel_started"] = time.time()
        tutorial_demo["duel_ticks"] += 1
        tutorial_demo["duel_progress"] = min(1.0, tutorial_demo["duel_progress"] + 0.20)
        play_sound("trade")
        spawn_sparks(pos[0], pos[1], C("ORANGE"), 12)
        floating_texts.append(FloatingText(pos[0], pos[1] - 30, random.choice(["Bought low!", "Nice timing!", "Smart!", "Sold high!"]), C("GREEN")))
    elif kind == "realtrade" and hit("realtrade"):
        aapl = find_asset("AAPL")
        if aapl and state.holdings.get("AAPL", 0) < 0.25:
            do_buy(aapl, 0.25)
            state.lesson = "Your first trade is now in your actual Ledger portfolio. Research, trade, monitor and learn."
            save_game()


def handle_tutorial_click(pos):
    step = TUTORIAL_STEPS[state.tutorial_index]
    if tutorial_next_btn and tutorial_next_btn.collidepoint(pos):
        if not tutorial_goal_complete():
            play_sound("error")
            state.lesson = "Finish the mission above before moving on. This practice is part of the game."
            return
        play_sound("click")
        if state.tutorial_index >= len(TUTORIAL_STEPS) - 1:
            state.screen_mode = "playing"
            if not getattr(state, "tutorial_completed", False):
                state.tutorial_completed = True
                add_xp(100)
                state.lesson = "You are ready. The same Market, Portfolio, News and Arena systems you practiced are now live."
                state.last_tick = 0.0
                state.live_last_refresh = 0.0
                state.live_last_news_refresh = 0.0
                state.live_started_at = time.time()
                state.live_first_quote_received = False
                request_live_price_refresh(force=True)
                request_live_news_refresh(force=True)
                save_game()
        else:
            state.tutorial_index += 1
        return
    handle_tutorial_demo_click(pos, step["kind"])

def draw_header(surface):
    global header_avatar_rect, header_trophy_rect
    if is_full_tab():
        draw_game_hud(surface)
        return

    pygame.draw.rect(surface, C("BG"), (0, 0, WIDTH, 192))
    header_avatar_rect = pygame.Rect(18, 12, 32, 32)
    draw_rounded_rect(surface, header_avatar_rect, C("PANEL_BG"), radius=16, border_color=C("BORDER"), border_width=1)
    if avatar_anim["pulse"] > 0:
        rad = int(16 + 8 * (1 - avatar_anim["pulse"]))
        ring = HiSurface((rad * 2 + 6, rad * 2 + 6), pygame.SRCALPHA)
        pygame.draw.circle(ring, (*C("PURPLE"), int(120 * avatar_anim["pulse"])), (rad + 3, rad + 3), rad, 2)
        surface.blit(ring, (header_avatar_rect.centerx - rad - 3, header_avatar_rect.centery - rad - 3))
    draw_avatar_icon(surface, state.avatar, header_avatar_rect.center, size=30, selected=avatar_anim["pulse"] > 0)
    draw_avatar_frame(surface, header_avatar_rect.center, 16, equipped("frame")["id"])
    draw_text(surface, f"{state.player_name}", font_body_bold, C("INK"), 58, 8, max_width=150)
    tchip = draw_title_chip(surface, 58, 27, equipped("title")["id"])
    lvr = draw_text(surface, f"Lv {state.level}", font_tiny, C("GOLD") if unclaimed_levels() else C("GRAY"), tchip.right + 8, 28)
    global header_level_rect
    header_level_rect = pygame.Rect(58, 26, lvr.right - 58 + 6, 20)
    if unclaimed_levels():
        pygame.draw.circle(surface, SG_GREEN, (lvr.right + 5, lvr.y + 3), 4)

    req_xp = state.level * 100
    xp_pct = min(1.0, state.xp / req_xp)
    pulse = 1 + (0.25 * state.xp_pulse)
    bar_w = int(90 * pulse)
    pygame.draw.rect(surface, C("PANEL_BG"), (58, 44, 110, 4), border_radius=2)
    xp_pct = tween("header_xp", xp_pct, 6.0)
    pygame.draw.rect(surface, C("PURPLE") if state.xp_pulse > 0 else C("GREEN"), (58, 44, max(0, int(110 * xp_pct)), 4), border_radius=2)

    league_name, league_icon, league_col = get_current_league()
    trophy_text = f"{league_icon} {state.trophies} Trophies"
    if state.win_streak >= 2:
        trophy_text += f"  • {state.win_streak} streak"
    badge_img = font_small_bold.render(trophy_text, True, league_col)
    badge_rect = pygame.Rect(WIDTH - 20 - badge_img.get_width() - 14, 14, badge_img.get_width() + 14, 26)
    header_trophy_rect = badge_rect
    global header_coin_rect
    coin_txt = f"{int(tween('coins_header', rewards_state().coins, 6)):,}"
    cw = font_small_bold.size(coin_txt)[0] + 34
    header_coin_rect = pygame.Rect(badge_rect.x - 8 - cw, 14, cw, 26)
    draw_rounded_rect(surface, header_coin_rect, C("CARD"), radius=13, border_color=C("BORDER"), border_width=1)
    draw_coin_icon(surface, header_coin_rect.x + 14, header_coin_rect.centery, 8)
    draw_text(surface, coin_txt, font_small_bold, C("INK"), header_coin_rect.x + 26, header_coin_rect.y + 5)
    rb = rewards_badge_count()
    if rb:
        draw_count_badge(surface, header_coin_rect.right - 2, header_coin_rect.y + 1, rb)
    draw_rounded_rect(surface, badge_rect, C("GOLD_BG"), radius=8, border_color=C("GOLD"), border_width=1)
    surface.blit(badge_img, (badge_rect.x + 7, badge_rect.y + 5))

    draw_text(surface, "Portfolio value", font_small, C("GRAY"), 20, 52)
    nw = tween("header_net_worth", net_worth(), 7.0)
    draw_text(surface, fmt_money(nw), font_large, C("INK"), 20, 68)
    gain = nw - STARTING_CASH
    gain_pct = (gain / STARTING_CASH) * 100
    gain_color = C("GREEN") if gain >= 0 else C("RED")
    sign = "+" if gain >= 0 else "-"
    draw_text(surface, f"{sign}{fmt_money(abs(gain))} ({sign}{abs(gain_pct):.1f}%)", font_body_bold, gain_color, 20, 108)
    secs_left = max(0, int(state.dividend_interval - (time.time() - state.last_dividend_time)))
    draw_text(surface, f"Payday: {secs_left}s", font_tiny, C("GRAY"), WIDTH - 20, 110, align="right")
    draw_mini_chart(surface, state.net_worth_history, gain >= 0, 20, 138, WIDTH - 40, 44, color=chart_skin_colors(gain >= 0),
                    anim_key="header_nw", tick_at=state.last_history_sample, tick_len=NET_WORTH_SAMPLE_SECONDS)
    pygame.draw.line(surface, C("BORDER"), (0, 192), (WIDTH, 192), 1)


TAB_BAR_HEIGHT = 62
CONTENT_TOP = 76   # every tab sits under the slim game HUD (same as GAME_TOP)
CONTENT_BOTTOM = HEIGHT - TAB_BAR_HEIGHT

market_row_rects = []
market_search_rect = None
market_clear_rect = None
portfolio_row_rects = []
settings_click_rects = {}
friend_add_btn_rect = None
friend_input_rect = None
news_trade_rects = []
header_avatar_rect = None
avatar_stage_rect = None


def clamp_scroll(tab_key, content_height):
    visible_h = CONTENT_BOTTOM - CONTENT_TOP
    max_scroll = max(0, content_height - visible_h)
    scroll_offset[tab_key] = max(0, min(scroll_offset[tab_key], max_scroll))


def filtered_assets():
    query = state.market_search.strip().lower()
    assets = all_assets()
    if not query:
        return assets
    return [a for a in assets if query in a.get("ticker", "").lower() or query in a.get("name", "").lower() or query in a.get("sector", "").lower()]


def select_asset_for_trade(asset):
    if asset_unlocked(asset):
        state.search_focus_ticker = asset["ticker"]
        open_modal(asset, "buy")
        play_sound("click")
    else:
        show_toast("Asset locked", f"Reach Level {asset.get('unlock_level', 1)} or {fmt_money(asset.get('unlock_worth', 0))} net worth.", "warning")


home_action_rects={}

home_anim = {"enter": 0.0, "last": 0.0}
home_hero_rect = None
home_chart_rect = None
# Colors are looked up at draw time (the SG_ palette is defined further down and colorblind mode swaps it).
HOME_ACTIONS = [("market", "Market", "SG_CYAN"), ("academy", "Learn", "SG_PURPLE"), ("news", "News", "SG_AMBER"),
                ("portfolio", "Portfolio", "SG_GREEN")]


def _home_greeting():
    h = time.localtime().tm_hour
    return "Good morning," if h < 12 else ("Good afternoon," if h < 18 else "Good evening,")


def _home_rise(i, now):
    """Staggered entrance: section i slides up into place when Home opens."""
    if getattr(state, "reduced_motion", False):
        return 0
    t = (now - home_anim["enter"] - i * 0.06) / 0.42
    return int((1 - ease_out_cubic(max(0.0, min(1.0, t)))) * 22)


def _home_hero(surface, card, now):
    """Portfolio hero: glow, drifting sparks, a shimmer sweep, count-up value and a live sparkline."""
    base = SG_PANEL
    pygame.draw.rect(surface, base, card, border_radius=22)
    daily = portfolio_daily_pnl()
    nw = net_worth()
    up_all = nw >= STARTING_CASH
    prev = surface.get_clip()
    surface.set_clip(prev)
    pygame.draw.rect(surface, SG_LINE, card, 1, border_radius=22)

    draw_text(surface, "Portfolio value", font_tiny, SG_MUTED, card.x + 18, card.y + 15)
    draw_text(surface, fmt_money(tween("header_net_worth", nw, 7.0)), font_large, SG_TEXT, card.x + 18, card.y + 34)
    col = SG_GREEN if daily >= 0 else SG_RED
    chip_t = f"Today {'+' if daily >= 0 else '-'}{fmt_money(abs(daily))}"
    cw = font_tiny.size(chip_t)[0] + 20
    chip = pygame.Rect(card.x + 18, card.y + 84, cw, 24)
    pygame.draw.rect(surface, mix_color(col, base, 0.78), chip, border_radius=12)
    draw_text(surface, chip_t, font_tiny, col, chip.centerx, chip.y + 4, align="center")
    all_pct = (nw - STARTING_CASH) / STARTING_CASH * 100
    all_t = f"{'+' if up_all else ''}{all_pct:.1f}% since start"
    draw_text(surface, all_t, font_tiny, SG_GREEN if up_all else SG_RED, chip.right + 10, chip.y + 4)
    draw_text(surface, f"Cash {fmt_money(state.cash)}", font_tiny, SG_MUTED, card.right - 18, card.y + 18, align="right")

    global home_chart_rect
    home_chart_rect = pygame.Rect(card.x + 12, card.y + 116, card.w - 24, card.h - 126)
    hist = state.net_worth_history[-60:] if len(state.net_worth_history) > 1 else [STARTING_CASH, nw]
    draw_mini_chart(surface, hist, up_all, home_chart_rect.x + 6, home_chart_rect.y + 4, home_chart_rect.w - 12,
                    home_chart_rect.h - 8, color=SG_GREEN if up_all else SG_RED, baseline=STARTING_CASH,
                    anim_key=("home", "nw"))


def draw_home_tab(surface):
    global home_action_rects, home_hero_rect
    home_action_rects = {}
    now = time.time()
    if now - home_anim["last"] > 0.4:
        home_anim["enter"] = now   # Home was just opened: replay the entrance
    home_anim["last"] = now
    mouse = pygame.mouse.get_pos()
    off = scroll_offset["home"]
    clip = pygame.Rect(0, GAME_TOP, WIDTH, CONTENT_BOTTOM - GAME_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y0 = GAME_TOP + 6 - off
    y = y0

    # Greeting + login streak.
    r = _home_rise(0, now)
    draw_text(surface, _home_greeting(), font_small, SG_MUTED, 20, y + r)
    draw_text(surface, state.player_name, font_sg_h2, SG_TEXT, 20, y + 18 + r, max_width=WIDTH - 150)
    streak = int(getattr(state, "login_streak", 0) or 0)
    st_t = f"{streak} day streak"
    sw = font_tiny.size(st_t)[0] + 40
    pill = pygame.Rect(WIDTH - 20 - sw, y + 20 + r, sw, 28)
    pygame.draw.rect(surface, mix_color(SG_AMBER, SG_BG, 0.82), pill, border_radius=14)
    draw_flame(surface, pill.x + 16, pill.centery, 0.9, lit=streak > 0)
    draw_text(surface, st_t, font_tiny, SG_AMBER, pill.x + 28, pill.y + 6)
    y += 60

    # Hero.
    home_hero_rect = pygame.Rect(20, y + _home_rise(1, now), WIDTH - 40, 196)
    _home_hero(surface, home_hero_rect, now)
    home_action_rects["portfolio_hero"] = home_hero_rect
    y += 196 + 16

    # Quick actions.
    r = _home_rise(2, now)
    gap = 10
    w = (WIDTH - 40 - gap * 3) // 4
    for i, (key, label, col_name) in enumerate(HOME_ACTIONS):
        col = globals()[col_name]
        tile = pygame.Rect(20 + i * (w + gap), y + r, w, 78)
        hov = tile.collidepoint(mouse) and clip.collidepoint(mouse)
        lift = int(tween(("home_tile", key), 3.0 if hov else 0.0, 14))
        face = tile.move(0, -lift)
        sg_panel(surface, face, 18, color=SG_PANEL_2 if hov else SG_PANEL)
        pygame.draw.circle(surface, mix_color(col, SG_PANEL, 0.75), (face.centerx, face.y + 28), 18)
        draw_tab_icon(surface, key, face.centerx, face.y + 28, col)
        draw_text(surface, label, font_tiny, SG_TEXT, face.centerx, face.y + 52, align="center", max_width=face.w - 8)
        badge = notification_counts().get(key, 0)
        if badge:
            draw_count_badge(surface, face.right - 12, face.y + 10, badge)
        home_action_rects[key] = tile
    y += 78 + 18

    # Today's mission.
    r = _home_rise(3, now)
    c = current_challenge()
    done = state.challenge_progress >= c["goal"]
    card = pygame.Rect(20, y + r, WIDTH - 40, 104)
    sg_panel(surface, card, 20)
    pygame.draw.rect(surface, SG_GOLD if done and not state.challenge_claimed else SG_LINE, card, 2 if done else 1, border_radius=20)
    draw_text(surface, "Today's mission", font_tiny, SG_MUTED, card.x + 18, card.y + 14)
    draw_text(surface, f"+{c['reward']} XP", font_tiny, SG_PURPLE, card.right - 18, card.y + 14, align="right")
    draw_text(surface, c["title"], font_body_bold, SG_TEXT, card.x + 18, card.y + 32, max_width=card.w - 150)
    draw_text(surface, c["desc"], font_tiny, SG_MUTED, card.x + 18, card.y + 54, max_width=card.w - 150)
    bar = pygame.Rect(card.x + 18, card.bottom - 22, card.w - 150, 8)
    pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=4)
    frac = tween("home_mission", min(1.0, state.challenge_progress / max(1, c["goal"])), 5)
    if frac > 0.01:
        pygame.draw.rect(surface, SG_GOLD, (bar.x, bar.y, max(8, int(bar.w * frac)), bar.h), border_radius=4)
    btn = pygame.Rect(card.right - 116, card.y + 40, 98, 40)
    if state.challenge_claimed:
        draw_check(surface, (btn.centerx, btn.centery), 16, SG_GREEN, SG_BG)
    elif done:
        glow = 0.5 + 0.5 * math.sin(now * 5)
        _sg_button(surface, btn, "claim", "Claim", mix_color(SG_GOLD, (255, 255, 255), 0.15 * glow), SG_INK,
                   font=font_small_bold, depth=4, btns=home_action_rects)
    else:
        draw_text(surface, f"{state.challenge_progress}/{c['goal']}", font_medium_bold, SG_TEXT, btn.centerx, btn.y + 8, align="center")
    y += 104 + 22

    # Watchlist, drawn with the exact same rows as the Market.
    r = _home_rise(4, now)
    draw_text(surface, "Your watchlist", font_medium_bold, SG_TEXT, 20, y + r)
    link = draw_text(surface, "See all", font_small_bold, SG_GOLD, WIDTH - 20, y + 4 + r, align="right")
    home_action_rects["see_watchlist"] = link.inflate(16, 12)
    y += 34
    watch = state.watchlist[:4] if state.watchlist else ["AAPL", "MSFT", "NVDA", "AMZN"]
    if not state.watchlist:
        draw_text(surface, "Popular picks. Tap Watch on any stock to save your own.", font_tiny, SG_MUTED, 20, y + r)
        y += 22
    for ticker in watch:
        a = find_asset(ticker)
        if not a:
            continue
        row = pygame.Rect(20, y + r, WIDTH - 40, 76)
        if row.bottom > GAME_TOP - 5 and row.top < CONTENT_BOTTOM + 5:
            hov = row.collidepoint(mouse) and clip.collidepoint(mouse)
            sg_panel(surface, row, 18, color=SG_PANEL_2 if hov else SG_PANEL)
            draw_stock_row(surface, row, a)
        home_action_rects[f"stock:{ticker}"] = row
        y += 86
    y += 10

    # Why did it move?
    r = _home_rise(5, now)
    a = max(STOCKS, key=lambda s: abs(stock_snapshot(s)["move"]))
    move = stock_snapshot(a)["move"]
    reason, lesson = why_it_moved(a)
    rl = _wrap_words(reason, font_small, WIDTH - 76)[:2]
    ll = _wrap_words(lesson, font_tiny, WIDTH - 76)[:2]
    card = pygame.Rect(20, y + r, WIDTH - 40, 64 + 19 * len(rl) + 17 * len(ll))
    sg_panel(surface, card, 20)
    draw_text(surface, "Why did it move?", font_tiny, SG_MUTED, card.x + 18, card.y + 14)
    mcol = SG_GREEN if move >= 0 else SG_RED
    draw_trend_arrow(surface, card.x + 26, card.y + 42, move >= 0, mcol)
    draw_text(surface, f"{a['name']}  {'+' if move >= 0 else ''}{move:.2f}%", font_body_bold, mcol, card.x + 42, card.y + 32,
              max_width=card.w - 60)
    ly = card.y + 58
    for ln in rl:
        draw_text(surface, ln, font_small, SG_TEXT, card.x + 18, ly)
        ly += 19
    for ln in ll:
        draw_text(surface, ln, font_tiny, SG_MUTED, card.x + 18, ly)
        ly += 17
    home_action_rects[f"why:{a['ticker']}"] = card
    y += card.h + 22

    # Recent activity timeline.
    r = _home_rise(6, now)
    draw_text(surface, "Recent activity", font_medium_bold, SG_TEXT, 20, y + r)
    y += 34
    acts = state.recent_actions[:4] if state.recent_actions else [
        {"label": "Your Ledger is ready."}, {"label": "Finish a lesson to start your learning streak."}]
    panel = pygame.Rect(20, y + r, WIDTH - 40, 20 + 38 * len(acts))
    sg_panel(surface, panel, 20)
    for i, act in enumerate(acts):
        label = act.get("label", "") if isinstance(act, dict) else str(act)
        cy = panel.y + 29 + i * 38
        if i < len(acts) - 1:
            pygame.draw.line(surface, SG_LINE, (panel.x + 26, cy + 6), (panel.x + 26, cy + 32), 2)
        pygame.draw.circle(surface, SG_PURPLE if i == 0 else SG_PANEL_2, (panel.x + 26, cy), 6)
        draw_text(surface, label, font_small, SG_TEXT if i == 0 else SG_MUTED, panel.x + 44, cy - 10, max_width=panel.w - 120)
        when = act.get("time") if isinstance(act, dict) else None
        if when:
            draw_text(surface, time_ago(when), font_tiny, SG_MUTED, panel.right - 16, cy - 8, align="right")
    y += panel.h + 20

    clamp_scroll_full("home", y - y0 + 10)
    surface.set_clip(prev)


def handle_home_click(pos):
    if not (GAME_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for key, r in home_action_rects.items():
        if not r.collidepoint(pos):
            continue
        if key.startswith(("stock:", "why:")):
            a = find_asset(key.split(":", 1)[1])
            if a:
                open_detail_modal(a)
        elif key == "claim":
            if claim_challenge():
                spawn_confetti(50)
                play_sound("achievement")
            return True
        elif key == "see_watchlist":
            market_ui["filter"] = "watch" if state.watchlist else "all"
            state.tab = "market"
        elif key == "portfolio_hero":
            state.tab = "portfolio"
        else:
            state.tab = key
        play_sound("click")
        return True
    return False


MARKET_FILTERS = [("all", "All"), ("owned", "My stocks"), ("watch", "Watchlist"), ("up", "Gainers"), ("down", "Losers")]
market_ui = {"filter": "all", "btns": {}}


def insight_signal(asset):
    """Market Insight's trend read: direction over the last 30 ticks."""
    move = recent_move_pct(asset, 30)
    if move > 0.25:
        return "Trending up", True, move
    if move < -0.25:
        return "Trending down", False, move
    return "Moving sideways", None, move


def draw_trend_arrow(surface, cx, cy, up, color, s=1.0):
    if up is None:
        pygame.draw.line(surface, color, (cx - 5 * s, cy), (cx + 5 * s, cy), max(2, int(2 * s)))
        return
    d = -1 if up else 1
    pygame.draw.polygon(surface, color, [(cx, cy + 6 * d * s), (cx - 6 * s, cy - 3 * d * s), (cx + 6 * s, cy - 3 * d * s)][::1])


def draw_boost_strip(surface, y):
    """Active boosts with their time left, night style."""
    active = [b for b in BOOSTS if not b.get("instant") and boost_active(b["id"])]
    if not active:
        return y
    x = 20
    for b in active:
        label = f"{b['name']}  ·  {boost_left_label(b['id'])}"
        w = font_tiny.size(label)[0] + 46
        if x + w > WIDTH - 20:
            x, y = 20, y + 40
        chip = pygame.Rect(x, y, w, 32)
        col = {"PURPLE": SG_PURPLE, "ORANGE": SG_AMBER, "GREEN": SG_GREEN, "GOLD": SG_GOLD}.get(b["color"], SG_CYAN)
        pygame.draw.rect(surface, mix_color(col, SG_BG, 0.78), chip, border_radius=16)
        pygame.draw.rect(surface, mix_color(col, SG_BG, 0.4), chip, 1, border_radius=16)
        draw_boost_icon(surface, b["id"], chip.x + 17, chip.centery, 11)
        draw_text(surface, label, font_tiny, col, chip.x + 34, chip.centery - 8)
        x = chip.right + 8
    return y + 44


def draw_market_tab(surface):
    global market_row_rects, market_search_rect, market_clear_rect
    market_row_rects = []
    b = market_ui["btns"] = {}
    now = time.time()
    off = scroll_offset["market"]
    clip = pygame.Rect(0, GAME_TOP, WIDTH, CONTENT_BOTTOM - GAME_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y0 = GAME_TOP + 6 - off
    y = y0

    draw_text(surface, "Market", font_sg_h2, SG_TEXT, 20, y)
    live = state.live_mode
    pill_label = "Live prices" if live else "Simulated"
    pw = font_tiny.size(pill_label)[0] + 30
    pill = pygame.Rect(WIDTH - 20 - pw, y + 4, pw, 24)
    pcol = SG_GREEN if live else SG_CYAN
    pygame.draw.rect(surface, mix_color(pcol, SG_BG, 0.8), pill, border_radius=12)
    pygame.draw.circle(surface, pcol, (pill.x + 12, pill.centery), 3 + (1.5 * (0.5 + 0.5 * math.sin(now * 4)) if live else 0))
    draw_text(surface, pill_label, font_tiny, pcol, pill.x + 21, pill.y + 4)
    y += 42

    # Market mood: regime, breadth and today's extremes.
    movers = sorted(STOCKS, key=lambda a: day_move_pct(a))
    ups = sum(1 for a in STOCKS if day_move_pct(a) >= 0)
    mood = pygame.Rect(20, y, WIDTH - 40, 176)
    pygame.draw.rect(surface, SG_PANEL, mood, border_radius=22)
    pygame.draw.rect(surface, SG_LINE, mood, 1, border_radius=22)
    surface.blit(_hero_glow(mood.size, [((*SG_GREEN, 40), (mood.w - 60, 30), 80), ((*SG_PURPLE, 50), (40, mood.h), 70)], 18), mood.topleft)
    pygame.draw.rect(surface, SG_LINE, mood, 1, border_radius=22)
    draw_text(surface, "Market mood", font_tiny, SG_MUTED, mood.x + 18, mood.y + 16)
    draw_text(surface, state.market_regime["name"], font_medium_bold, SG_TEXT, mood.x + 18, mood.y + 34, max_width=mood.w - 36)
    draw_text(surface, state.event_banner or state.market_regime.get("desc", ""), font_small, SG_MUTED, mood.x + 18, mood.y + 58,
              max_width=mood.w - 36)
    bar = pygame.Rect(mood.x + 18, mood.y + 88, mood.w - 36, 10)
    pygame.draw.rect(surface, SG_RED, bar, border_radius=5)
    fr = tween("mkt_breadth", ups / max(1, len(STOCKS)), 5)
    if fr > 0.01:
        pygame.draw.rect(surface, SG_GREEN, (bar.x, bar.y, max(10, int(bar.w * fr)), bar.h), border_radius=5)
    draw_text(surface, f"{ups} up", font_tiny, SG_GREEN, bar.x, bar.bottom + 8)
    draw_text(surface, f"{len(STOCKS) - ups} down", font_tiny, SG_RED, bar.right, bar.bottom + 8, align="right")
    cw = (mood.w - 36 - 10) // 2
    for i, (a, label) in enumerate(((movers[-1], "Top gainer"), (movers[0], "Top loser"))):
        mv = day_move_pct(a)
        col = SG_GREEN if mv >= 0 else SG_RED
        chip = pygame.Rect(mood.x + 18 + i * (cw + 10), bar.bottom + 32, cw, 30)
        pygame.draw.rect(surface, mix_color(col, SG_BG, 0.8), chip, border_radius=15)
        draw_text(surface, label, font_tiny, SG_MUTED, chip.x + 12, chip.y + 7)
        draw_text(surface, f"{a['ticker']} {'+' if mv >= 0 else ''}{mv:.1f}%", font_tiny, col, chip.right - 12, chip.y + 7, align="right")
    y = mood.bottom + 14

    y = draw_boost_strip(surface, y)

    # Market Insight: the full panel while the boost runs, a small shop link otherwise.
    if boost_active("insight"):
        sector, trend = hottest_sector()
        hot = sorted(STOCKS, key=lambda a: -abs(recent_move_pct(a, 30)))[:3]
        card = pygame.Rect(20, y, WIDTH - 40, 72 + len(hot) * 32 + 30)
        sg_panel(surface, card, 20, border=False)
        pygame.draw.rect(surface, SG_PURPLE, card, 2, border_radius=20)
        draw_boost_icon(surface, "insight", card.x + 26, card.y + 26, 13)
        draw_text(surface, "Market Insight", font_body_bold, SG_PURPLE, card.x + 48, card.y + 16)
        draw_text(surface, f"{boost_left_label('insight')} left", font_tiny, SG_MUTED, card.right - 18, card.y + 19, align="right")
        if sector:
            draw_text(surface, f"Hottest sector: {sector} ({'+' if trend >= 0 else ''}{trend * 100 if abs(trend) < 1 else trend:.1f}%)",
                      font_small, SG_TEXT, card.x + 18, card.y + 44, max_width=card.w - 36)
        ry = card.y + 72
        for a in hot:
            label, up, mv = insight_signal(a)
            col = SG_GREEN if up else (SG_RED if up is False else SG_MUTED)
            draw_trend_arrow(surface, card.x + 26, ry + 9, up, col)
            draw_text(surface, a["name"], font_small_bold, SG_TEXT, card.x + 42, ry, max_width=170)
            draw_text(surface, f"{label}  {'+' if mv >= 0 else ''}{mv:.2f}%", font_small, col, card.right - 18, ry, align="right")
            ry += 32
        draw_text(surface, "Trends can flip fast. Use them as a clue, not a promise.", font_tiny, SG_MUTED, card.x + 18, card.bottom - 24,
                  max_width=card.w - 36)
        y = card.bottom + 14
    else:
        card = pygame.Rect(20, y, WIDTH - 40, 58)
        hov = card.collidepoint(pygame.mouse.get_pos())
        sg_panel(surface, card, 18, color=SG_PANEL_2 if hov else SG_PANEL)
        draw_boost_icon(surface, "insight", card.x + 28, card.centery, 13)
        draw_text(surface, "Market Insight boost", font_small_bold, SG_TEXT, card.x + 52, card.y + 11)
        draw_text(surface, "See trend signals on every stock for 5 minutes", font_tiny, SG_MUTED, card.x + 52, card.y + 31,
                  max_width=card.w - 150)
        draw_coin_icon(surface, card.right - 70, card.centery, 8)
        draw_text(surface, str(BOOST_BY_ID["insight"]["price"]), font_small_bold, SG_GOLD, card.right - 58, card.centery - 9)
        pygame.draw.lines(surface, SG_MUTED, False, [(card.right - 22, card.centery - 6), (card.right - 16, card.centery),
                                                      (card.right - 22, card.centery + 6)], 2)
        b["insight_shop"] = card
        y = card.bottom + 14

    # Search.
    market_search_rect = pygame.Rect(20, y, WIDTH - 40, 48)
    pygame.draw.rect(surface, SG_PANEL, market_search_rect, border_radius=16)
    pygame.draw.rect(surface, SG_GOLD if state.market_search_active else SG_LINE, market_search_rect,
                     2 if state.market_search_active else 1, border_radius=16)
    _sg_icon(surface, "lens", market_search_rect.x + 24, market_search_rect.centery, SG_MUTED, 0.9)
    q = state.market_search
    if q:
        r = draw_text(surface, q, font_body, SG_TEXT, market_search_rect.x + 44, market_search_rect.centery - 10, max_width=market_search_rect.w - 90)
    else:
        r = pygame.Rect(market_search_rect.x + 44, market_search_rect.centery - 10, 0, 20)
        draw_text(surface, "Search by company or ticker", font_body, SG_MUTED, market_search_rect.x + 44, market_search_rect.centery - 10)
    if state.market_search_active and int(now * 2) % 2 == 0:
        pygame.draw.line(surface, SG_GOLD, (r.right + 2, market_search_rect.centery - 10), (r.right + 2, market_search_rect.centery + 10), 2)
    market_clear_rect = pygame.Rect(market_search_rect.right - 40, market_search_rect.y + 8, 32, 32)
    if q:
        _sg_cross(surface, market_clear_rect.centerx, market_clear_rect.centery, 0.7, SG_MUTED, 2)
    y = market_search_rect.bottom + 12

    # Filter chips.
    x = 20
    for key, label in MARKET_FILTERS:
        w = font_small_bold.size(label)[0] + 26
        r = pygame.Rect(x, y, w, 34)
        on = market_ui["filter"] == key
        pygame.draw.rect(surface, SG_GOLD if on else SG_PANEL, r, border_radius=17)
        if not on:
            pygame.draw.rect(surface, SG_LINE, r, 1, border_radius=17)
        draw_text(surface, label, font_small_bold, SG_INK if on else SG_TEXT, r.centerx, r.centery - 9, align="center")
        b["filter_" + key] = r
        x = r.right + 7
    y += 48

    assets = filtered_assets()
    f = market_ui["filter"]
    if f == "owned":
        assets = [a for a in assets if state.holdings.get(a["ticker"], 0) > 0]
    elif f == "watch":
        assets = [a for a in assets if a["ticker"] in state.watchlist]
    elif f == "up":
        assets = sorted([a for a in assets if day_move_pct(a) > 0 and asset_unlocked(a)], key=lambda a: -day_move_pct(a))
    elif f == "down":
        assets = sorted([a for a in assets if day_move_pct(a) < 0 and asset_unlocked(a)], key=lambda a: day_move_pct(a))
    if not assets:
        empty = pygame.Rect(20, y, WIDTH - 40, 104)
        sg_panel(surface, empty, 20)
        msg = {"owned": ("No stocks yet", "Tap any stock to buy your first shares."),
               "watch": ("Your watchlist is empty", "Open a stock and tap Watch to save it here."),
               "up": ("Nothing is up right now", "Check back in a moment."),
               "down": ("Nothing is down right now", "Check back in a moment.")}.get(
            f, ("No matches", "Try a ticker like AAPL or a company name."))
        draw_text(surface, msg[0], font_body_bold, SG_TEXT, empty.centerx, empty.y + 30, align="center")
        draw_text(surface, msg[1], font_small, SG_MUTED, empty.centerx, empty.y + 58, align="center")
        y = empty.bottom + 20
    insight = boost_active("insight")
    for s in assets:
        rect = pygame.Rect(20, y, WIDTH - 40, 84 if insight else 76)
        if rect.bottom > GAME_TOP - 5 and rect.top < CONTENT_BOTTOM + 5:
            locked = not asset_unlocked(s)
            hov = not locked and rect.collidepoint(pygame.mouse.get_pos())
            sg_panel(surface, rect, 18, color=SG_PANEL_2 if hov else SG_PANEL)
            if locked:
                draw_padlock(surface, rect.x + 34, rect.centery, 20, SG_MUTED)
                draw_text(surface, s["name"], font_body_bold, SG_MUTED, rect.x + 62, rect.y + 16, max_width=rect.w - 80)
                draw_text(surface, f"Unlocks at level {s.get('unlock_level', 1)} or {fmt_money(s.get('unlock_worth', 0))} net worth",
                          font_tiny, SG_MUTED, rect.x + 62, rect.y + 40, max_width=rect.w - 80)
            else:
                draw_stock_row(surface, rect, s, insight)
            market_row_rects.append((rect, s))
        y = rect.bottom + 10
    clamp_scroll_full("market", y - y0 + 10)
    surface.set_clip(prev)


def draw_stock_row(surface, rect, s, insight=False):
    """One stock row (badge, name, mini chart, price, day move). Shared by Market and Home."""
    draw_ticker_badge(surface, s["ticker"], rect.x + 14, rect.y + 16, size=44)
    name_w = 150
    draw_text(surface, s["name"], font_body_bold, SG_TEXT, rect.x + 70, rect.y + 13, max_width=name_w)
    owned = state.holdings.get(s["ticker"], 0)
    sub = f"You own {owned:g}" if owned else s["sector"]
    sub_col = SG_GOLD if owned else SG_MUTED
    sr = draw_text(surface, sub, font_tiny, sub_col, rect.x + 70, rect.y + 36, max_width=name_w)
    if s["ticker"] in state.watchlist:
        draw_star_shape(surface, sr.right + 10, sr.centery, 5, SG_GOLD)
    if insight:
        label, up, mv = insight_signal(s)
        col = SG_GREEN if up else (SG_RED if up is False else SG_MUTED)
        draw_trend_arrow(surface, rect.x + 75, rect.y + 63, up, col, 0.8)
        draw_text(surface, label, font_tiny, col, rect.x + 86, rect.y + 55)
    pct = day_move_pct(s)
    up = pct >= 0
    draw_mini_chart(surface, s["history"][-48:], up, rect.x + 222, rect.y + 24, 64, 26,
                    color=SG_GREEN if up else SG_RED, anim_key=("row", s["ticker"]), **smooth_chart_args())
    flash, went_up = price_flash(("px", s["ticker"]), s["price"])
    shown = tween(("px", s["ticker"]), s["price"], 6.0)
    price_text = fmt_money(shown)
    if flash > 0:
        pw = font_body_bold.size(price_text)[0]
        draw_alpha_rect(surface, (rect.right - 20 - pw, rect.y + 11, pw + 12, 24), SG_GREEN if went_up else SG_RED,
                        70 * flash, radius=8)
    draw_text(surface, price_text, font_body_bold, SG_TEXT, rect.right - 14, rect.y + 14, align="right")
    chip_t = f"{'+' if up else ''}{pct:.2f}%"
    cw = font_tiny.size(chip_t)[0] + 16
    chip = pygame.Rect(rect.right - 14 - cw, rect.y + 40, cw, 22)
    pygame.draw.rect(surface, mix_color(SG_GREEN if up else SG_RED, SG_PANEL, 0.72), chip, border_radius=11)
    draw_text(surface, chip_t, font_tiny, SG_GREEN if up else SG_RED, chip.centerx, chip.y + 3, align="center")


def handle_market_click(pos):
    if not (GAME_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for key, rect in market_ui["btns"].items():
        if rect.collidepoint(pos):
            if key == "insight_shop":
                state.tab = "rewards"
                scroll_offset["rewards"] = 0
                show_toast("Market Insight", "Find it under Boosts in the shop.", "achievement")
            else:
                market_ui["filter"] = key.split("_", 1)[1]
                scroll_offset["market"] = min(scroll_offset["market"], 0)
            play_sound("click")
            return True
    return False



def portfolio_analytics():
    positions = []
    total_value = 0.0
    for ticker, shares in state.holdings.items():
        if shares <= 0:
            continue
        stock = find_asset(ticker)
        if not stock:
            continue
        value = shares * stock["price"]
        total_value += value
        positions.append((ticker, stock["name"], stock["sector"], value))
    sector_values = {}
    for _, _, sector, value in positions:
        sector_values[sector] = sector_values.get(sector, 0.0) + value
    top_sector = max(sector_values.items(), key=lambda x: x[1])[0] if sector_values else "None"
    concentration = (max(sector_values.values()) / total_value) if total_value else 0.0
    diversification = max(0.0, min(100.0, (1.0 - concentration) * 125.0 + min(len(positions), 6) * 5.0))
    realized = sum(getattr(state, "realized_pnl", {}).values())
    unrealized = 0.0
    for ticker, shares in state.holdings.items():
        if shares > 0:
            stock = find_asset(ticker)
            avg = state.avg_buy_price.get(ticker, stock["price"]) if stock else 0
            if stock:
                unrealized += (stock["price"] - avg) * shares
    return {"positions": len(positions), "sectors": len(sector_values), "top_sector": top_sector,
            "concentration": concentration, "diversification": diversification,
            "realized": realized, "unrealized": unrealized}


def add_recent_action(label):
    if not label:
        return
    state.recent_actions.insert(0, {"label": str(label), "time": time.time()})
    state.recent_actions = state.recent_actions[:6]


def toggle_watchlist(ticker):
    ticker = ticker.upper()
    if ticker in state.watchlist:
        state.watchlist.remove(ticker)
        show_toast("Removed from watchlist", ticker, "neutral")
    elif find_asset(ticker) and len(state.watchlist) < 12:
        state.watchlist.append(ticker)
        show_toast("Added to watchlist", ticker, "achievement")
    else:
        show_toast("Watchlist full", "You can track up to 12 stocks.", "warning")
    save_game()


WEALTH_MILESTONES = [  # (net worth, coins, chest)
    (1250, 50, "common"), (1500, 80, "rare"), (2000, 120, "rare"), (3000, 200, "epic"),
    (5000, 300, "epic"), (10000, 600, "legendary"),
]
# Shades of the one accent plus grays, so the donut matches the rest of the app.
SECTOR_COLORS = [(0, 160, 70), (17, 17, 19), (120, 200, 150), (140, 140, 148), (0, 100, 45),
                 (200, 200, 206), (60, 180, 110), (80, 80, 88)]
portfolio_ui = {"btns": {}}


def next_wealth_milestone():
    claimed = set(getattr(state, "wealth_claimed", []))
    return next((m for m in WEALTH_MILESTONES if m[0] not in claimed), None)


def claim_wealth_milestone():
    m = next_wealth_milestone()
    if not m or net_worth() < m[0]:
        play_sound("error")
        return
    state.wealth_claimed = sorted(set(getattr(state, "wealth_claimed", [])) | {m[0]})
    add_coins(m[1], x=WIDTH // 2, y=300)
    grant_chest(m[2], f"{fmt_money(m[0])} net worth milestone")
    play_sound("victory")
    spawn_confetti(70)
    avatar_emote("cheer")
    save_game()


def portfolio_grade(stats, nw):
    gain = (nw / STARTING_CASH - 1) * 100
    profit_score = max(0.0, min(100.0, 50 + gain * 5))
    cash_frac = state.cash / max(1.0, nw)
    cash_score = 100.0 if 0.05 <= cash_frac <= 0.4 else (60.0 if cash_frac < 0.05 else max(20.0, 100 - (cash_frac - 0.4) * 160))
    div_score = stats["diversification"] if stats["positions"] else 0.0
    score = div_score * 0.5 + profit_score * 0.3 + cash_score * 0.2
    letter = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    return letter, [("Diversified", div_score / 100, SG_PURPLE), ("Profit", profit_score / 100, SG_GREEN),
                    ("Cash cushion", cash_score / 100, SG_CYAN)]


def draw_portfolio_tab(surface):
    global portfolio_row_rects, avatar_stage_rect
    portfolio_row_rects = []
    b = portfolio_ui["btns"] = {}
    now = time.time()
    off = scroll_offset["portfolio"]
    clip = pygame.Rect(0, GAME_TOP, WIDTH, CONTENT_BOTTOM - GAME_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y0 = GAME_TOP + 6 - off
    y = y0
    nw = net_worth()
    stats = portfolio_analytics()

    draw_text(surface, "Portfolio", font_sg_h2, SG_TEXT, 20, y)
    secs = max(0, int(state.dividend_interval - (now - state.last_dividend_time)))
    label = f"Payday in {secs}s"
    pw = font_tiny.size(label)[0] + 40
    pill = pygame.Rect(WIDTH - 20 - pw, y + 3, pw, 28)
    pygame.draw.rect(surface, mix_color(SG_GOLD, SG_BG, 0.8), pill, border_radius=14)
    draw_coin_icon(surface, pill.x + 16, pill.centery, 7)
    draw_text(surface, label, font_tiny, SG_GOLD, pill.x + 28, pill.y + 6)
    y += 44

    # Hero: net worth, gain, chart and your trader.
    hero = pygame.Rect(20, y, WIDTH - 40, 214)
    pygame.draw.rect(surface, SG_PANEL, hero, border_radius=24)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    gain = nw - STARTING_CASH
    up = gain >= 0
    surface.blit(_hero_glow(hero.size, [((*(SG_GREEN if up else SG_RED), 50), (60, 150), 90), ((*SG_PURPLE, 60), (hero.w - 60, 50), 80)], 18),
                 hero.topleft)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    draw_text(surface, "Net worth", font_tiny, SG_MUTED, hero.x + 20, hero.y + 20)
    shown = tween("pf_nw", nw, 7)
    draw_text(surface, fmt_money(shown), font_sg_title, SG_TEXT, hero.x + 20, hero.y + 38, max_width=hero.w - 150)
    chip_t = f"{'+' if up else '-'}{fmt_money(abs(gain))} ({'+' if up else '-'}{abs(gain / STARTING_CASH * 100):.1f}%) since you started"
    cw = min(hero.w - 150, font_tiny.size(chip_t)[0] + 20)
    chip = pygame.Rect(hero.x + 20, hero.y + 82, cw, 24)
    pygame.draw.rect(surface, mix_color(SG_GREEN if up else SG_RED, SG_BG, 0.75), chip, border_radius=12)
    draw_text(surface, chip_t, font_tiny, SG_GREEN if up else SG_RED, chip.x + 10, chip.y + 4, max_width=chip.w - 16)
    avatar_stage_rect = pygame.Rect(hero.right - 124, hero.y + 8, 116, 116)
    pc = surface.get_clip()
    surface.set_clip(pc.clip(hero.inflate(-2, -2)))
    if avatar_anim["pulse"] > 0:
        rad = int(40 + 20 * (1 - avatar_anim["pulse"]))
        pygame.draw.circle(surface, mix_color(SG_PURPLE, SG_BG, 1 - avatar_anim["pulse"]), (hero.right - 64, hero.y + 64), rad, 3)
    draw_character(surface, state.avatar, hero.right - 64, hero.y + 62, scale=1.3, animate=True, now=now)
    surface.set_clip(pc)
    if now < avatar_anim["speech_until"]:
        line = sg_wrap(avatar_anim["speech"], font_tiny, hero.w - 40, 1)
        if line:
            draw_text(surface, line[0], font_tiny, SG_TEXT, hero.x + 20, hero.y + 114, max_width=hero.w - 150)
    else:
        draw_text(surface, "Tap your trader for a tip", font_tiny, SG_MUTED, hero.x + 20, hero.y + 114)
    draw_mini_chart(surface, state.net_worth_history, up, hero.x + 20, hero.y + 142, hero.w - 40, 52,
                    color=SG_GREEN if up else SG_RED, anim_key="pf_nw_chart", tick_at=state.last_history_sample,
                    tick_len=NET_WORTH_SAMPLE_SECONDS)
    y = hero.bottom + 12

    # Cash / invested / dividends.
    invested = nw - state.cash
    tiles = [("Cash", fmt_money(state.cash), SG_TEXT), ("Invested", fmt_money(invested), SG_TEXT),
             ("Dividends", f"+{fmt_money(state.total_dividends)}", SG_GOLD)]
    tw = (WIDTH - 40 - 20) // 3
    for i, (lab, val, col) in enumerate(tiles):
        t = pygame.Rect(20 + i * (tw + 10), y, tw, 62)
        sg_panel(surface, t, 16)
        draw_text(surface, lab, font_tiny, SG_MUTED, t.x + 12, t.y + 12)
        draw_text(surface, val, font_small_bold, col, t.x + 12, t.y + 32, max_width=t.w - 18)
    y += 76
    y = draw_boost_strip(surface, y)

    # Wealth milestone: a reward to chase.
    m = next_wealth_milestone()
    card = pygame.Rect(20, y, WIDTH - 40, 108)
    sg_panel(surface, card, 20)
    if m:
        target, coins, chest = m
        claimed = [w for w in WEALTH_MILESTONES if w[0] in getattr(state, "wealth_claimed", [])]
        base = claimed[-1][0] if claimed else STARTING_CASH
        frac = max(0.0, min(1.0, (nw - base) / max(1.0, target - base)))
        ready = nw >= target
        if ready:
            pygame.draw.rect(surface, SG_GOLD, card, 2, border_radius=20)
        draw_chest(surface, card.x + 44, card.y + 48, 50, chest, shake=math.sin(now * 12) * 2 if ready else 0)
        draw_text(surface, "Wealth milestone", font_tiny, SG_GOLD, card.x + 86, card.y + 16)
        draw_text(surface, f"Reach {fmt_money(target)}", font_medium_bold, SG_TEXT, card.x + 86, card.y + 32)
        draw_text(surface, f"Reward: {coins} coins + {chest_name(chest)}", font_tiny, SG_MUTED, card.x + 86, card.y + 56, max_width=card.w - 106)
        bar = pygame.Rect(card.x + 86, card.y + 80, card.w - 106 - (96 if ready else 0), 10)
        pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=5)
        fill = tween("pf_wealth", frac, 5)
        if fill > 0.01:
            pygame.draw.rect(surface, SG_GOLD, (bar.x, bar.y, max(10, int(bar.w * fill)), bar.h), border_radius=5)
        if ready:
            br = pygame.Rect(card.right - 100, card.y + 66, 84, 34)
            _sg_button(surface, br, "claim_wealth", "Claim", SG_GOLD, SG_INK, font=font_small_bold, depth=4, btns=b)
        else:
            draw_text(surface, f"{fmt_money(max(0, target - nw))} to go", font_tiny, SG_MUTED, bar.right, card.y + 58, align="right")
    else:
        draw_trophy_icon(surface, card.x + 44, card.centery, SG_GOLD, 1.6)
        draw_text(surface, "Every wealth milestone claimed!", font_medium_bold, SG_TEXT, card.x + 86, card.y + 34)
        draw_text(surface, "You're a Ledger legend.", font_small, SG_MUTED, card.x + 86, card.y + 60)
    y = card.bottom + 12

    # Health grade + allocation donut.
    letter, meters = portfolio_grade(stats, nw)
    card = pygame.Rect(20, y, WIDTH - 40, 176)
    sg_panel(surface, card, 20)
    gcol = {"A": SG_GREEN, "B": SG_CYAN, "C": SG_GOLD, "D": SG_RED}[letter]
    draw_text(surface, "Portfolio health", font_body_bold, SG_TEXT, card.x + 20, card.y + 16)
    gc = (card.x + 46, card.y + 90)
    pygame.draw.circle(surface, mix_color(gcol, SG_PANEL, 0.75), gc, 30)
    pygame.draw.circle(surface, gcol, gc, 30, 3)
    draw_text(surface, letter, font_sg_h2, gcol, gc[0], gc[1] - 16, align="center")
    my = card.y + 52
    mx, mw = card.x + 92, 120
    for lab, frac, col in meters:
        draw_text(surface, lab, font_tiny, SG_MUTED, mx, my)
        bar = pygame.Rect(mx, my + 18, mw, 7)
        pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=4)
        f = tween(("pf_meter", lab), frac, 5)
        if f > 0.02:
            pygame.draw.rect(surface, col, (bar.x, bar.y, max(7, int(bar.w * f)), bar.h), border_radius=4)
        my += 38
    # Donut by sector.
    sectors = {}
    for t, q in state.holdings.items():
        a = find_asset(t)
        if a and q > 0:
            sectors[a["sector"]] = sectors.get(a["sector"], 0.0) + q * a["price"]
    dc = (card.right - 74, card.y + 96)
    if sectors:
        total = sum(sectors.values())
        items = sorted(sectors.items(), key=lambda kv: -kv[1])
        segs = [(v / total, SECTOR_COLORS[i % len(SECTOR_COLORS)]) for i, (_, v) in enumerate(items)]
        draw_donut(surface, dc, 50, 32, segs, tween("pf_donut", 1.0, 3))
        draw_text(surface, str(len(items)), font_medium_bold, SG_TEXT, dc[0], dc[1] - 16, align="center")
        draw_text(surface, "sectors" if len(items) != 1 else "sector", font_tiny, SG_MUTED, dc[0], dc[1] + 4, align="center")
    else:
        pygame.draw.circle(surface, SG_PANEL_2, dc, 50, 18)
        draw_text(surface, "No stocks", font_tiny, SG_MUTED, dc[0], dc[1] - 8, align="center")
    y = card.bottom + 12
    if sectors:
        # Legend under the card, two per row, so nothing is squeezed.
        items = sorted(sectors.items(), key=lambda kv: -kv[1])
        total = sum(sectors.values())
        rows = (len(items) + 1) // 2
        leg = pygame.Rect(20, y, WIDTH - 40, 20 + rows * 26)
        sg_panel(surface, leg, 18)
        colw = (leg.w - 20) // 2
        for i, (sec, v) in enumerate(items):
            lx = leg.x + 16 + (i % 2) * colw
            ly = leg.y + 12 + (i // 2) * 26
            pygame.draw.circle(surface, SECTOR_COLORS[i % len(SECTOR_COLORS)], (lx + 5, ly + 9), 5)
            draw_text(surface, sec, font_small, SG_TEXT, lx + 16, ly, max_width=colw - 70)
            draw_text(surface, f"{v / total * 100:.0f}%", font_small_bold, SG_MUTED, lx + colw - 20, ly, align="right")
        y = leg.bottom + 12

    # Goals.
    todo = [q for q in QUESTS if q[0] not in state.quests_claimed]
    done_n = len(QUESTS) - len(todo)
    card = pygame.Rect(20, y, WIDTH - 40, 62 + min(3, len(todo)) * 54 + (0 if todo else 20))
    sg_panel(surface, card, 20)
    draw_text(surface, "Goals", font_body_bold, SG_TEXT, card.x + 20, card.y + 16)
    draw_text(surface, f"{done_n}/{len(QUESTS)} done", font_small_bold, SG_GOLD, card.right - 20, card.y + 17, align="right")
    gy = card.y + 52
    for qid, title, why, xp in todo[:3]:
        pygame.draw.circle(surface, SG_PANEL_2, (card.x + 32, gy + 16), 13, 2)
        draw_text(surface, title, font_small_bold, SG_TEXT, card.x + 56, gy + 2, max_width=card.w - 150)
        draw_text(surface, why, font_tiny, SG_MUTED, card.x + 56, gy + 22, max_width=card.w - 76)
        xp_t = f"+{xp} XP"
        xw = font_tiny.size(xp_t)[0] + 18
        xc = pygame.Rect(card.right - 16 - xw, gy + 1, xw, 22)
        pygame.draw.rect(surface, mix_color(SG_PURPLE, SG_BG, 0.75), xc, border_radius=11)
        draw_text(surface, xp_t, font_tiny, SG_PURPLE, xc.centerx, xc.y + 3, align="center")
        gy += 54
    if not todo:
        draw_text(surface, "All goals complete. Legendary!", font_small, SG_MUTED, card.x + 20, card.y + 50)
    y = card.bottom + 22

    # Holdings.
    owned_stocks = [s for s in all_assets() if state.holdings.get(s["ticker"], 0) > 0]
    draw_text(surface, f"Your holdings ({len(owned_stocks)})", font_medium_bold, SG_TEXT, 20, y)
    y += 34
    if not owned_stocks:
        card = pygame.Rect(20, y, WIDTH - 40, 150)
        sg_panel(surface, card, 20)
        draw_text(surface, "No stocks yet", font_medium_bold, SG_TEXT, card.centerx, card.y + 24, align="center")
        draw_text(surface, "Buy your first shares to start growing.", font_small, SG_MUTED, card.centerx, card.y + 52, align="center")
        _sg_button(surface, pygame.Rect(card.x + 40, card.y + 84, card.w - 80, 48), "go_market", "Browse the Market", SG_GOLD, SG_INK,
                   font=font_body_bold, depth=4, btns=b)
        y = card.bottom + 20
    for s in owned_stocks:
        rect = pygame.Rect(20, y, WIDTH - 40, 82)
        if rect.bottom > GAME_TOP - 5 and rect.top < CONTENT_BOTTOM + 5:
            shares = state.holdings[s["ticker"]]
            avg = state.avg_buy_price.get(s["ticker"], s["price"])
            value = shares * s["price"]
            pnl = value - avg * shares
            pct = (s["price"] / avg - 1) * 100 if avg else 0.0
            hov = rect.collidepoint(pygame.mouse.get_pos())
            sg_panel(surface, rect, 18, color=SG_PANEL_2 if hov else SG_PANEL)
            draw_ticker_badge(surface, s["ticker"], rect.x + 14, rect.y + 18, size=44)
            draw_text(surface, s["name"], font_body_bold, SG_TEXT, rect.x + 70, rect.y + 14, max_width=150)
            draw_text(surface, f"{_shares_label(shares)}  ·  paid {fmt_money(avg)}", font_tiny, SG_MUTED, rect.x + 70, rect.y + 37, max_width=176)
            draw_text(surface, "Tap to sell", font_tiny, SG_PURPLE, rect.x + 70, rect.y + 55)
            draw_mini_chart(surface, s["history"][-40:], pnl >= 0, rect.x + 256, rect.y + 30, 40, 22, color=SG_GREEN if pnl >= 0 else SG_RED,
                            anim_key=("pf", s["ticker"]), **smooth_chart_args())
            # Same green/red pulse as the Market rows, keyed on the stock price so both pulse together.
            flash, went_up = price_flash(("pf_px", s["ticker"]), s["price"])
            value_text = fmt_money(tween(("pf_val", s["ticker"]), value, 6.0))
            if flash > 0:
                vw = font_body_bold.size(value_text)[0]
                draw_alpha_rect(surface, (rect.right - 20 - vw, rect.y + 13, vw + 12, 24), SG_GREEN if went_up else SG_RED,
                                70 * flash, radius=8)
            draw_text(surface, value_text, font_body_bold, SG_TEXT, rect.right - 14, rect.y + 16, align="right")
            chip_t = f"{'+' if pnl >= 0 else '-'}{fmt_money(abs(pnl))}"
            cw = font_tiny.size(chip_t)[0] + 16
            chip = pygame.Rect(rect.right - 14 - cw, rect.y + 44, cw, 22)
            pygame.draw.rect(surface, mix_color(SG_GREEN if pnl >= 0 else SG_RED, SG_PANEL, 0.72), chip, border_radius=11)
            draw_text(surface, chip_t, font_tiny, SG_GREEN if pnl >= 0 else SG_RED, chip.centerx, chip.y + 3, align="center")
            portfolio_row_rects.append((rect, s))
        y += 92
    clamp_scroll_full("portfolio", y - y0 + 10)
    surface.set_clip(prev)


def handle_portfolio_click(pos):
    if not (GAME_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for key, rect in portfolio_ui["btns"].items():
        if rect.collidepoint(pos):
            if key == "claim_wealth":
                claim_wealth_milestone()
            elif key == "go_market":
                state.tab = "market"
                play_sound("click")
            return True
    return False


# ----------------------------
# LEDGER ACADEMY (gamified learning path)
# ----------------------------

def draw_glyph(surface, kind, cx, cy, color, s=1.0):
    """Lesson icons, drawn supersampled for smooth edges."""
    draw_icon(surface, kind, cx, cy, color, s)


def draw_flame(surface, cx, cy, s, lit=True):
    outer = C("ORANGE") if lit else C("LIGHT_GRAY")
    inner = (255, 204, 64) if lit else C("PANEL_BG")
    flick = math.sin(time.time() * 9) * 1.2 * s if lit else 0
    pygame.draw.polygon(surface, outer, [(cx, cy - 11 * s - flick), (cx + 7 * s, cy - 1 * s), (cx + 6 * s, cy + 6 * s),
                                         (cx, cy + 9 * s), (cx - 6 * s, cy + 6 * s), (cx - 7 * s, cy - 1 * s)])
    pygame.draw.polygon(surface, inner, [(cx, cy - 3 * s - flick / 2), (cx + 3.5 * s, cy + 3 * s), (cx, cy + 7 * s), (cx - 3.5 * s, cy + 3 * s)])


def draw_star_shape(surface, cx, cy, r, color, outline=False):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.46
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    pygame.draw.polygon(surface, color, pts, 2 if outline else 0)


def draw_progress_ring(surface, center, r, frac, color, track, width=6):
    pygame.draw.circle(surface, track, center, r, width)
    if frac > 0.001:
        steps = max(2, int(60 * frac))
        a0 = -math.pi / 2
        pts = [(center[0] + math.cos(a0 + math.tau * frac * i / steps) * (r - width / 2),
                center[1] + math.sin(a0 + math.tau * frac * i / steps) * (r - width / 2)) for i in range(steps + 1)]
        pygame.draw.lines(surface, color, False, pts, width)


def draw_rotated_stamp(surface, text, color, center, angle):
    w = font_large_med.size(text)[0] + 28
    layer = HiSurface((w, 44), pygame.SRCALPHA)
    pygame.draw.rect(layer, (*color, 255), (0, 0, w, 44), 3, border_radius=8)
    pygame.draw.rect(layer, (*color, 255), (5, 5, w - 10, 34), 1, border_radius=5)
    img = font_large_med.render(text, True, color)
    layer.blit(img, img.get_rect(center=(w // 2, 22)))
    rotated = HiSurface(None, hi=pygame.transform.rotozoom(layer.hi, angle, 1.0))
    surface.blit(rotated, rotated.get_rect(center=center).topleft)


def _shuffled(n, seed):
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return order


_ripple_cache = {}


def _ripple_ring(color):
    """A smooth, soft-edged ring (drawn big, blurred a touch, cached) to scale per frame."""
    key = ("ring", tuple(color))
    img = _ripple_cache.get(key)
    if img is None:
        size = 256
        big = pygame.Surface((size, size), pygame.SRCALPHA)
        big.fill((*color, 0))
        pygame.draw.circle(big, (*color, 255), (size // 2, size // 2), size // 2 - 8, 9)
        img = pygame.transform.gaussian_blur(big, 3)
        _ripple_cache[key] = img
    return img


def _ripple_glow(color, r):
    key = ("glow", tuple(color), int(r), UI_SCALE)
    img = _ripple_cache.get(key)
    if img is None:
        pad = 26
        d = int((r + pad) * 2 * UI_SCALE)
        big = pygame.Surface((d, d), pygame.SRCALPHA)
        big.fill((*color, 0))
        pygame.draw.circle(big, (*color, 150), (d // 2, d // 2), int((r + 8) * UI_SCALE))
        img = soft_blur(big, int(12 * UI_SCALE))
        _ripple_cache[key] = img
    return img


def draw_soft_ripples(surface, center, r, color, now, period=2.4):
    """Inviting 'tap me' pulse: a breathing glow plus two soft rings drifting outward."""
    target = surface.hi if isinstance(surface, HiSurface) else surface
    sc = UI_SCALE if isinstance(surface, HiSurface) else 1
    cx, cy = center[0] * sc, center[1] * sc
    glow = _ripple_glow(color, r).copy()
    glow.set_alpha(int(120 + 70 * (0.5 + 0.5 * math.sin(now * math.tau / period))))
    target.blit(glow, (cx - glow.get_width() / 2, cy - glow.get_height() / 2))
    ring = _ripple_ring(color)
    for k in range(2):
        p = ((now / period) + k * 0.5) % 1.0
        e = 1 - (1 - p) ** 2.2
        rad = (r + 2 + 26 * e) * sc
        d = max(2, int(rad * 2 * 256 / (256 - 16)))
        img = pygame.transform.smoothscale(ring, (d, d))
        img.set_alpha(int(170 * (1 - p) ** 1.6))
        target.blit(img, (cx - d / 2, cy - d / 2))


# ----------------------------
# SCAM DETECTIVE
# ----------------------------
# A full-screen arcade mode. Each run is ten messages that ramp from easy to tricky:
# swipe or tap SCAM / LEGIT before the timer runs out, keep your three lives, and chain
# right answers for a score multiplier. Every verdict shows the red flags (or good signs)
# right on the message, then the detective tip behind it.

SCAM_CHANNELS = {
    "text": ("Text message", (13, 148, 136), "chat"),
    "email": ("Email", (124, 58, 237), "mail"),
    "dm": ("Direct message", (219, 39, 119), "chat"),
    "ad": ("Sponsored ad", (234, 88, 12), "ad"),
    "call": ("Voicemail", (37, 99, 235), "wave"),
    "popup": ("Website pop-up", (71, 85, 105), "window"),
    "game": ("Game chat", (79, 70, 229), "chat"),
    "post": ("Social post", (2, 132, 199), "post"),
    "shop": ("Marketplace", (180, 83, 9), "bag"),
    "app": ("App alert", (8, 145, 178), "bell"),
}
SCAM_LEVELS = {1: ("Easy", (13, 148, 136)), 2: ("Medium", (202, 138, 4)), 3: ("Tricky", (192, 38, 211))}
SCAM_RANKS = [  # (cases cracked in total, title, badge color)
    (0, "Rookie", (148, 163, 184)),
    (5, "Junior Detective", (45, 212, 191)),
    (15, "Detective", (96, 165, 250)),
    (30, "Inspector", (167, 139, 250)),
    (50, "Chief Inspector", (250, 204, 21)),
    (80, "Scam Legend", (244, 114, 182)),
]
SCAM_RUN_LEN = 10
SCAM_RUN_MIX = (3, 4, 3)     # easy, medium, tricky cases per run
SCAM_LIVES = 3
SCAM_HINTS = 2
SCAM_TIME = 30.0             # seconds per case
SCAM_ENTER_T = 0.55          # card fly-in; the clock starts after it lands
SCAM_SWIPE = 110             # drag distance that counts as an answer
SCAM_STAMP_T = 0.26          # stamp slam
SCAM_SHEET_T = 0.85          # verdict sheet starts sliding up
SCAM_LINE_H = 24
SCAM_CARD_X, SCAM_CARD_W = 20, WIDTH - 40
SCAM_CARD_TOP = 150          # top of the space the card is centered in while answering
SCAM_CARD_BOTTOM = HEIGHT - 164
SCAM_CARD_TOP_MIN = 64       # highest the card may move to make room for the verdict sheet

# The mode has its own night-time look in both light and dark mode.
SG_BG = (255, 255, 255)
SG_PANEL = (255, 255, 255)
SG_PANEL_2 = (240, 240, 242)
SG_LINE = (230, 230, 232)
SG_TEXT = (17, 17, 19)
SG_MUTED = (110, 110, 118)
SG_RED = (220, 50, 40)
SG_GREEN = (0, 160, 70)
SG_GOLD = (0, 160, 70)      # the one accent: buttons, highlights, progress
SG_AMBER = (110, 110, 118)
SG_CYAN = (17, 17, 19)
SG_PURPLE = (160, 160, 168)
SG_CARD = (255, 255, 255)
SG_INK = (255, 255, 255)    # text drawn on top of the accent
SG_CARD_MUTED = (110, 110, 118)
SG_CARD_LINE = (230, 230, 232)
SG_BUBBLE = (245, 245, 247)
# Clue highlights on the white card: (background, text).
SG_HL = {"scam": ((255, 214, 220), (176, 19, 60)), "legit": ((200, 246, 216), (21, 110, 55)),
         "hint": ((226, 219, 254), (91, 33, 182))}

font_sg_score = _SysFont(_DISPLAY_FONT, 30, bold=True)
font_sg_title = _SysFont(_DISPLAY_FONT, 32, bold=True)
font_sg_grade = _SysFont(_DISPLAY_FONT, 84, bold=True)

scam_game = {"open": False}
_sg_cache = {}


def _ease_back(t, k=1.7):
    """Overshoot a little, then settle: gives pops a bouncy feel."""
    t = max(0.0, min(1.0, t)) - 1
    return 1 + (k + 1) * t ** 3 + k * t ** 2


def _clamp01(t):
    return max(0.0, min(1.0, t))


def scam_stats():
    s = getattr(state, "scam_stats", None)
    if not isinstance(s, dict):
        s = {}
    for key in ("best", "runs", "correct", "seen", "best_combo", "perfect"):
        s[key] = int(s.get(key, 0) or 0)
    state.scam_stats = s
    return s


def scam_rank(correct=None):
    """(index, title, color, floor, next floor or None) for a number of cracked cases."""
    n = scam_stats()["correct"] if correct is None else correct
    idx = max(i for i, (floor, _, _) in enumerate(SCAM_RANKS) if n >= floor)
    floor, title, col = SCAM_RANKS[idx]
    nxt = SCAM_RANKS[idx + 1][0] if idx + 1 < len(SCAM_RANKS) else None
    return idx, title, col, floor, nxt


def scam_multiplier(combo):
    return min(4, 1 + combo // 2)


def _scam_grade(correct):
    if correct >= SCAM_RUN_LEN:
        return "S", SG_GOLD, "Perfect case file!"
    if correct >= 8:
        return "A", SG_GREEN, "Master detective!"
    if correct >= 6:
        return "B", SG_CYAN, "Sharp eyes!"
    if correct >= 4:
        return "C", SG_PURPLE, "Getting there!"
    return "D", SG_RED, "The scammers won this round"


def _scam_pick_run():
    """Ten cases, easy first and tricky last, preferring ones this player hasn't cracked yet."""
    cracked = set(getattr(state, "scam_cracked", []))
    picks = []
    for level, n in zip((1, 2, 3), SCAM_RUN_MIX):
        pool = [i for i, c in enumerate(SCAM_CASES) if c.get("level", 2) == level]
        random.shuffle(pool)
        pool.sort(key=lambda i: i in cracked)
        chosen = pool[:n]
        # Always mix in at least one honest message per level, so "everything is a scam" doesn't win.
        if chosen and all(SCAM_CASES[i]["answer"] == "scam" for i in chosen):
            legit = [i for i in pool[n:] if SCAM_CASES[i]["answer"] == "legit"]
            if legit:
                chosen[-1] = legit[0]
        random.shuffle(chosen)
        picks += chosen
    return picks


# ---- Game flow ----

def open_scam_game():
    now = time.time()
    scam_game.clear()
    scam_game.update(open=True, stage="lobby", stage_at=now, btns={}, shake_at=0.0, shake_amp=0.0,
                     flash=None, flash_at=0.0, last_draw=now)
    drag_state["active"] = False
    play_sound("swoosh")


def close_scam_game():
    scam_game["open"] = False
    play_sound("click")
    save_game()


def start_scam_run():
    now = time.time()
    scam_game.update(stage="play", stage_at=now, queue=_scam_pick_run(), i=0, lives=SCAM_LIVES, score=0,
                     combo=0, best_combo=0, correct=0, hints=SCAM_HINTS, results=[], confirm_quit=False,
                     heart_lost_at=0.0, combo_at=0.0)
    _scam_new_case(now)
    play_sound("swoosh")


def _scam_new_case(now):
    scam_game.update(case_at=now, phase="ask", answered_at=0.0, picked=None, was_correct=False, timed_out=False,
                     gain=0, hinted=False, hint_at=0.0, drag_x=0.0, dragging=False, drag_from=None,
                     fx=set(), time_left=SCAM_TIME, last_tick=None)


def scam_current_case():
    g = scam_game
    return SCAM_CASES[g["queue"][g["i"]]]


def scam_time_left(now):
    g = scam_game
    if g.get("phase") != "ask":
        return g.get("time_left", 0.0)
    if g.get("confirm_quit"):
        now = g.get("pause_at", now)
    return max(0.0, SCAM_TIME - max(0.0, now - g["case_at"] - SCAM_ENTER_T))


def scam_answer(pick):
    g = scam_game
    if g.get("stage") != "play" or g.get("phase") != "ask" or g.get("confirm_quit"):
        return
    now = time.time()
    case = scam_current_case()
    correct = pick == case["answer"]
    left = scam_time_left(now)
    g.update(phase="reveal", answered_at=now, picked=pick, was_correct=correct, timed_out=pick is None,
             time_left=left, dragging=False)
    stats = scam_stats()
    stats["seen"] += 1
    if correct:
        g["combo"] += 1
        g["best_combo"] = max(g["best_combo"], g["combo"])
        pts = (100 + int(50 * left / SCAM_TIME)) * scam_multiplier(g["combo"])
        if g["hinted"]:
            pts //= 2
        g["gain"] = pts
        g["score"] += pts
        g["correct"] += 1
        stats["correct"] += 1
        idx = g["queue"][g["i"]]
        if idx not in state.scam_cracked:
            state.scam_cracked = sorted(set(state.scam_cracked) | {idx})
        if g["correct"] == 1:
            update_challenge("scam")
    else:
        g["combo"] = 0
        g["lives"] -= 1
        g["gain"] = 0
    g["results"].append(correct)
    play_sound("swoosh")


def scam_use_hint():
    g = scam_game
    if g.get("phase") != "ask" or g.get("hinted") or g.get("hints", 0) <= 0 or g.get("confirm_quit"):
        play_sound("error")
        return
    g["hints"] -= 1
    g["hinted"] = True
    g["hint_at"] = time.time()
    play_sound("pop")


def scam_next():
    g = scam_game
    if g.get("phase") != "reveal":
        return
    if g["lives"] <= 0 or g["i"] + 1 >= len(g["queue"]):
        _scam_finish()
    else:
        g["i"] += 1
        _scam_new_case(time.time())
        play_sound("swoosh")


def _scam_finish():
    g = scam_game
    stats = scam_stats()
    rank_before = scam_rank(stats["correct"] - g["correct"])
    stats["runs"] += 1
    new_best = g["score"] > stats["best"] and g["score"] > 0
    stats["best"] = max(stats["best"], g["score"])
    stats["best_combo"] = max(stats["best_combo"], g["best_combo"])
    perfect = g["correct"] >= SCAM_RUN_LEN
    if perfect:
        stats["perfect"] += 1

    # Rewards are shown on the results screen itself, so drop the generic floating "+XP" pops.
    n_ft, n_orb, n_p = len(floating_texts), len(xp_orbs), len(particles)
    today = time.strftime("%Y-%m-%d")
    xp_before = state.xp_earned_today if getattr(state, "xp_day", "") == today else 0
    add_xp(g["correct"] * 8 + (20 if perfect else 0))
    xp_gained = max(0, getattr(state, "xp_earned_today", 0) - xp_before)
    coins = add_coins(g["correct"] * 3 + (15 if perfect else 0))
    if g["correct"]:
        unlock("scam_detective")
    if perfect:
        unlock("scam_perfect")
    del floating_texts[n_ft:]
    del xp_orbs[n_orb:]
    del particles[n_p:]

    letter, col, headline = _scam_grade(g["correct"])
    g.update(stage="results", stage_at=time.time(), xp=xp_gained, coins=coins, new_best=new_best,
             grade=(letter, col, headline), rank_before=rank_before, rank_after=scam_rank(), fx=set())
    save_game()


def _scam_pause(on):
    g = scam_game
    now = time.time()
    if on and not g.get("confirm_quit"):
        g["confirm_quit"] = True
        g["pause_at"] = now
    elif not on and g.get("confirm_quit"):
        g["confirm_quit"] = False
        g["case_at"] += now - g.get("pause_at", now)


def _scam_press(key):
    g = scam_game
    if key == "close":
        if g["stage"] == "play":
            play_sound("click")
            _scam_pause(True)
        else:
            close_scam_game()
    elif key in ("start", "again"):
        start_scam_run()
    elif key in ("scam", "legit"):
        scam_answer(key)
    elif key == "hint":
        scam_use_hint()
    elif key == "next":
        scam_next()
    elif key == "resume":
        play_sound("click")
        _scam_pause(False)
    elif key == "quit":
        _scam_pause(False)
        g.update(stage="lobby", stage_at=time.time())
        play_sound("click")
    elif key == "back":
        close_scam_game()


def handle_scam_game_event(event):
    g = scam_game
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        for key, rect in list(g.get("btns", {}).items()):
            if rect.collidepoint(event.pos):
                _scam_press(key)
                return
        card = g.get("card_rect")
        if (g.get("stage") == "play" and g.get("phase") == "ask" and not g.get("confirm_quit") and card
                and card.collidepoint(event.pos) and time.time() - g["case_at"] > SCAM_ENTER_T * 0.6):
            g["dragging"] = True
            g["drag_from"] = event.pos[0] - g.get("drag_x", 0.0)
    elif event.type == pygame.MOUSEMOTION and g.get("dragging"):
        g["drag_x"] = event.pos[0] - g["drag_from"]
    elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and g.get("dragging"):
        g["dragging"] = False
        if abs(g["drag_x"]) >= SCAM_SWIPE:
            scam_answer("legit" if g["drag_x"] > 0 else "scam")
    elif event.type == pygame.KEYDOWN:
        stage, phase = g.get("stage"), g.get("phase")
        if event.key == pygame.K_ESCAPE:
            if stage == "play" and g.get("confirm_quit"):
                _scam_press("resume")
            else:
                _scam_press("close")
        elif stage == "play" and g.get("confirm_quit"):
            return
        elif stage == "play" and phase == "ask" and event.key in (pygame.K_LEFT, pygame.K_a):
            scam_answer("scam")
        elif stage == "play" and phase == "ask" and event.key in (pygame.K_RIGHT, pygame.K_d):
            scam_answer("legit")
        elif stage == "play" and phase == "ask" and event.key == pygame.K_h:
            scam_use_hint()
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if stage == "lobby":
                start_scam_run()
            elif stage == "play" and phase == "reveal" and time.time() - g["answered_at"] > SCAM_SHEET_T:
                scam_next()
            elif stage == "results" and time.time() - g["stage_at"] > 0.8:
                start_scam_run()


# ---- Drawing helpers ----

def _sg_layer(key, size):
    """Reusable transparent scratch surface, so animations don't allocate a new one every frame."""
    size = (int(math.ceil(size[0])), int(math.ceil(size[1])))
    ck = ("layer", key, size, UI_SCALE)
    s = _sg_cache.get(ck)
    if s is None:
        s = _sg_cache[ck] = HiSurface(size, pygame.SRCALPHA)
    s.fill((0, 0, 0, 0))
    return s


def _sg_glow(color, r, alpha):
    ck = ("glow", tuple(color), r, alpha, UI_SCALE)
    img = _sg_cache.get(ck)
    if img is None:
        img = HiSurface((r * 4, r * 4), pygame.SRCALPHA)
        # Left transparent: the clean look has no glows.
        _sg_cache[ck] = img
    return img


def _sg_background(surface, now, accent=SG_PURPLE):
    surface.fill(SG_BG)


def _sg_button(surface, rect, key, label, bg, fg, font=font_medium_bold, icon=None, depth=5, btns=None):
    """Chunky game button with a darker rim underneath that squishes when pressed."""
    mouse = pygame.mouse.get_pos()
    hovered = rect.collidepoint(mouse)
    pressed = hovered and pygame.mouse.get_pressed()[0]
    depth = 0   # flat buttons
    lift = 0
    rim = bg
    face = rect.move(0, depth - lift)
    pygame.draw.rect(surface, rim, rect.move(0, depth), border_radius=16)
    pygame.draw.rect(surface, mix_color(bg, (255, 255, 255), 0.08) if hovered and not pressed else bg, face, border_radius=16)
    lw = font.size(label)[0]
    gap = 10 if icon else 0
    iw = 18 if icon else 0
    x0 = face.centerx - (lw + iw + gap) // 2
    if icon:
        _sg_icon(surface, icon, x0 + iw // 2, face.centery, fg, 1.0)
    img = font.render(label, True, fg)
    surface.blit(img, img.get_rect(midleft=(x0 + iw + gap, face.centery)))
    (scam_game.setdefault("btns", {}) if btns is None else btns)[key] = rect.inflate(0, depth)


def _sg_close(surface, rect, btns=None):
    hovered = rect.collidepoint(pygame.mouse.get_pos())
    pygame.draw.circle(surface, SG_PANEL_2 if hovered else SG_PANEL, rect.center, rect.w // 2)
    pygame.draw.circle(surface, SG_LINE, rect.center, rect.w // 2, 1)
    c = rect.center
    for a, b in (((-6, -6), (6, 6)), ((6, -6), (-6, 6))):
        pygame.draw.line(surface, SG_TEXT, (c[0] + a[0], c[1] + a[1]), (c[0] + b[0], c[1] + b[1]), 2)
    (scam_game.setdefault("btns", {}) if btns is None else btns)["close"] = rect


def _sg_heart(surface, cx, cy, s, color, width=0):
    r = 5.6 * s
    pts = []
    for i in range(33):
        t = math.tau * i / 32
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * r / 16 * 1.05, cy + y * r / 16 * 1.05 - 0.5 * s))
    pygame.draw.polygon(surface, color, pts, width)


def _sg_check(surface, cx, cy, s, color, width=3):
    pygame.draw.lines(surface, color, False, [(cx - 7 * s, cy), (cx - 2 * s, cy + 5 * s), (cx + 7 * s, cy - 5 * s)], width)


def _sg_cross(surface, cx, cy, s, color, width=3):
    pygame.draw.line(surface, color, (cx - 6 * s, cy - 6 * s), (cx + 6 * s, cy + 6 * s), width)
    pygame.draw.line(surface, color, (cx + 6 * s, cy - 6 * s), (cx - 6 * s, cy + 6 * s), width)


def _sg_shield(surface, cx, cy, s, color, fg):
    pts = [(cx, cy - 20 * s), (cx + 17 * s, cy - 13 * s), (cx + 15 * s, cy + 6 * s), (cx, cy + 20 * s),
           (cx - 15 * s, cy + 6 * s), (cx - 17 * s, cy - 13 * s)]
    pygame.draw.polygon(surface, mix_color(color, (0, 0, 0), 0.3), [(x, y + 3 * s) for x, y in pts])
    pygame.draw.polygon(surface, color, pts)
    draw_star_shape(surface, cx, cy - 1 * s, 8.5 * s, fg)


def _sg_icon(surface, kind, cx, cy, color, s=1.0):
    """Tiny line icons for channels, buttons and tips."""
    w = max(2, int(round(2 * s)))
    if kind == "chat":
        pygame.draw.rect(surface, color, (cx - 8 * s, cy - 6 * s, 16 * s, 11 * s), w, border_radius=int(4 * s))
        pygame.draw.polygon(surface, color, [(cx - 5 * s, cy + 4 * s), (cx - 5 * s, cy + 9 * s), (cx, cy + 4 * s)])
    elif kind == "mail":
        pygame.draw.rect(surface, color, (cx - 8 * s, cy - 6 * s, 16 * s, 12 * s), w, border_radius=int(2 * s))
        pygame.draw.lines(surface, color, False, [(cx - 7 * s, cy - 5 * s), (cx, cy + 1 * s), (cx + 7 * s, cy - 5 * s)], w)
    elif kind == "wave":
        for i, hgt in enumerate((4, 9, 13, 7, 3)):
            x = cx - 8 * s + i * 4 * s
            pygame.draw.line(surface, color, (x, cy - hgt * s / 2), (x, cy + hgt * s / 2), w)
    elif kind == "ad":
        pygame.draw.polygon(surface, color, [(cx - 8 * s, cy - 3 * s), (cx + 6 * s, cy - 8 * s), (cx + 6 * s, cy + 8 * s),
                                             (cx - 8 * s, cy + 3 * s)], w)
        pygame.draw.line(surface, color, (cx - 5 * s, cy + 3 * s), (cx - 3 * s, cy + 8 * s), w)
    elif kind == "window":
        pygame.draw.rect(surface, color, (cx - 8 * s, cy - 7 * s, 16 * s, 14 * s), w, border_radius=int(2 * s))
        pygame.draw.line(surface, color, (cx - 8 * s, cy - 3 * s), (cx + 7 * s, cy - 3 * s), w)
    elif kind == "post":
        pygame.draw.rect(surface, color, (cx - 8 * s, cy - 7 * s, 16 * s, 14 * s), w, border_radius=int(3 * s))
        pygame.draw.polygon(surface, color, [(cx - 6 * s, cy + 5 * s), (cx - 1 * s, cy - 1 * s), (cx + 2 * s, cy + 2 * s),
                                             (cx + 4 * s, cy), (cx + 6 * s, cy + 5 * s)])
    elif kind == "bag":
        pygame.draw.rect(surface, color, (cx - 7 * s, cy - 3 * s, 14 * s, 11 * s), w, border_radius=int(2 * s))
        pygame.draw.arc(surface, color, (cx - 4 * s, cy - 9 * s, 8 * s, 10 * s), 0, math.pi, w)
    elif kind == "bell":
        pygame.draw.polygon(surface, color, [(cx - 6 * s, cy + 4 * s), (cx - 5 * s, cy - 3 * s), (cx, cy - 7 * s),
                                             (cx + 5 * s, cy - 3 * s), (cx + 6 * s, cy + 4 * s)])
        pygame.draw.line(surface, color, (cx - 8 * s, cy + 4 * s), (cx + 8 * s, cy + 4 * s), w)
        pygame.draw.circle(surface, color, (cx, cy + 7 * s), 2 * s)
    elif kind == "lens":
        pygame.draw.circle(surface, color, (cx - 2 * s, cy - 2 * s), 6 * s, w)
        pygame.draw.line(surface, color, (cx + 2.5 * s, cy + 2.5 * s), (cx + 7 * s, cy + 7 * s), w + 1)
    elif kind == "clock":
        pygame.draw.circle(surface, color, (cx, cy), 8 * s, w)
        pygame.draw.lines(surface, color, False, [(cx, cy - 4.5 * s), (cx, cy), (cx + 3.5 * s, cy + 2 * s)], w)
    elif kind == "swipe":
        pygame.draw.line(surface, color, (cx - 8 * s, cy), (cx + 8 * s, cy), w)
        pygame.draw.lines(surface, color, False, [(cx - 4 * s, cy - 4 * s), (cx - 8 * s, cy), (cx - 4 * s, cy + 4 * s)], w)
        pygame.draw.lines(surface, color, False, [(cx + 4 * s, cy - 4 * s), (cx + 8 * s, cy), (cx + 4 * s, cy + 4 * s)], w)
    elif kind == "heart":
        _sg_heart(surface, cx, cy, s * 1.3, color)
    elif kind == "flame":
        draw_flame(surface, cx, cy + 1, 0.85 * s)
    elif kind == "check":
        _sg_check(surface, cx, cy, s, color, w + 1)
    elif kind == "cross":
        _sg_cross(surface, cx, cy, s, color, w + 1)
    elif kind == "warn":
        pts = [(cx, cy - 8 * s), (cx + 9 * s, cy + 7 * s), (cx - 9 * s, cy + 7 * s)]
        pygame.draw.polygon(surface, color, pts, w)
        pygame.draw.line(surface, color, (cx, cy - 2 * s), (cx, cy + 2 * s), w)
        pygame.draw.circle(surface, color, (cx, cy + 4.6 * s), 1.2 * s)
    elif kind == "star":
        draw_star_shape(surface, cx, cy, 8 * s, color)
    elif kind == "bolt":
        pygame.draw.polygon(surface, color, [(cx + 2 * s, cy - 10 * s), (cx - 6 * s, cy + 1 * s), (cx - 0.5 * s, cy + 1 * s),
                                             (cx - 2 * s, cy + 10 * s), (cx + 6 * s, cy - 1 * s), (cx + 0.5 * s, cy - 1 * s)])
    elif kind == "chart":
        pygame.draw.lines(surface, color, False, [(cx - 8 * s, cy + 6 * s), (cx - 3 * s, cy), (cx + 1 * s, cy + 3 * s),
                                                   (cx + 8 * s, cy - 6 * s)], w)
        pygame.draw.polygon(surface, color, [(cx + 9 * s, cy - 8 * s), (cx + 9 * s, cy - 2 * s), (cx + 3 * s, cy - 8 * s)])


def _sg_chip(surface, x, y, label, color, bg, icon=None, h=24, align="left"):
    w = font_tiny.size(label)[0] + 20 + (18 if icon else 0)
    rect = pygame.Rect(x if align == "left" else x - w, y, w, h)
    pygame.draw.rect(surface, bg, rect, border_radius=h // 2)
    tx = rect.x + 10
    if icon:
        _sg_icon(surface, icon, tx + 6, rect.centery, color, 0.72)
        tx += 18
    img = font_tiny.render(label, True, color)
    surface.blit(img, img.get_rect(midleft=(tx, rect.centery)))
    return rect


def _scam_layout(case, font, max_w):
    """Wrap the pitch word by word, tagging each word with the clue (flag) it belongs to."""
    text = case["pitch"]
    low = text.lower()
    spans = []
    for fi, (phrase, _label) in enumerate(case.get("flags", [])):
        start = low.find(phrase.lower())
        if start >= 0:
            spans.append((start, start + len(phrase), fi))
    space = font.size(" ")[0]
    lines, x, pos = [[]], 0, 0
    for word in text.split():
        start = text.index(word, pos)
        pos = start + len(word)
        fi = next((f for a, b, f in spans if start < b and pos > a), None)
        w = font.size(word)[0]
        if lines[-1] and x + space + w > max_w:
            lines.append([])
            x = 0
        elif lines[-1]:
            x += space
        lines[-1].append((word, fi, x, w))
        x += w
    return lines


def _scam_runs(line):
    """Merge neighbouring words of the same clue into one highlight run: (fi, x0, x1)."""
    runs = []
    for word, fi, x, w in line:
        if fi is None:
            continue
        if runs and runs[-1][0] == fi:
            runs[-1][2] = x + w
        else:
            runs.append([fi, x, x + w])
    return runs


def _scam_card_spec(case):
    """Measure a case's card once: wrapped lines and every section's height."""
    ck = ("spec", id(case))
    spec = _sg_cache.get(ck)
    if spec is None:
        chat = case.get("channel") in ("text", "dm", "game")
        text_w = SCAM_CARD_W - 36 - (28 if chat else 0)
        lines = _scam_layout(case, font_body, text_w)
        subject = wrap_text(case["subject"], font_body_bold, SCAM_CARD_W - 36)[:2] if case.get("subject") else []
        body_top = 116 + len(subject) * 22 + (10 if subject else 0) + (30 if case.get("channel") == "call" else 0)
        body_h = len(lines) * SCAM_LINE_H + (22 if chat else 0)
        spec = {"chat": chat, "lines": lines, "subject": subject, "body_top": body_top,
                "h": body_top + body_h + 20}
        _sg_cache[ck] = spec
    return spec


def _scam_draw_card(surface, case, x, y, now, reveal_t=None, hint_t=None, word_t=99.0):
    """The message card. reveal_t animates the clue highlights after a verdict; hint_t shows the magnifier hint."""
    spec = _scam_card_spec(case)
    card = pygame.Rect(x, y, SCAM_CARD_W, spec["h"])
    draw_rounded_rect(surface, card, SG_CARD, radius=22)
    ch_label, ch_col, ch_icon = SCAM_CHANNELS.get(case.get("channel"), SCAM_CHANNELS["text"])

    # Channel + difficulty chips.
    _sg_chip(surface, card.x + 18, card.y + 16, ch_label, ch_col, mix_color(ch_col, SG_CARD, 0.88), icon=ch_icon)
    lv_label, lv_col = SCAM_LEVELS.get(case.get("level", 2), SCAM_LEVELS[2])
    _sg_chip(surface, card.right - 18, card.y + 16, lv_label, lv_col, mix_color(lv_col, SG_CARD, 0.88), align="right")

    # Sender row.
    av = (card.x + 38, card.y + 72)
    pygame.draw.circle(surface, ch_col, av, 20)
    initial = next((ch for ch in case.get("sender", "?") if ch.isalnum()), "?").upper()
    img = font_medium_bold.render(initial, True, (255, 255, 255))
    surface.blit(img, img.get_rect(center=(av[0], av[1] + 1)))
    name_w = card.w - 88 - 18
    draw_text(surface, case.get("sender", ""), font_body_bold, SG_TEXT, card.x + 68, card.y + 53, max_width=name_w)
    draw_text(surface, case.get("handle", ""), font_tiny, SG_CARD_MUTED, card.x + 68, card.y + 75, max_width=name_w)
    pygame.draw.line(surface, SG_CARD_LINE, (card.x + 18, card.y + 104), (card.right - 18, card.y + 104), 1)

    by = card.y + 116
    for line in spec["subject"]:
        draw_text(surface, line, font_body_bold, SG_TEXT, card.x + 18, by, max_width=card.w - 36)
        by += 22
    if case.get("channel") == "call":
        # Voicemail waveform.
        for i in range(34):
            amp = 3 + 9 * abs(math.sin(i * 1.7) * math.cos(i * 0.45))
            xx = card.x + 20 + i * 5
            pygame.draw.line(surface, mix_color(ch_col, SG_CARD, 0.35), (xx, by + 10 - amp / 2), (xx, by + 10 + amp / 2), 2)
        draw_text(surface, "Transcript", font_tiny, SG_CARD_MUTED, card.x + 200, by + 3)

    ty = card.y + spec["body_top"]
    tx = card.x + 18
    if spec["chat"]:
        bubble = pygame.Rect(card.x + 18, ty, card.w - 36, len(spec["lines"]) * SCAM_LINE_H + 22)
        pygame.draw.rect(surface, SG_BUBBLE, bubble, border_radius=18)
        pygame.draw.polygon(surface, SG_BUBBLE, [(bubble.x + 6, bubble.bottom - 16), (bubble.x + 22, bubble.bottom),
                                                 (bubble.x - 3, bubble.bottom + 5)])
        tx, ty = bubble.x + 14, bubble.y + 11

    # Clue highlights sweep in behind the words.
    marks = {}
    if reveal_t is not None:
        kind = "scam" if case["answer"] == "scam" else "legit"
        for fi in range(len(case.get("flags", []))):
            marks[fi] = (kind, ease_out_cubic((reveal_t - 0.35 - fi * 0.14) / 0.3))
    elif hint_t is not None and case.get("flags"):
        marks[0] = ("hint", ease_out_cubic(hint_t / 0.35))
    colored = {}
    for li, line in enumerate(spec["lines"]):
        ly = ty + li * SCAM_LINE_H
        for fi, x0, x1 in _scam_runs(line):
            if fi not in marks:
                continue
            kind, p = marks[fi]
            if p <= 0:
                continue
            bg, fg = SG_HL[kind]
            full = x1 - x0 + 6
            pygame.draw.rect(surface, bg, (tx + x0 - 3, ly, max(4, int(full * p)), SCAM_LINE_H - 1), border_radius=6)
            if p > 0.5:
                colored[fi] = fg
    n = 0
    for li, line in enumerate(spec["lines"]):
        ly = ty + li * SCAM_LINE_H
        for word, fi, x0, w in line:
            a = _clamp01((word_t - n * 0.014) / 0.18)
            n += 1
            if a <= 0:
                continue
            img = font_body.render(word, True, colored.get(fi, SG_TEXT))
            if a < 1:
                img.set_alpha(int(255 * a))
            surface.blit(img, (tx + x0, ly + 1 + int((1 - a) * 4)))
    return card


def _sg_stamp(surface, text, color, center, angle, scale, alpha=255):
    w = font_sg_score.size(text)[0] + 44
    h = 62
    layer = _sg_layer(("stamp", text), (w, h))
    pygame.draw.rect(layer, (*color, 36), (0, 0, w, h), border_radius=12)
    pygame.draw.rect(layer, (*color, 255), (0, 0, w, h), 4, border_radius=12)
    pygame.draw.rect(layer, (*color, 255), (8, 8, w - 16, h - 16), 2, border_radius=8)
    img = font_sg_score.render(text, True, color)
    layer.blit(img, img.get_rect(center=(w // 2, h // 2 + 1)))
    rotated = HiSurface(None, hi=pygame.transform.rotozoom(layer.hi, angle, max(0.05, scale)))
    if alpha < 255:
        rotated.set_alpha(int(max(0, alpha)))
    surface.blit(rotated, rotated.get_rect(center=center).topleft)


def _sg_fx_once(name):
    """True the first time a named effect fires for the current case or screen."""
    fx = scam_game.setdefault("fx", set())
    if name in fx:
        return False
    fx.add(name)
    return True


def _sg_shake(amp):
    if not getattr(state, "reduced_motion", False):
        scam_game["shake_at"] = time.time()
        scam_game["shake_amp"] = amp


def _sg_flash(color):
    scam_game["flash"] = color
    scam_game["flash_at"] = time.time()


# ---- Screens ----

def _scam_draw_lobby(surface, now):
    g = scam_game
    t = now - g["stage_at"]
    calm = getattr(state, "reduced_motion", False)
    _sg_close(surface, pygame.Rect(16, 16, 40, 40))
    stats = scam_stats()

    # Emblem: magnifier with a radar sweep and orbiting messages.
    cx, cy = WIDTH // 2, 158
    pop = 1.0 if calm else _ease_back(t / 0.5)
    draw_soft_ripples(surface, (cx, cy), 58 * pop, SG_PURPLE, now)
    pygame.draw.circle(surface, SG_PANEL_2, (cx, cy), 58 * pop)
    pygame.draw.circle(surface, SG_LINE, (cx, cy), 58 * pop, 2)
    if pop > 0.3:
        sweep = now * 2.2
        pts = [(cx, cy)] + [(cx + math.cos(sweep - k * 0.06) * 50 * pop, cy + math.sin(sweep - k * 0.06) * 50 * pop) for k in range(14)]
        pygame.draw.polygon(surface, mix_color(SG_PANEL_2, SG_CYAN, 0.28), pts)
        pygame.draw.circle(surface, SG_GOLD, (cx - 7, cy - 7), 24 * pop, 6)
        pygame.draw.line(surface, SG_GOLD, (cx + 10 * pop, cy + 10 * pop), (cx + 28 * pop, cy + 28 * pop), 9)
        for k, (col, icon) in enumerate(((SG_RED, "cross"), (SG_GREEN, "check"), (SG_RED, "warn"))):
            a = now * 0.9 + k * math.tau / 3
            ox, oy = cx + math.cos(a) * 92 * pop, cy + math.sin(a) * 34 * pop
            chip = pygame.Rect(0, 0, 34, 26)
            chip.center = (ox, oy)
            pygame.draw.rect(surface, SG_PANEL, chip, border_radius=9)
            pygame.draw.rect(surface, col, chip, 2, border_radius=9)
            _sg_icon(surface, icon, chip.centerx, chip.centery, col, 0.7)

    a = _clamp01((t - 0.15) / 0.4)
    ty = 238 + int((1 - ease_out_cubic(a)) * 14)
    draw_text(surface, "Scam Detective", font_sg_title, SG_TEXT, WIDTH // 2, ty, align="center")
    draw_text(surface, "Spot the scam before it spots you.", font_body, SG_MUTED, WIDTH // 2, ty + 44, align="center")

    # Rank card.
    ri, rname, rcol, floor, nxt = scam_rank()
    card = pygame.Rect(20, 318, WIDTH - 40, 84)
    pygame.draw.rect(surface, SG_PANEL, card, border_radius=20)
    pygame.draw.rect(surface, SG_LINE, card, 1, border_radius=20)
    _sg_shield(surface, card.x + 44, card.centery, 1.15, rcol, SG_PANEL)
    draw_text(surface, "Your rank", font_tiny, SG_MUTED, card.x + 80, card.y + 14)
    draw_text(surface, rname, font_medium_bold, SG_TEXT, card.x + 80, card.y + 30, max_width=card.w - 100)
    bar = pygame.Rect(card.x + 80, card.y + 60, card.w - 100, 8)
    pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=4)
    if nxt:
        frac = (stats["correct"] - floor) / max(1, nxt - floor)
        label = f"{nxt - stats['correct']} more to {SCAM_RANKS[ri + 1][1]}"
    else:
        frac, label = 1.0, "Top rank reached"
    fill = tween("sg_lobby_rank", frac, 5)
    if fill > 0.01:
        pygame.draw.rect(surface, rcol, (bar.x, bar.y, max(8, int(bar.w * fill)), bar.h), border_radius=4)
    draw_text(surface, label, font_tiny, SG_MUTED, card.right - 20, card.y + 14, align="right", max_width=card.w - 200)

    # Stat tiles.
    tiles = [("Best score", f"{stats['best']:,}"), ("Cases cracked", f"{len(state.scam_cracked)}/{len(SCAM_CASES)}"),
             ("Runs played", f"{stats['runs']}")]
    tw = (WIDTH - 40 - 20) // 3
    for k, (lab, val) in enumerate(tiles):
        tile = pygame.Rect(20 + k * (tw + 10), 414, tw, 66)
        pygame.draw.rect(surface, SG_PANEL, tile, border_radius=16)
        draw_text(surface, val, font_medium_bold, SG_TEXT, tile.centerx, tile.y + 12, align="center", max_width=tw - 12)
        draw_text(surface, lab, font_tiny, SG_MUTED, tile.centerx, tile.y + 40, align="center", max_width=tw - 12)

    # How to play.
    how = pygame.Rect(20, 494, WIDTH - 40, 180)
    pygame.draw.rect(surface, SG_PANEL, how, border_radius=20)
    draw_text(surface, "How to play", font_small_bold, SG_TEXT, how.x + 20, how.y + 16)
    rows = [("swipe", SG_CYAN, "Swipe left for scam, right for legit"),
            ("clock", SG_AMBER, "Answer fast for bonus points"),
            ("flame", SG_GOLD, "Keep a streak to multiply your score"),
            ("heart", SG_RED, f"{SCAM_LIVES} lives and {SCAM_HINTS} magnifier hints per run")]
    for k, (icon, col, text) in enumerate(rows):
        ry = how.y + 50 + k * 31
        pygame.draw.circle(surface, mix_color(col, SG_PANEL, 0.78), (how.x + 34, ry + 9), 13)
        _sg_icon(surface, icon, how.x + 34, ry + 9, col, 0.75)
        draw_text(surface, text, font_small, SG_TEXT, how.x + 58, ry, max_width=how.w - 76)

    pulse = 0 if calm else math.sin(now * 3) * 0.5 + 0.5
    btn = pygame.Rect(20, HEIGHT - 86, WIDTH - 40, 60)
    glow = _sg_glow(SG_GOLD, 60, int(30 + 30 * pulse))
    surface.blit(glow, (btn.centerx - 120, btn.centery - 120))
    _sg_button(surface, btn, "start", "Start investigation", SG_GOLD, SG_INK, icon="lens")


def _scam_draw_hud(surface, now, alpha_row2):
    g = scam_game
    _sg_close(surface, pygame.Rect(16, 16, 40, 40))
    # Progress pips.
    n = len(g["queue"])
    x0, x1 = 70, WIDTH - 116
    pw = (x1 - x0 - (n - 1) * 4) / n
    for k in range(n):
        r = pygame.Rect(int(x0 + k * (pw + 4)), 24, int(pw), 7)
        if k < len(g["results"]):
            col = SG_GREEN if g["results"][k] else SG_RED
        elif k == g["i"]:
            col = mix_color(SG_TEXT, SG_PANEL_2, 0.3 + 0.3 * math.sin(now * 5))
        else:
            col = SG_PANEL_2
        pygame.draw.rect(surface, col, r, border_radius=4)
    draw_text(surface, f"Case {g['i'] + 1} of {n}", font_tiny, SG_MUTED, (x0 + x1) // 2, 38, align="center")

    # Lives.
    lost_age = now - g.get("heart_lost_at", 0.0)
    for k in range(SCAM_LIVES):
        hx, hy = WIDTH - 90 + k * 28, 34
        if k < g["lives"]:
            beat = 1 + 0.08 * max(0.0, math.sin(now * 6 - k * 0.5)) if g["lives"] == 1 else 1.0
            _sg_heart(surface, hx, hy, 2.0 * beat, SG_RED)
        elif k == g["lives"] and lost_age < 0.6:
            p = lost_age / 0.6
            _sg_heart(surface, hx, hy, 2.0 * (1 + 0.5 * p), mix_color(SG_RED, SG_BG, p))
            for side in (-1, 1):
                sx_, sy_ = hx + side * (4 + 18 * p), hy + 30 * p * p
                pygame.draw.circle(surface, mix_color(SG_RED, SG_BG, p), (sx_, sy_), 4 * (1 - p) + 1)
        else:
            _sg_heart(surface, hx, hy, 2.0, SG_LINE, 2)

    if alpha_row2 <= 0.01:
        return
    row = _sg_layer("hudrow", (WIDTH, 80))
    draw_text(row, "Score", font_tiny, SG_MUTED, 20, 4)
    shown = tween("sg_score", g["score"], 7)
    draw_text(row, f"{int(round(shown)):,}", font_sg_score, SG_TEXT, 20, 18)
    mult = scam_multiplier(g["combo"]) if g["combo"] else 1
    bump = 1 + 0.25 * max(0.0, 1 - (now - g.get("combo_at", 0.0)) / 0.3)
    label = f"x{mult} combo" if mult > 1 else "No streak yet"
    col = SG_GOLD if mult > 1 else SG_MUTED
    chip_w = font_small_bold.size(label)[0] + (44 if mult > 1 else 28)
    chip = pygame.Rect(0, 0, int(chip_w * bump), int(34 * bump))
    chip.midright = (WIDTH - 20, 34)
    pygame.draw.rect(row, mix_color(col, SG_BG, 0.78), chip, border_radius=chip.h // 2)
    pygame.draw.rect(row, mix_color(col, SG_BG, 0.45), chip, 1, border_radius=chip.h // 2)
    tx = chip.x + 14
    if mult > 1:
        draw_flame(row, tx + 6, chip.centery, 0.9)
        tx += 18
    img = font_small_bold.render(label, True, col)
    row.blit(img, img.get_rect(midleft=(tx, chip.centery)))

    # Timer.
    left = scam_time_left(now)
    frac = left / SCAM_TIME
    bar = pygame.Rect(20, 66, WIDTH - 40, 8)
    pygame.draw.rect(row, SG_PANEL_2, bar, border_radius=4)
    tcol = SG_GREEN if left > 10 else (SG_AMBER if left > 5 else SG_RED)
    if left <= 5 and g["phase"] == "ask":
        tcol = mix_color(tcol, (255, 255, 255), 0.35 * (0.5 + 0.5 * math.sin(now * 14)))
    if frac > 0:
        pygame.draw.rect(row, tcol, (bar.x, bar.y, max(8, int(bar.w * frac)), bar.h), border_radius=4)
    row.set_alpha(int(255 * alpha_row2))
    surface.blit(row, (0, 56))


def _scam_sheet_spec(case):
    ck = ("sheet", id(case))
    spec = _sg_cache.get(ck)
    if spec is None:
        tip = wrap_text(case["why"], font_small, WIDTH - 40 - 40 - 22)
        n = len(case.get("flags", []))
        tip_h = 40 + len(tip) * 20 + 12
        h = 20 + 48 + 16 + 24 + n * 27 + 10 + tip_h + 16 + 56 + 22
        spec = _sg_cache[ck] = {"tip": tip, "tip_h": tip_h, "h": h}
    return spec


def _scam_draw_play(surface, now):
    g = scam_game
    case = scam_current_case()
    calm = getattr(state, "reduced_motion", False)
    spec = _scam_card_spec(case)
    sheet = _scam_sheet_spec(case)
    reveal = g["phase"] == "reveal"
    rt = now - g["answered_at"] if reveal else 0.0
    if calm and reveal:
        rt = max(rt, 1.4)
    ct = 99.0 if calm else now - g["case_at"]

    # Timer: tick in the last five seconds, then time out.
    if g["phase"] == "ask" and not g.get("confirm_quit"):
        left = scam_time_left(now)
        sec = int(math.ceil(left))
        if left <= 5 and sec != g.get("last_tick") and left > 0:
            g["last_tick"] = sec
            play_sound("tick")
        if left <= 0:
            scam_answer(None)
            reveal, rt = True, 0.0

    move = ease_out_cubic((rt - 0.7) / 0.45) if reveal else 0.0
    _scam_draw_hud(surface, now, 1.0 - move)

    # Card position: fly in from the right, follow the drag, then glide up for the verdict.
    ask_top = SCAM_CARD_TOP + max(0, (SCAM_CARD_BOTTOM - SCAM_CARD_TOP - spec["h"]) // 2)
    reveal_top = max(SCAM_CARD_TOP_MIN, min(ask_top, HEIGHT - sheet["h"] - 14 - spec["h"]))
    card_y = ask_top + (reveal_top - ask_top) * move
    dt = min(0.05, now - g.get("last_draw", now))
    if not g.get("dragging"):
        g["drag_x"] *= math.exp(-dt * 16)
    enter = _ease_back(ct / SCAM_ENTER_T, 1.2)
    ox = (1 - enter) * (WIDTH + 40) + g["drag_x"]
    angle = -(1 - enter) * 10 - g["drag_x"] * 0.045
    hint_t = (now - g["hint_at"]) if g.get("hinted") and not reveal else None
    word_t = 99.0 if reveal else ct - SCAM_ENTER_T * 0.6

    pad = 24
    layer = _sg_layer("card", (SCAM_CARD_W + pad * 2, spec["h"] + pad * 2))
    _scam_draw_card(layer, case, pad, pad, now, reveal_t=rt if reveal else None, hint_t=hint_t, word_t=word_t)
    # Swipe feedback: tint and label on the side you're dragging toward.
    dx = g["drag_x"] if not reveal else 0.0
    if abs(dx) > 6:
        k = _clamp01(abs(dx) / SCAM_SWIPE)
        col = SG_GREEN if dx > 0 else SG_RED
        pygame.draw.rect(layer, (*col, int(200 * k)), (pad, pad, SCAM_CARD_W, spec["h"]), 4, border_radius=22)
        lab = "LEGIT" if dx > 0 else "SCAM"
        lx = pad + 34 if dx > 0 else pad + SCAM_CARD_W - 34
        stamp_scale = 0.7 + 0.3 * k
        _sg_stamp(layer, lab, col, (lx + (50 if dx > 0 else -50), pad + 44), 10 if dx > 0 else -10, stamp_scale, 255 * k)
    img = layer
    if abs(angle) > 0.05:
        img = HiSurface(None, hi=pygame.transform.rotozoom(layer.hi, angle, 1.0))
    center = (SCAM_CARD_X + SCAM_CARD_W / 2 + ox, card_y + spec["h"] / 2)
    surface.blit(img, img.get_rect(center=(int(center[0]), int(center[1]))).topleft)
    g["card_rect"] = pygame.Rect(SCAM_CARD_X + int(ox), int(card_y), SCAM_CARD_W, spec["h"])

    if not reveal:
        _scam_draw_answer_bar(surface, now, ct)
    else:
        _scam_draw_verdict(surface, now, case, rt, center, card_y + spec["h"], sheet)
    g["last_draw"] = now

    if g.get("confirm_quit"):
        _scam_draw_quit(surface)


def _scam_draw_answer_bar(surface, now, ct):
    g = scam_game
    appear = ease_out_cubic((ct - 0.2) / 0.4)
    off = int((1 - appear) * 90)
    # Magnifier hint.
    hint_y = HEIGHT - 148 + off
    if g["hinted"]:
        draw_text(surface, "Look closely at the highlighted words", font_small_bold, SG_PURPLE, WIDTH // 2, hint_y + 9, align="center")
    else:
        label = f"Magnifier hint  ({g['hints']} left)" if g["hints"] else "No hints left"
        w = font_small_bold.size(label)[0] + 52
        pill = pygame.Rect(WIDTH // 2 - w // 2, hint_y, w, 36)
        usable = g["hints"] > 0
        hovered = usable and pill.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, SG_PANEL_2 if hovered else SG_PANEL, pill, border_radius=18)
        pygame.draw.rect(surface, SG_PURPLE if usable else SG_LINE, pill, 1, border_radius=18)
        _sg_icon(surface, "lens", pill.x + 22, pill.centery, SG_PURPLE if usable else SG_MUTED, 0.85)
        draw_text(surface, label, font_small_bold, SG_TEXT if usable else SG_MUTED, pill.x + 38, pill.centery - 9)
        if usable:
            g["btns"]["hint"] = pill
    bw = (WIDTH - 40 - 14) // 2
    scam_btn = pygame.Rect(20, HEIGHT - 94 + off, bw, 64)
    legit_btn = pygame.Rect(scam_btn.right + 14, scam_btn.y, bw, 64)
    # Buttons light up as you drag toward them.
    k = _clamp01(abs(g["drag_x"]) / SCAM_SWIPE)
    s_col = mix_color(SG_RED, (255, 255, 255), 0.18 * k) if g["drag_x"] < 0 else SG_RED
    l_col = mix_color(SG_GREEN, (255, 255, 255), 0.18 * k) if g["drag_x"] > 0 else SG_GREEN
    _sg_button(surface, scam_btn, "scam", "Scam", s_col, (255, 255, 255), icon="warn")
    _sg_button(surface, legit_btn, "legit", "Legit", l_col, (255, 255, 255), icon="check")
    draw_text(surface, "Swipe the card, tap a button, or use the arrow keys", font_tiny, SG_MUTED,
              WIDTH // 2, HEIGHT - 20 + off, align="center")


def _scam_draw_verdict(surface, now, case, rt, card_center, card_bottom, sheet):
    g = scam_game
    is_scam = case["answer"] == "scam"
    truth_col = SG_RED if is_scam else SG_GREEN
    correct = g["was_correct"]

    # Stamp slams onto the card, then lifts away so the message stays readable.
    if rt < 1.15:
        t = _clamp01(rt / SCAM_STAMP_T)
        land = _clamp01((rt - SCAM_STAMP_T) / 0.18)
        scale = (2.5 - 1.5 * t * t) if t < 1 else 1 - 0.08 * math.sin(land * math.pi)
        fade = 1 - _clamp01((rt - 0.8) / 0.3)
        scale *= 1 + 0.25 * (1 - fade)
        _sg_stamp(surface, "SCAM" if is_scam else "LEGIT", truth_col, card_center, -12, scale, 255 * min(1.0, t * 1.8) * fade)
    if rt >= SCAM_STAMP_T and _sg_fx_once("land"):
        play_sound("stamp")
        spawn_sparks(card_center[0], card_center[1], truth_col, 26)
        if correct:
            _sg_shake(5)
            _sg_flash(SG_GREEN)
            play_sound("achievement")
            spawn_confetti(28 + 6 * min(4, g["combo"]))
            floating_texts.append(FloatingText(card_center[0], card_center[1] - 40, f"+{g['gain']}", SG_GOLD))
            if g["combo"] >= 2 and g["combo"] % 2 == 0:
                g["combo_at"] = now
                play_sound("combo")
        else:
            _sg_shake(11)
            _sg_flash(SG_RED)
            g["heart_lost_at"] = now
            play_sound("error")
    for fi in range(len(case.get("flags", []))):
        if rt >= 0.35 + fi * 0.14 and _sg_fx_once(f"clue{fi}"):
            play_sound("pop")

    # Verdict sheet slides up from the bottom.
    p = _ease_back((rt - SCAM_SHEET_T) / 0.45, 0.8)
    if p <= 0:
        return
    top = HEIGHT - sheet["h"]
    rect = pygame.Rect(0, int(top + (1 - p) * (sheet["h"] + 30)), WIDTH, sheet["h"] + 40)
    shadow, spad = soft_shadow(rect.w, 60, 28, 14, 120)
    surface.blit(shadow, (rect.x - spad, rect.y - spad - 6))
    pygame.draw.rect(surface, SG_PANEL, rect, border_top_left_radius=28, border_top_right_radius=28)
    pygame.draw.rect(surface, SG_LINE, rect, 1, border_top_left_radius=28, border_top_right_radius=28)
    pygame.draw.rect(surface, SG_LINE, (rect.centerx - 22, rect.y + 9, 44, 4), border_radius=2)
    x, y, w = 20, rect.y + 22, WIDTH - 40

    # Headline.
    head_col = SG_GREEN if correct else (SG_AMBER if g["timed_out"] else SG_RED)
    ic = (x + 22, y + 22)
    pop = _ease_back((rt - SCAM_SHEET_T - 0.1) / 0.35)
    pygame.draw.circle(surface, head_col, ic, 22 * pop)
    if pop > 0.5:
        _sg_icon(surface, "check" if correct else ("clock" if g["timed_out"] else "cross"), ic[0], ic[1], SG_PANEL, 1.1)
    if correct:
        title = random.Random(g["queue"][g["i"]]).choice(["Case cracked!", "Nailed it!", "Sharp eyes!", "Great detective work!"])
    elif g["timed_out"]:
        title = "Time's up!"
    else:
        title = "You got fooled!" if is_scam else "False alarm!"
    sub = "This message is a scam." if is_scam else "This message is legit."
    right_w = 96
    draw_text(surface, title, font_medium_bold, SG_TEXT, x + 56, y + 2, max_width=w - 56 - right_w)
    draw_text(surface, sub, font_small, SG_MUTED, x + 56, y + 26, max_width=w - 56 - right_w)
    if correct:
        mult = scam_multiplier(g["combo"])
        draw_text(surface, f"+{g['gain']}", font_sg_score, SG_GOLD, x + w, y - 2, align="right")
        extra = "hint used" if g["hinted"] else (f"x{mult} combo" if mult > 1 else "points")
        draw_text(surface, extra, font_tiny, SG_MUTED, x + w, y + 32, align="right")
    else:
        draw_text(surface, "-1 life", font_medium_bold, SG_RED, x + w, y + 4, align="right")
        left = g["lives"]
        draw_text(surface, f"{left} left" if left else "Out of lives", font_tiny, SG_MUTED, x + w, y + 30, align="right")
    y += 48 + 16

    # Clues.
    kind_col = SG_RED if is_scam else SG_GREEN
    _sg_icon(surface, "warn" if is_scam else "check", x + 8, y + 9, kind_col, 0.8)
    draw_text(surface, "Red flags" if is_scam else "Good signs", font_small_bold, kind_col, x + 24, y)
    y += 24
    for fi, (_phrase, label) in enumerate(case.get("flags", [])):
        cp = ease_out_cubic((rt - SCAM_SHEET_T - 0.2 - fi * 0.1) / 0.3)
        if cp > 0:
            off = int((1 - cp) * 16)
            pygame.draw.circle(surface, kind_col, (x + 8 + off, y + 10), 4)
            img = font_small.render(label, True, SG_TEXT)
            if cp < 1:
                img.set_alpha(int(255 * cp))
            surface.blit(img, (x + 24 + off, y + 1))
        y += 27
    y += 10

    # Detective tip.
    tp = ease_out_cubic((rt - SCAM_SHEET_T - 0.35) / 0.35)
    tip = pygame.Rect(x, y + int((1 - tp) * 10), w, sheet["tip_h"])
    if tp > 0:
        pygame.draw.rect(surface, SG_PANEL_2, tip, border_radius=16)
        pygame.draw.rect(surface, SG_PURPLE, (tip.x, tip.y + 12, 4, tip.h - 24), border_radius=2)
        _sg_icon(surface, "lens", tip.x + 26, tip.y + 20, SG_PURPLE, 0.8)
        draw_text(surface, "Detective tip", font_small_bold, SG_PURPLE, tip.x + 42, tip.y + 11)
        for i, line in enumerate(sheet["tip"]):
            draw_text(surface, line, font_small, SG_TEXT, tip.x + 20, tip.y + 38 + i * 20, max_width=tip.w - 36)
    y += sheet["tip_h"] + 16

    last = g["lives"] <= 0 or g["i"] + 1 >= len(g["queue"])
    label = "See results" if last else "Next case"
    btn = pygame.Rect(x, y, w, 56)
    if rt > SCAM_SHEET_T + 0.3:
        _sg_button(surface, btn, "next", label, SG_GOLD, SG_INK, icon="star" if last else None)


def _scam_draw_quit(surface):
    blit_color_overlay(surface, SG_BG, 215)
    box = pygame.Rect(34, HEIGHT // 2 - 120, WIDTH - 68, 232)
    pygame.draw.rect(surface, SG_PANEL, box, border_radius=24)
    pygame.draw.rect(surface, SG_LINE, box, 1, border_radius=24)
    draw_text(surface, "Leave this run?", font_large_med, SG_TEXT, box.centerx, box.y + 26, align="center")
    draw_text(surface, "Your score for this run won't count.", font_small, SG_MUTED, box.centerx, box.y + 62, align="center")
    g = scam_game
    g["btns"] = {}
    _sg_button(surface, pygame.Rect(box.x + 20, box.y + 100, box.w - 40, 52), "resume", "Keep playing", SG_GOLD, SG_INK)
    _sg_button(surface, pygame.Rect(box.x + 20, box.y + 164, box.w - 40, 48), "quit", "Quit run", SG_PANEL_2, SG_TEXT,
               font=font_body_bold)


def _scam_draw_results(surface, now):
    g = scam_game
    t = now - g["stage_at"]
    calm = getattr(state, "reduced_motion", False)
    if calm:
        t = max(t, 3.0)
    letter, gcol, headline = g["grade"]
    _sg_close(surface, pygame.Rect(16, 16, 40, 40))
    draw_text(surface, "Case file closed", font_small_bold, SG_MUTED, WIDTH // 2, 28, align="center")

    # Grade badge with spinning rays.
    cx, cy = WIDTH // 2, 158
    rays = _sg_layer("rays", (300, 300))
    for k in range(14):
        a = k * math.tau / 14 + now * 0.35
        pygame.draw.polygon(rays, (*gcol, 34), [(150, 150), (150 + math.cos(a - 0.1) * 150, 150 + math.sin(a - 0.1) * 150),
                                                (150 + math.cos(a + 0.1) * 150, 150 + math.sin(a + 0.1) * 150)])
    surface.blit(rays, (cx - 150, cy - 150))
    st = _clamp01(t / 0.35)
    scale = 2.2 - 1.2 * ease_out_cubic(st)
    r = 70
    pygame.draw.circle(surface, SG_PANEL_2, (cx, cy), r)
    pygame.draw.circle(surface, gcol, (cx, cy), r, 5)
    img = font_sg_grade.render(letter, True, gcol)
    if st < 1:
        img = HiSurface(None, hi=pygame.transform.rotozoom(img.hi, 0, scale))
        img.set_alpha(int(255 * st))
    surface.blit(img, img.get_rect(center=(cx, cy + 3)).topleft)
    if t >= 0.35 and _sg_fx_once("grade"):
        play_sound("stamp")
        _sg_shake(8)
        spawn_sparks(cx, cy, gcol, 30)
        if letter in ("S", "A", "B"):
            play_sound("victory")
            spawn_confetti(70 if letter == "S" else 45)
        else:
            play_sound("bell")

    a = ease_out_cubic((t - 0.4) / 0.4)
    y = 244 + int((1 - a) * 12)
    draw_text(surface, headline, font_large_med, SG_TEXT, WIDTH // 2, y, align="center", max_width=WIDTH - 40)
    sub = "You ran out of lives." if g["lives"] <= 0 else f"You cracked {g['correct']} of {len(g['queue'])} cases."
    draw_text(surface, sub, font_small, SG_MUTED, WIDTH // 2, y + 32, align="center")

    # Score counts up.
    ct = _clamp01((t - 0.6) / 1.0)
    shown = int(g["score"] * ease_out_cubic(ct))
    if 0 < ct < 1 and int(t * 20) != g.get("count_tick"):
        g["count_tick"] = int(t * 20)
        play_sound("tick")
    score_rect = draw_text(surface, f"{shown:,}", font_sg_score, SG_GOLD, WIDTH // 2, 308, align="center")
    draw_text(surface, "Score", font_tiny, SG_MUTED, WIDTH // 2, 346, align="center")
    if g["new_best"] and ct >= 1:
        if _sg_fx_once("best"):
            play_sound("combo")
        wob = math.sin(now * 5) * 4
        chip = pygame.Rect(0, 0, 92, 26)
        chip.midleft = (score_rect.right + 12, score_rect.centery)
        layer = _sg_layer("best", (92, 26))
        pygame.draw.rect(layer, SG_GOLD, (0, 0, 92, 26), border_radius=13)
        lab = font_tiny.render("NEW BEST", True, SG_INK)
        layer.blit(lab, lab.get_rect(center=(46, 13)))
        rot = HiSurface(None, hi=pygame.transform.rotozoom(layer.hi, wob, 1.0))
        surface.blit(rot, rot.get_rect(center=chip.center).topleft)

    # Stat tiles.
    total = max(1, len(g["results"]))
    tiles = [("Correct", f"{g['correct']}/{len(g['queue'])}"), ("Best streak", f"{g['best_combo']}"),
             ("Accuracy", f"{round(100 * g['correct'] / total)}%")]
    tw = (WIDTH - 40 - 20) // 3
    for k, (lab, val) in enumerate(tiles):
        tp = ease_out_cubic((t - 0.9 - k * 0.1) / 0.35)
        if tp <= 0:
            continue
        tile = pygame.Rect(20 + k * (tw + 10), 374 + int((1 - tp) * 16), tw, 66)
        pygame.draw.rect(surface, SG_PANEL, tile, border_radius=16)
        draw_text(surface, val, font_medium_bold, SG_TEXT, tile.centerx, tile.y + 12, align="center", max_width=tw - 12)
        draw_text(surface, lab, font_tiny, SG_MUTED, tile.centerx, tile.y + 40, align="center", max_width=tw - 12)

    # Rewards.
    rp = ease_out_cubic((t - 1.2) / 0.35)
    if rp > 0:
        chips = [(f"+{g['xp']} XP", SG_PURPLE, "star"), (f"+{g['coins']} coins", SG_GOLD, None)]
        widths = [font_small_bold.size(lab)[0] + 52 for lab, _, _ in chips]
        cx0 = WIDTH // 2 - (sum(widths) + 10) // 2
        for (lab, col, icon), w in zip(chips, widths):
            chip = pygame.Rect(cx0, 456 + int((1 - rp) * 10), w, 36)
            pygame.draw.rect(surface, mix_color(col, SG_BG, 0.8), chip, border_radius=18)
            pygame.draw.rect(surface, mix_color(col, SG_BG, 0.5), chip, 1, border_radius=18)
            if icon:
                _sg_icon(surface, icon, chip.x + 20, chip.centery, col, 0.85)
            else:
                draw_coin_icon(surface, chip.x + 20, chip.centery, 9)
            draw_text(surface, lab, font_small_bold, col, chip.x + 36, chip.centery - 9)
            cx0 += w + 10

    # Rank progress, animating from before this run to now.
    kp = ease_out_cubic((t - 1.4) / 0.35)
    if kp > 0:
        ri, rname, rcol, floor, nxt = g["rank_after"]
        ranked_up = g["rank_before"][0] < ri
        card = pygame.Rect(20, 510 + int((1 - kp) * 14), WIDTH - 40, 84)
        pygame.draw.rect(surface, SG_PANEL, card, border_radius=20)
        pygame.draw.rect(surface, rcol if ranked_up else SG_LINE, card, 2 if ranked_up else 1, border_radius=20)
        _sg_shield(surface, card.x + 44, card.centery, 1.15, rcol, SG_PANEL)
        draw_text(surface, "Rank up!" if ranked_up else "Your rank", font_tiny, rcol if ranked_up else SG_MUTED, card.x + 80, card.y + 14)
        draw_text(surface, rname, font_medium_bold, SG_TEXT, card.x + 80, card.y + 30, max_width=card.w - 100)
        total_c = scam_stats()["correct"]
        bar = pygame.Rect(card.x + 80, card.y + 60, card.w - 100, 8)
        pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=4)
        if nxt:
            start = (total_c - g["correct"] - floor) / max(1, nxt - floor) if not ranked_up else 0.0
            end = (total_c - floor) / max(1, nxt - floor)
            label = f"{nxt - total_c} more to {SCAM_RANKS[ri + 1][1]}"
        else:
            start, end, label = 1.0, 1.0, "Top rank reached"
        fill = max(0.0, start) + (end - max(0.0, start)) * ease_out_cubic((t - 1.6) / 0.8)
        if fill > 0.01:
            pygame.draw.rect(surface, rcol, (bar.x, bar.y, max(8, int(bar.w * fill)), bar.h), border_radius=4)
        draw_text(surface, label, font_tiny, SG_MUTED, card.right - 20, card.y + 14, align="right", max_width=card.w - 200)
        if ranked_up and t > 1.6 and _sg_fx_once("rankup"):
            play_sound("achievement")
            spawn_confetti(40)
            show_toast("New detective rank!", f"You are now a {rname}.", "achievement")

    bp = ease_out_cubic((t - 1.5) / 0.35)
    if bp > 0:
        off = int((1 - bp) * 40)
        _sg_button(surface, pygame.Rect(20, HEIGHT - 150 + off, WIDTH - 40, 60), "again", "Play again", SG_GOLD, SG_INK,
                   icon="swipe")
        _sg_button(surface, pygame.Rect(20, HEIGHT - 76 + off, WIDTH - 40, 50), "back", "Back to Learn", SG_PANEL_2, SG_TEXT,
                   font=font_body_bold, depth=4)


def draw_scam_game(surface):
    g = scam_game
    if not g.get("open"):
        return
    now = time.time()
    g["btns"] = {}
    frame = _sg_layer("frame", (WIDTH, HEIGHT))
    accent = SG_PURPLE
    if g["stage"] == "results":
        accent = g["grade"][1]
    _sg_background(frame, now, accent)
    if g["stage"] == "lobby":
        _scam_draw_lobby(frame, now)
    elif g["stage"] == "play":
        _scam_draw_play(frame, now)
    else:
        _scam_draw_results(frame, now)

    sx = sy = 0.0
    k = 1 - (now - g.get("shake_at", 0.0)) / 0.45
    if k > 0:
        amp = g.get("shake_amp", 0.0) * k * k
        sx, sy = math.sin(now * 71) * amp, math.cos(now * 57) * amp * 0.6
    surface.fill(SG_BG)
    surface.blit(frame, (int(sx), int(sy)))
    fk = 1 - (now - g.get("flash_at", 0.0)) / 0.35
    if fk > 0 and g.get("flash"):
        blit_color_overlay(surface, g["flash"], 60 * fk)
    return True


# ---- Learn tab entry card ----

academy_scam_play_btn = None


def draw_scam_entry(surface, y, now):
    """Big arcade-style card on the Learn tab that opens Scam Detective."""
    global academy_scam_play_btn
    stats = scam_stats()
    card = pygame.Rect(20, y, WIDTH - 40, 168)
    academy_scam_play_btn = card
    hovered = card.collidepoint(pygame.mouse.get_pos()) and GAME_TOP <= pygame.mouse.get_pos()[1] <= CONTENT_BOTTOM
    draw_rounded_rect(surface, card, SG_PANEL, radius=22)
    surface.blit(_hero_glow(card.size, [((*SG_PURPLE, 70), (card.w - 70, 40), 90), ((*SG_CYAN, 34), (40, card.h), 70)], 18),
                 card.topleft)
    if hovered:
        pygame.draw.rect(surface, SG_GOLD, card, 2, border_radius=22)

    draw_text(surface, "Arcade", font_tiny, SG_MUTED, card.x + 20, card.y + 18)
    draw_text(surface, "Scam Detective", font_large_med, SG_TEXT, card.x + 20, card.y + 36)
    draw_text(surface, f"{len(SCAM_CASES)} cases to crack", font_small, SG_MUTED, card.x + 20, card.y + 66)
    _ri, rname, rcol, _f, _n = scam_rank()
    chip = _sg_chip(surface, card.x + 20, card.y + 90, rname, rcol, mix_color(rcol, SG_PANEL, 0.78), icon="star")
    if stats["best"]:
        _sg_chip(surface, chip.right + 8, card.y + 90, f"Best {stats['best']:,}", SG_GOLD, mix_color(SG_GOLD, SG_PANEL, 0.8))

    # Mini phone with a message getting scanned.
    phone = pygame.Rect(card.right - 132, card.y + 20, 108, 128)
    bob = math.sin(now * 2) * 3
    phone.y += int(bob)
    pygame.draw.rect(surface, SG_BG, phone.inflate(8, 8), border_radius=18)
    pygame.draw.rect(surface, SG_CARD, phone, border_radius=14)
    pygame.draw.circle(surface, (219, 39, 119), (phone.x + 18, phone.y + 18), 8)
    pygame.draw.rect(surface, SG_CARD_LINE, (phone.x + 32, phone.y + 12, 50, 6), border_radius=3)
    pygame.draw.rect(surface, SG_CARD_LINE, (phone.x + 32, phone.y + 22, 32, 5), border_radius=3)
    for k, lw in enumerate((80, 70, 84, 52)):
        col = SG_HL["scam"][0] if k == 1 else SG_BUBBLE
        pygame.draw.rect(surface, col, (phone.x + 12, phone.y + 40 + k * 14, lw, 9), border_radius=4)
    stamp_t = (now % 3.2) / 3.2
    if stamp_t > 0.55:
        k = _clamp01((stamp_t - 0.55) / 0.08)
        _sg_stamp(surface, "SCAM", SG_RED, (phone.centerx, phone.y + 100), -12, 0.62 * (1.8 - 0.8 * k), 255 * k)
    lens_x = phone.x + 20 + (phone.w - 40) * (0.5 + 0.5 * math.sin(now * 1.6))
    lens_y = phone.y + 58 + math.cos(now * 1.1) * 12
    pygame.draw.circle(surface, SG_GOLD, (lens_x, lens_y), 13, 4)
    pygame.draw.line(surface, SG_GOLD, (lens_x + 9, lens_y + 9), (lens_x + 20, lens_y + 20), 6)

    label = "Play now" if not stats["runs"] else "Play again"
    play = pygame.Rect(card.x + 20, card.bottom - 44, font_small_bold.size(label)[0] + 50, 32)
    pygame.draw.rect(surface, SG_GOLD, play, border_radius=16)
    tri_x = play.x + 18
    pygame.draw.polygon(surface, SG_INK, [(tri_x - 4, play.centery - 6), (tri_x - 4, play.centery + 6), (tri_x + 6, play.centery)])
    draw_text(surface, label, font_small_bold, SG_INK, play.x + 30, play.centery - 9)
    return card.bottom + 22


# ----------------------------
# GAME PAGES (full-screen night look)
# ----------------------------
# Learn, Market, Portfolio, Arena and the Level Road share Scam Detective's look: a night
# background, a compact game HUD instead of the big portfolio header, and a matching tab bar.

# Every screen uses the game look: slim HUD on top, night palette, dark cards.
FULL_TABS = {"home", "academy", "levels", "market", "portfolio", "arena", "news", "leaderboard", "rewards",
             "inventory", "challenges", "analytics", "journal", "settings", "parents"}
GAME_TOP = 76            # content starts below the game HUD
font_sg_h2 = _SysFont(_DISPLAY_FONT, 25, bold=True)


def is_full_tab(tab=None):
    return (tab or state.tab) in FULL_TABS


def tab_top(tab=None):
    return GAME_TOP if is_full_tab(tab) else CONTENT_TOP


def clamp_scroll_full(tab_key, content_height):
    visible_h = CONTENT_BOTTOM - GAME_TOP
    scroll_offset[tab_key] = max(0, min(scroll_offset[tab_key], max(0, content_height - visible_h)))


def draw_game_hud(surface):
    """Avatar, level, coins and trophies in one slim bar. Reuses the header hit boxes so taps work the same."""
    global header_avatar_rect, header_level_rect, header_coin_rect, header_trophy_rect
    now = time.time()
    _sg_background(surface, now)
    # Soft fade under the HUD so scrolled content slides beneath it cleanly.
    shade = _sg_cache.get(("hudshade", UI_SCALE))
    if shade is None:
        shade = HiSurface((WIDTH, GAME_TOP), pygame.SRCALPHA)
        for yy in range(GAME_TOP):
            a = 255 if yy < GAME_TOP - 14 else int(255 * (GAME_TOP - yy) / 14)
            pygame.draw.line(shade, (*mix_color(SG_PANEL, SG_BG, 0.1), a), (0, yy), (WIDTH, yy))
        _sg_cache[("hudshade", UI_SCALE)] = shade
    surface.blit(shade, (0, 0))

    header_avatar_rect = pygame.Rect(16, 14, 46, 46)
    pygame.draw.circle(surface, SG_PANEL_2, header_avatar_rect.center, 23)
    draw_avatar_icon(surface, state.avatar, header_avatar_rect.center, size=42, dark=True)
    draw_avatar_frame(surface, header_avatar_rect.center, 23, equipped("frame")["id"], now)

    x0 = header_avatar_rect.right + 12
    draw_text(surface, state.player_name, font_body_bold, SG_TEXT, x0, 13, max_width=150)
    lv_text = f"Level {state.level}"
    lr = draw_text(surface, lv_text, font_tiny, SG_GOLD if unclaimed_levels() else SG_MUTED, x0, 35)
    if unclaimed_levels():
        pygame.draw.circle(surface, SG_RED, (lr.right + 7, lr.centery), 4)
    bar = pygame.Rect(x0, 54, 118, 6)
    pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=3)
    frac = tween("hud_xp", min(1.0, state.xp / max(1, state.level * 100)), 6)
    if frac > 0.01:
        pygame.draw.rect(surface, SG_PURPLE, (bar.x, bar.y, max(6, int(bar.w * frac)), bar.h), border_radius=3)
    header_level_rect = pygame.Rect(x0 - 2, 10, 130, 54)

    # Right side: trophies then coins.
    league_name, _icon, league_col = get_current_league()
    t_label = f"{state.trophies:,}"
    tw = font_small_bold.size(t_label)[0] + 42
    header_trophy_rect = pygame.Rect(WIDTH - 16 - tw, 20, tw, 32)
    pygame.draw.rect(surface, SG_PANEL, header_trophy_rect, border_radius=16)
    pygame.draw.rect(surface, SG_LINE, header_trophy_rect, 1, border_radius=16)
    draw_trophy_icon(surface, header_trophy_rect.x + 17, header_trophy_rect.centery, SG_GOLD, 0.8)
    draw_text(surface, t_label, font_small_bold, SG_TEXT, header_trophy_rect.x + 31, header_trophy_rect.centery - 9)
    c_label = f"{int(tween('coins_header', rewards_state().coins, 6)):,}"
    cw = font_small_bold.size(c_label)[0] + 42
    header_coin_rect = pygame.Rect(header_trophy_rect.x - 8 - cw, 20, cw, 32)
    pygame.draw.rect(surface, SG_PANEL, header_coin_rect, border_radius=16)
    pygame.draw.rect(surface, SG_LINE, header_coin_rect, 1, border_radius=16)
    draw_coin_icon(surface, header_coin_rect.x + 17, header_coin_rect.centery, 8)
    draw_text(surface, c_label, font_small_bold, SG_TEXT, header_coin_rect.x + 31, header_coin_rect.centery - 9)
    rb = rewards_badge_count()
    if rb:
        draw_count_badge(surface, header_coin_rect.right - 3, header_coin_rect.y + 2, rb)


def draw_trophy_icon(surface, cx, cy, color, s=1.0):
    pygame.draw.polygon(surface, color, [(cx - 8 * s, cy - 9 * s), (cx + 8 * s, cy - 9 * s), (cx + 6 * s, cy + 1 * s),
                                         (cx, cy + 4 * s), (cx - 6 * s, cy + 1 * s)])
    pygame.draw.arc(surface, color, (cx - 13 * s, cy - 9 * s, 9 * s, 9 * s), math.pi / 2, math.pi * 1.5, max(1, int(2 * s)))
    pygame.draw.arc(surface, color, (cx + 4 * s, cy - 9 * s, 9 * s, 9 * s), -math.pi / 2, math.pi / 2, max(1, int(2 * s)))
    pygame.draw.rect(surface, color, (cx - 1.5 * s, cy + 3 * s, 3 * s, 4 * s))
    pygame.draw.rect(surface, color, (cx - 6 * s, cy + 7 * s, 12 * s, 3 * s), border_radius=max(1, int(s)))


def sg_panel(surface, rect, radius=20, border=True, color=SG_PANEL):
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    if border:
        pygame.draw.rect(surface, SG_LINE, rect, 1, border_radius=radius)


def sg_section_title(surface, x, y, title, sub=None):
    draw_text(surface, title, font_medium_bold, SG_TEXT, x, y)
    if sub:
        draw_text(surface, sub, font_small, SG_MUTED, x, y + 26, max_width=WIDTH - 2 * x)
    return y + (50 if sub else 30)


def sg_progress_ring(surface, center, r, frac, color, width=7, track=SG_PANEL_2):
    pygame.draw.circle(surface, track, center, r, width)
    if frac > 0.001:
        steps = max(3, int(64 * frac))
        pts = [(center[0] + math.cos(-math.pi / 2 + math.tau * frac * i / steps) * (r - width / 2),
                center[1] + math.sin(-math.pi / 2 + math.tau * frac * i / steps) * (r - width / 2)) for i in range(steps + 1)]
        pygame.draw.lines(surface, color, False, pts, width)
        for p in (pts[0], pts[-1]):
            pygame.draw.circle(surface, color, p, width / 2)


def sg_stars(surface, x, cy, n, total=3, r=7, gap=17, empty=SG_LINE):
    for k in range(total):
        draw_star_shape(surface, x + r + k * gap, cy, r, SG_GOLD if k < n else empty)
    return x + (total - 1) * gap + 2 * r


def sg_wrap(text, font, width, max_lines=None):
    lines = wrap_text(text, font, width)
    return lines[:max_lines] if max_lines else lines


# ----------------------------
# LEDGER ACADEMY
# ----------------------------

LESSON_XP = 35
_LESSON_INFO = {lid: (d["title"], d["idea"]) for lid, d in LESSONS.items()}
academy_node_rects = []
academy_upnext_btn = None
academy_scenario_btns = []
academy_scenario_next_btn = None
academy_claim_btn = None
lesson_game = {"open": False}
ACADEMY_ZIG = (-72, 72)       # lesson nodes alternate left and right of center
ACADEMY_NODE_GAP = 132
ACADEMY_NODE_R = 32


def academy_path():
    """Lessons in path order with their unit index."""
    return [(u, lid) for u, unit in enumerate(ACADEMY_UNITS) for lid in unit[3] if lid in LESSONS]


def academy_current_lesson():
    return next((lid for _, lid in academy_path() if lid not in state.academy_completed), None)


def lesson_unlocked(lid):
    path = [l for _, l in academy_path()]
    if lid in state.academy_completed:
        return True
    i = path.index(lid) if lid in path else 0
    return all(p in state.academy_completed for p in path[:i])


def lesson_unit(lid):
    return next((u for u, l in academy_path() if l == lid), 0)


def unit_color(u):
    return ACADEMY_UNITS[u][2]


def _next_lesson_after(lid):
    path = [l for _, l in academy_path()]
    for l in path[path.index(lid) + 1:] if lid in path else []:
        if l not in state.academy_completed:
            return l
    return None


def _lesson_node(surface, cx, cy, r, col, glyph, status, now, lift=0.0):
    """3D lesson button: darker rim underneath, bright face, icon on top."""
    locked = status == "locked"
    face = SG_PANEL_2 if locked else col
    rim = SG_LINE if locked else mix_color(col, (0, 0, 0), 0.38)
    cy -= lift
    pygame.draw.circle(surface, rim, (cx, cy + 6), r)
    pygame.draw.circle(surface, face, (cx, cy), r)
    if not locked:
        pygame.draw.circle(surface, mix_color(face, (255, 255, 255), 0.25), (cx, cy), r, 3)
    if locked:
        draw_padlock(surface, cx, cy, 20, SG_MUTED)
    else:
        draw_glyph(surface, glyph, cx, cy, text_on_game(face), 1.15)
    if status == "done":
        badge = (cx + r * 0.72, cy - r * 0.72)
        pygame.draw.circle(surface, SG_BG, badge, 11)
        pygame.draw.circle(surface, SG_GREEN, badge, 9)
        _sg_check(surface, badge[0], badge[1] + 0.5, 0.6, SG_BG, 2)


def text_on_game(fill):
    return SG_TEXT if _luminance(fill) > 0.45 else (255, 255, 255)


def draw_academy_tab(surface):
    global academy_node_rects, academy_upnext_btn, academy_scenario_btns, academy_scenario_next_btn
    global academy_claim_btn, academy_scam_play_btn
    academy_node_rects = []
    academy_scenario_btns = []
    academy_upnext_btn = academy_scenario_next_btn = academy_claim_btn = academy_scam_play_btn = None
    now = time.time()
    off = scroll_offset["academy"]
    clip = pygame.Rect(0, GAME_TOP, WIDTH, CONTENT_BOTTOM - GAME_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y0 = GAME_TOP + 6 - off
    y = y0
    path = academy_path()
    done_n = sum(1 for _, l in path if l in state.academy_completed)
    stars_total = sum(getattr(state, "academy_stars", {}).get(l, 0) for _, l in path)

    # Hero: title, streak, stars and a course progress ring.
    hero = pygame.Rect(20, y, WIDTH - 40, 150)
    pygame.draw.rect(surface, SG_PANEL, hero, border_radius=24)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    surface.blit(_hero_glow(hero.size, [((*SG_PURPLE, 80), (hero.w - 70, 50), 90), ((*SG_CYAN, 36), (30, hero.h), 70)], 18),
                 hero.topleft)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    draw_text(surface, "Ledger Academy", font_tiny, SG_MUTED, hero.x + 20, hero.y + 20)
    draw_text(surface, "35 short lessons", font_sg_h2, SG_TEXT, hero.x + 20, hero.y + 38)
    draw_text(surface, "on how money works", font_sg_h2, SG_TEXT, hero.x + 20, hero.y + 68)
    streak = int(getattr(state, "learning_streak", 0))
    chip = _sg_chip(surface, hero.x + 20, hero.y + 110, f"{streak}-day streak", SG_AMBER, mix_color(SG_AMBER, SG_BG, 0.8), icon="flame", h=26)
    _sg_chip(surface, chip.right + 8, hero.y + 110, f"{stars_total} stars", SG_GOLD, mix_color(SG_GOLD, SG_BG, 0.82), icon="star", h=26)
    rc = (hero.right - 64, hero.y + 72)
    frac = tween("academy_ring", done_n / max(1, len(path)), 5)
    sg_progress_ring(surface, rc, 44, frac, SG_GOLD, 8)
    draw_text(surface, f"{done_n}/{len(path)}", font_medium_bold, SG_TEXT, rc[0], rc[1] - 16, align="center")
    draw_text(surface, "lessons", font_tiny, SG_MUTED, rc[0], rc[1] + 5, align="center")
    y = hero.bottom + 14

    # Up next: the one big button that always continues the course.
    cur = academy_current_lesson()
    card = pygame.Rect(20, y, WIDTH - 40, 92)
    if cur:
        u = lesson_unit(cur)
        col = unit_color(u)
        hovered = card.collidepoint(pygame.mouse.get_pos())
        sg_panel(surface, card, 20, border=False, color=SG_PANEL_2 if hovered else SG_PANEL)
        pygame.draw.rect(surface, col, card, 2, border_radius=20)
        _lesson_node(surface, card.x + 46, card.centery - 3, 26, col, LESSONS[cur]["glyph"], "current", now,
                     lift=abs(math.sin(now * 3)) * 3)
        n_in_unit = ACADEMY_UNITS[u][3].index(cur) + 1
        draw_text(surface, f"Up next  ·  Unit {u + 1}, lesson {n_in_unit}", font_tiny, col, card.x + 88, card.y + 18,
                  max_width=card.w - 200)
        draw_text(surface, LESSONS[cur]["title"], font_medium_bold, SG_TEXT, card.x + 88, card.y + 36, max_width=card.w - 200)
        draw_text(surface, f"+{LESSON_XP} XP  ·  3 cards + quiz", font_tiny, SG_MUTED, card.x + 88, card.y + 62, max_width=card.w - 200)
        go = pygame.Rect(card.right - 104, card.centery - 20, 88, 40)
        pygame.draw.rect(surface, mix_color(SG_GOLD, (0, 0, 0), 0.35), go.move(0, 4), border_radius=14)
        pygame.draw.rect(surface, SG_GOLD, go, border_radius=14)
        draw_text(surface, "Start", font_body_bold, SG_INK, go.centerx, go.centery - 10, align="center")
        academy_upnext_btn = card
    else:
        sg_panel(surface, card, 20)
        draw_trophy_icon(surface, card.x + 46, card.centery, SG_GOLD, 1.6)
        draw_text(surface, "Course complete!", font_medium_bold, SG_TEXT, card.x + 88, card.y + 24)
        draw_text(surface, "Replay any lesson to earn all 3 stars.", font_small, SG_MUTED, card.x + 88, card.y + 50)
    y = card.bottom + 14

    # Daily challenge.
    c = current_challenge()
    ready = state.challenge_progress >= c["goal"] and not state.challenge_claimed
    card = pygame.Rect(20, y, WIDTH - 40, 88)
    sg_panel(surface, card, 20, border=not ready)
    if ready:
        pygame.draw.rect(surface, SG_GOLD, card, 2, border_radius=20)
    draw_chest(surface, card.x + 44, card.centery + 2, 46, "rare", shake=math.sin(now * 12) * 2 if ready else 0)
    tx = card.x + 88
    draw_text(surface, "Daily challenge", font_tiny, SG_GOLD, tx, card.y + 16)
    draw_text(surface, c["title"], font_body_bold, SG_TEXT, tx, card.y + 34, max_width=card.right - 120 - tx)
    bar = pygame.Rect(tx, card.y + 62, card.right - 128 - tx, 8)
    pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=4)
    pf = tween("academy_challenge", min(1.0, state.challenge_progress / max(1, c["goal"])), 6)
    if pf > 0.01:
        pygame.draw.rect(surface, SG_GOLD, (bar.x, bar.y, max(8, int(bar.w * pf)), bar.h), border_radius=4)
    right = pygame.Rect(card.right - 108, card.centery - 20, 92, 40)
    if ready:
        pygame.draw.rect(surface, mix_color(SG_GOLD, (0, 0, 0), 0.35), right.move(0, 4), border_radius=14)
        pygame.draw.rect(surface, SG_GOLD, right, border_radius=14)
        draw_text(surface, "Claim", font_body_bold, SG_INK, right.centerx, right.centery - 10, align="center")
        academy_claim_btn = right
    elif state.challenge_claimed:
        pygame.draw.circle(surface, SG_GREEN, right.center, 16)
        _sg_check(surface, right.centerx, right.centery, 0.9, SG_BG, 3)
    else:
        draw_text(surface, f"+{c['reward']} XP", font_small_bold, SG_GOLD, right.centerx, right.y + 2, align="center")
        draw_text(surface, f"{min(state.challenge_progress, c['goal'])}/{c['goal']}", font_tiny, SG_MUTED, right.centerx, right.y + 22,
                  align="center")
    y = card.bottom + 14

    y = draw_scam_entry(surface, y, now)

    # The course map.
    y = sg_section_title(surface, 20, y, "Your course", f"{len(ACADEMY_UNITS)} units  ·  {len(path)} lessons  ·  finish one to unlock the next")
    for u, (name, tagline, col, ids) in enumerate(ACADEMY_UNITS):
        unit_done = sum(1 for l in ids if l in state.academy_completed)
        unit_open = lesson_unlocked(ids[0])
        perfect = unit_done == len(ids) and all(getattr(state, "academy_stars", {}).get(l, 0) >= 3 for l in ids)
        banner = pygame.Rect(20, y, WIDTH - 40, 84)
        if banner.bottom > GAME_TOP - 20 and banner.y < CONTENT_BOTTOM + 20:
            base = col if unit_open else SG_PANEL_2
            pygame.draw.rect(surface, mix_color(base, (0, 0, 0), 0.4), banner.move(0, 5), border_radius=22)
            pygame.draw.rect(surface, base, banner, border_radius=22)
            glow = _sg_glow((255, 255, 255), 50, 40 if unit_open else 0)
            surface.blit(glow, (banner.right - 110 - 100, banner.y - 100 + 10))
            fg = text_on_game(base) if unit_open else SG_MUTED
            sub = mix_color(fg, base, 0.3)
            draw_text(surface, f"UNIT {u + 1}", font_tiny, sub, banner.x + 20, banner.y + 14)
            draw_text(surface, name, font_medium_bold, fg, banner.x + 20, banner.y + 31, max_width=banner.w - 130)
            draw_text(surface, tagline, font_small, sub, banner.x + 20, banner.y + 55, max_width=banner.w - 130)
            rc = (banner.right - 44, banner.centery)
            if unit_open:
                sg_progress_ring(surface, rc, 26, unit_done / len(ids), fg, 5, track=mix_color(base, (0, 0, 0), 0.25))
                if perfect:
                    draw_crown(surface, rc[0], rc[1], fg)
                else:
                    draw_text(surface, f"{unit_done}/{len(ids)}", font_small_bold, fg, rc[0], rc[1] - 9, align="center")
            else:
                draw_padlock(surface, rc[0], rc[1], 22, SG_MUTED)
        y = banner.bottom + 44

        nodes = []
        for k, lid in enumerate(ids):
            nodes.append((lid, WIDTH // 2 + ACADEMY_ZIG[k % 2], y + ACADEMY_NODE_R))
            y += ACADEMY_NODE_GAP
        y -= ACADEMY_NODE_GAP - ACADEMY_NODE_R * 2 - 36
        r = ACADEMY_NODE_R
        # Dotted trail between lessons. It stops short of every button so nothing overlaps.
        for (la, ax, ay), (lb, bx, by_) in zip(nodes, nodes[1:]):
            lit = la in state.academy_completed and lb in state.academy_completed
            dcol = col if lit else SG_LINE
            p0, p3 = (ax, ay), (bx, by_ + 6)
            c1, c2 = (ax, ay + 70), (bx, by_ - 64)
            steps = 30
            for s_i in range(steps + 1):
                t = s_i / steps
                mt = 1 - t
                px = mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p3[0]
                py = mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p3[1]
                if math.hypot(px - ax, py - ay) < r + 16 or math.hypot(px - bx, py - by_) < r + 16:
                    continue
                if s_i % 2 == 0:
                    pygame.draw.circle(surface, dcol, (px, py), 3.5)
        for k, (lid, cx, cy) in enumerate(nodes):
            info = LESSONS[lid]
            done = lid in state.academy_completed
            is_cur = lid == cur
            locked = not lesson_unlocked(lid)
            status = "done" if done else ("current" if is_cur else ("locked" if locked else "open"))
            if GAME_TOP - 90 < cy < CONTENT_BOTTOM + 90:
                lift = 0.0
                if is_cur:
                    draw_soft_ripples(surface, (cx, cy), r, col, now)
                    lift = abs(math.sin(now * 2.6)) * 4
                _lesson_node(surface, cx, cy, r, col, info["glyph"], status, now, lift)
                # Label on the open side: title, then stars / start / locked on the second row.
                side = 1 if cx < WIDTH // 2 else -1
                lx = cx + side * (r + 18)
                lw = (WIDTH - 22 - lx) if side > 0 else (lx - 22)
                lines = sg_wrap(info["title"], font_body_bold, lw, 2)
                block_h = len(lines) * 20 + 26
                ty = cy - block_h // 2
                align = "left" if side > 0 else "right"
                for i, line in enumerate(lines):
                    draw_text(surface, line, font_body_bold, SG_MUTED if locked else SG_TEXT, lx, ty + i * 20, align=align, max_width=lw)
                ry = ty + len(lines) * 20 + 4
                if done:
                    n_st = getattr(state, "academy_stars", {}).get(lid, 3)
                    sx = lx if side > 0 else lx - 48
                    sg_stars(surface, sx, ry + 10, n_st, r=7, gap=17)
                elif is_cur:
                    label = f"Start  +{LESSON_XP} XP"
                    cw = font_tiny.size(label)[0] + 20
                    chip = pygame.Rect(lx if side > 0 else lx - cw, ry, cw, 22)
                    pygame.draw.rect(surface, SG_GOLD, chip, border_radius=11)
                    draw_text(surface, label, font_tiny, SG_INK, chip.centerx, chip.y + 3, align="center")
                else:
                    draw_text(surface, "Locked" if locked else "Ready", font_tiny, SG_MUTED, lx, ry + 3, align=align)
            hit = pygame.Rect(cx - r - 8, cy - r - 8, (r + 8) * 2, (r + 8) * 2)
            academy_node_rects.append((hit, lid, locked))
        y += 18

    # Practice: What would you do?
    y = sg_section_title(surface, 20, y + 6, "What would you do?", "Real situations. No perfect answer, just smarter ones.")
    idx = state.scenario_index
    scenario = WHAT_WOULD_YOU_DO[idx]
    answered = getattr(state, "scenario_answered", False)
    picked = getattr(state, "scenario_pick", None)
    order = _shuffled(len(scenario["choices"]), f"wwyd{idx}")
    best = scenario.get("best", 1)
    title_lines = sg_wrap(scenario["title"], font_body_bold, WIDTH - 80)
    info_lines = sg_wrap(scenario["best_info"], font_small, WIDTH - 80) if answered else []
    sc_h = 48 + len(title_lines) * 22 + len(order) * 58 + (len(info_lines) * 20 + 96 if answered else 6)
    sc = pygame.Rect(20, y, WIDTH - 40, sc_h)
    sg_panel(surface, sc, 22)
    draw_text(surface, f"Situation {idx + 1} of {len(WHAT_WOULD_YOU_DO)}", font_tiny, SG_PURPLE, sc.x + 20, sc.y + 18)
    ty = sc.y + 38
    for line in title_lines:
        draw_text(surface, line, font_body_bold, SG_TEXT, sc.x + 20, ty)
        ty += 22
    by = ty + 10
    for slot, ci in enumerate(order):
        br = pygame.Rect(sc.x + 16, by, sc.w - 32, 48)
        if answered and ci == best:
            bg, fg, bd = mix_color(SG_GREEN, SG_PANEL, 0.75), SG_TEXT, SG_GREEN
        elif answered and ci == picked:
            bg, fg, bd = mix_color(SG_AMBER, SG_PANEL, 0.8), SG_TEXT, SG_AMBER
        else:
            hov = not answered and br.collidepoint(pygame.mouse.get_pos())
            bg, fg, bd = (SG_PANEL_2 if hov else mix_color(SG_PANEL_2, SG_PANEL, 0.5)), SG_TEXT, SG_LINE
        pygame.draw.rect(surface, bg, br, border_radius=14)
        pygame.draw.rect(surface, bd, br, 1, border_radius=14)
        draw_text(surface, scenario["choices"][ci], font_small_bold, fg, br.x + 16, br.centery - 9, max_width=br.w - 32)
        academy_scenario_btns.append((br, ci))
        by += 58
    if answered:
        good = picked == best
        draw_text(surface, "Great thinking!  +20 XP" if good else "Here's a smarter move.  +5 XP", font_body_bold,
                  SG_GREEN if good else SG_AMBER, sc.x + 20, by + 4)
        for i, line in enumerate(info_lines):
            draw_text(surface, line, font_small, SG_MUTED, sc.x + 20, by + 32 + i * 20)
        academy_scenario_next_btn = pygame.Rect(sc.x + 16, by + 38 + len(info_lines) * 20, sc.w - 32, 44)
        _draw_plain_button(surface, academy_scenario_next_btn, "Next situation", SG_PANEL_2, SG_TEXT)
    y = sc.bottom + 30
    clamp_scroll_full("academy", y - y0 + 6)
    surface.set_clip(prev)


def _draw_plain_button(surface, rect, label, bg, fg, font=font_body_bold, depth=4):
    hovered = rect.collidepoint(pygame.mouse.get_pos())
    pressed = hovered and pygame.mouse.get_pressed()[0]
    lift = 1 if pressed else depth
    pygame.draw.rect(surface, mix_color(bg, (0, 0, 0), 0.35), rect.move(0, depth), border_radius=14)
    face = rect.move(0, depth - lift)
    pygame.draw.rect(surface, mix_color(bg, (255, 255, 255), 0.07) if hovered else bg, face, border_radius=14)
    img = font.render(label, True, fg)
    surface.blit(img, img.get_rect(center=face.center))


def draw_crown(surface, cx, cy, color):
    pts = [(cx - 12, cy + 7), (cx - 12, cy - 5), (cx - 6, cy + 1), (cx, cy - 9), (cx + 6, cy + 1), (cx + 12, cy - 5), (cx + 12, cy + 7)]
    pygame.draw.polygon(surface, color, pts)


def handle_academy_click(pos):
    if not (GAME_TOP <= pos[1] <= CONTENT_BOTTOM):
        return
    if academy_claim_btn and academy_claim_btn.collidepoint(pos):
        if claim_challenge():
            spawn_confetti(50)
        return
    if academy_upnext_btn and academy_upnext_btn.collidepoint(pos):
        open_lesson_game(academy_current_lesson())
        return
    if academy_scam_play_btn and academy_scam_play_btn.collidepoint(pos):
        open_scam_game()
        return
    for rect, lid, locked in academy_node_rects:
        if rect.collidepoint(pos):
            if locked:
                play_sound("error")
                show_toast("Lesson locked", "Finish the lessons before it to unlock this one.", "warning")
            else:
                open_lesson_game(lid)
            return
    if academy_scenario_next_btn and academy_scenario_next_btn.collidepoint(pos):
        play_sound("click")
        next_scenario()
        return
    for rect, index in academy_scenario_btns:
        if rect.collidepoint(pos):
            scenario_answer(index)
            return


# ---- Lesson game ----

LESSON_CARDS = [("idea", "Key idea", "bolt", SG_GOLD), ("example", "Real-life example", "chart", SG_CYAN),
                ("tip", "Pro tip", "star", SG_PURPLE)]


def open_lesson_game(lid):
    if not lid or lid not in LESSONS:
        return
    now = time.time()
    quiz = []
    for q, choices, why in LESSONS[lid]["quiz"]:
        order = list(range(len(choices)))
        random.shuffle(order)
        quiz.append({"q": q, "choices": [choices[i] for i in order], "correct": order.index(0), "why": why})
    lesson_game.clear()
    lesson_game.update(open=True, id=lid, stage="learn", stage_at=now, card=0, card_at=now, fly_from=None,
                       quiz=quiz, qi=0, picked=None, picked_at=0.0, right=0, combo=0, results=[],
                       btns={}, fx=set(), shake_at=0.0, shake_amp=0.0, flash=None, flash_at=0.0,
                       drag_x=0.0, dragging=False, drag_from=0, last_draw=now)
    drag_state["active"] = False
    play_sound("swoosh")


def close_lesson_game():
    lesson_game["open"] = False
    play_sound("click")
    save_game()


def _lg_fx_once(name):
    if name in lesson_game["fx"]:
        return False
    lesson_game["fx"].add(name)
    return True


def _lg_shake(amp):
    if not getattr(state, "reduced_motion", False):
        lesson_game["shake_at"] = time.time()
        lesson_game["shake_amp"] = amp


def lesson_next_card():
    g = lesson_game
    if g.get("stage") != "learn":
        return
    now = time.time()
    if g["card"] < len(LESSON_CARDS) - 1:
        g["fly_from"] = (g["card"], now, -1)
        g["card"] += 1
        g["card_at"] = now
        play_sound("swoosh")
    else:
        g.update(stage="quiz", stage_at=now, qi=0, picked=None, card_at=now)
        play_sound("swoosh")


def lesson_prev_card():
    g = lesson_game
    if g.get("stage") == "learn" and g["card"] > 0:
        g["fly_from"] = None
        g["card"] -= 1
        g["card_at"] = time.time()
        play_sound("click")


def lesson_answer(ci):
    g = lesson_game
    if g.get("stage") != "quiz" or g.get("picked") is not None:
        return
    now = time.time()
    q = g["quiz"][g["qi"]]
    g["picked"] = ci
    g["picked_at"] = now
    ok = ci == q["correct"]
    g["results"].append(ok)
    g["fx"] = set()
    if ok:
        g["right"] += 1
        g["combo"] += 1
    else:
        g["combo"] = 0


def lesson_continue():
    g = lesson_game
    now = time.time()
    if g["qi"] + 1 < len(g["quiz"]):
        g["qi"] += 1
        g["picked"] = None
        g["card_at"] = now
        g["fx"] = set()
        play_sound("swoosh")
    else:
        _lesson_finish()


def _lesson_finish():
    g = lesson_game
    lid = g["id"]
    passed = g["right"] >= 2
    stars = g["right"] if passed else 0
    first_time = passed and lid not in state.academy_completed
    old_stars = getattr(state, "academy_stars", {}).get(lid, 0)
    n_ft, n_orb, n_p = len(floating_texts), len(xp_orbs), len(particles)
    today = time.strftime("%Y-%m-%d")
    xp_before = state.xp_earned_today if getattr(state, "xp_day", "") == today else 0
    coins = 0
    if passed:
        state.academy_stars = dict(getattr(state, "academy_stars", {}))
        state.academy_stars[lid] = max(old_stars, stars)
        if first_time:
            state.academy_completed.append(lid)
            add_xp(LESSON_XP)
            coins += add_coins(15)
            update_challenge("academy")
        if stars == 3 and old_stars < 3:
            coins += add_coins(10)
            add_xp(10)
        if state.last_learning_day != today:
            yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
            state.learning_streak = (state.learning_streak + 1) if state.last_learning_day == yesterday else 1
            state.last_learning_day = today
        check_achievements()
    xp_gained = max(0, getattr(state, "xp_earned_today", 0) - xp_before)
    del floating_texts[n_ft:]
    del xp_orbs[n_orb:]
    del particles[n_p:]
    g.update(stage="done", stage_at=time.time(), passed=passed, stars=stars, first_time=first_time, xp=xp_gained,
             coins=coins, fx=set(), unit_done=all(l in state.academy_completed for l in ACADEMY_UNITS[lesson_unit(lid)][3]))
    save_game()


def _lesson_press(key):
    g = lesson_game
    if key == "close":
        close_lesson_game()
    elif key == "next_card":
        lesson_next_card()
    elif key == "prev_card":
        lesson_prev_card()
    elif key.startswith("choice_"):
        lesson_answer(int(key.split("_")[1]))
    elif key == "continue":
        lesson_continue()
    elif key == "retry":
        open_lesson_game(g["id"])
        lesson_game.update(stage="quiz", stage_at=time.time(), card_at=time.time())
    elif key == "review":
        open_lesson_game(g["id"])
    elif key == "next_lesson":
        nxt = _next_lesson_after(g["id"])
        if nxt:
            open_lesson_game(nxt)
        else:
            close_lesson_game()
    elif key == "back":
        close_lesson_game()


def handle_lesson_game_event(event):
    g = lesson_game
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        for key, rect in list(g.get("btns", {}).items()):
            if rect.collidepoint(event.pos):
                _lesson_press(key)
                return
        card = g.get("card_rect")
        if g.get("stage") == "learn" and card and card.collidepoint(event.pos):
            g["dragging"] = True
            g["drag_from"] = event.pos[0]
            g["drag_x"] = 0.0
    elif event.type == pygame.MOUSEMOTION and g.get("dragging"):
        g["drag_x"] = event.pos[0] - g["drag_from"]
    elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and g.get("dragging"):
        g["dragging"] = False
        if g["drag_x"] <= -90:
            g["drag_x"] = 0.0
            lesson_next_card()
        elif g["drag_x"] >= 90:
            g["drag_x"] = 0.0
            lesson_prev_card()
        elif abs(g["drag_x"]) < 8:
            g["drag_x"] = 0.0
            lesson_next_card()
    elif event.type == pygame.KEYDOWN:
        stage = g.get("stage")
        if event.key == pygame.K_ESCAPE:
            close_lesson_game()
        elif stage == "learn" and event.key in (pygame.K_RIGHT, pygame.K_RETURN, pygame.K_SPACE):
            lesson_next_card()
        elif stage == "learn" and event.key == pygame.K_LEFT:
            lesson_prev_card()
        elif stage == "quiz" and g.get("picked") is None and event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_a, pygame.K_b, pygame.K_c):
            k = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_a: 0, pygame.K_b: 1, pygame.K_c: 2}[event.key]
            lesson_answer(k)
        elif stage == "quiz" and g.get("picked") is not None and event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if time.time() - g["picked_at"] > 0.6:
                lesson_continue()
        elif stage == "done" and event.key in (pygame.K_RETURN, pygame.K_SPACE) and time.time() - g["stage_at"] > 1.0:
            _lesson_press("next_lesson" if g.get("passed") else "retry")


def _lg_button(surface, rect, key, label, bg, fg, font=font_medium_bold, icon=None, depth=5):
    """Scam Detective's chunky button, registered on the lesson game."""
    _sg_button(surface, rect, key, label, bg, fg, font=font, icon=icon, depth=depth, btns=lesson_game["btns"])


def _lg_topbar(surface, now, col, steps_done, total_steps):
    g = lesson_game
    close = pygame.Rect(16, 16, 40, 40)
    _sg_close(surface, close, g["btns"])
    x0, x1 = 70, WIDTH - 20
    pw = (x1 - x0 - (total_steps - 1) * 5) / total_steps
    for k in range(total_steps):
        r = pygame.Rect(int(x0 + k * (pw + 5)), 29, int(pw), 8)
        pygame.draw.rect(surface, SG_PANEL_2, r, border_radius=4)
        fill = tween(("lg_pip", k), 1.0 if k < steps_done else 0.0, 9)
        if fill > 0.02:
            pygame.draw.rect(surface, col, (r.x, r.y, max(8, int(r.w * fill)), r.h), border_radius=4)


def _lg_draw_learn(surface, now, info, col):
    g = lesson_game
    u = lesson_unit(g["id"])
    _lg_topbar(surface, now, col, g["card"] + 1, len(LESSON_CARDS) + 3)
    t = now - g["stage_at"]
    a = ease_out_cubic(t / 0.4)
    draw_text(surface, f"Unit {u + 1}  ·  {ACADEMY_UNITS[u][0]}", font_small_bold, col, 20, 66 + int((1 - a) * 8))
    title_lines = sg_wrap(info["title"], font_sg_h2, WIDTH - 40, 2)
    for i, line in enumerate(title_lines):
        draw_text(surface, line, font_sg_h2, SG_TEXT, 20, 88 + i * 32 + int((1 - a) * 10))
    top = 88 + len(title_lines) * 32 + 22

    key, label, icon, ccol = LESSON_CARDS[g["card"]]
    text = info[key]
    font = font_medium_bold if key == "idea" else font_body
    lh = 27 if key == "idea" else 25
    lines = sg_wrap(text, font, WIDTH - 40 - 56)
    card_h = max(300, 110 + len(lines) * lh + 30)
    card = pygame.Rect(20, top, WIDTH - 40, card_h)

    # Stack of the cards still to come, peeking out underneath.
    remaining = len(LESSON_CARDS) - 1 - g["card"]
    for k in range(min(2, remaining), 0, -1):
        back = card.inflate(-24 * k, 0).move(0, 14 * k)
        pygame.draw.rect(surface, mix_color(SG_CARD, SG_BG, 0.25 + 0.2 * k), back, border_radius=24)

    ct = now - g["card_at"]
    enter = _ease_back(ct / 0.4, 1.1) if not getattr(state, "reduced_motion", False) else 1.0
    dt = min(0.05, now - g.get("last_draw", now))
    if not g.get("dragging"):
        g["drag_x"] *= math.exp(-dt * 16)
    ox = g["drag_x"] + (1 - enter) * 0
    oy = (1 - enter) * 30
    layer = _sg_layer("lesson_card", (card.w + 40, card.h + 40))
    lc = pygame.Rect(20, 20, card.w, card.h)
    draw_rounded_rect(layer, lc, SG_CARD, radius=24)
    band = pygame.Rect(lc.x, lc.y, lc.w, 70)
    pygame.draw.rect(layer, mix_color(ccol, SG_CARD, 0.84), band, border_top_left_radius=24, border_top_right_radius=24)
    pygame.draw.circle(layer, ccol, (lc.x + 44, lc.y + 35), 20)
    _sg_icon(layer, icon, lc.x + 44, lc.y + 35, SG_TEXT if _luminance(ccol) > 0.45 else (255, 255, 255), 1.0)
    draw_text(layer, label, font_body_bold, SG_TEXT, lc.x + 76, lc.y + 16)
    draw_text(layer, f"Card {g['card'] + 1} of {len(LESSON_CARDS)}", font_tiny, SG_CARD_MUTED, lc.x + 76, lc.y + 39)
    for i, line in enumerate(lines):
        wa = _clamp01((ct - 0.15 - i * 0.06) / 0.25)
        img = font.render(line, True, SG_TEXT)
        if wa < 1:
            img.set_alpha(int(255 * wa))
        layer.blit(img, (lc.x + 28, lc.y + 96 + i * lh + int((1 - wa) * 6)))
    angle = -g["drag_x"] * 0.04
    img = layer if abs(angle) < 0.05 else HiSurface(None, hi=pygame.transform.rotozoom(layer.hi, angle, 1.0))
    center = (card.centerx + ox, card.centery + oy)
    img_rect = img.get_rect(center=(int(center[0]), int(center[1])))
    if enter < 1:
        img.set_alpha(int(255 * _clamp01(enter * 1.5)))
    surface.blit(img, img_rect.topleft)
    g["card_rect"] = card

    # The card you just finished flies off to the left.
    if g.get("fly_from"):
        fi, t0, d = g["fly_from"]
        ft = (now - t0) / 0.35
        if ft < 1:
            fk, flab, ficon, fcol = LESSON_CARDS[fi]
            ghost = _sg_layer("lesson_ghost", (card.w + 40, 120))
            pygame.draw.rect(ghost, SG_CARD, (20, 20, card.w, 80), border_radius=24)
            pygame.draw.rect(ghost, mix_color(fcol, SG_CARD, 0.84), (20, 20, card.w, 70), border_top_left_radius=24,
                             border_top_right_radius=24)
            draw_text(ghost, flab, font_body_bold, SG_TEXT, 96, 36)
            rot = HiSurface(None, hi=pygame.transform.rotozoom(ghost.hi, 18 * ft, 1.0))
            rot.set_alpha(int(255 * (1 - ft)))
            surface.blit(rot, rot.get_rect(center=(int(card.centerx - ease_out_cubic(ft) * WIDTH), card.y + 60)).topleft)

    hint = "Tap or swipe the card for the next one" if g["card"] < len(LESSON_CARDS) - 1 else "Ready? Three quick questions."
    draw_text(surface, hint, font_small, SG_MUTED, WIDTH // 2, HEIGHT - 128, align="center")
    last = g["card"] == len(LESSON_CARDS) - 1
    bw = WIDTH - 40
    if g["card"] > 0:
        back = pygame.Rect(20, HEIGHT - 96, 64, 60)
        _lg_button(surface, back, "prev_card", "", SG_PANEL_2, SG_TEXT, depth=5)
        pygame.draw.lines(surface, SG_TEXT, False, [(back.centerx + 4, back.centery - 7), (back.centerx - 4, back.centery),
                                                     (back.centerx + 4, back.centery + 7)], 3)
        bw -= 76
    btn = pygame.Rect(WIDTH - 20 - bw, HEIGHT - 96, bw, 60)
    _lg_button(surface, btn, "next_card", "Start the quiz" if last else "Next card", SG_GOLD, SG_INK, icon="lens" if last else None)


def _lg_draw_quiz(surface, now, info, col):
    g = lesson_game
    q = g["quiz"][g["qi"]]
    answered = g["picked"] is not None
    _lg_topbar(surface, now, col, len(LESSON_CARDS) + g["qi"] + (1 if answered else 0), len(LESSON_CARDS) + 3)
    ct = now - g["card_at"]
    a = ease_out_cubic(ct / 0.35)
    draw_text(surface, f"Question {g['qi'] + 1} of {len(g['quiz'])}", font_small_bold, col, 20, 66)
    if g["combo"] >= 2:
        _sg_chip(surface, WIDTH - 20, 62, f"{g['combo']} in a row", SG_GOLD, mix_color(SG_GOLD, SG_BG, 0.8), icon="flame", align="right")
    lines = sg_wrap(q["q"], font_sg_h2, WIDTH - 40, 4)
    qy = 94
    for i, line in enumerate(lines):
        la = _clamp01((ct - i * 0.05) / 0.3)
        img = font_sg_h2.render(line, True, SG_TEXT)
        if la < 1:
            img.set_alpha(int(255 * la))
        surface.blit(img, (20, qy + i * 32 + int((1 - la) * 8)))
    y = qy + len(lines) * 32 + 22

    pt = now - g["picked_at"] if answered else 0.0
    for i, choice in enumerate(q["choices"]):
        c_lines = sg_wrap(choice, font_body_bold, WIDTH - 40 - 84, 2)
        h = max(64, 30 + len(c_lines) * 21)
        enter = _ease_back((ct - 0.15 - i * 0.07) / 0.35, 1.2)
        rect = pygame.Rect(20 + int((1 - enter) * 60), y, WIDTH - 40, h)
        is_right = i == q["correct"]
        is_pick = i == g["picked"]
        hovered = not answered and rect.collidepoint(pygame.mouse.get_pos())
        if answered and is_right:
            bg, bd, badge = mix_color(SG_GREEN, SG_PANEL, 0.7), SG_GREEN, SG_GREEN
        elif answered and is_pick:
            bg, bd, badge = mix_color(SG_RED, SG_PANEL, 0.72), SG_RED, SG_RED
            if pt < 0.45:
                rect.x += int(math.sin(pt * 60) * 9 * (1 - pt / 0.45))
        elif answered:
            bg, bd, badge = mix_color(SG_PANEL, SG_BG, 0.4), SG_LINE, SG_PANEL_2
        else:
            bg, bd, badge = (SG_PANEL_2 if hovered else SG_PANEL), (col if hovered else SG_LINE), SG_PANEL_2
        pressed = hovered and pygame.mouse.get_pressed()[0]
        depth = 1 if pressed else 5
        pygame.draw.rect(surface, mix_color(bd, (0, 0, 0), 0.45), rect.move(0, 5), border_radius=18)
        face = rect.move(0, 5 - depth)
        pygame.draw.rect(surface, bg, face, border_radius=18)
        pygame.draw.rect(surface, bd, face, 2, border_radius=18)
        bc = (face.x + 32, face.centery)
        pygame.draw.circle(surface, badge, bc, 16)
        if answered and is_right:
            _sg_check(surface, bc[0], bc[1], 0.8, SG_BG, 3)
        elif answered and is_pick:
            _sg_cross(surface, bc[0], bc[1], 0.75, SG_BG, 3)
        else:
            draw_text(surface, "ABC"[i], font_small_bold, SG_TEXT if not answered else SG_MUTED, bc[0], bc[1] - 9, align="center")
        tcol = SG_TEXT if (not answered or is_right or is_pick) else SG_MUTED
        ty = face.centery - len(c_lines) * 21 // 2
        for line in c_lines:
            draw_text(surface, line, font_body_bold, tcol, face.x + 60, ty, max_width=face.w - 76)
            ty += 21
        if not answered:
            lesson_game["btns"][f"choice_{i}"] = rect
        y += h + 14

    if answered:
        ok = g["picked"] == q["correct"]
        if _lg_fx_once("land"):
            mid = (WIDTH // 2, 200)
            if ok:
                play_sound("achievement")
                _lg_shake(5)
                spawn_sparks(WIDTH // 2, y - 40, SG_GREEN, 26)
                spawn_confetti(24 + 8 * min(3, g["combo"]))
                if g["combo"] >= 2:
                    play_sound("combo")
            else:
                play_sound("error")
                _lg_shake(10)
            lesson_game["flash"], lesson_game["flash_at"] = (SG_GREEN if ok else SG_RED), now
        # Stamp pops on the question, then lifts away.
        if pt < 1.0:
            st = _clamp01(pt / 0.22)
            fade = 1 - _clamp01((pt - 0.7) / 0.3)
            scale = (2.3 - 1.3 * st * st) * (1 + 0.2 * (1 - fade))
            _sg_stamp(surface, "CORRECT" if ok else "NOT QUITE", SG_GREEN if ok else SG_RED, (WIDTH // 2, 140), -10, scale,
                      255 * min(1.0, st * 1.8) * fade)
        # Explanation sheet.
        why = sg_wrap(q["why"], font_small, WIDTH - 40 - 40)
        sheet_h = 22 + 30 + len(why) * 20 + 18 + 60 + 26
        p = _ease_back((pt - 0.45) / 0.4, 0.8)
        if p > 0:
            rect = pygame.Rect(0, int(HEIGHT - sheet_h + (1 - p) * (sheet_h + 30)), WIDTH, sheet_h + 40)
            shadow, spad = soft_shadow(rect.w, 60, 28, 14, 120)
            surface.blit(shadow, (rect.x - spad, rect.y - spad - 6))
            pygame.draw.rect(surface, SG_PANEL, rect, border_top_left_radius=28, border_top_right_radius=28)
            pygame.draw.rect(surface, SG_LINE, rect, 1, border_top_left_radius=28, border_top_right_radius=28)
            hc = SG_GREEN if ok else SG_AMBER
            _sg_icon(surface, "check" if ok else "lens", 34, rect.y + 34, hc, 1.0)
            draw_text(surface, "Nice! Here's why" if ok else "The right answer, and why", font_body_bold, hc, 52, rect.y + 24)
            for i, line in enumerate(why):
                draw_text(surface, line, font_small, SG_TEXT, 20, rect.y + 54 + i * 20, max_width=WIDTH - 40)
            last = g["qi"] + 1 >= len(g["quiz"])
            if pt > 0.7:
                _lg_button(surface, pygame.Rect(20, rect.y + 54 + len(why) * 20 + 18, WIDTH - 40, 56), "continue",
                           "See results" if last else "Continue", SG_GOLD, SG_INK)


def _lg_draw_done(surface, now, info, col):
    g = lesson_game
    t = now - g["stage_at"]
    if getattr(state, "reduced_motion", False):
        t = max(t, 3.0)
    close = pygame.Rect(16, 16, 40, 40)
    _sg_close(surface, close, g["btns"])
    passed = g["passed"]
    cx, cy = WIDTH // 2, 170
    rays = _sg_layer("lg_rays", (320, 320))
    rc = SG_GOLD if passed else SG_PURPLE
    for k in range(14):
        a = k * math.tau / 14 + now * 0.3
        pygame.draw.polygon(rays, (*rc, 30), [(160, 160), (160 + math.cos(a - 0.1) * 160, 160 + math.sin(a - 0.1) * 160),
                                              (160 + math.cos(a + 0.1) * 160, 160 + math.sin(a + 0.1) * 160)])
    surface.blit(rays, (cx - 160, cy - 160))
    for k in range(3):
        st = _clamp01((t - 0.2 - k * 0.22) / 0.3)
        if st <= 0:
            continue
        earned = k < g["stars"]
        sx = cx + (k - 1) * 84
        sy = cy + (14 if k != 1 else -8)
        r = (30 if k != 1 else 40) * (1.8 - 0.8 * ease_out_cubic(st))
        draw_star_shape(surface, sx, sy + 4, r, mix_color(SG_GOLD, (0, 0, 0), 0.4) if earned else SG_BG)
        draw_star_shape(surface, sx, sy, r, SG_GOLD if earned else SG_PANEL_2)
        if st >= 1 and _lg_fx_once(f"star{k}"):
            if earned:
                play_sound("stamp")
                spawn_sparks(sx, sy, SG_GOLD, 16)
                _lg_shake(4)
            else:
                play_sound("click")
    if t > 1.0 and _lg_fx_once("cheer"):
        if passed:
            play_sound("victory")
            spawn_confetti(60 if g["stars"] == 3 else 35)
            avatar_emote("cheer")
        else:
            play_sound("bell")

    a = ease_out_cubic((t - 0.8) / 0.4)
    ty = 262 + int((1 - a) * 12)
    if passed:
        title = ["", "", "Lesson complete!", "Perfect lesson!"][g["stars"]]
        sub = f"You got {g['right']} of {len(g['quiz'])} right."
    else:
        title, sub = "So close!", f"You got {g['right']} of {len(g['quiz'])}. Get 2 right to pass."
    draw_text(surface, title, font_sg_title, SG_TEXT, cx, ty, align="center")
    draw_text(surface, sub, font_body, SG_MUTED, cx, ty + 44, align="center")

    rp = ease_out_cubic((t - 1.1) / 0.35)
    y = 356
    if rp > 0 and passed:
        chips = []
        if g["xp"]:
            chips.append((f"+{g['xp']} XP", SG_PURPLE, "star"))
        if g["coins"]:
            chips.append((f"+{g['coins']} coins", SG_GOLD, None))
        chips.append((f"{state.learning_streak}-day streak", SG_AMBER, "flame"))
        widths = [font_small_bold.size(lab)[0] + 52 for lab, _, _ in chips]
        x = cx - (sum(widths) + 10 * (len(chips) - 1)) // 2
        for (lab, ccol, icon), w in zip(chips, widths):
            chip = pygame.Rect(x, y + int((1 - rp) * 10), w, 38)
            pygame.draw.rect(surface, mix_color(ccol, SG_BG, 0.8), chip, border_radius=19)
            pygame.draw.rect(surface, mix_color(ccol, SG_BG, 0.5), chip, 1, border_radius=19)
            if icon:
                _sg_icon(surface, icon, chip.x + 20, chip.centery, ccol, 0.85)
            else:
                draw_coin_icon(surface, chip.x + 20, chip.centery, 9)
            draw_text(surface, lab, font_small_bold, ccol, chip.x + 36, chip.centery - 9)
            x += w + 10
    y += 58

    # Unit progress.
    kp = ease_out_cubic((t - 1.3) / 0.35)
    if kp > 0:
        u = lesson_unit(g["id"])
        name, tagline, ucol, ids = ACADEMY_UNITS[u]
        done = sum(1 for l in ids if l in state.academy_completed)
        card = pygame.Rect(20, y + int((1 - kp) * 14), WIDTH - 40, 92)
        sg_panel(surface, card, 20)
        _lesson_node(surface, card.x + 46, card.centery - 3, 26, ucol, info["glyph"], "done" if passed else "open", now)
        draw_text(surface, f"Unit {u + 1}  ·  {name}", font_tiny, ucol, card.x + 88, card.y + 18)
        draw_text(surface, "Unit complete!" if g.get("unit_done") and passed else f"{done} of {len(ids)} lessons done",
                  font_medium_bold, SG_TEXT, card.x + 88, card.y + 34, max_width=card.w - 108)
        bar = pygame.Rect(card.x + 88, card.y + 66, card.w - 108, 8)
        pygame.draw.rect(surface, SG_PANEL_2, bar, border_radius=4)
        fill = tween(("lg_unit", g["id"]), done / len(ids), 4)
        if fill > 0.01:
            pygame.draw.rect(surface, ucol, (bar.x, bar.y, max(8, int(bar.w * fill)), bar.h), border_radius=4)
        if g.get("unit_done") and passed and _lg_fx_once("unit"):
            show_toast("Unit complete!", f"{name} is done. Next unit unlocked!", "achievement")
    bp = ease_out_cubic((t - 1.4) / 0.35)
    if bp > 0:
        off = int((1 - bp) * 40)
        nxt = _next_lesson_after(g["id"])
        if passed and nxt:
            _lg_button(surface, pygame.Rect(20, HEIGHT - 150 + off, WIDTH - 40, 60), "next_lesson",
                       f"Next: {LESSONS[nxt]['title']}", SG_GOLD, SG_INK)
        elif passed:
            _lg_button(surface, pygame.Rect(20, HEIGHT - 150 + off, WIDTH - 40, 60), "back", "Course complete!", SG_GOLD, SG_INK,
                       icon="star")
        else:
            _lg_button(surface, pygame.Rect(20, HEIGHT - 150 + off, WIDTH - 40, 60), "retry", "Try the quiz again", SG_GOLD, SG_INK)
        second = ("back", "Back to Academy") if passed else ("review", "Review the cards")
        _lg_button(surface, pygame.Rect(20, HEIGHT - 76 + off, WIDTH - 40, 50), second[0], second[1], SG_PANEL_2, SG_TEXT,
                   font=font_body_bold, depth=4)


def draw_lesson_game(surface):
    g = lesson_game
    if not g.get("open"):
        return True
    now = time.time()
    g["btns"] = {}
    info = LESSONS[g["id"]]
    col = unit_color(lesson_unit(g["id"]))
    frame = _sg_layer("frame", (WIDTH, HEIGHT))
    _sg_background(frame, now, col)
    if g["stage"] == "learn":
        _lg_draw_learn(frame, now, info, col)
    elif g["stage"] == "quiz":
        _lg_draw_quiz(frame, now, info, col)
    else:
        _lg_draw_done(frame, now, info, col)
    g["last_draw"] = now
    sx = sy = 0.0
    k = 1 - (now - g.get("shake_at", 0.0)) / 0.45
    if k > 0:
        amp = g.get("shake_amp", 0.0) * k * k
        sx, sy = math.sin(now * 71) * amp, math.cos(now * 57) * amp * 0.6
    surface.fill(SG_BG)
    surface.blit(frame, (int(sx), int(sy)))
    fk = 1 - (now - g.get("flash_at", 0.0)) / 0.35
    if fk > 0 and g.get("flash"):
        blit_color_overlay(surface, g["flash"], 55 * fk)
    return True


# ----------------------------
# BATTLE ARENA
# ----------------------------
# A battle is its own little market: you and a bot each get $1,000 of battle cash and the same
# four stocks. Breaking news pushes stocks up or down for a few seconds. Buy what you think will
# rise, sell to lock in profit, and whoever has more money when the clock hits zero wins.
# Battles never touch your real portfolio.

BATTLE_CASH = 1000.0
BATTLE_BUY = 250.0
BATTLE_TICK = 0.25
BATTLE_DURATIONS = (60, 90)
BOT_INFO = {
    "rookie": {"color": (52, 211, 153), "plan": "Buys small amounts of random stocks and almost never sells.",
               "beat": "Buy stocks with good news, then sell after they rise. That's enough to win."},
    "aggressive": {"color": (244, 63, 94), "plan": "Goes all-in on the wildest stock and never sells.",
                   "beat": "If Rick's stock gets bad news he can't escape. Stay flexible and dodge the drops."},
    "speed": {"color": (251, 191, 36), "plan": "Jumps on breaking news about two seconds after it hits.",
              "beat": "Be faster than Tara: buy the moment good news appears, and sell before the move fades."},
    "dividend": {"color": (96, 165, 250), "plan": "Splits money evenly across all four stocks and holds.",
                 "beat": "Sam gets the average. Beat it by selling the losers and moving into the winners."},
    "news": {"color": (192, 132, 252), "plan": "Buys good news, sells bad news and takes profit when the story ends.",
             "beat": "Nina reacts in about a second. Pick better stocks and cut losers even faster."},
    "quant": {"color": (34, 211, 238), "plan": "Buys dips, takes quick profits and trades every headline.",
              "beat": "Quinn rarely panics. Ride good news longer than Quinn does and avoid chasing drops."},
}
BATTLE_NEWS_UP = ["{n} beats sales estimates", "{n} launches a hit product", "Big investor buys {n} shares",
                  "{n} raises its forecast", "Analysts upgrade {n}"]
BATTLE_NEWS_DOWN = ["{n} misses earnings", "{n} recalls a product", "{n} loses a major customer",
                    "Regulators probe {n}", "{n} cuts its forecast"]
BATTLE_TIPS = ["Watch the news bar. Good news pushes a stock up for a few seconds.",
               "Sell a stock after it rises to lock in the profit.",
               "Bad news? Sell that stock fast before it drops more.",
               "Cash is safe. Holding cash during a drop is a smart move.",
               "When time runs out, your shares are cashed out at the final price."]

battle = {"open": False}


def _bot_style(rival):
    return BOT_INFO.get(rival["style"], BOT_INFO["rookie"])


def open_battle(rival, duration=60):
    now = time.time()
    picks = random.sample(STOCKS, 4)
    stocks = []
    for s in picks:
        p = float(s["price"])
        stocks.append({"ticker": s["ticker"], "name": s["name"], "price": p, "start": p, "hist": [p] * 40,
                       "vol": max(0.0025, min(0.006, s.get("vol", 0.004) * 0.9)), "drift": 0.0, "news_until": 0.0})
    battle.clear()
    battle.update(open=True, stage="brief", stage_at=now, rival=rival, duration=duration, stocks=stocks, btns={},
                  fx=set(), shake_at=0.0, shake_amp=0.0, flash=None, flash_at=0.0)
    drag_state["active"] = False
    play_sound("swoosh")


def _battle_reset_sides():
    b = battle
    b["me"] = {"cash": BATTLE_CASH, "shares": {}, "cost": {}}
    b["bot"] = {"cash": BATTLE_CASH, "shares": {}, "cost": {}}
    for s in b["stocks"]:
        s["price"] = s["start"]
        s["hist"] = [s["start"]] * 40
        s["drift"] = 0.0
        s["news_until"] = 0.0
    b.update(news=None, next_news=0.0, feed=[], last_tick=0.0, bot_next=0.0, bot_seen_news=None, bot_news_at=0.0,
             best_trade=None, my_trades=0, tip=random.choice(BATTLE_TIPS), tip_at=0.0, last_beep=-1, result=None)


def start_battle_countdown():
    _battle_reset_sides()
    battle.update(stage="count", stage_at=time.time(), fx=set())


def _battle_value(side):
    b = battle
    return side["cash"] + sum(q * next(s["price"] for s in b["stocks"] if s["ticker"] == t) for t, q in side["shares"].items())


def _battle_stock(ticker):
    return next(s for s in battle["stocks"] if s["ticker"] == ticker)


def _battle_buy(side, ticker, amount):
    s = _battle_stock(ticker)
    amount = min(amount, side["cash"])
    if amount < 1:
        return 0.0
    qty = amount / s["price"]
    side["cash"] -= amount
    side["shares"][ticker] = side["shares"].get(ticker, 0.0) + qty
    side["cost"][ticker] = side["cost"].get(ticker, 0.0) + amount
    return qty


def _battle_sell(side, ticker):
    qty = side["shares"].get(ticker, 0.0)
    if qty <= 1e-9:
        return None
    s = _battle_stock(ticker)
    proceeds = qty * s["price"]
    profit = proceeds - side["cost"].get(ticker, 0.0)
    side["cash"] += proceeds
    side["shares"][ticker] = 0.0
    side["cost"][ticker] = 0.0
    return profit


def _battle_feed(text, col):
    battle["feed"].insert(0, (text, col, time.time()))
    del battle["feed"][4:]


def battle_player_buy(ticker):
    b = battle
    if b.get("stage") != "fight":
        return
    if b["me"]["cash"] < 1:
        play_sound("error")
        show_toast("Out of cash", "Sell a stock to free up cash first.", "warning")
        return
    _battle_buy(b["me"], ticker, BATTLE_BUY)
    b["my_trades"] += 1
    play_sound("trade")
    row = b.get("row_rects", {}).get(ticker)
    if row:
        spawn_sparks(row.right - 100, row.centery, SG_GREEN, 10)


def battle_player_sell(ticker):
    b = battle
    if b.get("stage") != "fight":
        return
    profit = _battle_sell(b["me"], ticker)
    if profit is None:
        play_sound("error")
        return
    b["my_trades"] += 1
    s = _battle_stock(ticker)
    if b["best_trade"] is None or profit > b["best_trade"][1]:
        b["best_trade"] = (s["name"], profit)
    row = b.get("row_rects", {}).get(ticker)
    x, y = (row.right - 100, row.centery) if row else (WIDTH // 2, 300)
    floating_texts.append(FloatingText(x, y - 20, f"{'+' if profit >= 0 else '-'}{fmt_money(abs(profit))}", SG_GREEN if profit >= 0 else SG_RED))
    if profit >= 0:
        play_sound("dividend")
        spawn_coins(x, y, True, 8)
    else:
        play_sound("error")


def _battle_tick(now):
    b = battle
    while now - b["last_tick"] >= BATTLE_TICK:
        b["last_tick"] = now if b["last_tick"] == 0.0 else b["last_tick"] + BATTLE_TICK
        for s in b["stocks"]:
            if s["news_until"] and now > s["news_until"]:
                s["drift"] = 0.0
                s["news_until"] = 0.0
            move = s["drift"] + random.gauss(0, s["vol"]) - (s["price"] / s["start"] - 1) * 0.004
            s["price"] = max(1.0, s["price"] * (1 + move))
            s["hist"].append(s["price"])
            del s["hist"][:-40]
    # Breaking news every few seconds, never on a stock that already has a story running.
    if now >= b["next_news"]:
        calm = [s for s in b["stocks"] if not s["news_until"]]
        if calm:
            s = random.choice(calm)
            up = random.random() < 0.55
            s["drift"] = (0.0042 if up else -0.0042) * random.uniform(0.85, 1.2)
            s["news_until"] = now + random.uniform(5.5, 7.5)
            headline = random.choice(BATTLE_NEWS_UP if up else BATTLE_NEWS_DOWN).format(n=s["name"])
            b["news"] = {"ticker": s["ticker"], "up": up, "text": headline, "at": now}
            play_sound("bell" if up else "beep")
        b["next_news"] = now + random.uniform(7.0, 10.0)


def _battle_bot(now):
    b = battle
    rival = b["rival"]
    style = rival["style"]
    bot = b["bot"]
    news = b["news"]
    fresh = news if news and news["at"] != b["bot_seen_news"] else None
    react = {"rookie": 99, "aggressive": 99, "speed": 2.0, "dividend": 99, "news": 1.1, "quant": 1.3}[style]
    name = rival["name"].split()[-1]

    def did(verb, s, col):
        _battle_feed(f"{name} {verb} {s['name']}", col)

    if fresh and now - fresh["at"] >= react:
        b["bot_seen_news"] = fresh["at"]
        s = _battle_stock(fresh["ticker"])
        if fresh["up"]:
            amt = {"speed": 400, "news": 450, "quant": 350}[style]
            if _battle_buy(bot, s["ticker"], amt):
                did("bought", s, SG_GREEN)
        elif _battle_sell(bot, s["ticker"]) is not None:
            did("sold", s, SG_RED)
        return
    if now < b["bot_next"]:
        return
    t_in = now - b["fight_at"]
    if style == "rookie":
        b["bot_next"] = now + random.uniform(3.0, 4.5)
        s = random.choice(b["stocks"])
        if random.random() < 0.75 and _battle_buy(bot, s["ticker"], 150):
            did("bought a little", s, SG_GREEN)
    elif style == "aggressive":
        b["bot_next"] = now + 999
        s = max(b["stocks"], key=lambda x: x["vol"])
        if _battle_buy(bot, s["ticker"], bot["cash"]):
            did("went all-in on", s, SG_AMBER)
    elif style == "dividend":
        b["bot_next"] = now + 999
        each = bot["cash"] / len(b["stocks"])
        for s in b["stocks"]:
            _battle_buy(bot, s["ticker"], each)
        _battle_feed(f"{name} split his cash across all 4 stocks", SG_CYAN)
    elif style == "speed":
        b["bot_next"] = now + random.uniform(4.0, 6.0)
        s = random.choice(b["stocks"])
        if _battle_buy(bot, s["ticker"], 120):
            did("grabbed some", s, SG_GREEN)
    elif style in ("news", "quant"):
        b["bot_next"] = now + (1.5 if style == "quant" else 2.0)
        # Take profit when a story ends, and (quant) buy healthy dips.
        for s in b["stocks"]:
            q = bot["shares"].get(s["ticker"], 0.0)
            if q > 0 and not s["news_until"]:
                cost = bot["cost"].get(s["ticker"], 0.0)
                if q * s["price"] > cost * 1.015 or (style == "quant" and q * s["price"] < cost * 0.97):
                    _battle_sell(bot, s["ticker"])
                    did("took profit on" if q * s["price"] >= cost else "cut", s, SG_AMBER)
                    return
        if style == "quant" and t_in > 4:
            dip = min(b["stocks"], key=lambda x: x["price"] / x["start"])
            if dip["price"] < dip["start"] * 0.97 and not dip["news_until"] and bot["cash"] > 150:
                if _battle_buy(bot, dip["ticker"], 250):
                    did("bought the dip in", dip, SG_GREEN)


def _battle_finish(now, forfeit=False):
    b = battle
    for s in b["stocks"]:
        if b["me"]["shares"].get(s["ticker"], 0) > 0:
            profit = _battle_sell(b["me"], s["ticker"])
            if b["best_trade"] is None or profit > b["best_trade"][1]:
                b["best_trade"] = (s["name"], profit)
        _battle_sell(b["bot"], s["ticker"])
    me, bot = b["me"]["cash"], b["bot"]["cash"]
    rival = b["rival"]
    state.total_duels += 1
    update_challenge("duel")
    rewards = {"trophies": 0, "xp": 0, "coins": 0, "shield": False, "unlocked": None}
    n_ft, n_orb, n_p = len(floating_texts), len(xp_orbs), len(particles)
    today = time.strftime("%Y-%m-%d")
    xp_before = state.xp_earned_today if getattr(state, "xp_day", "") == today else 0
    unlock("first_duel")
    if me > bot + 0.005 and not forfeit:
        result = "win"
        state.total_wins += 1
        state.win_streak += 1
        rewards["trophies"] = 30 + state.win_streak * 5
        state.trophies += rewards["trophies"]
        add_week_points(30 + rival["difficulty"] * 10)
        add_xp(60 + rival["difficulty"] * 15)
        rewards["coins"] = add_coins(25 + rival["difficulty"] * 5)
        unlock("duel_win")
        if state.win_streak >= 3:
            unlock("streak_3")
        state.highest_bot_beaten = max(state.highest_bot_beaten, rival["id"])
        nxt = next((r for r in RIVALS if r["id"] == rival["id"] + 1), None)
        if nxt and not nxt["unlocked"]:
            nxt["unlocked"] = True
            rewards["unlocked"] = nxt
    elif me < bot - 0.005 or forfeit:
        result = "loss"
        state.win_streak = 0
        if consume_boost("shield"):
            rewards["shield"] = True
        else:
            rewards["trophies"] = -min(15, state.trophies)
            state.trophies = max(0, state.trophies - 15)
        add_xp(20)
        add_week_points(5)
    else:
        result = "tie"
        add_xp(30)
        add_week_points(12)
    rewards["xp"] = max(0, getattr(state, "xp_earned_today", 0) - xp_before)
    del floating_texts[n_ft:]
    del xp_orbs[n_orb:]
    del particles[n_p:]
    b.update(stage="result", stage_at=now, result=result, final=(me, bot), rewards=rewards, fx=set())
    save_game()


def _battle_press(key):
    b = battle
    if key == "close":
        if b["stage"] == "fight":
            b["confirm_quit"] = True
            play_sound("click")
        else:
            battle["open"] = False
            play_sound("click")
            save_game()
    elif key in ("dur60", "dur90"):
        b["duration"] = int(key[3:])
        play_sound("click")
    elif key == "start":
        start_battle_countdown()
    elif key.startswith("buy_"):
        battle_player_buy(key[4:])
    elif key.startswith("sell_"):
        battle_player_sell(key[5:])
    elif key == "rematch":
        open_battle(b["rival"], b["duration"])
        start_battle_countdown()
    elif key == "back":
        battle["open"] = False
        state.tab = "arena"
        play_sound("click")
    elif key == "keep":
        b["confirm_quit"] = False
        play_sound("click")
    elif key == "forfeit":
        b["confirm_quit"] = False
        _battle_finish(time.time(), forfeit=True)


def handle_battle_event(event):
    b = battle
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        for key, rect in list(b.get("btns", {}).items()):
            if rect.collidepoint(event.pos):
                _battle_press(key)
                return
    elif event.type == pygame.KEYDOWN:
        if event.key == pygame.K_ESCAPE:
            _battle_press("keep" if b.get("confirm_quit") else "close")
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            if b["stage"] == "brief":
                start_battle_countdown()
            elif b["stage"] == "result" and time.time() - b["stage_at"] > 1.2:
                _battle_press("rematch")


def _bot_badge(surface, rival, cx, cy, r):
    col = _bot_style(rival)["color"]
    pygame.draw.circle(surface, mix_color(col, (0, 0, 0), 0.4), (cx, cy + max(3, r // 10)), r)
    pygame.draw.circle(surface, col, (cx, cy), r)
    # A little robot face.
    ex = r * 0.34
    pygame.draw.rect(surface, SG_BG, (cx - r * 0.6, cy - r * 0.34, r * 1.2, r * 0.62), border_radius=int(r * 0.22))
    for sx in (-1, 1):
        pygame.draw.circle(surface, col, (cx + sx * ex, cy - r * 0.04), max(2, r * 0.13))
    pygame.draw.line(surface, SG_BG, (cx, cy - r), (cx, cy - r * 0.72), max(2, int(r * 0.08)))
    pygame.draw.circle(surface, SG_BG, (cx, cy - r * 1.02), max(2, r * 0.1))


def _battle_draw_brief(surface, now):
    b = battle
    t = now - b["stage_at"]
    rival = b["rival"]
    info = _bot_style(rival)
    _sg_close(surface, pygame.Rect(16, 16, 40, 40), b["btns"])
    draw_text(surface, "Battle", font_small_bold, SG_MUTED, WIDTH // 2, 28, align="center")
    # VS splash: both fighters slide in.
    e = _ease_back(t / 0.5, 1.2)
    ly, lx, rx = 128, 110 - (1 - e) * 200, WIDTH - 110 + (1 - e) * 200
    pygame.draw.circle(surface, SG_PANEL_2, (lx, ly), 48)
    pygame.draw.circle(surface, SG_GOLD, (lx, ly), 48, 3)
    draw_avatar_icon(surface, state.avatar, (int(lx), ly), size=86, dark=True)
    _bot_badge(surface, rival, int(rx), ly, 46)
    vs = _clamp01((t - 0.35) / 0.25)
    if vs > 0:
        img = font_sg_title.render("VS", True, SG_GOLD)
        img = HiSurface(None, hi=pygame.transform.rotozoom(img.hi, 0, 2.0 - vs))
        img.set_alpha(int(255 * vs))
        surface.blit(img, img.get_rect(center=(WIDTH // 2, ly)).topleft)
    draw_text(surface, "You", font_body_bold, SG_TEXT, lx, ly + 58, align="center")
    draw_text(surface, rival["name"], font_body_bold, SG_TEXT, rx, ly + 58, align="center")
    for k in range(6):
        pygame.draw.rect(surface, info["color"] if k < rival["difficulty"] else SG_PANEL_2, (rx - 33 + k * 11, ly + 82, 8, 8), border_radius=2)

    # How to win.
    card = pygame.Rect(20, 240, WIDTH - 40, 190)
    sg_panel(surface, card, 20)
    draw_text(surface, "How to win", font_body_bold, SG_TEXT, card.x + 20, card.y + 16)
    steps = [("coin", SG_GOLD, f"You both start with {fmt_money(BATTLE_CASH)} of battle cash."),
             ("chart", SG_GREEN, "Buy stocks you think will rise. Sell to lock in profit."),
             ("clock", SG_CYAN, f"After {b['duration']} seconds, whoever has more money wins.")]
    for i, (icon, col, text) in enumerate(steps):
        ry = card.y + 52 + i * 44
        pygame.draw.circle(surface, mix_color(col, SG_PANEL, 0.75), (card.x + 34, ry + 10), 15)
        if icon == "coin":
            draw_coin_icon(surface, card.x + 34, ry + 10, 8)
        else:
            _sg_icon(surface, icon, card.x + 34, ry + 10, col, 0.8)
        for j, line in enumerate(sg_wrap(text, font_small, card.w - 80, 2)):
            draw_text(surface, line, font_small, SG_TEXT, card.x + 60, ry + (1 if len(sg_wrap(text, font_small, card.w - 80)) == 1 else -7) + j * 18)

    # Opponent scouting report.
    plan_lines = sg_wrap(info["plan"], font_small, WIDTH - 80)
    beat_lines = sg_wrap(info["beat"], font_small, WIDTH - 80)
    card = pygame.Rect(20, 444, WIDTH - 40, 64 + (len(plan_lines) + len(beat_lines)) * 19 + 26)
    sg_panel(surface, card, 20)
    pygame.draw.rect(surface, info["color"], (card.x, card.y + 14, 4, card.h - 28), border_radius=2)
    draw_text(surface, f"Scouting report: {rival['name']}", font_body_bold, info["color"], card.x + 20, card.y + 14)
    y = card.y + 40
    for line in plan_lines:
        draw_text(surface, line, font_small, SG_TEXT, card.x + 20, y)
        y += 19
    y += 8
    draw_text(surface, "How to beat them", font_small_bold, SG_GOLD, card.x + 20, y)
    y += 20
    for line in beat_lines:
        draw_text(surface, line, font_small, SG_TEXT, card.x + 20, y)
        y += 19

    # Length + start.
    for i, d in enumerate(BATTLE_DURATIONS):
        r = pygame.Rect(20 + i * 110, HEIGHT - 150, 100, 40)
        on = b["duration"] == d
        pygame.draw.rect(surface, mix_color(SG_GOLD, SG_BG, 0.75) if on else SG_PANEL, r, border_radius=14)
        pygame.draw.rect(surface, SG_GOLD if on else SG_LINE, r, 1, border_radius=14)
        draw_text(surface, f"{d} seconds", font_small_bold, SG_GOLD if on else SG_TEXT, r.centerx, r.centery - 9, align="center")
        b["btns"][f"dur{d}"] = r
    draw_text(surface, f"Win: +{30 + (state.win_streak + 1) * 5} trophies", font_tiny, SG_MUTED, WIDTH - 20, HEIGHT - 142, align="right")
    _sg_button(surface, pygame.Rect(20, HEIGHT - 92, WIDTH - 40, 62), "start", "Start battle", SG_GOLD, SG_INK, icon="bolt", btns=b["btns"])


def _battle_draw_count(surface, now):
    b = battle
    t = now - b["stage_at"]
    n = 3 - int(t)
    if t >= 3.0:
        b.update(stage="fight", stage_at=now, fight_at=now, last_tick=now, next_news=now + 3.0, bot_next=now + 1.5, fx=set())
        play_sound("victory")
        return
    if _sg_fx_once_in(b, f"count{n}"):
        play_sound("beep")
    frac = t - int(t)
    scale = 2.2 - 1.2 * ease_out_cubic(min(1.0, frac / 0.35))
    img = font_sg_grade.render(str(n), True, SG_GOLD)
    img = HiSurface(None, hi=pygame.transform.rotozoom(img.hi, 0, scale))
    img.set_alpha(int(255 * (1 - max(0.0, frac - 0.7) / 0.3)))
    surface.blit(img, img.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 40)).topleft)
    draw_text(surface, f"You vs {b['rival']['name']}", font_body_bold, SG_MUTED, WIDTH // 2, HEIGHT // 2 + 40, align="center")


def _sg_fx_once_in(store, name):
    fx = store.setdefault("fx", set())
    if name in fx:
        return False
    fx.add(name)
    return True


def _battle_draw_fight(surface, now):
    b = battle
    rival = b["rival"]
    info = _bot_style(rival)
    paused = b.get("confirm_quit")
    if not paused:
        _battle_tick(now)
        _battle_bot(now)
    else:
        # Freeze the clock while the quit dialog is up.
        b["fight_at"] += now - b.get("last_frame", now)
        b["last_tick"] = now
        b["next_news"] += now - b.get("last_frame", now)
    b["last_frame"] = now
    left = max(0.0, b["duration"] - (now - b["fight_at"]))
    if left <= 0:
        _battle_finish(now)
        return
    sec = int(math.ceil(left))
    if sec <= 5 and sec != b["last_beep"]:
        b["last_beep"] = sec
        play_sound("beep")

    # Scoreboard.
    me_v, bot_v = _battle_value(b["me"]), _battle_value(b["bot"])
    _sg_close(surface, pygame.Rect(16, 16, 40, 40), b["btns"])
    for side, val, x, align, label in ((b["me"], me_v, 70, "left", "You"), (b["bot"], bot_v, WIDTH - 20, "right", rival["name"])):
        pct = (val / BATTLE_CASH - 1) * 100
        draw_text(surface, label, font_small_bold, SG_MUTED, x, 14, align=align, max_width=150)
        draw_text(surface, fmt_money(val), font_medium_bold, SG_TEXT, x, 32, align=align)
        draw_text(surface, f"{'+' if pct >= 0 else ''}{pct:.2f}%", font_small_bold, SG_GREEN if pct >= 0 else SG_RED, x, 56, align=align)
    tc = (WIDTH // 2, 44)
    tcol = SG_RED if left <= 10 else SG_GOLD
    sg_progress_ring(surface, tc, 28, left / b["duration"], tcol, 5)
    draw_text(surface, str(sec), font_medium_bold, SG_TEXT, tc[0], tc[1] - 12, align="center")
    lead = max(0.08, min(0.92, 0.5 + (me_v - bot_v) / 120.0))
    bar = pygame.Rect(20, 86, WIDTH - 40, 12)
    pygame.draw.rect(surface, info["color"], bar, border_radius=6)
    pygame.draw.rect(surface, SG_GOLD, (bar.x, bar.y, int(bar.w * tween("battle_lead", lead, 6)), bar.h), border_radius=6)
    mid = bar.x + int(bar.w * tween("battle_lead", lead, 6))
    pygame.draw.circle(surface, SG_TEXT, (mid, bar.centery), 9)
    status = "You're winning!" if me_v > bot_v + 0.01 else ("It's tied" if abs(me_v - bot_v) <= 0.01 else f"{rival['name'].split()[-1]} is ahead")
    draw_text(surface, status, font_tiny, SG_GOLD if me_v > bot_v else SG_MUTED, WIDTH // 2, 102, align="center")

    # Breaking news bar.
    nb = pygame.Rect(20, 124, WIDTH - 40, 48)
    news = b["news"]
    live = news and now - news["at"] < 7.0
    if live:
        col = SG_GREEN if news["up"] else SG_RED
        slide = ease_out_cubic((now - news["at"]) / 0.3)
        nb.x += int((1 - slide) * 40)
        pygame.draw.rect(surface, mix_color(col, SG_BG, 0.7), nb, border_radius=16)
        pygame.draw.rect(surface, col, nb, 2, border_radius=16)
        tag = pygame.Rect(nb.x + 10, nb.y + 12, 72, 24)
        pygame.draw.rect(surface, col, tag, border_radius=12)
        draw_text(surface, "BREAKING", font_tiny, SG_INK, tag.centerx, tag.y + 4, align="center")
        draw_text(surface, news["text"], font_small_bold, SG_TEXT, tag.right + 10, nb.centery - 9, max_width=nb.right - tag.right - 22)
    else:
        pygame.draw.rect(surface, SG_PANEL, nb, border_radius=16)
        pygame.draw.rect(surface, SG_LINE, nb, 1, border_radius=16)
        draw_text(surface, "Breaking news shows up here. It moves prices!", font_small, SG_MUTED, nb.centerx, nb.centery - 9, align="center")

    # Stock rows.
    b["row_rects"] = {}
    y = 184
    for s in b["stocks"]:
        row = pygame.Rect(20, y, WIDTH - 40, 104)
        hot = s["news_until"] and news and news["ticker"] == s["ticker"]
        pygame.draw.rect(surface, SG_PANEL, row, border_radius=18)
        if hot:
            hc = SG_GREEN if news["up"] else SG_RED
            pygame.draw.rect(surface, mix_color(hc, SG_PANEL, 0.3 + 0.3 * math.sin(now * 8)), row, 2, border_radius=18)
        else:
            pygame.draw.rect(surface, SG_LINE, row, 1, border_radius=18)
        b["row_rects"][s["ticker"]] = row
        draw_ticker_badge(surface, s["ticker"], row.x + 14, row.y + 14, size=40)
        draw_text(surface, s["name"], font_body_bold, SG_TEXT, row.x + 64, row.y + 12, max_width=150)
        chg = (s["price"] / s["start"] - 1) * 100
        pr = draw_text(surface, fmt_money(s["price"]), font_small_bold, SG_TEXT, row.x + 64, row.y + 34)
        draw_text(surface, f"{'+' if chg >= 0 else ''}{chg:.1f}%", font_small_bold, SG_GREEN if chg >= 0 else SG_RED, pr.right + 8, row.y + 34)
        # Sparkline.
        hist = s["hist"]
        lo, hi = min(hist), max(hist)
        span = max(hi - lo, s["start"] * 0.004)
        sx0, sw, sy0, sh = row.x + 14, 150, row.y + 62, 30
        pts = [(sx0 + i * sw / (len(hist) - 1), sy0 + sh - (v - lo) / span * sh) for i, v in enumerate(hist)]
        pygame.draw.lines(surface, SG_GREEN if hist[-1] >= hist[0] else SG_RED, False, pts, 2)
        pygame.draw.circle(surface, SG_TEXT, pts[-1], 3)
        # Your position.
        q = b["me"]["shares"].get(s["ticker"], 0.0)
        bx = row.right - 104
        if q > 1e-9:
            val = q * s["price"]
            pnl = val - b["me"]["cost"].get(s["ticker"], 0.0)
            draw_text(surface, f"You own {fmt_money(val)}", font_tiny, SG_TEXT, bx - 10, row.y + 62, align="right")
            draw_text(surface, f"{'+' if pnl >= 0 else '-'}{fmt_money(abs(pnl))}", font_small_bold, SG_GREEN if pnl >= 0 else SG_RED,
                      bx - 10, row.y + 78, align="right")
        # Buttons.
        can_buy = b["me"]["cash"] >= 1
        buy_r = pygame.Rect(bx, row.y + 12, 90, 38)
        sell_r = pygame.Rect(bx, row.y + 56, 90, 36)
        _sg_button(surface, buy_r, "buy_" + s["ticker"], f"Buy ${int(min(BATTLE_BUY, b['me']['cash'])) if can_buy else 0}",
                   SG_GREEN if can_buy else SG_PANEL_2, SG_INK if can_buy else SG_MUTED, font=font_small_bold, depth=4, btns=b["btns"])
        has = q > 1e-9
        _sg_button(surface, sell_r, "sell_" + s["ticker"], "Sell all", SG_RED if has else SG_PANEL_2, SG_INK if has else SG_MUTED,
                   font=font_small_bold, depth=4, btns=b["btns"])
        y += 114

    # Cash, bot feed and a coaching tip.
    cash_r = pygame.Rect(20, y + 2, 150, 58)
    sg_panel(surface, cash_r, 16)
    draw_text(surface, "Your cash", font_tiny, SG_MUTED, cash_r.x + 14, cash_r.y + 10)
    draw_text(surface, fmt_money(b["me"]["cash"]), font_body_bold, SG_GOLD, cash_r.x + 14, cash_r.y + 28, max_width=cash_r.w - 20)
    feed_r = pygame.Rect(cash_r.right + 10, y + 2, WIDTH - 20 - cash_r.right - 10, 58)
    sg_panel(surface, feed_r, 16)
    _bot_badge(surface, rival, feed_r.x + 22, feed_r.centery + 1, 12)
    if b["feed"]:
        text, col, at = b["feed"][0]
        a = _clamp01((now - at) / 0.25)
        draw_text(surface, text, font_small_bold, col, feed_r.x + 44 + int((1 - a) * 12), feed_r.centery - 9, max_width=feed_r.w - 54)
    else:
        draw_text(surface, f"{rival['name'].split()[-1]} is thinking...", font_small, SG_MUTED, feed_r.x + 44, feed_r.centery - 9, max_width=feed_r.w - 54)
    if now - b["tip_at"] > 9:
        b["tip"], b["tip_at"] = random.choice(BATTLE_TIPS), now
    draw_text(surface, b["tip"], font_tiny, SG_MUTED, WIDTH // 2, y + 72, align="center", max_width=WIDTH - 40)

    if paused:
        blit_color_overlay(surface, SG_BG, 215)
        box = pygame.Rect(34, HEIGHT // 2 - 120, WIDTH - 68, 232)
        sg_panel(surface, box, 24)
        draw_text(surface, "Leave this battle?", font_large_med, SG_TEXT, box.centerx, box.y + 26, align="center")
        draw_text(surface, "Leaving now counts as a loss.", font_small, SG_MUTED, box.centerx, box.y + 62, align="center")
        b["btns"] = {}
        _sg_button(surface, pygame.Rect(box.x + 20, box.y + 100, box.w - 40, 52), "keep", "Keep battling", SG_GOLD, SG_INK, btns=b["btns"])
        _sg_button(surface, pygame.Rect(box.x + 20, box.y + 164, box.w - 40, 48), "forfeit", "Forfeit", SG_PANEL_2, SG_TEXT,
                   font=font_body_bold, btns=b["btns"])


def _battle_draw_result(surface, now):
    b = battle
    t = now - b["stage_at"]
    if getattr(state, "reduced_motion", False):
        t = max(t, 3.0)
    res = b["result"]
    rival = b["rival"]
    me, bot = b["final"]
    col = {"win": SG_GOLD, "loss": SG_RED, "tie": SG_CYAN}[res]
    _sg_close(surface, pygame.Rect(16, 16, 40, 40), b["btns"])
    rays = _sg_layer("battle_rays", (340, 340))
    for k in range(16):
        a = k * math.tau / 16 + now * 0.3
        pygame.draw.polygon(rays, (*col, 30), [(170, 170), (170 + math.cos(a - 0.09) * 170, 170 + math.sin(a - 0.09) * 170),
                                               (170 + math.cos(a + 0.09) * 170, 170 + math.sin(a + 0.09) * 170)])
    surface.blit(rays, (WIDTH // 2 - 170, 150 - 170))
    st = _clamp01(t / 0.3)
    word = {"win": "VICTORY", "loss": "DEFEAT", "tie": "TIE"}[res]
    _sg_stamp(surface, word, col, (WIDTH // 2, 150), -8, 2.3 - 1.3 * ease_out_cubic(st), 255 * st)
    if st >= 1 and _sg_fx_once_in(b, "land"):
        play_sound("stamp")
        b["shake_at"], b["shake_amp"] = now, 9
        spawn_sparks(WIDTH // 2, 150, col, 30)
        if res == "win":
            play_sound("victory")
            spawn_confetti(80)
            avatar_react("duel_win")
        elif res == "loss":
            play_sound("defeat")
            avatar_react("duel_loss")

    # Final scores.
    a = ease_out_cubic((t - 0.4) / 0.4)
    card = pygame.Rect(20, 236 + int((1 - a) * 14), WIDTH - 40, 136)
    sg_panel(surface, card, 20)
    for i, (label, val, badge) in enumerate((("You", me, "me"), (rival["name"], bot, "bot"))):
        x = card.x + 20 + i * (card.w // 2)
        cy = card.y + 36
        if badge == "me":
            draw_avatar_icon(surface, state.avatar, (x + 18, cy), size=34, dark=True)
        else:
            _bot_badge(surface, rival, x + 18, cy, 16)
        draw_text(surface, label, font_small_bold, SG_MUTED, x + 44, cy - 10, max_width=card.w // 2 - 60)
        pct = (val / BATTLE_CASH - 1) * 100
        draw_text(surface, fmt_money(val), font_medium_bold, SG_TEXT, x, cy + 30)
        draw_text(surface, f"{'+' if pct >= 0 else ''}{pct:.2f}%", font_small_bold, SG_GREEN if pct >= 0 else SG_RED, x, cy + 56)
    pygame.draw.line(surface, SG_LINE, (card.centerx, card.y + 18), (card.centerx, card.bottom - 18), 1)

    # What happened.
    y = card.bottom + 16
    if b["best_trade"] and b["best_trade"][1] > 0:
        coach = f"Best trade: selling {b['best_trade'][0]} for +{fmt_money(b['best_trade'][1])}."
    elif b["my_trades"] == 0:
        coach = "You didn't trade. Buy a stock with good news next time!"
    elif res == "loss":
        coach = "Tip: sell stocks with bad news quickly, and hold the ones with good news."
    else:
        coach = "Nice work. Selling after a rise is how you lock in profit."
    for i, line in enumerate(sg_wrap(coach, font_small, WIDTH - 60, 2)):
        draw_text(surface, line, font_small, SG_TEXT, WIDTH // 2, y + i * 19, align="center")
    y += 50

    rp = ease_out_cubic((t - 0.9) / 0.35)
    rw = b["rewards"]
    if rp > 0:
        chips = []
        if rw["trophies"] > 0:
            chips.append((f"+{rw['trophies']} trophies", SG_GOLD))
        elif rw["trophies"] < 0:
            chips.append((f"{rw['trophies']} trophies", SG_RED))
        elif rw["shield"]:
            chips.append(("Shield saved your trophies", SG_CYAN))
        if rw["xp"]:
            chips.append((f"+{rw['xp']} XP", SG_PURPLE))
        if rw["coins"]:
            chips.append((f"+{rw['coins']} coins", SG_GOLD))
        widths = [font_small_bold.size(l)[0] + 28 for l, _ in chips]
        x = WIDTH // 2 - (sum(widths) + 8 * (len(chips) - 1)) // 2
        for (lab, c), w in zip(chips, widths):
            chip = pygame.Rect(x, y + int((1 - rp) * 10), w, 36)
            pygame.draw.rect(surface, mix_color(c, SG_BG, 0.8), chip, border_radius=18)
            pygame.draw.rect(surface, mix_color(c, SG_BG, 0.5), chip, 1, border_radius=18)
            draw_text(surface, lab, font_small_bold, c, chip.centerx, chip.centery - 9, align="center")
            x += w + 8
    y += 54
    if rw["unlocked"] and t > 1.2:
        nr = rw["unlocked"]
        card = pygame.Rect(20, y, WIDTH - 40, 72)
        sg_panel(surface, card, 18)
        pygame.draw.rect(surface, _bot_style(nr)["color"], card, 2, border_radius=18)
        _bot_badge(surface, nr, card.x + 38, card.centery, 20)
        draw_text(surface, "New rival unlocked!", font_tiny, _bot_style(nr)["color"], card.x + 72, card.y + 16)
        draw_text(surface, nr["name"], font_medium_bold, SG_TEXT, card.x + 72, card.y + 32)
        if _sg_fx_once_in(b, "unlock"):
            play_sound("achievement")

    bp = ease_out_cubic((t - 1.2) / 0.35)
    if bp > 0:
        off = int((1 - bp) * 40)
        _sg_button(surface, pygame.Rect(20, HEIGHT - 150 + off, WIDTH - 40, 60), "rematch", "Rematch", SG_GOLD, SG_INK, icon="bolt",
                   btns=b["btns"])
        _sg_button(surface, pygame.Rect(20, HEIGHT - 76 + off, WIDTH - 40, 50), "back", "Back to Arena", SG_PANEL_2, SG_TEXT,
                   font=font_body_bold, depth=4, btns=b["btns"])


def draw_battle(surface):
    b = battle
    if not b.get("open"):
        return True
    now = time.time()
    b["btns"] = {}
    frame = _sg_layer("frame", (WIDTH, HEIGHT))
    _sg_background(frame, now, _bot_style(b["rival"])["color"])
    {"brief": _battle_draw_brief, "count": _battle_draw_count, "fight": _battle_draw_fight,
     "result": _battle_draw_result}[b["stage"]](frame, now)
    sx = sy = 0.0
    k = 1 - (now - b.get("shake_at", 0.0)) / 0.45
    if k > 0:
        amp = b.get("shake_amp", 0.0) * k * k
        sx, sy = math.sin(now * 71) * amp, math.cos(now * 57) * amp * 0.6
    surface.fill(SG_BG)
    surface.blit(frame, (int(sx), int(sy)))
    return True


# ---- Arena page ----

arena_btns = []


def draw_arena_tab(surface):
    global arena_btns
    arena_btns = []
    now = time.time()
    off = scroll_offset["arena"]
    clip = pygame.Rect(0, GAME_TOP, WIDTH, CONTENT_BOTTOM - GAME_TOP)
    prev = surface.get_clip()
    surface.set_clip(clip)
    y0 = GAME_TOP + 6 - off
    y = y0

    # Hero.
    name, floor, lcol = league_tier()
    nxt = next((t for t in LEAGUE_TIERS if t[1] > state.trophies), None)
    hero = pygame.Rect(20, y, WIDTH - 40, 150)
    pygame.draw.rect(surface, SG_PANEL, hero, border_radius=24)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    surface.blit(_hero_glow(hero.size, [((*SG_RED, 50), (hero.w - 60, 40), 90), ((*SG_GOLD, 50), (40, hero.h), 70)], 18), hero.topleft)
    pygame.draw.rect(surface, SG_LINE, hero, 1, border_radius=24)
    draw_text(surface, "Battle arena", font_tiny, SG_MUTED, hero.x + 20, hero.y + 20)
    draw_text(surface, "Out-trade the bots", font_sg_h2, SG_TEXT, hero.x + 20, hero.y + 38)
    wins, played = state.total_wins, state.total_duels
    draw_text(surface, f"{wins} win{'s' if wins != 1 else ''}  ·  {played} battle{'s' if played != 1 else ''}  ·  {state.win_streak} streak",
              font_small, SG_MUTED, hero.x + 20, hero.y + 72, max_width=hero.w - 140)
    chip = _sg_chip(surface, hero.x + 20, hero.y + 104, f"{name} league", lcol, mix_color(lcol, SG_BG, 0.75), icon="star", h=28)
    if nxt:
        draw_text(surface, f"{nxt[1] - state.trophies} to {nxt[0]}", font_tiny, SG_MUTED, chip.right + 10, chip.y + 7)
    tc = (hero.right - 62, hero.y + 72)
    pygame.draw.circle(surface, SG_PANEL_2, tc, 42)
    pygame.draw.circle(surface, lcol, tc, 42, 3)
    draw_trophy_icon(surface, tc[0], tc[1] - 10, SG_GOLD, 1.3)
    draw_text(surface, f"{state.trophies:,}", font_body_bold, SG_TEXT, tc[0], tc[1] + 10, align="center")
    y = hero.bottom + 16

    # How battles work.
    steps = [("coin", SG_GOLD, "Start equal", f"You and the bot each get {fmt_money(BATTLE_CASH)} of battle cash."),
             ("news", SG_CYAN, "Watch the news", "Breaking news pushes a stock up or down for a few seconds."),
             ("chart", SG_GREEN, "Buy low, sell high", "Buy stocks with good news. Sell after they rise to lock in profit."),
             ("star", SG_PURPLE, "Beat the clock", "When time runs out, whoever has more money wins.")]
    bodies = [sg_wrap(body, font_small, WIDTH - 40 - 86) for _, _, _, body in steps]
    card = pygame.Rect(20, y, WIDTH - 40, 76 + sum(26 + len(bl) * 19 + 14 for bl in bodies))
    sg_panel(surface, card, 22)
    draw_text(surface, "How battles work", font_medium_bold, SG_TEXT, card.x + 20, card.y + 16)
    draw_text(surface, "Battles use battle cash. Your real portfolio is never touched.", font_tiny, SG_MUTED, card.x + 20, card.y + 42,
              max_width=card.w - 40)
    ry = card.y + 72
    for i, (icon, col, title, body) in enumerate(steps):
        pygame.draw.circle(surface, mix_color(col, SG_PANEL, 0.72), (card.x + 36, ry + 18), 18)
        if icon == "coin":
            draw_coin_icon(surface, card.x + 36, ry + 18, 9)
        elif icon == "news":
            draw_glyph(surface, "news", card.x + 36, ry + 18, col, 0.7)
        else:
            _sg_icon(surface, icon, card.x + 36, ry + 18, col, 0.85)
        draw_text(surface, f"{i + 1}. {title}", font_body_bold, SG_TEXT, card.x + 66, ry)
        for j, line in enumerate(bodies[i]):
            draw_text(surface, line, font_small, SG_MUTED, card.x + 66, ry + 24 + j * 19)
        ry += 26 + len(bodies[i]) * 19 + 14
    y = card.bottom + 22

    # Opponents.
    y = sg_section_title(surface, 20, y, "Choose your opponent", "Beat a bot to unlock the next one.")
    for rival in RIVALS:
        info = _bot_style(rival)
        plan_lines = sg_wrap(info["plan"], font_small, WIDTH - 40 - 40)
        beat_lines = sg_wrap(info["beat"], font_small, WIDTH - 40 - 40)
        h = 84 + len(plan_lines) * 19 + 12 + 18 + len(beat_lines) * 19 + 16 + 40 + 16
        card = pygame.Rect(20, y, WIDTH - 40, h)
        locked = not rival["unlocked"]
        beaten = rival["id"] <= state.highest_bot_beaten
        sg_panel(surface, card, 22)
        if not locked:
            pygame.draw.rect(surface, info["color"], (card.x, card.y + 18, 4, 56), border_radius=2)
        _bot_badge(surface, rival, card.x + 46, card.y + 46, 26 if not locked else 22)
        if locked:
            pygame.draw.circle(surface, (*SG_BG,), (card.x + 46, card.y + 46), 27)
            draw_padlock(surface, card.x + 46, card.y + 46, 20, SG_MUTED)
        draw_text(surface, rival["name"], font_medium_bold, SG_MUTED if locked else SG_TEXT, card.x + 86, card.y + 20)
        for k in range(6):
            pygame.draw.rect(surface, info["color"] if (k < rival["difficulty"] and not locked) else SG_PANEL_2,
                             (card.x + 86 + k * 12, card.y + 48, 9, 9), border_radius=2)
        draw_text(surface, "Difficulty", font_tiny, SG_MUTED, card.x + 86 + 6 * 12 + 6, card.y + 45)
        if beaten:
            _sg_chip(surface, card.right - 18, card.y + 20, "Beaten", SG_GREEN, mix_color(SG_GREEN, SG_BG, 0.8), icon="check", align="right")
        ty = card.y + 84
        for line in plan_lines:
            draw_text(surface, line, font_small, SG_MUTED if locked else SG_TEXT, card.x + 20, ty)
            ty += 19
        ty += 12
        draw_text(surface, "How to beat them", font_small_bold, SG_GOLD if not locked else SG_MUTED, card.x + 20, ty)
        ty += 20
        for line in beat_lines:
            draw_text(surface, line, font_small, SG_MUTED, card.x + 20, ty)
            ty += 19
        by = card.bottom - 56
        if locked:
            prev_name = next((r["name"] for r in RIVALS if r["id"] == rival["id"] - 1), "the previous bot")
            box = pygame.Rect(card.x + 16, by, card.w - 32, 40)
            pygame.draw.rect(surface, SG_BG, box, border_radius=14)
            draw_text(surface, f"Beat {prev_name} to unlock", font_small_bold, SG_MUTED, box.centerx, box.centery - 9, align="center")
        else:
            btn = pygame.Rect(card.x + 16, by, card.w - 32, 40)
            _draw_plain_button(surface, btn, f"Battle {rival['name'].split()[-1]}", SG_GOLD, SG_INK)
            arena_btns.append((btn, rival))
        y = card.bottom + 14

    # Weekly league.
    y = sg_section_title(surface, 20, y + 10, "This week's league", "Top 3 earn bonus XP. Win battles for points.")
    rows = league_standings()
    me_i = next(i for i, r in enumerate(rows) if r["me"])
    show = list(range(min(3, len(rows))))
    show.append(me_i if me_i >= 3 else 3)
    card = pygame.Rect(20, y, WIDTH - 40, 20 + len(show) * 44)
    sg_panel(surface, card, 22)
    ry = card.y + 10
    for i in show:
        if i >= len(rows):
            continue
        r = rows[i]
        box = pygame.Rect(card.x + 10, ry, card.w - 20, 40)
        if r["me"]:
            pygame.draw.rect(surface, mix_color(SG_GOLD, SG_PANEL, 0.82), box, border_radius=12)
        medal = [SG_GOLD, (203, 213, 225), (217, 119, 6)][i] if i < 3 else SG_PANEL_2
        pygame.draw.circle(surface, medal, (box.x + 22, box.centery), 13)
        draw_text(surface, str(i + 1), font_small_bold, SG_INK if i < 3 else SG_TEXT, box.x + 22, box.centery - 9, align="center")
        draw_text(surface, "You" if r["me"] else r["name"], font_body_bold if r["me"] else font_body, SG_TEXT, box.x + 46, box.centery - 10,
                  max_width=box.w - 140)
        draw_text(surface, f"{r['points']} pts", font_small_bold, SG_GOLD if r["me"] else SG_MUTED, box.right - 12, box.centery - 9, align="right")
        ry += 44
    y = card.bottom + 30
    clamp_scroll_full("arena", y - y0)
    surface.set_clip(prev)


def handle_arena_click(pos):
    if not (GAME_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    for rect, rival in arena_btns:
        if rect.collidepoint(pos):
            open_battle(rival, 60)
            return True
    return False


# ----------------------------
# FRIENDS (real requests between Ledger accounts on this device)
# ----------------------------
# Social links live on each account record under "social", outside "profile", so
# save_game() never overwrites a request another player sent while you were playing.

friend_action_rects = []
_social_cache = {"at": 0.0, "user": None, "data": None}
SOCIAL_REFRESH_SECONDS = 3.0


def _social_of(record):
    social = record.setdefault("social", {})
    for k in ("friends", "incoming", "outgoing", "blocked"):
        if not isinstance(social.get(k), list):
            social[k] = []
    return social


def _social_rename(accounts, old_key, new_key):
    for rec in accounts.get("accounts", {}).values():
        if isinstance(rec, dict) and isinstance(rec.get("social"), dict):
            for k in ("friends", "incoming", "outgoing", "blocked"):
                rec["social"][k] = [new_key if x == old_key else x for x in rec["social"].get(k, [])]


def social_snapshot(force=False):
    """Friends (with their live stats), incoming and outgoing requests for the current player."""
    now = time.time()
    me = _normalize_account_key(state.account_username) if getattr(state, "logged_in", False) and state.account_username else None
    c = _social_cache
    if not force and c["user"] == me and c["data"] is not None and now - c["at"] < SOCIAL_REFRESH_SECONDS:
        return c["data"]
    data = {"friends": [], "incoming": [], "outgoing": [], "blocked": []}
    if me:
        accounts = _read_accounts().get("accounts", {})
        rec = accounts.get(me)
        if isinstance(rec, dict):
            social = _social_of(rec)

            def info(key):
                other = accounts.get(key)
                if not isinstance(other, dict):
                    return None
                prof = other.get("profile", {}) if isinstance(other.get("profile"), dict) else {}
                eq = prof.get("equipped") if isinstance(prof.get("equipped"), dict) else {}
                name = str(other.get("username", key))
                if not ledger_safety.is_kid_safe(name):
                    name = "Hidden name"  # saved before the username filter existed
                return {"key": key, "name": name, "avatar": prof.get("avatar"),
                        "trophies": int(prof.get("trophies", 0) or 0), "streak": int(prof.get("win_streak", 0) or 0),
                        "level": int(prof.get("level", 1) or 1), "frame": eq.get("frame"), "title": eq.get("title")}
            for k in ("friends", "incoming", "outgoing", "blocked"):
                keys = social[k] if k == "blocked" else [x for x in social[k] if x not in social["blocked"]]
                data[k] = [x for x in (info(key) for key in keys) if x]
    c.update(at=now, user=me, data=data)
    return data


def _social_update(fn):
    """Read-modify-write the accounts file for a social action, then refresh the cache."""
    accounts = _read_accounts()
    fn(accounts.setdefault("accounts", {}))
    _write_accounts(accounts)
    social_snapshot(force=True)


def send_friend_request(username):
    name = " ".join(username.strip().split())
    if not name:
        return
    if not getattr(state, "logged_in", False):
        show_toast("Log in to add friends", "Guest progress isn't saved, so guests can't have friends.", "warning")
        play_sound("error")
        return
    me = _normalize_account_key(state.account_username)
    target = _normalize_account_key(name)
    accounts = _read_accounts().get("accounts", {})
    if target == me:
        show_toast("That's you!", "Type a friend's Ledger username instead.", "warning")
        play_sound("error")
        return
    if target not in accounts:
        show_toast("Player not found", f"No Ledger account named “{name}” on this device.", "warning")
        play_sound("error")
        return
    snap = social_snapshot(force=True)
    display = accounts[target].get("username", name)
    if any(f["key"] == target for f in snap["blocked"]):
        show_toast("You blocked this player", "Unblock them under Manage friends first.", "warning")
        play_sound("error")
        return
    if me in _social_of(accounts[target])["blocked"]:
        show_toast("Can't send a request", "This player isn't taking requests from you.", "warning")
        play_sound("error")
        return
    if any(f["key"] == target for f in snap["friends"]):
        show_toast("Already friends", f"{display} is already on your leaderboard.", "warning")
        play_sound("error")
        return
    if any(f["key"] == target for f in snap["outgoing"]):
        show_toast("Request already sent", f"Waiting for {display} to accept.", "warning")
        play_sound("error")
        return
    if any(f["key"] == target for f in snap["incoming"]):
        accept_friend_request(target)
        return

    def apply(accts):
        _social_of(accts[me])["outgoing"].append(target) if target not in _social_of(accts[me])["outgoing"] else None
        inc = _social_of(accts[target])["incoming"]
        if me not in inc:
            inc.append(me)
    if me in accounts:
        _social_update(apply)
    show_toast("Friend request sent", f"{display} will see it next time they open Ledger.", "achievement")
    play_sound("click")
    state.friend_input_text = ""


def accept_friend_request(key):
    me = _normalize_account_key(state.account_username)

    def apply(accts):
        if me not in accts or key not in accts:
            return
        mine, theirs = _social_of(accts[me]), _social_of(accts[key])
        for lst, val in ((mine["incoming"], key), (mine["outgoing"], key), (theirs["incoming"], me), (theirs["outgoing"], me)):
            while val in lst:
                lst.remove(val)
        if key not in mine["friends"]:
            mine["friends"].append(key)
        if me not in theirs["friends"]:
            theirs["friends"].append(me)
    _social_update(apply)
    name = next((f["name"] for f in social_snapshot()["friends"] if f["key"] == key), key)
    show_toast("New friend!", f"You and {name} are now on each other's leaderboard.", "achievement")
    play_sound("achievement")
    spawn_confetti(40)


def decline_friend_request(key):
    me = _normalize_account_key(state.account_username)

    def apply(accts):
        if me in accts:
            lst = _social_of(accts[me])["incoming"]
            while key in lst:
                lst.remove(key)
        if key in accts:
            lst = _social_of(accts[key])["outgoing"]
            while me in lst:
                lst.remove(me)
    _social_update(apply)
    play_sound("click")


def cancel_friend_request(key):
    me = _normalize_account_key(state.account_username)

    def apply(accts):
        if me in accts:
            lst = _social_of(accts[me])["outgoing"]
            while key in lst:
                lst.remove(key)
        if key in accts:
            lst = _social_of(accts[key])["incoming"]
            while me in lst:
                lst.remove(me)
    _social_update(apply)
    play_sound("click")


def remove_friend(key):
    me = _normalize_account_key(state.account_username)

    def apply(accts):
        for a, b in ((me, key), (key, me)):
            if a in accts:
                lst = _social_of(accts[a])["friends"]
                while b in lst:
                    lst.remove(b)
    _social_update(apply)
    play_sound("click")


def handle_leaderboard_click(pos):
    if friend_add_btn_rect and friend_add_btn_rect.collidepoint(pos):
        send_friend_request(state.friend_input_text)
        return True
    for rect, action, key in friend_action_rects:
        if rect.collidepoint(pos):
            {"accept": accept_friend_request, "decline": decline_friend_request,
             "cancel": cancel_friend_request, "remove": remove_friend, "block": block_player,
             "unblock": unblock_player}[action](key)
            return True
    return False


def draw_leaderboard_tab(surface):
    global friend_add_btn_rect, friend_input_rect, friend_action_rects
    friend_action_rects = []
    off = scroll_offset["leaderboard"]
    clip_rect = pygame.Rect(0, CONTENT_TOP, WIDTH, CONTENT_BOTTOM - CONTENT_TOP)
    prev_clip = surface.get_clip()
    surface.set_clip(clip_rect)
    snap = social_snapshot()
    draw_text(surface, "Friends", font_sg_h2, C("INK"), 20, CONTENT_TOP - off)
    draw_text(surface, "Add a friend by their Ledger username. They'll get a request.", font_small, C("GRAY"), 20, CONTENT_TOP + 31 - off, max_width=WIDTH - 40)

    friend_input_rect = pygame.Rect(20, CONTENT_TOP + 52 - off, WIDTH - 140, 42)
    draw_rounded_rect(surface, friend_input_rect, C("CARD"), radius=12, border_color=C("PURPLE") if state.friend_input_text else C("BORDER"), border_width=2 if state.friend_input_text else 1)
    draw_search_icon(surface, friend_input_rect.x + 12, friend_input_rect.y + 13, C("GRAY"))
    draw_text(surface, state.friend_input_text or "Friend's username", font_body, C("INK") if state.friend_input_text else C("LIGHT_GRAY"), friend_input_rect.x + 36, friend_input_rect.y + 12, max_width=friend_input_rect.w - 44)
    friend_add_btn_rect = pygame.Rect(friend_input_rect.right + 10, friend_input_rect.y, 90, 42)
    draw_button(surface, friend_add_btn_rect, "Send", C("PURPLE"), (255, 255, 255), font=font_small_bold, radius=12)
    y = friend_input_rect.bottom + 18

    if not getattr(state, "logged_in", False):
        note = pygame.Rect(20, y, WIDTH - 40, 50)
        draw_rounded_rect(surface, note, C("GOLD_BG"), radius=12, border_color=C("GOLD"), border_width=1, shadow=False)
        draw_text(surface, "You're a guest. Log in or create an account to add friends.", font_small_bold, C("INK"), note.centerx, note.y + 16, align="center", max_width=note.w - 20)
        y = note.bottom + 16

    def person_row(rect, person, sub, sub_col):
        if isinstance(person.get("avatar"), dict):
            draw_avatar_icon(surface, person["avatar"], (rect.x + 30, rect.centery), size=40)
        draw_text(surface, person["name"], font_body_bold, C("INK"), rect.x + 58, rect.y + 11, max_width=rect.w - 250)
        draw_text(surface, sub, font_tiny, sub_col, rect.x + 58, rect.y + 32, max_width=rect.w - 250)

    if snap["incoming"]:
        draw_text(surface, f"FRIEND REQUESTS  ({len(snap['incoming'])})", font_tiny, C("RED"), 20, y)
        y += 20
        for p in snap["incoming"]:
            rect = pygame.Rect(20, y, WIDTH - 40, 58)
            draw_rounded_rect(surface, rect, C("PURPLE_BG"), radius=14, border_color=C("PURPLE"), border_width=1)
            person_row(rect, p, f"{p['trophies']} trophies", C("PURPLE"))
            acc = pygame.Rect(rect.right - 196, rect.y + 12, 70, 34)
            dec = pygame.Rect(rect.right - 120, rect.y + 12, 46, 34)
            blk = pygame.Rect(rect.right - 68, rect.y + 12, 56, 34)
            draw_button(surface, acc, "Accept", C("GREEN"), (255, 255, 255), font=font_small_bold, radius=10)
            draw_button(surface, dec, "No", C("PANEL_BG"), C("INK"), font=font_small_bold, radius=10)
            draw_button(surface, blk, "Block", C("PANEL_BG"), C("RED"), font=font_tiny, radius=10)
            friend_action_rects += [(acc, "accept", p["key"]), (dec, "decline", p["key"]), (blk, "block", p["key"])]
            y += 66
        y += 6

    if snap["outgoing"]:
        draw_text(surface, "SENT  •  WAITING FOR THEM TO ACCEPT", font_tiny, C("GRAY"), 20, y)
        y += 20
        for p in snap["outgoing"]:
            rect = pygame.Rect(20, y, WIDTH - 40, 52)
            draw_rounded_rect(surface, rect, C("CARD"), radius=14, border_color=C("BORDER"), border_width=1)
            person_row(rect, p, "Request pending", C("GRAY"))
            cancel = pygame.Rect(rect.right - 84, rect.y + 10, 72, 32)
            draw_button(surface, cancel, "Cancel", C("PANEL_BG"), C("INK"), font=font_tiny, radius=10)
            friend_action_rects.append((cancel, "cancel", p["key"]))
            y += 60
        y += 6

    draw_text(surface, "LEADERBOARD", font_tiny, C("GRAY"), 20, y)
    y += 20
    rows = [{"name": state.player_name, "avatar": state.avatar, "trophies": state.trophies, "streak": state.win_streak,
             "level": state.level, "is_user": True, "frame": equipped("frame")["id"], "title": equipped("title")["id"]}]
    rows.extend(snap["friends"])
    rows.sort(key=lambda f: f["trophies"], reverse=True)
    medal_cols = [(255, 196, 0), (192, 192, 200), (205, 127, 50)]
    for i, friend in enumerate(rows):
        rect = pygame.Rect(20, y, WIDTH - 40, 68)
        me = friend.get("is_user")
        draw_rounded_rect(surface, rect, C("GOLD_BG") if me else C("CARD"), radius=14, border_color=C("GOLD") if me else C("BORDER"), border_width=1)
        mc = (rect.x + 24, rect.centery)
        if i < 3:
            pygame.draw.circle(surface, medal_cols[i], mc, 14)
            draw_text(surface, str(i + 1), font_small_bold, text_on(medal_cols[i]), mc[0], mc[1] - 9, align="center")
        else:
            draw_text(surface, f"#{i + 1}", font_small_bold, C("GRAY"), mc[0], mc[1] - 9, align="center")
        if isinstance(friend.get("avatar"), dict):
            draw_avatar_icon(surface, friend["avatar"], (rect.x + 70, rect.centery), size=44, selected=me)
            draw_avatar_frame(surface, (rect.x + 70, rect.centery), 22, friend.get("frame"))
        name = friend["name"] + ("  (You)" if me else "")
        draw_text(surface, name, font_body_bold, C("INK"), rect.x + 100, rect.y + 12, max_width=rect.w - 210)
        tchip = draw_title_chip(surface, rect.x + 100, rect.y + 36, friend.get("title") or "title_rookie")
        draw_text(surface, f"Lv {friend.get('level', 1)}", font_tiny, C("GRAY"), tchip.right + 8, rect.y + 37)
        draw_text(surface, f"{friend['trophies']}", font_medium_bold, C("INK"), rect.right - 16, rect.y + 13, align="right")
        draw_text(surface, "trophies", font_tiny, C("GRAY"), rect.right - 16, rect.y + 37, align="right")
        y += 76
    if len(rows) == 1:
        draw_text(surface, "Just you so far. Send a request to a friend above!", font_small, C("LIGHT_GRAY"), WIDTH // 2, y + 6, align="center")
        y += 40
    if snap["friends"] or snap["blocked"]:
        y += 10
        draw_text(surface, "MANAGE FRIENDS", font_tiny, C("GRAY"), 20, y)
        y += 20
        for p, actions in [(p, (("Remove", "remove"), ("Block", "block"))) for p in snap["friends"]] + \
                          [(p, (("Unblock", "unblock"),)) for p in snap["blocked"]]:
            rect = pygame.Rect(20, y, WIDTH - 40, 52)
            draw_rounded_rect(surface, rect, C("CARD"), radius=14, border_color=C("BORDER"), border_width=1)
            person_row(rect, p, "Blocked" if actions[0][1] == "unblock" else "Friend", C("GRAY"))
            bx = rect.right - 12
            for label, action in reversed(actions):
                w = 74 if label == "Unblock" else 64
                b = pygame.Rect(bx - w, rect.y + 10, w, 32)
                draw_button(surface, b, label, C("PANEL_BG"), C("RED") if action == "block" else C("INK"), font=font_tiny, radius=10)
                friend_action_rects.append((b, action, p["key"]))
                bx -= w + 8
            y += 60
    clamp_scroll("leaderboard", (y - (CONTENT_TOP - off)) + off)
    surface.set_clip(prev_clip)


def draw_news_tab(surface):
    global news_trade_rects, market_search_rect, market_clear_rect
    news_trade_rects = []
    now = time.time()
    state.news_seen_at = now  # viewing News clears its unread badge
    off = scroll_offset["news"]
    clip_rect = pygame.Rect(0, CONTENT_TOP, WIDTH, CONTENT_BOTTOM - CONTENT_TOP)
    prev_clip = surface.get_clip()
    surface.set_clip(clip_rect)
    draw_text(surface, "Market News", font_sg_h2, C("INK"), 20, CONTENT_TOP - off)
    draw_text(surface, ("Real headlines + real quotes" if state.live_mode else "Stories move the stocks they mention") + "  •  tap Trade to act",
              font_small, C("GRAY"), 20, CONTENT_TOP + 31 - off, max_width=WIDTH - 40)
    search_y = CONTENT_TOP + 52 - off
    market_search_rect = pygame.Rect(20, search_y, WIDTH - 60, 40)
    draw_rounded_rect(surface, market_search_rect, C("CARD"), radius=10, border_color=C("PURPLE") if state.market_search_active else C("BORDER"), border_width=2 if state.market_search_active else 1)
    draw_search_icon(surface, market_search_rect.x + 12, market_search_rect.y + 11, C("GRAY"))
    draw_text(surface, state.market_search or "Search a stock to trade from anywhere", font_body, C("INK") if state.market_search else C("LIGHT_GRAY"), market_search_rect.x + 34, market_search_rect.y + 11)
    market_clear_rect = pygame.Rect(WIDTH - 34, search_y + 6, 28, 28)
    if state.market_search:
        draw_text(surface, "×", font_medium_bold, C("GRAY"), market_clear_rect.centerx, market_clear_rect.y + 4, align="center")
    y = search_y + 56
    if not state.news_feed:
        draw_text(surface, "Waiting for the next market story…", font_body_bold, C("GRAY"), WIDTH // 2, y + 20, align="center")
        surface.set_clip(prev_clip)
        return
    highlight_id, highlight_until = getattr(state, "news_highlight", (None, 0))
    for item in state.news_feed:
        ticker = item.get("ticker", "SECTOR")
        asset = find_asset(ticker)
        lines = wrap_text(item["headline"], font_body_bold, WIDTH - 40 - 32)[:4]
        card_h = 100 + len(lines) * 20
        rect = pygame.Rect(20, y, WIDTH - 40, card_h)
        iid = news_item_id(item)
        if getattr(state, "news_scroll_to", None) == iid:
            # Jump so a story opened from a notification sits at the top of the list.
            state.news_scroll_to = None
            scroll_offset["news"] = max(0, off + (y - (CONTENT_TOP + 8)))
        if rect.bottom > CONTENT_TOP - 5 and rect.top < CONTENT_BOTTOM + 5:
            lit = iid == highlight_id and now < highlight_until
            if lit:
                glow = 0.5 + 0.5 * math.sin(now * 6)
                draw_alpha_rect(surface, rect.inflate(10, 10), C("PURPLE"), 50 + 60 * glow, radius=18)
            draw_rounded_rect(surface, rect, C("CARD"), radius=14, border_color=C("PURPLE") if lit else C("BORDER"), border_width=2 if lit else 1)
            real = item.get("real_news")
            direction = item.get("quote_direction", "neutral") if real else item.get("direction", "neutral")
            dcol = C("GREEN") if direction == "up" else (C("RED") if direction == "down" else C("GRAY"))
            # Header: badge, ticker, event tag, time.
            if asset:
                draw_ticker_badge(surface, ticker, rect.x + 14, rect.y + 14, size=34)
            else:
                globe = (rect.x + 31, rect.y + 31)
                pygame.draw.circle(surface, C("PURPLE"), globe, 17)
                pygame.draw.circle(surface, (255, 255, 255), globe, 9, 2)
                pygame.draw.line(surface, (255, 255, 255), (globe[0] - 9, globe[1]), (globe[0] + 9, globe[1]), 2)
                pygame.draw.ellipse(surface, (255, 255, 255), (globe[0] - 4, globe[1] - 9, 8, 18), 2)
            name = asset["name"] if asset else ("Whole market" if ticker == "MARKET" else item.get("sector", "Market"))
            draw_text(surface, name, font_small_bold, C("INK"), rect.x + 58, rect.y + 13, max_width=rect.w - 170)
            tag = item.get("event") or ("Real headline" if real else ("Price alert" if item.get("volatility_event") else "Company news"))
            draw_text(surface, f"{tag}  •  {time_ago(item.get('arrived', item.get('time', now)))}", font_tiny, C("GRAY"), rect.x + 58, rect.y + 32, max_width=rect.w - 170)
            ty = rect.y + 58
            for line in lines:
                draw_text(surface, line, font_body_bold, C("INK"), rect.x + 16, ty)
                ty += 20
            # Footer: what the news means and what the stock actually did.
            fy = rect.bottom - 34
            if real:
                senti = item.get("sentiment_direction", "neutral")
                label = {"up": "Positive headline", "down": "Negative headline"}.get(senti, "Neutral headline")
                chip_col = C("GREEN") if senti == "up" else (C("RED") if senti == "down" else C("GRAY"))
            else:
                what = "stock" if asset else "market"
                label = {"up": f"Good news for the {what}", "down": f"Bad news for the {what}"}.get(direction, "Mixed news")
                chip_col = dcol
            cw = font_tiny.size(label)[0] + 18
            chip = pygame.Rect(rect.x + 14, fy, cw, 22)
            draw_rounded_rect(surface, chip, mix_color(chip_col, C("CARD"), 0.85), radius=11, shadow=False)
            draw_text(surface, label, font_tiny, chip_col, chip.centerx, chip.y + 4, align="center")
            if asset:
                if real:
                    mv, mlabel = day_move_pct(asset), "Today"
                else:
                    base = item.get("price_at") or asset["price"]
                    mv, mlabel = ((asset["price"] - base) / base * 100 if base else 0.0), "Since story"
                mcol = C("GREEN") if mv > 0.005 else (C("RED") if mv < -0.005 else C("GRAY"))
                draw_text(surface, f"{mlabel} {mv:+.2f}%", font_tiny, mcol, chip.right + 10, fy + 4, max_width=rect.right - 110 - chip.right)
            btn = pygame.Rect(rect.right - 90, fy - 6, 76, 32)
            if asset:
                draw_button(surface, btn, "Trade", C("INK"), C("CARD"), font=font_small_bold, radius=10)
                news_trade_rects.append((btn, ticker))
            elif ticker == "MARKET":
                draw_button(surface, btn, "Market", C("PANEL_BG"), C("INK"), font=font_small_bold, radius=10)
                news_trade_rects.append((btn, "MARKET"))
        y += card_h + 10
    clamp_scroll("news", (y - (CONTENT_TOP - off)) + off)
    surface.set_clip(prev_clip)


def draw_settings_tab(surface):
    global settings_click_rects
    settings_click_rects = {}
    off = scroll_offset["settings"]
    clip_rect = pygame.Rect(0, CONTENT_TOP, WIDTH, CONTENT_BOTTOM - CONTENT_TOP)
    prev_clip = surface.get_clip()
    surface.set_clip(clip_rect)
    y = CONTENT_TOP - off
    draw_text(surface, "Account Settings", font_sg_h2, C("INK"), 20, y)
    draw_text(surface, "Sound, accessibility, username and password", font_small, C("GRAY"), 20, y + 31)
    y += 56
    draw_text(surface, "Appearance", font_small_bold, C("GRAY"), 20, y)
    y += 20
    sound_btn = pygame.Rect(20, y, WIDTH - 40, 44)
    draw_button(surface, sound_btn, f"Sound: {'On' if state.sound_enabled else 'Off'}", C("CARD"), C("INK"), radius=10)
    settings_click_rects["sound"] = sound_btn
    y += 52
    half = (WIDTH - 50) // 2
    cb_btn = pygame.Rect(20, y, half, 44)
    draw_button(surface, cb_btn, f"Colorblind: {'On' if state.colorblind else 'Off'}", C("CARD"), C("INK"), font=font_small_bold, radius=10)
    settings_click_rects["colorblind"] = cb_btn
    rm_btn = pygame.Rect(30 + half, y, half, 44)
    draw_button(surface, rm_btn, f"Less motion: {'On' if state.reduced_motion else 'Off'}", C("CARD"), C("INK"), font=font_small_bold, radius=10)
    settings_click_rects["reduced_motion"] = rm_btn
    y += 58
    draw_text(surface, "Change username & password", font_small_bold, C("GRAY"), 20, y)
    y += 18
    hint = "Confirm your current password first." if state.password else "No password yet. Set one below. Old password can be blank."
    draw_text(surface, hint, font_tiny, C("GRAY"), 20, y)
    y += 20
    draw_text(surface, "Current password", font_tiny, C("GRAY"), 20, y)
    y += 16
    old_pw_box = pygame.Rect(20, y, WIDTH - 40, 36)
    draw_rounded_rect(surface, old_pw_box, C("CARD"), radius=8, border_color=C("INK") if state.settings_active_field == "old_pw" else C("BORDER"), border_width=1)
    draw_text(surface, "*" * len(state.settings_old_pw) if state.settings_old_pw else "Type current password...", font_body, C("INK") if state.settings_old_pw else C("LIGHT_GRAY"), old_pw_box.x + 10, old_pw_box.y + 8)
    settings_click_rects["old_pw"] = old_pw_box
    y += 44
    draw_text(surface, "New username", font_tiny, C("GRAY"), 20, y)
    y += 16
    new_user_box = pygame.Rect(20, y, WIDTH - 40, 36)
    draw_rounded_rect(surface, new_user_box, C("CARD"), radius=8, border_color=C("INK") if state.settings_active_field == "new_user" else C("BORDER"), border_width=1)
    draw_text(surface, state.settings_new_user or state.player_name, font_body, C("INK") if state.settings_new_user else C("LIGHT_GRAY"), new_user_box.x + 10, new_user_box.y + 8)
    settings_click_rects["new_user"] = new_user_box
    y += 44
    draw_text(surface, "New password", font_tiny, C("GRAY"), 20, y)
    y += 16
    new_pw_box = pygame.Rect(20, y, WIDTH - 40, 36)
    draw_rounded_rect(surface, new_pw_box, C("CARD"), radius=8, border_color=C("INK") if state.settings_active_field == "new_pw" else C("BORDER"), border_width=1)
    draw_text(surface, "*" * len(state.settings_new_pw) if state.settings_new_pw else "Type new password...", font_body, C("INK") if state.settings_new_pw else C("LIGHT_GRAY"), new_pw_box.x + 10, new_pw_box.y + 8)
    settings_click_rects["new_pw"] = new_pw_box
    y += 48
    save_btn = pygame.Rect(20, y, WIDTH - 40, 44)
    draw_button(surface, save_btn, "Save Changes", C("INK"), C("CARD"), radius=10)
    settings_click_rects["save"] = save_btn
    y += 58
    switch_btn = pygame.Rect(20, y, WIDTH - 40, 42)
    draw_button(surface, switch_btn, "Add / Switch Account", C("PANEL_BG"), C("INK"), radius=10)
    settings_click_rects["switch_account"] = switch_btn
    y += 52
    logout_btn = pygame.Rect(20, y, WIDTH - 40, 42)
    draw_button(surface, logout_btn, "Log Out", C("RED"), C("CARD"), radius=10)
    settings_click_rects["logout"] = logout_btn
    y += 62

    if state.logged_in:
        draw_text(surface, "Your data", font_small_bold, C("GRAY"), 20, y)
        y += 18
        draw_text(surface, "Everything Ledger saves stays on this computer.", font_tiny, C("GRAY"), 20, y)
        y += 22
        export_btn = pygame.Rect(20, y, WIDTH - 40, 42)
        draw_button(surface, export_btn, "Download my data", C("PANEL_BG"), C("INK"), radius=10)
        settings_click_rects["export"] = export_btn
        y += 50
        if not state.settings_confirm_delete:
            del_btn = pygame.Rect(20, y, WIDTH - 40, 42)
            draw_button(surface, del_btn, "Delete my account", C("CARD"), C("RED"), radius=10)
            pygame.draw.rect(surface, C("RED"), del_btn, 1, border_radius=10)
            settings_click_rects["delete"] = del_btn
            y += 56
        else:
            card = pygame.Rect(20, y, WIDTH - 40, 150)
            draw_rounded_rect(surface, card, C("CARD"), radius=12, border_color=C("RED"), border_width=2)
            draw_text(surface, "Delete this account forever?", font_body_bold, C("RED"), card.x + 14, card.y + 12)
            draw_text(surface, "Progress, trader and friends are erased. This can't be undone.", font_tiny, C("GRAY"),
                      card.x + 14, card.y + 36, max_width=card.w - 28)
            pw_box = pygame.Rect(card.x + 14, card.y + 58, card.w - 28, 36)
            draw_rounded_rect(surface, pw_box, C("PANEL_BG"), radius=8, border_color=C("INK") if state.settings_active_field == "delete_pw" else C("BORDER"), border_width=1)
            draw_text(surface, "*" * len(state.settings_delete_pw) if state.settings_delete_pw else "Type your password...", font_body,
                      C("INK") if state.settings_delete_pw else C("LIGHT_GRAY"), pw_box.x + 10, pw_box.y + 8)
            settings_click_rects["delete_pw"] = pw_box
            bw = (card.w - 38) // 2
            cancel = pygame.Rect(card.x + 14, card.y + 104, bw, 36)
            confirm = pygame.Rect(cancel.right + 10, card.y + 104, bw, 36)
            draw_button(surface, cancel, "Keep it", C("PANEL_BG"), C("INK"), font=font_small_bold, radius=10)
            draw_button(surface, confirm, "Delete forever", C("RED"), (255, 255, 255), font=font_small_bold, radius=10)
            settings_click_rects["delete_cancel"] = cancel
            settings_click_rects["delete_confirm"] = confirm
            y += 164

    draw_text(surface, "About", font_small_bold, C("GRAY"), 20, y)
    y += 22
    about = pygame.Rect(20, y, WIDTH - 40, 88)
    draw_rounded_rect(surface, about, C("CARD"), radius=10, border_color=C("BORDER"), border_width=1)
    draw_text(surface, f"Ledger version {VERSION}", font_small_bold, C("INK"), about.x + 14, about.y + 12)
    if update_info["latest"]:
        upd = pygame.Rect(about.right - 130, about.y + 8, 116, 30)
        draw_button(surface, upd, f"Get v{update_info['latest']}", C("PURPLE"), (255, 255, 255), font=font_tiny, radius=8)
        settings_click_rects["update"] = upd
    else:
        draw_text(surface, "Up to date" if UPDATE_URL else "", font_tiny, C("GRAY"), about.right - 14, about.y + 14, align="right")
    n_err = error_report_count()
    draw_text(surface, f"Problem reports saved: {n_err}", font_small, C("GRAY"), about.x + 14, about.y + 50)
    if n_err:
        show = pygame.Rect(about.right - 90, about.y + 44, 76, 30)
        draw_button(surface, show, "Show file", C("PANEL_BG"), C("INK"), font=font_tiny, radius=8)
        settings_click_rects["errors"] = show
    y += 104
    clamp_scroll("settings", (y - (CONTENT_TOP - off)) + off)
    surface.set_clip(prev_clip)


def handle_settings_extra_click(pos):
    """New settings buttons. Returns True when a click was used."""
    if not (CONTENT_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    hit = next((k for k, r in settings_click_rects.items() if r.collidepoint(pos)), None)
    if hit == "colorblind":
        state.colorblind = not state.colorblind
        apply_color_mode()
    elif hit == "reduced_motion":
        state.reduced_motion = not state.reduced_motion
    elif hit == "export":
        export_my_data()
        return True
    elif hit == "delete":
        state.settings_confirm_delete = True
        state.settings_delete_pw = ""
        state.settings_active_field = "delete_pw"
    elif hit == "delete_pw":
        state.settings_active_field = "delete_pw"
        return True
    elif hit == "delete_cancel":
        state.settings_confirm_delete = False
        state.settings_delete_pw = ""
        state.settings_active_field = None
    elif hit == "delete_confirm":
        if delete_current_account(state.settings_delete_pw):
            play_sound("click")
        return True
    elif hit == "update":
        open_update_download()
    elif hit == "errors":
        reveal_error_log()
    else:
        return False
    play_sound("click")
    save_game()
    return True


def try_save_settings():
    if not state.logged_in:
        show_toast("Guest mode", "Create an account to save settings.", "warning")
        return

    # Verify the current password against the in-memory credential. The real password is
    # never written to disk; only its SHA-256 hash is stored in ledger_accounts.json.
    if state.password and state.settings_old_pw != state.password:
        show_toast("Incorrect password", "Type your current password to make changes.", "warning")
        play_sound("error")
        return
    if not state.password and state.settings_old_pw:
        show_toast("No password yet", "Leave current password blank, or set a new one.", "warning")
        play_sound("error")
        return

    new_username = state.settings_new_user.strip()
    new_password = state.settings_new_pw.strip()
    old_key = _normalize_account_key(state.account_username)
    new_key = _normalize_account_key(new_username) if new_username else old_key

    if new_username and new_username != state.account_username:
        problem = ledger_safety.username_problem(new_username)
        if problem:
            show_toast("Can't use that username", problem, "warning")
            play_sound("error")
            return
    if new_password and len(new_password) < 4:
        show_toast("Password too short", "Use at least 4 characters.", "warning")
        play_sound("error")
        return

    if new_key != old_key:
        accounts = _migrate_old_save_if_needed(_read_accounts())
        if new_key in accounts["accounts"]:
            show_toast("Username taken", "Choose a different username.", "warning")
            play_sound("error")
            return
        record = accounts["accounts"].pop(old_key, None)
        if record is None:
            record = {"username": state.account_username, "password_hash": _hash_for_current_password() if state.password else ""}
        state.account_username = new_username
        state.player_name = new_username
        record["username"] = new_username
        accounts["accounts"][new_key] = record
        _social_rename(accounts, old_key, new_key)
        _write_accounts(accounts)

    changed = []
    if new_username and new_username != state.player_name:
        state.player_name = new_username
        changed.append("username")
    elif new_username and new_key != old_key:
        changed.append("username")

    if new_password:
        state.password = new_password
        changed.append("password")

    if not changed:
        show_toast("Nothing to save", "Enter a new username or password.", "warning")
        return

    state.settings_old_pw = ""
    state.settings_new_user = ""
    state.settings_new_pw = ""
    show_toast("Settings saved", "Updated " + " and ".join(changed) + ".", "achievement")
    play_sound("achievement")
    spawn_sparks(WIDTH // 2, 420, C("GOLD"), 20)
    save_game()


TABS = [
    ("home", "Home", "HOME"),
    ("market", "Market", "MKT"),
    ("academy", "Learn", "LEARN"),
    ("portfolio", "Portfolio", "PORT"),
]

# Ledger uses a simple five-destination navigation model. The fifth destination
# is a large hamburger button that opens the less-frequently-used sections.
MENU_ITEMS = [
    ("arena", "Arena", "DUEL"),
    ("news", "News", "NEWS"),
    ("leaderboard", "Rank & Friends", "RANK"),
    ("rewards", "Rewards", "GIFT"),
    ("inventory", "Inventory", "BAG"),
    ("avatar", "Avatar", "YOU"),
    ("challenges", "Challenges", "GOAL"),
    ("analytics", "Analytics", "DATA"),
    ("journal", "Trade Journal", "LOG"),
    ("settings", "Settings", "SET"),
    ("parents", "Parent View", "PAR"),
]

tab_button_rects = []
menu_button_rects = []
menu_open = False
MENU_WIDTH = 300
MENU_ANIM_SPEED = 18.0
menu_x = float(WIDTH)

last_ui_error = ""
last_ui_error_until = 0.0

def ui_error_guard(where, exc):
    global last_ui_error, last_ui_error_until, menu_open, modal_stock, detail_modal_stock
    last_ui_error = f"{where}: {type(exc).__name__}"
    last_ui_error_until = time.time() + 4.0
    try:
        with open(os.path.join(_DATA_DIR, "ledger_ui_errors.log"), "a", encoding="utf-8") as f:
            f.write("\n" + time.strftime("%Y-%m-%d %H:%M:%S") + " | " + where + " | " + repr(exc) + "\n")
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass
    menu_open = False
    modal_stock = None
    detail_modal_stock = None
    # Preserve onboarding/account screens. A button exception must never
    # throw the player out of account creation or the tutorial.
    # Keep the selected destination when possible. Navigation recovery is
    # handled by safe_draw_tab(), so an exception never silently changes the
    # player's destination.
    try:
        show_toast("UI recovered", "That button did not complete, but Ledger stayed open.", "warning")
        play_sound("error")
    except Exception:
        pass

def safe_button_action(where, fn):
    try:
        return fn()
    except Exception as exc:
        ui_error_guard(where, exc)
        return False


def draw_tab_icon(surface, key, cx, cy, color):
    """Line icons for the main destinations, drawn in one consistent style."""
    if key == "home":
        pygame.draw.lines(surface, color, False, [(cx - 9, cy - 1), (cx, cy - 9), (cx + 9, cy - 1)], 2)
        pygame.draw.rect(surface, color, (cx - 7, cy - 3, 14, 12), 2, border_radius=2)
        pygame.draw.rect(surface, color, (cx - 2, cy + 3, 4, 6))
    elif key == "market":
        pts = [(cx - 9, cy + 6), (cx - 4, cy + 1), (cx, cy + 4), (cx + 8, cy - 5)]
        pygame.draw.lines(surface, color, False, pts, 2)
        pygame.draw.polygon(surface, color, [(cx + 9, cy - 8), (cx + 9, cy - 2), (cx + 3, cy - 8)])
        pygame.draw.line(surface, color, (cx - 10, cy + 9), (cx + 10, cy + 9), 2)
    elif key == "academy":
        pygame.draw.polygon(surface, color, [(cx - 11, cy - 3), (cx, cy - 8), (cx + 11, cy - 3), (cx, cy + 2)])
        pygame.draw.lines(surface, color, False, [(cx - 6, cy), (cx - 6, cy + 6), (cx, cy + 9), (cx + 6, cy + 6), (cx + 6, cy)], 2)
        pygame.draw.line(surface, color, (cx + 9, cy - 2), (cx + 9, cy + 6), 2)
    elif key == "portfolio":
        pygame.draw.circle(surface, color, (cx, cy), 9, 2)
        pygame.draw.polygon(surface, color, [(cx, cy), (cx, cy - 9), (cx + 6.4, cy - 6.4), (cx + 9, cy)])
    elif key == "news":
        pygame.draw.rect(surface, color, (cx - 9, cy - 8, 18, 16), 2, border_radius=3)
        pygame.draw.rect(surface, color, (cx - 5, cy - 4, 5, 4))
        for ly in (cy - 4, cy):
            pygame.draw.line(surface, color, (cx + 2, ly), (cx + 5, ly), 2)
        pygame.draw.line(surface, color, (cx - 5, cy + 4), (cx + 5, cy + 4), 2)
    elif key == "__menu__":
        for dy in (-6, 0, 6):
            pygame.draw.line(surface, color, (cx - 9, cy + dy), (cx + 9, cy + dy), 2)


def draw_tab_bar(surface):
    """Large, easy-to-press five-button navigation bar with a sliding highlight."""
    global tab_button_rects, menu_open
    tab_button_rects = []
    y0 = HEIGHT - TAB_BAR_HEIGHT
    night = is_full_tab()
    bar_bg, bar_line = (SG_BG, SG_LINE) if night else (C("CARD"), C("BORDER"))
    on_col, off_col = SG_TEXT, (170, 170, 178)
    pygame.draw.rect(surface, bar_bg, (0, y0, WIDTH, TAB_BAR_HEIGHT))
    pygame.draw.line(surface, bar_line, (0, y0), (WIDTH, y0), 1)

    # Four main destinations + one hamburger menu.
    items = TABS + [("__menu__", "More", "MENU")]
    col_w = WIDTH / 5
    counts = notification_counts()
    active_index = next((i for i, (key, _, _) in enumerate(items)
                         if (key == "__menu__" and menu_open) or (key == state.tab and not menu_open)), None)
    for i, (key, label, icon) in enumerate(items):
        x = i * col_w
        rect = pygame.Rect(int(x), int(y0), int(col_w + 1), TAB_BAR_HEIGHT)
        active = i == active_index
        color = on_col if active else off_col
        cx = int(x + col_w / 2)
        draw_tab_icon(surface, key, cx, y0 + 21, color)
        label_s = font_tiny.render(label, True, color)
        surface.blit(label_s, label_s.get_rect(center=(cx, y0 + 44)))
        badge = counts.get(key, 0) if key != "__menu__" else counts["news"] + counts["leaderboard"] + counts["rewards"]
        if badge and not (key == "__menu__" and menu_open):
            pygame.draw.circle(surface, SG_GREEN, (cx + 12, y0 + 12), 4)   # quiet dot, no number
        tab_button_rects.append((rect, key))



def draw_menu_icon(surface, key, box):
    """Hand-drawn vector glyphs for the drawer, themed around trading."""
    fg = C("PURPLE")
    acc = C("GOLD")
    cx, cy = box.center
    w = 2
    if key == "arena":  # crossed swords
        for sx in (-1, 1):
            pygame.draw.line(surface, fg, (cx - sx * 8, cy - 8), (cx + sx * 6, cy + 6), w + 1)
            pygame.draw.line(surface, acc, (cx + sx * 3, cy + 3), (cx + sx * 8, cy - 2), w)
            pygame.draw.circle(surface, acc, (cx + sx * 8, cy + 8), 2)
    elif key == "news":  # newspaper
        page = pygame.Rect(cx - 9, cy - 8, 18, 16)
        pygame.draw.rect(surface, fg, page, w, border_radius=3)
        pygame.draw.rect(surface, acc, (cx - 6, cy - 5, 6, 5), border_radius=1)
        for i, ly in enumerate((cy - 5, cy - 1)):
            pygame.draw.line(surface, fg, (cx + 1, ly), (cx + 6, ly), 1)
        pygame.draw.line(surface, fg, (cx - 6, cy + 3), (cx + 6, cy + 3), 1)
    elif key == "leaderboard":  # podium with star
        for dx, top in ((-9, cy), (-3, cy - 6), (3, cy + 3)):
            pygame.draw.rect(surface, fg, (cx + dx, top + 1, 5, cy + 9 - top), border_radius=1)
        pygame.draw.circle(surface, acc, (cx, cy - 10), 3)
    elif key == "avatar":  # head and shoulders
        pygame.draw.circle(surface, fg, (cx, cy - 4), 5)
        pygame.draw.ellipse(surface, fg, (cx - 9, cy + 3, 18, 12))
        pygame.draw.circle(surface, acc, (cx + 7, cy - 8), 2)
    elif key == "challenges":  # target with arrow
        pygame.draw.circle(surface, fg, (cx, cy), 9, w)
        pygame.draw.circle(surface, fg, (cx, cy), 5, w)
        pygame.draw.circle(surface, acc, (cx, cy), 2)
        pygame.draw.line(surface, acc, (cx, cy), (cx + 8, cy - 8), w)
    elif key == "analytics":  # candlesticks
        for dx, top, bot, up in ((-7, cy - 2, cy + 6, False), (-1, cy - 8, cy + 1, True), (5, cy - 5, cy + 4, True)):
            col = acc if up else fg
            pygame.draw.line(surface, col, (cx + dx, top - 3), (cx + dx, bot + 3), 1)
            pygame.draw.rect(surface, col, (cx + dx - 2, top, 5, bot - top), border_radius=1)
    elif key == "journal":  # ledger book
        book = pygame.Rect(cx - 8, cy - 9, 16, 18)
        pygame.draw.rect(surface, fg, book, w, border_radius=3)
        pygame.draw.line(surface, fg, (cx - 4, cy - 9), (cx - 4, cy + 9), w)
        for ly in (cy - 4, cy, cy + 4):
            pygame.draw.line(surface, acc, (cx - 1, ly), (cx + 5, ly), 1)
    elif key == "parents":  # shield with heart
        pts = [(cx - 9, cy - 8), (cx, cy - 11), (cx + 9, cy - 8), (cx + 8, cy + 3), (cx, cy + 11), (cx - 8, cy + 3)]
        pygame.draw.polygon(surface, fg, pts, w)
        pygame.draw.circle(surface, acc, (cx - 2, cy - 2), 3)
        pygame.draw.circle(surface, acc, (cx + 2, cy - 2), 3)
        pygame.draw.polygon(surface, acc, [(cx - 5, cy - 1), (cx + 5, cy - 1), (cx, cy + 5)])
    elif key == "inventory":  # backpack
        pygame.draw.rect(surface, fg, (cx - 8, cy - 5, 16, 14), border_radius=4)
        pygame.draw.arc(surface, fg, (cx - 5, cy - 11, 10, 10), 0, math.pi, 2)
        pygame.draw.rect(surface, acc, (cx - 5, cy + 1, 10, 5), border_radius=2)
    elif key == "rewards":  # gift box
        pygame.draw.rect(surface, fg, (cx - 9, cy - 3, 18, 12), border_radius=2)
        pygame.draw.rect(surface, fg, (cx - 10, cy - 7, 20, 5), border_radius=2)
        pygame.draw.rect(surface, acc, (cx - 2, cy - 7, 4, 16))
        pygame.draw.circle(surface, acc, (cx - 4, cy - 9), 3, 2)
        pygame.draw.circle(surface, acc, (cx + 4, cy - 9), 3, 2)
    elif key == "settings":  # gear
        for i in range(8):
            a = i * math.pi / 4
            pygame.draw.line(surface, fg, (cx + math.cos(a) * 6, cy + math.sin(a) * 6),
                             (cx + math.cos(a) * 10, cy + math.sin(a) * 10), 3)
        pygame.draw.circle(surface, fg, (cx, cy), 7)
        pygame.draw.circle(surface, C("PURPLE_BG"), (cx, cy), 3)
    else:
        draw_text(surface, key[:3].upper(), font_tiny, fg, cx, cy - 6, align="center")


def draw_menu_drawer(surface):
    """Draw the hamburger drawer over the app with large touch-friendly rows."""
    global menu_button_rects, menu_x
    target = WIDTH - MENU_WIDTH if menu_open else WIDTH
    menu_x += (target - menu_x) * min(1.0, MENU_ANIM_SPEED / 60.0)
    if abs(target - menu_x) < 1:
        menu_x = target
    if menu_x >= WIDTH - 1:
        menu_button_rects = []
        return

    # Dim the rest of the app so the drawer has clear focus.
    overlay = HiSurface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 85))
    surface.blit(overlay, (0, 0))

    panel = pygame.Rect(int(menu_x), 0, MENU_WIDTH, HEIGHT)
    draw_rounded_rect(surface, panel, C("CARD"), radius=0, shadow=True)
    pygame.draw.line(surface, C("BORDER"), (panel.x, 0), (panel.x, HEIGHT), 1)

    # Header
    draw_text(surface, "Ledger", font_large, C("INK"), panel.x + 24, 24)
    draw_text(surface, "Everything in one place", font_small, C("GRAY"), panel.x + 24, 61)
    close_rect = pygame.Rect(panel.right - 58, 18, 40, 40)
    draw_rounded_rect(surface, close_rect, C("PANEL_BG"), radius=12, border_color=C("BORDER"), border_width=1)
    draw_text(surface, "×", font_body_bold, C("INK"), close_rect.centerx, close_rect.y + 8, align="center")
    tour_rect = pygame.Rect(close_rect.x - 70, 24, 62, 28)
    draw_rounded_rect(surface, tour_rect, C("PURPLE_BG"), radius=14, border_color=C("PURPLE"), border_width=1, shadow=False)
    draw_text(surface, "Tour", font_small_bold, C("PURPLE"), tour_rect.centerx, tour_rect.y + 5, align="center")

    # Section labels keep the drawer organized without making the main nav busy.
    sections = [
        ("COMPETE", MENU_ITEMS[:3]),
        ("PERSONAL", MENU_ITEMS[3:7]),
        ("TOOLS", MENU_ITEMS[7:]),
    ]
    y = 96
    drawer_counts = notification_counts()
    menu_button_rects = [(close_rect, "__close__"), (tour_rect, "__tour__")]
    for section, items in sections:
        draw_text(surface, section, font_tiny, C("GRAY"), panel.x + 24, y)
        y += 22
        for key, label, icon in items:
            rect = pygame.Rect(panel.x + 14, y, panel.w - 28, 44)
            hovered = rect.collidepoint(pygame.mouse.get_pos())
            draw_rounded_rect(surface, rect, C("PANEL_BG") if hovered else C("CARD"), radius=12,
                              border_color=C("BORDER") if hovered else None, border_width=1)
            icon_box = pygame.Rect(rect.x + 8, rect.y + 5, 34, 34)
            draw_rounded_rect(surface, icon_box, C("PURPLE_BG"), radius=10)
            draw_menu_icon(surface, key, icon_box)
            draw_text(surface, label, font_body_bold, C("INK"), rect.x + 54, rect.y + 11)
            draw_count_badge(surface, rect.right - 24, rect.centery, drawer_counts.get(key, 0))
            menu_button_rects.append((rect, key))
            y += 48
        y += 8

    # Bottom profile/status card.



# ----------------------------
# NEWS NOTIFICATIONS + UNREAD BADGES
# ----------------------------

toast_rect = None


def news_item_id(item):
    return f"{item.get('ticker', '')}|{item.get('headline', '')}"


def stamp_news(item, price_at=None):
    """Remember when a story arrived and the stock price at that moment."""
    item.setdefault("arrived", time.time())
    asset = find_asset(item.get("ticker", "")) if item.get("ticker") else None
    if asset and "price_at" not in item:
        item["price_at"] = float(price_at if price_at is not None else asset["price"])


def notify_news(item, price_at=None):
    """Tappable 'breaking news' notification that opens the story in News."""
    stamp_news(item, price_at)
    ticker = item.get("ticker", "")
    label = item.get("event") or ("Price alert" if item.get("volatility_event") else "Breaking news")
    title = f"{label}  •  {ticker}" if find_asset(ticker) else label
    watched = get_alert(ticker) if find_asset(ticker) else None
    if watched and "news" in watched["rules"]:
        title = f"Your alert  •  {ticker} news"
    show_toast(title, item.get("headline", ""), "news", action=("news", news_item_id(item)), direction=item.get("direction"))
    play_sound("bell")


def news_unread_count():
    seen = getattr(state, "news_seen_at", 0.0)
    return sum(1 for it in state.news_feed if it.get("arrived", 0) > seen)


def open_news_item(item_id):
    global menu_open
    close_modal()
    close_detail_modal()
    menu_open = False
    state.market_search = ""
    state.market_search_active = False
    state.tab = "news"
    state.news_highlight = (item_id, time.time() + 3.0)
    state.news_scroll_to = item_id
    play_sound("click")


def notification_counts():
    counts = {"news": news_unread_count(), "leaderboard": 0, "academy": 0, "rewards": rewards_badge_count(), "inventory": inventory_badge_count()}
    if getattr(state, "logged_in", False):
        counts["leaderboard"] = len(social_snapshot()["incoming"])
    c = current_challenge()
    if state.challenge_progress >= c["goal"] and not state.challenge_claimed:
        counts["academy"] = 1
    return counts


def draw_count_badge(surface, cx, cy, n):
    """Small green dot: something new here. No red numbers competing for attention."""
    if n <= 0:
        return
    pygame.draw.circle(surface, C("CARD"), (int(cx) - 4, int(cy) + 2), 6)
    pygame.draw.circle(surface, SG_GREEN, (int(cx) - 4, int(cy) + 2), 4)


def time_ago(t):
    secs = max(0, int(time.time() - t))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


TOAST_SECONDS = 3.4


def show_toast(title, subtitle, tone="neutral", action=None, direction=None):
    now = time.time()
    state.toast = {"title": title, "subtitle": subtitle, "tone": tone, "start": now,
                   "expire": now + (TOAST_SECONDS + 1.6 if action else TOAST_SECONDS), "action": action, "direction": direction}


def _draw_toast_icon(surface, tone, cx, cy, fg):
    if tone == "achievement":  # trophy
        pygame.draw.polygon(surface, fg, [(cx - 9, cy - 9), (cx + 9, cy - 9), (cx + 7, cy + 1), (cx, cy + 4), (cx - 7, cy + 1)])
        pygame.draw.arc(surface, fg, (cx - 14, cy - 8, 9, 9), math.pi / 2, 3 * math.pi / 2, 2)
        pygame.draw.arc(surface, fg, (cx + 5, cy - 8, 9, 9), -math.pi / 2, math.pi / 2, 2)
        pygame.draw.rect(surface, fg, (cx - 2, cy + 3, 4, 5))
        pygame.draw.rect(surface, fg, (cx - 7, cy + 8, 14, 3), border_radius=1)
    elif tone == "dividend":  # coin
        pygame.draw.circle(surface, fg, (cx, cy), 10, 2)
        draw_text(surface, "$", font_small_bold, fg, cx, cy - 9, align="center")
    elif tone == "warning":
        pygame.draw.polygon(surface, fg, [(cx, cy - 10), (cx + 11, cy + 9), (cx - 11, cy + 9)], 2)
        pygame.draw.line(surface, fg, (cx, cy - 3), (cx, cy + 3), 2)
        pygame.draw.circle(surface, fg, (cx, cy + 6), 1.5)
    elif tone == "duel":  # crossed swords
        pygame.draw.line(surface, fg, (cx - 9, cy - 9), (cx + 8, cy + 8), 3)
        pygame.draw.line(surface, fg, (cx + 9, cy - 9), (cx - 8, cy + 8), 3)
    elif tone == "news":  # newspaper
        pygame.draw.rect(surface, fg, (cx - 10, cy - 8, 20, 16), 2, border_radius=3)
        pygame.draw.rect(surface, fg, (cx - 6, cy - 4, 6, 5))
        pygame.draw.line(surface, fg, (cx + 2, cy - 4), (cx + 6, cy - 4), 2)
        pygame.draw.line(surface, fg, (cx + 2, cy), (cx + 6, cy), 2)
        pygame.draw.line(surface, fg, (cx - 6, cy + 4), (cx + 6, cy + 4), 2)
    elif tone == "buy":
        pygame.draw.line(surface, fg, (cx, cy + 9), (cx, cy - 6), 3)
        pygame.draw.polygon(surface, fg, [(cx - 7, cy - 3), (cx + 7, cy - 3), (cx, cy - 11)])
    elif tone == "sell":
        pygame.draw.line(surface, fg, (cx, cy - 9), (cx, cy + 6), 3)
        pygame.draw.polygon(surface, fg, [(cx - 7, cy + 3), (cx + 7, cy + 3), (cx, cy + 11)])
    else:  # bell (alerts)
        pygame.draw.polygon(surface, fg, [(cx - 8, cy + 5), (cx - 6, cy - 3), (cx, cy - 9), (cx + 6, cy - 3), (cx + 8, cy + 5)])
        pygame.draw.circle(surface, fg, (cx, cy + 8), 2.5)


def draw_toast(surface):
    t = state.toast
    if not t:
        return
    now = time.time()
    if now > t["expire"]:
        state.toast = None
        return
    start = t.get("start", t["expire"] - TOAST_SECONDS)
    age = now - start
    left = t["expire"] - now
    # Spring in from above, slide back up when leaving.
    if age < 0.45:
        p = age / 0.45
        slide = 1 - math.exp(-6 * p) * math.cos(9 * p)
    else:
        slide = 1.0
    if left < 0.3:
        slide = min(slide, ease_out_cubic(left / 0.3))
    tone = t["tone"]
    accents = {"warning": C("RED"), "achievement": C("GOLD"), "dividend": C("GREEN"), "duel": C("PURPLE"),
               "buy": C("GREEN"), "sell": C("ORANGE"), "bell": C("PURPLE")}
    accent = accents.get(tone, C("PURPLE"))
    if tone == "news":
        accent = {"up": C("GREEN"), "down": C("RED")}.get(t.get("direction"), C("PURPLE"))
    special = tone in ("achievement", "duel")
    h = 68
    rect = pygame.Rect(14, int(-h - 10 + (h + 22) * slide), WIDTH - 28, h)
    global toast_rect
    toast_rect = rect if t.get("action") else None
    bg = SG_PANEL if special else C("CARD")
    draw_rounded_rect(surface, rect, bg, radius=18, border_color=accent if special else C("BORDER"), border_width=2 if special else 1)
    if special:
        # A soft shine sweeping across celebratory toasts.
        sweep = (age * 0.9) % 1.6
        if sweep < 1.0:
            shine = HiSurface(rect.size, pygame.SRCALPHA)
            sx = int(-60 + (rect.w + 120) * sweep)
            pygame.draw.polygon(shine, (255, 255, 255, 34), [(sx, 0), (sx + 40, 0), (sx + 10, rect.h), (sx - 30, rect.h)])
            mask = HiSurface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=18)
            shine.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
            surface.blit(shine, rect.topleft)
    icon_c = (rect.x + 36, rect.centery)
    pop = ease_out_cubic((age - 0.1) / 0.3)
    pygame.draw.circle(surface, accent, icon_c, max(2, int(21 * (0.6 + 0.4 * pop))))
    _draw_toast_icon(surface, tone, icon_c[0], icon_c[1], text_on(accent))
    title_col = (255, 215, 0) if tone == "achievement" else ((255, 255, 255) if special else C("INK"))
    sub_col = (205, 200, 225) if special else C("GRAY")
    text_w = rect.w - 84 - (44 if t.get("action") else 0)
    draw_text(surface, t["title"], font_body_bold, title_col, rect.x + 68, rect.y + 14, max_width=text_w)
    draw_text(surface, t["subtitle"], font_small, sub_col, rect.x + 68, rect.y + 36, max_width=text_w)
    if t.get("action"):
        # Chevron says "tap me".
        chev = (rect.right - 30, rect.centery)
        pygame.draw.circle(surface, mix_color(accent, bg, 0.8), chev, 15)
        pygame.draw.lines(surface, accent, False, [(chev[0] - 3, chev[1] - 6), (chev[0] + 3, chev[1]), (chev[0] - 3, chev[1] + 6)], 3)
    # Time-left bar.
    bar_w = int((rect.w - 36) * max(0.0, min(1.0, left / max(0.1, t["expire"] - start))))
    pygame.draw.rect(surface, mix_color(accent, bg, 0.5), (rect.x + 18, rect.bottom - 6, bar_w, 3), border_radius=2)


detail_modal_stock=None
detail_close_btn=None
detail_buy_btn=None
detail_sell_btn=None
detail_watch_btn=None
detail_alert_btn=None
detail_recurring_btn=None
detail_range_btns=[]

def open_detail_modal(stock):
    global detail_modal_stock; detail_modal_stock=stock

def close_detail_modal():
    global detail_modal_stock; detail_modal_stock=None

def draw_detail_modal(surface):
    """Stock details: big chart, why it moved, key numbers, and clear Buy / Sell buttons."""
    global detail_close_btn, detail_buy_btn, detail_sell_btn, detail_watch_btn, detail_alert_btn, detail_recurring_btn, detail_range_btns
    if not detail_modal_stock:
        return
    a = detail_modal_stock
    snap = stock_snapshot(a)
    now = time.time()
    blit_color_overlay(surface, (6, 5, 16), 170)
    sheet = pygame.Rect(0, 28, WIDTH, HEIGHT)
    pygame.draw.rect(surface, SG_PANEL, sheet, border_top_left_radius=28, border_top_right_radius=28)
    pygame.draw.rect(surface, SG_LINE, sheet, 1, border_top_left_radius=28, border_top_right_radius=28)
    pygame.draw.rect(surface, SG_LINE, (sheet.centerx - 22, sheet.y + 9, 44, 4), border_radius=2)
    tmp = {}
    _sg_close(surface, pygame.Rect(WIDTH - 56, sheet.y + 20, 40, 40), tmp)
    detail_close_btn = tmp["close"]
    y = sheet.y + 24
    draw_ticker_badge(surface, a["ticker"], 20, y, 48)
    draw_text(surface, a["name"], font_medium_bold, SG_TEXT, 80, y + 2, max_width=WIDTH - 150)
    draw_text(surface, f"{a['ticker']}  ·  {a['sector']}", font_small, SG_MUTED, 80, y + 26, max_width=WIDTH - 150)
    y += 66
    draw_text(surface, fmt_money(a["price"]), font_sg_title, SG_TEXT, 20, y)
    up = snap["move"] >= 0
    chip_t = f"{'+' if up else ''}{snap['move']:.2f}% today"
    cw = font_small_bold.size(chip_t)[0] + 20
    chip = pygame.Rect(20, y + 44, cw, 26)
    pygame.draw.rect(surface, mix_color(SG_GREEN if up else SG_RED, SG_PANEL, 0.72), chip, border_radius=13)
    draw_text(surface, chip_t, font_small_bold, SG_GREEN if up else SG_RED, chip.centerx, chip.y + 4, align="center")
    detail_range_btns = []
    for i, label in enumerate(["1D", "1W", "1M", "1Y"]):
        br = pygame.Rect(WIDTH - 20 - (4 - i) * 50 + 4, y + 8, 46, 32)
        on = state.chart_range == label
        pygame.draw.rect(surface, SG_GOLD if on else SG_BG, br, border_radius=12)
        draw_text(surface, label, font_small_bold, SG_INK if on else SG_MUTED, br.centerx, br.centery - 9, align="center")
        detail_range_btns.append((br, label))
    y += 84
    chart = pygame.Rect(20, y, WIDTH - 40, 136)
    pygame.draw.rect(surface, SG_BG, chart, border_radius=18)
    n = {"1D": 40, "1W": 80, "1M": 120, "1Y": 160}.get(state.chart_range, 40)
    draw_mini_chart(surface, a.get("history", [a["price"]])[-n:], up, chart.x + 14, chart.y + 22, chart.w - 28, chart.h - 40,
                    color=SG_GREEN if up else SG_RED, anim_key=("detail", a["ticker"], n), **smooth_chart_args())
    y = chart.bottom + 14

    # Why it moved (plus the Insight trend while that boost is on).
    head, lesson = why_it_moved(a)
    head_lines = sg_wrap(head, font_small_bold, WIDTH - 80, 2)
    lesson_lines = sg_wrap(lesson, font_tiny, WIDTH - 80, 2) if lesson else []
    ins = boost_active("insight")
    card = pygame.Rect(20, y, WIDTH - 40, 40 + len(head_lines) * 19 + len(lesson_lines) * 16 + (28 if ins else 0) + 8)
    sg_panel(surface, card, 18)
    pygame.draw.rect(surface, SG_PURPLE, (card.x, card.y + 12, 4, card.h - 24), border_radius=2)
    draw_text(surface, "Why it moved", font_small_bold, SG_PURPLE, card.x + 18, card.y + 12)
    ty = card.y + 34
    for line in head_lines:
        draw_text(surface, line, font_small_bold, SG_TEXT, card.x + 18, ty)
        ty += 19
    for line in lesson_lines:
        draw_text(surface, line, font_tiny, SG_MUTED, card.x + 18, ty)
        ty += 16
    if ins:
        label, sup, mv = insight_signal(a)
        col = SG_GREEN if sup else (SG_RED if sup is False else SG_MUTED)
        draw_trend_arrow(surface, card.x + 24, ty + 13, sup, col, 0.8)
        draw_text(surface, f"Insight: {label.lower()} ({'+' if mv >= 0 else ''}{mv:.2f}% lately)", font_small_bold, col, card.x + 36, ty + 4,
                  max_width=card.w - 54)
    y = card.bottom + 12

    # Key numbers.
    owned = state.holdings.get(a["ticker"], 0)
    tiles = [("Recent high", fmt_money(snap["high"])), ("Recent low", fmt_money(snap["low"])),
             ("P/E ratio", f"{snap['pe']:.1f}"), ("You own", f"{owned:g} share{'s' if owned != 1 else ''}" if owned else "None yet")]
    tw = (WIDTH - 40 - 10) // 2
    for i, (lab, val) in enumerate(tiles):
        t = pygame.Rect(20 + (i % 2) * (tw + 10), y + (i // 2) * 60, tw, 52)
        pygame.draw.rect(surface, SG_BG, t, border_radius=14)
        draw_text(surface, lab, font_tiny, SG_MUTED, t.x + 14, t.y + 9)
        draw_text(surface, val, font_body_bold, SG_TEXT, t.x + 14, t.y + 25, max_width=t.w - 24)
    y += 124

    # Actions: Buy / Sell big, Watch / Alerts small.
    bw = (WIDTH - 40 - 12) // 2
    detail_buy_btn = pygame.Rect(20, y, bw, 58)
    detail_sell_btn = pygame.Rect(20 + bw + 12, y, bw, 58)
    tmp = {}
    _sg_button(surface, detail_buy_btn, "buy", "Buy", SG_GREEN, SG_INK, btns=tmp)
    _sg_button(surface, detail_sell_btn, "sell", "Sell", SG_RED if owned else SG_PANEL_2, SG_INK if owned else SG_MUTED, btns=tmp)
    y += 72
    watched = a["ticker"] in state.watchlist
    detail_watch_btn = pygame.Rect(20, y, bw, 44)
    detail_alert_btn = pygame.Rect(20 + bw + 12, y, bw, 44)
    detail_recurring_btn = None
    for rect, label, col in ((detail_watch_btn, "Watching" if watched else "Watch", SG_GOLD if watched else SG_TEXT),
                             (detail_alert_btn, "Alerts & auto-invest", SG_PURPLE)):
        hov = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, SG_PANEL_2 if hov else SG_BG, rect, border_radius=14)
        pygame.draw.rect(surface, SG_LINE, rect, 1, border_radius=14)
        draw_text(surface, label, font_small_bold, col, rect.centerx + (8 if rect is detail_watch_btn else 0), rect.centery - 9,
                  align="center", max_width=rect.w - 20)
    draw_star_shape(surface, detail_watch_btn.centerx - font_small_bold.size("Watching" if watched else "Watch")[0] // 2 - 6,
                    detail_watch_btn.centery, 7, SG_GOLD, outline=not watched)

modal_reason = None


def sell_qty(q, owned):
    """A sell amount that never exceeds what you own. Rounds down (never up) to 4 decimals,
    and "all" stays exactly the amount owned, even for tiny fractional holdings."""
    if owned <= 0:
        return 0.0
    if q >= owned - 1e-9:
        return owned
    return max(min(0.01, owned), math.floor(q * 10000) / 10000)


def open_modal(stock, mode):
    global modal_stock, modal_mode, modal_qty, qty_input_text, modal_reason
    modal_stock = stock
    modal_mode = mode
    modal_qty = 1
    modal_reason = None
    trade_ui["opened"] = time.time()
    price = float(stock.get("price", 0) or 0)
    if mode == "buy" and price > state.cash >= 0.01 * price:
        # One whole share costs more than you have: start with the fraction you can afford.
        modal_qty = max(0.01, math.floor(state.cash / price * 100) / 100)
    elif mode == "sell":
        modal_qty = sell_qty(1.0, state.holdings.get(stock["ticker"], 0))
    qty_input_text = f"{modal_qty:g}"


def close_modal():
    global modal_stock
    modal_stock = None


trade_ui = {"btns": {}, "opened": 0.0}


def _trade_limits():
    owned = state.holdings.get(modal_stock["ticker"], 0)
    price = modal_stock["price"]
    max_buy = math.floor(state.cash / price * 100) / 100 if price > 0 else 0
    return owned, max_buy


def _trade_can_confirm():
    owned, max_buy = _trade_limits()
    total = modal_stock["price"] * modal_qty
    if modal_qty <= 0 or (modal_qty < 0.01 and modal_mode == "buy"):
        return False, "Pick how many shares"
    if modal_mode == "buy":
        return (total <= state.cash + 0.005), "Not enough cash for that many"
    return (modal_qty <= owned + 1e-9), "You don't own that many shares"


def _shares_label(q):
    return f"{q:g} share" + ("" if abs(q - 1) < 1e-9 else "s")


def draw_modal(surface):
    """Buy / sell sheet: one decision per row, big targets, a plain-English confirm button."""
    if not modal_stock:
        return
    b = trade_ui["btns"] = {}
    now = time.time()
    blit_color_overlay(surface, (6, 5, 16), 170)
    appear = ease_out_cubic((now - trade_ui["opened"]) / 0.3)
    buy = modal_mode == "buy"
    owned, max_buy = _trade_limits()
    price = modal_stock["price"]
    total = price * modal_qty
    sheet_h = 22 + 70 + 66 + 30 + 26 + 86 + 58 + 150 + 16 + (122 if buy else 0) + 60 + 28
    top = max(40, HEIGHT - sheet_h)
    sheet = pygame.Rect(0, int(top + (1 - appear) * 80), WIDTH, HEIGHT - top + 40)
    b["sheet"] = sheet
    pygame.draw.rect(surface, SG_PANEL, sheet, border_top_left_radius=28, border_top_right_radius=28)
    pygame.draw.rect(surface, SG_LINE, sheet, 1, border_top_left_radius=28, border_top_right_radius=28)
    pygame.draw.rect(surface, SG_LINE, (sheet.centerx - 22, sheet.y + 9, 44, 4), border_radius=2)
    _sg_close(surface, pygame.Rect(WIDTH - 56, sheet.y + 18, 40, 40), b)
    y = sheet.y + 22

    # Header.
    draw_ticker_badge(surface, modal_stock["ticker"], 20, y, size=48)
    draw_text(surface, modal_stock["name"], font_medium_bold, SG_TEXT, 80, y + 2, max_width=WIDTH - 150)
    move = day_move_pct(modal_stock)
    mcol = SG_GREEN if move >= 0 else SG_RED
    pr = draw_text(surface, fmt_money(price), font_body_bold, SG_TEXT, 80, y + 26)
    draw_text(surface, f"{'+' if move >= 0 else ''}{move:.2f}% today", font_small_bold, mcol, pr.right + 10, y + 27)
    y += 70

    # Buy / Sell toggle.
    seg = pygame.Rect(20, y, WIDTH - 40, 54)
    pygame.draw.rect(surface, SG_BG, seg, border_radius=18)
    half = (seg.w - 8) // 2
    for i, (mode, label, col) in enumerate((("buy", "Buy", SG_GREEN), ("sell", "Sell", SG_RED))):
        r = pygame.Rect(seg.x + 4 + i * (half), seg.y + 4, half, seg.h - 8)
        on = modal_mode == mode
        disabled = mode == "sell" and owned <= 0
        if on:
            pygame.draw.rect(surface, col, r, border_radius=14)
        draw_text(surface, label, font_medium_bold, SG_INK if on else (SG_LINE if disabled else SG_MUTED), r.centerx, r.centery - 11,
                  align="center")
        b["mode_" + mode] = r
    y += 66
    info = f"You have {fmt_money(state.cash)} to spend" if buy else f"You own {_shares_label(round(owned, 4))}"
    draw_text(surface, info, font_small, SG_MUTED, WIDTH // 2, y, align="center")
    y += 30

    # Share count with big - / + buttons.
    draw_text(surface, "How many shares?", font_small_bold, SG_TEXT, WIDTH // 2, y, align="center")
    y += 26
    for key, cx, sign in (("minus", 56, "-"), ("plus", WIDTH - 56, "+")):
        r = pygame.Rect(cx - 30, y + 4, 60, 60)
        hov = r.collidepoint(pygame.mouse.get_pos())
        pygame.draw.circle(surface, mix_color(SG_PANEL_2, (0, 0, 0), 0.35), (r.centerx, r.centery + 4), 30)
        pygame.draw.circle(surface, SG_LINE if hov else SG_PANEL_2, r.center, 30)
        pygame.draw.line(surface, SG_TEXT, (r.centerx - 10, r.centery), (r.centerx + 10, r.centery), 4)
        if sign == "+":
            pygame.draw.line(surface, SG_TEXT, (r.centerx, r.centery - 10), (r.centerx, r.centery + 10), 4)
        b[key] = r
    qty_font = font_sg_title if len(qty_input_text) < 8 else font_sg_h2
    draw_text(surface, qty_input_text or "0", qty_font, SG_TEXT, WIDTH // 2, y + 8, align="center", max_width=WIDTH - 180)
    draw_text(surface, f"= {fmt_money(total)}", font_body_bold, SG_GOLD, WIDTH // 2, y + 48, align="center")
    y += 86

    # Quick amounts.
    base = max_buy if buy else owned
    quick = [("one", "1 share"), ("q25", "25%"), ("q50", "Half"), ("max", "Max" if buy else "All")]
    qw = (WIDTH - 40 - 3 * 8) // 4
    for i, (key, label) in enumerate(quick):
        r = pygame.Rect(20 + i * (qw + 8), y, qw, 42)
        target = {"one": 1.0, "q25": base * 0.25, "q50": base * 0.5, "max": base}[key]
        on = abs(round(target, 2) - modal_qty) < 0.005 and target >= 0.01
        hov = r.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, mix_color(SG_GOLD, SG_PANEL, 0.75) if on else (SG_PANEL_2 if hov else SG_BG), r, border_radius=14)
        pygame.draw.rect(surface, SG_GOLD if on else SG_LINE, r, 1, border_radius=14)
        draw_text(surface, label, font_small_bold, SG_GOLD if on else SG_TEXT, r.centerx, r.centery - 9, align="center")
        b[key] = r
    y += 58

    # Receipt.
    rc = pygame.Rect(20, y, WIDTH - 40, 150)
    pygame.draw.rect(surface, SG_BG, rc, border_radius=18)
    rows = [("Price per share", fmt_money(price), SG_TEXT), ("Shares", f"{modal_qty:g}", SG_TEXT)]
    if buy:
        rows.append(("You pay", fmt_money(total), SG_GOLD))
        drop = total * 0.10
        risk_pct = drop / max(0.01, net_worth()) * 100
        note = f"If the price drops 10%, you'd be down {fmt_money(drop)} ({risk_pct:.1f}% of everything you have)."
        note_col = SG_RED if risk_pct >= 5 else (SG_AMBER if risk_pct >= 2 else SG_MUTED)
    else:
        avg = state.avg_buy_price.get(modal_stock["ticker"], price)
        est = total - avg * modal_qty
        rows.append(("You get", fmt_money(total), SG_GOLD))
        note = f"{'Profit' if est >= 0 else 'Loss'} on these shares: {'+' if est >= 0 else '-'}{fmt_money(abs(est))} (you paid {fmt_money(avg)} each)"
        note_col = SG_GREEN if est >= 0 else SG_RED
    for i, (label, val, col) in enumerate(rows):
        f = font_body_bold if i == 2 else font_small
        ry = rc.y + (16, 42, 80)[i]
        draw_text(surface, label, f, SG_MUTED if i < 2 else SG_TEXT, rc.x + 18, ry)
        draw_text(surface, val, f, col, rc.right - 18, ry, align="right")
    pygame.draw.line(surface, SG_LINE, (rc.x + 18, rc.y + 70), (rc.right - 18, rc.y + 70), 1)
    for i, line in enumerate(sg_wrap(note, font_tiny, rc.w - 36, 2)):
        draw_text(surface, line, font_tiny, note_col, rc.x + 18, rc.y + 110 + i * 15)
    y += rc.h + 16

    if buy:
        draw_text(surface, "Why are you buying?", font_small_bold, SG_TEXT, 20, y)
        draw_text(surface, "Optional  ·  +5 XP", font_tiny, SG_PURPLE, WIDTH - 20, y + 2, align="right")
        y += 26
        cw = (WIDTH - 40 - 2 * 8) // 3
        for i, (rid, label) in enumerate(TRADE_REASONS):
            r = pygame.Rect(20 + (i % 3) * (cw + 8), y + (i // 3) * 44, cw, 36)
            on = modal_reason == rid
            pygame.draw.rect(surface, SG_PURPLE if on else SG_BG, r, border_radius=18)
            pygame.draw.rect(surface, SG_PURPLE if on else SG_LINE, r, 1, border_radius=18)
            draw_text(surface, label, font_tiny, SG_INK if on else SG_TEXT, r.centerx, r.centery - 8, align="center", max_width=r.w - 12)
            b["reason_" + rid] = r
        y += 96

    ok, why_not = _trade_can_confirm()
    verb = "Buy" if buy else "Sell"
    label = f"{verb} {_shares_label(modal_qty)} for {fmt_money(total)}" if ok else why_not
    col = (SG_GREEN if buy else SG_RED) if ok else SG_PANEL_2
    _sg_button(surface, pygame.Rect(20, y, WIDTH - 40, 60), "confirm", label, col, SG_INK if ok else SG_MUTED, btns=b)



def handle_menu_click(pos):
    global menu_open
    if not menu_open:
        return False
    for rect, key in menu_button_rects:
        if not rect.collidepoint(pos):
            continue
        if key == "__close__":
            menu_open = False
            play_sound("click")
            return True
        if key == "__tour__":
            menu_open = False
            play_sound("click")
            start_tour()
            return True
        if key == "avatar":
            state.avatar_editing = True
            state.avatar_snapshot = dict(state.avatar)
            state.avatar_return_tab = state.tab
            state.name_input = state.player_name
            state.password_input = state.password
            state.avatar_active_field = "name"
            state.auth_message = ""
            state.screen_mode = "avatar"
            menu_open = False
            play_sound("click")
            return True
        # Every drawer item now has its own real destination.
        valid = {"arena", "news", "leaderboard", "challenges", "analytics", "journal", "settings", "rewards", "parents", "inventory", "levels"}
        if key in valid:
            state.tab = key
            state.market_search_active = False
            close_modal()
            close_detail_modal()
            menu_open = False
            play_sound("click")
            return True
    # Clicking outside the drawer closes it. A click inside the drawer that hits
    # nothing is swallowed, so it can never "fall through" to the screen underneath
    # (that's how Parent View used to press Settings' Log out button).
    if pos[0] < menu_x:
        menu_open = False
        play_sound("click")
    return True

def handle_modal_click(pos):
    global modal_mode, modal_reason
    if not modal_stock:
        return
    b = trade_ui["btns"]
    owned, max_buy = _trade_limits()

    def hit(k):
        return k in b and b[k].collidepoint(pos)

    def set_qty(q):
        global modal_qty, qty_input_text
        modal_qty = sell_qty(q, owned) if modal_mode == "sell" else max(0.01, round(q, 2))
        qty_input_text = f"{modal_qty:g}"
        play_sound("click")

    if hit("close") or ("sheet" in b and not b["sheet"].collidepoint(pos)):
        play_sound("click")
        close_modal()
    elif hit("mode_buy"):
        modal_mode = "buy"
        play_sound("click")
    elif hit("mode_sell"):
        if owned > 0:
            modal_mode = "sell"
            set_qty(min(modal_qty, owned))
        else:
            show_toast("Nothing to sell yet", "Buy some shares first, then you can sell them here.", "warning")
            play_sound("error")
    elif hit("minus") or hit("plus"):
        limit = max_buy if modal_mode == "buy" else owned
        step = 1.0 if limit >= 1 else 0.1
        set_qty(modal_qty + (step if hit("plus") else -step))
    elif hit("one"):
        set_qty(1.0)
    elif hit("q25") or hit("q50") or hit("max"):
        base = max_buy if modal_mode == "buy" else owned
        set_qty(base * (0.25 if hit("q25") else 0.5 if hit("q50") else 1.0))
    elif any(hit("reason_" + rid) for rid, _ in TRADE_REASONS) and modal_mode == "buy":
        rid = next(rid for rid, _ in TRADE_REASONS if hit("reason_" + rid))
        modal_reason = None if modal_reason == rid else rid
        play_sound("click")
    elif hit("confirm"):
        ok, why_not = _trade_can_confirm()
        if ok:
            if modal_mode == "buy":
                do_buy(modal_stock, modal_qty, modal_reason)
            else:
                do_sell(modal_stock, modal_qty)
            close_modal()
        else:
            play_sound("error")


def handle_text_event(event, current, limit):
    if event.key == pygame.K_BACKSPACE:
        return current[:-1]
    if event.unicode.isprintable() and len(current) < limit:
        return current + event.unicode
    return current


# ----------------------------
# PARENT CONTROLS & ACCOUNT SAFETY
# ----------------------------
# Everything here stays on this computer. The Parent PIN is scrypt-hashed like passwords.

VERSION = "1.0.0"
# Set to a URL serving {"latest": "1.0.1", "download": "https://..."} to turn on update checks.
UPDATE_URL = ""
TIME_LIMIT_CHOICES = [0, 30, 60, 90, 120]

parental = {}       # this account's parent settings: birth_year, pin_hash, consent_at, daily_limit_min, extra_*
parent_ui = {"mode": "", "pin": "", "first": "", "msg": "", "btns": {}}   # mode: "" | "set" | "confirm"
time_up = {"active": False, "asking": False, "pin": "", "msg": "", "btns": {}, "warned_day": ""}
reset_pw = {"user": "", "pin": "", "pw": "", "pw2": "", "field": "user", "error": "", "btns": {}, "opened": 0.0}
update_info = {"latest": "", "download": ""}
_play_clock = {"last": 0.0}
_ORIGINAL_SG = {}


def _account_key():
    return _normalize_account_key(state.account_username)


def _update_record(fn):
    accounts = _read_accounts()
    rec = accounts.get("accounts", {}).get(_account_key())
    if isinstance(rec, dict):
        fn(rec)
        _write_accounts(accounts)


def load_parental():
    parental.clear()
    if getattr(state, "logged_in", False):
        rec = _read_accounts().get("accounts", {}).get(_account_key())
        if isinstance(rec, dict) and isinstance(rec.get("parental"), dict):
            parental.update(rec["parental"])


def save_parental():
    snapshot = dict(parental)
    _update_record(lambda rec: rec.__setitem__("parental", snapshot))


def parent_pin_set():
    return bool(parental.get("pin_hash"))


def check_parent_pin(pin, pin_hash=None, key=None):
    key = key or _account_key()
    wait = _pin_limiter.seconds_locked(key)
    if wait:
        return False, f"Too many tries. Wait {wait} seconds."
    ok, _ = ledger_safety.verify_secret(pin, parental.get("pin_hash", "") if pin_hash is None else pin_hash)
    if ok:
        _pin_limiter.success(key)
        return True, ""
    _pin_limiter.miss(key)
    return False, "That PIN isn't right."


# ---- Daily time limit ----

def _today():
    return time.strftime("%Y-%m-%d")


def track_play_time(now):
    """Count minutes while a saved account is actually in the game (not in sign-in screens)."""
    last, _play_clock["last"] = _play_clock["last"], now
    if not (state.logged_in and state.screen_mode == "playing") or time_up["active"]:
        return
    if getattr(state, "play_day", "") != _today():
        state.play_day, state.play_seconds_today = _today(), 0.0
    if last:
        state.play_seconds_today += min(1.0, max(0.0, now - last))  # sleep/lag never counts as play
    left = minutes_left_today()
    if left is None:
        return
    if left <= 0:
        time_up.update(active=True, asking=False, pin="", msg="")
        save_game()
    elif left <= 5 and time_up["warned_day"] != _today():
        time_up["warned_day"] = _today()
        show_toast("5 minutes left today", "Your grown-up set a daily time limit.", "warning")


def minutes_left_today():
    limit = int(parental.get("daily_limit_min", 0) or 0)
    if not limit:
        return None
    extra = int(parental.get("extra_min", 0) or 0) if parental.get("extra_day") == _today() else 0
    played = state.play_seconds_today / 60 if getattr(state, "play_day", "") == _today() else 0
    return limit + extra - played


def set_time_limit(minutes):
    parental["daily_limit_min"] = int(minutes)
    save_parental()
    play_sound("click")


# ---- PIN pad (used by Parent View and the time-up screen) ----

def draw_pin_pad(surface, cx, top, entered, btns, colors):
    """Four dots and a 3x4 keypad. colors = (text, key face, key text, accent)."""
    text_col, key_bg, key_fg, accent = colors
    for i in range(4):
        x = cx - 45 + i * 30
        if i < len(entered):
            pygame.draw.circle(surface, accent, (x, top + 8), 8)
        else:
            pygame.draw.circle(surface, text_col, (x, top + 8), 8, 2)
    keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "del"]
    kw, kh, gap = 76, 50, 10
    x0 = cx - (3 * kw + 2 * gap) // 2
    for i, k in enumerate(keys):
        if not k:
            continue
        r = pygame.Rect(x0 + (i % 3) * (kw + gap), top + 32 + (i // 3) * (kh + gap), kw, kh)
        hovered = r.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, mix_color(key_bg, accent, 0.15) if hovered else key_bg, r, border_radius=14)
        draw_text(surface, "Delete" if k == "del" else k, font_small_bold if k == "del" else font_large_med, key_fg,
                  r.centerx, r.centery - (9 if k == "del" else 13), align="center")
        btns["pin_" + k] = r
    return top + 32 + 4 * (kh + gap)


def pin_pad_press(btns, pos, current):
    """Return the new PIN string if a key was hit, else None."""
    for key, rect in btns.items():
        if key.startswith("pin_") and rect.collidepoint(pos):
            k = key[4:]
            play_sound("click")
            return current[:-1] if k == "del" else (current + k)[:4]
    return None


def pin_key_press(event, current):
    if event.key == pygame.K_BACKSPACE:
        return current[:-1]
    if event.unicode.isdigit():
        return (current + event.unicode)[:4]
    return None


# ---- Parent View ----

def _parent_pin_entered(pin):
    """Called when 4 digits are in: unlock, or step through setting a new PIN."""
    ui = parent_ui
    if ui["mode"] == "set":
        ui.update(mode="confirm", first=pin, pin="", msg="Type the same PIN again.")
    elif ui["mode"] == "confirm":
        if pin == ui["first"]:
            parental["pin_hash"] = ledger_safety.hash_secret(pin)
            save_parental()
            state.parent_unlocked = True
            ui.update(mode="", pin="", first="", msg="")
            show_toast("Parent PIN saved", "Parent View, time limits and resets are now protected.", "achievement")
            play_sound("achievement")
        else:
            ui.update(mode="set", pin="", first="", msg="Those didn't match. Start again.")
            play_sound("error")
    else:
        ok, msg = check_parent_pin(pin)
        ui.update(pin="", msg=msg)
        if ok:
            state.parent_unlocked = True
            play_sound("achievement")
        else:
            play_sound("error")


def _parent_needs_pin():
    return parent_ui["mode"] in ("set", "confirm") or (parent_pin_set() and not getattr(state, "parent_unlocked", False))


def draw_parents_tab(surface):
    ui = parent_ui
    ui["btns"] = {}
    if not getattr(state, "logged_in", False):
        prev, y = _draw_section_shell(surface, "Parent View", "Parent tools are for saved accounts.")
        draw_text(surface, "Guest play isn't saved, so there's nothing to manage here.", font_small, C("GRAY"), 20, y,
                  max_width=WIDTH - 40)
        surface.set_clip(prev)
        return

    if _parent_needs_pin():
        setting = ui["mode"] in ("set", "confirm")
        prev, y = _draw_section_shell(surface, "Parent View", "Grown-ups only." if not setting else "Choose a 4-number Parent PIN.")
        title = {"set": "New Parent PIN", "confirm": "Confirm Parent PIN"}.get(ui["mode"], "Enter Parent PIN")
        draw_text(surface, title, font_medium_bold, C("INK"), WIDTH // 2, y, align="center")
        if ui["msg"]:
            draw_text(surface, ui["msg"], font_small_bold, C("RED") if "n't" in ui["msg"] or "Too" in ui["msg"] else C("GRAY"),
                      WIDTH // 2, y + 26, align="center")
        y = draw_pin_pad(surface, WIDTH // 2, y + 56, ui["pin"], ui["btns"], (C("GRAY"), C("PANEL_BG"), C("INK"), C("PURPLE")))
        if setting:
            cancel = pygame.Rect(WIDTH // 2 - 70, y + 6, 140, 38)
            draw_button(surface, cancel, "Cancel", C("CARD"), C("INK"), font=font_small_bold, radius=10)
            ui["btns"]["cancel"] = cancel
        else:
            draw_text(surface, "Forgot the PIN? Delete and re-create the account from Settings.", font_tiny, C("GRAY"),
                      WIDTH // 2, y + 10, align="center", max_width=WIDTH - 40)
        surface.set_clip(prev)
        return

    prev, y = _draw_section_shell(surface, "Parent View", "What your trader has practiced. All money here is pretend.")
    played = int(state.play_seconds_today // 60) if getattr(state, "play_day", "") == _today() else 0
    by = parental.get("birth_year")
    done_q = [q[1] for q in QUESTS if q[0] in state.quests_claimed]
    rows = [
        ("Played today", f"{played} min"),
        ("Lessons finished", str(len(state.academy_completed))),
        ("Learning streak", f"{state.learning_streak} day{'s' if state.learning_streak != 1 else ''}"),
        ("Trader Path", f"{len(done_q)}/{len(QUESTS)} quests"),
        ("Trades made", str(state.trade_count)),
        ("Diversification", f"{diversification_score()}/100"),
        ("Bot battles", f"{state.total_wins} won of {state.total_duels}"),
        ("Pretend portfolio", fmt_money(net_worth())),
    ]
    for label, val in rows:
        r = pygame.Rect(20, y, WIDTH - 40, 40)
        draw_rounded_rect(surface, r, C("CARD"), radius=10, border_color=C("BORDER"), border_width=1)
        draw_text(surface, label, font_small, C("GRAY"), r.x + 14, r.y + 11)
        draw_text(surface, val, font_small_bold, C("INK"), r.right - 14, r.y + 11, align="right")
        y += 46

    # Controls
    y += 10
    draw_text(surface, "Daily time limit", font_body_bold, C("INK"), 20, y)
    left = minutes_left_today()
    draw_text(surface, "No limit" if left is None else f"{max(0, int(left))} min left today", font_small, C("GRAY"),
              WIDTH - 20, y + 2, align="right")
    y += 28
    cw = (WIDTH - 40 - 4 * 8) // 5
    current = int(parental.get("daily_limit_min", 0) or 0)
    for i, mins in enumerate(TIME_LIMIT_CHOICES):
        r = pygame.Rect(20 + i * (cw + 8), y, cw, 38)
        on = mins == current
        draw_button(surface, r, "Off" if not mins else f"{mins}m", C("PURPLE") if on else C("CARD"),
                    (255, 255, 255) if on else C("INK"), font=font_small_bold, radius=10)
        if not on:
            pygame.draw.rect(surface, C("BORDER"), r, 1, border_radius=10)
        ui["btns"][f"limit_{mins}"] = r
    y += 46
    if not parent_pin_set():
        draw_text(surface, "Set a Parent PIN so your trader can't change the limit.", font_tiny, C("ORANGE"), 20, y,
                  max_width=WIDTH - 40)
        y += 20
    y += 6
    half = (WIDTH - 50) // 2
    pin_btn = pygame.Rect(20, y, half, 40)
    draw_button(surface, pin_btn, "Change PIN" if parent_pin_set() else "Set Parent PIN", C("INK"), C("CARD"),
                font=font_small_bold, radius=10)
    ui["btns"]["set_pin"] = pin_btn
    if parent_pin_set():
        lock_btn = pygame.Rect(30 + half, y, half, 40)
        draw_button(surface, lock_btn, "Lock Parent View", C("PANEL_BG"), C("INK"), font=font_small_bold, radius=10)
        ui["btns"]["lock"] = lock_btn
    y += 54

    # Privacy
    draw_text(surface, "Privacy & data", font_body_bold, C("INK"), 20, y)
    y += 26
    facts = [
        f"Age: born {by}." if by else "Age: not asked (account made before age check).",
        "Stored: username, scrambled password, trader look and game progress.",
        "Not stored: email, real name, location. Nothing is sent online.",
        "It all lives only on this computer. Delete it anytime in Settings.",
    ]
    for ftxt in facts:
        for ln in _wrap_words(ftxt, font_small, WIDTH - 60):
            draw_text(surface, ln, font_small, C("GRAY"), 30, y)
            y += 19
        y += 3

    y += 10
    draw_text(surface, "Talk about it together", font_body_bold, C("INK"), 20, y)
    y += 28
    prompts = ["Which stock did you pick, and why?", "What happened the last time a price dropped?",
               "Why is owning different kinds of companies safer?"]
    if state.trade_reviews:
        prompts.insert(0, "Coach said: " + state.trade_reviews[0])
    for ptxt in prompts:
        lines = _wrap_words(ptxt, font_small, WIDTH - 72)
        r = pygame.Rect(20, y, WIDTH - 40, 20 + 18 * len(lines))
        draw_rounded_rect(surface, r, C("PURPLE_BG"), radius=10)
        for i, ln in enumerate(lines):
            draw_text(surface, ln, font_small, C("INK"), r.x + 14, r.y + 10 + i * 18)
        y += r.h + 8
    y += 6
    note = ("No real money, no chat, no ads. Prices are real market quotes." if state.live_mode
            else "No real money, no chat, no ads. Prices are simulated for learning.")
    draw_text(surface, note, font_tiny, C("GRAY"), 20, y, max_width=WIDTH - 40)
    y += 30
    clamp_scroll("parents", y - CONTENT_TOP + scroll_offset.get("parents", 0))
    surface.set_clip(prev)


def handle_parents_click(pos):
    ui = parent_ui
    if not (CONTENT_TOP <= pos[1] <= CONTENT_BOTTOM):
        return False
    if _parent_needs_pin():
        if ui["btns"].get("cancel") and ui["btns"]["cancel"].collidepoint(pos):
            ui.update(mode="", pin="", first="", msg="")
            play_sound("click")
            return True
        new = pin_pad_press(ui["btns"], pos, ui["pin"])
        if new is None:
            return False
        ui["pin"] = new
        if len(new) == 4:
            _parent_pin_entered(new)
        return True
    for key, rect in ui["btns"].items():
        if not rect.collidepoint(pos):
            continue
        if key.startswith("limit_"):
            set_time_limit(int(key.split("_")[1]))
        elif key == "set_pin":
            ui.update(mode="set", pin="", first="", msg="")
            play_sound("click")
        elif key == "lock":
            state.parent_unlocked = False
            play_sound("click")
        return True
    return False


def handle_parents_key(event):
    if not _parent_needs_pin():
        return
    new = pin_key_press(event, parent_ui["pin"])
    if new is not None:
        parent_ui["pin"] = new
        if len(new) == 4:
            _parent_pin_entered(new)


# ---- Time's up ----

def draw_time_up(surface):
    t = time_up
    t["btns"] = {}
    now = time.time()
    _sg_background(surface, now)
    limit = int(parental.get("daily_limit_min", 0) or 0)
    y = 90
    draw_crown(surface, WIDTH // 2, y, SG_GOLD)
    y += 40
    draw_text(surface, "That's it for today!", font_sg_title, SG_TEXT, WIDTH // 2, y, align="center")
    draw_text(surface, f"You've played your {limit} minutes. Great work!", font_body, SG_MUTED, WIDTH // 2, y + 46, align="center")
    draw_text(surface, "Your progress is saved. Come back tomorrow.", font_body, SG_MUTED, WIDTH // 2, y + 70, align="center")
    y += 120
    if t["asking"]:
        draw_text(surface, "Grown-up: enter Parent PIN for 15 more minutes", font_small_bold, SG_TEXT, WIDTH // 2, y, align="center")
        if t["msg"]:
            draw_text(surface, t["msg"], font_small_bold, SG_RED, WIDTH // 2, y + 24, align="center")
        draw_pin_pad(surface, WIDTH // 2, y + 50, t["pin"], t["btns"], (SG_MUTED, SG_PANEL_2, SG_TEXT, SG_GOLD))
    elif parent_pin_set():
        _sg_button(surface, pygame.Rect(40, y, WIDTH - 80, 56), "more", "Grown-up: add 15 minutes", SG_PANEL_2, SG_TEXT,
                   font=font_body_bold, btns=t["btns"])
    _sg_button(surface, pygame.Rect(20, HEIGHT - 92, WIDTH - 40, 60), "logout", "Log out", SG_GOLD, SG_INK, btns=t["btns"])


def _time_up_pin(pin):
    t = time_up
    t["pin"] = pin
    if len(pin) < 4:
        return
    ok, msg = check_parent_pin(pin)
    if ok:
        today = _today()
        parental["extra_min"] = (int(parental.get("extra_min", 0) or 0) if parental.get("extra_day") == today else 0) + 15
        parental["extra_day"] = today
        save_parental()
        t.update(active=False, asking=False, pin="", msg="")
        show_toast("15 more minutes", "Enjoy! A grown-up added extra time.", "achievement")
        play_sound("achievement")
    else:
        t.update(pin="", msg=msg)
        play_sound("error")


def handle_time_up_event(event):
    t = time_up
    if event.type == pygame.KEYDOWN and t["asking"]:
        new = pin_key_press(event, t["pin"])
        if new is not None:
            _time_up_pin(new)
        return
    if event.type != pygame.MOUSEBUTTONDOWN:
        return
    if t["btns"].get("logout") and t["btns"]["logout"].collidepoint(event.pos):
        t.update(active=False, asking=False, pin="", msg="")
        logout_account()
        return
    if t["btns"].get("more") and t["btns"]["more"].collidepoint(event.pos):
        t.update(asking=True, pin="", msg="")
        play_sound("click")
        return
    if t["asking"]:
        new = pin_pad_press(t["btns"], event.pos, t["pin"])
        if new is not None:
            _time_up_pin(new)


# ---- Forgot password (needs the Parent PIN) ----

def open_reset_password():
    reset_pw.update(user=state.login_username_input.strip(), pin="", pw="", pw2="", field="user", error="",
                    btns={}, opened=time.time())
    if reset_pw["user"]:
        reset_pw["field"] = "pin"
    state.screen_mode = "reset_password"


def submit_reset_password():
    r = reset_pw
    key = _normalize_account_key(r["user"])
    accounts = _read_accounts()
    rec = accounts.get("accounts", {}).get(key)
    if not isinstance(rec, dict):
        r["error"] = "No account with that username on this computer."
    elif not (rec.get("parental") or {}).get("pin_hash"):
        r["error"] = "This account has no Parent PIN, so it can't be reset here."
    elif len(r["pw"]) < 4:
        r["error"] = "The new password needs at least 4 characters."
    elif r["pw"] != r["pw2"]:
        r["error"] = "The two new passwords don't match."
    else:
        ok, msg = check_parent_pin(r["pin"], pin_hash=rec["parental"]["pin_hash"], key="reset:" + key)
        if not ok:
            r["error"], r["pin"] = msg, ""
        else:
            rec["password_hash"] = _password_hash(r["pw"])
            _write_accounts(accounts)
            _login_limiter.success(key)
            state.login_username_input = rec.get("username", r["user"])
            state.login_password_input = ""
            state.auth_active_field = "password"
            state.screen_mode = "signin"
            state.auth_message = "Password reset! Log in with the new password."
            play_sound("achievement")
            return
    play_sound("error")


def draw_reset_password(surface):
    r = reset_pw
    r["btns"] = {}
    now = time.time()
    _sg_background(surface, now)
    _sg_close(surface, pygame.Rect(16, 16, 40, 40), r["btns"])
    y = 70
    draw_text(surface, "Reset password", font_sg_title, SG_TEXT, WIDTH // 2, y, align="center")
    draw_text(surface, "A grown-up's Parent PIN is needed.", font_body, SG_MUTED, WIDTH // 2, y + 44, align="center")
    y += 90
    for key, label, hint, masked in (("user", "Username", "Your Ledger username", False),
                                     ("pin", "Parent PIN", "4 numbers", True),
                                     ("pw", "New password", "At least 4 characters", True),
                                     ("pw2", "Confirm new password", "Type it again", True)):
        y = _setup_field(surface, r["btns"], key, label, r[key], hint, masked, y, r["field"] == key, now)
    if r["error"]:
        draw_text(surface, r["error"], font_small_bold, SG_RED, WIDTH // 2, y, align="center", max_width=WIDTH - 40)
    ok = all(r[k] for k in ("user", "pin", "pw", "pw2"))
    _sg_button(surface, pygame.Rect(20, HEIGHT - 92, WIDTH - 40, 60), "reset", "Reset password",
               SG_GOLD if ok else SG_PANEL_2, SG_INK if ok else SG_MUTED, btns=r["btns"])


def handle_reset_password_click(pos):
    r = reset_pw
    for key, rect in r["btns"].items():
        if rect.collidepoint(pos):
            if key == "close":
                state.screen_mode = "signin"
                play_sound("click")
            elif key == "reset":
                submit_reset_password()
            else:
                r["field"] = key.split("_", 1)[1]
                r["error"] = ""
            return


def handle_reset_password_key(event):
    r = reset_pw
    order = ["user", "pin", "pw", "pw2"]
    if event.key == pygame.K_TAB:
        r["field"] = order[(order.index(r["field"]) + 1) % len(order)]
    elif event.key == pygame.K_RETURN:
        if r["field"] != "pw2":
            r["field"] = order[order.index(r["field"]) + 1]
        else:
            submit_reset_password()
    elif event.key == pygame.K_ESCAPE:
        state.screen_mode = "signin"
    else:
        limit = {"user": 14, "pin": 4}.get(r["field"], 25)
        value = handle_text_event(event, r[r["field"]], limit)
        if r["field"] == "pin":
            value = "".join(ch for ch in value if ch.isdigit())
        r[r["field"]] = value
        r["error"] = ""


# ---- Your data: export & delete ----

def export_my_data():
    """Save a readable copy of this account's data (without password or PIN hashes) to Downloads."""
    if not state.logged_in:
        show_toast("Guest mode", "Guests don't have saved data.", "warning")
        return
    save_game()
    rec = _read_accounts().get("accounts", {}).get(_account_key(), {})
    out = json.loads(json.dumps(rec))
    out.pop("password_hash", None)
    out.pop("google_sub", None)
    if isinstance(out.get("parental"), dict):
        out["parental"].pop("pin_hash", None)
    folder = os.path.expanduser("~/Downloads")
    if not os.path.isdir(folder):
        folder = os.path.expanduser("~")
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", state.account_username) or "trader"
    path = os.path.join(folder, f"Ledger-{safe}-data.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"exported_at": time.strftime("%Y-%m-%d %H:%M"), "app_version": VERSION, "account": out}, f, indent=2)
        show_toast("Data saved", f"{os.path.basename(path)} is in your {os.path.basename(folder)} folder.", "achievement")
        play_sound("achievement")
    except OSError:
        show_toast("Couldn't save", "Ledger couldn't write to your Downloads folder.", "warning")
        play_sound("error")


def delete_current_account(password):
    accounts = _read_accounts()
    key = _account_key()
    rec = accounts.get("accounts", {}).get(key)
    if not isinstance(rec, dict):
        return False
    stored = rec.get("password_hash", "")
    if stored and not ledger_safety.verify_secret(password, stored)[0]:
        show_toast("Incorrect password", "Type your password to delete the account.", "warning")
        play_sound("error")
        return False
    accounts["accounts"].pop(key, None)
    for other in accounts["accounts"].values():
        if isinstance(other, dict) and isinstance(other.get("social"), dict):
            for k in ("friends", "incoming", "outgoing", "blocked"):
                other["social"][k] = [x for x in other["social"].get(k, []) if x != key]
    if accounts.get("last_user") and _normalize_account_key(str(accounts["last_user"])) == key:
        accounts.pop("last_user", None)
    _write_accounts(accounts)
    _reset_to_fresh_state()
    parental.clear()
    state.screen_mode = "signin"
    state.auth_message = "Account deleted. Its data was removed from this computer."
    return True


# ---- Settings extras: accessibility, data, about ----

def apply_color_mode():
    """Colorblind-friendly mode swaps green/red for blue/orange (Okabe-Ito colors) everywhere."""
    global SG_GREEN, SG_RED
    if not _ORIGINAL_SG:
        _ORIGINAL_SG.update(green=SG_GREEN, red=SG_RED)
    cb = getattr(state, "colorblind", False)
    SG_GREEN = (86, 180, 233) if cb else _ORIGINAL_SG["green"]
    SG_RED = (230, 159, 0) if cb else _ORIGINAL_SG["red"]


def error_report_count():
    try:
        with open(os.path.join(_DATA_DIR, "ledger_ui_errors.log"), encoding="utf-8") as f:
            return sum(1 for line in f if re.match(r"\d{4}-\d{2}-\d{2} \d", line))
    except OSError:
        return 0


def reveal_error_log():
    path = os.path.join(_DATA_DIR, "ledger_ui_errors.log")
    target = path if os.path.exists(path) else _DATA_DIR
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", target])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(target)])
    except OSError:
        show_toast("Error file", target, "neutral")


def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def _update_check_worker():
    try:
        data = _live_json(UPDATE_URL, timeout=6)
        latest = str(data.get("latest", ""))
        if _version_tuple(latest) > _version_tuple(VERSION):
            update_info.update(latest=latest, download=str(data.get("download", "")))
    except Exception:
        pass


def start_update_check():
    if UPDATE_URL:
        threading.Thread(target=_update_check_worker, daemon=True).start()


def open_update_download():
    if update_info["download"].startswith("https://"):
        import webbrowser
        webbrowser.open(update_info["download"])


# ---- Friends: blocking ----

def block_player(key):
    me = _account_key()

    def apply(accts):
        if me in accts:
            mine = _social_of(accts[me])
            if key not in mine["blocked"]:
                mine["blocked"].append(key)
        for a, b in ((me, key), (key, me)):
            if a in accts:
                soc = _social_of(accts[a])
                for k in ("friends", "incoming", "outgoing"):
                    soc[k] = [x for x in soc[k] if x != b]
    _social_update(apply)
    show_toast("Player blocked", "They can't send you requests or see you on their board.", "neutral")
    play_sound("click")


def unblock_player(key):
    me = _account_key()

    def apply(accts):
        if me in accts:
            soc = _social_of(accts[me])
            soc["blocked"] = [x for x in soc["blocked"] if x != key]
    _social_update(apply)
    play_sound("click")


# -----------------------------------------------------------------------------
# NAVIGATION HARDENING
# -----------------------------------------------------------------------------
ui_recovery_message = ""
ui_recovery_until = 0.0

def _draw_section_shell(surface, title, subtitle):
    off = scroll_offset.get(state.tab, 0)
    clip = pygame.Rect(0, CONTENT_TOP, WIDTH, CONTENT_BOTTOM - CONTENT_TOP)
    prev = surface.get_clip(); surface.set_clip(clip)
    y = CONTENT_TOP - off
    draw_text(surface, title, font_sg_h2, C("INK"), 20, y)
    draw_text(surface, subtitle, font_small, C("GRAY"), 20, y + 32)
    return prev, y + 68


# Guided "First Week" path: each quest teaches one habit and pays XP once.
QUESTS = [
    ("buy", "Buy your first stock", "Owning a share means you own a tiny piece of a company.", 40),
    ("diversify", "Own 3 different stocks", "Spreading money out means one bad day hurts less.", 60),
    ("sell", "Sell a stock", "Selling locks in your profit or loss.", 40),
    ("lesson", "Finish an Academy lesson", "Knowing why prices move beats guessing.", 50),
    ("duel", "Win a bot battle", "Battles show how different strategies play out.", 80),
    ("dividend", "Collect a dividend", "Some companies pay you just for holding.", 60),
    ("sectors", "Own stocks in 3 sectors", "Different industries rise and fall at different times.", 80),
    ("grow", "Grow your portfolio 5%", "Patience and smart choices add up.", 120),
]


def owned_tickers():
    return [t for t, q in state.holdings.items() if q and q > 0]


def diversification_score():
    """0-100: rewards more holdings, more sectors, and no single stock dominating."""
    held = owned_tickers()
    if not held:
        return 0
    values = []
    sectors = set()
    for t in held:
        a = find_asset(t)
        if a:
            values.append(a["price"] * state.holdings[t])
            sectors.add(a.get("sector", "?"))
    total = sum(values) or 1
    biggest = max(values) / total if values else 1
    return int(min(40, len(held) * 8) + min(30, len(sectors) * 10) + (1 - biggest) * 30)


def quest_done(qid):
    held = owned_tickers()
    if qid == "buy":
        return state.trade_count > 0 or bool(held)
    if qid == "diversify":
        return len(held) >= 3
    if qid == "sell":
        return bool(state.realized_pnl)
    if qid == "lesson":
        return bool(state.academy_completed)
    if qid == "duel":
        return state.total_wins > 0
    if qid == "dividend":
        return state.total_dividends > 0
    if qid == "sectors":
        return len({(find_asset(t) or {}).get("sector") for t in held}) >= 3
    if qid == "grow":
        return net_worth() >= STARTING_CASH * 1.05
    return False


def check_quests():
    claimed = state.quests_claimed
    for qid, title, _, xp in QUESTS:
        if qid not in claimed and quest_done(qid):
            claimed.append(qid)
            add_xp(xp)
            add_week_points(xp // 4)
            show_toast(f"Quest complete: {title}", f"+{xp} XP", "achievement")
            play_sound("achievement")
            return  # one celebration at a time


def _wrap_words(text, font, width):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if font.size(t)[0] <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])

def trade_review(stock, pnl, avg_price):
    """A short, kid-friendly coach note after each sale."""
    pct = (stock["price"] - avg_price) / avg_price * 100 if avg_price else 0.0
    held_for = time.time() - state.hold_since.get(stock["ticker"], time.time())
    if pnl >= 0 and pct >= 3:
        return f"Nice! You sold {stock['ticker']} {pct:.1f}% above what you paid. Locking in gains is a real skill."
    if abs(pct) < 0.05:
        return f"You broke even on {stock['ticker']}. No harm done; next time, have a plan for when you'll sell."
    if pnl >= 0:
        return f"Small win on {stock['ticker']} (+{pct:.1f}%). Tiny gains add up, but trading too often can eat them."
    if held_for < 60:
        return f"You sold {stock['ticker']} {abs(pct):.1f}% down after under a minute. Prices wiggle; quick panic sells often lock in losses."
    if pct <= -8:
        return f"{stock['ticker']} fell {abs(pct):.1f}%. Cutting a big loser can be smart; spreading money out keeps one loss small."
    return f"A {abs(pct):.1f}% loss on {stock['ticker']}. Ask: did the reason I bought change, or just the price?"


# ---- Weekly league: trophies set your tier, weekly points set your place vs. bots.
LEAGUE_TIERS = [("Bronze", 0, (176, 112, 64)), ("Silver", 150, (150, 156, 168)), ("Gold", 400, (212, 160, 23)),
                ("Platinum", 800, (60, 170, 180)), ("Diamond", 1400, (110, 110, 240))]


def league_tier(trophies=None):
    t = state.trophies if trophies is None else trophies
    tier = LEAGUE_TIERS[0]
    for entry in LEAGUE_TIERS:
        if t >= entry[1]:
            tier = entry
    return tier


def week_id():
    import datetime
    iso = datetime.date.today().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _week_progress():
    import datetime
    d = datetime.datetime.now()
    return min(1.0, (d.weekday() * 86400 + d.hour * 3600 + d.minute * 60) / (7 * 86400))


def league_standings():
    """Player plus six bots. Bot scores grow through the week, seeded per week."""
    rows = [{"name": state.player_name, "points": state.week_points, "me": True}]
    prog = _week_progress()
    for r in RIVALS:
        rnd = random.Random(f"{week_id()}:{r['id']}")
        target = rnd.randint(40, 120) + r["difficulty"] * 35 + league_tier()[1] // 10
        rows.append({"name": r["name"], "points": int(target * prog), "me": False})
    return sorted(rows, key=lambda x: -x["points"])


def check_week_rollover():
    wk = week_id()
    if state.week_id == wk:
        return
    if state.week_id and state.week_points > 0:
        place = next((i for i, r in enumerate(league_standings()) if r["me"]), 6) + 1
        reward = {1: 300, 2: 200, 3: 120}.get(place, 40)
        add_xp(reward)
        show_toast(f"Weekly league: you placed #{place}", f"+{reward} XP. A fresh week starts now!", "achievement")
    state.week_id = wk
    state.week_points = 0


def add_week_points(n):
    check_week_rollover()
    state.week_points += max(0, int(n))


def why_it_moved(asset):
    """Plain-language reason for a stock's move today, based on what the sim actually did."""
    snap = stock_snapshot(asset)
    move = snap["move"]
    now = time.time()
    for item in state.news_feed[:20]:
        if item.get("ticker") == asset["ticker"] and now - item.get("time", 0) < 900:
            return item.get("headline", ""), "News about the company changed what investors expect."
    ev = state.active_market_event
    if ev and (ev.get("kind") in ("market", "volatility") or ev.get("sector") == asset.get("sector") or ev.get("ticker") == asset["ticker"]):
        return ev.get("headline", ev.get("title", "Market event")), ev.get("lesson", "")
    sector_trend = state.sector_trends.get(asset.get("sector"), 0.0)
    if abs(sector_trend) > abs(getattr(state, "sim_market_trend", 0.0)) and (sector_trend > 0) == (move > 0):
        return f"The whole {asset.get('sector', '')} sector is moving {'up' if move > 0 else 'down'}.", \
               "Stocks in the same industry often move together."
    if (getattr(state, "sim_market_trend", 0.0) > 0) == (move > 0):
        return f"The overall market is {'rising' if move > 0 else 'falling'} today.", \
               "When the whole market moves, most stocks get pulled along."
    return "No big news: this is normal day-to-day wiggle.", "Prices bounce around even when nothing important happens."


def draw_why_card(surface, y):
    movers = sorted(STOCKS, key=lambda a: -abs(stock_snapshot(a)["move"]))
    a = movers[0]
    move = stock_snapshot(a)["move"]
    reason, lesson = why_it_moved(a)
    lines = _wrap_words(reason, font_small, WIDTH - 72)[:2] + _wrap_words(lesson, font_tiny, WIDTH - 72)[:2]
    card = pygame.Rect(20, y, WIDTH - 40, 58 + 18 * len(lines))
    draw_rounded_rect(surface, card, C("CARD"), radius=14, border_color=C("BORDER"), border_width=1)
    draw_text(surface, "WHY DID IT MOVE?", font_tiny, C("PURPLE"), card.x + 14, card.y + 12)
    col = C("GREEN") if move >= 0 else C("RED")
    draw_text(surface, f"{a['ticker']}  {'+' if move >= 0 else ''}{move:.2f}%", font_body_bold, col, card.x + 14, card.y + 30)
    home_action_rects[f"stock:{a['ticker']}"] = card
    ly = card.y + 56
    n_reason = len(_wrap_words(reason, font_small, WIDTH - 72)[:2])
    for i, ln in enumerate(lines):
        draw_text(surface, ln, font_small if i < n_reason else font_tiny, C("INK") if i < n_reason else C("GRAY"), card.x + 14, ly)
        ly += 18
    return card.bottom + 14


def draw_challenges_tab(surface):
    global challenge_click_rects
    challenge_click_rects = {}
    prev, y = _draw_section_shell(surface, "Challenges", "Complete missions to earn XP and build habits.")
    c = current_challenge()
    card = pygame.Rect(20, y, WIDTH - 40, 150)
    draw_rounded_rect(surface, card, C("PURPLE_BG"), radius=18, border_color=C("PURPLE"), border_width=1)
    draw_text(surface, "TODAY'S CHALLENGE", font_tiny, C("PURPLE"), card.x + 16, card.y + 14)
    draw_text(surface, c["title"], font_body_bold, C("INK"), card.x + 16, card.y + 38, max_width=270)
    draw_text(surface, c["desc"], font_small, C("GRAY"), card.x + 16, card.y + 66, max_width=300)
    draw_text(surface, f"Progress  {state.challenge_progress}/{c['goal']}", font_small_bold, C("INK"), card.x + 16, card.y + 98)
    bar = pygame.Rect(card.x + 16, card.y + 122, card.w - 32, 10)
    pygame.draw.rect(surface, C("PANEL_BG"), bar, border_radius=5)
    pct = min(1.0, state.challenge_progress / max(1, c["goal"]))
    pygame.draw.rect(surface, C("PURPLE"), (bar.x, bar.y, int(bar.w * pct), bar.h), border_radius=5)
    y += 168
    done_n = sum(1 for q in QUESTS if q[0] in state.quests_claimed)
    draw_text(surface, "Trader Path", font_body_bold, C("INK"), 20, y)
    draw_text(surface, f"{done_n}/{len(QUESTS)} complete", font_small_bold, C("PURPLE"), WIDTH - 20, y + 2, align="right")
    y += 30
    next_found = False
    for qid, title, why, xp in QUESTS:
        done = qid in state.quests_claimed
        current = not done and not next_found
        next_found = next_found or current
        r = pygame.Rect(20, y, WIDTH - 40, 64)
        draw_rounded_rect(surface, r, C("PANEL_BG") if done else (C("PURPLE_BG") if current else C("CARD")), radius=12,
                          border_color=C("GREEN") if done else (C("PURPLE") if current else C("BORDER")), border_width=1)
        dot = (r.x + 22, r.centery)
        if done:
            pygame.draw.circle(surface, C("GREEN"), dot, 10)
            pygame.draw.lines(surface, C("CARD"), False, [(dot[0] - 5, dot[1]), (dot[0] - 1, dot[1] + 4), (dot[0] + 5, dot[1] - 4)], 2)
        else:
            pygame.draw.circle(surface, C("PURPLE") if current else C("BORDER"), dot, 10, 2)
        draw_text(surface, title, font_small_bold, C("INK") if (done or current) else C("GRAY"), r.x + 44, r.y + 12, max_width=r.w - 120)
        draw_text(surface, why, font_tiny, C("GRAY"), r.x + 44, r.y + 36, max_width=r.w - 60)
        draw_text(surface, f"+{xp} XP", font_tiny, C("GREEN") if done else C("PURPLE"), r.right - 14, r.y + 13, align="right")
        y += 72
    clamp_scroll("challenges", y - CONTENT_TOP + scroll_offset.get("challenges", 0))
    surface.set_clip(prev)


# ---- Report card: risk-adjusted performance vs. the index ------------------

GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1}
GRADE_COLORS = {"A": "GREEN", "B": "TEAL", "C": "GOLD", "D": "ORANGE"}


def sample_performance(now):
    """Record net worth and the Ledger 500 index side by side for the Report Card."""
    if now - getattr(state, "last_perf_sample", 0.0) < PERF_SAMPLE_SECONDS:
        return
    state.last_perf_sample = now
    bench = find_asset("LEDR")
    state.perf_history.append([round(now, 1), round(net_worth(), 2), round(float(bench["price"]) if bench else 0.0, 2)])
    del state.perf_history[:-PERF_HISTORY_MAX]


def performance_stats():
    """Risk and return from the saved history, chain-linked like a real fund's returns.
    Steps that span a gap between play sessions are skipped, because prices reset on launch."""
    rets, bench = [], []
    h = state.perf_history
    for (t0, v0, b0), (t1, v1, b1) in zip(h, h[1:]):
        if t1 - t0 > PERF_SAMPLE_SECONDS * 3 or v0 <= 0 or b0 <= 0:
            continue
        rets.append(v1 / v0 - 1.0)
        bench.append(b1 / b0 - 1.0)
    if len(rets) < 6:
        return None
    you, idx = [100.0], [100.0]
    for r, b in zip(rets, bench):
        you.append(you[-1] * (1 + r))
        idx.append(idx[-1] * (1 + b))
    n = len(rets)
    mean, bmean = sum(rets) / n, sum(bench) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
    bvar = sum((b - bmean) ** 2 for b in bench) / (n - 1)
    cov = sum((r - mean) * (b - bmean) for r, b in zip(rets, bench)) / (n - 1)
    per_hour = 3600.0 / PERF_SAMPLE_SECONDS
    peak, mdd = you[0], 0.0
    for v in you:
        peak = max(peak, v)
        mdd = max(mdd, 1 - v / peak)
    return {"you": you, "index": idx, "ret": you[-1] / 100 - 1, "bench_ret": idx[-1] / 100 - 1,
            "vol": std * math.sqrt(per_hour), "sharpe": mean / std * math.sqrt(per_hour) if std > 1e-12 else 0.0,
            "mdd": mdd, "beta": cov / bvar if bvar > 1e-12 else 0.0, "minutes": n * PERF_SAMPLE_SECONDS / 60}


def report_card(stats):
    """Rows of (subject, letter grade or '-', detail)."""
    rows = []
    if stats:
        edge = (stats["ret"] - stats["bench_ret"]) * 100
        rows.append(("Growth vs. the index", "A" if edge >= 1 else "B" if edge >= -0.5 else "C" if edge >= -3 else "D",
                     f"You {stats['ret'] * 100:+.1f}%  vs.  index {stats['bench_ret'] * 100:+.1f}%"))
        dd = stats["mdd"] * 100
        rows.append(("Risk control", "A" if dd <= 3 else "B" if dd <= 7 else "C" if dd <= 12 else "D",
                     f"Worst dip: {dd:.1f}% below your high"))
    else:
        rows.append(("Growth vs. the index", "-", "Play for a couple of minutes to get graded"))
        rows.append(("Risk control", "-", "Play for a couple of minutes to get graded"))
    div = diversification_score()
    rows.append(("Diversification", ("A" if div >= 70 else "B" if div >= 50 else "C" if div >= 30 else "D") if owned_tickers() else "-",
                 f"Score {div}/100" if owned_tickers() else "Own a few stocks to get graded"))
    trades = sum(1 for t in state.trade_log if t.get("reason") != "auto")
    biases = sum(state.bias_counts.values())
    if trades:
        rate = biases / trades
        rows.append(("Discipline", "A" if rate <= 0.1 else "B" if rate <= 0.25 else "C" if rate <= 0.5 else "D",
                     f"{biases} bias alert{'s' if biases != 1 else ''} in {trades} trade{'s' if trades != 1 else ''}"))
    else:
        rows.append(("Discipline", "-", "Make a few trades to get graded"))
    total = len(_LESSON_INFO)
    done = len([l for l in state.academy_completed if l in _LESSON_INFO])
    frac = done / max(1, total)
    rows.append(("Learning", "A" if frac >= 0.8 else "B" if frac >= 0.5 else "C" if frac >= 0.25 else "D",
                 f"{done}/{total} Academy lessons"))
    return rows


def draw_grade_badge(surface, center, letter, r=15, font=None):
    col = C(GRADE_COLORS.get(letter, "LIGHT_GRAY"))
    font = font or font_body_bold
    pygame.draw.circle(surface, mix_color(col, C("CARD"), 0.84), center, r)
    pygame.draw.circle(surface, col, center, r, 2)
    draw_text(surface, letter, font, col, center[0], center[1] - font.get_height() // 2, align="center")


def draw_compare_chart(surface, rect, series, baseline=100.0):
    """Several lines on one shared scale. series: [(values, color)]. Values start at `baseline`."""
    vals = [v for s, _ in series for v in s] + [baseline]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1.0:
        mid = (hi + lo) / 2
        lo, hi = mid - 0.5, mid + 0.5
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    def pt(i, v, n):
        return (rect.x + rect.w * i / max(1, n - 1), rect.bottom - (v - lo) / (hi - lo) * rect.h)

    by = pt(0, baseline, 2)[1]
    for dx in range(0, rect.w, 9):
        pygame.draw.line(surface, C("BORDER"), (rect.x + dx, by), (rect.x + min(rect.w, dx + 4), by), 1)
    for values, col in series:
        n = len(values)
        step = max(1, n // 240)  # thin very long histories so drawing stays cheap
        pts = [pt(i, values[i], n) for i in range(0, n, step)]
        if pts[-1] != pt(n - 1, values[-1], n):
            pts.append(pt(n - 1, values[-1], n))
        if len(pts) >= 2:
            pygame.draw.lines(surface, col, False, pts, 2)
        pygame.draw.circle(surface, col, pts[-1], 4)


def draw_analytics_tab(surface):
    prev, y = _draw_section_shell(surface, "Analytics", "Your report card: how you trade, not just how much you made.")
    stats = performance_stats()
    rows = report_card(stats)

    graded = [GRADE_POINTS[g] for _, g, _ in rows if g in GRADE_POINTS]
    gpa = sum(graded) / len(graded) if graded else 0.0
    overall = "A" if gpa >= 3.5 else "B" if gpa >= 2.5 else "C" if gpa >= 1.5 else "D"
    card = pygame.Rect(20, y, WIDTH - 40, 76 + len(rows) * 50)
    draw_rounded_rect(surface, card, C("CARD"), radius=16, border_color=C("BORDER"), border_width=1)
    draw_text(surface, "REPORT CARD", font_tiny, C("PURPLE"), card.x + 16, card.y + 14)
    draw_text(surface, "Graded like a real fund manager", font_small_bold, C("INK"), card.x + 16, card.y + 32)
    draw_grade_badge(surface, (card.right - 40, card.y + 36), overall, r=22, font=font_large_med)
    draw_text(surface, "OVERALL", font_tiny, C("GRAY"), card.right - 40, card.y + 62, align="center")
    ry = card.y + 76
    for label, grade, detail in rows:
        draw_grade_badge(surface, (card.x + 32, ry + 18), grade)
        draw_text(surface, label, font_small_bold, C("INK"), card.x + 58, ry + 3)
        draw_text(surface, detail, font_tiny, C("GRAY"), card.x + 58, ry + 23, max_width=card.w - 74)
        ry += 50
    y = card.bottom + 18

    draw_text(surface, "You vs. the Ledger 500 index", font_body_bold, C("INK"), 20, y)
    y += 26
    chart = pygame.Rect(20, y, WIDTH - 40, 176)
    draw_rounded_rect(surface, chart, C("CARD"), radius=14, border_color=C("BORDER"), border_width=1)
    if stats:
        you_col, idx_col = C("PURPLE"), C("LIGHT_GRAY")
        draw_compare_chart(surface, pygame.Rect(chart.x + 16, chart.y + 42, chart.w - 32, chart.h - 58),
                           [(stats["index"], idx_col), (stats["you"], you_col)])
        lx = chart.x + 16
        for label, col, val in (("You", you_col, stats["ret"]), ("Index", idx_col, stats["bench_ret"])):
            pygame.draw.circle(surface, col, (lx + 5, chart.y + 21), 5)
            r = draw_text(surface, f"{label} {val * 100:+.2f}%", font_small_bold, C("INK"), lx + 15, chart.y + 12)
            lx = r.right + 18
        draw_text(surface, f"last {stats['minutes']:.0f} min of play", font_tiny, C("GRAY"), chart.right - 14, chart.y + 15, align="right")
    else:
        draw_text(surface, "Your line appears after about a minute of play.", font_small, C("GRAY"), chart.centerx, chart.centery - 18, align="center")
        draw_text(surface, "Beating the index is harder than it looks!", font_tiny, C("LIGHT_GRAY"), chart.centerx, chart.centery + 6, align="center")
    y = chart.bottom + 18

    draw_text(surface, "Risk stats the pros use", font_body_bold, C("INK"), 20, y)
    y += 26
    if stats:
        tiles = [
            ("Bumpiness", f"{stats['vol'] * 100:.1f}% / hr", "How much your value swings. Pros call it volatility."),
            ("Worst dip", f"-{stats['mdd'] * 100:.1f}%", "Biggest drop from a high. Pros call it max drawdown."),
            ("Reward per bump", f"{stats['sharpe']:.2f}", "Return for each unit of risk. Pros call it the Sharpe ratio."),
            ("Moves with market", f"{stats['beta']:.2f}x", "1.0 means you move like the index. Pros call it beta."),
        ]
    else:
        tiles = [(name, "--", hint) for name, hint in (
            ("Bumpiness", "How much your value swings. Pros call it volatility."),
            ("Worst dip", "Biggest drop from a high. Pros call it max drawdown."),
            ("Reward per bump", "Return for each unit of risk. Pros call it the Sharpe ratio."),
            ("Moves with market", "1.0 means you move like the index. Pros call it beta."))]
    cw = (WIDTH - 50) // 2
    for i, (label, value, hint) in enumerate(tiles):
        r = pygame.Rect(20 + (i % 2) * (cw + 10), y + (i // 2) * 104, cw, 94)
        draw_rounded_rect(surface, r, C("CARD"), radius=12, border_color=C("BORDER"), border_width=1)
        draw_text(surface, label, font_tiny, C("GRAY"), r.x + 12, r.y + 10, max_width=r.w - 24)
        draw_text(surface, value, font_medium_bold, C("INK"), r.x + 12, r.y + 28, max_width=r.w - 24)
        for k, line in enumerate(wrap_text(hint, font_tiny, r.w - 24)[:2]):
            draw_text(surface, line, font_tiny, C("GRAY"), r.x + 12, r.y + 56 + k * 15)
    y += 2 * 104 + 10

    metrics = [
        ("Portfolio value", fmt_money(net_worth())),
        ("Total trades", str(state.trade_count)),
        ("Realized P&L", fmt_money(sum(state.realized_pnl.values()))),
        ("Dividends", fmt_money(state.total_dividends)),
    ]
    for i, (label, value) in enumerate(metrics):
        r = pygame.Rect(20 + (i % 2) * (cw + 10), y + (i // 2) * 74, cw, 64)
        draw_rounded_rect(surface, r, C("CARD"), radius=12, border_color=C("BORDER"), border_width=1)
        draw_text(surface, label, font_tiny, C("GRAY"), r.x + 12, r.y + 10, max_width=r.w - 24)
        draw_text(surface, value, font_body_bold, C("INK"), r.x + 12, r.y + 30, max_width=r.w - 24)
    y += 2 * 74 + 8
    draw_text(surface, "Past results in Ledger don't predict future results, just like real markets.", font_tiny, C("GRAY"), 20, y, max_width=WIDTH - 40)
    y += 30
    clamp_scroll("analytics", y - CONTENT_TOP + scroll_offset.get("analytics", 0))
    surface.set_clip(prev)


def draw_journal_tab(surface):
    prev, y = _draw_section_shell(surface, "Trade Journal", "Your trades, your reasons, and what they taught you.")

    # Bias Radar
    total_b = sum(state.bias_counts.values())
    card = pygame.Rect(20, y, WIDTH - 40, 62 + len(BIASES) * 44)
    draw_rounded_rect(surface, card, C("CARD"), radius=16, border_color=C("BORDER"), border_width=1)
    draw_text(surface, "BIAS RADAR", font_tiny, C("ORANGE"), card.x + 16, card.y + 14)
    draw_text(surface, "Mistakes every trader makes. Fewer is better." if total_b else "No alerts yet. Calm and steady!",
              font_small_bold, C("INK"), card.x + 16, card.y + 32, max_width=card.w - 32)
    ry = card.y + 62
    for bid, (name, tip) in BIASES.items():
        n = state.bias_counts.get(bid, 0)
        col = C("ORANGE") if n else C("GREEN")
        pygame.draw.circle(surface, col, (card.x + 24, ry + 12), 6)
        draw_text(surface, name, font_small_bold, C("INK"), card.x + 40, ry + 3, max_width=card.w - 110)
        draw_text(surface, tip, font_tiny, C("GRAY"), card.x + 40, ry + 22, max_width=card.w - 56)
        pill = pygame.Rect(card.right - 58, ry + 2, 42, 22)
        draw_rounded_rect(surface, pill, mix_color(col, C("CARD"), 0.85), radius=11, shadow=False)
        draw_text(surface, f"x{n}", font_tiny, col, pill.centerx, pill.y + 4, align="center")
        ry += 44
    y = card.bottom + 18

    # Which reasons actually work?
    draw_text(surface, "Which reasons work for you?", font_body_bold, C("INK"), 20, y)
    y += 28
    scored = [(TRADE_REASON_LABELS[rid], state.reason_stats[rid]) for rid in TRADE_REASON_LABELS
              if state.reason_stats.get(rid, {}).get("n")]
    if not scored:
        lines = wrap_text("Pick a reason when you buy. When you sell, Ledger scores whether that reason made you money.",
                          font_small, WIDTH - 72)
        r = pygame.Rect(20, y, WIDTH - 40, 20 + 18 * len(lines))
        draw_rounded_rect(surface, r, C("PURPLE_BG"), radius=12, shadow=False)
        for i, ln in enumerate(lines):
            draw_text(surface, ln, font_small, C("INK"), r.x + 16, r.y + 10 + i * 18)
        y = r.bottom + 18
    else:
        for label, rs in sorted(scored, key=lambda x: -x[1]["pnl"]):
            r = pygame.Rect(20, y, WIDTH - 40, 56)
            draw_rounded_rect(surface, r, C("CARD"), radius=12, border_color=C("BORDER"), border_width=1)
            win = rs["wins"] / rs["n"]
            draw_text(surface, label, font_small_bold, C("INK"), r.x + 14, r.y + 8)
            draw_text(surface, f"{rs['n']} sold  •  {win * 100:.0f}% winners", font_tiny, C("GRAY"), r.x + 14, r.y + 28)
            pcol = C("GREEN") if rs["pnl"] >= 0 else C("RED")
            draw_text(surface, f"{'+' if rs['pnl'] >= 0 else '-'}{fmt_money(abs(rs['pnl']))}", font_body_bold, pcol, r.right - 14, r.y + 8, align="right")
            bar = pygame.Rect(r.right - 114, r.y + 34, 100, 6)
            pygame.draw.rect(surface, C("PANEL_BG"), bar, border_radius=3)
            if win > 0:
                pygame.draw.rect(surface, pcol, (bar.x, bar.y, max(6, int(bar.w * win)), bar.h), border_radius=3)
            y += 64
        y += 10

    # Every trade
    draw_text(surface, "Trade log", font_body_bold, C("INK"), 20, y)
    draw_text(surface, f"{len(state.trade_log)} saved", font_tiny, C("GRAY"), WIDTH - 20, y + 4, align="right")
    y += 28
    entries = list(reversed(state.trade_log))[:25]
    if not entries:
        draw_text(surface, "No trades yet. Your first decision will appear here.", font_small, C("GRAY"), 20, y)
        y += 30
    for t in entries:
        r = pygame.Rect(20, y, WIDTH - 40, 58)
        if r.bottom > CONTENT_TOP - 5 and r.top < CONTENT_BOTTOM + 5:
            draw_rounded_rect(surface, r, C("CARD"), radius=10, border_color=C("BORDER"), border_width=1)
            buy = t.get("side") == "buy"
            side = pygame.Rect(r.x + 12, r.y + 10, 42, 20)
            scol = C("PURPLE") if buy else C("INK")
            draw_rounded_rect(surface, side, mix_color(scol, C("CARD"), 0.85), radius=10, shadow=False)
            draw_text(surface, "BUY" if buy else "SELL", font_tiny, scol, side.centerx, side.y + 3, align="center")
            draw_text(surface, f"{t.get('ticker', '')}  {t.get('qty', 0):g} @ {fmt_money(t.get('price', 0))}",
                      font_small_bold, C("INK"), side.right + 10, r.y + 10, max_width=r.w - 170)
            reason = t.get("reason")
            tags = [TRADE_REASON_LABELS.get(reason, reason) if reason else "No reason given"]
            tags += [BIASES[b][0] for b in t.get("biases", []) if b in BIASES]
            draw_text(surface, "  •  ".join(tags), font_tiny, C("ORANGE") if t.get("biases") else C("GRAY"),
                      r.x + 12, r.y + 36, max_width=r.w - 120)
            draw_text(surface, time_ago(t.get("t", time.time())), font_tiny, C("GRAY"), r.right - 12, r.y + 12, align="right")
            if "pnl" in t:
                pnl = t["pnl"]
                draw_text(surface, f"{'+' if pnl >= 0 else '-'}{fmt_money(abs(pnl))}", font_small_bold,
                          C("GREEN") if pnl >= 0 else C("RED"), r.right - 12, r.y + 32, align="right")
        y += 64

    if state.trade_reviews:
        y += 10
        draw_text(surface, "Coach notes", font_body_bold, C("INK"), 20, y)
        y += 28
        for note in state.trade_reviews[:3]:
            lines = _wrap_words(note, font_small, WIDTH - 72)
            r = pygame.Rect(20, y, WIDTH - 40, 20 + 18 * len(lines))
            draw_rounded_rect(surface, r, C("PURPLE_BG"), radius=10, border_color=C("PURPLE"), border_width=1)
            for i, ln in enumerate(lines):
                draw_text(surface, ln, font_small, C("INK"), r.x + 14, r.y + 10 + i * 18, max_width=r.w - 28)
            y += r.h + 8
    y += 16
    clamp_scroll("journal", y - CONTENT_TOP + scroll_offset.get("journal", 0))
    surface.set_clip(prev)


TAB_TRANSITION_SECONDS = 0.24


def draw_tab_animated(surface, tab_key):
    """Draw the current tab, sliding and fading it in for a moment after a tab switch."""
    order = [k for k, _, _ in TABS]
    prev = _slides.get("tab", {}).get("value")
    a = order.index(tab_key) if tab_key in order else len(order)
    b = order.index(prev) if prev in order else len(order)
    top = GAME_TOP if is_full_tab(tab_key) else 193
    area = pygame.Rect(0, top, WIDTH, CONTENT_BOTTOM - top)
    draw_with_slide(surface, "tab", tab_key, area, lambda: safe_draw_tab(surface, tab_key),
                    direction=1 if a >= b else -1, duration=TAB_TRANSITION_SECONDS)


# ----------------------------
# GUIDED TOUR (spotlight walkthrough of the real screens)
# ----------------------------

header_trophy_rect = None
header_coin_rect = None
header_level_rect = None
tour = {"active": False, "step": 0, "start": 0.0}
tour_btn = {}


def _tab_rect(key):
    for rect, k in tab_button_rects:
        if k == key:
            return rect
    return None


def _menu_rect(keys):
    rects = [r for r, k in menu_button_rects if k in keys]
    return rects[0].unionall(rects[1:]) if rects else None


def _first_market_row():
    return market_row_rects[0][0] if market_row_rects else None


TOUR_STEPS = [
    {"title": "Welcome to the trading floor!", "body": "Here's a quick tour of where everything lives. It takes about a minute.", "tab": "home"},
    {"title": "Your portfolio value", "body": "Everything you're worth: your cash plus the stocks you own. Green means you're up from your $1,000 start.",
     "tab": "home", "target": lambda: home_hero_rect},
    {"title": "Your money chart", "body": "This line moves live as your stocks change. The dashed line marks where it started.",
     "tab": "home", "target": lambda: home_chart_rect},
    {"title": "Trophies & leagues", "body": "Win 1v1 duels in the Arena to earn trophies and climb the leagues.",
     "target": lambda: header_trophy_rect},
    {"title": "Ledger Coins", "body": "Earn coins by learning, trading and winning duels. Tap here to open Rewards: chests, boosts and cosmetics!",
     "target": lambda: header_coin_rect},
    {"title": "This is you!", "body": "Tap your avatar any time to change your look. It reacts to your trades too.",
     "target": lambda: pygame.Rect(10, 8, 200, 60)},
    {"title": "Home", "body": "Your daily mission, watchlist and quick shortcuts all live here.",
     "tab": "home", "target": lambda: _tab_rect("home")},
    {"title": "Market", "body": "Every stock you can trade. Search by company name or ticker.",
     "tab": "market", "target": lambda: market_search_rect},
    {"title": "Tap a stock to trade", "body": "Each row shows the company, a mini chart, the price and today's move. Tap one to research, buy or sell.",
     "tab": "market", "target": _first_market_row},
    {"title": "Learn", "body": "Short lessons and quizzes that earn XP and level you up.",
     "tab": "academy", "target": lambda: _tab_rect("academy")},
    {"title": "Portfolio", "body": "What you own, your profit and loss, and how spread out your money is.",
     "tab": "portfolio", "target": lambda: _tab_rect("portfolio")},
    {"title": "More", "body": "Arena duels, News, Friends, Rewards, Settings and more are in this menu.",
     "menu": True, "target": lambda: _menu_rect({"arena", "news", "leaderboard"})},
    {"title": "You're all set!", "body": "You can replay this tour any time from the More menu. Happy trading!", "tab": "home"},
]


def start_tour():
    tour.update(active=True, step=0)
    _enter_tour_step()


def _enter_tour_step():
    global menu_open
    step = TOUR_STEPS[tour["step"]]
    tour["start"] = time.time()
    close_modal()
    close_detail_modal()
    state.market_search_active = False
    menu_open = bool(step.get("menu"))
    if step.get("tab"):
        state.tab = step["tab"]
        scroll_offset[state.tab] = 0


def end_tour(completed=True):
    global menu_open
    tour["active"] = False
    menu_open = False
    state.tab = "home"
    if not getattr(state, "tour_completed", False):
        state.tour_completed = True
        save_game()
    if completed:
        spawn_confetti(40)
        play_sound("achievement")
        avatar_emote("cheer")


def tour_go(delta):
    nxt = tour["step"] + delta
    if nxt < 0:
        return
    play_sound("click")
    if nxt >= len(TOUR_STEPS):
        end_tour(True)
        return
    tour["step"] = nxt
    _enter_tour_step()


def handle_tour_event(event):
    if event.type == pygame.KEYDOWN:
        if event.key in (pygame.K_RIGHT, pygame.K_RETURN, pygame.K_SPACE):
            tour_go(1)
        elif event.key == pygame.K_LEFT:
            tour_go(-1)
        elif event.key == pygame.K_ESCAPE:
            end_tour(False)
    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        pos = event.pos
        if tour_btn.get("skip") and tour_btn["skip"].collidepoint(pos):
            end_tour(False)
        elif tour_btn.get("back") and tour_btn["back"].collidepoint(pos):
            tour_go(-1)
        elif (tour_btn.get("next") and tour_btn["next"].collidepoint(pos)) or \
                (tour_btn.get("hole") and tour_btn["hole"].collidepoint(pos)):
            tour_go(1)


def draw_tour(surface):
    if not tour["active"]:
        return
    tour_btn.clear()
    now = time.time()
    i = tour["step"]
    step = TOUR_STEPS[i]
    n = len(TOUR_STEPS)
    appear = ease_out_cubic((now - tour["start"]) / 0.3)

    target = None
    try:
        target = step["target"]() if step.get("target") else None
    except Exception:
        target = None
    hole = None
    if target:
        t = pygame.Rect(target).inflate(12, 12)
        hole = pygame.Rect(int(tween("tour_x", t.x, 14)), int(tween("tour_y", t.y, 14)),
                           int(tween("tour_w", t.w, 14)), int(tween("tour_h", t.h, 14)))
        tour_btn["hole"] = hole

    # Dim everything except the spotlight.
    overlay = HiSurface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill((8, 8, 16, 180))
    if hole:
        pygame.draw.rect(overlay, (0, 0, 0, 0), hole, border_radius=14)
    surface.blit(overlay, (0, 0))
    if hole:
        p = (now * 0.9) % 1.0
        grow = int(3 + 9 * p)
        ring_r = hole.inflate(grow * 2, grow * 2)
        ring = HiSurface((ring_r.w + 4, ring_r.h + 4), pygame.SRCALPHA)
        pygame.draw.rect(ring, (*C("PURPLE"), int(220 * (1 - p))), (2, 2, ring_r.w, ring_r.h), 3, border_radius=14 + grow)
        surface.blit(ring, (ring_r.x - 2, ring_r.y - 2))
        pygame.draw.rect(surface, (255, 255, 255), hole, 2, border_radius=14)

    # Tooltip card.
    card_w = WIDTH - 36
    body_lines = wrap_text(step["body"], font_body, card_w - 40)[:4]
    card_h = 18 + 18 + 30 + len(body_lines) * 22 + 16 + 44 + 18
    if hole:
        below = hole.bottom + 18
        above = hole.y - 18 - card_h
        card_y = below if below + card_h <= HEIGHT - 12 else max(12, above)
    else:
        card_y = HEIGHT // 2 - card_h // 2
    card = pygame.Rect(18, int(card_y + 14 * (1 - appear)), card_w, card_h)
    draw_rounded_rect(surface, card, C("CARD"), radius=20)
    if hole:
        ax = max(card.x + 28, min(card.right - 28, hole.centerx))
        if card.y >= hole.bottom:
            pts = [(ax - 10, card.y + 1), (ax + 10, card.y + 1), (ax, card.y - 10)]
        else:
            pts = [(ax - 10, card.bottom - 1), (ax + 10, card.bottom - 1), (ax, card.bottom + 10)]
        pygame.draw.polygon(surface, C("CARD"), pts)

    x = card.x + 20
    y = card.y + 18
    draw_text(surface, f"TOUR  •  {i + 1} OF {n}", font_tiny, C("PURPLE"), x, y)
    skip = draw_text(surface, "Skip tour", font_small_bold, C("GRAY"), card.right - 20, y - 2, align="right")
    tour_btn["skip"] = skip.inflate(16, 14)
    y += 20
    draw_text(surface, step["title"], font_large_med, C("INK"), x, y, max_width=card.w - 40)
    y += 32
    for line in body_lines:
        draw_text(surface, line, font_body, C("GRAY"), x, y)
        y += 22

    # Progress dots + buttons.
    by = card.bottom - 18 - 44
    for d in range(n):
        cx = x + 4 + d * 11
        pygame.draw.circle(surface, C("PURPLE") if d == i else C("BORDER"), (cx, by + 22), 4 if d == i else 3)
    last = i == n - 1
    tour_btn["next"] = pygame.Rect(card.right - 20 - 120, by, 120, 44)
    draw_button(surface, tour_btn["next"], "Finish" if last else "Next", C("GREEN") if last else C("INK"), C("CARD"), radius=14)
    if i > 0:
        tour_btn["back"] = pygame.Rect(tour_btn["next"].x - 84, by, 76, 44)
        draw_button(surface, tour_btn["back"], "Back", C("PANEL_BG"), C("INK"), radius=14)


def safe_draw_tab(surface, tab_key):
    """Draw a tab without allowing one broken tab to terminate Ledger.

    Navigation is deliberately isolated from individual screen rendering. If a
    tab contains a bad value or drawing call, Ledger keeps running and shows a
    clear recovery panel instead of restarting/closing the whole game.
    """
    global ui_recovery_message, ui_recovery_until
    drawers = {
        "home": draw_home_tab,
        "market": draw_market_tab,
        "portfolio": draw_portfolio_tab,
        "academy": draw_academy_tab,
        "arena": draw_arena_tab,
        "leaderboard": draw_leaderboard_tab,
        "news": draw_news_tab,
        "settings": draw_settings_tab,
        "challenges": draw_challenges_tab,
        "analytics": draw_analytics_tab,
        "journal": draw_journal_tab,
        "parents": draw_parents_tab,
        "rewards": draw_rewards_tab,
        "inventory": draw_inventory_tab,
        "levels": draw_levels_tab,
    }
    drawer = drawers.get(tab_key, draw_market_tab)
    try:
        drawer(surface)
    except Exception as exc:
        ui_recovery_message = f"{tab_key.title()} screen recovered"
        ui_recovery_until = time.time() + 5.0
        ui_error_guard(f"draw {tab_key} tab", exc)
        # Do NOT change state.tab here. The navigation destination remains
        # selected, and the recovery card tells the player what happened.
        try:
            surface.set_clip(None)
            draw_rounded_rect(surface, pygame.Rect(18, CONTENT_TOP + 30, WIDTH - 36, 180), C("CARD"), radius=18, border_color=C("BORDER"), border_width=1)
            draw_text(surface, "Ledger recovered this screen", font_large_med, C("INK"), WIDTH // 2, CONTENT_TOP + 62, align="center")
            draw_text(surface, "Your account and progress are still safe.", font_small, C("GRAY"), WIDTH // 2, CONTENT_TOP + 101, align="center")
            draw_text(surface, "Tap another navigation button to continue.", font_small, C("GRAY"), WIDTH // 2, CONTENT_TOP + 126, align="center")
            draw_button(surface, pygame.Rect(60, CONTENT_TOP + 154, WIDTH - 120, 38), "Back to Market", C("INK"), C("CARD"), font=font_small_bold, radius=10)
        except Exception:
            pass
        return False
    return True


def safe_navigation_click(pos):
    """Handle bottom navigation from raw coordinates, not rendered hitboxes.

    This is intentionally independent of tab_button_rects. The old navigation
    depended on rectangles created during drawing, so a rendering error or stale
    rectangle could make every navigation button appear dead.
    """
    global menu_open
    try:
        x, y = int(pos[0]), int(pos[1])
        nav_top = HEIGHT - TAB_BAR_HEIGHT
        if y < nav_top or y >= HEIGHT:
            return False

        # Five equal, large hit zones. Clamp the index so the right edge is safe.
        col_w = WIDTH / 5.0
        index = max(0, min(4, int(x / col_w)))
        destinations = ["home", "market", "academy", "portfolio", "__menu__"]
        key = destinations[index]

        if key == "__menu__":
            menu_open = not menu_open
        else:
            state.tab = key
            menu_open = False
            # Clear transient modal/search state when changing sections.
            state.market_search_active = False
            close_modal()
            close_detail_modal()

        play_sound("click")
        return True
    except Exception as exc:
        # Navigation itself must never be allowed to terminate the game.
        try:
            with open(os.path.join(_DATA_DIR, "ledger_ui_errors.log"), "a", encoding="utf-8") as f:
                f.write("\n" + time.strftime("%Y-%m-%d %H:%M:%S") + " | navigation | " + repr(exc) + "\n")
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        return True


def _main_loop():
    global modal_qty, qty_input_text, menu_open
    running = True
    while running:
        now = time.time()
        track_play_time(now)
        apply_color_mode()
        if state.screen_mode == "playing" and not time_up["active"]:
            # Login/tutorial completion resets last_tick to 0, so this runs immediately.
            # The renderer runs at 60 FPS, while market data is allowed to be
            # applied four times per second. This makes login/quote arrival feel
            # immediate without pretending that a real stock changes every frame.
            if now - state.last_tick >= MARKET_TICK_SECONDS:
                if state.last_tick == 0.0:
                    # Fresh login/new account: warm up so prices are visibly moving right away.
                    for _ in range(12):
                        tick_market()
                tick_market()
                check_price_alerts()
                state.last_tick = now
            if now - getattr(state, "last_housekeeping", 0.0) >= 1.0:
                check_dividends()
                run_auto_invest(now)
                check_safety_orders()
                check_achievements()
                check_quests()
                state.last_housekeeping = now
            if now - getattr(state, "last_autosave", 0.0) >= 12.0:
                save_game()
                state.last_autosave = now
            if now - state.last_history_sample >= NET_WORTH_SAMPLE_SECONDS:
                state.net_worth_history.append(net_worth())
                state.net_worth_history = state.net_worth_history[-120:]
                state.last_history_sample = now
            sample_performance(now)
            if state.xp_pulse > 0:
                state.xp_pulse = max(0.0, state.xp_pulse - 0.04)
            avatar_update(now)

        for p in particles[:]:
            p.update()
            if p.life <= 0:
                particles.remove(p)
        for ft in floating_texts[:]:
            ft.update()
            if ft.life <= 0:
                floating_texts.remove(ft)
        for orb in xp_orbs[:]:
            orb.update()
            if orb.life <= 0:
                xp_orbs.remove(orb)
        if screen_flash["life"] > 0:
            screen_flash["life"] -= 0.04

        if state.screen_mode == "signin":
            safe_button_action("google sign-in", finish_google_sign_in)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif state.screen_mode != "playing":
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if state.screen_mode == "signin":
                        safe_button_action("signin button", lambda: handle_signin_click(event.pos))
                    elif state.screen_mode == "google_form":
                        safe_button_action("google form button", lambda: handle_google_form_click(event.pos))
                    elif state.screen_mode == "account_setup":
                        safe_button_action("account setup", lambda: handle_account_setup_click(event.pos))
                    elif state.screen_mode == "reset_password":
                        safe_button_action("reset password", lambda: handle_reset_password_click(event.pos))
                    elif state.screen_mode == "avatar":
                        safe_button_action("avatar button", lambda: handle_avatar_click(event.pos))
                    elif state.screen_mode == "tutorial":
                        safe_button_action("tutorial button", lambda: handle_tutorial_click(event.pos))
                elif event.type == pygame.KEYDOWN and state.screen_mode == "signin":
                    if event.key == pygame.K_TAB:
                        state.auth_active_field = "password" if state.auth_active_field == "username" else "username"
                    elif event.key == pygame.K_RETURN:
                        login_account(state.login_username_input, state.login_password_input)
                    elif state.auth_active_field == "password":
                        state.login_password_input = handle_text_event(event, state.login_password_input, 25)
                    else:
                        state.login_username_input = handle_text_event(event, state.login_username_input, 18)
                elif event.type == pygame.KEYDOWN and state.screen_mode == "avatar":
                    state.auth_message = ""
                    if event.key == pygame.K_TAB:
                        order = ["name", "password"]
                        cur = state.avatar_active_field if state.avatar_active_field in order else "name"
                        state.avatar_active_field = order[(order.index(cur) + 1) % len(order)]
                    elif state.avatar_active_field == "password" and getattr(state, "avatar_editing", False):
                        state.password_input = handle_text_event(event, state.password_input, 25)
                    elif state.avatar_active_field == "nick":
                        state.avatar["nickname"] = handle_text_event(event, str(state.avatar.get("nickname", "")), 12)
                    elif getattr(state, "avatar_editing", False):
                        # Only an existing trader can rename here; new players chose a username already.
                        state.name_input = handle_text_event(event, state.name_input, 14)
                elif event.type == pygame.KEYDOWN and state.screen_mode == "account_setup":
                    handle_account_setup_key(event)
                elif event.type == pygame.KEYDOWN and state.screen_mode == "reset_password":
                    handle_reset_password_key(event)
                elif event.type == pygame.KEYDOWN and state.screen_mode == "google_form":
                    field = "name_input" if state.google_active_field == "name" else "email_input"
                    setattr(state, field, handle_text_event(event, getattr(state, field), 30))

            elif time_up["active"]:
                safe_button_action("time limit", lambda: handle_time_up_event(event))

            elif tour["active"] and event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL, pygame.KEYDOWN, pygame.TEXTINPUT):
                safe_button_action("tour", lambda: handle_tour_event(event))

            elif scam_game.get("open"):
                # Scam Detective is full screen, so it gets every click, drag and key while open.
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.KEYDOWN):
                    safe_button_action("scam detective", lambda: handle_scam_game_event(event))

            elif lesson_game.get("open"):
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.KEYDOWN):
                    safe_button_action("lesson", lambda: handle_lesson_game_event(event))

            elif battle.get("open"):
                if event.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN):
                    safe_button_action("battle", lambda: handle_battle_event(event))

            elif event.type == pygame.MOUSEBUTTONDOWN:
                pos = event.pos
                if chest_anim["rarity"]:
                    safe_button_action("chest", lambda: handle_chest_opening_click(pos))
                    continue
                if chest_info["rarity"]:
                    safe_button_action("chest odds", lambda: handle_chest_info_click(pos))
                    continue
                if header_level_rect and header_level_rect.collidepoint(pos) and not menu_open and not modal_stock and not detail_modal_stock:
                    state.tab = "levels"
                    _levels_scrolled["done"] = False
                    play_sound("click")
                    continue
                if header_coin_rect and header_coin_rect.collidepoint(pos) and not menu_open and not modal_stock and not detail_modal_stock:
                    state.tab = "rewards"
                    play_sound("click")
                    continue
                if state.toast and state.toast.get("action") and toast_rect and toast_rect.collidepoint(pos):
                    act = state.toast["action"]
                    state.toast = None
                    if act[0] == "news":
                        safe_button_action("news notification", lambda: open_news_item(act[1]))
                    elif act[0] in ("rewards", "inventory", "levels"):
                        close_modal()
                        close_detail_modal()
                        alerts_sheet["ticker"] = None
                        state.tab = act[0]
                        scroll_offset[act[0]] = 0
                        _levels_scrolled["done"] = False
                        play_sound("click")
                    elif act[0] == "stock" and find_asset(act[1]):
                        close_modal()
                        open_detail_modal(find_asset(act[1]))
                        play_sound("click")
                    continue
                if alerts_sheet["ticker"]:
                    safe_button_action("alerts sheet", lambda: handle_alerts_sheet_click(pos))
                    continue
                if detail_modal_stock:
                    if detail_close_btn and detail_close_btn.collidepoint(pos): close_detail_modal(); continue
                    if detail_buy_btn and detail_buy_btn.collidepoint(pos): open_modal(detail_modal_stock,"buy"); close_detail_modal(); continue
                    if detail_sell_btn and detail_sell_btn.collidepoint(pos):
                        if state.holdings.get(detail_modal_stock["ticker"], 0) > 0:
                            open_modal(detail_modal_stock, "sell"); close_detail_modal()
                        else:
                            show_toast("Nothing to sell yet", "Buy some shares first, then you can sell them.", "warning")
                            play_sound("error")
                        continue
                    if detail_watch_btn and detail_watch_btn.collidepoint(pos):
                        t=detail_modal_stock["ticker"]
                        if t in state.watchlist: state.watchlist.remove(t)
                        else: state.watchlist.append(t)
                        save_game(); play_sound("click"); continue
                    if detail_alert_btn and detail_alert_btn.collidepoint(pos):
                        open_alerts_sheet(detail_modal_stock["ticker"])
                        continue
                    for br,label in detail_range_btns:
                        if br.collidepoint(pos): state.chart_range=label; play_sound("click"); break
                    continue
                if modal_stock:
                    safe_button_action("trade modal button", lambda: handle_modal_click(pos))
                    continue

                # Hamburger drawer gets first priority while it is open.
                if menu_open:
                    if safe_button_action("menu button", lambda: handle_menu_click(pos)):
                        continue

                if header_avatar_rect and header_avatar_rect.inflate(10, 10).collidepoint(pos):
                    avatar_poke(pos)
                    play_sound("click")
                    continue
                if state.tab == "portfolio" and avatar_stage_rect and avatar_stage_rect.collidepoint(pos):
                    avatar_poke(pos)
                    play_sound("click")
                    continue

                if safe_navigation_click(pos):
                    continue

                if state.tab in ("market", "news"):
                    if market_clear_rect and market_clear_rect.collidepoint(pos) and state.market_search:
                        state.market_search = ""
                        state.market_search_active = True
                        play_sound("click")
                        continue
                    if market_search_rect and market_search_rect.collidepoint(pos):
                        state.market_search_active = True
                        continue
                if state.tab == "market" and safe_button_action("market", lambda: handle_market_click(pos)):
                    continue
                if state.tab == "portfolio" and safe_button_action("portfolio", lambda: handle_portfolio_click(pos)):
                    continue
                if state.tab == "home":
                    if safe_button_action("home button", lambda: handle_home_click(pos)): continue
                if state.tab == "academy":
                    safe_button_action("academy button", lambda: handle_academy_click(pos))
                elif state.tab == "settings":
                    if safe_button_action("settings extras", lambda: handle_settings_extra_click(pos)):
                        continue
                    if settings_click_rects.get("theme") and settings_click_rects["theme"].collidepoint(pos):
                        state.dark_mode = not state.dark_mode
                        play_sound("click")
                    elif settings_click_rects.get("sound") and settings_click_rects["sound"].collidepoint(pos):
                        state.sound_enabled = not state.sound_enabled
                        play_sound("click")
                        save_game()
                    elif settings_click_rects.get("old_pw") and settings_click_rects["old_pw"].collidepoint(pos):
                        state.settings_active_field = "old_pw"
                    elif settings_click_rects.get("new_user") and settings_click_rects["new_user"].collidepoint(pos):
                        state.settings_active_field = "new_user"
                    elif settings_click_rects.get("new_pw") and settings_click_rects["new_pw"].collidepoint(pos):
                        state.settings_active_field = "new_pw"
                    elif settings_click_rects.get("save") and settings_click_rects["save"].collidepoint(pos):
                        try_save_settings()
                    elif settings_click_rects.get("switch_account") and settings_click_rects["switch_account"].collidepoint(pos):
                        # Sign out first. Staying signed in made "Create an account" rename this
                        # account and change its password instead of creating a new one.
                        logout_account()
                        state.auth_message = "Create another account or log into a different one."
                        play_sound("click")
                    elif settings_click_rects.get("logout") and settings_click_rects["logout"].collidepoint(pos):
                        logout_account()
                        play_sound("click")
                elif state.tab == "leaderboard":
                    if safe_button_action("friends button", lambda: handle_leaderboard_click(pos)):
                        continue
                elif state.tab == "parents":
                    if safe_button_action("parent view", lambda: handle_parents_click(pos)):
                        continue
                elif state.tab == "rewards":
                    if safe_button_action("rewards button", lambda: handle_rewards_click(pos)):
                        continue
                elif state.tab == "inventory":
                    if safe_button_action("inventory button", lambda: handle_inventory_click(pos)):
                        continue
                elif state.tab == "levels":
                    if safe_button_action("levels button", lambda: handle_levels_click(pos)):
                        continue
                if state.tab == "news":
                    news_trade_clicked = False
                    for btn_rect, ticker in news_trade_rects:
                        if btn_rect.collidepoint(pos) and CONTENT_TOP <= pos[1] <= CONTENT_BOTTOM:
                            asset = find_asset(ticker)
                            if asset:
                                select_asset_for_trade(asset)
                            elif ticker == "MARKET":
                                state.tab = "market"
                                play_sound("click")
                            news_trade_clicked = True
                            break
                    if news_trade_clicked:
                        continue
                if state.tab == "arena" and safe_button_action("arena", lambda: handle_arena_click(pos)):
                    continue

                if state.tab in scroll_offset and tab_top() <= pos[1] <= CONTENT_BOTTOM and not (state.tab == "market" and market_search_rect and market_search_rect.collidepoint(pos)):
                    drag_state["active"] = True
                    drag_state["start_pos"] = pos
                    drag_state["start_offset"] = scroll_offset[state.tab]
                    drag_state["tab"] = state.tab
                    drag_state["moved"] = False

            elif event.type == pygame.MOUSEMOTION and state.screen_mode == "playing":
                if drag_state["active"] and drag_state["tab"]:
                    dx = event.pos[0] - drag_state["start_pos"][0]
                    dy = event.pos[1] - drag_state["start_pos"][1]
                    if abs(dy) > CLICK_DRAG_THRESHOLD or abs(dx) > CLICK_DRAG_THRESHOLD:
                        drag_state["moved"] = True
                    if drag_state["moved"]:
                        scroll_offset[drag_state["tab"]] = drag_state["start_offset"] - dy

            elif event.type == pygame.MOUSEBUTTONUP and state.screen_mode == "playing":
                pos = event.pos
                if drag_state["active"]:
                    tab = drag_state["tab"]
                    if not drag_state["moved"]:
                        if tab == "market":
                            for rect, stock in market_row_rects:
                                if rect.collidepoint(pos):
                                    if asset_unlocked(stock):
                                        open_detail_modal(stock)
                                    else:
                                        show_toast("Locked asset", f"Reach Level {stock.get('unlock_level',1)} or the listed net worth.", "warning")
                                    break
                        elif tab == "portfolio":
                            for rect, stock in portfolio_row_rects:
                                if rect.collidepoint(pos):
                                    open_modal(stock, "sell")
                                    break
                    drag_state["active"] = False
                    drag_state["start_pos"] = None
                    drag_state["tab"] = None
                    drag_state["moved"] = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE and menu_open:
                    menu_open = False
                    continue
                if modal_stock:
                    if event.key == pygame.K_BACKSPACE:
                        qty_input_text = qty_input_text[:-1]
                    elif event.unicode.isdigit() or event.unicode == ".":
                        if event.unicode == "." and "." in qty_input_text:
                            pass
                        else:
                            qty_input_text += event.unicode
                    try:
                        modal_qty = max(0.01, round(float(qty_input_text), 4)) if qty_input_text not in ("", ".") else 0.01
                    except ValueError:
                        modal_qty = 0.01
                elif state.tab in ("market", "news") and state.market_search_active:
                    if event.key == pygame.K_ESCAPE:
                        state.market_search_active = False
                    elif event.key == pygame.K_RETURN:
                        matches = filtered_assets()
                        if matches:
                            select_asset_for_trade(matches[0])
                    else:
                        state.market_search = handle_text_event(event, state.market_search, 24)
                elif state.tab == "leaderboard":
                    state.friend_input_text = handle_text_event(event, state.friend_input_text, 18)
                    if event.key == pygame.K_RETURN:
                        send_friend_request(state.friend_input_text)
                elif state.tab == "parents":
                    handle_parents_key(event)
                elif state.tab == "settings" and state.settings_active_field:
                    attr = f"settings_{state.settings_active_field}"
                    setattr(state, attr, handle_text_event(event, getattr(state, attr), 25))

        if state.screen_mode == "signin":
            draw_signin_screen(screen)
        elif state.screen_mode == "google_form":
            draw_google_form_screen(screen)
        elif state.screen_mode == "reset_password":
            draw_reset_password(screen)
        elif state.screen_mode == "account_setup":
            draw_account_setup(screen)
            for p in particles:
                p.draw(screen)
        elif state.screen_mode == "avatar":
            draw_avatar_screen(screen)
        elif state.screen_mode == "tutorial":
            draw_tutorial_screen(screen)
            for p in particles:
                p.draw(screen)
            for ft in floating_texts:
                ft.draw(screen)
        else:
            draw_app_background(screen)
            draw_header(screen)
            draw_tab_animated(screen, state.tab)
            draw_tab_bar(screen)
            draw_avatar_speech_bubble(screen)
            draw_modal(screen)
            draw_detail_modal(screen)
            draw_alerts_sheet(screen)
            draw_menu_drawer(screen)
            if scam_game.get("open") and safe_button_action("scam detective screen", lambda: draw_scam_game(screen)) is False:
                scam_game["open"] = False
            if lesson_game.get("open") and safe_button_action("lesson screen", lambda: draw_lesson_game(screen)) is False:
                lesson_game["open"] = False
            if battle.get("open") and safe_button_action("battle screen", lambda: draw_battle(screen)) is False:
                battle["open"] = False
            draw_toast(screen)
            draw_trade_fx(screen)
            draw_chest_info(screen)
            draw_chest_opening(screen)
            if not tour["active"] and state.tutorial_completed and not getattr(state, "tour_completed", False):
                start_tour()
            elif not tour["active"] and state.tutorial_completed and getattr(state, "last_free_chest_day", "") != time.strftime("%Y-%m-%d"):
                maybe_grant_free_daily_chest()
            draw_tour(screen)
            if time_up["active"]:
                draw_time_up(screen)
            if time.time() < last_ui_error_until:
                err = pygame.Rect(18, 74, WIDTH - 36, 34)
                draw_rounded_rect(screen, err, C("RED"), radius=10)
                draw_text(screen, "Ledger recovered a UI action — your account is still safe.", font_tiny, C("CARD"), err.centerx, err.y + 8, align="center")
            for p in particles:
                p.draw(screen)
            for ft in floating_texts:
                ft.draw(screen)
            for orb in xp_orbs:
                orb.draw(screen)
            if screen_flash["life"] > 0 and screen_flash["color"]:
                blit_color_overlay(screen, screen_flash["color"], 70 * max(0.0, screen_flash["life"] / 0.22))

        present_frame()
        clock.tick(60)

    save_game()
    pygame.quit()
    sys.exit()


def main():
    """Run Ledger with a last-resort crash barrier.

    Pygame UI code has many independent drawing/button paths. If one path ever
    raises unexpectedly, the old version could terminate the entire Python
    process. This wrapper restarts the UI loop in-place, preserves the account
    and returns to a safe screen instead of kicking the player out.
    """
    global menu_open, modal_stock, detail_modal_stock
    start_update_check()
    while True:
        try:
            _main_loop()
            return
        except SystemExit:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            ui_error_guard("fatal UI loop", exc)
            try:
                # Keep the account/progress intact and restart from a stable
                # playable screen. If the exception happened during onboarding,
                # stay on that onboarding screen instead.
                menu_open = False
                modal_stock = None
                detail_modal_stock = None
                pygame.event.clear()
                present_frame()
                time.sleep(0.15)
            except Exception:
                # If even the recovery display is unavailable, rebuild the
                # pygame display once rather than exiting the process.
                try:
                    present_frame()
                except Exception:
                    time.sleep(0.25)


if __name__ == "__main__":
    main()
