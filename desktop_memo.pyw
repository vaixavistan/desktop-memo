# -*- coding: utf-8 -*-
"""바탕화면 메모

바탕화면에 붙어 있는 마크다운 메모.
- Win+D / 바탕화면 보기를 해도 사라지지 않고, 다른 프로그램을 열면 그 뒤로 가려짐
- 마크다운 문법 실시간 표시, 블록 지정 후 우클릭으로 서식 적용
- 위쪽 막대로 이동, 가장자리/모서리로 크기 조절
"""
import ctypes
import json
import os
import re
import sys
import traceback
import uuid
import webbrowser
import winreg
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes
from tkinter import messagebox

APP_NAME = "DesktopMemo"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "notes.json")
LOG_FILE = os.path.join(BASE_DIR, "error.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

BASE_FAMILY = "Malgun Gothic"
MONO_FAMILY = "Consolas"
ICON_FAMILY = "Segoe UI Symbol"

# ---------------------------------------------------------------- Win32
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]

GWLP_HWNDPARENT = -8
SW_SHOWNOACTIVATE = 4
ERROR_ALREADY_EXISTS = 183


def desktop_window():
    return user32.FindWindowW("Progman", None)


def pin_to_desktop(hwnd):
    """바탕화면(Progman)을 소유자로 지정 → Win+D 해도 남아 있고, 다른 창 뒤로는 가려짐."""
    progman = desktop_window()
    if hwnd and progman:
        user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, progman)


def virtual_screen():
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))


# ---------------------------------------------------------------- 자동 실행
def autostart_command():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pyw):
        pyw = sys.executable
    return f'"{pyw}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(on):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


# ---------------------------------------------------------------- 색상
COLORS = {
    "노랑": ("#FFF6A8", "#F4DF72"),
    "주황": ("#FFE2C2", "#F7C590"),
    "분홍": ("#FFDDEA", "#F6BCD3"),
    "보라": ("#E9E1FF", "#D1C2F9"),
    "하늘": ("#DCEEFF", "#B9D9F6"),
    "연두": ("#E1F5D0", "#C1E6A3"),
    "흰색": ("#FFFFFF", "#ECECEC"),
    "다크": ("#26282C", "#1B1C1F"),
}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def blend(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def palette(name):
    bg, bar = COLORS.get(name, COLORS["노랑"])
    dark = name == "다크"
    fg = "#E6E6E6" if dark else "#2F2E28"
    return {
        "bg": bg, "bar": bar, "fg": fg,
        "dim": blend(fg, bg, 0.55),
        "border": blend(bar, fg, 0.18),
        "hover": blend(bar, fg, 0.13),
        "accent": "#F5A524" if dark else "#C2410C",
        "link": "#7DB4FF" if dark else "#1D4ED8",
        "quote": blend(fg, bg, 0.3),
        "codebg": blend(bg, "#FFFFFF" if dark else "#000000", 0.08),
        "hl": "#7A5F00" if dark else ("#FFB357" if name == "노랑" else "#FFE45C"),
        "sel": "#3E5C86" if dark else "#A9CBFF",
    }


# ---------------------------------------------------------------- 마크다운 패턴
HEAD_RE = re.compile(r"^(#{1,6})(\s+)")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)]) (\[[ xX]\] )?")
QUOTE_RE = re.compile(r"^(\s*)(>+ ?)")
HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
FENCE_RE = re.compile(r"^\s*```")
PREFIX_RE = re.compile(r"^(\s*)(#{1,6}\s+|>+ ?|[-*+] \[[ xX]\] |[-*+] |\d+[.)] )")
CODE_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
URL_RE = re.compile(r"(?<![\w(/])(?:https?://|www\.)[^\s<>\]\)\x01\x02]+")
INLINE = [
    (re.compile(r"(?<!\*)\*\*\*(?![\s*])(.+?)(?<![\s*])\*\*\*(?!\*)"), 3, 3, ("b", "i")),
    (re.compile(r"(?<!\*)\*\*(?![\s*])(.+?)(?<!\s)\*\*"), 2, 2, ("b",)),
    (re.compile(r"(?<![\w_])__(?![\s_])(.+?)(?<!\s)__(?![\w_])"), 2, 2, ("b",)),
    (re.compile(r"(?<!\*)\*(?![\s*])(.+?)(?<![\s*])\*(?!\*)"), 1, 1, ("i",)),
    (re.compile(r"(?<![\w_])_(?![\s_])(.+?)(?<!\s)_(?![\w_])"), 1, 1, ("i",)),
    (re.compile(r"~~(?!\s)(.+?)(?<!\s)~~"), 2, 2, ("s",)),
    (re.compile(r"==(?!\s)(.+?)(?<!\s)=="), 2, 2, ("hl",)),
    (re.compile(r"<u>(.+?)</u>"), 3, 4, ("u",)),
]
HEAD_SCALE = {"h1": 1.75, "h2": 1.4, "h3": 1.18, "n": 1.0}

WELCOME = """# 바탕화면 메모

글자를 **블록 지정**하고 *우클릭*하면 서식 메뉴가 나와요.

- [ ] 체크박스는 [ ] 부분을 클릭
- [x] 완료한 일
- ~~취소선~~, ==형광펜==, `코드`, <u>밑줄</u>

> 인용문은 이렇게

## 사용법
- 위쪽 막대를 끌어서 이동
- 가장자리·모서리를 끌어서 크기 조절
- Ctrl+B 굵게 · Ctrl+I 기울임 · Ctrl+U 밑줄
- Ctrl+1/2/3 제목 · Ctrl+0 본문
- Ctrl+휠 글자 크기 · Ctrl+N 새 메모
"""


