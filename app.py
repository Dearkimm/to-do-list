# -*- coding: utf-8 -*-
"""할 일 정리 GUI. 실행하면 최신 정리 내용을 즉시 보여준다."""
import ctypes
import json
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

import analyze
import collect

# exe(frozen)면 데이터는 exe 옆, 번들 자산(이미지·폰트)은 _MEIPASS에서 읽는다
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).parent
else:
    BASE = Path(__file__).parent
ASSETS = Path(getattr(sys, "_MEIPASS", BASE))
TASKS_FILE = BASE / "tasks.json"
LATEST = BASE / "latest.txt"
ICON = ASSETS / "app.ico"
WEEKDAYS = "월화수목금토일"


def ensure_fonts():
    """Pretendard가 없는 PC면 번들 폰트를 사용자 계정에 설치한다 (Tk 시작 전 호출)."""
    import ctypes as ct
    import shutil as sh
    import winreg
    fdir = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"
    src_dir = ASSETS / "fonts"
    if not src_dir.exists():
        return
    try:
        fdir.mkdir(parents=True, exist_ok=True)
        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Fonts")
        for otf in src_dir.glob("*.otf"):
            dst = fdir / otf.name
            if not dst.exists():
                sh.copy2(otf, dst)
            name = otf.stem.replace("-", " ") + " (OpenType)"
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(dst))
            ct.windll.gdi32.AddFontResourceW(str(dst))
        winreg.CloseKey(key)
    except Exception:
        pass  # 실패해도 폴백 폰트로 동작

# 고해상도 배율에서 글자가 흐려지지 않게
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# ----- 헬로키티 핑크 팔레트 -----
PALE = "#ffe3ef"       # 창 배경 (키티 핑크)
CARD = "#ffffff"       # 카드 배경
BORDER = "#f6b9d2"     # 핑크 테두리
ACCENT = "#e0447e"     # 진핑크 포인트
SOFT = "#ffd1e3"       # 선택/태그 배경
FG = "#111111"
MUTED = "#b08ba0"

TITLE_MAX = 46  # 할 일 칸 축약 길이


def load_state():
    if TASKS_FILE.exists():
        state = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    else:
        state = {"last_run": None, "seq": 0, "tasks": []}
    state.setdefault("deleted", [])
    # 과거 소프트삭제(status=삭제) 항목은 숨은 삭제 목록으로 이관
    gone = [t for t in state["tasks"] if t["status"] == "삭제"]
    if gone:
        state["tasks"] = [t for t in state["tasks"] if t["status"] != "삭제"]
        state["deleted"] += [t["title"] for t in gone]
    return state


def save_state(state):
    tmp = TASKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(TASKS_FILE)


def parse_sections(text):
    """정리 내용을 [제목] 단위 섹션으로 쪼갠다."""
    sections, title, buf = [], None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]") and 2 < len(s) <= 30:
            if title is not None or any(l.strip() for l in buf):
                sections.append((title or "정리", "\n".join(buf).strip()))
            title, buf = s[1:-1], []
        else:
            buf.append(line)
    if title is not None or any(l.strip() for l in buf):
        sections.append((title or "정리", "\n".join(buf).strip()))
    return sections or [("정리", text.strip())]


