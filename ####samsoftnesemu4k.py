#!/usr/bin/env python3
"""
SamsoftEmu NES v1.1 (Tkinter GUI Frontend + iNES/NES 2.0 header parser)
Frontend for a future FCEUX-class emulator.
Single-file build: program.py

What’s new in v1.1
- Adds robust iNES 1.0 and partial NES 2.0 header parsing (mapper, submapper, PRG/CHR sizes, RAM/NVRAM, mirroring, trainer, TV system).
- Displays Cartridge Info via Tools → Cartridge Info.
- Logs detailed header analysis to the Emulator Log.
- Keeps everything in one file (no external data files required).

This file does NOT emulate CPU/PPU/APU yet; “Run” remains a stub that simply demonstrates that a ROM has been parsed.
"""

import os
import sys
import struct
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ------------------------------
# iNES / NES 2.0 Data Structures
# ------------------------------

@dataclass
class INESHeader:
    format: str                 # "iNES" or "NES 2.0" (or "Archaic iNES")
    mapper: int
    submapper: int | None
    mapper_name: str
    prg_rom_size: int           # bytes
    chr_rom_size: int           # bytes
    prg_ram_size: int           # bytes (volatile)
    prg_nvram_size: int         # bytes (battery-backed)
    chr_ram_size: int           # bytes
    chr_nvram_size: int         # bytes
    mirroring: str              # "Horizontal", "Vertical", or "Four-screen VRAM"
    has_battery: bool
    has_trainer: bool
    four_screen: bool
    tv_system: str              # "NTSC", "PAL", "Both", etc.
    vs_unisystem: bool
    playchoice10: bool

@dataclass
class Cartridge:
    header: INESHeader
    prg_rom: bytes
    chr_rom: bytes
    trainer: bytes | None
    raw_header: bytes


MAPPER_NAMES: dict[int, str] = {
    0: "NROM",
    1: "MMC1 (SxROM)",
    2: "UNROM (UxROM)",
    3: "CNROM (CxROM)",
    4: "MMC3 (TxROM)",
    5: "MMC5 (ExROM)",
    7: "AOROM (AxROM)",
    9: "MMC2 (PxROM)",
    10: "MMC4 (FxROM)",
    11: "Color Dreams",
    13: "CPROM",
    15: "100-in-1",
    66: "GxROM/MxROM",
    69: "FME-7 / Sunsoft 5",
    71: "Camerica (BF909x)",
    73: "VRC3",
    75: "VRC1",
    76: "VRC4",
    78: "Irem 74HC161/32",
    79: "NINA-003/006",
    85: "VRC7",
    87: "VRC2",
    94: "HVC-UN1ROM",
    118: "TxSROM",
    119: "TQROM",
    210: "Namco 129/163",
    # Many more exist; unknowns will be displayed as "Unknown/Custom".
}


def _fmt_size(n_bytes: int) -> str:
    if n_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB"]
    size = float(n_bytes)
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def _exp_to_size(exp: int) -> int:
    """NES 2.0 RAM/NVRAM size encoding: 2^exp × 64 bytes (0 means absent)."""
    if exp == 0:
        return 0
    return (64 << exp)


