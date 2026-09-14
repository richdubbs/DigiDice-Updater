"""Small Tk widgets for the DigiDice desktop UI. All animation runs on Tk's loop."""

import ctypes
import sys
import time
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

BG = "#080f14"
PANEL = "#101c25"
BORDER = "#345268"
TEXT = "#f1f6fc"
MUTED = "#a9bdd0"
LIME = "#87f647"
CYAN = "#4bd6ff"
ORANGE = "#ed6207"
BLUE = "#075bfa"
PURPLE = "#7021b9"
RED = "#c52230"


def animations_enabled():
    """Honor Windows' 'Animation effects' accessibility preference."""
    if sys.platform == "win32":
        value = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0):
            return bool(value.value)
    return True


def blend(a, b, amount):
    aa, bb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(aa, bb))


def rounded(canvas, x, y, w, h, radius=10, **kwargs):
    r = min(radius, w / 2, h / 2)
    return canvas.create_polygon(
        x+r, y, x+w-r, y, x+w, y, x+w, y+r, x+w, y+h-r,
        x+w, y+h, x+w-r, y+h, x+r, y+h, x, y+h, x, y+h-r,
        x, y+r, x, y, smooth=True, splinesteps=24, **kwargs)


def label(parent, text="", size=11, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                    font=("Segoe UI", size, "bold" if bold else "normal"),
                    anchor="w", justify="left", **kwargs)


def theme(root):
    root.configure(bg=BG)
    root.option_add("*Font", ("Segoe UI", 10))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                    foreground=TEXT, arrowcolor=CYAN, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, padding=7)
    style.map("TCombobox", fieldbackground=[("disabled", BG), ("readonly", PANEL)],
              foreground=[("disabled", MUTED)], selectbackground=[("!disabled", BLUE)])
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", BLUE)
    style.configure("Horizontal.TProgressbar", background=ORANGE, troughcolor=BG,
                    borderwidth=0, lightcolor=ORANGE, darkcolor=ORANGE)
    style.configure("TScrollbar", background=BORDER, troughcolor=BG, borderwidth=0,
                    arrowcolor=MUTED, darkcolor=BG, lightcolor=BG)
    for name in ("Horizontal.TScrollbar", "Vertical.TScrollbar"):
        style.configure(name, background=BORDER, troughcolor=BG, bordercolor=BG,
                        darkcolor=BORDER, lightcolor=BORDER, arrowcolor=MUTED,
                        borderwidth=0, arrowsize=12)
        style.map(name, background=[("active", "#47748c"), ("!active", BORDER)])


class Button(tk.Canvas):
    """Rounded button with 90ms hover, instant press, and keyboard activation.

    Commands execute on release inside the button, once per click. Animation
    never delays a command. A new state cancels the previous visual tween.
    """
    def __init__(self, parent, text, command=None, color=PANEL, height=42,
                 width=160, size=11, enabled=True, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), height=height, width=width,
                         highlightthickness=0, takefocus=True, **kwargs)
        self.text, self.command, self.color = text, command, color
        self.size, self.enabled = size, enabled
        self._font = tkfont.Font(self, family="Segoe UI", size=size, weight="bold")
        self.hover = self.pressed = self.focused = False
        self._job = None
        self._fill = color if enabled else "#17212a"
        self.motion = animations_enabled()
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda e: self._focus(True))
        self.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<KeyPress-space>", self._key_press)
        self.bind("<KeyRelease-space>", self._key_release)
        self.bind("<KeyPress-Return>", self._key_press)
        self.bind("<KeyRelease-Return>", self._key_release)
        self.bind("<Destroy>", self._destroy)
        self.set_enabled(enabled)

    def _destroy(self, event):
        if event.widget is self and self._job:
            self.after_cancel(self._job)
            self._job = None

    def _target(self):
        if not self.enabled:
            return "#17212a"
        if self.pressed:
            return blend(self.color, "#000000", .27)
        return blend(self.color, "#ffffff", .14) if self.hover else self.color

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        inset = 2 if self.pressed else 0
        edge = CYAN if self.focused else (blend(self.color, "#ffffff", .4) if self.hover else BORDER)
        rounded(self, 1+inset, 1+inset, max(1, w-3-2*inset), max(1, h-3-2*inset),
                fill=self._fill, outline=edge, width=2 if self.focused else 1)
        ink = TEXT if self.enabled else "#7890a3"
        y = h/2 + (1 if self.pressed else 0)
        icon = self.text[0] if self.text.startswith(("↑", "▧")) else None
        caption = self.text[1:].strip() if icon else self.text
        if icon:
            x = (w-self._font.measure(caption)-36)/2
            if icon == "↑":
                self.create_line(x+4, y+4, x+4, y+10, x+24, y+10, x+24, y+4, fill=ink, width=2)
                self.create_line(x+14, y+5, x+14, y-11, fill=ink, width=2)
                self.create_line(x+7, y-4, x+14, y-11, x+21, y-4, fill=ink, width=2)
            else:
                self.create_rectangle(x+2, y-10, x+26, y+10, outline=ink, width=2)
                self.create_line(x+4, y+8, x+11, y-1, x+16, y+4, x+21, y-2, x+25, y+4, fill=ink, width=2)
                self.create_oval(x+18, y-7, x+21, y-4, fill=ink, outline=ink)
            self.create_text(x+36, y, text=caption, anchor="w", fill=ink, font=self._font)
        else:
            self.create_text(w/2, y, text=caption, fill=ink, font=self._font)

    def _animate(self, immediate=False):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        target = self._target()
        if immediate or not self.motion:
            self._fill = target
            self._draw()
            return
        start, began = self._fill, time.monotonic()
        def tick():
            self._job = None
            t = min(1, (time.monotonic() - began) / .09)
            self._fill = blend(start, target, 1 - (1-t)**3)
            self._draw()
            if t < 1:
                self._job = self.after(15, tick)
        tick()

    def _hover(self, inside):
        self.hover = inside
        self._animate()

    def _focus(self, focused):
        self.focused = focused
        if not focused:
            self.pressed = False
        self._animate(immediate=True)

    def _press(self, event=None):
        if self.enabled:
            self.focus_set()
            self.pressed = True
            self._animate(immediate=True)

    def _release(self, event):
        armed = self.pressed
        self.pressed = False
        self._animate()
        if armed and self.enabled and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def _key_press(self, event):
        if not self.pressed:
            self._press()
        return "break"

    def _key_release(self, event):
        armed = self.pressed
        self.pressed = False
        self._animate()
        if armed:
            self.invoke()
        return "break"

    def invoke(self):
        if self.enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not enabled:
            self.pressed = False
        self.configure(cursor="hand2" if enabled else "arrow", takefocus=int(bool(enabled)))
        self._animate(immediate=True)

    def set_text(self, text):
        self.text = text
        self._draw()

    def set_color(self, color):
        self.color = color
        self._animate()


