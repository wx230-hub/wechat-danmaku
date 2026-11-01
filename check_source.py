
import sys, os, json, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from danmaku.source_wechat import WeChatSource, find_wechat_window
cfg = {}
try:
    cfg = json.load(open("config.json", encoding="utf-8"))
except Exception as e:
    print("no config:", e)
src = WeChatSource(cfg)
info = find_wechat_window(cfg.get("process", "weixin.exe"))
print("window:", info, flush=True)
rows, err = src.poll()
print("err:", err, flush=True)
for r in rows:
    print(r["y"], "|", r["title"], "|", r["preview"], "|", r["time"], flush=True)
