"""
TBH 塔斯克巴·英雄 — 自動效率計算機
需求: pip install pywin32 Pillow pytesseract mss numpy
另需安裝 Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki
"""

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import re
import json
import os
import sys
from datetime import datetime

# 打包成 exe 後 __file__ 在 bundle 內，可寫檔案要放在 exe 旁邊
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH  = os.path.join(BASE_DIR, "tbh_config.json")
COMPARE_PATH = os.path.join(BASE_DIR, "tbh_compare.json")

DEPS_OK = True
MISSING = []
try:
    import win32gui
    import win32api
except ImportError:
    MISSING.append("pywin32"); DEPS_OK = False
try:
    from PIL import Image, ImageEnhance, ImageTk
except ImportError:
    MISSING.append("Pillow"); DEPS_OK = False
try:
    import pytesseract
except ImportError:
    MISSING.append("pytesseract"); DEPS_OK = False
# 讓 comtypes 在記憶體內產生 COM 模組，避免打包後寫磁碟失敗（dxcam 依賴）
try:
    import comtypes.client
    comtypes.client.gen_dir = None
except Exception:
    pass
try:
    import dxcam
except ImportError:
    MISSING.append("dxcam"); DEPS_OK = False
try:
    import numpy as np
except ImportError:
    MISSING.append("numpy"); DEPS_OK = False

# dxcam 相機實例（全域共用，避免重複建立）
_dx_camera = None

def get_dx_camera():
    global _dx_camera
    if _dx_camera is None:
        # 用 numpy backend，避免依賴龐大的 cv2（打包更小更穩）
        _dx_camera = dxcam.create(output_color="RGB", processor_backend="numpy")
    return _dx_camera

