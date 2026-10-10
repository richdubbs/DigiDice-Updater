"""Small Tk widgets for the DigiDice desktop UI. All animation runs on Tk's loop."""

import ctypes
import math
import random
import sys
import time
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from PIL import Image, ImageOps, ImageTk

BG = "#080f14"
PANEL = "#101c25"
BORDER = "#345268"
TEXT = "#f1f6fc"
MUTED = "#a9bdd0"
LIME = "#87f647"
CYAN = "#4bd6ff"
ORANGE = "#ff7000"
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
                 width=160, size=11, enabled=True, navigation=False, **kwargs):
        super().__init__(parent, bg=parent.cget("bg"), height=height, width=width,
                         highlightthickness=0, takefocus=True, **kwargs)
        self.text, self.command, self.color = text, command, color
        self.size, self.enabled = size, enabled
        self.navigation = navigation
        self.selected = False
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
        if self.navigation:
            self.create_rectangle(0, 0, w, h, fill=self._fill,
                                  outline=CYAN if self.focused else self._fill)
            if self.selected:
                self.create_rectangle(0, 0, 4, h, fill=ORANGE, outline=ORANGE)
        else:
            rounded(self, 1+inset, 1+inset, max(1, w-3-2*inset), max(1, h-3-2*inset),
                    fill=self._fill, outline=edge, width=2 if self.focused else 1)
        ink = TEXT if self.enabled else "#7890a3"
        y = h/2 + (1 if self.pressed else 0)
        icon = self.text[0] if self.text.startswith(("↑", "▧")) else None
        caption = self.text[1:].strip() if icon else self.text
        if icon:
            x = 22 if self.navigation else (w-self._font.measure(caption)-36)/2
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
            self.create_text(26 if self.navigation else w/2, y, text=caption,
                             anchor="w" if self.navigation else "center", fill=ink, font=self._font)

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

    def set_selected(self, selected):
        self.selected = selected
        self.set_color("#192e3e" if selected else PANEL)


def _wrap_resize(image, size):
    """Resize a tiling image so it still tiles: resample across its own seams."""
    w, h = image.size
    sheet = Image.new(image.mode, (w*3, h*3))
    for i in range(3):
        for j in range(3):
            sheet.paste(image, (i*w, j*h))
    sheet = sheet.resize((size*3, size*3), Image.Resampling.BICUBIC)
    return sheet.crop((size, size, size*2, size*2))


def _fractal(rng, base, octaves):
    out = total = None
    for cells, weight in octaves:
        grid = Image.frombytes("L", (cells, cells), bytes(rng.randrange(256) for _ in range(cells*cells)))
        layer = _wrap_resize(grid, base)
        if out is None:
            out, total = layer, weight
        else:
            total += weight
            out = Image.blend(out, layer, weight/total)
    return ImageOps.autocontrast(out, cutoff=1)


