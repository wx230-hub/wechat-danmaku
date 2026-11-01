# -*- coding: utf-8 -*-
"""B 站风格弹幕覆盖层：全屏透明、置顶、鼠标穿透、右->左多轨道。"""
import ctypes
import queue
import random
import time
import tkinter as tk
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFont, ImageTk

TRANSPARENT_KEY = "#010203"  # 用作色键，正常文字里不会出现


def _load_font(size, bold=True):
    cands = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


class DanmakuOverlay:
    def __init__(self, cfg):
        self.cfg = cfg
        self.queue = queue.Queue()
        self.items = {}  # item_id -> dict
        self.photo_refs = {}
        self.lanes = []
        self._img_cache = {}

        self.root = tk.Tk()
        self.root.title("WeChat Danmaku")
        self.root.overrideredirect(True)
        sw0 = self.root.winfo_screenwidth()
        sh0 = self.root.winfo_screenheight()
        self.root.geometry("%dx%d+0+0" % (sw0, sh0))
        self.root.attributes("-topmost", True)
        self.opacity = float(cfg.get("opacity", 1.0))
        self.root.attributes("-alpha", self.opacity)
        self.transparent = bool(cfg.get("transparent", True))
        if self.transparent:
            try:
                self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
            except tk.TclError:
                self.transparent = False

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.width, self.height = sw, sh
        self.root.geometry("%dx%d+0+0" % (sw, sh))
        self.bg_color = str(cfg.get("bg_color", TRANSPARENT_KEY))
        self.root.configure(bg=self.bg_color)

        self.canvas = tk.Canvas(
            self.root, width=sw, height=sh, bg=self.bg_color,
            highlightthickness=0, bd=0,
        )
        self.canvas.pack()

        self.font_size = int(cfg.get("font_size", 26))
        self.font = _load_font(self.font_size, True)
        self.stroke_width = int(cfg.get("stroke_width", 2))
        self.speed = float(cfg.get("speed", 130.0))  # px/s
        self.gap = int(cfg.get("min_gap", 60))
        self.lane_height = int(self.font_size + cfg.get("lane_gap", 16))
        ratio = float(cfg.get("lane_area_ratio", 0.62))
        max_lanes = max(1, int((sh * ratio) // self.lane_height))
        self.lane_count = min(int(cfg.get("max_lanes", 14)), max_lanes)
        self.lane_top = int(cfg.get("lane_top", 70))
        for i in range(self.lane_count):
            self.lanes.append({
                "y": self.lane_top + i * self.lane_height,
                "edge": 0.0,  # 该轨道上最右侧弹幕的右边界 x
            })

        if cfg.get("click_through", True):
            self._make_click_through()
        else:
            self.hwnd = self.root.winfo_id()
        self.root.update_idletasks()
        self.running = True
        self._last = time.time()
        self._topmost_tick()

    # ---------- 窗口属性 ----------
    def _make_click_through(self):
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = self.root.winfo_id()
        # 取顶层 hwnd（overrideredirect 下 winfo_id 即顶层，仍做一次保险）
        parent = user32.GetParent(hwnd)
        if parent:
            hwnd = parent
        get_l = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_l = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        style = get_l(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
        # 注意：不要在这里显式加 WS_EX_LAYERED —— 给已映射窗口动态加该位会把
        # 分层属性重置为「完全透明」，导致窗口看不见。透明已由 -transparentcolor /
        # -alpha 负责，这里只补点击穿透相关的样式位。
        style |= WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        set_l(hwnd, GWL_EXSTYLE, style)
        self.hwnd = hwnd
        # 改样式后重新压一遍分层属性与置顶，确保不被重置
        if self.transparent:
            try:
                self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
            except tk.TclError:
                pass
        try:
            self.root.attributes("-alpha", float(self.opacity))
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass

    def _topmost_tick(self):
        try:
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception:
            pass
        if self.running:
            self.root.after(3000, self._topmost_tick)

    # ---------- 文本渲染 ----------
    def _render(self, text, color):
        key = (text, color)
        cached = self._img_cache.get(key)
        if cached is not None:
            return cached
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        try:
            bbox = probe.textbbox((0, 0), text, font=self.font, stroke_width=self.stroke_width)
        except Exception:
            bbox = (0, 0, self.font_size * len(text), self.font_size)
        w = max(1, bbox[2] - bbox[0] + 8)
        h = max(1, bbox[3] - bbox[1] + 8)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((4 - bbox[0], 4 - bbox[1]), text, font=self.font,
               fill=color, stroke_width=self.stroke_width, stroke_fill=(0, 0, 0, 255))
        if len(self._img_cache) > 300:
            self._img_cache.clear()
        self._img_cache[key] = img
        return img

    # ---------- 对外接口 ----------
    def push(self, text, color=None):
        self.queue.put({"text": str(text), "color": color})

    def shutdown(self):
        self.running = False
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    # ---------- 主循环 ----------
    def _spawn(self, text, color):
        if not text.strip():
            return
        candidates = [i for i, ln in enumerate(self.lanes) if ln["edge"] <= self.width - self.gap]
        if not candidates:
            return False
        lane_idx = random.choice(candidates[: max(1, len(candidates) // 2)] or candidates)
        lane = self.lanes[lane_idx]
        img = self._render(text, color or (255, 255, 255, 255))
        ph = ImageTk.PhotoImage(img)
        x = float(self.width + 10)
        y = lane["y"]
        item = self.canvas.create_image(x, y, image=ph, anchor="nw")
        self.photo_refs[item] = ph
        self.items[item] = {
            "x": x, "y": y, "w": img.width, "lane": lane_idx,
            "born": time.time(),
        }
        lane["edge"] = x + img.width
        return True

    def _tick(self):
        if not self.running:
            return
        now = time.time()
        dt = min(0.1, now - self._last)
        self._last = now
        # 取出待显示消息
        try:
            while True:
                msg = self.queue.get_nowait()
                if not self._spawn(msg["text"], msg["color"]):
                    self.queue.put(msg)
                    break
        except queue.Empty:
            pass
        # 平移
        dx = self.speed * dt
        dead = []
        edge = [0.0] * len(self.lanes)
        for item, st in self.items.items():
            st["x"] -= dx
            self.canvas.move(item, -dx, 0)
            right = st["x"] + st["w"]
            if right > edge[st["lane"]]:
                edge[st["lane"]] = right
            if right < -20:
                dead.append(item)
        for item in dead:
            self.canvas.delete(item)
            self.photo_refs.pop(item, None)
            self.items.pop(item, None)
        for i, ln in enumerate(self.lanes):
            ln["edge"] = edge[i]
        self.root.after(int(1000 / 60), self._tick)

    def run(self):
        self.root.after(16, self._tick)
        self.root.mainloop()
