# -*- coding: utf-8 -*-
"""微信消息弹幕 —— 启动入口。

用法:
    pythonw main.py              # 正常运行（无控制台）
    python  main.py              # 带控制台，方便看日志
    python  main.py --demo       # 演示模式，用假消息验证弹幕效果
    python  main.py --check      # 只做一次抓取+识别，打印解析结果后退出
"""
import argparse
import ctypes
import json
import os
import queue
import sys
import threading
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from danmaku.overlay import DanmakuOverlay  # noqa: E402
from danmaku.source_wechat import WeChatSource  # noqa: E402

DEFAULT_CONFIG = {
    "process": "weixin.exe",
    "poll_interval": 1.5,
    "emit_on_start": False,
    "sidebar_box_rel": [0.04, 0.07, 0.23, 1.0],
    "font_size": 26,
    "stroke_width": 2,
    "speed": 130.0,
    "min_gap": 60,
    "lane_gap": 16,
    "lane_top": 70,
    "lane_area_ratio": 0.62,
    "max_lanes": 14,
    "opacity": 1.0,
    "palette": ["#ffffff", "#9ee7ff", "#ffd88a", "#b7ffb0", "#ffb3d1", "#d9c2ff"],
    "format": "{title}  {preview}",
    "blacklist": ["文件传输助手", "微信团队", "服务通知"],
    "log_file": "danmaku.log",
}

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def load_config():
    path = os.path.join(HERE, "config.json")
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print("读取 config.json 失败: %r" % (e,))
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


class Logger:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def __call__(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        with self.lock:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass
        try:
            print(line)
        except Exception:
            pass


class HotkeyWatcher(threading.Thread):
    """Ctrl+Alt+Q 退出，Ctrl+Alt+P 暂停/恢复。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.events = []
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32 = user32
        user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("Q"))
        user32.RegisterHotKey(None, 2, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("P"))

    def run(self):
        msg = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.events.append(int(msg.wParam))


def color_for(title, palette):
    return palette[sum(ord(c) for c in title) % len(palette)]


def run_demo(cfg, overlay):
    samples = [
        ("方舟港789", "王天昊:彻底疯狂"),
        ("明鉴-横沥地铁站接驳车群", "莫萱的芹意:#接龙 11月1号返校"),
        ("这91的漩涡", "邱艺琳:[链接] 盘点人生搞笑"),
        ("17班班委群", "语文科代 曾梓盟:[文件] 第三单元"),
        ("罗德岛", "凯尔希信仰玩家:这波稳了"),
        ("蒋有权", "收到收到"),
    ]
    for i, (t, p) in enumerate(samples):
        overlay.root.after(300 + i * 620, lambda t=t, p=p: overlay.push(
            cfg["format"].format(title=t, preview=p), color_for(t, cfg["palette"])))
    return samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="演示模式，用假消息验证弹幕效果")
    ap.add_argument("--check", action="store_true", help="只做一次抓取+识别并打印结果")
    ap.add_argument("--announce", action="store_true", help="启动时把当前会话列表播一遍")
    args = ap.parse_args()

    cfg = load_config()
    if args.announce:
        cfg["emit_on_start"] = True

    if not args.check:
        # 单实例：避免重复启动叠加多个弹幕窗口、重复跑 OCR
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "WeChatDanmakuOverlay")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            print("弹幕已经在运行了（若看不到窗口，按 Ctrl+Alt+Q 退出旧的再启动）")
            return 0
    log = Logger(os.path.join(HERE, cfg["log_file"]))

    if args.check:
        src = WeChatSource(cfg, log)
        rows, err = src.poll()
        if err:
            print("错误:", err)
            return 1
        print("识别到 %d 个会话:" % len(rows))
        for r in rows:
            print("  %-28s | %-6s | %s" % (r["title"], r["time"], r["preview"]))
        return 0

    overlay = DanmakuOverlay(cfg)
    src = WeChatSource(cfg, log)
    log("弹幕窗口已就绪 hwnd=%s 轨道=%d" % (overlay.hwnd, overlay.lane_count))

    pending = queue.Queue()

    if args.demo:
        run_demo(cfg, overlay)
    else:
        def on_message(title, preview):
            if any(b and b in title for b in cfg.get("blacklist", [])):
                return
            text = cfg["format"].format(title=title, preview=preview).strip()
            if not text:
                return
            log("新消息: " + text)
            # 采集线程 -> Tk 线程，用队列传递，避免跨线程操作 Tk 控件
            pending.put((text, color_for(title, cfg["palette"])))

        def on_status(msg):
            pass

        src.start(on_message, on_status)

        def pump_messages():
            while True:
                try:
                    text, color = pending.get_nowait()
                except queue.Empty:
                    break
                overlay.push(text, color)
            overlay.root.after(120, pump_messages)

        overlay.root.after(120, pump_messages)

    watcher = HotkeyWatcher()
    watcher.start()

    def pump_hotkeys():
        while watcher.events:
            key = watcher.events.pop(0)
            if key == 1:
                log("收到退出热键")
                src.stop()
                overlay.shutdown()
                return
            if key == 2:
                src.paused = not src.paused
                log("暂停" if src.paused else "恢复")
        overlay.root.after(200, pump_hotkeys)

    overlay.root.after(500, pump_hotkeys)
    try:
        overlay.run()
    finally:
        src.stop()
        log("退出")


if __name__ == "__main__":
    sys.exit(main() or 0)