# ================================================================ Note
class Note:
    MIN_W, MIN_H = 160, 110

    def __init__(self, app, data):
        self.app = app
        S = app.S
        self.id = data.get("id") or uuid.uuid4().hex
        self.color = data.get("color") if data.get("color") in COLORS else "노랑"
        self.font_size = int(data.get("font_size", 11))
        self.alpha = float(data.get("alpha", 1.0))
        self.fonts = {}
        self._hl_job = None
        self._drag = None
        self._rs = None
        self.hwnd = None
        self.focused = False

        w = int(data.get("w", 290 * S))
        h = int(data.get("h", 320 * S))
        x = int(data.get("x", 120 * S))
        y = int(data.get("y", 120 * S))
        vx, vy, vw, vh = virtual_screen()
        if not (vx - w + 40 <= x <= vx + vw - 40 and vy <= y <= vy + vh - 30):
            x, y = int(120 * S), int(120 * S)

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        self.M = max(4, int(5 * S))
        self.frame = tk.Frame(self.win, bd=0, highlightthickness=1)
        self.frame.pack(fill="both", expand=True)

        self.bar = tk.Frame(self.frame, height=int(22 * S), bd=0)
        self.bar.pack(side="top", fill="x", padx=self.M, pady=(self.M, 0))
        self.bar.pack_propagate(False)
        icon_font = (ICON_FAMILY, 10)
        self.btns = []
        for txt, cmd in (("✕", lambda e: self.delete()),
                         ("⋯", self._bar_menu),
                         ("+", lambda e: self.app.new_note_from(self))):
            b = tk.Label(self.bar, text=txt, font=icon_font, width=2, cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda e, c=cmd: (c(e), "break")[1])
            b.bind("<Enter>", lambda e, b=b: b.configure(bg=self.p["hover"]))
            b.bind("<Leave>", lambda e, b=b: b.configure(bg=self.p["bar"]))
            self.btns.append(b)
        self.bar.bind("<ButtonPress-1>", self._drag_start)
        self.bar.bind("<B1-Motion>", self._drag_move)
        self.bar.bind("<ButtonRelease-1>", lambda e: self.app.save_soon())
        self.bar.bind("<Button-3>", self._bar_menu)

        self.txt = tk.Text(self.frame, wrap="word", undo=True, maxundo=-1, autoseparators=True,
                           bd=0, highlightthickness=0, padx=int(8 * S), pady=int(6 * S),
                           spacing1=int(1 * S), spacing3=int(1 * S),
                           font=(BASE_FAMILY, self.font_size))
        self.txt.pack(fill="both", expand=True, padx=self.M, pady=(0, self.M))
        self.base_font = tkfont.Font(family=BASE_FAMILY, size=self.font_size)
        self.txt.configure(font=self.base_font)

        self._setup_tags()
        self.apply_theme()
        self.txt.insert("1.0", data.get("text", ""))
        self.txt.edit_reset()
        self.txt.edit_modified(False)
        self.txt.mark_set("insert", "end-1c")

        t = self.txt
        t.bind("<<Modified>>", self._on_modified)
        t.bind("<KeyRelease>", lambda e: self.schedule_hl())
        t.bind("<ButtonRelease-1>", lambda e: self.schedule_hl())
        t.bind("<Button-1>", lambda e: self.txt.focus_force(), add="+")
        t.bind("<FocusIn>", lambda e: self._set_focus(True))
        t.bind("<FocusOut>", lambda e: self._set_focus(False))
        t.bind("<Button-3>", self._text_menu)
        t.bind("<Control-KeyPress>", self._on_ctrl)
        t.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        t.bind("<Return>", self._on_return)
        t.bind("<Tab>", self._on_tab)
        t.bind("<Shift-Tab>", self._on_shift_tab)
        t.tag_bind("cbox", "<Button-1>", self._on_cbox)
        t.tag_bind("cbox", "<Enter>", lambda e: t.configure(cursor="hand2"))
        t.tag_bind("cbox", "<Leave>", lambda e: t.configure(cursor="xterm"))
        t.tag_bind("link", "<Control-Button-1>", self._open_link)

        for ev, fn in (("<Motion>", self._rs_hover), ("<ButtonPress-1>", self._rs_start),
                       ("<B1-Motion>", self._rs_move), ("<ButtonRelease-1>", self._rs_end),
                       ("<Leave>", lambda e: self.frame.configure(cursor="arrow"))):
            self.frame.bind(ev, fn)

        self.win.attributes("-alpha", self.alpha)
        self.win.deiconify()
        self.win.update_idletasks()
        try:
            self.hwnd = int(self.win.wm_frame(), 16)
        except (tk.TclError, ValueError):
            self.hwnd = user32.GetParent(self.txt.winfo_id())
        pin_to_desktop(self.hwnd)
        self._highlight()

    # ------------------------------------------------------------ 데이터
    def to_dict(self):
        return {
            "id": self.id, "color": self.color, "font_size": self.font_size, "alpha": self.alpha,
            "x": self.win.winfo_x(), "y": self.win.winfo_y(),
            "w": self.win.winfo_width(), "h": self.win.winfo_height(),
            "text": self.txt.get("1.0", "end-1c"),
        }

    # ------------------------------------------------------------ 모양
    def _setup_tags(self):
        t = self.txt
        for name in ("quote", "bullet", "cbox", "link", "codebg", "hl", "u", "s",
                     "done", "hr", "mk", "hide"):
            t.tag_configure(name)
        for cls in ("h1", "h2", "h3"):
            t.tag_configure("sp_" + cls)
        t.tag_configure("hide", elide=True)
        t.tag_configure("u", underline=True)
        t.tag_configure("s", overstrike=True)
        t.tag_configure("link", underline=True)
        t.tag_configure("done", overstrike=True)
        t.tag_configure("hr", overstrike=True)
        t.tag_configure("quote", lmargin1=int(12 * self.app.S), lmargin2=int(12 * self.app.S))
        self._update_spacing()
        t.tag_raise("mk")
        t.tag_raise("hide")
        t.tag_raise("sel")

    def _update_spacing(self):
        for cls, k in (("h1", 0.9), ("h2", 0.7), ("h3", 0.5)):
            self.txt.tag_configure("sp_" + cls, spacing1=int(self.font_size * k * self.app.S))

    def apply_theme(self):
        p = self.p = palette(self.color)
        self.frame.configure(bg=p["bg"], highlightbackground=p["border"], highlightcolor=p["border"])
        self.bar.configure(bg=p["bar"])
        for b in self.btns:
            b.configure(bg=p["bar"], fg=p["dim"], activebackground=p["hover"])
        t = self.txt
        t.configure(bg=p["bg"], fg=p["fg"], insertbackground=p["fg"], selectbackground=p["sel"],
                    selectforeground=p["fg"], inactiveselectbackground=p["sel"])
        t.tag_configure("mk", foreground=p["dim"])
        t.tag_configure("bullet", foreground=p["accent"])
        t.tag_configure("cbox", foreground=p["accent"])
        t.tag_configure("done", foreground=p["dim"])
        t.tag_configure("hr", foreground=p["dim"])
        t.tag_configure("link", foreground=p["link"])
        t.tag_configure("quote", foreground=p["quote"])
        t.tag_configure("codebg", background=p["codebg"])
        t.tag_configure("hl", background=p["hl"])

    def set_color(self, name):
        self.color = name
        self.apply_theme()
        self.app.save_soon()

    def set_alpha(self, a):
        self.alpha = a
        self.win.attributes("-alpha", a)
        self.app.save_soon()

    def _size_for(self, cls, mono):
        s = self.font_size * HEAD_SCALE[cls]
        if mono:
            s *= 0.92
        return max(6, round(s))

    def _font_tag(self, key):
        name = "F%s%d%d%d" % key
        if name not in self.fonts:
            cls, b, i, m = key
            f = tkfont.Font(family=MONO_FAMILY if m else BASE_FAMILY, size=self._size_for(cls, m),
                            weight="bold" if (b or cls != "n") else "normal",
                            slant="italic" if i else "roman")
            self.fonts[name] = (f, key)
            self.txt.tag_configure(name, font=f)
            self.txt.tag_lower(name)
        return name

    def set_font_size(self, size):
        self.font_size = max(7, min(40, int(size)))
        self.base_font.configure(size=self.font_size)
        for f, key in self.fonts.values():
            f.configure(size=self._size_for(key[0], key[3]))
        self._update_spacing()
        self.app.save_soon()

    # ------------------------------------------------------------ 마크다운 표시
    def schedule_hl(self):
        if self._hl_job:
            self.txt.after_cancel(self._hl_job)
        self._hl_job = self.txt.after(15, self._highlight)

    def _set_focus(self, on):
        if self.focused != on:
            self.focused = on
            self.schedule_hl()

    def _on_modified(self, e=None):
        if self.txt.edit_modified():
            self.txt.edit_modified(False)
            self.schedule_hl()
            self.app.save_soon()

    def _highlight(self):
        self._hl_job = None
        t = self.txt
        for tag in t.tag_names():
            if tag != "sel":
                t.tag_remove(tag, "1.0", "end")
        content = t.get("1.0", "end-1c")
        cur_ln, cur_col = self._rc(t.index("insert"))
        # 메모에 포커스가 없으면 기호를 모두 숨기고,
        # 포커스가 있으면 커서가 닿아 있는 서식 부분의 기호만 보여 준다
        if not self.focused:
            cur_ln = 0
        hide_marks = self.app.settings.get("hide_marks", True)
        spans = {}
        in_code = False

        for ln, line in enumerate(content.split("\n"), 1):
            n = len(line)

            def add(tag, a, b, ln=ln):
                if b > a:
                    spans.setdefault(tag, []).extend((f"{ln}.{a}", f"{ln}.{b}"))

            def mark(a, b, hide=True, span=None, ln=ln):
                add("mk", a, b)
                sa, sb = span or (a, b)
                if hide and hide_marks and not (ln == cur_ln and sa <= cur_col <= sb):
                    add("hide", a, b)

            cls = "n"
            fb = [0] * n
            fi = [0] * n
            fm = [0] * n
            start = 0

            if FENCE_RE.match(line):
                in_code = not in_code
                mark(0, n, hide=False)
                fm = [1] * n
            elif in_code:
                add("codebg", 0, n)
                fm = [1] * n
                start = n
            elif HR_RE.match(line):
                add("hr", 0, n)
                start = n
            else:
                m = HEAD_RE.match(line)
                if m:
                    lvl = len(m.group(1))
                    cls = "h1" if lvl == 1 else "h2" if lvl == 2 else "h3"
                    mark(0, m.end(), span=(0, n))
                    add("sp_" + cls, 0, n)
                    start = m.end()
                else:
                    m = QUOTE_RE.match(line)
                    if m:
                        mark(m.start(2), m.end(2), hide=False)
                        add("quote", 0, n)
                        start = m.end()
                    off = start
                    lm = LIST_RE.match(line[off:])
                    if lm:
                        add("bullet", off + lm.start(2), off + lm.end(2))
                        if lm.group(3):
                            cb = off + lm.start(3)
                            add("cbox", cb, cb + 3)
                            if lm.group(3)[1] in "xX":
                                add("done", off + lm.end(), n)
                        start = off + lm.end()

            if start < n:
                self._inline(line, start, fb, fi, fm, add, mark)

            i = 0
            while i < n:
                key = (fb[i], fi[i], fm[i])
                j = i + 1
                while j < n and (fb[j], fi[j], fm[j]) == key:
                    j += 1
                add(self._font_tag((cls,) + key), i, j)
                i = j

        for tag, idx in spans.items():
            t.tag_add(tag, *idx)

    @staticmethod
    def _inline(line, start, fb, fi, fm, add, mark):
        s = list(line)

        def mask(a, b, ch):
            for k in range(a, b):
                s[k] = ch

        for m in CODE_RE.finditer(line, start):
            L = len(m.group(1))
            a, b = m.start(), m.end()
            mark(a, a + L, span=(a, b))
            mark(b - L, b, span=(a, b))
            for k in range(a + L, b - L):
                fm[k] = 1
            add("codebg", a + L, b - L)
            mask(a, a + L, "\x01")
            mask(b - L, b, "\x01")
            mask(a + L, b - L, "\x02")
        for m in LINK_RE.finditer("".join(s), start):
            a, b = m.span()
            ta, tb = m.span(1)
            mark(a, ta, span=(a, b))
            mark(tb, b, span=(a, b))
            add("link", ta, tb)
            mask(a, ta, "\x01")
            mask(tb, b, "\x01")
        for m in URL_RE.finditer("".join(s), start):
            add("link", *m.span())
            mask(*m.span(), "\x02")
        for rx, L, R, flags in INLINE:
            for m in rx.finditer("".join(s), start):
                a, b = m.span()
                mark(a, a + L, span=(a, b))
                mark(b - R, b, span=(a, b))
                mask(a, a + L, "\x01")
                mask(b - R, b, "\x01")
                for f in flags:
                    if f == "b":
                        fb[a + L:b - R] = [1] * (b - R - a - L)
                    elif f == "i":
                        fi[a + L:b - R] = [1] * (b - R - a - L)
                    else:
                        add(f, a + L, b - R)

    # ------------------------------------------------------------ 서식 명령
    def _sel(self):
        try:
            return self.txt.index("sel.first"), self.txt.index("sel.last")
        except tk.TclError:
            return None

    @staticmethod
    def _rc(index):
        r, c = index.split(".")
        return int(r), int(c)

    def _edit(self, fn):
        t = self.txt
        t.edit_separator()
        try:
            fn()
        finally:
            t.edit_separator()
        t.focus_set()
        self.schedule_hl()

    @staticmethod
    def _star_ok(k, L):
        return k == L or k == 3

    def wrap(self, left, right=None):
        right = left if right is None else right
        self._edit(lambda: self._wrap(left, right))

    def _wrap(self, left, right):
        t = self.txt
        r = self._sel()
        L, R = len(left), len(right)
        if not r:
            t.insert("insert", left + right)
            t.mark_set("insert", f"insert-{R}c")
            return
        (l1, c1), (l2, c2) = self._rc(r[0]), self._rc(r[1])
        segs = []
        for ln in range(l1, l2 + 1):
            line = t.get(f"{ln}.0", f"{ln}.end")
            a = c1 if ln == l1 else 0
            b = c2 if ln == l2 else len(line)
            if a == 0:
                pm = PREFIX_RE.match(line)
                if pm:
                    a = max(a, pm.end())
            while a < b and line[a].isspace():
                a += 1
            while b > a and line[b - 1].isspace():
                b -= 1
            if a < b:
                segs.append([ln, a, b, line])
        if not segs:
            return

        star = left.strip("*") == "" and right == left

        def state(seg):
            ln, a, b, line = seg
            inner = line[a:b]
            if star:
                k_in = len(inner) - len(inner.lstrip("*"))
                k_out = 0
                while a - 1 - k_out >= 0 and line[a - 1 - k_out] == "*":
                    k_out += 1
                if len(inner) > 2 * L and self._star_ok(k_in, L) and inner.endswith(left):
                    return "in"
                if self._star_ok(k_out, L) and line[b:b + R] == right:
                    return "out"
                return None
            if len(inner) >= L + R and inner.startswith(left) and inner.endswith(right):
                return "in"
            if line[max(0, a - L):a] == left and line[b:b + R] == right:
                return "out"
            return None

        states = [state(s) for s in segs]
        unwrap = all(states)
        new_a = new_b = None
        for idx in range(len(segs) - 1, -1, -1):
            ln, a, b, line = segs[idx]
            st = states[idx]
            if unwrap:
                if st == "in":
                    t.delete(f"{ln}.{b - R}", f"{ln}.{b}")
                    t.delete(f"{ln}.{a}", f"{ln}.{a + L}")
                    na, nb = a, b - L - R
                else:
                    t.delete(f"{ln}.{b}", f"{ln}.{b + R}")
                    t.delete(f"{ln}.{a - L}", f"{ln}.{a}")
                    na, nb = a - L, b - L
            else:
                if st == "out":
                    na, nb = a - L, b + R
                elif st == "in":
                    na, nb = a, b
                else:
                    t.insert(f"{ln}.{b}", right)
                    t.insert(f"{ln}.{a}", left)
                    na, nb = a, b + L + R
            if idx == len(segs) - 1:
                new_b = f"{ln}.{nb}"
            if idx == 0:
                new_a = f"{ln}.{na}"
        t.tag_remove("sel", "1.0", "end")
        t.tag_add("sel", new_a, new_b)
        t.mark_set("insert", new_b)

    def _line_range(self):
        r = self._sel()
        if r:
            (l1, _), (l2, c2) = self._rc(r[0]), self._rc(r[1])
            if c2 == 0 and l2 > l1:
                l2 -= 1
            return l1, l2, True
        ln = self._rc(self.txt.index("insert"))[0]
        return ln, ln, False

    def _map_lines(self, fn):
        """fn(list_of_lines) -> new list. 선택한 줄(또는 현재 줄)을 바꾼다."""
        def run():
            t = self.txt
            l1, l2, had_sel = self._line_range()
            lines = [t.get(f"{ln}.0", f"{ln}.end") for ln in range(l1, l2 + 1)]
            new = fn(lines)
            for i in range(len(lines) - 1, -1, -1):
                if new[i] != lines[i]:
                    ln = l1 + i
                    t.delete(f"{ln}.0", f"{ln}.end")
                    t.insert(f"{ln}.0", new[i])
            t.tag_remove("sel", "1.0", "end")
            if had_sel:
                t.tag_add("sel", f"{l1}.0", f"{l2}.end")
            t.mark_set("insert", f"{l2}.end")
        self._edit(run)

    def heading(self, level):
        def fn(lines):
            def lvl(s):
                m = HEAD_RE.match(s)
                return len(m.group(1)) if m else 0
            same = level > 0 and all(lvl(s) == level for s in lines if s.strip())
            out = []
            for s in lines:
                body = HEAD_RE.sub("", s, count=1)
                if level and not same and (s.strip() or len(lines) == 1):
                    body = "#" * level + " " + body
                out.append(body)
            return out
        self._map_lines(fn)

    def set_list(self, kind):
        def fn(lines):
            def kind_of(s):
                m = LIST_RE.match(s)
                if not m:
                    return None
                if m.group(3):
                    return "check"
                return "number" if m.group(2)[0].isdigit() else "bullet"
            targets = [s for s in lines if s.strip()] or lines
            same = all(kind_of(s) == kind for s in targets)
            out, n = [], 0
            for s in lines:
                if not s.strip() and len(lines) > 1:
                    out.append(s)
                    continue
                m = LIST_RE.match(s)
                indent = m.group(1) if m else re.match(r"\s*", s).group(0)
                body = s[m.end():] if m else s[len(indent):]
                if same:
                    out.append(indent + body)
                    continue
                n += 1
                prefix = {"bullet": "- ", "check": "- [ ] ", "number": f"{n}. "}[kind]
                out.append(indent + prefix + body)
            return out
        self._map_lines(fn)

    def toggle_quote(self):
        def fn(lines):
            targets = [s for s in lines if s.strip()] or lines
            same = all(QUOTE_RE.match(s) for s in targets)
            out = []
            for s in lines:
                if same:
                    out.append(QUOTE_RE.sub(r"\1", s, count=1))
                elif s.strip() or len(lines) == 1:
                    out.append("> " + s)
                else:
                    out.append(s)
            return out
        self._map_lines(fn)

    def code_block(self):
        def run():
            t = self.txt
            l1, l2, had_sel = self._line_range()
            above = t.get(f"{l1 - 1}.0", f"{l1 - 1}.end") if l1 > 1 else ""
            below = t.get(f"{l2 + 1}.0", f"{l2 + 1}.end")
            if FENCE_RE.match(above) and FENCE_RE.match(below):
                t.delete(f"{l2}.end", f"{l2 + 1}.end")
                t.delete(f"{l1 - 1}.0", f"{l1}.0")
                return
            if not had_sel and not t.get(f"{l1}.0", f"{l1}.end").strip():
                t.delete(f"{l1}.0", f"{l1}.end")
                t.insert(f"{l1}.0", "```\n\n```")
                t.mark_set("insert", f"{l1 + 1}.0")
                return
            t.insert(f"{l2}.end", "\n```")
            t.insert(f"{l1}.0", "```\n")
        self._edit(run)

    def make_link(self):
        def run():
            t = self.txt
            r = self._sel()
            if not r:
                t.insert("insert", "[](https://)")
                t.mark_set("insert", "insert-11c")
                return
            sel = t.get(*r)
            t.delete(*r)
            start = r[0]
            if re.match(r"^(https?://|www\.)\S+$", sel):
                t.insert(start, f"[{sel}]({sel})")
                t.tag_add("sel", f"{start}+1c", f"{start}+{1 + len(sel)}c")
            else:
                t.insert(start, f"[{sel}](https://)")
                a = f"{start}+{len(sel) + 3}c"
                t.tag_add("sel", a, f"{a}+8c")
                t.mark_set("insert", f"{a}+8c")
        self._edit(run)

    def clear_format(self):
        def run():
            t = self.txt
            r = self._sel()
            if not r:
                ln = self._rc(t.index("insert"))[0]
                r = (f"{ln}.0", f"{ln}.end")
            s = t.get(*r)
            new = s
            for _ in range(3):
                new = re.sub(r"(\*\*\*|\*\*|\*|~~|==|`+)(.+?)\1", r"\2", new)
                new = re.sub(r"(?<![\w_])(__|_)(.+?)\1(?![\w_])", r"\2", new)
                new = re.sub(r"<u>(.*?)</u>", r"\1", new)
                new = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", r"\1", new)
            if r[0].endswith(".0"):
                new = re.sub(r"(?m)^(\s*)(#{1,6}\s+|>+ ?)", r"\1", new)
            if new != s:
                t.delete(*r)
                t.insert(r[0], new)
                t.tag_add("sel", r[0], f"{r[0]}+{len(new)}c")
        self._edit(run)

    # ------------------------------------------------------------ 키 입력
    def _on_ctrl(self, e):
        t = self.txt
        shift = bool(e.state & 0x1)
        k = e.keycode
        acts = {
            (66, False): lambda: self.wrap("**"),
            (73, False): lambda: self.wrap("*"),
            (85, False): lambda: self.wrap("<u>", "</u>"),
            (69, False): lambda: self.wrap("`"),
            (75, False): self.make_link,
            (88, True): lambda: self.wrap("~~"),
            (72, True): lambda: self.wrap("=="),
            (48, False): lambda: self.heading(0),
            (49, False): lambda: self.heading(1),
            (50, False): lambda: self.heading(2),
            (51, False): lambda: self.heading(3),
            (56, True): lambda: self.set_list("bullet"),
            (55, True): lambda: self.set_list("number"),
            (57, True): lambda: self.set_list("check"),
            (78, False): lambda: self.app.new_note_from(self),
            (83, False): self.app.save,
            (187, False): lambda: self.set_font_size(self.font_size + 1),
            (189, False): lambda: self.set_font_size(self.font_size - 1),
            (65, False): lambda: (t.tag_add("sel", "1.0", "end-1c"), t.mark_set("insert", "end-1c")),
            (67, False): lambda: t.event_generate("<<Copy>>"),
            (86, False): lambda: t.event_generate("<<Paste>>"),
            (88, False): lambda: t.event_generate("<<Cut>>"),
            (90, False): lambda: t.event_generate("<<Undo>>"),
            (90, True): lambda: t.event_generate("<<Redo>>"),
            (89, False): lambda: t.event_generate("<<Redo>>"),
        }
        fn = acts.get((k, shift))
        if fn:
            fn()
            self.schedule_hl()
            return "break"
        if 65 <= k <= 90:  # Tk 기본 Emacs식 단축키(Ctrl+I=탭 등) 막기
            return "break"
        return None

    def _on_ctrl_wheel(self, e):
        self.set_font_size(self.font_size + (1 if e.delta > 0 else -1))
        return "break"

    def _on_return(self, e):
        t = self.txt
        if self._sel():
            return None
        before = t.get("insert linestart", "insert")
        q = QUOTE_RE.match(before)
        qpre = q.group(0) if q else ""
        m = LIST_RE.match(before[len(qpre):])
        if not m:
            if q and before.strip() == q.group(2).strip():
                t.delete("insert linestart", "insert")
                return "break"
            if q:
                t.insert("insert", "\n" + qpre)
                t.see("insert")
                return "break"
            return None
        if not before[len(qpre) + m.end():].strip():
            t.delete("insert linestart", "insert")
            t.insert("insert", qpre)
            return "break"
        marker = m.group(2)
        if marker[0].isdigit():
            marker = f"{int(marker[:-1]) + 1}{marker[-1]}"
        prefix = qpre + m.group(1) + marker + " " + ("[ ] " if m.group(3) else "")
        t.insert("insert", "\n" + prefix)
        t.see("insert")
        return "break"

    def _on_tab(self, e):
        t = self.txt
        line = t.get("insert linestart", "insert lineend")
        if LIST_RE.match(line):
            t.insert("insert linestart", "    ")
            return "break"
        t.insert("insert", "    ")
        return "break"

    def _on_shift_tab(self, e):
        t = self.txt
        line = t.get("insert linestart", "insert lineend")
        n = len(line) - len(line.lstrip(" "))
        if n:
            t.delete("insert linestart", f"insert linestart+{min(4, n)}c")
        return "break"

    def _on_cbox(self, e):
        t = self.txt
        ln = t.index(f"@{e.x},{e.y}").split(".")[0]
        line = t.get(f"{ln}.0", f"{ln}.end")
        q = QUOTE_RE.match(line)
        off = q.end() if q else 0
        m = LIST_RE.match(line[off:])
        if m and m.group(3):
            pos = off + m.start(3) + 1
            new = " " if line[pos] in "xX" else "x"
            t.edit_separator()
            t.delete(f"{ln}.{pos}")
            t.insert(f"{ln}.{pos}", new)
            t.edit_separator()
            return "break"
        return None

    def _open_link(self, e):
        t = self.txt
        idx = t.index(f"@{e.x},{e.y}")
        ln, col = self._rc(idx)
        line = t.get(f"{ln}.0", f"{ln}.end")
        url = None
        for m in LINK_RE.finditer(line):
            if m.start() <= col <= m.end():
                url = m.group(2)
        if not url:
            for m in URL_RE.finditer(line):
                if m.start() <= col <= m.end():
                    url = m.group(0)
        if url:
            if url.startswith("www."):
                url = "https://" + url
            if re.match(r"^(https?|mailto):", url):
                webbrowser.open(url)
        return "break"

    # ------------------------------------------------------------ 이동 / 크기
    def _drag_start(self, e):
        self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag_move(self, e):
        if self._drag:
            self.win.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _edge(self, x, y):
        w, h = self.frame.winfo_width(), self.frame.winfo_height()
        g = self.M + 3
        e = ""
        if y < g:
            e += "n"
        elif y > h - g:
            e += "s"
        if x < g:
            e += "w"
        elif x > w - g:
            e += "e"
        return e

    CURSORS = {"n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we",
               "ne": "size_ne_sw", "sw": "size_ne_sw", "nw": "size_nw_se", "se": "size_nw_se"}

    def _rs_hover(self, e):
        if not self._rs:
            self.frame.configure(cursor=self.CURSORS.get(self._edge(e.x, e.y), "arrow"))

    def _rs_start(self, e):
        edge = self._edge(e.x, e.y)
        if not edge:
            self._drag_start(e)
            self._rs = None
            return
        self._drag = None
        w = self.win
        self._rs = (edge, e.x_root, e.y_root, w.winfo_x(), w.winfo_y(), w.winfo_width(), w.winfo_height())

    def _rs_move(self, e):
        if not self._rs:
            self._drag_move(e)
            return
        edge, px, py, x, y, w, h = self._rs
        dx, dy = e.x_root - px, e.y_root - py
        mw, mh = int(self.MIN_W * self.app.S), int(self.MIN_H * self.app.S)
        nx, ny, nw, nh = x, y, w, h
        if "e" in edge:
            nw = max(mw, w + dx)
        if "s" in edge:
            nh = max(mh, h + dy)
        if "w" in edge:
            nw = max(mw, w - dx)
            nx = x + w - nw
        if "n" in edge:
            nh = max(mh, h - dy)
            ny = y + h - nh
        self.win.geometry(f"{nw}x{nh}+{nx}+{ny}")

    def _rs_end(self, e):
        self._rs = None
        self._drag = None
        self.app.save_soon()

    # ------------------------------------------------------------ 메뉴
    def _new_menu(self, parent):
        return tk.Menu(parent, tearoff=0, font=self.app.menu_font)

    def _note_items(self, m):
        a = self.app
        m.add_command(label="새 메모", accelerator="Ctrl+N", command=lambda: a.new_note_from(self))
        cm = self._new_menu(m)
        var = tk.StringVar(m, self.color)
        m._keep = [var]
        for name in COLORS:
            cm.add_radiobutton(label=name, variable=var, value=name,
                               command=lambda n=name: self.set_color(n))
        m.add_cascade(label="메모 색상", menu=cm)
        om = self._new_menu(m)
        avar = tk.DoubleVar(m, round(self.alpha, 2))
        m._keep.append(avar)
        for v in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
            om.add_radiobutton(label=f"{int(v * 100)}%", variable=avar, value=v,
                               command=lambda v=v: self.set_alpha(v))
        m.add_cascade(label="투명도", menu=om)
        fm = self._new_menu(m)
        fm.add_command(label="크게", accelerator="Ctrl+=", command=lambda: self.set_font_size(self.font_size + 1))
        fm.add_command(label="작게", accelerator="Ctrl+-", command=lambda: self.set_font_size(self.font_size - 1))
        fm.add_command(label="기본 (11)", command=lambda: self.set_font_size(11))
        m.add_cascade(label=f"글자 크기 ({self.font_size})", menu=fm)
        m.add_separator()
        hv = tk.BooleanVar(m, a.settings.get("hide_marks", True))
        sv = tk.BooleanVar(m, autostart_enabled())
        m._keep += [hv, sv]
        m.add_checkbutton(label="마크다운 기호 숨기기", variable=hv, command=lambda: a.set_hide_marks(hv.get()))
        m.add_checkbutton(label="윈도우 시작 시 자동 실행", variable=sv, command=lambda: set_autostart(sv.get()))
        m.add_separator()
        m.add_command(label="메모 삭제", command=self.delete)
        m.add_command(label="종료", command=a.quit)

    def _popup(self, m, e):
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _bar_menu(self, e):
        m = self._new_menu(self.win)
        self._note_items(m)
        self._popup(m, e)
        return "break"

    def _text_menu(self, e):
        t = self.txt
        if not self._sel():
            t.mark_set("insert", f"@{e.x},{e.y}")
        t.focus_force()
        m = self._new_menu(self.win)
        m.add_command(label="굵게", accelerator="Ctrl+B", command=lambda: self.wrap("**"))
        m.add_command(label="기울임", accelerator="Ctrl+I", command=lambda: self.wrap("*"))
        m.add_command(label="밑줄", accelerator="Ctrl+U", command=lambda: self.wrap("<u>", "</u>"))
        m.add_command(label="취소선", accelerator="Ctrl+Shift+X", command=lambda: self.wrap("~~"))
        m.add_command(label="형광펜", accelerator="Ctrl+Shift+H", command=lambda: self.wrap("=="))
        m.add_command(label="코드", accelerator="Ctrl+E", command=lambda: self.wrap("`"))
        m.add_command(label="링크", accelerator="Ctrl+K", command=self.make_link)
        m.add_separator()
        hm = self._new_menu(m)
        hm.add_command(label="제목 1", accelerator="Ctrl+1", command=lambda: self.heading(1))
        hm.add_command(label="제목 2", accelerator="Ctrl+2", command=lambda: self.heading(2))
        hm.add_command(label="제목 3", accelerator="Ctrl+3", command=lambda: self.heading(3))
        hm.add_command(label="본문", accelerator="Ctrl+0", command=lambda: self.heading(0))
        m.add_cascade(label="제목", menu=hm)
        lm = self._new_menu(m)
        lm.add_command(label="글머리 기호", accelerator="Ctrl+Shift+8", command=lambda: self.set_list("bullet"))
        lm.add_command(label="번호 매기기", accelerator="Ctrl+Shift+7", command=lambda: self.set_list("number"))
        lm.add_command(label="체크박스", accelerator="Ctrl+Shift+9", command=lambda: self.set_list("check"))
        m.add_cascade(label="목록", menu=lm)
        m.add_command(label="인용", command=self.toggle_quote)
        m.add_command(label="코드 블록", command=self.code_block)
        m.add_command(label="서식 지우기", command=self.clear_format)
        m.add_separator()
        has = bool(self._sel())
        st = "normal" if has else "disabled"
        m.add_command(label="잘라내기", accelerator="Ctrl+X", state=st, command=lambda: t.event_generate("<<Cut>>"))
        m.add_command(label="복사", accelerator="Ctrl+C", state=st, command=lambda: t.event_generate("<<Copy>>"))
        m.add_command(label="붙여넣기", accelerator="Ctrl+V", command=lambda: t.event_generate("<<Paste>>"))
        m.add_command(label="모두 선택", accelerator="Ctrl+A",
                      command=lambda: t.tag_add("sel", "1.0", "end-1c"))
        m.add_separator()
        nm = self._new_menu(m)
        self._note_items(nm)
        m.add_cascade(label="메모", menu=nm)
        self._popup(m, e)
        return "break"

    # ------------------------------------------------------------ 삭제
    def delete(self, e=None):
        if self.txt.get("1.0", "end-1c").strip():
            if not messagebox.askyesno("메모 삭제", "이 메모를 삭제할까요?", parent=self.win):
                return
        self.app.remove_note(self)


