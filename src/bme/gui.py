"""Tk desktop front end for the material exporter."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .paths import discover_material_paths
from .service import (
    corresponding_texture_archive,
    export_from_inputs,
    starfield_install_path,
)


DATABASE_EXTENSIONS = (".ba2",)

BACKGROUND = "#121212"
TITLEBAR = "#181818"
SURFACE = "#1E1E1E"
SURFACE_RAISED = "#2A2A2A"
OUTLINE = "#3A3A3A"
PRIMARY = "#BB86FC"
PRIMARY_ACTIVE = "#D0A8FF"
TEXT = "#F5F2F7"
TEXT_MUTED = "#B8B2BC"
ERROR = "#B3261E"


def _accepted_files_text(
    extensions: tuple[str, ...], *, folders: bool = False
) -> str:
    description = f"Accepted files: {', '.join(extensions)}"
    if folders:
        description += " (folders are scanned recursively)"
    return description


def _file_pattern(extensions: tuple[str, ...]) -> str:
    return " ".join(f"*{extension}" for extension in extensions)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title("Bethesda Material Extractor")
        self._set_window_icon()
        self.geometry("840x560")
        self.minsize(700, 440)
        self._is_maximized = False
        self._normal_geometry = ""
        self._drag_offset = (0, 0)
        self._resize_origin = (0, 0, 0, 0)
        self._configure_theme()
        if os.name != "nt":
            self.overrideredirect(True)
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._window = ttk.Frame(self, style="Window.TFrame")
        self._window.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._build_title_bar()
        self._build_content()
        self.bind("<Map>", self._restore_custom_frame)
        if os.name == "nt":
            self.after_idle(self._show_windows_window)
        else:
            self.deiconify()
        self.after(80, self._poll_events)

    @property
    def _data_dir(self) -> str:
        install = starfield_install_path()
        return str(install / "Data") if install else ""

    def _set_window_icon(self) -> None:
        bundle_root = Path(
            getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)
        )
        icon_path = bundle_root / "assets" / "bme-icon.png"
        try:
            self._window_icon = tk.PhotoImage(file=icon_path)
            self.iconphoto(True, self._window_icon)
        except (OSError, tk.TclError):
            self._window_icon = None

    def _configure_theme(self) -> None:
        self.configure(background=OUTLINE)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            ".", background=BACKGROUND, foreground=TEXT, font=("Segoe UI", 10)
        )
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Window.TFrame", background=BACKGROUND)
        style.configure("Titlebar.TFrame", background=TITLEBAR)
        style.configure(
            "TLabel",
            background=SURFACE,
            foreground=TEXT_MUTED,
            padding=(0, 2),
        )
        style.configure(
            "Caption.TLabel",
            background=SURFACE,
            foreground=TEXT_MUTED,
            font=("Segoe UI", 9),
            padding=(0, 2),
        )
        style.configure(
            "Brand.TLabel",
            background=TITLEBAR,
            foreground=PRIMARY,
            font=("Segoe UI Semibold", 18),
            padding=(0, 2),
        )
        style.configure(
            "Title.TLabel",
            background=TITLEBAR,
            foreground=TEXT,
            font=("Segoe UI Semibold", 12),
            padding=(0, 3),
        )
        style.configure(
            "Status.TLabel",
            background=BACKGROUND,
            foreground=TEXT_MUTED,
            font=("Segoe UI Semibold", 10),
            padding=(2, 2),
        )
        style.configure(
            "TLabelframe",
            background=SURFACE,
            bordercolor=OUTLINE,
            darkcolor=OUTLINE,
            lightcolor=OUTLINE,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=SURFACE,
            foreground=TEXT,
            font=("Segoe UI Semibold", 11),
            padding=(6, 3),
        )
        style.configure(
            "TEntry",
            fieldbackground=SURFACE_RAISED,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=OUTLINE,
            lightcolor=OUTLINE,
            darkcolor=OUTLINE,
            padding=(8, 7),
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", PRIMARY)],
            lightcolor=[("focus", PRIMARY)],
            darkcolor=[("focus", PRIMARY)],
        )
        style.configure(
            "TButton",
            background=SURFACE_RAISED,
            foreground=TEXT,
            bordercolor=SURFACE_RAISED,
            lightcolor=SURFACE_RAISED,
            darkcolor=SURFACE_RAISED,
            borderwidth=0,
            relief="flat",
            focusthickness=0,
            focuscolor=SURFACE_RAISED,
            padding=(14, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.layout(
            "TButton",
            [
                (
                    "Button.border",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Button.padding",
                                {
                                    "sticky": "nswe",
                                    "children": [
                                        ("Button.label", {"sticky": "nswe"})
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.map(
            "TButton",
            background=[("pressed", OUTLINE), ("active", OUTLINE)],
            foreground=[("disabled", "#777279"), ("active", TEXT)],
        )
        style.configure(
            "Text.TButton",
            background=TITLEBAR,
            foreground=PRIMARY,
            bordercolor=TITLEBAR,
            lightcolor=TITLEBAR,
            darkcolor=TITLEBAR,
            focuscolor=TITLEBAR,
            padding=(12, 7),
        )
        style.map(
            "Text.TButton",
            background=[("pressed", SURFACE), ("active", SURFACE)],
            foreground=[("active", PRIMARY_ACTIVE)],
        )
        style.configure(
            "Window.TButton",
            background=TITLEBAR,
            foreground=TEXT_MUTED,
            bordercolor=TITLEBAR,
            lightcolor=TITLEBAR,
            darkcolor=TITLEBAR,
            borderwidth=0,
            focuscolor=TITLEBAR,
            padding=(12, 7),
            font=("Segoe UI Symbol", 10),
        )
        style.map(
            "Window.TButton",
            background=[("pressed", OUTLINE), ("active", SURFACE_RAISED)],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "Close.TButton",
            background=TITLEBAR,
            foreground=TEXT_MUTED,
            bordercolor=TITLEBAR,
            lightcolor=TITLEBAR,
            darkcolor=TITLEBAR,
            borderwidth=0,
            focuscolor=TITLEBAR,
            padding=(12, 7),
            font=("Segoe UI Symbol", 11),
        )
        style.map(
            "Close.TButton",
            background=[("pressed", "#8C1D18"), ("active", ERROR)],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "Resize.TLabel",
            background=BACKGROUND,
            foreground=TEXT_MUTED,
            font=("Segoe UI Symbol", 10),
            padding=(4, 2),
        )
        style.configure(
            "Accent.TButton",
            background=PRIMARY,
            foreground=BACKGROUND,
            bordercolor=PRIMARY,
            lightcolor=PRIMARY,
            darkcolor=PRIMARY,
            focuscolor=PRIMARY,
            padding=(18, 9),
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", "#59456B"),
                ("pressed", PRIMARY),
                ("active", PRIMARY_ACTIVE),
            ],
            foreground=[("disabled", "#9A8EA1"), ("active", BACKGROUND)],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE_RAISED,
            troughcolor=SURFACE,
            bordercolor=SURFACE,
            arrowcolor=TEXT_MUTED,
            lightcolor=SURFACE_RAISED,
            darkcolor=SURFACE_RAISED,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("pressed", PRIMARY), ("active", OUTLINE)],
        )

    def _build_title_bar(self) -> None:
        title_bar = ttk.Frame(
            self._window,
            style="Titlebar.TFrame",
            padding=(14, 7),
        )
        title_bar.pack(fill=tk.X)
        title_bar.columnconfigure(1, weight=1)
        brand = ttk.Label(title_bar, text="BME", style="Brand.TLabel")
        brand.grid(row=0, column=0, sticky="w")
        title = ttk.Label(
            title_bar,
            text="Bethesda Material Extractor",
            style="Title.TLabel",
        )
        title.grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Button(
            title_bar,
            text="About",
            command=self._about,
            style="Text.TButton",
            takefocus=False,
        ).grid(row=0, column=2, sticky="e", padx=(0, 4))
        ttk.Button(
            title_bar,
            text="—",
            width=3,
            command=self._minimize_window,
            style="Window.TButton",
            takefocus=False,
        ).grid(row=0, column=3)
        self.maximize_button = ttk.Button(
            title_bar,
            text="□",
            width=3,
            command=self._toggle_maximize,
            style="Window.TButton",
            takefocus=False,
        )
        self.maximize_button.grid(row=0, column=4)
        ttk.Button(
            title_bar,
            text="×",
            width=3,
            command=self.destroy,
            style="Close.TButton",
            takefocus=False,
        ).grid(row=0, column=5)
        for widget in (title_bar, brand, title):
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._move_window)
            widget.bind("<Double-Button-1>", self._toggle_maximize)

    def _start_move(self, event: tk.Event) -> None:
        if self._is_maximized:
            return
        if os.name == "nt":
            self._start_windows_move()
            return
        self._drag_offset = (
            event.x_root - self.winfo_x(),
            event.y_root - self.winfo_y(),
        )

    def _move_window(self, event: tk.Event) -> None:
        if self._is_maximized or os.name == "nt":
            return
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.geometry(f"+{x}+{y}")

    def _start_windows_move(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.ReleaseCapture.argtypes = []
            user32.ReleaseCapture.restype = wintypes.BOOL
            user32.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            user32.PostMessageW.restype = wintypes.BOOL
            handle = user32.GetAncestor(self.winfo_id(), 2)
            if handle:
                cursor = wintypes.POINT()
                if not user32.GetCursorPos(ctypes.byref(cursor)):
                    return
                position = ((cursor.y & 0xFFFF) << 16) | (cursor.x & 0xFFFF)
                user32.ReleaseCapture()
                user32.PostMessageW(handle, 0x00A1, 2, position)
        except (AttributeError, OSError):
            pass

    def _toggle_maximize(self, _event: tk.Event | None = None) -> None:
        if self._is_maximized:
            self.geometry(self._normal_geometry)
            self._is_maximized = False
            self.maximize_button.configure(text="□")
            return
        self.update_idletasks()
        self._normal_geometry = self.geometry()
        left, top, right, bottom = self._work_area()
        self.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
        self._is_maximized = True
        self.maximize_button.configure(text="❐")

    def _work_area(self) -> tuple[int, int, int, int]:
        if os.name == "nt":
            try:
                import ctypes

                class Rect(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                rect = Rect()
                if ctypes.windll.user32.SystemParametersInfoW(
                    0x0030, 0, ctypes.byref(rect), 0
                ):
                    return rect.left, rect.top, rect.right, rect.bottom
            except (AttributeError, OSError):
                pass
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    def _minimize_window(self) -> None:
        if os.name != "nt":
            self.overrideredirect(False)
        self.iconify()

    def _restore_custom_frame(self, event: tk.Event) -> None:
        if event.widget is self and self.state() == "normal":
            self.after_idle(self._enable_custom_frame)

    def _enable_custom_frame(self) -> None:
        if os.name == "nt":
            self._apply_taskbar_style()
        else:
            self.overrideredirect(True)

    def _show_windows_window(self) -> None:
        self.update_idletasks()
        self._apply_taskbar_style()
        self.deiconify()
        self._set_window_icon()
        self.lift()
        self.after(50, self._finish_windows_setup)

    def _finish_windows_setup(self) -> None:
        self._apply_taskbar_style()
        self._set_window_icon()

    def _apply_taskbar_style(self) -> None:
        if os.name != "nt" or not self.winfo_exists():
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_long,
            ]
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            handle = user32.GetAncestor(self.winfo_id(), 2)
            if not handle:
                return
            style = user32.GetWindowLongW(handle, -16)
            style &= ~(0x00C00000 | 0x00040000)
            style |= 0x00080000 | 0x00020000
            user32.SetWindowLongW(handle, -16, style)
            ex_style = user32.GetWindowLongW(handle, -20)
            ex_style = (ex_style & ~0x00000080) | 0x00040000
            user32.SetWindowLongW(handle, -20, ex_style)
            user32.SetWindowPos(handle, 0, 0, 0, 0, 0, 0x0027)
        except (AttributeError, OSError):
            pass

    def _start_resize(self, event: tk.Event) -> None:
        if self._is_maximized:
            return
        self._resize_origin = (
            event.x_root,
            event.y_root,
            self.winfo_width(),
            self.winfo_height(),
        )

    def _resize_window(self, event: tk.Event) -> None:
        if self._is_maximized:
            return
        start_x, start_y, width, height = self._resize_origin
        width = max(700, width + event.x_root - start_x)
        height = max(440, height + event.y_root - start_y)
        self.geometry(f"{width}x{height}")

    def _build_content(self) -> None:
        root = ttk.Frame(self._window, padding=(20, 14, 20, 20))
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        database = ttk.LabelFrame(
            root, text="Material Archive", padding=(16, 14)
        )
        database.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        database.columnconfigure(0, weight=1)
        ttk.Label(
            database,
            text=_accepted_files_text(DATABASE_EXTENSIONS),
            style="Caption.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        archive_help = ttk.Label(
            database,
            text=(
                "For the base game, this would be the materials.ba2 file. "
                "For other creations, choose the corresponding main.ba2 file; "
                "a sibling textures.ba2 is exported automatically."
            ),
            style="Caption.TLabel",
            justify=tk.LEFT,
            wraplength=720,
        )
        archive_help.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        database.bind(
            "<Configure>",
            lambda event: archive_help.configure(
                wraplength=max(320, event.width - 48)
            ),
        )
        self.database_var = tk.StringVar()
        ttk.Entry(database, textvariable=self.database_var).grid(
            row=2, column=0, sticky="ew", pady=(0, 2)
        )
        ttk.Button(
            database,
            text="Browse...",
            command=self._choose_database,
            takefocus=False,
        ).grid(
            row=2, column=1, padx=(10, 0), pady=(0, 2)
        )

        path_log = ttk.LabelFrame(
            root, text="Discovered Material Paths", padding=(16, 14)
        )
        path_log.grid(row=1, column=0, sticky="nsew")
        path_log.columnconfigure(0, weight=1)
        path_log.rowconfigure(1, weight=1)
        ttk.Label(
            path_log,
            text="Paths found automatically in the selected BA2 archive.",
            style="Caption.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.path_log = tk.Listbox(
            path_log,
            activestyle="none",
            selectmode=tk.EXTENDED,
            background="#181818",
            foreground=TEXT,
            selectbackground=PRIMARY,
            selectforeground=BACKGROUND,
            highlightbackground=OUTLINE,
            highlightcolor=PRIMARY,
            highlightthickness=1,
            borderwidth=0,
            relief=tk.FLAT,
            font=("Cascadia Mono", 10),
        )
        path_scroll = ttk.Scrollbar(
            path_log, orient=tk.VERTICAL, command=self.path_log.yview
        )
        self.path_log.configure(yscrollcommand=path_scroll.set)
        self.path_log.grid(row=1, column=0, sticky="nsew")
        path_scroll.grid(row=1, column=1, sticky="ns")

        export_row = ttk.Frame(root)
        export_row.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        export_row.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(
            export_row, textvariable=self.status_var, style="Status.TLabel"
        ).grid(
            row=0, column=0, sticky="w"
        )
        self.export_button = ttk.Button(
            export_row,
            text="Export Materials + Textures",
            command=self._choose_export,
            style="Accent.TButton",
            takefocus=False,
        )
        self.export_button.grid(row=0, column=1)
        resize_grip = ttk.Label(
            export_row,
            text="◢",
            style="Resize.TLabel",
            cursor="size_nw_se",
        )
        resize_grip.grid(row=0, column=2, sticky="se", padx=(12, 0))
        resize_grip.bind("<ButtonPress-1>", self._start_resize)
        resize_grip.bind("<B1-Motion>", self._resize_window)

    def _choose_database(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open Material Archive",
            initialdir=self._data_dir,
            filetypes=[
                (
                    "Material archives (.ba2)",
                    _file_pattern(DATABASE_EXTENSIONS),
                ),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.database_var.set(path)
            self._discover_archive(path)

    def _discover_archive(self, archive_path: str) -> None:
        self.path_log.delete(0, tk.END)
        self.status_var.set("Discovering material paths...")

        def worker() -> None:
            try:
                paths = discover_material_paths([archive_path])
                self._events.put(
                    ("selected_paths", (archive_path, paths))
                )
            except Exception as exc:
                self._events.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_discovered_paths(
        self, paths: list[str], archive_path: str | None = None
    ) -> None:
        self.path_log.delete(0, tk.END)
        for path in paths:
            self.path_log.insert(tk.END, path)
        status = f"Discovered {len(paths)} material path(s)"
        texture_archive = (
            corresponding_texture_archive(archive_path) if archive_path else None
        )
        if texture_archive is not None:
            status += f"; paired {texture_archive.name}"
        self.status_var.set(status)

    def _choose_export(self) -> None:
        database = self.database_var.get().strip()
        if not database or Path(database).suffix.casefold() not in DATABASE_EXTENSIONS:
            messagebox.showerror(
                "Invalid materials file",
                "Choose a .ba2 materials archive.",
                parent=self,
            )
            return
        output = filedialog.askdirectory(
            parent=self, title="Export Folder", initialdir=self._data_dir
        )
        if not output:
            return
        self.export_button.state(["disabled"])
        self.status_var.set("Exporting materials...")

        def progress(value: int, maximum: int, label: str) -> None:
            self._events.put(("progress", (value, maximum, label)))

        def discovered(paths: list[str]) -> None:
            self._events.put(("paths", paths))

        def worker() -> None:
            try:
                written = export_from_inputs(
                    database,
                    output,
                    [],
                    progress=progress,
                    discovered=discovered,
                )
                self._events.put(("exported", (written, output)))
            except Exception as exc:
                self._events.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self._events.get_nowait()
                if event == "paths":
                    self._show_discovered_paths(payload)  # type: ignore[arg-type]
                elif event == "selected_paths":
                    archive_path, paths = payload  # type: ignore[misc]
                    if self.database_var.get() == archive_path:
                        self._show_discovered_paths(paths, archive_path)
                elif event == "progress":
                    value, maximum, label = payload  # type: ignore[misc]
                    self.status_var.set(f"[{value}/{maximum}] {label}")
                elif event == "exported":
                    written, output = payload  # type: ignore[misc]
                    self.export_button.state(["!disabled"])
                    count = len(written)
                    label = (
                        f"Exported {count} file(s)"
                        if count
                        else "No materials or textures found"
                    )
                    self.status_var.set(label)
                    messagebox.showinfo(
                        "Export complete",
                        f"{label} to:\n{output}" if count else label,
                        parent=self,
                    )
                    if count:
                        self._open_folder(output)
                elif event == "error":
                    self.export_button.state(["!disabled"])
                    self.status_var.set("Operation failed")
                    messagebox.showerror("BME", str(payload), parent=self)
        except queue.Empty:
            pass
        self.after(80, self._poll_events)

    @staticmethod
    def _open_folder(path: str) -> None:
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass

    def _about(self) -> None:
        messagebox.showinfo(
            "About",
            "Bethesda Material Extractor (BME)\n"
            "Python implementation v1.0.1\n\n"
            "Copyright © 2026 Wes Sitzes\n\n"
            "Discovers material references and exports material JSON.\n\n"
            "Licensed under GNU GPL v3.0 or later.",
            parent=self,
        )


def run() -> None:
    App().mainloop()
