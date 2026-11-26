#!/usr/bin/env python3
"""Watch Face Studio - Custom iOS Lock Screen Watch Face Creator & BLE Flasher.
Designed for Noise ColorFit Icon Buzz and MoYoung / Da Fit 240x280 smartwatches.
Supports 3D subject depth effect, custom clock fonts & opacity, color pickers,
and dynamic switching between 3 Mario-style health hearts and live battery percentage.
"""

import os, sys, shutil, subprocess, threading, queue, datetime
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk
import tkinter as tk
from tkinter import ttk, filedialog, colorchooser, messagebox

W, H = 240, 280

# Detect Orbitron font
orbitron_cache = os.path.join(os.path.expanduser('~'), '.cache', 'face_cli', 'Orbitron.ttf')
if not os.path.exists(orbitron_cache):
    if os.path.exists('Orbitron.ttf'):
        orbitron_cache = os.path.abspath('Orbitron.ttf')

DEFAULT_BLE_MAC = ""

class WatchFaceStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Watch Face Studio - iOS Lock Screen Watch Face Creator")
        self.geometry("1120x840")
        self.minsize(1020, 760)
        self.configure(bg="#181825")
        
        # State
        self.bg_path = tk.StringVar(value="")
        self.fg_path = tk.StringVar(value="")
        self.ble_address = tk.StringVar(value=DEFAULT_BLE_MAC)
        
        # Clock settings
        self.clock_font_name = tk.StringVar(value="Orbitron Black")
        self.clock_color = "#FFFFFF"
        self.clock_opacity = tk.IntVar(value=65)
        self.clock_w = tk.IntVar(value=46)
        self.clock_h = tk.IntVar(value=72)
        self.clock_y = tk.IntVar(value=34)
        self.depth_enabled = tk.BooleanVar(value=True)
        
        # Date settings
        self.date_enabled = tk.BooleanVar(value=True)
        self.date_color = "#FFFFFF"
        self.date_x = tk.IntVar(value=26)
        self.date_y = tk.IntVar(value=8)
        self.date_opacity = tk.IntVar(value=85)
        
        # Top-Right Display Mode: 3 Hearts Gauge vs Live Battery %
        self.top_right_mode = tk.StringVar(value="3 Hearts (Mario Style)")
        self.hearts_fill_style = tk.StringVar(value="Solid White Hearts")
        self.hearts_level = tk.StringVar(value="2.5 Hearts (~58% Battery)")
        self.hearts_color = "#FFFFFF"
        self.hearts_x = tk.IntVar(value=156)
        self.hearts_y = tk.IntVar(value=7)
        
        # Live Battery settings
        self.battery_color = "#FFFFFF"
        self.battery_x = tk.IntVar(value=182)
        self.battery_y = tk.IntVar(value=8)
        self.battery_sample = tk.IntVar(value=58)
        
        # Stats settings
        self.steps_enabled = tk.BooleanVar(value=True)
        self.steps_color = "#FFFFFF"
        self.steps_x = tk.IntVar(value=22)
        self.steps_y = tk.IntVar(value=254)
        self.steps_sample = tk.IntVar(value=0)
        
        self.hr_enabled = tk.BooleanVar(value=True)
        self.hr_color = "#FFFFFF"
        self.hr_x = tk.IntVar(value=198)
        self.hr_y = tk.IntVar(value=254)
        self.hr_sample = tk.IntVar(value=81)
        
        # Subject Framing
        self.scale_var = tk.DoubleVar(value=1.15)
        self.shift_x = tk.IntVar(value=0)
        self.shift_y = tk.IntVar(value=95)
        
        # Process queue
        self.log_queue = queue.Queue()
        self.is_flashing = False
        
        # Images
        self.im_orig = None
        self.im_cutout = None
        self.preview_tk = None
        
        self.auto_load_default_images()
        self.setup_ui()
        self.update_preview()
        self.check_log_queue()
        
    def auto_load_default_images(self):
        if os.path.exists('original.png'):
            self.bg_path.set(os.path.abspath('original.png'))
        if os.path.exists('cutout.png'):
            self.fg_path.set(os.path.abspath('cutout.png'))
        self.load_images()

    def load_images(self):
        bg = self.bg_path.get()
        fg = self.fg_path.get()
        if bg and os.path.exists(bg):
            try:
                self.im_orig = Image.open(bg).convert('RGB')
            except Exception:
                self.im_orig = None
        else:
            self.im_orig = None
            
        if fg and os.path.exists(fg):
            try:
                cut_raw = Image.open(fg)
                if cut_raw.mode == 'RGBA':
                    self.im_cutout = cut_raw
                else:
                    arr = np.array(cut_raw.convert('RGB'))
                    mask = (np.max(arr, axis=2) > 10).astype(np.uint8) * 255
                    mask_im = Image.fromarray(mask).filter(ImageFilter.GaussianBlur(1))
                    if self.im_orig and cut_raw.size != self.im_orig.size:
                        cut_resized = self.im_orig.copy().convert('RGBA')
                        mask_resized = mask_im.resize(self.im_orig.size, Image.LANCZOS)
                        cut_resized.putalpha(mask_resized)
                        self.im_cutout = cut_resized
                    else:
                        rgba = cut_raw.convert('RGBA')
                        rgba.putalpha(mask_im)
                        self.im_cutout = rgba
            except Exception:
                self.im_cutout = None
        else:
            self.im_cutout = None

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(".", background="#181825", foreground="#cdd6f4", font=("Segoe UI", 10))
        style.configure("TLabel", background="#181825", foreground="#cdd6f4")
        style.configure("Card.TFrame", background="#1e1e2e")
        style.configure("TButton", font=("Segoe UI Bold", 10), background="#313244", foreground="#cdd6f4", borderwidth=0)
        style.map("TButton", background=[("active", "#45475a")])
        style.configure("TCheckbutton", background="#1e1e2e", foreground="#cdd6f4")
        style.configure("TRadiobutton", background="#1e1e2e", foreground="#cdd6f4")

        # Top Bar
        top_bar = tk.Frame(self, bg="#1e1e2e", height=50)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        title_lbl = tk.Label(top_bar, text="⌚ Watch Face Studio  •  iOS Lock Screen Creator", font=("Segoe UI Bold", 14), bg="#1e1e2e", fg="#89b4fa")
        title_lbl.pack(side=tk.LEFT, padx=20, pady=10)
        
        mac_frame = tk.Frame(top_bar, bg="#1e1e2e")
        mac_frame.pack(side=tk.RIGHT, padx=20, pady=10)
        tk.Label(mac_frame, text="Watch BLE MAC:", font=("Segoe UI", 10), bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT, padx=5)
        mac_entry = tk.Entry(mac_frame, textvariable=self.ble_address, width=18, font=("Consolas", 10), bg="#313244", fg="#cdd6f4", insertbackground="white")
        mac_entry.pack(side=tk.LEFT, padx=5)

        # Paned Window
        main_paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg="#181825", sashwidth=4)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left Container
        left_container = tk.Frame(main_paned, bg="#181825")
        main_paned.add(left_container, minsize=500, stretch="always")

        canvas = tk.Canvas(left_container, bg="#181825", highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#181825")
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Right Container
        right_container = tk.Frame(main_paned, bg="#181825", width=420)
        main_paned.add(right_container, minsize=400, stretch="never")

        self.setup_controls(scrollable_frame)
        self.setup_preview_panel(right_container)

    def setup_controls(self, parent):
        pad = {'padx': 10, 'pady': 5}

        # 1. Images Card
        c1 = self.make_card(parent, "1. Images & Depth Cutout")
        r1 = tk.Frame(c1, bg="#1e1e2e")
        r1.pack(fill=tk.X, **pad)
        tk.Label(r1, text="Original Photo:", bg="#1e1e2e", fg="#cdd6f4", width=14, anchor="w").pack(side=tk.LEFT)
        bg_ent = tk.Entry(r1, textvariable=self.bg_path, font=("Segoe UI", 9), bg="#313244", fg="#cdd6f4")
        bg_ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(r1, text="Browse...", command=self.browse_bg).pack(side=tk.RIGHT)

        r2 = tk.Frame(c1, bg="#1e1e2e")
        r2.pack(fill=tk.X, **pad)
        tk.Label(r2, text="Cutout (No BG):", bg="#1e1e2e", fg="#cdd6f4", width=14, anchor="w").pack(side=tk.LEFT)
        fg_ent = tk.Entry(r2, textvariable=self.fg_path, font=("Segoe UI", 9), bg="#313244", fg="#cdd6f4")
        fg_ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(r2, text="Browse...", command=self.browse_fg).pack(side=tk.RIGHT)

        r_scale = tk.Frame(c1, bg="#1e1e2e")
        r_scale.pack(fill=tk.X, **pad)
        tk.Label(r_scale, text="Subject Scale:", bg="#1e1e2e", fg="#a6adc8", width=14, anchor="w").pack(side=tk.LEFT)
        s_sc = tk.Scale(r_scale, from_=0.5, to=2.0, resolution=0.05, variable=self.scale_var, orient=tk.HORIZONTAL, bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, command=lambda v: self.update_preview())
        s_sc.pack(side=tk.LEFT, fill=tk.X, expand=True)

        r_y = tk.Frame(c1, bg="#1e1e2e")
        r_y.pack(fill=tk.X, **pad)
        tk.Label(r_y, text="Head Y Pos:", bg="#1e1e2e", fg="#a6adc8", width=14, anchor="w").pack(side=tk.LEFT)
        s_y = tk.Scale(r_y, from_=50, to=150, variable=self.shift_y, orient=tk.HORIZONTAL, bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, command=lambda v: self.update_preview())
        s_y.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 2. Clock Card
        c2 = self.make_card(parent, "2. iPhone Clock Style & Depth")
        r_font = tk.Frame(c2, bg="#1e1e2e")
        r_font.pack(fill=tk.X, **pad)
        tk.Label(r_font, text="Clock Font:", bg="#1e1e2e", fg="#cdd6f4", width=14, anchor="w").pack(side=tk.LEFT)
        f_cb = ttk.Combobox(r_font, textvariable=self.clock_font_name, values=["Orbitron Black", "Segoe UI Bold"], state="readonly")
        f_cb.pack(side=tk.LEFT, padx=5)
        f_cb.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        r_col = tk.Frame(c2, bg="#1e1e2e")
        r_col.pack(fill=tk.X, **pad)
        tk.Label(r_col, text="Clock Color:", bg="#1e1e2e", fg="#cdd6f4", width=14, anchor="w").pack(side=tk.LEFT)
        self.btn_clock_col = tk.Button(r_col, bg=self.clock_color, width=4, relief="ridge", command=self.pick_clock_color)
        self.btn_clock_col.pack(side=tk.LEFT, padx=5)
        tk.Label(r_col, text="Opacity (%):", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT, padx=(15, 5))
        s_op = tk.Scale(r_col, from_=10, to=100, variable=self.clock_opacity, orient=tk.HORIZONTAL, bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, command=lambda v: self.update_preview())
        s_op.pack(side=tk.LEFT, fill=tk.X, expand=True)

        r_dim = tk.Frame(c2, bg="#1e1e2e")
        r_dim.pack(fill=tk.X, **pad)
        tk.Label(r_dim, text="Squeeze Height:", bg="#1e1e2e", fg="#a6adc8", width=14, anchor="w").pack(side=tk.LEFT)
        s_h = tk.Scale(r_dim, from_=55, to=95, variable=self.clock_h, orient=tk.HORIZONTAL, bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, command=lambda v: self.update_preview())
        s_h.pack(side=tk.LEFT, fill=tk.X, expand=True)

        r_ypos = tk.Frame(c2, bg="#1e1e2e")
        r_ypos.pack(fill=tk.X, **pad)
        tk.Label(r_ypos, text="Clock Y Pos:", bg="#1e1e2e", fg="#a6adc8", width=14, anchor="w").pack(side=tk.LEFT)
        s_cy = tk.Scale(r_ypos, from_=15, to=60, variable=self.clock_y, orient=tk.HORIZONTAL, bg="#1e1e2e", fg="#cdd6f4", highlightthickness=0, command=lambda v: self.update_preview())
        s_cy.pack(side=tk.LEFT, fill=tk.X, expand=True)

        cb_depth = ttk.Checkbutton(c2, text="Enable 3D Depth Effect (Clock behind subject)", variable=self.depth_enabled, command=self.update_preview)
        cb_depth.pack(anchor="w", **pad)

        # 3. Top Status Card: Date & Top-Right Gauge Switch
        c3 = self.make_card(parent, "3. Top Status: Date & Battery / Hearts Gauge")
        
        # Date
        r_date = tk.Frame(c3, bg="#1e1e2e")
        r_date.pack(fill=tk.X, **pad)
        ttk.Checkbutton(r_date, text="Live Date", variable=self.date_enabled, command=self.update_preview).pack(side=tk.LEFT)
        self.btn_date_col = tk.Button(r_date, bg=self.date_color, width=3, relief="ridge", command=self.pick_date_color)
        self.btn_date_col.pack(side=tk.LEFT, padx=10)
        tk.Label(r_date, text="X:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT)
        tk.Spinbox(r_date, from_=10, to=80, textvariable=self.date_x, width=3, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT, padx=3)
        tk.Label(r_date, text="Y:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT)
        tk.Spinbox(r_date, from_=2, to=30, textvariable=self.date_y, width=3, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT, padx=3)

        tk.Frame(c3, bg="#313244", height=1).pack(fill=tk.X, padx=10, pady=6)

        # Top-Right Mode Switch (User Request: switch between 3 Hearts and Battery %)
        r_mode = tk.Frame(c3, bg="#1e1e2e")
        r_mode.pack(fill=tk.X, **pad)
        tk.Label(r_mode, text="Top-Right Display:", font=("Segoe UI Bold", 10), bg="#1e1e2e", fg="#f9e2af", width=15, anchor="w").pack(side=tk.LEFT)
        m_cb = ttk.Combobox(r_mode, textvariable=self.top_right_mode, values=["3 Hearts (Mario Style)", "Live Battery % (Digits)", "Off"], state="readonly", width=22)
        m_cb.pack(side=tk.LEFT, padx=5)
        m_cb.bind("<<ComboboxSelected>>", lambda e: self.on_top_right_mode_change())

        # Sub-frame for Hearts Controls
        self.frame_hearts_opts = tk.Frame(c3, bg="#1e1e2e")
        self.frame_hearts_opts.pack(fill=tk.X, padx=15, pady=4)
        
        rh1 = tk.Frame(self.frame_hearts_opts, bg="#1e1e2e")
        rh1.pack(fill=tk.X, pady=2)
        tk.Label(rh1, text="Heart Level:", bg="#1e1e2e", fg="#cdd6f4", width=12, anchor="w").pack(side=tk.LEFT)
        hl_cb = ttk.Combobox(rh1, textvariable=self.hearts_level, values=[
            "2.5 Hearts (~58% Battery)",
            "3.0 Hearts (100% Battery)",
            "2.0 Hearts (~40% Battery)",
            "1.5 Hearts (~25% Battery)",
            "1.0 Heart (~15% Battery)",
            "0.5 Heart (~5% Battery)"
        ], state="readonly", width=24)
        hl_cb.pack(side=tk.LEFT, padx=5)
        hl_cb.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        rh2 = tk.Frame(self.frame_hearts_opts, bg="#1e1e2e")
        rh2.pack(fill=tk.X, pady=2)
        tk.Label(rh2, text="Heart Style:", bg="#1e1e2e", fg="#cdd6f4", width=12, anchor="w").pack(side=tk.LEFT)
        hs_cb = ttk.Combobox(rh2, textvariable=self.hearts_fill_style, values=[
            "White Outline + Shine (Mario)",
            "Solid White Hearts",
            "Classic Mario Red"
        ], state="readonly", width=24)
        hs_cb.pack(side=tk.LEFT, padx=5)
        hs_cb.bind("<<ComboboxSelected>>", lambda e: self.update_preview())

        tk.Label(rh2, text="X:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT, padx=(10, 2))
        tk.Spinbox(rh2, from_=130, to=200, textvariable=self.hearts_x, width=4, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT)

        # Sub-frame for Battery % Controls
        self.frame_batt_opts = tk.Frame(c3, bg="#1e1e2e")
        
        rb1 = tk.Frame(self.frame_batt_opts, bg="#1e1e2e")
        rb1.pack(fill=tk.X, pady=2)
        tk.Label(rb1, text="Battery Color:", bg="#1e1e2e", fg="#cdd6f4", width=12, anchor="w").pack(side=tk.LEFT)
        self.btn_batt_col = tk.Button(rb1, bg=self.battery_color, width=3, relief="ridge", command=self.pick_batt_color)
        self.btn_batt_col.pack(side=tk.LEFT, padx=5)
        tk.Label(rb1, text="Sample %:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT, padx=(10, 2))
        tk.Spinbox(rb1, from_=1, to=100, textvariable=self.battery_sample, width=4, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT)
        tk.Label(rb1, text="X:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT, padx=(10, 2))
        tk.Spinbox(rb1, from_=140, to=210, textvariable=self.battery_x, width=4, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT)

        # 4. Fitness Stats: Steps & BPM
        c4 = self.make_card(parent, "4. Bottom Fitness Stats")
        r_st = tk.Frame(c4, bg="#1e1e2e")
        r_st.pack(fill=tk.X, **pad)
        ttk.Checkbutton(r_st, text="Live Steps", variable=self.steps_enabled, command=self.update_preview).pack(side=tk.LEFT)
        self.btn_steps_col = tk.Button(r_st, bg=self.steps_color, width=3, relief="ridge", command=self.pick_steps_color)
        self.btn_steps_col.pack(side=tk.LEFT, padx=10)
        tk.Label(r_st, text="Sample:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT)
        tk.Spinbox(r_st, from_=0, to=99999, textvariable=self.steps_sample, width=6, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT, padx=4)

        r_hr = tk.Frame(c4, bg="#1e1e2e")
        r_hr.pack(fill=tk.X, **pad)
        ttk.Checkbutton(r_hr, text="Live BPM", variable=self.hr_enabled, command=self.update_preview).pack(side=tk.LEFT)
        self.btn_hr_col = tk.Button(r_hr, bg=self.hr_color, width=3, relief="ridge", command=self.pick_hr_color)
        self.btn_hr_col.pack(side=tk.LEFT, padx=10)
        tk.Label(r_hr, text="Sample:", bg="#1e1e2e", fg="#a6adc8").pack(side=tk.LEFT)
        tk.Spinbox(r_hr, from_=40, to=220, textvariable=self.hr_sample, width=4, bg="#313244", fg="#cdd6f4", command=self.update_preview).pack(side=tk.LEFT, padx=4)

    def on_top_right_mode_change(self):
        mode = self.top_right_mode.get()
        if "3 Hearts" in mode:
            self.frame_batt_opts.pack_forget()
            self.frame_hearts_opts.pack(fill=tk.X, padx=15, pady=4)
        elif "Battery %" in mode:
            self.frame_hearts_opts.pack_forget()
            self.frame_batt_opts.pack(fill=tk.X, padx=15, pady=4)
        else:
            self.frame_hearts_opts.pack_forget()
            self.frame_batt_opts.pack_forget()
        self.update_preview()

    def make_card(self, parent, title):
        frame = tk.Frame(parent, bg="#1e1e2e", bd=1, relief="solid")
        frame.pack(fill=tk.X, padx=10, pady=8)
        lbl = tk.Label(frame, text=title, font=("Segoe UI Bold", 11), bg="#1e1e2e", fg="#89b4fa")
        lbl.pack(anchor="w", padx=10, pady=(8, 4))
        return frame

    def setup_preview_panel(self, parent):
        lbl = tk.Label(parent, text="Live Watch Preview (240x280)", font=("Segoe UI Bold", 12), bg="#181825", fg="#89b4fa")
        lbl.pack(pady=(5, 5))

        chassis = tk.Frame(parent, bg="#11111b", bd=4, relief="ridge")
        chassis.pack(pady=5)
        
        self.canvas_preview = tk.Canvas(chassis, width=W, height=H, bg="#000000", highlightthickness=0)
        self.canvas_preview.pack(padx=8, pady=8)

        self.lbl_status = tk.Label(parent, text="Ready", font=("Segoe UI", 10), bg="#181825", fg="#a6adc8")
        self.lbl_status.pack(pady=(8, 2))

        self.progress_bar = ttk.Progressbar(parent, orient="horizontal", length=280, mode="determinate")
        self.progress_bar.pack(pady=4)

        btn_frame = tk.Frame(parent, bg="#181825")
        btn_frame.pack(pady=8)

        self.btn_flash = tk.Button(btn_frame, text="⚡ Build & Flash to Watch", font=("Segoe UI Bold", 11), bg="#a6e3a1", fg="#11111b", padx=15, pady=8, relief="flat", command=self.start_flash)
        self.btn_flash.pack(fill=tk.X, pady=4)

        self.btn_save = tk.Button(btn_frame, text="💾 Save face.bin Only", font=("Segoe UI", 10), bg="#313244", fg="#cdd6f4", padx=15, pady=5, relief="flat", command=self.save_bin_file)
        self.btn_save.pack(fill=tk.X, pady=4)

        self.txt_log = tk.Text(parent, height=6, width=42, font=("Consolas", 8), bg="#11111b", fg="#a6adc8", bd=0)
        self.txt_log.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

    def log(self, msg):
        self.log_queue.put(msg)

    def check_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.txt_log.insert(tk.END, msg + "\n")
            self.txt_log.see(tk.END)
            self.lbl_status.config(text=msg.split("\n")[-1][:50])
        self.after(100, self.check_log_queue)

    def browse_bg(self):
        f = filedialog.askopenfilename(title="Select Original Photo", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp")])
        if f:
            self.bg_path.set(f)
            self.load_images()
            self.update_preview()

    def browse_fg(self):
        f = filedialog.askopenfilename(title="Select Cutout Image", filetypes=[("PNG Cutout", "*.png *.jpg *.jpeg *.webp")])
        if f:
            self.fg_path.set(f)
            self.load_images()
            self.update_preview()

    def pick_clock_color(self):
        c = colorchooser.askcolor(color=self.clock_color)[1]
        if c:
            self.clock_color = c
            self.btn_clock_col.config(bg=c)
            self.update_preview()

    def pick_date_color(self):
        c = colorchooser.askcolor(color=self.date_color)[1]
        if c:
            self.date_color = c
            self.btn_date_col.config(bg=c)
            self.update_preview()

    def pick_batt_color(self):
        c = colorchooser.askcolor(color=self.battery_color)[1]
        if c:
            self.battery_color = c
            self.btn_batt_col.config(bg=c)
            self.update_preview()

    def pick_steps_color(self):
        c = colorchooser.askcolor(color=self.steps_color)[1]
        if c:
            self.steps_color = c
            self.btn_steps_col.config(bg=c)
            self.update_preview()

    def pick_hr_color(self):
        c = colorchooser.askcolor(color=self.hr_color)[1]
        if c:
            self.hr_color = c
            self.btn_hr_col.config(bg=c)
            self.update_preview()

    def hex_to_rgb(self, h):
        h = h.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def draw_white_mario_heart(self, d, x, y, bg_crop, s=17, state='full', style='White Outline + Shine (Mario)'):
        c1 = (x + s * 0.28, y + s * 0.28)
        c2 = (x + s * 0.72, y + s * 0.28)
        r = s * 0.28
        
        # Outer white contour
        d.ellipse((c1[0]-r, c1[1]-r, c1[0]+r, c1[1]+r), fill=(255, 255, 255, 255))
        d.ellipse((c2[0]-r, c2[1]-r, c2[0]+r, c2[1]+r), fill=(255, 255, 255, 255))
        d.polygon([(x+s*0.02, y+s*0.35), (x+s*0.98, y+s*0.35), (x+s*0.5, y+s*0.96)], fill=(255, 255, 255, 255))
        
        ir = r * 0.72
        sky_arr = np.array(bg_crop)[int(y):int(y+s), int(x):int(x+s)]
        sky_rgb = tuple(int(v) for v in np.mean(sky_arr, axis=(0,1))[:3]) if sky_arr.size > 0 else (40, 50, 70)
        dark_sky = tuple(max(0, v - 30) for v in sky_rgb)

        if "White Outline" in style:
            d.ellipse((c1[0]-ir, c1[1]-ir+s*0.02, c1[0]+ir, c1[1]+ir+s*0.02), fill=sky_rgb + (255,))
            if state == 'full':
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=sky_rgb + (255,))
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=sky_rgb + (255,))
                d.ellipse((x+s*0.20, y+s*0.18, x+s*0.34, y+s*0.32), fill=(255, 255, 255, 255))
            elif state == 'half':
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=dark_sky + (255,))
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.5, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=sky_rgb + (255,))
                d.polygon([(x+s*0.5, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=dark_sky + (255,))
                d.ellipse((x+s*0.20, y+s*0.18, x+s*0.34, y+s*0.32), fill=(255, 255, 255, 255))
                d.line([(x+s*0.5, y+s*0.25), (x+s*0.5, y+s*0.86)], fill=(255, 255, 255, 255), width=1)
            elif state == 'empty':
                d.ellipse((c1[0]-ir, c1[1]-ir+s*0.02, c1[0]+ir, c1[1]+ir+s*0.02), fill=dark_sky + (255,))
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=dark_sky + (255,))
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=dark_sky + (255,))

        elif "Solid White" in style:
            if state == 'full':
                pass
            elif state == 'half':
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=dark_sky + (255,))
                d.polygon([(x+s*0.5, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=dark_sky + (255,))
                d.line([(x+s*0.5, y+s*0.25), (x+s*0.5, y+s*0.86)], fill=(255, 255, 255, 255), width=1)
            elif state == 'empty':
                d.ellipse((c1[0]-ir, c1[1]-ir+s*0.02, c1[0]+ir, c1[1]+ir+s*0.02), fill=dark_sky + (255,))
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=dark_sky + (255,))
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=dark_sky + (255,))

        elif "Classic Mario Red" in style:
            fill_c = (235, 30, 30, 255)
            dark_c = (55, 10, 10, 255)
            d.ellipse((c1[0]-ir, c1[1]-ir+s*0.02, c1[0]+ir, c1[1]+ir+s*0.02), fill=fill_c)
            if state == 'full':
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=fill_c)
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=fill_c)
                d.ellipse((x+s*0.20, y+s*0.18, x+s*0.34, y+s*0.32), fill=(255, 255, 255, 255))
            elif state == 'half':
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=dark_c)
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.5, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=fill_c)
                d.polygon([(x+s*0.5, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=dark_c)
                d.ellipse((x+s*0.20, y+s*0.18, x+s*0.34, y+s*0.32), fill=(255, 255, 255, 255))
            elif state == 'empty':
                d.ellipse((c1[0]-ir, c1[1]-ir+s*0.02, c1[0]+ir, c1[1]+ir+s*0.02), fill=dark_c)
                d.ellipse((c2[0]-ir, c2[1]-ir+s*0.02, c2[0]+ir, c2[1]+ir+s*0.02), fill=dark_c)
                d.polygon([(x+s*0.14, y+s*0.36), (x+s*0.86, y+s*0.36), (x+s*0.5, y+s*0.86)], fill=dark_c)

    def render_composition(self, sample_time=None):
        if sample_time is None:
            now = datetime.datetime.now()
            sample_time = f"{now.hour:02d}:{now.minute:02d}"

        # 1. Framing
        if self.im_orig:
            base_sc = max(W / self.im_orig.width, H / self.im_orig.height)
            sc = base_sc * self.scale_var.get()
            nw = round(self.im_orig.width * sc)
            nh = round(self.im_orig.height * sc)
            bgr = self.im_orig.resize((nw, nh), Image.LANCZOS)
            
            left = max(0, min(nw - W, (nw - W) // 2 + self.shift_x.get()))
            top = max(0, min(nh - H, nh - H - self.shift_y.get()))
            bg_crop = bgr.crop((left, top, left + W, top + H))
            
            if self.im_cutout and self.depth_enabled.get():
                cutr = self.im_cutout.resize((nw, nh), Image.LANCZOS)
                fg_crop = cutr.crop((left, top, left + W, top + H))
            else:
                fg_crop = None
        else:
            bg_crop = Image.new('RGB', (W, H), (20, 25, 35))
            fg_crop = None

        comp = bg_crop.copy()
        d_comp = ImageDraw.Draw(comp, 'RGBA')

        # 2. Top-Right Gauge: 3 Hearts vs Battery %
        mode = self.top_right_mode.get()
        if "3 Hearts" in mode:
            hx = self.hearts_x.get()
            hy = self.hearts_y.get()
            style = self.hearts_fill_style.get()
            lvl = self.hearts_level.get()
            
            if "2.5" in lvl:
                states = ['full', 'full', 'half']
            elif "3.0" in lvl:
                states = ['full', 'full', 'full']
            elif "2.0" in lvl:
                states = ['full', 'full', 'empty']
            elif "1.5" in lvl:
                states = ['full', 'half', 'empty']
            elif "1.0" in lvl:
                states = ['full', 'empty', 'empty']
            elif "0.5" in lvl:
                states = ['half', 'empty', 'empty']
            else:
                states = ['full', 'full', 'half']
                
            for i, st in enumerate(states):
                self.draw_white_mario_heart(d_comp, hx + i * 22, hy, bg_crop, s=17, state=st, style=style)
                
        elif "Battery %" in mode:
            bx, by = self.battery_x.get(), self.battery_y.get()
            bcol = self.hex_to_rgb(self.battery_color)
            # Battery outline box
            d_comp.rectangle((bx, by + 1, bx + 16, by + 10), outline=bcol, width=1)
            d_comp.rectangle((bx + 16, by + 3, bx + 18, by + 8), fill=bcol)
            # Battery % sample digits
            f_pct = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 13)
            d_comp.text((bx + 21, by), f"{self.battery_sample.get()}%", font=f_pct, fill=bcol)

        # 3. Live Date
        if self.date_enabled.get():
            dx, dy = self.date_x.get(), self.date_y.get()
            f_date = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 14)
            d_col = self.hex_to_rgb(self.date_color)
            op = round(255 * (self.date_opacity.get() / 100))
            now = datetime.datetime.now()
            d_comp.text((dx, dy), f"{now.day:02d}", font=f_date, fill=d_col + (op,))
            d_comp.text((dx + 23, dy - 1), "/", font=f_date, fill=d_col + (op,))
            d_comp.text((dx + 32, dy), f"{now.month:02d}", font=f_date, fill=d_col + (op,))

        # 4. Bottom Stats
        f_stat = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 13)
        if self.steps_enabled.get():
            sx, sy = self.steps_x.get(), self.steps_y.get()
            s_col = self.hex_to_rgb(self.steps_color)
            d_comp.ellipse((sx - 14, sy + 3, sx - 9, sy + 12), fill=s_col)
            d_comp.ellipse((sx - 10, sy + 6, sx - 4, sy + 13), fill=s_col)
            d_comp.text((sx, sy), str(self.steps_sample.get()), font=f_stat, fill=s_col)

        if self.hr_enabled.get():
            hrx, hry = self.hr_x.get(), self.hr_y.get()
            hr_col = self.hex_to_rgb(self.hr_color)
            hx, hy = hrx - 14, hry + 4
            d_comp.ellipse((hx, hy, hx+4, hy+4), fill=hr_col)
            d_comp.ellipse((hx+3, hy, hx+7, hy+4), fill=hr_col)
            d_comp.polygon([(hx, hy+2), (hx+7, hy+2), (hx+3.5, hy+7)], fill=hr_col)
            d_comp.text((hrx, hry), str(self.hr_sample.get()), font=f_stat, fill=hr_col)

        # 5. Clock & Depth
        sw, sh = self.clock_w.get(), self.clock_h.get()
        cw = 12
        total = 4 * sw + cw
        x0 = (W - total) // 2
        cy = self.clock_y.get()

        slots_x = [x0, x0 + sw, x0 + 2 * sw + cw, x0 + 3 * sw + cw]
        colon_x = x0 + 2 * sw

        if "Orbitron" in self.clock_font_name.get() and orbitron_cache and os.path.exists(orbitron_cache):
            f_clk = ImageFont.truetype(orbitron_cache, 105)
            try: f_clk.set_variation_by_axes([900])
            except: pass
        else:
            f_clk = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 105)

        ws, tops, bots = [], [], []
        for c in '0123456789':
            l, t, r, b = f_clk.getbbox(c, anchor='ls')
            ws.append(r - l)
            tops.append(t)
            bots.append(b)
        dw_native = max(ws)
        asc, desc = -min(tops), max(bots)
        sw_native = dw_native + 4
        sh_native = asc + desc + 6
        base_y = 2 + asc

        c_col = self.hex_to_rgb(self.clock_color)
        op_c = round(255 * (self.clock_opacity.get() / 100))

        t_digits = sample_time.replace(":", "")[:4]
        for idx, ch in enumerate(t_digits):
            x = slots_x[idx]
            tile = comp.crop((x, cy, x + sw, cy + sh)).convert('RGBA')
            layer = Image.new('RGBA', (sw_native, sh_native), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((sw_native / 2, base_y), ch, font=f_clk, fill=c_col + (op_c,), anchor='ms')
            layer_resized = layer.resize((sw, sh), Image.LANCZOS)
            tile.alpha_composite(layer_resized)
            if fg_crop and self.depth_enabled.get():
                tile.alpha_composite(fg_crop.crop((x, cy, x + sw, cy + sh)))
            comp.paste(tile.convert('RGB'), (x, cy))

        c_tile = comp.crop((colon_x, cy, colon_x + cw, cy + sh)).convert('RGBA')
        clayer = Image.new('RGBA', (cw, sh), (0, 0, 0, 0))
        cd = ImageDraw.Draw(clayer)
        cd.ellipse((cw / 2 - 3, sh * 0.35 - 3, cw / 2 + 3, sh * 0.35 + 3), fill=c_col + (op_c,))
        cd.ellipse((cw / 2 - 3, sh * 0.65 - 3, cw / 2 + 3, sh * 0.65 + 3), fill=c_col + (op_c,))
        c_tile.alpha_composite(clayer)
        if fg_crop and self.depth_enabled.get():
            c_tile.alpha_composite(fg_crop.crop((colon_x, cy, colon_x + cw, cy + sh)))
        comp.paste(c_tile.convert('RGB'), (colon_x, cy))

        return comp.convert('RGB'), bg_crop, fg_crop

    def update_preview(self):
        try:
            comp, _, _ = self.render_composition()
            self.preview_tk = ImageTk.PhotoImage(comp)
            self.canvas_preview.delete("all")
            self.canvas_preview.create_image(0, 0, anchor="nw", image=self.preview_tk)
        except Exception as e:
            print("Preview error:", e)

    def build_binary(self, output_bin_path):
        self.log("Building watch face package...")
        build_dir = os.path.abspath("temp_studio_build")
        df = os.path.join(build_dir, "dawft")
        shutil.rmtree(df, ignore_errors=True)
        os.makedirs(df, exist_ok=True)

        _, bg_crop, fg_crop = self.render_composition()

        bg_final = bg_crop.copy()
        d_bg = ImageDraw.Draw(bg_final, 'RGBA')

        # Top-Right Elements
        mode = self.top_right_mode.get()
        if "3 Hearts" in mode:
            hx = self.hearts_x.get()
            hy = self.hearts_y.get()
            style = self.hearts_fill_style.get()
            lvl = self.hearts_level.get()
            if "2.5" in lvl: states = ['full', 'full', 'half']
            elif "3.0" in lvl: states = ['full', 'full', 'full']
            elif "2.0" in lvl: states = ['full', 'full', 'empty']
            elif "1.5" in lvl: states = ['full', 'half', 'empty']
            elif "1.0" in lvl: states = ['full', 'empty', 'empty']
            elif "0.5" in lvl: states = ['half', 'empty', 'empty']
            else: states = ['full', 'full', 'half']
            for i, st in enumerate(states):
                self.draw_white_mario_heart(d_bg, hx + i * 22, hy, bg_crop, s=17, state=st, style=style)
        elif "Battery %" in mode:
            bx, by = self.battery_x.get(), self.battery_y.get()
            bcol = self.hex_to_rgb(self.battery_color)
            d_bg.rectangle((bx, by + 1, bx + 16, by + 10), outline=bcol, width=1)
            d_bg.rectangle((bx + 16, by + 3, bx + 18, by + 8), fill=bcol)
            f_pct = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 11)
            d_bg.text((bx + 41, by + 1), '%', font=f_pct, fill=bcol)

        # Date separator
        if self.date_enabled.get():
            dx, dy = self.date_x.get(), self.date_y.get()
            f_date = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 14)
            d_col = self.hex_to_rgb(self.date_color)
            op = round(255 * (self.date_opacity.get() / 100))
            d_bg.text((dx + 23, dy - 1), "/", font=f_date, fill=d_col + (op,))

        # Steps icon
        if self.steps_enabled.get():
            sx, sy = self.steps_x.get(), self.steps_y.get()
            s_col = self.hex_to_rgb(self.steps_color)
            d_bg.ellipse((sx - 14, sy + 3, sx - 9, sy + 12), fill=s_col + (220,))
            d_bg.ellipse((sx - 10, sy + 6, sx - 4, sy + 13), fill=s_col + (220,))

        # HR icon
        if self.hr_enabled.get():
            hrx, hry = self.hr_x.get(), self.hr_y.get()
            hr_col = self.hex_to_rgb(self.hr_color)
            hx, hy = hrx - 14, hry + 4
            d_bg.ellipse((hx, hy, hx+4, hy+4), fill=hr_col + (220,))
            d_bg.ellipse((hx+3, hy, hx+7, hy+4), fill=hr_col + (220,))
            d_bg.polygon([(hx, hy+2), (hx+7, hy+2), (hx+3.5, hy+7)], fill=hr_col + (220,))

        bg_final = bg_final.convert('RGB')

        # Clock font setup
        sw, sh = self.clock_w.get(), self.clock_h.get()
        cw = 12
        total = 4 * sw + cw
        x0 = (W - total) // 2
        cy = self.clock_y.get()
        c_col = self.hex_to_rgb(self.clock_color)
        op_c = round(255 * (self.clock_opacity.get() / 100))

        if "Orbitron" in self.clock_font_name.get() and orbitron_cache and os.path.exists(orbitron_cache):
            f_clk = ImageFont.truetype(orbitron_cache, 105)
            try: f_clk.set_variation_by_axes([900])
            except: pass
        else:
            f_clk = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 105)

        ws, tops, bots = [], [], []
        for c in '0123456789':
            l, t, r, b = f_clk.getbbox(c, anchor='ls')
            ws.append(r - l)
            tops.append(t)
            bots.append(b)
        dw_native = max(ws)
        asc, desc = -min(tops), max(bots)
        sw_native = dw_native + 4
        sh_native = asc + desc + 6
        base_y = 2 + asc

        slots = {
            'H1': (0x40, x0),
            'H2': (0x41, x0 + sw),
            'M1': (0x43, x0 + 2 * sw + cw),
            'M2': (0x44, x0 + 3 * sw + cw)
        }
        colon_x = x0 + 2 * sw

        lines = []
        blobs = []
        compression_modes = []
        blob = 0

        def add_bmp(name, im, compress=True):
            nonlocal blob
            im = im.convert('RGB')
            blobs.append(im)
            im.save(os.path.join(df, name), format='BMP')
            compression_modes.append('TRY_RLE' if compress else 'NONE')
            blob += 1

        # Background
        add_bmp('background000.bmp', bg_final, compress=True)
        lines.append(f'faceData       0x01    000      0    0  {W}  {H}    background000.bmp   # BACKGROUND')

        # Clock Digits
        for name, (code, x) in slots.items():
            first_idx = blob
            for d in range(10):
                tile = bg_final.crop((x, cy, x + sw, cy + sh)).convert('RGBA')
                layer = Image.new('RGBA', (sw_native, sh_native), (0, 0, 0, 0))
                ImageDraw.Draw(layer).text((sw_native / 2, base_y), str(d), font=f_clk, fill=c_col + (op_c,), anchor='ms')
                layer_resized = layer.resize((sw, sh), Image.LANCZOS)
                tile.alpha_composite(layer_resized)
                if fg_crop and self.depth_enabled.get():
                    tile.alpha_composite(fg_crop.crop((x, cy, x + sw, cy + sh)))
                add_bmp(f'{name.lower()}_{d:03d}.bmp', tile, compress=True)
            lines.append(f'faceData       0x{code:02X}    {first_idx:03d}   {x:4d} {cy:4d}  {sw:3d}  {sh:3d}    {name.lower()}_000.bmp   # TIME_{name}')

        # Colon
        c_tile = bg_final.crop((colon_x, cy, colon_x + cw, cy + sh)).convert('RGBA')
        clayer = Image.new('RGBA', (cw, sh), (0, 0, 0, 0))
        cd = ImageDraw.Draw(clayer)
        cd.ellipse((cw / 2 - 3, sh * 0.35 - 3, cw / 2 + 3, sh * 0.35 + 3), fill=c_col + (op_c,))
        cd.ellipse((cw / 2 - 3, sh * 0.65 - 3, cw / 2 + 3, sh * 0.65 + 3), fill=c_col + (op_c,))
        c_tile.alpha_composite(clayer)
        if fg_crop and self.depth_enabled.get():
            c_tile.alpha_composite(fg_crop.crop((colon_x, cy, colon_x + cw, cy + sh)))
        colon_idx = blob
        add_bmp('colon_000.bmp', c_tile, compress=False)
        lines.append(f'faceData       0xF0    {colon_idx:03d}   {colon_x:4d} {cy:4d}  {cw:3d}  {sh:3d}    colon_000.bmp   # SEPARATOR')

        bg_arr = np.array(bg_final)

        # Date Digits (0x30, 0x11)
        if self.date_enabled.get():
            dx, dy = self.date_x.get(), self.date_y.get()
            f_date = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 14)
            d_col = self.hex_to_rgb(self.date_color)
            op_d = round(255 * (self.date_opacity.get() / 100))
            w_date, h_date = 10, 14
            dfill = tuple(int(v) for v in np.mean(bg_arr[dy:dy+h_date, dx:dx+40], axis=(0,1)))
            date_start_idx = blob
            for d in range(10):
                t = Image.new('RGBA', (w_date, h_date), dfill + (255,))
                ImageDraw.Draw(t).text((w_date / 2, 12), str(d), font=f_date, fill=d_col + (op_d,), anchor='ms')
                add_bmp(f'date_{d:03d}.bmp', t, compress=False)
            lines.append(f'faceData       0x30    {date_start_idx:03d}     {dx:4d} {dy:4d}  {w_date:3d}  {h_date:3d}    date_000.bmp   # DAY_NUM')
            lines.append(f'faceData       0x11    {date_start_idx:03d}     {dx+32:4d} {dy:4d}  {w_date:3d}  {h_date:3d}    date_000.bmp   # MONTH_NUM')

        # Live Battery Digits (0xD2 BATT) - Only if in Battery % Mode!
        if "Battery %" in mode:
            bx, by = self.battery_x.get(), self.battery_y.get()
            f_batt = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 13)
            b_col = self.hex_to_rgb(self.battery_color)
            w_batt, h_batt = 9, 14
            bfill = tuple(int(v) for v in np.mean(bg_arr[by:by+h_batt, bx:bx+25], axis=(0,1)))
            batt_start_idx = blob
            for d in range(10):
                t = Image.new('RGBA', (w_batt, h_batt), bfill + (255,))
                ImageDraw.Draw(t).text((w_batt / 2, 12), str(d), font=f_batt, fill=b_col + (255,), anchor='ms')
                add_bmp(f'batt_{d:03d}.bmp', t, compress=False)
            lines.append(f'faceData       0xD2    {batt_start_idx:03d}     {bx:4d} {by:4d}  {w_batt:3d}  {h_batt:3d}    batt_000.bmp   # BATT_LA')

        # Steps Digits (0x62)
        if self.steps_enabled.get():
            sx, sy = self.steps_x.get(), self.steps_y.get()
            f_stat = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 13)
            s_col = self.hex_to_rgb(self.steps_color)
            w_stat, h_stat = 9, 14
            sfill = tuple(int(v) for v in np.mean(bg_arr[sy:sy+h_stat, sx:sx+40], axis=(0,1)))
            steps_start_idx = blob
            for d in range(10):
                t = Image.new('RGBA', (w_stat, h_stat), sfill + (255,))
                ImageDraw.Draw(t).text((w_stat / 2, 12), str(d), font=f_stat, fill=s_col + (255,), anchor='ms')
                add_bmp(f'step_{d:03d}.bmp', t, compress=False)
            lines.append(f'faceData       0x62    {steps_start_idx:03d}     {sx:4d} {sy:4d}  {w_stat:3d}  {h_stat:3d}    step_000.bmp   # STEPS')

        # Heart Rate Digits (0x65)
        if self.hr_enabled.get():
            hrx, hry = self.hr_x.get(), self.hr_y.get()
            f_stat = ImageFont.truetype('C:/Windows/Fonts/segoeuib.ttf', 13)
            hr_col = self.hex_to_rgb(self.hr_color)
            w_stat, h_stat = 9, 14
            hrfill = tuple(int(v) for v in np.mean(bg_arr[hry:hry+h_stat, hrx:hrx+35], axis=(0,1)))
            hr_start_idx = blob
            for d in range(10):
                t = Image.new('RGBA', (w_stat, h_stat), hrfill + (255,))
                ImageDraw.Draw(t).text((w_stat / 2, 12), str(d), font=f_stat, fill=hr_col + (255,), anchor='ms')
                add_bmp(f'hr_{d:03d}.bmp', t, compress=False)
            lines.append(f'faceData       0x65    {hr_start_idx:03d}     {hrx:4d} {hry:4d}  {w_stat:3d}  {h_stat:3d}    hr_000.bmp   # HR')

        # Preview blob with current live time
        comp_preview, _, _ = self.render_composition()
        pv = comp_preview.resize((140, 163), Image.LANCZOS)
        add_bmp(f'{blob:03d}.bmp', pv, compress=True)

        # Write watchface.txt
        comp_str = '\n'.join(f'blobCompression {i:03d}  {m}' for i, m in enumerate(compression_modes))
        txt = (f'fileType       C\nfileID         0x81\n'
               f'dataCount      {len(lines)}\nblobCount      {blob}\nfaceNumber     50010\n\n'
               '#              TYPE  INDEX      X    Y    W    H    FILENAME\n' + '\n'.join(lines) +
               '\n\n# blobs\n#             INDEX  CTYPE\n' + comp_str + '\n')

        with open(os.path.join(df, 'watchface.txt'), 'w') as f:
            f.write(txt)

        dawft_exe = r'C:\Users\ASUS\AppData\Local\Temp\dawft\dawft.x64.exe'
        if not os.path.exists(dawft_exe):
            dawft_exe = 'dawft.x64.exe'

        r = subprocess.run([dawft_exe, 'create', f'folder={df}', output_bin_path], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"dawft packer error: {r.stderr}")
        self.log(f"Successfully generated {output_bin_path} ({os.path.getsize(output_bin_path)} bytes)")

    def save_bin_file(self):
        dest = filedialog.asksaveasfilename(defaultextension=".bin", filetypes=[("Watch Face Binary", "*.bin")])
        if dest:
            try:
                self.build_binary(dest)
                messagebox.showinfo("Success", f"Watch face successfully saved to:\n{dest}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to build watch face:\n{e}")

    def start_flash(self):
        if self.is_flashing:
            return
        self.is_flashing = True
        self.btn_flash.config(state="disabled", text="Flashing in progress...")
        self.progress_bar["value"] = 0
        threading.Thread(target=self.flash_worker, daemon=True).start()

    def flash_worker(self):
        try:
            target_bin = os.path.abspath("temp_studio_face.bin")
            self.build_binary(target_bin)
            
            mac = self.ble_address.get().strip() or DEFAULT_BLE_MAC
            self.log(f"Connecting to watch BLE ({mac})...")
            
            cmd = [sys.executable, "-u", "face_cli.py", "--upload-file", target_bin, "--address", mac, "--yes"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            
            for line in p.stdout:
                line_str = line.strip()
                if line_str:
                    self.log(line_str)
                    if "%" in line_str:
                        parts = line_str.replace("\r", " ").split()
                        for part in parts:
                            if part.endswith("%"):
                                try:
                                    pct = int(part[:-1])
                                    self.after(0, lambda p=pct: self.progress_bar.configure(value=p))
                                except: pass
            p.wait()
            if p.returncode == 0:
                self.log("✅ Flash complete! Check the watch.")
                self.after(0, lambda: messagebox.showinfo("Finished", "Watch Face uploaded successfully! Open the watch face list to enjoy your new watch face."))
            else:
                self.log("❌ Flash failed. Make sure watch is awake and nearby.")
                self.after(0, lambda: messagebox.showerror("Error", "Upload failed. Make sure your watch is near and on the charger."))
        except Exception as e:
            self.log(f"Error: {e}")
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.is_flashing = False
            self.after(0, lambda: self.btn_flash.config(state="normal", text="⚡ Build & Flash to Watch"))

if __name__ == "__main__":
    app = WatchFaceStudio()
    app.mainloop()
