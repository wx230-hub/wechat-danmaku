import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from danmaku.source_wechat import WeChatSource

src = WeChatSource({}, log=lambda m: None)
def R(*rows):
    return [{"title": t, "preview": p, "time": "", "y": i * 60} for i, (t, p) in enumerate(rows)]

base = R(("方舟港789", "王天昊:彻底疯狂"), ("罗德岛", "凯尔希信仰玩家"), ("17班班委群", "语文科代:[文件]"))
print("1 first poll (no emit):", src.diff(base, emit_start=False))
print("2 same rows:", src.diff(base))
same_noisy = R(("方舟港789", "王天昊:彻底疯狂"), ("罗德岛", "凯尔希信仰玩家."), ("17班班委群", "语文科代:[文件]"))
print("3 OCR noise (trailing dot):", src.diff(same_noisy))
changed = R(("方舟港789", "王天昊:彻底疯狂"), ("罗德岛", "凯尔希信仰玩家"), ("17班班委群", "语文科代:收到收到"))
print("4 preview changed:", src.diff(changed))
newbie = R(("方舟港789", "王天昊:彻底疯狂"), ("罗德岛", "凯尔希信仰玩家"), ("17班班委群", "语文科代:收到收到"), ("新会话", "你好呀"))
print("5 new session appears:", src.diff(newbie))
print("6 emit_on_start on empty state:")
src2 = WeChatSource({}, log=lambda m: None)
print("   ", src2.diff(base, emit_start=True))
