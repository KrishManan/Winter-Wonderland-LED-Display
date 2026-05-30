import time
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import serial
import serial.tools.list_ports

BAUD = 115200
NUM_LEDS = 300


class LedGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Winter Wonderland LED Controller")
        self.geometry("820x650")

        self.ser = None
        self.read_buffer = b""
        self.ui_ready = False

        # Keep a "shadow copy" of what we think the strip looks like
        self.led_state = [(0, 0, 0) for _ in range(NUM_LEDS)]

        # ----- DUMP parsing state -----
        self.dump_active = False
        self.dump_expected = NUM_LEDS
        self.dump_brightness = None
        self.dump_temp_state = None
        self.dump_count = 0

        # ----- STROBE state -----
        self.strobe_active = False

        # ---------- 1) Connect ----------
        top = ttk.LabelFrame(self, text="1) Connect to Arduino")
        top.pack(fill="x", padx=10, pady=8)

        self.port_var = tk.StringVar(value="")
        self.port_menu = ttk.Combobox(top, textvariable=self.port_var, state="readonly", width=20)
        self.port_menu.grid(row=0, column=0, padx=8, pady=8, sticky="w")

        ttk.Button(top, text="Refresh Ports", command=self.refresh_ports).grid(row=0, column=1, padx=8, pady=8)
        self.connect_btn = ttk.Button(top, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=2, padx=8, pady=8)
        self.disconnect_btn = ttk.Button(top, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_btn.grid(row=0, column=3, padx=8, pady=8)

        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(top, textvariable=self.status_var).grid(row=0, column=4, padx=8, pady=8, sticky="w")

        # ---------- 2) Save / Load ----------
        files = ttk.LabelFrame(self, text="2) Save / Load a Class Preset")
        files.pack(fill="x", padx=10, pady=8)

        ttk.Button(files, text="Save Preset (JSON)", command=self.save_json).grid(row=0, column=0, padx=8, pady=8)
        ttk.Button(files, text="Load Preset (JSON)", command=self.load_json).grid(row=0, column=1, padx=8, pady=8)
        ttk.Button(files, text="Save Preset (TXT)", command=self.save_txt).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(files, text="Load Preset (TXT)", command=self.load_txt).grid(row=0, column=3, padx=8, pady=8)

        self.file_status = tk.StringVar(value="No preset loaded")
        ttk.Label(files, textvariable=self.file_status).grid(row=0, column=4, padx=8, pady=8, sticky="w")

        # ---------- 3) Select LEDs ----------
        mid = ttk.LabelFrame(self, text="3) Choose which LEDs to change")
        mid.pack(fill="x", padx=10, pady=8)

        self.mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(mid, text="Single LED", variable=self.mode_var, value="single",
                        command=self.update_mode_widgets).grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Radiobutton(mid, text="Range", variable=self.mode_var, value="range",
                        command=self.update_mode_widgets).grid(row=0, column=1, padx=8, pady=6, sticky="w")
        ttk.Radiobutton(mid, text="List", variable=self.mode_var, value="list",
                        command=self.update_mode_widgets).grid(row=0, column=2, padx=8, pady=6, sticky="w")

        self.single_idx = tk.IntVar(value=0)
        ttk.Label(mid, text="LED #:").grid(row=1, column=0, padx=8, pady=6, sticky="e")
        self.single_spin = ttk.Spinbox(mid, from_=0, to=NUM_LEDS - 1, textvariable=self.single_idx, width=6)
        self.single_spin.grid(row=1, column=1, padx=8, pady=6, sticky="w")

        self.range_start = tk.IntVar(value=0)
        self.range_end = tk.IntVar(value=9)
        ttk.Label(mid, text="From / To:").grid(row=1, column=2, padx=8, pady=6, sticky="e")
        self.range_start_spin = ttk.Spinbox(mid, from_=0, to=NUM_LEDS - 1, textvariable=self.range_start, width=6)
        self.range_end_spin = ttk.Spinbox(mid, from_=0, to=NUM_LEDS - 1, textvariable=self.range_end, width=6)
        self.range_start_spin.grid(row=1, column=3, padx=4, pady=6, sticky="w")
        self.range_end_spin.grid(row=1, column=4, padx=4, pady=6, sticky="w")

        self.list_str = tk.StringVar(value="0,1,2,3")
        ttk.Label(mid, text="List (e.g. 0,5,9):").grid(row=2, column=0, padx=8, pady=6, sticky="e")
        self.list_entry = ttk.Entry(mid, textvariable=self.list_str, width=25)
        self.list_entry.grid(row=2, column=1, columnspan=2, padx=8, pady=6, sticky="w")

        # ---------- 4) Color ----------
        color = ttk.LabelFrame(self, text="4) Pick a color (RGB)")
        color.pack(fill="x", padx=10, pady=8)

        self.r_var = tk.DoubleVar(value=0)
        self.g_var = tk.DoubleVar(value=0)
        self.b_var = tk.DoubleVar(value=0)

        ttk.Label(color, text="Red").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        self.r_scale = ttk.Scale(color, from_=0, to=255, orient="horizontal", variable=self.r_var,
                                 command=lambda _v: self.update_preview())
        self.r_scale.grid(row=0, column=1, padx=8, pady=6, sticky="ew")

        ttk.Label(color, text="Green").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        self.g_scale = ttk.Scale(color, from_=0, to=255, orient="horizontal", variable=self.g_var,
                                 command=lambda _v: self.update_preview())
        self.g_scale.grid(row=1, column=1, padx=8, pady=6, sticky="ew")

        ttk.Label(color, text="Blue").grid(row=2, column=0, padx=8, pady=6, sticky="w")
        self.b_scale = ttk.Scale(color, from_=0, to=255, orient="horizontal", variable=self.b_var,
                                 command=lambda _v: self.update_preview())
        self.b_scale.grid(row=2, column=1, padx=8, pady=6, sticky="ew")

        for sc in (self.r_scale, self.g_scale, self.b_scale):
            sc.bind("<ButtonRelease-1>", self.on_slider_release)

        color.columnconfigure(1, weight=1)

        self.rgb_label = ttk.Label(color, text="RGB = (0, 0, 0)")
        self.rgb_label.grid(row=3, column=0, columnspan=2, padx=8, pady=6, sticky="w")

        self.preview = tk.Canvas(color, width=80, height=40, highlightthickness=1, highlightbackground="#888")
        self.preview.grid(row=0, column=2, rowspan=3, padx=10, pady=6)
        self.preview_rect = self.preview.create_rectangle(0, 0, 80, 40, fill="#000000", outline="")

        self.live_update = tk.BooleanVar(value=True)
        ttk.Checkbutton(color, text="Send when I let go of slider",
                        variable=self.live_update).grid(row=3, column=2, padx=10, pady=6, sticky="w")

        # ---------- 5) Actions ----------
        actions = ttk.LabelFrame(self, text="5) Send to LEDs")
        actions.pack(fill="x", padx=10, pady=8)

        self.apply_btn = ttk.Button(actions, text="Apply Color to Selected LEDs", command=self.apply_color)
        self.apply_btn.grid(row=0, column=0, padx=8, pady=8)

        self.fill_btn = ttk.Button(actions, text="Fill ALL LEDs with this Color", command=self.fill_all)
        self.fill_btn.grid(row=0, column=1, padx=8, pady=8)

        self.clear_btn = ttk.Button(actions, text="Clear (All OFF)", command=self.clear_all)
        self.clear_btn.grid(row=0, column=2, padx=8, pady=8)

        self.upload_btn = ttk.Button(actions, text="Upload CURRENT Preset to LEDs", command=self.upload_state_to_arduino)
        self.upload_btn.grid(row=0, column=3, padx=8, pady=8)

        self.bri_var = tk.DoubleVar(value=128)
        ttk.Label(actions, text="Brightness (max)").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        self.bri_scale = ttk.Scale(actions, from_=0, to=255, orient="horizontal", variable=self.bri_var)
        self.bri_scale.grid(row=1, column=1, padx=8, pady=6, sticky="ew")
        self.bri_scale.bind("<ButtonRelease-1>", self.send_brightness)
        actions.columnconfigure(1, weight=1)

        # ---------- 6) Sync + Effects ----------
        sync = ttk.LabelFrame(self, text="6) Sync + Effects (DUMP / STROBE)")
        sync.pack(fill="x", padx=10, pady=8)

        self.dump_btn = ttk.Button(sync, text="Sync from Arduino (DUMP)", command=self.request_dump)
        self.dump_btn.grid(row=0, column=0, padx=8, pady=8, sticky="w")

        self.dump_status = tk.StringVar(value="Dump: idle")
        ttk.Label(sync, textvariable=self.dump_status).grid(row=0, column=1, padx=8, pady=8, sticky="w")

        self.dump_bar = ttk.Progressbar(sync, length=240, mode="determinate", maximum=NUM_LEDS)
        self.dump_bar.grid(row=0, column=2, padx=8, pady=8, sticky="w")

        # Strobe controls
        stf = ttk.LabelFrame(sync, text="Strobe")
        stf.grid(row=1, column=0, columnspan=3, padx=8, pady=8, sticky="ew")

        self.strobe_var = tk.BooleanVar(value=False)

        ttk.Checkbutton(stf, text="Enable strobe (on/off fade)",
                        variable=self.strobe_var, command=self.on_strobe_toggle).grid(row=0, column=0, padx=8, pady=6, sticky="w")

        self.strobe_step_var = tk.IntVar(value=25)   # safer default than 10ms
        self.strobe_min_var = tk.IntVar(value=0)

        ttk.Label(stf, text="Step (ms):").grid(row=0, column=1, padx=8, pady=6, sticky="e")
        self.strobe_step_spin = ttk.Spinbox(stf, from_=1, to=500, textvariable=self.strobe_step_var, width=6)
        self.strobe_step_spin.grid(row=0, column=2, padx=4, pady=6, sticky="w")

        ttk.Label(stf, text="Min brightness:").grid(row=0, column=3, padx=8, pady=6, sticky="e")
        self.strobe_min_spin = ttk.Spinbox(stf, from_=0, to=255, textvariable=self.strobe_min_var, width=6)
        self.strobe_min_spin.grid(row=0, column=4, padx=4, pady=6, sticky="w")

        self.strobe_status = tk.StringVar(value="Strobe: OFF")
        ttk.Label(stf, textvariable=self.strobe_status).grid(row=0, column=5, padx=12, pady=6, sticky="w")

        stf.columnconfigure(6, weight=1)
        sync.columnconfigure(2, weight=1)

        # ---------- Log ----------
        logf = ttk.LabelFrame(self, text="Arduino Replies")
        logf.pack(fill="both", expand=True, padx=10, pady=8)

        self.log = tk.Text(logf, height=10, wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self.log.insert("end", "Tip: Connect, then try Fill or Apply.\n")

        # Finish init
        self.refresh_ports()
        self.update_mode_widgets()
        self.ui_ready = True
        self.update_preview()

        self.after(50, self.read_serial_loop)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- Serial ----------
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_menu["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])
        if not ports:
            self.port_var.set("")

    def connect(self):
        if self.ser:
            return
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("No Port", "Plug in the Arduino, then click Refresh Ports.")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=0.1)
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))
            return

        self.status_var.set(f"Connected to {port} @ {BAUD}")
        self.connect_btn.config(state="disabled")
        self.disconnect_btn.config(state="normal")

        time.sleep(2.0)
        self.flush_input()
        self.write_line("HELP")

    def disconnect(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.status_var.set("Not connected")
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")

        # reset states
        self.dump_active = False
        self.strobe_active = False
        self.strobe_var.set(False)
        self.strobe_status.set("Strobe: OFF")
        self.dump_status.set("Dump: idle")
        self.dump_bar["value"] = 0
        self.set_send_controls_enabled(True)

    def flush_input(self):
        if self.ser:
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass

    def write_line(self, text):
        if not self.ser:
            self.log_line("ERR Not connected\n")
            return
        try:
            self.ser.write((text.strip() + "\n").encode("ascii", errors="ignore"))
            self.ser.flush()
        except Exception as e:
            self.log_line(f"ERR write failed: {e}\n")

    def read_serial_loop(self):
        if self.ser:
            try:
                data = self.ser.read(256)
                if data:
                    self.read_buffer += data
                    while b"\n" in self.read_buffer:
                        line, self.read_buffer = self.read_buffer.split(b"\n", 1)
                        s = line.decode("utf-8", errors="replace").strip()
                        if s:
                            should_log = self.handle_serial_line(s)
                            if should_log:
                                self.log_line(s + "\n")
            except Exception:
                pass
        self.after(50, self.read_serial_loop)

    def log_line(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    # ---------- DUMP parsing ----------
    def handle_serial_line(self, s: str) -> bool:
        """
        Return True if this line should be printed in the log.
        DUMP data lines are suppressed (otherwise your log becomes huge).
        """
        # If we're currently in a dump, parse dump content
        if self.dump_active:
            if s.startswith("DUMP END"):
                # finalize
                self.dump_active = False
                if self.dump_temp_state is None:
                    self.dump_status.set("Dump: failed (no data)")
                    self.set_send_controls_enabled(True)
                    return False

                # Copy to our led_state (clamp to NUM_LEDS)
                n = min(NUM_LEDS, len(self.dump_temp_state))
                self.led_state = [(0, 0, 0) for _ in range(NUM_LEDS)]
                for i in range(n):
                    self.led_state[i] = self.dump_temp_state[i]

                if self.dump_brightness is not None:
                    self.bri_var.set(int(self.dump_brightness))

                self.dump_status.set(f"Dump: complete ({self.dump_count}/{self.dump_expected})")
                self.file_status.set("Synced from Arduino (DUMP) — you can Save now")
                self.log_line(f"[DUMP] Synced {self.dump_count} LEDs from Arduino.\n")

                self.dump_bar["value"] = min(self.dump_count, NUM_LEDS)
                self.set_send_controls_enabled(True)
                return False

            # regular dump line: "<idx> <r> <g> <b>"
            parts = s.split()
            if len(parts) == 4:
                try:
                    idx = int(parts[0])
                    r = int(parts[1]); g = int(parts[2]); b = int(parts[3])
                except Exception:
                    return False

                if 0 <= idx < NUM_LEDS and self.dump_temp_state is not None:
                    r = max(0, min(255, r))
                    g = max(0, min(255, g))
                    b = max(0, min(255, b))
                    self.dump_temp_state[idx] = (r, g, b)
                    self.dump_count += 1

                    # update progress occasionally
                    if self.dump_count % 10 == 0 or self.dump_count == self.dump_expected:
                        self.dump_bar["value"] = min(self.dump_count, NUM_LEDS)
                        self.dump_status.set(f"Dump: receiving {self.dump_count}/{self.dump_expected}")

            return False  # don't spam the log with dump data

        # Not in dump yet — look for "DUMP BEGIN ..."
        if s.startswith("DUMP BEGIN"):
            parts = s.split()
            # expected: DUMP BEGIN <num_leds> <brightness>
            if len(parts) >= 4:
                try:
                    self.dump_expected = int(parts[2])
                    self.dump_brightness = int(parts[3])
                except Exception:
                    self.dump_expected = NUM_LEDS
                    self.dump_brightness = None
            else:
                self.dump_expected = NUM_LEDS
                self.dump_brightness = None

            self.dump_active = True
            self.dump_count = 0
            self.dump_temp_state = [(0, 0, 0) for _ in range(NUM_LEDS)]

            self.dump_status.set(f"Dump: receiving 0/{self.dump_expected}")
            self.dump_bar["value"] = 0
            return False

        return True

    def request_dump(self):
        if not self.ser:
            messagebox.showwarning("Not connected", "Click Connect first.")
            return

        # For reliability: stop strobe before dump (strobe = lots of FastLED.show calls).
        if self.strobe_active:
            self.strobe_var.set(False)
            self.send_strobe(False)
            self.log_line("[INFO] Strobe stopped for DUMP.\n")

        # reset dump state and clear old incoming bytes
        self.dump_active = False
        self.dump_temp_state = None
        self.dump_count = 0
        self.dump_expected = NUM_LEDS
        self.dump_brightness = None

        self.flush_input()
        self.read_buffer = b""

        self.set_send_controls_enabled(False)
        self.dump_btn.config(state="disabled")
        self.dump_status.set("Dump: requested...")
        self.dump_bar["value"] = 0

        self.write_line("DUMP")

        # Re-enable the dump button shortly; the rest is controlled by dump completion
        self.after(500, lambda: self.dump_btn.config(state="normal"))

    # ---------- STROBE ----------
    def on_strobe_toggle(self):
        want = bool(self.strobe_var.get())
        self.send_strobe(want)

    def send_strobe(self, enable: bool):
        if not self.ser:
            self.strobe_var.set(False)
            self.strobe_active = False
            self.strobe_status.set("Strobe: OFF")
            return

        if enable:
            step_ms = int(self.strobe_step_var.get())
            min_bri = int(self.strobe_min_var.get())
            step_ms = max(1, min(500, step_ms))
            min_bri = max(0, min(255, min_bri))

            self.write_line(f"STROBE 1 {step_ms} {min_bri}")
            self.strobe_active = True
            self.strobe_status.set("Strobe: ON")
            # Disable heavy write actions while strobing (serial reliability)
            self.set_send_controls_enabled(False, keep_strobe=True)
        else:
            self.write_line("STROBE 0")
            self.strobe_active = False
            self.strobe_status.set("Strobe: OFF")
            self.set_send_controls_enabled(True)

    def set_send_controls_enabled(self, enabled: bool, keep_strobe: bool = False):
        """
        enabled=False disables the buttons that spam the serial link.
        keep_strobe=True keeps the strobe checkbox usable (so you can turn it off).
        """
        state = "normal" if enabled else "disabled"

        for w in (self.apply_btn, self.fill_btn, self.clear_btn, self.upload_btn):
            w.config(state=state)

        # Brightness changes are small; keep enabled unless we’re dumping
        if self.dump_active:
            self.bri_scale.config(state="disabled")
        else:
            self.bri_scale.config(state="normal")

        if keep_strobe:
            self.strobe_step_spin.config(state="normal")
            self.strobe_min_spin.config(state="normal")
        else:
            self.strobe_step_spin.config(state=state)
            self.strobe_min_spin.config(state=state)

    # ---------- UI ----------
    def update_mode_widgets(self):
        mode = self.mode_var.get()
        self.single_spin.config(state="normal" if mode == "single" else "disabled")

        st = "normal" if mode == "range" else "disabled"
        self.range_start_spin.config(state=st)
        self.range_end_spin.config(state=st)

        self.list_entry.config(state="normal" if mode == "list" else "disabled")

    def get_rgb(self):
        r = int(round(self.r_var.get()))
        g = int(round(self.g_var.get()))
        b = int(round(self.b_var.get()))
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        return r, g, b

    def update_preview(self):
        if not self.ui_ready:
            return
        r, g, b = self.get_rgb()
        self.rgb_label.config(text=f"RGB = ({r}, {g}, {b})")
        self.preview.itemconfig(self.preview_rect, fill=f"#{r:02x}{g:02x}{b:02x}")

    def on_slider_release(self, _event):
        self.update_preview()
        if self.live_update.get() and not self.strobe_active:
            self.apply_color()

    def get_selected_indices(self):
        mode = self.mode_var.get()

        if mode == "single":
            idx = int(self.single_idx.get())
            if not (0 <= idx < NUM_LEDS):
                raise ValueError("LED # must be between 0 and 299")
            return [idx]

        if mode == "range":
            a = int(self.range_start.get())
            b = int(self.range_end.get())
            if a > b:
                a, b = b, a
            if not (0 <= a < NUM_LEDS) or not (0 <= b < NUM_LEDS):
                raise ValueError("Range must be between 0 and 299")
            return list(range(a, b + 1))

        if mode == "list":
            raw = self.list_str.get().strip()
            if not raw:
                raise ValueError("Type a list like: 0,5,9")
            out = []
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                v = int(part)
                if not (0 <= v < NUM_LEDS):
                    raise ValueError("All LED numbers must be between 0 and 299")
                out.append(v)
            if not out:
                raise ValueError("List is empty")
            return out

        raise ValueError("Unknown selection mode")

    # ---------- Commands (and update shadow state) ----------
    def apply_color(self):
        if self.strobe_active:
            messagebox.showinfo("Strobe is ON", "Turn OFF strobe before editing LEDs.")
            return

        r, g, b = self.get_rgb()
        try:
            idxs = self.get_selected_indices()
        except Exception as e:
            messagebox.showerror("Selection error", str(e))
            return

        for i in idxs:
            self.led_state[i] = (r, g, b)

        if not self.ser:
            messagebox.showwarning("Not connected", "Click Connect first.")
            return

        if len(idxs) > 5:
            self.write_line("AUTO 0")
            for i in idxs:
                self.write_line(f"SET {i} {r} {g} {b}")
            self.write_line("SHOW")
            self.write_line("AUTO 1")
        else:
            for i in idxs:
                self.write_line(f"SET {i} {r} {g} {b}")

    def fill_all(self):
        if self.strobe_active:
            messagebox.showinfo("Strobe is ON", "Turn OFF strobe before editing LEDs.")
            return

        r, g, b = self.get_rgb()
        self.led_state = [(r, g, b) for _ in range(NUM_LEDS)]
        self.write_line(f"FILL {r} {g} {b}")

    def clear_all(self):
        if self.strobe_active:
            messagebox.showinfo("Strobe is ON", "Turn OFF strobe before editing LEDs.")
            return

        self.led_state = [(0, 0, 0) for _ in range(NUM_LEDS)]
        self.write_line("CLR")

    def send_brightness(self, _event):
        val = int(round(self.bri_var.get()))
        val = max(0, min(255, val))
        self.write_line(f"BRI {val}")

    def upload_state_to_arduino(self):
        if self.strobe_active:
            messagebox.showinfo("Strobe is ON", "Turn OFF strobe before uploading a preset.")
            return

        if not self.ser:
            messagebox.showwarning("Not connected", "Click Connect first.")
            return

        bri = int(round(self.bri_var.get()))
        bri = max(0, min(255, bri))
        self.write_line(f"BRI {bri}")

        self.write_line("AUTO 0")
        for i, (r, g, b) in enumerate(self.led_state):
            self.write_line(f"SET {i} {r} {g} {b}")
        self.write_line("SHOW")
        self.write_line("AUTO 1")

        self.log_line("Uploaded preset to LEDs.\n")

    # ---------- Save / Load ----------
    def save_json(self):
        path = filedialog.asksaveasfilename(
            title="Save preset as JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        data = {
            "version": 1,
            "num_leds": NUM_LEDS,
            "brightness": int(round(self.bri_var.get())),
            "colors": [[r, g, b] for (r, g, b) in self.led_state],
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.file_status.set(f"Saved: {path}")

    def load_json(self):
        path = filedialog.askopenfilename(
            title="Load preset JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return

        try:
            colors = data.get("colors")
            if not isinstance(colors, list):
                raise ValueError("JSON missing 'colors' list")

            new_state = [(0, 0, 0) for _ in range(NUM_LEDS)]
            for i in range(min(NUM_LEDS, len(colors))):
                rgb = colors[i]
                if (not isinstance(rgb, list)) or len(rgb) != 3:
                    continue
                r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                new_state[i] = (r, g, b)

            self.led_state = new_state

            bri = data.get("brightness", 128)
            bri = max(0, min(255, int(bri)))
            self.bri_var.set(bri)

        except Exception as e:
            messagebox.showerror("Bad preset file", str(e))
            return

        self.file_status.set(f"Loaded: {path}")

        if self.ser and messagebox.askyesno("Upload now?", "Preset loaded. Upload it to the LEDs now?"):
            self.upload_state_to_arduino()

    def save_txt(self):
        path = filedialog.asksaveasfilename(
            title="Save preset as TXT",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Winter Wonderland LED preset\n")
                f.write(f"# num_leds={NUM_LEDS}\n")
                f.write(f"# brightness={int(round(self.bri_var.get()))}\n")
                for i, (r, g, b) in enumerate(self.led_state):
                    f.write(f"{i} {r} {g} {b}\n")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.file_status.set(f"Saved: {path}")

    def load_txt(self):
        path = filedialog.askopenfilename(
            title="Load preset TXT",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not path:
            return

        new_state = [(0, 0, 0) for _ in range(NUM_LEDS)]
        bri = None

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("#"):
                        if "brightness=" in line:
                            try:
                                bri = int(line.split("brightness=", 1)[1].strip())
                            except Exception:
                                pass
                        continue

                    parts = line.split()
                    if len(parts) != 4:
                        continue
                    i = int(parts[0])
                    if not (0 <= i < NUM_LEDS):
                        continue
                    r = max(0, min(255, int(parts[1])))
                    g = max(0, min(255, int(parts[2])))
                    b = max(0, min(255, int(parts[3])))
                    new_state[i] = (r, g, b)

        except Exception as e:
            messagebox.showerror("Load failed", str(e))
            return

        self.led_state = new_state
        if bri is not None:
            self.bri_var.set(max(0, min(255, bri)))

        self.file_status.set(f"Loaded: {path}")

        if self.ser and messagebox.askyesno("Upload now?", "Preset loaded. Upload it to the LEDs now?"):
            self.upload_state_to_arduino()

    def on_close(self):
        self.disconnect()
        self.destroy()


if __name__ == "__main__":
    app = LedGui()
    app.mainloop()