def _find_tesseract():
    """依序尋找 Tesseract：打包附帶 → 常見安裝路徑 → PATH"""
    candidates = [
        os.path.join(BASE_DIR, "Tesseract-OCR", "tesseract.exe"),  # 打包一起附帶
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "tesseract"  # 退而求其次：靠系統 PATH

TESSERACT_PATH = _find_tesseract()

def _setup_tessdata():
    """設定 TESSDATA_PREFIX。tesseract.exe 無法讀含中文的路徑，
    若 tessdata 路徑含非英數字元，複製到英數路徑（AppData）再指過去。"""
    if not (os.path.isabs(TESSERACT_PATH) and os.path.exists(TESSERACT_PATH)):
        return  # 用系統 PATH 的 tesseract，交由系統處理
    src = os.path.join(os.path.dirname(TESSERACT_PATH), "tessdata")
    if not os.path.isdir(src):
        return
    if src.isascii():
        os.environ["TESSDATA_PREFIX"] = src
        return
    # 路徑含中文 → 複製到英數路徑
    import shutil
    import tempfile
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    dst = os.path.join(base, "TBHCalc", "tessdata")
    try:
        if not os.path.exists(os.path.join(dst, "eng.traineddata")):
            if os.path.exists(dst):
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        os.environ["TESSDATA_PREFIX"] = dst if dst.isascii() else src
    except Exception:
        os.environ["TESSDATA_PREFIX"] = src

_setup_tessdata()

GAME_WINDOW_KEYWORDS = ["TaskBarHero", "塔斯克巴", "Taskbar Heroes"]
# 排除這些視窗類別（檔案總管等非遊戲視窗）
GAME_WINDOW_EXCLUDE_CLASSES = ["CabinetWClass", "ExploreWClass", "Progman", "WorkerW"]

DEFAULT_REGIONS = {
    "gold": {"x": 0.05, "y": 0.02, "w": 0.25, "h": 0.07},
    "exp":  {"x": 0.05, "y": 0.88, "w": 0.25, "h": 0.07},
}

FONT    = ("Microsoft JhengHei UI", 9)
FONT_SM = ("Microsoft JhengHei UI", 8)
FONT_LG = ("Microsoft JhengHei UI", 10)
FONT_TL = ("Microsoft JhengHei UI", 12, "bold")


# ════════════════════════════════════════════════════════════════
#  設定檔
# ════════════════════════════════════════════════════════════════

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

def load_compare():
    if os.path.exists(COMPARE_PATH):
        try:
            with open(COMPARE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_compare(rows: list):
    with open(COMPARE_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


# ════════════════════════════════════════════════════════════════
#  工具函式
# ════════════════════════════════════════════════════════════════

def find_game_window():
    result = []
    def enum_cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        # 排除檔案總管等非遊戲視窗
        cls = win32gui.GetClassName(hwnd)
        if cls in GAME_WINDOW_EXCLUDE_CLASSES:
            return
        for kw in GAME_WINDOW_KEYWORDS:
            if kw.lower() in title.lower():
                result.append((hwnd, title))
    win32gui.EnumWindows(enum_cb, None)
    return result


def capture_region(hwnd, rel):
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w = right - left
    h = bottom - top
    x1 = int(left + rel["x"] * w)
    y1 = int(top  + rel["y"] * h)
    x2 = x1 + int(rel["w"] * w)
    y2 = y1 + int(rel["h"] * h)
    region = (x1, y1, x2, y2)
    # grab() 在畫面無更新時回傳 None，重試最多 5 次
    cam = get_dx_camera()
    for _ in range(5):
        frame = cam.grab(region=region)
        if frame is not None:
            return Image.fromarray(frame)
        time.sleep(0.05)
    # 最後手段：全螢幕截圖後裁切
    full = cam.grab()
    if full is not None:
        return Image.fromarray(full).crop(region)
    raise RuntimeError("dxcam 無法截取畫面，請確認遊戲視窗可見")


def preprocess_for_ocr(img):
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    # 分離 RGB 通道，取最亮的通道（金色數字在 R/G 通道最亮）
    arr = np.array(img).astype(np.float32)
    bright = np.max(arr, axis=2)  # 取 R/G/B 最大值
    # 自適應閾值：用畫面最亮值的 55% 當門檻
    thresh = max(bright.max() * 0.55, 80)
    binary = np.where(bright > thresh, 255, 0).astype(np.uint8)
    return Image.fromarray(binary)


def ocr_number(img):
    processed = preprocess_for_ocr(img)
    cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,."
    text = pytesseract.image_to_string(processed, config=cfg).strip()
    text = text.replace(",", "").replace(" ", "")
    m = re.search(r"\d+\.?\d*", text)
    return float(m.group()) if m else None


def ocr_number_debug(img):
    """回傳 (數值或None, 原始OCR文字, 預處理後影像)，供除錯用"""
    processed = preprocess_for_ocr(img)
    cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,."
    text = pytesseract.image_to_string(processed, config=cfg).strip()
    clean = text.replace(",", "").replace(" ", "")
    m = re.search(r"\d+\.?\d*", clean)
    val = float(m.group()) if m else None
    return val, text, processed


def ocr_exp_pair(img):
    """讀取「目前經驗 / 升級需求」格式，回傳 (current, required, 原始文字)"""
    processed = preprocess_for_ocr(img)
    cfg = "--psm 7 -c tessedit_char_whitelist=0123456789,/ "
    text = pytesseract.image_to_string(processed, config=cfg).strip()
    # 移除逗號與空白，只留數字與斜線
    clean = re.sub(r"[^\d/]", "", text)
    parts = [p for p in clean.split("/") if p]
    cur = req = None
    if len(parts) == 1:
        cur = float(parts[0])
    elif len(parts) >= 2:
        # 最後一段為升級需求，其餘合併為目前經驗
        # （修正 OCR 在經驗數字中誤插的斜線，如 2/79147 → 279147）
        req = float(parts[-1])
        cur = float("".join(parts[:-1]))
    return cur, req, text


def fmt_num(n):
    if n >= 1:
        return f"{int(n):,}"
    return f"{n:.2f}"


# ════════════════════════════════════════════════════════════════
#  拖曳選取覆蓋層
# ════════════════════════════════════════════════════════════════

class RegionPicker(tk.Toplevel):
    """
    全螢幕覆蓋層，讓使用者拖曳選取區域。
    用 win32api.GetCursorPos() 取實體像素座標，和 dxcam / GetWindowRect 座標系一致。
    """
    def __init__(self, master, hwnd, callback):
        super().__init__(master)
        self.hwnd = hwnd
        self.callback = callback
        # 起點/終點用實體座標記錄
        self.sx = self.sy = self.ex = self.ey = 0
        self._rect_id = None
        self._pressing = False

        # dxcam 截全螢幕（實體像素）
        cam = get_dx_camera()
        frame = None
        for _ in range(10):
            frame = cam.grab()
            if frame is not None:
                break
            time.sleep(0.05)
        if frame is None:
            self.destroy()
            messagebox.showerror("錯誤", "截圖失敗，請確認遊戲視窗可見")
            return
        self._screen_img = Image.fromarray(frame)  # 實體像素大小
        pw, ph = self._screen_img.size

        # 覆蓋層顯示尺寸 = 實體像素（DPI Aware 模式下 geometry 是實體像素）
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="black")
        self.geometry(f"{pw}x{ph}+0+0")

        self._tk_img = ImageTk.PhotoImage(self._screen_img)
        self.canvas = tk.Canvas(self, cursor="crosshair",
                                highlightthickness=0, bg="black",
                                width=pw, height=ph)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_img)
        self.canvas.create_rectangle(0, 0, pw, ph,
                                     fill="black", stipple="gray50", outline="")
        self.canvas.create_text(pw // 2, 60,
                                text="拖曳選取區域，放開滑鼠確認　|　Esc 取消",
                                fill="white", font=("Microsoft JhengHei UI", 20))

        # 遊戲視窗實體座標
        self._win_rect = win32gui.GetWindowRect(hwnd)

        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda _: self.destroy())

    def _cursor_pos(self):
        """直接向 Windows 取實體像素座標，不用 tkinter 的 e.x/e.y"""
        return win32api.GetCursorPos()

    def _on_press(self, e):
        self.sx, self.sy = self._cursor_pos()
        self._pressing = True

    def _on_drag(self, e):
        if not self._pressing:
            return
        cx, cy = self._cursor_pos()
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            self.sx, self.sy, cx, cy,
            outline="#f5c842", width=2, fill="")

    def _on_release(self, e):
        if not self._pressing:
            return
        self._pressing = False
        self.ex, self.ey = self._cursor_pos()

        x1, y1 = min(self.sx, self.ex), min(self.sy, self.ey)
        x2, y2 = max(self.sx, self.ex), max(self.sy, self.ey)
        if x2 - x1 < 5 or y2 - y1 < 5:
            self.destroy()
            return

        # 全部是實體像素，直接換算相對比例
        wl, wt, wr, wb = self._win_rect
        ww = wr - wl
        wh = wb - wt
        rel = {
            "x": (x1 - wl) / ww,
            "y": (y1 - wt) / wh,
            "w": (x2 - x1) / ww,
            "h": (y2 - y1) / wh,
        }
        self.destroy()
        self.callback(rel)