# ================================================================ App
class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("바탕화면 메모")
        self.root.report_callback_exception = self._log_error
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.S = self.root.winfo_fpixels("1i") / 96.0
        self.menu_font = tkfont.Font(family=BASE_FAMILY, size=10)
        self._save_job = None
        self.notes = []

        data = self._load()
        self.settings = data.get("settings", {})
        for nd in data.get("notes", []):
            self.notes.append(Note(self, nd))
        if not self.notes:
            self.notes.append(Note(self, {"text": WELCOME}))
            self.save()
        self.root.after(400, self._watchdog)

    def _log_error(self, *args):
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            traceback.print_exception(*args, file=f)

    def _load(self):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception:
            try:
                os.replace(DATA_FILE, DATA_FILE + ".broken")
            except OSError:
                pass
            return {}

    def save_soon(self):
        if self._save_job:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(600, self.save)

    def save(self):
        self._save_job = None
        data = {"settings": self.settings, "notes": [n.to_dict() for n in self.notes]}
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, DATA_FILE)

    def new_note_from(self, src=None):
        S = self.S
        if src:
            d = {"x": src.win.winfo_x() + int(28 * S), "y": src.win.winfo_y() + int(28 * S),
                 "w": src.win.winfo_width(), "h": src.win.winfo_height(),
                 "color": src.color, "font_size": src.font_size, "alpha": src.alpha}
        else:
            d = {}
        n = Note(self, d)
        self.notes.append(n)
        n.txt.focus_force()
        self.save_soon()
        return n

    def remove_note(self, note):
        self.notes.remove(note)
        note.win.destroy()
        if not self.notes:
            self.new_note_from(None)
        self.save()

    def set_hide_marks(self, on):
        self.settings["hide_marks"] = bool(on)
        for n in self.notes:
            n.schedule_hl()
        self.save_soon()

    def _watchdog(self):
        """혹시 최소화/숨김 처리되거나 탐색기가 재시작돼도 바탕화면에 다시 붙인다."""
        progman = desktop_window()
        for n in self.notes:
            h = n.hwnd
            if not h:
                continue
            if progman and user32.GetWindowLongPtrW(h, GWLP_HWNDPARENT) != progman:
                pin_to_desktop(h)
            if user32.IsIconic(h) or not user32.IsWindowVisible(h):
                user32.ShowWindow(h, SW_SHOWNOACTIVATE)
        self.root.after(400, self._watchdog)

    def quit(self):
        try:
            self.save()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    mutex = kernel32.CreateMutexW(None, False, "Local\\DesktopMemo_SingleInstance")
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return
    app = App()
    app.run()
    del mutex


if __name__ == "__main__":
    main()