def parse_ines_file(path: str) -> Cartridge:
    """Parse a .nes file, returning a Cartridge with header + PRG/CHR slices.
    Supports iNES 1.0 and (partially) NES 2.0.
    Raises ValueError on invalid header or inconsistent sizes.
    """
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 16:
        raise ValueError("File too small to contain an iNES header.")

    header = data[:16]
    if header[:4] != b"NES\x1A":
        raise ValueError("Missing NES\x1A magic; not an iNES/NES2.0 ROM.")

    prg_units = header[4]             # 16KB units
    chr_units = header[5]             # 8KB units
    flags6 = header[6]
    flags7 = header[7]
    flags8 = header[8] if len(header) >= 9 else 0
    flags9 = header[9] if len(header) >= 10 else 0
    flags10 = header[10] if len(header) >= 11 else 0
    flags11 = header[11] if len(header) >= 12 else 0
    flags12 = header[12] if len(header) >= 13 else 0

    # Detect format
    # NES 2.0 if ((flags7 & 0x0C) == 0x08). Otherwise iNES 1.0 (or archaic).
    is_nes20 = (flags7 & 0x0C) == 0x08
    format_name = "NES 2.0" if is_nes20 else "iNES"

    # Mapper and Submapper
    mapper_low = (flags6 >> 4) | (flags7 & 0xF0)  # bits 0..7
    submapper: int | None = None
    if is_nes20:
        mapper_ext = flags8 & 0x0F  # adds bits 8..11
        mapper = mapper_low | (mapper_ext << 8)
        submapper = (flags8 >> 4) & 0x0F
    else:
        mapper = mapper_low

    # Sizes
    if is_nes20:
        prg_rom_size = (prg_units | ((flags9 & 0x0F) << 8)) * 16 * 1024
        chr_rom_size = (chr_units | ((flags9 & 0xF0) << 4)) * 8 * 1024
        prg_ram_size = _exp_to_size(flags10 & 0x0F)
        prg_nvram_size = _exp_to_size((flags10 >> 4) & 0x0F)
        chr_ram_size = _exp_to_size(flags11 & 0x0F)
        chr_nvram_size = _exp_to_size((flags11 >> 4) & 0x0F)
    else:
        prg_rom_size = prg_units * 16 * 1024
        chr_rom_size = chr_units * 8 * 1024
        # iNES: byte 8 is PRG-RAM size in 8KB units; 0 implies 8KB for some mappers.
        prg_ram_size = (flags8 * 8 * 1024) if flags8 else (8 * 1024 if mapper in (1, 4) else 0)
        prg_nvram_size = 0
        # If no CHR ROM, assume 8KB CHR-RAM (common).
        chr_ram_size = 8 * 1024 if chr_rom_size == 0 else 0
        chr_nvram_size = 0

    # Flags
    vert_mirr = bool(flags6 & 0x01)
    has_battery = bool(flags6 & 0x02)
    has_trainer = bool(flags6 & 0x04)
    four_screen = bool(flags6 & 0x08)
    mirroring = "Vertical" if vert_mirr else "Horizontal"
    if four_screen:
        mirroring = "Four-screen VRAM"

    vs_unisystem = bool(flags7 & 0x01)
    playchoice10 = bool(flags7 & 0x02)

    # TV system (best-effort)
    if is_nes20:
        tv_code = flags12 & 0x03
        tv_system = {0: "NTSC", 1: "PAL", 2: "Both (NTSC/PAL)", 3: "Dendy/Reserved"}.get(tv_code, "Unknown")
    else:
        tv_system = "PAL" if (flags9 & 0x01) else "NTSC"

    # Compute data offsets
    offset = 16
    trainer_data = None
    if has_trainer:
        if len(data) < offset + 512:
            raise ValueError("Header indicates trainer but file is too small.")
        trainer_data = data[offset:offset + 512]
        offset += 512

    if len(data) < offset + prg_rom_size:
        raise ValueError("File truncated: PRG ROM is smaller than indicated by header.")
    prg_data = data[offset:offset + prg_rom_size]
    offset += prg_rom_size

    if len(data) < offset + chr_rom_size:
        raise ValueError("File truncated: CHR ROM is smaller than indicated by header.")
    chr_data = data[offset:offset + chr_rom_size]

    mapper_name = MAPPER_NAMES.get(mapper, "Unknown/Custom")

    ines_header = INESHeader(
        format=format_name,
        mapper=mapper,
        submapper=submapper,
        mapper_name=mapper_name,
        prg_rom_size=prg_rom_size,
        chr_rom_size=chr_rom_size,
        prg_ram_size=prg_ram_size,
        prg_nvram_size=prg_nvram_size,
        chr_ram_size=chr_ram_size,
        chr_nvram_size=chr_nvram_size,
        mirroring=mirroring,
        has_battery=has_battery,
        has_trainer=has_trainer,
        four_screen=four_screen,
        tv_system=tv_system,
        vs_unisystem=vs_unisystem,
        playchoice10=playchoice10,
    )

    return Cartridge(
        header=ines_header,
        prg_rom=prg_data,
        chr_rom=chr_data,
        trainer=trainer_data,
        raw_header=header,
    )


# ------------------------------
# Tkinter GUI
# ------------------------------

class SamsoftEmuNESGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SamsoftEmu NES v1.1")
        self.root.geometry("900x650")
        self.root.configure(bg="#1e1e1e")

        # Emulator state
        self.rom_path: str | None = None
        self.cartridge: Cartridge | None = None
        self.is_running = False
        self.version = "1.1"

        # UI setup
        self.create_menu()
        self.create_toolbar()
        self.create_statusbar()
        self.create_console()

        self.log("SamsoftEmu NES v1.1 GUI Ready")

    def create_menu(self):
        menubar = tk.Menu(self.root, bg="#2d2d2d", fg="white", tearoff=0)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open ROM", command=self.open_rom)
        file_menu.add_command(label="Reset Emulator", command=self.reset_emulator)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Cartridge Info", command=self.show_cart_info)
        tools_menu.add_command(label="Debugger", command=self.launch_debugger)
        tools_menu.add_command(label="Cheats", command=self.launch_cheats)
        tools_menu.add_command(label="TAS Tools", command=self.launch_tas_tools)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def create_toolbar(self):
        toolbar = tk.Frame(self.root, bg="#2d2d2d", height=44)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        open_btn = tk.Button(toolbar, text="📂 Open ROM", command=self.open_rom,
                             bg="#3a3a3a", fg="white", relief=tk.FLAT, cursor="hand2")
        open_btn.pack(side=tk.LEFT, padx=5, pady=6)

        run_btn = tk.Button(toolbar, text="▶ Run", command=self.run_emulator,
                            bg="#4CAF50", fg="white", relief=tk.FLAT, cursor="hand2")
        run_btn.pack(side=tk.LEFT, padx=5, pady=6)

        reset_btn = tk.Button(toolbar, text="⟳ Reset", command=self.reset_emulator,
                              bg="#FF9800", fg="white", relief=tk.FLAT, cursor="hand2")
        reset_btn.pack(side=tk.LEFT, padx=5, pady=6)

        stop_btn = tk.Button(toolbar, text="■ Stop", command=self.stop_emulator,
                             bg="#f44336", fg="white", relief=tk.FLAT, cursor="hand2")
        stop_btn.pack(side=tk.LEFT, padx=5, pady=6)

    def create_statusbar(self):
        self.status_var = tk.StringVar()
        self.status_var.set("Ready – No ROM loaded")
        status_bar = tk.Label(self.root, textvariable=self.status_var,
                              bd=1, relief=tk.SUNKEN, anchor=tk.W,
                              bg="#2d2d2d", fg="white")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def create_console(self):
        console_frame = tk.LabelFrame(self.root, text=" Emulator Log ",
                                      font=("Consolas", 10, "bold"),
                                      fg="#90CAF9", bg="#1e1e1e")
        console_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.console = scrolledtext.ScrolledText(console_frame, wrap=tk.WORD,
                                                 font=("Consolas", 9),
                                                 bg="#0d0d0d", fg="#00ff00",
                                                 insertbackground="white")
        self.console.pack(fill=tk.BOTH, expand=True)

    def log(self, msg: str):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, msg + "\n")
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

    # ------------------------------
    # Emulator actions
    # ------------------------------
    def open_rom(self):
        filetypes = [("NES ROMs", "*.nes"), ("All files", "*.*")]
        filename = filedialog.askopenfilename(title="Select NES ROM", filetypes=filetypes)
        if not filename:
            return

        try:
            cart = parse_ines_file(filename)
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to parse ROM:\n{e}")
            self.log(f"[ERROR] ROM load failed: {e}")
            return

        self.rom_path = filename
        self.cartridge = cart
        self.status_var.set(f"Loaded ROM: {os.path.basename(filename)}")
        self.log(f"[ROM] Loaded: {filename}")
        self._log_header(cart.header)

        # Brief tip
        self.log("[TIP] Use Tools → Cartridge Info to view a formatted summary.")

    def _log_header(self, h: INESHeader):
        self.log("[HEADER] Format: " + h.format)
        self.log(f"[HEADER] Mapper: {h.mapper} ({h.mapper_name})" + (f"  Submapper: {h.submapper}" if h.submapper is not None else ""))
        self.log(f"[HEADER] PRG-ROM: {_fmt_size(h.prg_rom_size)}  CHR-ROM: {_fmt_size(h.chr_rom_size)}")
        self.log(f"[HEADER] PRG-RAM: {_fmt_size(h.prg_ram_size)}  PRG-NVRAM: {_fmt_size(h.prg_nvram_size)}")
        self.log(f"[HEADER] CHR-RAM: {_fmt_size(h.chr_ram_size)}  CHR-NVRAM: {_fmt_size(h.chr_nvram_size)}")
        self.log(f"[HEADER] Mirroring: {h.mirroring}  Battery: {h.has_battery}  Trainer: {h.has_trainer}")
        self.log(f"[HEADER] TV: {h.tv_system}  VS: {h.vs_unisystem}  PlayChoice10: {h.playchoice10}")

    def run_emulator(self):
        if not self.rom_path or not self.cartridge:
            messagebox.showwarning("No ROM", "Please load a ROM first!")
            return
        self.is_running = True
        self.status_var.set("Running...")
        base = os.path.basename(self.rom_path)
        self.log(f"[SYSTEM] Emulating {base} (stub backend)")
        h = self.cartridge.header
        self.log(f"[SYSTEM] Mapper {h.mapper} ({h.mapper_name}), PRG={_fmt_size(h.prg_rom_size)}, CHR={_fmt_size(h.chr_rom_size)}")
        # TODO: plug in CPU6502/PPU/APU backend

    def reset_emulator(self):
        if self.is_running:
            self.log("[SYSTEM] Emulator reset")
            self.status_var.set("Reset")
        else:
            self.log("[WARN] Reset called but emulator not running")

    def stop_emulator(self):
        if self.is_running:
            self.is_running = False
            self.log("[SYSTEM] Emulator stopped")
            self.status_var.set("Stopped")

    def launch_debugger(self):
        self.log("[TOOLS] Debugger opened (stub)")

    def launch_cheats(self):
        self.log("[TOOLS] Cheats manager opened (stub)")

    def launch_tas_tools(self):
        self.log("[TOOLS] TAS tools opened (stub)")

    def show_cart_info(self):
        if not self.cartridge:
            messagebox.showinfo("Cartridge Info", "No ROM loaded.")
            return
        h = self.cartridge.header
        lines = [
            f"Format: {h.format}",
            f"Mapper: {h.mapper} ({h.mapper_name})" + (f"   Submapper: {h.submapper}" if h.submapper is not None else ""),
            "",
            f"PRG-ROM: {_fmt_size(h.prg_rom_size)}",
            f"CHR-ROM: {_fmt_size(h.chr_rom_size)}" + ("  (uses CHR-RAM)" if h.chr_rom_size == 0 else ""),
            f"PRG-RAM: {_fmt_size(h.prg_ram_size)}",
            f"PRG-NVRAM (battery): {_fmt_size(h.prg_nvram_size)}",
            f"CHR-RAM: {_fmt_size(h.chr_ram_size)}",
            f"CHR-NVRAM: {_fmt_size(h.chr_nvram_size)}",
            "",
            f"Mirroring: {h.mirroring}",
            f"Battery: {'Yes' if h.has_battery else 'No'}   Trainer: {'Yes' if h.has_trainer else 'No'}",
            f"VS Unisystem: {'Yes' if h.vs_unisystem else 'No'}   PlayChoice-10: {'Yes' if h.playchoice10 else 'No'}",
            f"TV System: {h.tv_system}",
        ]

        top = tk.Toplevel(self.root)
        top.title("Cartridge Info")
        top.configure(bg="#1e1e1e")

        text = tk.Text(top, width=80, height=20, bg="#0d0d0d", fg="#e0e0e0",
                       insertbackground="white", font=("Consolas", 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        text.insert("1.0", "\n".join(lines))
        text.configure(state=tk.DISABLED)

    def show_about(self):
        messagebox.showinfo("About SamsoftEmu NES",
                            "SamsoftEmu NES v1.1\nTkinter GUI Frontend + iNES/NES2 Parser\nAI Core Edition")

# ------------------------------
# Entrypoint
# ------------------------------
if __name__ == "__main__":
    # Tkinter requires a display. If running headless (no $DISPLAY), the app may fail.
    root = tk.Tk()
    app = SamsoftEmuNESGUI(root)
    root.mainloop()