class App:
    def __init__(self, root):
        self.root = root
        self.state = load_state()
        self.show_closed = tk.BooleanVar(value=False)
        self.analyzing = False
        self.project_filter = None  # None=전체, ""=미지정, 그 외=프로젝트명

        fams = set(tkfont.families())
        if "Pretendard" in fams:
            BODY = "Pretendard"
        elif "Noto Sans KR" in fams:
            BODY = "Noto Sans KR"
        else:
            BODY = "맑은 고딕"
        self.F_TITLE = (BODY, 20, "bold")
        self.F_CLOCK = (BODY, 11, "bold")
        self.F = (BODY, 10)
        self.F_B = (BODY, 10, "bold")
        self.F_S = (BODY, 9)
        self.F_T = (BODY, 8)
        self.F_TB = (BODY, 8, "bold")
        self.F_COUNT = (BODY, 14, "bold")

        s = root.winfo_fpixels("1i") / 96.0  # 화면 배율
        self.scale = s
        root.title("Work Status")
        root.geometry(f"{int(820 * s)}x{int(760 * s)}")
        root.minsize(int(640 * s), int(520 * s))
        root.configure(bg=PALE)
        try:
            root.iconbitmap(str(ICON))
        except Exception:
            pass

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=FG, font=self.F, rowheight=int(30 * s),
                        borderwidth=0)
        style.configure("Treeview.Heading", background=CARD, foreground=MUTED,
                        font=self.F_S, relief="flat")
        # 기본 테마는 헤더 이미지를 우측 끝에 붙이므로 좌측으로 재배치
        style.layout("Treeview.Heading", [
            ("Treeheading.cell", {"sticky": "nswe"}),
            ("Treeheading.border", {"sticky": "nswe", "children": [
                ("Treeheading.padding", {"sticky": "nswe", "children": [
                    ("Treeheading.image", {"side": "left", "sticky": ""}),
                    ("Treeheading.text", {"sticky": "we"}),
                ]}),
            ]}),
        ])
        style.map("Treeview", background=[("selected", SOFT)],
                  foreground=[("selected", FG)])
        style.configure("Vertical.TScrollbar", background=SOFT, troughcolor=PALE,
                        bordercolor=PALE, arrowcolor=ACCENT)
        style.configure("TNotebook", background=CARD, borderwidth=0)
        style.configure("TNotebook.Tab", font=self.F_S, padding=[14, 5],
                        background=SOFT, foreground="#9c6a82", borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", CARD)],
                  foreground=[("selected", ACCENT)])

        # ----- 헤더 (키티+제목 좌측, 실시간 시계 우측 — 상하 중앙 정렬) -----
        header = tk.Frame(root, bg=PALE)
        header.pack(fill="x", padx=20, pady=(16, 4))
        try:
            img = Image.open(ASSETS / "kitty.png")
            kh = int(44 * s)
            kw = int(kh * img.size[0] / img.size[1])
            self.kitty_img = ImageTk.PhotoImage(
                img.resize((kw, kh), Image.LANCZOS))
            tk.Label(header, image=self.kitty_img, bg=PALE).pack(side="left",
                                                                 padx=(0, 10))
        except Exception:
            pass
        tk.Label(header, text="TO-DO LIST", font=self.F_TITLE, bg=PALE,
                 fg=FG).pack(side="left")
        self.clock_lbl = tk.Label(header, text="", font=self.F_CLOCK, bg=PALE,
                                  fg=ACCENT)
        self.clock_lbl.pack(side="right")
        self._tick()

        # ----- 하단 버튼/상태 (창 크기와 무관하게 항상 보이도록 먼저 배치) -----
        self.status_lbl = tk.Label(root, text="", font=self.F_T, bg=PALE,
                                   fg=MUTED, anchor="w")
        self.status_lbl.pack(side="bottom", fill="x", padx=21, pady=(0, 8))
        bar = tk.Frame(root, bg=PALE)
        bar.pack(side="bottom", fill="x", padx=20, pady=(8, 4))
        for text, cmd in (("수정", self.edit_task),
                          ("완료", lambda: self.set_status("완료")),
                          ("보류", self.toggle_hold),
                          ("삭제", self.delete_task)):
            self.pink_button(bar, text, cmd).pack(side="left", padx=(0, 6))
        self.pink_button(bar, "전체 검색", self.open_search).pack(side="right")
        self.btn_analyze = self.pink_button(bar, "새로고침", self.run_analyze)
        self.btn_analyze.pack(side="right", padx=(0, 6))

        # ----- 정리 탭 -----
        bc = tk.Frame(root, bg=CARD, highlightthickness=1,
                      highlightbackground=BORDER)
        bc.pack(fill="x", padx=20, pady=(8, 0))
        self.nb = ttk.Notebook(bc)
        self.nb.pack(fill="both", expand=True, padx=2, pady=2)

        # ----- 할 일 카드 -----
        tc = tk.Frame(root, bg=CARD, highlightthickness=1,
                      highlightbackground=BORDER)
        tc.pack(fill="both", expand=True, padx=20, pady=(10, 0))
        th = tk.Frame(tc, bg=CARD)
        th.pack(fill="x", padx=12, pady=(10, 2))
        tk.Label(th, text="처리 상태", font=self.F_B, bg=CARD,
                 fg=FG).pack(side="left")
        self.count_lbl = tk.Label(th, text="0", font=self.F_COUNT, bg=CARD,
                                  fg=ACCENT)
        self.count_lbl.pack(side="left", padx=(8, 0))
        tk.Checkbutton(th, text="완료 표시", variable=self.show_closed,
                       command=self.refresh_table, bg=CARD, fg=MUTED,
                       font=self.F_S, activebackground=CARD,
                       selectcolor=CARD).pack(side="right")
        tk.Label(tc, text="체크박스를 누르면 완료, 항목을 더블클릭하면 상세 내용이 열립니다.",
                 font=self.F_T, bg=CARD, fg=MUTED,
                 anchor="e").pack(fill="x", padx=12)

        # 하단 추가 링크를 먼저 고정해 창이 작아도 잘리지 않게 한다
        add = tk.Label(tc, text="+ 작업 추가", font=self.F_S, bg=CARD, fg=ACCENT,
                       anchor="w", cursor="hand2")
        add.pack(side="bottom", fill="x", padx=12, pady=(2, 8))
        add.bind("<Button-1>", lambda e: self.add_task())

        self.chk_on, self.chk_off = self._make_checks()
        tf = tk.Frame(tc, bg=CARD)
        tf.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        cols = ("status", "due", "title", "project")
        self.tree = ttk.Treeview(tf, columns=cols, show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="완료")
        self.tree.column("#0", width=int(52 * s), stretch=False)
        for col, text, w, anchor, stretch in (
            ("status", "상태", 50, "center", False),
            ("due", "기한", 86, "center", False),
            ("title", "할 일", 380, "w", True),
            ("project", "프로젝트", 130, "w", False),
        ):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=int(w * s), anchor=anchor, stretch=stretch)
        self._proj_head_img = self._heading_image("프로젝트")
        self.tree.heading("project", text="", image=self._proj_head_img,
                          anchor="w", command=self.project_menu)
        tsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tree.tag_configure("urgent", foreground=ACCENT)
        self.tree.tag_configure("closed", foreground=MUTED)
        self.tree.tag_configure("hold", foreground="#b08ba0")
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Double-1>", lambda e: self.show_detail())

        self.load_briefing()
        self.refresh_table()
        self.maybe_auto_analyze()

    def _tick(self):
        now = datetime.now()
        self.clock_lbl.configure(
            text=f"{now:%Y.%m.%d} · {WEEKDAYS[now.weekday()]} · {now:%H:%M}")
        self.root.after(1000, self._tick)

    def pink_button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, font=self.F_S, bg=CARD,
                         fg=ACCENT, activebackground=SOFT, activeforeground=ACCENT,
                         relief="solid", borderwidth=1, padx=12, pady=2,
                         cursor="hand2")

    # ----- 데이터 표시 -----
    def load_briefing(self):
        if LATEST.exists():
            lines = LATEST.read_text(encoding="utf-8").splitlines()
            text = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        else:
            text = "아직 정리된 내용이 없습니다. [새로고침]을 눌러 만드세요."
        for tab in self.nb.tabs():
            self.nb.forget(tab)
        s = self.scale
        for title, body in parse_sections(text):
            frame = tk.Frame(self.nb, bg=CARD)
            txt = tk.Text(frame, height=9, font=self.F, bg=CARD, fg=FG,
                          wrap="word", relief="flat", padx=14, pady=12,
                          spacing2=int(3 * s), spacing3=int(2 * s),
                          selectbackground=SOFT, selectforeground=FG)
            sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            txt.tag_configure("bullet", foreground=ACCENT, font=self.F_B)
            txt.tag_configure("item", lmargin1=int(6 * s),
                              lmargin2=int(22 * s), spacing1=int(7 * s))
            txt.tag_configure("plain", spacing1=int(5 * s))
            for line in (body or "(내용 없음)").splitlines():
                st = line.strip()
                if st.startswith("- "):
                    txt.insert("end", "•  ", ("item", "bullet"))
                    txt.insert("end", st[2:] + "\n", ("item",))
                elif st:
                    txt.insert("end", st + "\n", ("plain",))
            txt.configure(state="disabled")
            txt.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.nb.add(frame, text=f" {title} ")

    def project_menu(self):
        menu = tk.Menu(self.root, tearoff=0, bg=CARD, fg=FG, font=self.F_S,
                       activebackground=SOFT, activeforeground=ACCENT,
                       relief="flat", borderwidth=1)
        projects = sorted({t.get("project") or "" for t in self.state["tasks"]})

        def label(name, value):
            mark = "✓ " if self.project_filter == value else "   "
            return mark + name

        menu.add_command(label=label("전체", None),
                         command=lambda: self.set_project_filter(None))
        for p in projects:
            name = p if p else "(미지정)"
            menu.add_command(label=label(name, p),
                             command=lambda v=p: self.set_project_filter(v))
        menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def set_project_filter(self, value):
        self.project_filter = value
        if value is None:
            label = "프로젝트"
        else:
            name = value if value else "(미지정)"
            label = name[:8] + "…" if len(name) > 8 else name
        self._proj_head_img = self._heading_image(label)
        self.tree.heading("project", text="", image=self._proj_head_img)
        self.refresh_table()

    def visible_tasks(self):
        tasks = self.state["tasks"]
        if self.project_filter is not None:
            tasks = [t for t in tasks
                     if (t.get("project") or "") == self.project_filter]
        if not self.show_closed.get():
            tasks = [t for t in tasks if t["status"] in ("진행", "보류")]
        # 완료 표시가 켜져 있으면 완료를 위에 모아서 보여준다
        return sorted(tasks, key=lambda t: (
            0 if t["status"] == "완료" else 1,
            t.get("due") is None, t.get("due") or "", t.get("created", "")))

    def _due_display(self, due):
        if not due:
            return "", ()
        today = f"{datetime.now():%Y-%m-%d}"
        tomorrow = f"{datetime.now() + timedelta(days=1):%Y-%m-%d}"
        if due < today:
            return f"{due[5:].replace('-', '.')} 지남", ("urgent",)
        if due == today:
            return "오늘", ("urgent",)
        if due == tomorrow:
            return "내일", ()
        return due[5:].replace("-", "."), ()

    def _heading_image(self, label):
        """'라벨 + 중간 크기 핑크 ▼'를 한 장의 헤더 이미지로 렌더링."""
        s, n = self.scale, 4
        fpx = int(12 * s) * n  # 9pt 상당
        try:
            f = ImageFont.truetype(str(ASSETS / "fonts" /
                                       "Pretendard-Regular.otf"), fpx)
        except Exception:
            f = ImageFont.truetype("malgun.ttf", fpx)
        tb = ImageDraw.Draw(Image.new("RGBA", (4, 4))).textbbox((0, 0), label,
                                                                font=f)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tri_w, tri_h = int(9 * s) * n, int(6 * s) * n
        gap = int(5 * s) * n
        W, H = tw + gap + tri_w, max(th, tri_h)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((-tb[0], -tb[1]), label, font=f, fill=MUTED)
        y0 = (H - tri_h) // 2 + int(1 * s) * n
        d.polygon([(tw + gap, y0), (W - 1, y0),
                   (tw + gap + tri_w // 2, min(y0 + tri_h, H) - 1)], fill=ACCENT)
        return ImageTk.PhotoImage(img.resize((W // n, H // n), Image.LANCZOS))

    def _make_checks(self):
        """이미지 기반 체크박스 (미완료: 흰 박스, 완료: 핑크 채움 + 흰 체크)."""
        size = int(19 * self.scale)

        def make(on):
            n = size * 4
            img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            r = int(n * 0.28)
            if on:
                d.rounded_rectangle([2, 2, n - 3, n - 3], radius=r, fill=ACCENT)
                d.line([(n * 0.26, n * 0.54), (n * 0.44, n * 0.71),
                        (n * 0.75, n * 0.31)], fill="white",
                       width=int(n * 0.11), joint="curve")
            else:
                d.rounded_rectangle([2, 2, n - 3, n - 3], radius=r, fill="white",
                                    outline=BORDER, width=int(n * 0.08))
            return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))

        return make(True), make(False)

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        open_count = hold_count = 0
        for t in self.visible_tasks():
            done = t["status"] == "완료"
            due_text, tags = self._due_display(t.get("due"))
            if done:
                tags = ("closed",)
            elif t["status"] == "보류":
                tags = ("hold",)
                hold_count += 1
            else:
                open_count += 1
            title = t["title"]
            if len(title) > TITLE_MAX:
                title = title[:TITLE_MAX] + "…"
            self.tree.insert("", "end", iid=t["id"], tags=tags,
                             image=self.chk_on if done else self.chk_off,
                             values=(t["status"], due_text, title,
                                     t.get("project") or ""))
        self.count_lbl.configure(text=str(open_count))
        last = self.state.get("last_run")
        if last:
            dt = datetime.fromisoformat(last)
            self.status_lbl.configure(
                text=f"문서 상태: 저장됨 · 마지막 분석 {dt:%m-%d %H:%M}")

    def find_task(self, tid):
        return next((t for t in self.state["tasks"] if t["id"] == tid), None)

    def selected(self):
        sel = self.tree.selection()
        return self.find_task(sel[0]) if sel else None

    # ----- 클릭 동작 -----
    def on_click(self, event):
        if self.tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return
        if self.tree.identify_column(event.x) == "#0":  # 체크박스 칸
            row = self.tree.identify_row(event.y)
            t = self.find_task(row)
            if t:
                t["status"] = "진행" if t["status"] == "완료" else "완료"
                t["updated"] = f"{datetime.now():%Y-%m-%d %H:%M}"
                t.pop("auto_note", None)
                save_state(self.state)
                self.refresh_table()
            return "break"

    def show_detail(self):
        t = self.selected()
        if not t:
            return
        s = self.scale
        win = tk.Toplevel(self.root)
        win.title("상세")
        win.configure(bg=CARD, highlightthickness=1,
                      highlightbackground=BORDER)
        win.geometry(f"+{self.root.winfo_pointerx() + 12}"
                     f"+{self.root.winfo_pointery() + 12}")
        win.transient(self.root)
        try:
            win.iconbitmap(str(ICON))
        except Exception:
            pass
        meta = " · ".join(x for x in (t["status"], t.get("project"),
                                      t.get("due") and f'기한 {t["due"]}') if x)
        tk.Label(win, text=meta, font=self.F_TB, bg=CARD, fg=ACCENT,
                 anchor="w", justify="left").pack(fill="x", padx=16, pady=(12, 2))
        tk.Label(win, text=t["title"], font=self.F_B, bg=CARD, fg=FG,
                 anchor="w", justify="left",
                 wraplength=int(420 * s)).pack(fill="x", padx=16)
        if t.get("note") or t.get("auto_note"):
            tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=16,
                                                    pady=(10, 0))
            block = tk.Frame(win, bg="#fff5f9")
            block.pack(fill="x", padx=16, pady=(10, 0))
            tk.Label(block, text="상세 메모", font=self.F_TB, bg="#fff5f9",
                     fg=ACCENT, anchor="w").pack(fill="x", padx=10, pady=(8, 0))
            if t.get("note"):
                tk.Label(block, text=t["note"], font=self.F_S, bg="#fff5f9",
                         fg=FG, anchor="w", justify="left",
                         wraplength=int(400 * s)).pack(fill="x", padx=10,
                                                       pady=(2, 8))
            if t.get("auto_note"):
                tk.Label(block, text=t["auto_note"], font=self.F_T,
                         bg="#fff5f9", fg=MUTED, anchor="w", justify="left",
                         wraplength=int(400 * s)).pack(fill="x", padx=10,
                                                       pady=(0, 8))
        btns = tk.Frame(win, bg=CARD)
        btns.pack(fill="x", padx=16, pady=12)

        def edit():
            win.destroy()
            self.task_dialog(t)

        self.pink_button(btns, "수정", edit).pack(side="left")
        self.pink_button(btns, "닫기", win.destroy).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())

    # ----- 할 일 편집 -----
    def set_status(self, status):
        t = self.selected()
        if not t:
            return
        t["status"] = status
        t["updated"] = f"{datetime.now():%Y-%m-%d %H:%M}"
        t.pop("auto_note", None)
        save_state(self.state)
        self.refresh_table()

    def toggle_hold(self):
        t = self.selected()
        if t:
            self.set_status("진행" if t["status"] == "보류" else "보류")

    def delete_task(self):
        t = self.selected()
        if not t:
            return
        if not messagebox.askyesno("삭제",
                                   f'"{t["title"]}"\n\n정말 삭제할까요? '
                                   "목록에서 완전히 사라집니다."):
            return
        self.state["tasks"].remove(t)
        self.state["deleted"].append(t["title"])  # 재추가 방지용 숨은 목록
        save_state(self.state)
        self.refresh_table()

    def add_task(self):
        self.task_dialog(None)

    def edit_task(self):
        t = self.selected()
        if t:
            self.task_dialog(t)

    def task_dialog(self, task):
        win = tk.Toplevel(self.root)
        win.title("작업 추가" if task is None else "작업 수정")
        win.configure(bg=PALE)
        win.grab_set()
        try:
            win.iconbitmap(str(ICON))
        except Exception:
            pass
        fields = {}
        for i, (key, label) in enumerate((("title", "할 일"), ("project", "프로젝트"),
                                          ("due", "기한 (YYYY-MM-DD)"), ("note", "메모"))):
            tk.Label(win, text=label, font=self.F_S, bg=PALE, fg=MUTED,
                     anchor="w").grid(row=i, column=0, sticky="w", padx=14,
                                      pady=(10, 0))
            e = tk.Entry(win, font=self.F, width=48, relief="flat", bg=CARD, fg=FG,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
            e.grid(row=i, column=1, padx=(0, 14), pady=(10, 0))
            if task:
                e.insert(0, task.get(key) or "")
            fields[key] = e
        fields["title"].focus_set()

        def ok():
            title = fields["title"].get().strip()
            if not title:
                messagebox.showwarning("확인", "할 일 내용을 입력하세요.", parent=win)
                return
            due = fields["due"].get().strip() or None
            if due:
                try:
                    datetime.strptime(due, "%Y-%m-%d")
                except ValueError:
                    messagebox.showwarning("확인", "기한은 YYYY-MM-DD 형식으로 입력하세요.",
                                           parent=win)
                    return
            now = f"{datetime.now():%Y-%m-%d %H:%M}"
            if task is None:
                self.state["seq"] += 1
                self.state["tasks"].append({
                    "id": f'T{self.state["seq"]:03d}', "title": title,
                    "project": fields["project"].get().strip(), "due": due,
                    "note": fields["note"].get().strip(), "status": "진행",
                    "source": "manual", "created": now, "updated": now,
                })
            else:
                task.update(title=title, project=fields["project"].get().strip(),
                            due=due, note=fields["note"].get().strip(), updated=now)
                task["source"] = "manual"
            save_state(self.state)
            self.refresh_table()
            win.destroy()

        self.pink_button(win, "저장", ok).grid(row=4, column=1, sticky="e",
                                               padx=(0, 14), pady=12)

    # ----- 분석 실행 -----
    def maybe_auto_analyze(self):
        last = self.state.get("last_run")
        if last is None:
            return
        hours = (datetime.now().astimezone()
                 - datetime.fromisoformat(last)).total_seconds() / 3600
        if hours > 20:
            self.run_analyze(auto=True)

    def run_analyze(self, auto=False):
        if self.analyzing:
            return
        self.analyzing = True
        self.btn_analyze.configure(state="disabled")
        note = "정리가 오래되어 자동 새로고침을 시작했습니다" if auto else "새로고침 중"
        self.status_lbl.configure(text=f"{note}… 2~4분 걸립니다.")

        def work():
            try:
                analyze.run()
                err = None
            except Exception as e:
                err = str(e)
                try:
                    analyze.log(f"GUI 분석 오류: {e!r}")
                except Exception:
                    pass
            self.root.after(0, lambda: self.analyze_done(err))

        threading.Thread(target=work, daemon=True).start()

    def analyze_done(self, err):
        self.analyzing = False
        self.btn_analyze.configure(state="normal")
        if err:
            self.status_lbl.configure(text=f"새로고침 실패: {err[:80]}")
            return
        self.state = load_state()
        self.load_briefing()
        self.refresh_table()

    # ----- 전체 검색 -----
    def open_search(self):
        win = tk.Toplevel(self.root)
        win.title("전체 세션 검색")
        s = self.scale
        win.geometry(f"{int(720 * s)}x{int(480 * s)}")
        win.configure(bg=PALE)
        try:
            win.iconbitmap(str(ICON))
        except Exception:
            pass
        top = tk.Frame(win, bg=PALE)
        top.pack(fill="x", padx=14, pady=10)
        entry = tk.Entry(top, font=self.F, relief="flat", bg=CARD, fg=FG,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=ACCENT)
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        entry.focus_set()
        out = tk.Text(win, font=self.F_S, bg=CARD, fg=FG, wrap="word",
                      relief="flat", highlightthickness=1,
                      highlightbackground=BORDER, padx=10, pady=8,
                      selectbackground=SOFT)
        out.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        out.tag_configure("head", foreground=ACCENT)

        def do_search(*_):
            kw = entry.get().strip()
            if not kw:
                return
            out.delete("1.0", "end")
            out.insert("end", "검색 중… (전체 기록을 훑으므로 수십 초 걸릴 수 있음)\n")

            def work():
                hits = collect.search(kw)
                def show():
                    out.delete("1.0", "end")
                    if not hits:
                        out.insert("end", "검색 결과가 없습니다.\n")
                    for ts, proj, role, snip in hits:
                        out.insert("end", f"{ts:%Y-%m-%d %H:%M} [{proj}] {role}\n",
                                   "head")
                        out.insert("end", f"  {snip}\n\n")
                win.after(0, show)

            threading.Thread(target=work, daemon=True).start()

        entry.bind("<Return>", do_search)
        self.pink_button(top, "검색", do_search).pack(side="left", padx=(8, 0))


def install_schedule():
    """이 exe를 매일 08:50 자동 분석으로 작업 스케줄러에 등록."""
    exe = sys.executable if getattr(sys, "frozen", False) else None
    if not exe:
        raise RuntimeError("스케줄 등록은 exe 버전에서만 지원합니다.")
    subprocess.run(
        ["schtasks", "/Create", "/TN", "WorkStatusDaily", "/SC", "DAILY",
         "/ST", "08:50", "/F", "/TR", f'"{exe}" --analyze'],
        check=True, creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    if "--analyze" in sys.argv:  # 스케줄러용 무화면 분석
        analyze.run()
        sys.exit(0)
    ensure_fonts()
    root = tk.Tk()
    if "--install-schedule" in sys.argv:
        root.withdraw()
        try:
            install_schedule()
            messagebox.showinfo("Work Status",
                                "매일 08:50 자동 분석이 등록되었습니다.")
        except Exception as e:
            messagebox.showerror("Work Status", f"등록 실패: {e}")
        sys.exit(0)
    App(root)
    root.mainloop()
