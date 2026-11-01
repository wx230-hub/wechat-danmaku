# 微信消息弹幕（WeChat Danmaku）

把微信**最新消息**以 B 站弹幕的形式打在屏幕上：白色（或彩色）粗体字 + 黑色描边，
从屏幕右侧向左飘过，**置顶显示、鼠标可穿透**，多条消息分布在不同纵坐标（轨道）上。

基于 Python + tkinter 分层窗口 + RapidOCR，不修改微信、不注入进程、不需要数据库密钥。

---

## 快速开始

1. 打开微信并登录（**主窗口不要最小化**，最小化时抓不到内容）。
2. 双击 `启动弹幕.bat`（也可以在命令行运行 `python main.py` 看日志）。
3. 有人发来新消息，屏幕上就会飘出对应弹幕。

退出：**Ctrl + Alt + Q**；暂停/恢复：**Ctrl + Alt + P**。

其他命令：

```bat
python main.py --demo        :: 演示模式，用假消息看效果
python main.py --check       :: 只抓一次屏幕并打印识别出的会话列表（排查用）
python main.py --announce    :: 启动时先把当前会话列表整套播一遍
```

## 环境依赖

```bat
pip install pillow rapidocr-onnxruntime onnxruntime numpy
```

（已在 Python 3.14 + `rapidocr-onnxruntime 1.2.3` + `onnxruntime 1.31.1` 上验证通过。）

## 配置（config.json）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `process` | `weixin.exe` | 微信进程名 |
| `poll_interval` | `1.5` | 轮询间隔（秒）。一次抓取+识别约 2 秒，不建议小于 2 |
| `emit_on_start` | `false` | 启动时是否把当前列表播一遍 |
| `sidebar_box_rel` | `[0.04,0.07,0.23,1.0]` | 会话列表在微信窗口内的相对位置（左/上/右/下） |
| `ocr_scale` | `2.0` | 识别前放大倍数，2.0 对小字更准 |
| `auto_restore` | `false` | 微信最小化时是否临时还原窗口抓取再最小化 |
| `font_size` | `26` | 弹幕字号 |
| `stroke_width` | `2` | 描边宽度 |
| `speed` | `130` | 滚动速度（像素/秒） |
| `lane_gap` / `lane_top` | `16` / `70` | 轨道间距 / 顶部留白 |
| `lane_area_ratio` | `0.62` | 弹幕区域占屏幕高度比例 |
| `max_lanes` | `14` | 最多轨道数（= 同时可见的不同纵坐标条数） |
| `opacity` | `1.0` | 整体不透明度 |
| `palette` | 6 色 | 按会话名散列取色 |
| `format` | `{title}  {preview}` | 弹幕文本模板 |
| `blacklist` | 文件传输助手等 | 会话名命中则忽略 |
| `log_file` | `danmaku.log` | 日志（记录每条弹出的消息） |

## 原理

1. **抓取**：`PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` 直接把微信窗口画到内存位图，
   不需要窗口在前台、不抢焦点，被别的窗口盖住也能抓。
2. **识别**：裁出左侧会话列表（头像右侧的 会话名 + 最后一条消息预览 + 时间），
   放大 2 倍后交给 RapidOCR（PP-OCRv4 onnx）识别中文小字。
3. **比对**：用 `difflib` 按相似度匹配会话名（阈值 0.70），预览文本相似度 < 0.90 即判定为“有新消息”。
4. **显示**：一个 1920×1080 无边框 `-topmost` 的 tkinter 窗口，设 `-transparentcolor` 抠掉背景色，
   Canvas 上逐帧左移渲染的 PIL 图片（含描边）；面板加 `WS_EX_TRANSPARENT` 让鼠标点击穿透。

## 已知限制

- 微信主窗口**最小化时无法抓取**（系统只返回 160×28 的空壳）；可打开 `auto_restore` 让工具临时还原窗口。
- 只读取会话列表的“最后一条消息预览”，因此：
  - 同一会话连发多条时只会显示最新的一条；
  - 图片/表情/语音消息只能显示为 `[图片]`、`[动画表情]` 之类的占位文本（或识别不到）。
- OCR 偶尔认错字，属于识别层误差。
- 屏幕分辨率变化后请调整 `sidebar_box_rel`（`python main.py --check` 可验证识别结果）。
- 只在 Windows 上可用（依赖 Win32 API）。

---

## 许可证

GPL-3.0，详见 [LICENSE](LICENSE)。