def smoke_texture(size=1024, seed=7, base=160):
    """A seamlessly tiling sheet of dark smoke: fractal noise, domain-warped.

    Built small and scaled up, so it takes about 60ms, once, at startup.
    """
    rng = random.Random(seed)
    octaves = ((2, 8), (4, 5), (8, 3), (16, 1.5), (32, .6))
    field = _fractal(rng, base, octaves).tobytes()
    wx = _fractal(rng, base, octaves[:3]).tobytes()
    wy = _fractal(rng, base, octaves[:3]).tobytes()
    reach = base * .45 / 255
    warped = bytearray(base*base)
    for i in range(base*base):
        x = int(i % base + (wx[i]-128)*reach) % base
        y = int(i // base + (wy[i]-128)*reach) % base
        warped[i] = field[y*base + x]
    smoke = Image.frombytes("L", (base, base), bytes(warped)).point(lambda v: int(255 * (v/255) ** 1.6))
    return ImageOps.colorize(_wrap_resize(smoke, size), black=BG, mid="#12304a",
                             white="#2e6a8c", midpoint=135)


class Smoke:
    """Slowly drifting smoke behind the pages.

    Tk has no shaders and its frames are opaque, so the texture is built once
    and each surface that shows it is a Canvas holding tiles of that one image,
    positioned from where the canvas sits in the window. The surfaces read as
    one continuous sheet, through page slides and scrolling too, and a tick
    only moves tiles: nothing is ever redrawn into the image.
    """
    SPEED = (9.0, 4.0)  # px/s

    def __init__(self, root, tile=1024):
        self.root, self.tile = root, tile
        self.image = ImageTk.PhotoImage(smoke_texture(tile), master=root)
        self.surfaces = {}
        self.drift = (0, 0)
        self.began = time.monotonic()
        self._job = None
        if animations_enabled():
            self._job = root.after(33, self._tick)

    def attach(self, canvas):
        self.surfaces[canvas] = []
        canvas.bind("<Configure>", lambda e: self.paint(canvas), add="+")
        canvas.bind("<Destroy>", lambda e: e.widget is canvas and self.surfaces.pop(canvas, None), add="+")
        self.paint(canvas)

    def paint(self, canvas):
        tiles = self.surfaces.get(canvas)
        if tiles is None:
            return
        t = self.tile
        across = canvas.winfo_width() // t + 2
        down = canvas.winfo_height() // t + 2
        while len(tiles) < across*down:
            tiles.append(canvas.create_image(0, 0, image=self.image, anchor="nw", tags="smoke"))
            canvas.tag_lower(tiles[-1])
        x = canvas.winfo_rootx() - self.root.winfo_rootx() + self.drift[0]
        y = canvas.winfo_rooty() - self.root.winfo_rooty() + self.drift[1]
        left, top = canvas.canvasx(0) - x % t, canvas.canvasy(0) - y % t
        for i, item in enumerate(tiles):
            canvas.coords(item, left + (i % across)*t, top + (i // across)*t)

    def _tick(self):
        elapsed = time.monotonic() - self.began
        drift = (math.floor(elapsed*self.SPEED[0]), math.floor(elapsed*self.SPEED[1]))
        if drift != self.drift and self.root.state() != "iconic":
            self.drift = drift
            for canvas in list(self.surfaces):
                self.paint(canvas)
        self._job = self.root.after(33, self._tick)

    def stop(self):
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None


class CanvasText:
    """A canvas text item that answers configure() and cget() like a Label."""
    def __init__(self, canvas, item, changed=None):
        self.canvas, self.item, self.changed = canvas, item, changed

    def configure(self, cnf=None, **kwargs):
        kwargs = {**(cnf or {}), **kwargs}
        options = {"fill" if key == "fg" else key: value for key, value in kwargs.items()}
        self.canvas.itemconfigure(self.item, **options)
        if self.changed:
            self.changed()

    config = configure

    def cget(self, key):
        return self.canvas.itemcget(self.item, "fill" if key == "fg" else key)


class Card:
    """Rounded panel drawn on a page's canvas, holding ordinary accessible Tk content."""
    def __init__(self, page, padding=15):
        self.page, self.padding = page, padding
        self.border_color = BORDER
        self.tag = f"card{id(self)}"
        self.body = tk.Frame(page.canvas, bg=PANEL)
        self._window = page.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: page.schedule(), add="+")

    def place_at(self, x, y, width):
        canvas, p = self.page.canvas, self.padding
        height = self.body.winfo_reqheight() + p*2
        canvas.coords(self._window, x + p, y + p)
        canvas.itemconfigure(self._window, width=max(1, width - p*2))
        canvas.delete(self.tag)
        rounded(canvas, x + 1, y + 1, max(1, width - 3), max(1, height - 3),
                fill=PANEL, outline=self.border_color, tags=self.tag)
        canvas.tag_lower(self.tag)
        canvas.tag_lower("smoke")
        return height

    def set_border(self, color):
        self.border_color = color
        self.page.canvas.itemconfigure(self.tag, outline=color)


class Scroller(tk.Frame):
    """One page: cards stacked down a canvas the smoke shows through."""
    MARGIN = (18, 18, 20, 6)  # left, top, right, bottom

    def __init__(self, parent, smoke):
        super().__init__(parent, bg=BG)
        self.smoke = smoke
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._scrollbar)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.entries = []
        self._job = None
        smoke.attach(self.canvas)
        self.canvas.bind("<Configure>", lambda e: self.layout(), add="+")
        # A slide moves this frame, not the canvas inside it.
        self.bind("<Configure>", lambda e: smoke.paint(self.canvas), add="+")

    def card(self, padding=15, gap=14):
        card = Card(self, padding)
        self.entries.append((card, gap))
        self.schedule()
        return card

    def schedule(self):
        if not self._job:
            self._job = self.after_idle(self.layout)

    def layout(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        canvas = self.canvas
        left, top, right, bottom = self.MARGIN
        width = max(1, canvas.winfo_width() - left - right)
        y = top
        for card, gap in self.entries:
            y += card.place_at(left, y, width) + gap
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), y + bottom))

    def _scrollbar(self, first, last):
        self.bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.bar.pack_forget()
        elif not self.bar.winfo_manager():
            self.bar.pack(side="right", fill="y", before=self.canvas)
        self.smoke.paint(self.canvas)

    def scroll(self, delta):
        region = self.canvas.cget("scrollregion").split()
        if region and float(region[3]) > self.canvas.winfo_height():
            self.canvas.yview_scroll(delta, "units")


class StatusBar(tk.Canvas):
    """The status line and progress bar under the pages, on the same smoke."""
    MARGIN = 18

    def __init__(self, parent, smoke):
        super().__init__(parent, bg=BG, highlightthickness=0, height=1)
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self._bar = self.create_window(self.MARGIN, 0, window=self.progress, anchor="nw", state="hidden")
        self._text = self.create_text(self.MARGIN, 0, anchor="nw", fill=MUTED, font=("Segoe UI", 10))
        self.status = CanvasText(self, self._text, self._layout)
        self.bind("<Configure>", lambda e: self._layout(), add="+")
        smoke.attach(self)

    def show_progress(self, shown):
        self.itemconfigure(self._bar, state="normal" if shown else "hidden")
        self._layout()

    def _layout(self):
        width = max(1, self.winfo_width() - self.MARGIN*2)
        y = 2
        if self.itemcget(self._bar, "state") == "normal":
            self.coords(self._bar, self.MARGIN, y)
            self.itemconfigure(self._bar, width=width)
            y += self.progress.winfo_reqheight() + 5
        self.coords(self._text, self.MARGIN, y)
        self.itemconfigure(self._text, width=width)
        box = self.bbox(self._text)
        if box and self.itemcget(self._text, "text"):
            y = box[3]
        height = y + 8
        if int(float(self.cget("height"))) != height:
            self.configure(height=height)


class Screens(tk.Canvas):
    """120ms directional slide; rapid navigation settles the previous tween."""
    def __init__(self, parent, smoke):
        super().__init__(parent, bg=BG, highlightthickness=0)
        self.smoke = smoke
        smoke.attach(self)
        self.pages, self.active, self._job = [], None, None
        self.motion = animations_enabled()

    def add(self):
        page = Scroller(self, self.smoke)
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
