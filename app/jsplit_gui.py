"""
Jsplit — offline stem-splitter GUI.

The workflow the plugin mirrors:
    drop the audio  ->  choose the stems you want  ->  generate  ->  export.

This is a plain-Tkinter desktop app (no external GUI deps) so it runs anywhere
Python does. It drives the same `StemSplitter` engine the CLI and the VST bridge
use, so what you hear here is exactly what the plugin produces.

Run:
    .venv\\Scripts\\python.exe app/jsplit_gui.py
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Make `src` importable no matter where we're launched from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Stems each quality tier can produce (see src/engine.py QUALITY_TIERS).
TIER_STEMS = {
    "fast":     ["vocals", "drums", "bass", "other"],
    "balanced": ["vocals", "drums", "bass", "other"],
    "full":     ["vocals", "drums", "bass", "other", "guitar", "piano"],
    "max":      ["vocals", "drums", "bass", "other", "guitar", "piano"],
}

TIER_BLURB = {
    "fast":     "htdemucs · 4 stems · quickest",
    "balanced": "htdemucs_ft · 4 stems · fine-tuned, cleaner",
    "full":     "htdemucs_6s · 6 stems · + guitar & piano",
    "max":      "htdemucs_6s + RoFormer · 6 stems · cleanest vocal (slowest)",
}

AUDIO_TYPES = [
    ("Audio files", "*.wav *.mp3 *.flac *.m4a *.ogg *.aiff *.aif"),
    ("All files", "*.*"),
]


class JsplitApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Jsplit — Stem Splitter")
        self.root.geometry("620x640")
        self.root.minsize(560, 600)

        # thread -> UI message pump
        self.msg_q: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None

        # state
        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(ROOT / "outputs_jsplit"))
        self.quality = tk.StringVar(value="full")
        self.run_metrics = tk.BooleanVar(value=True)
        self.stem_vars: dict[str, tk.BooleanVar] = {}
        self.last_output: Path | None = None

        self._build_style()
        self._build_ui()
        self._rebuild_stems()
        self.root.after(100, self._pump)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg = "#1e1f26"
        panel = "#282a36"
        fg = "#e6e6e6"
        accent = "#8be9fd"
        self.colors = dict(bg=bg, panel=panel, fg=fg, accent=accent)

        self.root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg, fieldbackground=panel)
        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Card.TLabel", background=panel, foreground=fg)
        style.configure("Title.TLabel", background=bg, foreground=accent,
                        font=("Segoe UI Semibold", 18))
        style.configure("Sub.TLabel", background=bg, foreground="#9aa0b0",
                        font=("Segoe UI", 9))
        style.configure("Hint.TLabel", background=panel, foreground="#9aa0b0",
                        font=("Segoe UI", 8))
        style.configure("TButton", background=panel, foreground=fg, borderwidth=0,
                        padding=6, font=("Segoe UI", 9))
        style.map("TButton", background=[("active", "#3a3d4d")])
        style.configure("Go.TButton", background=accent, foreground="#0b0c10",
                        font=("Segoe UI Semibold", 11), padding=10)
        style.map("Go.TButton",
                  background=[("active", "#6fd6ea"), ("disabled", "#444657")],
                  foreground=[("disabled", "#8a8d9c")])
        style.configure("TCheckbutton", background=panel, foreground=fg)
        style.map("TCheckbutton", background=[("active", panel)])
        style.configure("TCombobox", fieldbackground=panel, background=panel,
                        foreground=fg, arrowcolor=fg)
        style.configure("Horizontal.TProgressbar", background=accent,
                        troughcolor=panel, borderwidth=0)

    def _card(self, parent, title):
        outer = ttk.Frame(parent, style="TFrame")
        outer.pack(fill="x", pady=(0, 12))
        lbl = ttk.Label(outer, text=title, style="Sub.TLabel")
        lbl.pack(anchor="w", pady=(0, 4))
        card = ttk.Frame(outer, style="Card.TFrame", padding=12)
        card.pack(fill="x")
        return card

    def _build_ui(self):
        pad = ttk.Frame(self.root, padding=18, style="TFrame")
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="Jsplit", style="Title.TLabel").pack(anchor="w")
        ttk.Label(pad, text="Clarity-first offline stem separation",
                  style="Sub.TLabel").pack(anchor="w", pady=(0, 14))

        # --- 1. Input file ---
        c1 = self._card(pad, "1 · SONG")
        row = ttk.Frame(c1, style="Card.TFrame")
        row.pack(fill="x")
        self.in_entry = ttk.Entry(row, textvariable=self.input_path)
        self.in_entry.pack(side="left", fill="x", expand=True, ipady=3)
        ttk.Button(row, text="Browse…", command=self._pick_input).pack(side="left", padx=(8, 0))
        ttk.Label(c1, text="Drop in a .wav / .mp3 / .flac — anything your DAW exports.",
                  style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        # --- 2. Quality ---
        c2 = self._card(pad, "2 · QUALITY")
        row2 = ttk.Frame(c2, style="Card.TFrame")
        row2.pack(fill="x")
        cb = ttk.Combobox(row2, textvariable=self.quality, state="readonly",
                          values=list(TIER_STEMS.keys()), width=12)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_stems())
        self.quality_hint = ttk.Label(row2, text="", style="Hint.TLabel")
        self.quality_hint.pack(side="left", padx=(12, 0))

        # --- 3. Stems ---
        c3 = self._card(pad, "3 · STEMS TO EXPORT")
        self.stems_frame = ttk.Frame(c3, style="Card.TFrame")
        self.stems_frame.pack(fill="x")
        sel_row = ttk.Frame(c3, style="Card.TFrame")
        sel_row.pack(fill="x", pady=(8, 0))
        ttk.Button(sel_row, text="All", command=lambda: self._set_all(True), width=6).pack(side="left")
        ttk.Button(sel_row, text="None", command=lambda: self._set_all(False), width=6).pack(side="left", padx=(6, 0))

        # --- 4. Output ---
        c4 = self._card(pad, "4 · EXPORT TO")
        row4 = ttk.Frame(c4, style="Card.TFrame")
        row4.pack(fill="x")
        ttk.Entry(row4, textvariable=self.output_dir).pack(side="left", fill="x", expand=True, ipady=3)
        ttk.Button(row4, text="Change…", command=self._pick_output).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(c4, text="Run clarity diagnostics after export (recommended)",
                        variable=self.run_metrics).pack(anchor="w", pady=(8, 0))

        # --- Action + progress ---
        self.go_btn = ttk.Button(pad, text="⬇  Generate stems", style="Go.TButton",
                                 command=self._start)
        self.go_btn.pack(fill="x", pady=(4, 8))

        self.pbar = ttk.Progressbar(pad, mode="indeterminate", style="Horizontal.TProgressbar")
        self.pbar.pack(fill="x")

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(pad, textvariable=self.status, style="Sub.TLabel").pack(anchor="w", pady=(6, 0))

        self.open_btn = ttk.Button(pad, text="Open export folder", command=self._open_output,
                                   state="disabled")
        self.open_btn.pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------------ #
    # stem checkboxes rebuild on tier change
    # ------------------------------------------------------------------ #
    def _rebuild_stems(self):
        tier = self.quality.get()
        self.quality_hint.config(text=TIER_BLURB.get(tier, ""))
        prev = {k: v.get() for k, v in self.stem_vars.items()}
        for child in self.stems_frame.winfo_children():
            child.destroy()
        self.stem_vars.clear()

        grid = self.stems_frame
        for i, stem in enumerate(TIER_STEMS[tier]):
            var = tk.BooleanVar(value=prev.get(stem, True))
            self.stem_vars[stem] = var
            cbx = ttk.Checkbutton(grid, text=stem.capitalize(), variable=var)
            cbx.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 24), pady=3)

    def _set_all(self, value: bool):
        for v in self.stem_vars.values():
            v.set(value)

    # ------------------------------------------------------------------ #
    # pickers
    # ------------------------------------------------------------------ #
    def _pick_input(self):
        f = filedialog.askopenfilename(title="Choose a song", filetypes=AUDIO_TYPES)
        if f:
            self.input_path.set(f)
            if not self.status.get().startswith("Working"):
                self.status.set(f"Loaded: {Path(f).name}")

    def _pick_output(self):
        d = filedialog.askdirectory(title="Choose export folder",
                                    initialdir=self.output_dir.get() or str(ROOT))
        if d:
            self.output_dir.set(d)

    def _open_output(self):
        target = self.last_output or Path(self.output_dir.get())
        if target and target.exists():
            try:
                os.startfile(str(target))  # Windows
            except AttributeError:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, str(target)])

    # ------------------------------------------------------------------ #
    # run
    # ------------------------------------------------------------------ #
    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        infile = self.input_path.get().strip()
        if not infile or not Path(infile).exists():
            messagebox.showwarning("No song", "Pick a valid audio file first.")
            return
        keep = [s for s, v in self.stem_vars.items() if v.get()]
        if not keep:
            messagebox.showwarning("No stems", "Select at least one stem to export.")
            return

        self.go_btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.pbar.start(12)
        self.status.set("Working… loading model")

        args = dict(
            infile=infile,
            output_dir=self.output_dir.get().strip() or str(ROOT / "outputs_jsplit"),
            quality=self.quality.get(),
            keep=keep,
            run_metrics=self.run_metrics.get(),
        )
        self.worker = threading.Thread(target=self._run_worker, args=(args,), daemon=True)
        self.worker.start()

    def _run_worker(self, a: dict):
        """Runs in a background thread. Talks to the UI only via self.msg_q."""
        try:
            from src.engine import StemSplitter

            def cb(msg: str):
                self.msg_q.put(("status", msg))

            splitter = StemSplitter(quality=a["quality"])
            result = splitter.process_file(
                input_file=a["infile"],
                output_dir=a["output_dir"],
                run_metrics=a["run_metrics"],
                keep_stems=a["keep"],
                progress_cb=cb,
            )
            self.msg_q.put(("done", result))
        except Exception:
            self.msg_q.put(("error", traceback.format_exc()))

    # ------------------------------------------------------------------ #
    # UI message pump (main thread)
    # ------------------------------------------------------------------ #
    def _pump(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == "status":
                    self.status.set(str(payload).strip() or "Working…")
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _on_done(self, result: dict):
        self.pbar.stop()
        self.go_btn.config(state="normal")
        self.open_btn.config(state="normal")
        self.last_output = Path(result["output_dir"])
        stems = ", ".join(result.get("stems", {}).keys())
        self.status.set(f"Done — exported {len(result.get('stems', {}))} stems to {self.last_output.name}")

        # Surface the no-hollow number if we measured it.
        extra = ""
        m = result.get("metrics", {})
        recon = m.get("reconstruction", {})
        if recon:
            db = recon.get("residual_energy_db")
            grade = recon.get("verdict", "")
            if db is not None:
                extra = f"\n\nIntegrity check: reconstruction residual {db:.1f} dB\n({grade})"
        messagebox.showinfo("Jsplit — finished",
                            f"Exported: {stems}\n\nFolder:\n{self.last_output}{extra}")

    def _on_error(self, tb: str):
        self.pbar.stop()
        self.go_btn.config(state="normal")
        self.status.set("Error — see details.")
        short = tb.strip().splitlines()[-1] if tb.strip() else "Unknown error"
        messagebox.showerror("Jsplit — error", f"{short}\n\n(Full traceback in the console.)")
        print(tb, file=sys.stderr)


def main():
    root = tk.Tk()
    JsplitApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
