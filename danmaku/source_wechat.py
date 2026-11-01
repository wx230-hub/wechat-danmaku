# -*- coding: utf-8 -*-
"""从微信窗口抓取会话列表最新消息（PrintWindow + RapidOCR）。"""
import ctypes
import difflib
import re
import threading
import time
from ctypes import wintypes

from PIL import Image

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]


def _pids_by_name(name):
    """通过 QueryFullProcessImageName 找出指定进程名的 pid 列表。"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    out = set()
    arr = (wintypes.DWORD * 2048)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return out
    n = needed.value // ctypes.sizeof(wintypes.DWORD)
    buf = ctypes.create_unicode_buffer(1024)
    for i in range(n):
        pid = arr[i]
        if not pid:
            continue
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            continue
        try:
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                if buf.value.lower().endswith(name):
                    out.add(int(pid))
        finally:
            kernel32.CloseHandle(h)
    return out


def find_wechat_window(exe_name="weixin.exe"):
    """找到微信主窗口（可能是最小化状态）。"""
    pids = _pids_by_name(exe_name)
    if not pids:
        return None
    results = []

    def cb(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        cn = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cn, 256)
        cls = cn.value
        if "TrayIcon" in cls or not cls.startswith("Qt5"):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        minimized = rect.left <= -30000 or w <= 0 or h <= 0
        results.append({
            "hwnd": hwnd, "class": cls,
            "rect": (rect.left, rect.top, rect.right, rect.bottom),
            "minimized": minimized, "area": 0 if minimized else w * h,
        })
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not results:
        return None
    results.sort(key=lambda r: (not r["minimized"], r["area"]), reverse=True)
    best = results[0]
    best.pop("area", None)
    return best


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BitmapCapture:
    @staticmethod
    def grab(hwnd):
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        old = gdi32.SelectObject(hdc_mem, hbm)
        try:
            ok = user32.PrintWindow(hwnd, hdc_mem, 2)
            if not ok:
                return None
            bi = BITMAPINFO()
            bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bi.bmiHeader.biWidth = w
            bi.bmiHeader.biHeight = -h
            bi.bmiHeader.biPlanes = 1
            bi.bmiHeader.biBitCount = 32
            bi.bmiHeader.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            got = gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bi), 0)
            if got != h:
                return None
            return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
        finally:
            if old:
                gdi32.SelectObject(hdc_mem, old)
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)


TRAIL = re.compile(r"[.\u3002\uff0e\u2026]\u200b*$")


def _norm(s):
    s = re.sub(r"\(\d+\)$", "", s.strip())
    s = re.sub(r"\s+", "", s)
    return s


def _clean(s):
    s = s.strip()
    s = TRAIL.sub("", s)
    s = s.replace("\u3000", " ")
    return s.strip()


def parse_rows(boxes, scale=1.0):
    """boxes: [{'x','y','w','h','t'}] 相对侧栏裁剪图；返回 [{title, preview, time, y}]

    scale: OCR 前把裁剪图放大的倍数，行间距阈值需要同步放大。
    """
    if not boxes:
        return []
    scale = float(scale) or 1.0
    gap_max = 12.0 * scale
    maxx = max(b["x"] + b["w"] for b in boxes)
    left = [b for b in boxes if b["x"] < maxx * 0.74]
    right = [b for b in boxes if b["x"] >= maxx * 0.74]
    left.sort(key=lambda b: b["y"])
    rows = []
    cur = None
    for b in left:
        if cur is None or b["y"] - cur["bottom"] > gap_max:
            cur = {"title": b["t"], "preview": "", "y": b["y"], "bottom": b["y"] + b["h"]}
            rows.append(cur)
        else:
            cur["preview"] = (cur["preview"] + b["t"]) if cur["preview"] else b["t"]
            cur["bottom"] = max(cur["bottom"], b["y"] + b["h"])
    for r in rows:
        r["time"] = ""
        for b in right:
            if abs((b["y"] + b["h"] / 2) - (r["y"] + 12 * scale)) < 22 * scale:
                r["time"] = b["t"]
                break
        r["title"] = _clean(r["title"])
        r["preview"] = _clean(r["preview"])
    return [r for r in rows if r["title"]]


class WeChatSource:
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.engine = None
        self.known = {}  # key -> preview
        self.started = False
        self.paused = False
        self._stop = threading.Event()
        self.thread = None

    def _ensure_engine(self):
        if self.engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.engine = RapidOCR()
        return self.engine

    def snapshot(self):
        info = find_wechat_window(self.cfg.get("process", "weixin.exe"))
        if not info:
            return None, "未找到微信窗口，请先启动微信"
        restored = False
        if info["minimized"]:
            if not self.cfg.get("auto_restore", False):
                return None, "微信窗口已最小化，请还原窗口（或在 config.json 打开 auto_restore）"
            user32.ShowWindow(info["hwnd"], 4)  # SW_SHOWNOACTIVATE
            time.sleep(0.35)
            restored = True
        try:
            img = BitmapCapture.grab(info["hwnd"])
            if img is None:
                return None, "抓取微信窗口失败"
            w, h = img.size
            if w < 400 or h < 300:
                return None, "微信窗口尺寸异常（可能已最小化）"
            if img.convert("L").getextrema() == (0, 0):
                return None, "微信窗口内容为空"
        finally:
            if restored and not self.cfg.get("keep_restored", False):
                user32.ShowWindow(info["hwnd"], 6)  # SW_MINIMIZE
        x0, y0, x1, y1 = self.cfg.get("sidebar_box_rel", [0.04, 0.07, 0.23, 1.0])
        box = (int(w * x0), int(h * y0), int(w * x1), int(h * y1))
        return img.crop(box), None

    def poll(self):
        crop, err = self.snapshot()
        if err:
            return [], err
        engine = self._ensure_engine()
        import numpy as np
        scale = float(self.cfg.get("ocr_scale", 2.0))
        if scale and abs(scale - 1.0) > 0.01:
            crop = crop.resize((int(crop.width * scale), int(crop.height * scale)),
                               Image.LANCZOS)
        arr = np.ascontiguousarray(np.array(crop.convert("RGB"))[:, :, ::-1])
        res, _ = engine(arr)
        boxes = []
        for item in res or []:
            pts, text, score = item[0], item[1], item[2]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            boxes.append({
                "x": min(xs), "y": min(ys),
                "w": max(xs) - min(xs), "h": max(ys) - min(ys),
                "t": text, "s": float(score),
            })
        return parse_rows(boxes, scale), None

    def diff(self, rows, emit_start=False):
        """对比上一次，返回新消息列表 [(title, preview)]"""
        events = []
        matched = {}
        old_keys = list(self.known.keys())
        for r in rows:
            key = _norm(r["title"])
            best, best_ratio = None, 0.0
            for k in old_keys:
                ratio = difflib.SequenceMatcher(None, key, k).ratio()
                if ratio > best_ratio:
                    best, best_ratio = k, ratio
            if best is not None and best_ratio >= 0.70:
                matched[key] = best
                old_preview = self.known.pop(best)
                new_preview = r["preview"]
                if new_preview and old_preview and \
                        difflib.SequenceMatcher(None, new_preview, old_preview).ratio() < 0.90:
                    events.append((r["title"], new_preview))
                elif new_preview and not old_preview:
                    events.append((r["title"], new_preview))
                self.known[key] = new_preview
            else:
                self.known[key] = r["preview"]
                if emit_start and r["preview"]:
                    events.append((r["title"], r["preview"]))
        # 消失的会话（被顶出列表）从状态里删除
        for k in list(self.known.keys()):
            if k not in matched and k not in {_norm(r["title"]) for r in rows}:
                self.known.pop(k, None)
        return events

    def start(self, on_message, on_status=None):
        def loop():
            err_count = 0
            while not self._stop.is_set():
                try:
                    if self.paused:
                        time.sleep(0.5)
                        continue
                    rows, err = self.poll()
                    if err:
                        err_count += 1
                        if err_count in (1, 10) or err_count % 60 == 0:
                            self.log("source: " + err)
                            if on_status:
                                on_status(err)
                    else:
                        err_count = 0
                        first = not self.started
                        if first:
                            self.started = True
                        for title, preview in self.diff(rows, emit_start=self.cfg.get("emit_on_start", False)):
                            on_message(title, preview)
                except Exception as e:  # noqa
                    self.log("source error: %r" % (e,))
                    time.sleep(1.0)
                self._stop.wait(float(self.cfg.get("poll_interval", 1.5)))

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
