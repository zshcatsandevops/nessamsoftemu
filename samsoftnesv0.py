#!/usr/bin/env python3
"""
SamsoftEmu NES v2.0 (Tkinter GUI Frontend with iNES parsing)
Frontend for a future FCEUX-class emulator.
"""

import os
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, filedialog, messagebox, scrolledtext


class INESParseError(Exception):
    """Raised when an iNES header cannot be parsed."""


@dataclass
class INESHeader:
    prg_rom_size_bytes: int
    chr_rom_size_bytes: int
    prg_ram_size_bytes: int
    prg_nvram_size_bytes: int
    chr_ram_size_bytes: int
    chr_nvram_size_bytes: int
    mapper: int
    submapper: int
    mirroring: str
    has_battery_backed_ram: bool
    has_trainer: bool
    is_nes2: bool
    is_vs_system: bool
    is_playchoice10: bool
    tv_system: str

    @classmethod
    def from_path(cls, path):
        with open(path, "rb") as rom:
            header = rom.read(16)
        if len(header) < 16:
            raise INESParseError("File too small to contain an iNES header.")
        if header[:4] != b"NES\x1a":
            raise INESParseError("Missing iNES magic number (expected 'NES<0x1A>').")

        flags6 = header[6]
        flags7 = header[7]
        is_nes2 = (flags7 & 0x0C) == 0x08

        mapper = (flags6 >> 4) | (flags7 & 0xF0)
        submapper = 0
        prg_rom_units = header[4]
        chr_rom_units = header[5]

        if is_nes2:
            mapper |= (header[8] & 0x0F) << 8
            mapper |= (header[9] & 0x0F) << 12
            submapper = header[8] >> 4
            prg_rom_units |= (header[9] & 0x0F) << 8
            chr_rom_units |= (header[9] >> 4) << 8

        prg_rom_size_bytes = prg_rom_units * 16384
        chr_rom_size_bytes = chr_rom_units * 8192

        has_battery = bool(flags6 & 0x02)
        has_trainer = bool(flags6 & 0x04)

        mirroring = "Four-screen" if (flags6 & 0x08) else ("Vertical" if (flags6 & 0x01) else "Horizontal")

        console_type = flags7 & 0x03
        is_vs_system = console_type == 1
        is_playchoice10 = console_type == 2

        if is_nes2:
            tv_bits = header[12] & 0x03
            tv_system = {0: "NTSC", 1: "PAL", 2: "Multi-region", 3: "Hd/Nst Hybrid"}.get(tv_bits, "Unknown")
            prg_ram_size_bytes = cls._decode_nes2_size(header[10] & 0x0F)
            prg_nvram_size_bytes = cls._decode_nes2_size(header[10] >> 4)
            chr_ram_size_bytes = cls._decode_nes2_size(header[11] & 0x0F)
            chr_nvram_size_bytes = cls._decode_nes2_size(header[11] >> 4)
        else:
            tv_system = "PAL" if (header[9] & 0x01) else "NTSC"
            prg_ram_units = header[8] if header[8] else 1
            prg_ram_size_bytes = prg_ram_units * 8192
            prg_nvram_size_bytes = 0
            chr_ram_size_bytes = 0
            chr_nvram_size_bytes = 0

        return cls(
            prg_rom_size_bytes=prg_rom_size_bytes,
            chr_rom_size_bytes=chr_rom_size_bytes,
            prg_ram_size_bytes=prg_ram_size_bytes,
            prg_nvram_size_bytes=prg_nvram_size_bytes,
            chr_ram_size_bytes=chr_ram_size_bytes,
            chr_nvram_size_bytes=chr_nvram_size_bytes,
            mapper=mapper,
            submapper=submapper,
            mirroring=mirroring,
            has_battery_backed_ram=has_battery,
            has_trainer=has_trainer,
            is_nes2=is_nes2,
            is_vs_system=is_vs_system,
            is_playchoice10=is_playchoice10,
            tv_system=tv_system,
        )

    @staticmethod
    def _decode_nes2_size(shift):
        if shift == 0:
            return 0
        return 1 << (shift + 6)

    @staticmethod
    def _format_bytes(byte_count):
        if byte_count == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB"]
        value = float(byte_count)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if value.is_integer():
                    return f"{int(value)} {unit}"
                return f"{value:.2f} {unit}".rstrip("0").rstrip(".")
            value /= 1024
        return f"{int(value)} GB"

    def summary_lines(self):
        lines = []
        format_label = "NES 2.0" if self.is_nes2 else "iNES 1.0"
        mapper_line = f"Mapper {self.mapper}"
        if self.submapper:
            mapper_line += f" (submapper {self.submapper})"
        lines.append(f"Format: {format_label}")
        lines.append(mapper_line)
        lines.append(f"PRG ROM: {self._format_bytes(self.prg_rom_size_bytes)}")
        lines.append(f"CHR ROM: {self._format_bytes(self.chr_rom_size_bytes)}")
        if self.prg_ram_size_bytes or self.prg_nvram_size_bytes:
            ram_desc = f"PRG RAM: {self._format_bytes(self.prg_ram_size_bytes)}"
            if self.prg_nvram_size_bytes:
                ram_desc += f" (NV: {self._format_bytes(self.prg_nvram_size_bytes)})"
            lines.append(ram_desc)
        else:
            lines.append("PRG RAM: none declared")
        if self.chr_ram_size_bytes or self.chr_nvram_size_bytes:
            chr_desc = f"CHR RAM: {self._format_bytes(self.chr_ram_size_bytes)}"
            if self.chr_nvram_size_bytes:
                chr_desc += f" (NV: {self._format_bytes(self.chr_nvram_size_bytes)})"
            lines.append(chr_desc)
        lines.append(f"Mirroring: {self.mirroring}")
        lines.append(f"Battery-backed RAM: {'yes' if self.has_battery_backed_ram else 'no'}")
        lines.append(f"Trainer present: {'yes' if self.has_trainer else 'no'}")
        if self.is_vs_system:
            lines.append("Console type: VS System")
        if self.is_playchoice10:
            lines.append("Console type: PlayChoice-10")
        lines.append(f"TV System: {self.tv_system}")
        return lines


class SamsoftEmuNESGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SamsoftEmu NES v2.0")
        self.root.geometry("800x600")
        self.root.configure(bg="#1e1e1e")

        # Emulator state placeholders
        self.rom_path = None
        self.ines_header = None
        self.is_running = False
        self.version = "2.0"

        # UI setup
        self.create_menu()
        self.create_toolbar()
        self.create_statusbar()
        self.create_console()
    def create_menu(self):
        menubar = tk.Menu(self.root, bg="#2d2d2d", fg="white", tearoff=0)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open ROM", command=self.open_rom)
        file_menu.add_command(label="Reset Emulator", command=self.reset_emulator)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label="Debugger", command=self.launch_debugger)
        tools_menu.add_command(label="Cheats", command=self.launch_cheats)
        tools_menu.add_command(label="TAS Tools", command=self.launch_tas_tools)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def create_toolbar(self):
        toolbar = tk.Frame(self.root, bg="#2d2d2d", height=40)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        open_btn = tk.Button(toolbar, text="📂 Open ROM", command=self.open_rom,
                             bg="#3a3a3a", fg="white", relief=tk.FLAT, cursor="hand2")
        open_btn.pack(side=tk.LEFT, padx=5, pady=5)

        run_btn = tk.Button(toolbar, text="▶ Run", command=self.run_emulator,
                            bg="#4CAF50", fg="white", relief=tk.FLAT, cursor="hand2")
        run_btn.pack(side=tk.LEFT, padx=5, pady=5)

        reset_btn = tk.Button(toolbar, text="⟳ Reset", command=self.reset_emulator,
                              bg="#FF9800", fg="white", relief=tk.FLAT, cursor="hand2")
        reset_btn.pack(side=tk.LEFT, padx=5, pady=5)

        stop_btn = tk.Button(toolbar, text="■ Stop", command=self.stop_emulator,
                             bg="#f44336", fg="white", relief=tk.FLAT, cursor="hand2")
        stop_btn.pack(side=tk.LEFT, padx=5, pady=5)

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

        self.log("SamsoftEmu NES v2.0 GUI Ready")

    def log(self, msg):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, msg + "\n")
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)
    # Emulator actions
    def open_rom(self):
        filetypes = [("NES ROMs", "*.nes"), ("All files", "*.*")]
        filename = filedialog.askopenfilename(title="Select NES ROM", filetypes=filetypes)
        if not filename:
            return
        try:
            ines_header = INESHeader.from_path(filename)
        except (IOError, OSError) as io_err:
            messagebox.showerror("File Error", f"Unable to read ROM: {io_err}")
            self.log(f"[ERROR] Unable to read ROM: {io_err}")
            return
        except INESParseError as parse_err:
            messagebox.showerror("Invalid ROM", str(parse_err))
            self.log(f"[ERROR] {parse_err}")
            return

        self.rom_path = filename
        self.ines_header = ines_header
        rom_name = os.path.basename(filename)
        mapper_info = f"Mapper {ines_header.mapper}"
        if ines_header.submapper:
            mapper_info += f"/{ines_header.submapper}"
        self.status_var.set(f"Loaded ROM: {rom_name} | {mapper_info}")
        self.log(f"[ROM] Loaded: {filename}")
        for detail in ines_header.summary_lines():
            self.log(f"[iNES] {detail}")

    def run_emulator(self):
        if not self.rom_path:
            messagebox.showwarning("No ROM", "Please load a ROM first!")
            return
        self.is_running = True
        rom_name = os.path.basename(self.rom_path)
        if self.ines_header:
            header_tag = f"Mapper {self.ines_header.mapper}"
        else:
            header_tag = "Unknown mapper"
        self.status_var.set("Running...")
        self.log(f"[SYSTEM] Emulating {rom_name} ({header_tag}, stub backend)")
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

    def show_about(self):
        messagebox.showinfo("About SamsoftEmu NES",
                            "SamsoftEmu NES v2.0\nTkinter GUI Frontend\nAI Core Edition")


if __name__ == "__main__":
    root = tk.Tk()
    app = SamsoftEmuNESGUI(root)
    root.mainloop()