# ════════════════════════════════════════════════════════════════
#  主應用程式
# ════════════════════════════════════════════════════════════════

class TBHApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TBH 效率計算機")
        self.geometry("560x860")
        self.resizable(True, True)
        self.configure(bg="#1a1208")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.hwnd = None
        self.tracking = False
        # 全程平均：保存整段紀錄的取樣 (time, value)
        self._hist = {"gold": [], "exp": []}
        self.compare_rows = load_compare()
        self._sort_col = None
        self._sort_reverse = False
        self._render_rows = []   # 目前顯示順序（供移除對應）
        self._track_start = None
        self._timer_job = None

        cfg = load_config()
        # 截圖區域：優先用已儲存的，沒有才用預設
        self.regions = {k: dict(v) for k, v in DEFAULT_REGIONS.items()}
        for k, v in cfg.get("regions", {}).items():
            if k in self.regions:
                self.regions[k] = v
        self._live_gold = None
        self._live_exp  = None
        self._exp_required = None   # 升級所需經驗（OCR 的 / 後數字）

        if DEPS_OK:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

        self._build_ui()
        self._render_compare()   # 載入已儲存的比較資料
        self._refresh_windows()

        # 區域設定的即時 OCR 預覽（背景執行）
        if DEPS_OK:
            threading.Thread(target=self._region_preview_loop, daemon=True).start()

    # ── UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#1a1208", foreground="#e8d5a0",
                        fieldbackground="#2a1e0e", font=FONT)
        style.configure("TNotebook", background="#1a1208", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2a1e0e", foreground="#b09060",
                        padding=[10, 4], font=FONT)
        style.map("TNotebook.Tab",
                  background=[("selected", "#3a2a08")],
                  foreground=[("selected", "#f5c842")])
        style.configure("TFrame", background="#1a1208")
        style.configure("Status.TLabel", foreground="#9a8060",
                        font=FONT_SM, background="#1a1208")
        style.configure("Treeview", background="#2a1e0e", foreground="#e8d5a0",
                        fieldbackground="#2a1e0e", rowheight=24, font=FONT)
        style.configure("Treeview.Heading", background="#3a2a08",
                        foreground="#f5c842", font=FONT)

        tk.Label(self, text="⚔ TBH 塔斯克巴·英雄 效率計算機",
                 bg="#1a1208", fg="#f5c842", font=FONT_TL).pack(pady=(12, 4))

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=4)
        self._tab_monitor(nb)
        self._tab_compare(nb)
        self._tab_region(nb)

        self.lbl_status = ttk.Label(self, text="尚未連接遊戲視窗",
                                    style="Status.TLabel")
        self.lbl_status.pack(pady=(2, 6))

    def _tab_monitor(self, nb):
        frm = ttk.Frame(nb)
        nb.add(frm, text=" 即時監控 ")

        box = tk.Frame(frm, bg="#2a1e0e", padx=16, pady=12)
        box.pack(fill="x", padx=10, pady=8)

        def row(parent, label, attr, unit=""):
            f = tk.Frame(parent, bg="#2a1e0e")
            f.pack(fill="x", pady=2)
            tk.Label(f, text=label, bg="#2a1e0e", fg="#9a8060",
                     font=FONT, width=14, anchor="w").pack(side="left")
            lbl = tk.Label(f, text="—", bg="#2a1e0e",
                           fg="#f5c842", font=FONT_LG)
            lbl.pack(side="left")
            if unit:
                tk.Label(f, text=unit, bg="#2a1e0e",
                         fg="#6a5030", font=FONT_SM).pack(side="left", padx=2)
            setattr(self, attr, lbl)

        row(box, "紀錄時間",   "lbl_timer")
        row(box, "目前金幣",   "lbl_gold")
        row(box, "金幣 / 秒",  "lbl_gps", "/s")
        row(box, "金幣 / 分鐘", "lbl_gpm", "/min")
        row(box, "金幣 / 小時", "lbl_gph", "/hr")
        row(box, "目前經驗",   "lbl_exp")
        row(box, "升級需求",   "lbl_exp_req")
        row(box, "預計升級",   "lbl_exp_eta")

        # 經驗進度條
        bar_wrap = tk.Frame(box, bg="#2a1e0e")
        bar_wrap.pack(fill="x", pady=(6, 2))
        tk.Label(bar_wrap, text="升級進度", bg="#2a1e0e", fg="#9a8060",
                 font=FONT, width=14, anchor="w").pack(side="left")
        self.exp_bar = tk.Canvas(bar_wrap, height=18, bg="#0e0c06",
                                 highlightthickness=1, highlightbackground="#5a3e1a")
        self.exp_bar.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.exp_bar_fill = self.exp_bar.create_rectangle(0, 0, 0, 18,
                                                          fill="#5ac840", outline="")
        self.exp_bar_text = self.exp_bar.create_text(0, 0, text="—",
                                                     fill="#e8d5a0", font=FONT_SM)
        self.exp_bar.bind("<Configure>", self._redraw_exp_bar)
        self._exp_pct = 0.0

        row(box, "經驗 / 秒",  "lbl_eps", "/s")
        row(box, "經驗 / 分鐘", "lbl_epm", "/min")
        row(box, "經驗 / 小時", "lbl_eph", "/hr")

        # 監控控制按鈕
        frm_btn = tk.Frame(frm, bg="#1a1208")
        frm_btn.pack(pady=(6, 4))

        self.btn_track = tk.Button(frm_btn, text="▶ 開始監控",
                                   command=self._toggle_tracking,
                                   bg="#c89a00", fg="#1a1208",
                                   font=FONT, relief="flat", padx=16, pady=6)
        self.btn_track.pack(side="left", padx=4)

        tk.Button(frm_btn, text="重新計算", command=self._reset_history,
                  bg="#3a1a2a", fg="#e8a0d0", font=FONT,
                  relief="flat", padx=10, pady=6).pack(side="left", padx=4)

        # 關卡名稱 + 保存
        frm_save = tk.Frame(frm, bg="#2a1e0e", padx=12, pady=8)
        frm_save.pack(fill="x", padx=10, pady=(0, 6))

        tk.Label(frm_save, text="關卡名稱：", bg="#2a1e0e",
                 fg="#b09060", font=FONT).pack(side="left")
        self.var_stage_name = tk.StringVar()
        tk.Entry(frm_save, textvariable=self.var_stage_name,
                 bg="#1a1208", fg="#e8d5a0", insertbackground="#e8d5a0",
                 relief="flat", font=FONT, width=10).pack(side="left", padx=6)
        tk.Button(frm_save, text="保存至比較表",
                  command=self._add_to_compare,
                  bg="#204080", fg="#e8d5a0", font=FONT,
                  relief="flat", padx=10, pady=4).pack(side="left")

        # 自動保存設定
        frm_auto = tk.Frame(frm, bg="#2a1e0e", padx=12, pady=6)
        frm_auto.pack(fill="x", padx=10, pady=(0, 6))
        self.var_autosave = tk.BooleanVar(value=False)
        tk.Checkbutton(frm_auto, text="自動保存：監測", variable=self.var_autosave,
                       bg="#2a1e0e", fg="#b09060", font=FONT,
                       selectcolor="#1a1208", activebackground="#2a1e0e",
                       activeforeground="#f5c842",
                       highlightthickness=0, bd=0).pack(side="left")
        self.var_autosave_min = tk.StringVar(value="5")
        tk.Entry(frm_auto, textvariable=self.var_autosave_min,
                 bg="#1a1208", fg="#e8d5a0", insertbackground="#e8d5a0",
                 relief="flat", font=FONT, width=5).pack(side="left", padx=4)
        tk.Label(frm_auto, text="分鐘後自動保存並停止", bg="#2a1e0e",
                 fg="#6a5030", font=FONT_SM).pack(side="left")

        tk.Label(frm, text="最近取樣紀錄", bg="#1a1208",
                 fg="#7a6040", font=FONT_SM).pack(anchor="w", padx=12)
        self.txt_log = tk.Text(frm, height=6, bg="#0e0c06", fg="#7a6040",
                               font=("Microsoft JhengHei UI", 8), relief="flat",
                               state="disabled", padx=6, pady=4)
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=(2, 8))

    def _tab_compare(self, nb):
        frm = ttk.Frame(nb)
        nb.add(frm, text=" 關卡比較 ")

        cols = ("stage", "gps", "gph", "eps", "eph", "dur")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=10)
        self._compare_heads = {
            "stage": "關卡", "gps": "金幣/秒", "gph": "金幣/時",
            "eps": "經驗/秒", "eph": "經驗/時", "dur": "時間",
        }
        for cid, w in [("stage", 60), ("gps", 80), ("gph", 88),
                       ("eps", 80), ("eph", 88), ("dur", 64)]:
            self.tree.heading(cid, text=self._compare_heads[cid],
                              command=lambda c=cid: self._sort_compare(c))
            self.tree.column(cid, width=w, anchor="center")
        self.tree.tag_configure("best_g", foreground="#f5c842", background="#1a1208")
        self.tree.tag_configure("best_e", foreground="#44aaee", background="#1a1208")
        self.tree.tag_configure("best_ge", foreground="#aaee44", background="#1a2a08")
        self.tree.pack(fill="both", expand=True, padx=10, pady=8)
        tk.Button(frm, text="移除選取", command=self._remove_compare_row,
                  bg="#6a1810", fg="#e8d5a0", relief="flat",
                  font=FONT, padx=10, pady=4).pack(pady=(0, 8))

    def _tab_region(self, nb):
        frm = ttk.Frame(nb)
        nb.add(frm, text=" 區域設定 ")

        tk.Label(frm, text="點擊按鈕，在遊戲畫面上拖曳選取對應區域",
                 bg="#1a1208", fg="#b09060", font=FONT).pack(
                 anchor="w", padx=14, pady=(14, 10))

        # 金幣區域
        self._region_card(frm, "gold", "💰 金幣區域",
                          "選取金幣數字顯示的位置",
                          lambda r: self._on_region_set("gold", r))

        # 經驗區域
        self._region_card(frm, "exp", "✨ 經驗區域",
                          "選取經驗值數字顯示的位置",
                          lambda r: self._on_region_set("exp", r))

        tk.Label(frm,
                 text="提示：選取時請確保遊戲視窗完整可見，選取框盡量貼近數字。\n"
                      "選取後可再次點擊按鈕重新選取。",
                 bg="#1a1208", fg="#6a5030",
                 font=FONT_SM, justify="left").pack(anchor="w", padx=14, pady=(8, 0))

    def _region_card(self, parent, key, title, hint, callback):
        box = tk.Frame(parent, bg="#2a1e0e", padx=14, pady=10)
        box.pack(fill="x", padx=12, pady=5)

        tk.Label(box, text=title, bg="#2a1e0e",
                 fg="#f5c842", font=FONT).grid(row=0, column=0, sticky="w")

        # 目前座標顯示
        lbl = tk.Label(box, text=self._fmt_region(key),
                       bg="#2a1e0e", fg="#9a8060", font=FONT_SM)
        lbl.grid(row=1, column=0, sticky="w", pady=(2, 4))
        setattr(self, f"_lbl_region_{key}", lbl)

        # 即時 OCR 讀值
        preview = tk.Label(box, text="OCR：—", bg="#2a1e0e",
                           fg="#aaee44", font=FONT)
        preview.grid(row=2, column=0, sticky="w")
        setattr(self, f"_lbl_preview_{key}", preview)

        tk.Label(box, text=hint, bg="#2a1e0e",
                 fg="#6a5030", font=FONT_SM).grid(row=3, column=0, sticky="w")

        def pick():
            if not self.hwnd:
                messagebox.showwarning("提示", "請先選擇並偵測到遊戲視窗")
                return
            self.after(200, lambda: RegionPicker(self, self.hwnd, callback))

        def test_capture():
            if not self.hwnd:
                messagebox.showwarning("提示", "請先選擇遊戲視窗"); return
            try:
                img = capture_region(self.hwnd, self.regions[key])
                img.save(os.path.join(BASE_DIR, f"tbh_{key}_raw.png"))
                processed = preprocess_for_ocr(img)
                processed.save(os.path.join(BASE_DIR, f"tbh_{key}_ocr.png"))

                if key == "exp":
                    cur, req, raw_text = ocr_exp_pair(img)
                    parsed = (f"目前經驗：{int(cur):,}\n" if cur is not None else "目前經驗：讀取失敗\n") + \
                             (f"升級需求：{int(req):,}" if req is not None else "升級需求：讀取失敗")
                else:
                    val, raw_text, _ = ocr_number_debug(img)
                    parsed = f"解析數值：{int(val):,}" if val is not None else "解析數值：讀取失敗"

                messagebox.showinfo(
                    "測試結果",
                    f"OCR 原始文字：「{raw_text}」\n\n"
                    f"{parsed}\n\n"
                    f"原始截圖：tbh_{key}_raw.png\n"
                    f"OCR預處理：tbh_{key}_ocr.png\n"
                    f"（已儲存至程式資料夾）"
                )
            except Exception as e:
                messagebox.showerror("錯誤", str(e))

        btn_frame = tk.Frame(box, bg="#2a1e0e")
        btn_frame.grid(row=0, column=1, rowspan=4, padx=(20, 0), sticky="e")
        tk.Button(btn_frame, text="選取區域", command=pick,
                  bg="#c89a00", fg="#1a1208", font=FONT,
                  relief="flat", padx=12, pady=4).pack(pady=(0, 4))
        tk.Button(btn_frame, text="測試截圖", command=test_capture,
                  bg="#2a3a18", fg="#aaee44", font=FONT_SM,
                  relief="flat", padx=8, pady=2).pack()
        box.columnconfigure(0, weight=1)

    def _fmt_region(self, key):
        r = self.regions[key]
        return f"X:{r['x']:.2f}  Y:{r['y']:.2f}  W:{r['w']:.2f}  H:{r['h']:.2f}"

    def _on_region_set(self, key, rel):
        # 夾到合理範圍
        rel["x"] = max(0.0, min(rel["x"], 1.0))
        rel["y"] = max(0.0, min(rel["y"], 1.0))
        rel["w"] = max(0.01, min(rel["w"], 1.0))
        rel["h"] = max(0.01, min(rel["h"], 1.0))
        self.regions[key] = rel
        lbl = getattr(self, f"_lbl_region_{key}", None)
        if lbl:
            lbl.config(text=self._fmt_region(key))
        # 持久化儲存區域
        cfg = load_config()
        cfg["regions"] = self.regions
        save_config(cfg)
        self._set_status(f"{key} 區域已更新")

    def _region_preview_loop(self):
        """每 1.5 秒更新區域設定的即時 OCR 預覽"""
        while True:
            time.sleep(1.5)
            if not self.hwnd:
                self.after(0, self._set_preview, "gold", None)
                self.after(0, self._set_preview, "exp", None, None)
                continue

            # 追蹤中直接用已讀到的 live 值，避免與監控執行緒搶 dxcam
            if self.tracking:
                self.after(0, self._set_preview, "gold", self._live_gold)
                self.after(0, self._set_preview, "exp", self._live_exp, self._exp_required)
                continue

            # 未追蹤時自行截圖 OCR
            try:
                g, _, _ = ocr_number_debug(capture_region(self.hwnd, self.regions["gold"]))
            except Exception:
                g = None
            try:
                e, r, _ = ocr_exp_pair(capture_region(self.hwnd, self.regions["exp"]))
            except Exception:
                e = r = None
            self.after(0, self._set_preview, "gold", g)
            self.after(0, self._set_preview, "exp", e, r)

    def _set_preview(self, key, val, req=None):
        lbl = getattr(self, f"_lbl_preview_{key}", None)
        if lbl is None:
            return
        if key == "exp":
            if val is None:
                lbl.config(text="OCR：請重新擷取", fg="#e87040")
            elif req is None:
                lbl.config(text=f"OCR：{int(val):,}（升級需求請重新擷取）", fg="#e8c040")
            else:
                lbl.config(text=f"OCR：{int(val):,} / {int(req):,}", fg="#aaee44")
        else:
            if val is None:
                lbl.config(text="OCR：請重新擷取", fg="#e87040")
            else:
                lbl.config(text=f"OCR：{int(val):,}", fg="#aaee44")

    # ── 視窗管理 ────────────────────────────────────────────────

    def _refresh_windows(self):
        if not DEPS_OK:
            self._set_status("缺少套件，請執行安裝")
            return
        wins = find_game_window()
        if wins:
            self.hwnd = wins[0][0]
            self._set_status(f"已偵測到遊戲：{wins[0][1]}")
        else:
            self.hwnd = None
            self._set_status("找不到遊戲視窗，請先開啟遊戲")

    # ── 監控 ────────────────────────────────────────────────────

    def _toggle_tracking(self):
        if self.tracking:
            self.tracking = False
            self.btn_track.config(text="▶ 開始監控", bg="#c89a00", fg="#1a1208")
            if self._timer_job:
                self.after_cancel(self._timer_job)
                self._timer_job = None
            self._set_status("監控已停止")
        else:
            if not self.hwnd:
                messagebox.showwarning("提示", "請先選擇遊戲視窗"); return
            if not DEPS_OK:
                messagebox.showerror("錯誤", "缺少必要套件"); return
            self.tracking = True
            self._track_start = time.time()
            self._reset_accumulators()
            self.btn_track.config(text="⏹ 停止監控", bg="#a03020", fg="#e8d5a0")
            self._set_status("監控中…")
            self._tick_timer()
            threading.Thread(target=self._track_loop, daemon=True).start()

    def _tick_timer(self):
        if not self.tracking:
            return
        elapsed = int(time.time() - self._track_start)
        h, r = divmod(elapsed, 3600)
        m, s = divmod(r, 60)
        self.lbl_timer.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        # 自動保存：監測時間到 → 保存比較表並停止
        if self.var_autosave.get():
            try:
                mins = float(self.var_autosave_min.get())
            except ValueError:
                mins = 0
            if mins > 0 and elapsed >= mins * 60:
                self._add_to_compare()
                self._toggle_tracking()   # 停止監控
                self._set_status(f"已監測 {mins:g} 分鐘，自動保存並停止")
                return
        self._timer_job = self.after(1000, self._tick_timer)

    def _track_loop(self):
        while self.tracking:
            self._do_snapshot()
            time.sleep(1)

    def _reset_accumulators(self):
        self._hist = {"gold": [], "exp": []}

    def _accumulate(self, key, val, now):
        """全程平均（含 IQR 離群過濾）：對整段紀錄的每秒增量取平均"""
        h = self._hist[key]
        if val is not None:
            h.append((now, val))
        if len(h) < 2:
            return None, None, None
        # 每段的每秒增量（忽略負值：換關/升級重置）
        rates = []
        for i in range(1, len(h)):
            dt = h[i][0] - h[i-1][0]
            dv = h[i][1] - h[i-1][1]
            if dt > 0 and dv >= 0:
                rates.append(dv / dt)
        if not rates:
            return None, None, None
        # IQR 離群值過濾：剔除暴衝的垃圾讀值
        s = sorted(rates)
        if len(s) >= 4:
            q1 = s[len(s) // 4]
            q3 = s[len(s) * 3 // 4]
            limit = q3 + (q3 - q1) * 3
            s = [r for r in s if r <= limit]
        if not s:
            return None, None, None
        ps = sum(s) / len(s)
        return ps, ps * 60, ps * 3600

    def _do_snapshot(self):
        gold_raw = exp_raw = ""
        gold = exp = None

        # 金幣：OCR 截圖
        try:
            img_gold = capture_region(self.hwnd, self.regions["gold"])
            gold, gold_raw, _ = ocr_number_debug(img_gold)
        except Exception as e:
            self.after(0, self._set_status, f"截圖失敗(金幣)：{e}")

        # 經驗：OCR 截圖（同時讀升級需求）
        try:
            img_exp = capture_region(self.hwnd, self.regions["exp"])
            exp, req, exp_raw = ocr_exp_pair(img_exp)
            # 升級需求只在 OCR 確實讀到第二個數字時更新（避免漏讀時歸零）
            if req is not None and req > 0:
                self._exp_required = req
            # 經驗合理性檢查：超過升級需求或非正值 → 視為 OCR 誤讀，丟棄
            if exp is not None and (exp <= 0 or
                    (self._exp_required and exp > self._exp_required * 1.02)):
                exp = None
        except Exception as e:
            self.after(0, self._set_status, f"截圖失敗(經驗)：{e}")

        now = time.time()
        gps, gpm, gph = self._accumulate("gold", gold, now)
        eps, epm, eph = self._accumulate("exp",  exp,  now)

        ts = datetime.now().strftime("%H:%M:%S")
        # 顯示解析值，若為 None 則顯示 OCR 原始文字供除錯
        g_disp = fmt_num(gold) if gold is not None else f"?({gold_raw.strip()!r})"
        e_disp = fmt_num(exp)  if exp  is not None else f"?({exp_raw.strip()!r})"
        log_line = f"[{ts}] 金幣={g_disp}  經驗={e_disp}"
        if gps is not None:
            log_line += f"  金{fmt_num(gps)}/s"
        if eps is not None:
            log_line += f"  經{fmt_num(eps)}/s"

        self.after(0, self._update_monitor, gold, exp, gps, gpm, gph, eps, epm, eph, log_line)

    def _update_monitor(self, gold, exp, gps, gpm, gph, eps, epm, eph, log_line):
        # 供記憶體掃描器直接取用，不需重複 OCR
        if gold is not None: self._live_gold = int(gold)
        if exp  is not None: self._live_exp  = int(exp)
        # 記住最新速率，保存比較表時直接用（避免解析格式化文字出錯）
        self._last_gps = gps
        self._last_eps = eps
        def v(x): return fmt_num(x) if x is not None else "—"
        self.lbl_gold.config(text=v(gold))
        self.lbl_gps.config(text=v(gps))
        self.lbl_gpm.config(text=v(gpm))
        self.lbl_gph.config(text=v(gph))
        self.lbl_exp.config(text=v(exp))
        self.lbl_eps.config(text=v(eps))
        self.lbl_epm.config(text=v(epm))
        self.lbl_eph.config(text=v(eph))

        # 升級需求 / 進度 / 預計升級時間
        req = self._exp_required
        self.lbl_exp_req.config(text=v(req))
        if req and exp is not None and req > 0:
            pct = max(0.0, min(exp / req * 100, 100.0))
            self._exp_pct = pct
            remain = req - exp
            if eps and eps > 0 and remain > 0:
                self.lbl_exp_eta.config(text=self._fmt_duration(remain / eps))
            elif remain <= 0:
                self.lbl_exp_eta.config(text="可升級")
            else:
                self.lbl_exp_eta.config(text="—")
        else:
            self._exp_pct = 0.0
            self.lbl_exp_eta.config(text="—")
        self._redraw_exp_bar()

        self.txt_log.config(state="normal")
        self.txt_log.insert("end", log_line + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    def _fmt_duration(self, sec):
        sec = int(sec)
        h, r = divmod(sec, 3600)
        m, s = divmod(r, 60)
        if h > 0: return f"{h} 小時 {m} 分"
        if m > 0: return f"{m} 分 {s} 秒"
        return f"{s} 秒"

    def _redraw_exp_bar(self, event=None):
        if not hasattr(self, "exp_bar"):
            return
        w = self.exp_bar.winfo_width()
        h = self.exp_bar.winfo_height()
        fill_w = int(w * self._exp_pct / 100)
        self.exp_bar.coords(self.exp_bar_fill, 0, 0, fill_w, h)
        self.exp_bar.coords(self.exp_bar_text, w // 2, h // 2)
        self.exp_bar.itemconfig(self.exp_bar_text, text=f"{self._exp_pct:.1f}%")

    def _add_to_compare(self):
        stage = self.var_stage_name.get().strip() or "未命名"
        gps = getattr(self, "_last_gps", None)
        eps = getattr(self, "_last_eps", None)
        if gps is None and eps is None:
            messagebox.showinfo("提示", "尚無數據，請先監控至少 2 秒"); return
        duration = int(time.time() - self._track_start) if self._track_start else 0
        self._insert_compare(stage, gps, eps, duration)

    def _fmt_dur_short(self, sec):
        sec = int(sec or 0)
        h, r = divmod(sec, 3600)
        m, s = divmod(r, 60)
        if h > 0: return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ── 比較表 ──────────────────────────────────────────────────

    def _insert_compare(self, stage, gps, eps, duration=0):
        row = {"stage": stage, "gps": gps, "eps": eps, "duration": duration}
        # 同名覆蓋，否則新增
        for i, r in enumerate(self.compare_rows):
            if r["stage"] == stage:
                self.compare_rows[i] = row
                break
        else:
            self.compare_rows.append(row)
        save_compare(self.compare_rows)
        self._render_compare()

    def _sort_compare(self, col):
        """點欄位標題排序，同欄再點切換升降冪"""
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = (col != "stage")  # 數值欄預設由大到小
        self._render_compare()

    def _render_compare(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 最佳值依數值計算，與排序無關（綠底標記不受影響）
        valid_g = [r["gps"] for r in self.compare_rows if r["gps"] is not None]
        valid_e = [r["eps"] for r in self.compare_rows if r["eps"] is not None]
        best_g = max(valid_g) if valid_g else None
        best_e = max(valid_e) if valid_e else None

        # 依排序欄位排序（gph/eph 與 gps/eps 同序）
        rows = list(self.compare_rows)
        keymap = {
            "stage": lambda r: r["stage"],
            "gps": lambda r: r["gps"] if r["gps"] is not None else -1,
            "gph": lambda r: r["gps"] if r["gps"] is not None else -1,
            "eps": lambda r: r["eps"] if r["eps"] is not None else -1,
            "eph": lambda r: r["eps"] if r["eps"] is not None else -1,
            "dur": lambda r: r.get("duration", 0),
        }
        if self._sort_col in keymap:
            rows.sort(key=keymap[self._sort_col], reverse=self._sort_reverse)
        self._render_rows = rows

        # 更新標題箭頭
        for cid, base in self._compare_heads.items():
            arrow = ""
            if cid == self._sort_col:
                arrow = " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(cid, text=base + arrow)

        def v(x): return fmt_num(x) if x is not None else "—"
        for r in rows:
            is_bg = best_g is not None and r["gps"] == best_g
            is_be = best_e is not None and r["eps"] == best_e
            if is_bg and is_be:
                tag = ("best_ge",)
            elif is_bg:
                tag = ("best_g",)
            elif is_be:
                tag = ("best_e",)
            else:
                tag = ()
            gph = r["gps"] * 3600 if r["gps"] else None
            eph = r["eps"] * 3600 if r["eps"] else None
            self.tree.insert("", "end", values=(
                r["stage"],
                v(r["gps"]),
                v(gph),
                v(r["eps"]),
                v(eph),
                self._fmt_dur_short(r.get("duration", 0)),
            ), tags=tag)

    def _remove_compare_row(self):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])   # 對應目前顯示順序
        if 0 <= idx < len(self._render_rows):
            row = self._render_rows[idx]
            self.compare_rows.remove(row)
            save_compare(self.compare_rows)
            self._render_compare()

    # ── 手動計算 ────────────────────────────────────────────────

    # ── 其他 ────────────────────────────────────────────────────

    def _reset_history(self):
        self._reset_accumulators()
        self._track_start = time.time()
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.config(state="disabled")
        for attr in ("lbl_timer", "lbl_gps", "lbl_gpm", "lbl_gph",
                     "lbl_eps", "lbl_epm", "lbl_eph", "lbl_exp_eta"):
            getattr(self, attr).config(text="—")
        self.lbl_timer.config(text="00:00:00")
        self._exp_pct = 0.0
        self._redraw_exp_bar()
        self._set_status("已清除紀錄，重新開始計算")

    def _set_status(self, msg):
        self.lbl_status.config(text=msg)

    def _on_close(self):
        self.tracking = False
        self.destroy()


# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not DEPS_OK:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "缺少套件",
            f"缺少以下套件：{', '.join(MISSING)}\n\n"
            "請開啟命令列執行：\n\n"
            "pip install pywin32 Pillow pytesseract dxcam numpy\n\n"
            "並安裝 Tesseract OCR：\n"
            "https://github.com/UB-Mannheim/tesseract/wiki"
        )
        root.destroy()
    else:
        TBHApp().mainloop()