class Card(tk.Canvas):
    """Rounded border surrounding ordinary accessible Tk content."""
    def __init__(self, parent, padding=15, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, **kwargs)
        self.padding = padding
        self.border_color = BORDER
        self.body = tk.Frame(self, bg=PANEL)
        self._window = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self._layout)
        self.body.bind("<Configure>", self._measure)

    def _measure(self, event=None):
        desired = self.body.winfo_reqheight() + self.padding*2
        if int(float(self.cget("height"))) != desired:
            self.configure(height=desired)

    def _layout(self, event=None):
        w = self.winfo_width()
        self.itemconfigure(self._window, width=max(1, w-self.padding*2))
        self.delete("border")
        rounded(self, 1, 1, max(1, w-3), max(1, self.winfo_height()-3),
                fill=PANEL, outline=self.border_color, tags="border")
        self.tag_lower("border")

    def set_border(self, color):
        self.border_color = color
        self.itemconfigure("border", outline=color)


class Scroller(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._scrollbar)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

    def _scrollbar(self, first, last):
        self.bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.bar.pack_forget()
        elif not self.bar.winfo_manager():
            self.bar.pack(side="right", fill="y", before=self.canvas)

    def scroll(self, delta):
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(delta, "units")


class Screens(tk.Frame):
    """120ms directional slide; rapid navigation settles the previous tween."""
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.pages, self.active, self._job = [], None, None
        self.motion = animations_enabled()

    def add(self):
        page = Scroller(self)
        self.pages.append(page)
        return page

    def show(self, index):
        if index == self.active:
            return
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        previous = self.active
        self.active = index
        for page in self.pages:
            page.place_forget()
        page = self.pages[index]
        direction = 1 if previous is None or index > previous else -1
        distance = 22 * direction if self.motion and previous is not None else 0
        page.place(x=distance, y=0, relwidth=1, relheight=1)
        page.lift()
        if not distance:
            return
        began = time.monotonic()
        def tick():
            self._job = None
            t = min(1, (time.monotonic()-began)/.12)
            page.place_configure(x=round(distance*(1-t)**3))
            if t < 1:
                self._job = self.after(15, tick)
        tick()

    def destroy(self):
        if self._job:
            self.after_cancel(self._job)
        super().destroy()


class Steps(tk.Canvas):
    def __init__(self, parent, titles):
        super().__init__(parent, bg=parent.cget("bg"), height=60, highlightthickness=0)
        self.titles, self.active = titles, 0
        self.bind("<Configure>", lambda e: self.draw())

    def set_step(self, active):
        self.active = active
        self.draw()

    def draw(self):
        self.delete("all")
        spacing = max(1, self.winfo_width()) / len(self.titles)
        for i, (title, subtitle) in enumerate(self.titles):
            x = spacing*i + 3
            fill = "#36bb41" if i < self.active else ORANGE if i == self.active else BG
            self.create_oval(x, 12, x+36, 48, fill=fill, outline=MUTED if i > self.active else fill, width=2)
            self.create_text(x+18, 30, text="✓" if i < self.active else str(i+1),
                             fill=TEXT, font=("Segoe UI", 15, "bold"))
            self.create_text(x+47, 23, text=title, anchor="w", fill=TEXT, font=("Segoe UI", 10, "bold"))
            self.create_text(x+47, 43, text=subtitle, anchor="w", fill=MUTED, font=("Segoe UI", 9))
