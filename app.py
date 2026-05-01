import os
import sys

# --- RUNTIME PATH FIXER (for PyInstaller frozen app) ---
if getattr(sys, 'frozen', False):
    _app_dir = os.path.dirname(sys.executable)
    _ai_libs = ['torch', 'cv2', 'whisper', 'torchvision', 'PIL', 'psutil',
                'deep_translator', 'tqdm', 'tiktoken']
    for _lib in _ai_libs:
        _lib_path = os.path.join(_app_dir, _lib)
        if os.path.isdir(_lib_path) and _lib_path not in sys.path:
            sys.path.insert(0, _lib_path)
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)

try:
    import torch
    HAS_TORCH = True
except ImportError:
    class _DummyTorch:
        def no_grad(self):
            return lambda fn: fn
        def device(self, *args, **kwargs):
            return None
        class _cuda:
            @staticmethod
            def is_available(): return False
            @staticmethod
            def get_device_name(*args): return "None"
        cuda = _cuda()
    torch = _DummyTorch()
    HAS_TORCH = False

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import subprocess
import shutil
import urllib.request
import zipfile
import glob
import json
import psutil
import re
import requests
import io
from PIL import Image, ImageTk, ImageDraw

# --- GLOBAL HARDWARE MANAGER ---
class HardwareManager:
    @staticmethod
    def get_info():
        has_cuda = HAS_TORCH and torch.cuda.is_available()
        info = {
            "has_cuda": has_cuda,
            "gpu_name": torch.cuda.get_device_name(0) if has_cuda else "None",
            "memory": f"{psutil.virtual_memory().total // (1024**3)} GB"
        }
        return info

GLOBAL_HW = HardwareManager.get_info()

# --- SETTINGS MANAGER (Persistence) ---
class SettingsManager:
    def __init__(self):
        self.settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
        self.defaults = {
            "prefer_gpu": True,
            "batch_size": 4
        }
        self.settings = self._load()

    def _load(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    # Overlay defaults for missing keys
                    for k,v in self.defaults.items():
                        if k not in data: data[k] = v
                    return data
            except: pass
        return self.defaults.copy()

    def save(self):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self.settings, f, indent=4)
        except: pass

    def get(self, key):
        return self.settings.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.settings[key] = value
        self.save()

GLOBAL_SETTINGS = SettingsManager()


# External imports for merged modules
import time
try:
    from deep_translator import GoogleTranslator
    HAS_DEEP_TRANS = True
except ImportError:
    HAS_DEEP_TRANS = False

try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

# Global Helpers for merged modules
def compute_ahash(image_path):
    """Compute Average Hash (a-hash) for an image"""
    try:
        with Image.open(image_path) as img:
            img = img.resize((8, 8), Image.Resampling.LANCZOS).convert('L')
            pixels = list(img.getdata())
            avg = sum(pixels) / 64
            diff = "".join(["1" if p >= avg else "0" for p in pixels])
            return int(diff, 2)
    except:
        return None

def hamming_distance(h1, h2):
    """Calculate hamming distance between two integers"""
    x = h1 ^ h2
    return bin(x).count("1")

class ImageFinderTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.source_img_path = tk.StringVar()
        self.target_dir      = tk.StringVar(value=os.path.expanduser("~/Pictures"))
        self.threshold_var   = tk.IntVar(value=5)
        self.status_var      = tk.StringVar(value="Ready to find similar images ✓")
        self.progress_var    = tk.DoubleVar(value=0)
        self.is_searching    = False
        self.is_cancelled    = False # New
        self.results         = []
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=10)
        header.pack(fill="x", padx=30)
        logo_frame = tk.Frame(header, bg=BG)
        logo_frame.pack()
        tk.Label(logo_frame, text="🔍", font=("Segoe UI Emoji", 24), fg=ACCENT2, bg=BG).pack(side="left")
        tk.Label(logo_frame, text=" Image", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_frame, text="Finder", font=("Impact", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(header, text="Find similar images in your folders using Perceptual Hashing (AI)", 
                 font=("Segoe UI", 10), fg=SUBTEXT, bg=BG).pack()
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)
        main_body = tk.Frame(self, bg=BG, padx=30, pady=20)
        main_body.pack(fill="both", expand=True)
        left_pane = tk.Frame(main_body, bg=BG, width=350)
        left_pane.pack(side="left", fill="both", padx=(0, 20))
        left_pane.pack_propagate(False)
        tk.Label(left_pane, text="🖼️  SOURCE IMAGE", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG, anchor="w").pack(fill="x")
        self.preview_canvas = tk.Canvas(left_pane, width=300, height=180, bg=BG2, highlightthickness=1, highlightbackground=BG3)
        self.preview_canvas.pack(pady=(8, 12))
        self.preview_canvas.create_text(150, 90, text="NO IMAGE SELECTED", fill=SUBTEXT, font=("Segoe UI", 9))
        tk.Button(left_pane, text="📁 SELECT SOURCE IMAGE", font=("Segoe UI", 9, "bold"), bg=BG3, fg=TEXT, relief="flat", cursor="hand2", pady=8, command=self._select_source).pack(fill="x", pady=(0, 20))
        tk.Label(left_pane, text="📂  TARGET FOLDER", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG, anchor="w").pack(fill="x")
        f_row = tk.Frame(left_pane, bg=BG)
        f_row.pack(fill="x", pady=(8, 12))
        entry_f = tk.Frame(f_row, bg=BG3, pady=2)
        entry_f.pack(side="left", fill="x", expand=True)
        self.folder_entry = tk.Entry(entry_f, textvariable=self.target_dir, font=("Consolas", 10), bg=BG3, fg=TEXT, insertbackground=ACCENT2, relief="flat", bd=5)
        self.folder_entry.pack(fill="x", padx=4)
        tk.Button(f_row, text="BROWSE", font=("Segoe UI", 8, "bold"), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", command=self._select_folder).pack(side="right", padx=(5, 0))
        tk.Label(left_pane, text="🎯  SIMILARITY THRESHOLD", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG, anchor="w").pack(fill="x")
        slider_frame = tk.Frame(left_pane, bg=BG2, padx=10, pady=10)
        slider_frame.pack(fill="x", pady=(8, 20))
        tk.Scale(slider_frame, from_=0, to=20, variable=self.threshold_var, orient="horizontal", bg=BG2, fg=SUBTEXT, highlightthickness=0, troughcolor=BG3, activebackground=ACCENT).pack(fill="x")
        tk.Label(slider_frame, text="(0 = Identical, 10 = Very Loose Match)", font=("Segoe UI", 8), fg=SUBTEXT, bg=BG2).pack()
        self.search_btn = tk.Button(left_pane, text="🔍  FIND SIMILAR IMAGES", font=("Impact", 15), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", pady=15, command=self._start_search)
        self.search_btn.pack(fill="x")
        
        self.cancel_btn = tk.Button(left_pane, text="🚫  CANCEL SEARCH", font=("Segoe UI", 10, "bold"), bg="#444", fg=TEXT, relief="flat", cursor="hand2", pady=10, command=self._cancel_search)
        # Hidden by default
        right_pane = tk.Frame(main_body, bg=BG2, padx=15, pady=15)
        right_pane.pack(side="right", fill="both", expand=True)
        tk.Label(right_pane, text="📄  SEARCH RESULTS", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        res_frame = tk.Frame(right_pane, bg=BG3, pady=2)
        res_frame.pack(fill="both", expand=True, pady=(10, 10))
        self.res_listbox = tk.Listbox(res_frame, bg=BG3, fg=TEXT, font=("Segoe UI", 10), relief="flat", bd=5, selectbackground=ACCENT, selectforeground=TEXT, highlightthickness=0)
        self.res_listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(res_frame, orient="vertical", command=self.res_listbox.yview)
        sb.pack(side="right", fill="y")
        self.res_listbox.config(yscrollcommand=sb.set)
        act_row = tk.Frame(right_pane, bg=BG2)
        act_row.pack(fill="x")
        tk.Button(act_row, text="📂 Open Folder", font=("Segoe UI", 9), bg=BG3, fg=TEXT, relief="flat", cursor="hand2", padx=15, command=self._open_result_folder).pack(side="left")
        tk.Button(act_row, text="🖼️ Open File", font=("Segoe UI", 9, "bold"), bg=ACCENT2, fg=BG, relief="flat", cursor="hand2", padx=20, command=self._open_result_file).pack(side="right")
        status_bar = tk.Frame(self, bg=BG, pady=5)
        status_bar.pack(fill="x", side="bottom")
        progress_f = tk.Frame(status_bar, bg=BG)
        progress_f.pack(fill="x", side="bottom", padx=30, pady=(0, 5))
        self.pbar = ttk.Progressbar(progress_f, variable=self.progress_var, maximum=100)
        self.pbar.pack(fill="x")
        tk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9), bg=BG, fg=SUBTEXT, padx=30).pack(side="left")

    def _update_preview(self, path):
        try:
            img = Image.open(path)
            img.thumbnail((300, 180))
            self.tk_preview = ImageTk.PhotoImage(img)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(150, 90, image=self.tk_preview)
        except: pass

    def _select_source(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.bmp")])
        if path:
            self.source_img_path.set(path)
            self._update_preview(path)

    def _select_folder(self):
        d = filedialog.askdirectory()
        if d: self.target_dir.set(d)

    def _start_search(self):
        if self.is_searching: return
        source, target = self.source_img_path.get(), self.target_dir.get()
        if not source or not os.path.exists(source) or not target or not os.path.isdir(target):
            messagebox.showwarning("Error", "Please select valid source image and target folder.")
            return
        self.is_searching = True
        self.is_cancelled = False
        self.search_btn.config(text="⌛ SEARCHING...", state="disabled", bg="#444")
        self.cancel_btn.pack(fill="x", pady=(10, 0)) # Show cancel button
        self.res_listbox.delete(0, tk.END)
        self.results = []
        self.progress_var.set(0)
        self.status_var.set("Scanning folder...")
        threading.Thread(target=self._search_thread, args=(source, target), daemon=True).start()

    def _cancel_search(self):
        self.is_cancelled = True
        self.status_var.set("Cancelling...")
        self.cancel_btn.config(state="disabled", text="⌛ CANCELLING...")

    def _compute_pixel_similarity(self, source_img, target_path):
        """Deep pixel-level comparison using PIL ImageChops"""
        try:
            from PIL import ImageChops, ImageStat
            with Image.open(target_path) as t_img:
                t_img = t_img.convert("RGB").resize(source_img.size)
                diff = ImageChops.difference(source_img, t_img)
                stat = ImageStat.Stat(diff)
                # Average brightness of the difference image (0-255)
                # Lower is more similar. Similarity = (1 - avg_diff/255)
                avg_diff = sum(stat.mean) / 3.0
                return max(0, (1.0 - avg_diff / 255.0) * 100.0)
        except:
            return 0.0

    def _search_thread(self, source_path, target_dir):
        try:
            s_hash = compute_ahash(source_path)
            if s_hash is None: raise Exception("Failed to process source image.")
            valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
            all_files = []
            for root, dirs, files in os.walk(target_dir):
                for f in files:
                    if f.lower().endswith(valid_exts): all_files.append(os.path.join(root, f))
            total = len(all_files)
            if total == 0:
                self.after(0, lambda: self.status_var.set("No images found."))
                return
            threshold = self.threshold_var.get()
            # Relax hash threshold slightly to catch more pixel candidates
            relaxed_thresh = threshold + 4
            
            # Load source image for pixel comparison once
            source_img = Image.open(source_path).convert("RGB").resize((128, 128))
            
            matches = []
            for i, f_path in enumerate(all_files):
                if not self.is_searching or self.is_cancelled: break
                f_hash = compute_ahash(f_path)
                if f_hash is not None:
                    dist = hamming_distance(s_hash, f_hash)
                    if dist <= relaxed_thresh:
                        # Stage 2: Deep Pixel Sim
                        pixel_sim = self._compute_pixel_similarity(source_img, f_path)
                        # We accept if Hash is very good OR Pixel match is very high
                        if dist <= threshold or pixel_sim > 90:
                            matches.append((f_path, pixel_sim))

                if i % 10 == 0 or i == total - 1:
                    pct = ((i + 1) / total) * 100
                    self.after(0, lambda p=pct: self.progress_var.set(p))
                    self.after(0, lambda n=i+1, t=total: self.status_var.set(f"Hybrid Scanning {n}/{t}..."))
            
            # Sort by Pixel Similarity (highest first)
            matches.sort(key=lambda x: x[1], reverse=True)
            self.results = matches
            self.after(0, self._update_res_ui)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.after(0, lambda: self.search_btn.config(text="🔍  FIND SIMILAR IMAGES", state="normal", bg=ACCENT))
            self.after(0, lambda: self.cancel_btn.pack_forget()) # Hide cancel
            self.is_searching = False

    def _update_res_ui(self):
        self.res_listbox.delete(0, tk.END)
        if not self.results: self.status_var.set("No matches found.")
        else:
            for path, sim in self.results:
                self.res_listbox.insert("end", f"[{sim:.1f}%] {os.path.basename(path)}")
            self.status_var.set(f"Found {len(self.results)} matches (Hybrid) ✓")
        self.search_btn.config(text="🔍  FIND SIMILAR IMAGES", state="normal", bg=ACCENT)
        self.cancel_btn.pack_forget() # Hide cancel
        self.is_searching = False

    def _open_result_folder(self):
        sel = self.res_listbox.curselection()
        if sel: os.startfile(os.path.dirname(self.results[sel[0]][0]))

    def _open_result_file(self):
        sel = self.res_listbox.curselection()
        if sel: os.startfile(self.results[sel[0]][0])

class TiktokTranslatorTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready ✓")
        self.output_lang = tk.StringVar(value="English")
        self.trans_mode = tk.StringVar(value="speech")
        self.languages = {
            "English": "en", "Thai": "th", "Japanese": "ja", "Korean": "ko",
            "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
            "French": "fr", "German": "de", "Spanish": "es", "Russian": "ru",
            "Vietnamese": "vi", "Indonesian": "id", "Arabic": "ar"
        }
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=20)
        header.pack(fill="x", padx=30)
        logo_frame = tk.Frame(header, bg=BG)
        logo_frame.pack()
        tk.Label(logo_frame, text="🎙️", font=("Segoe UI Emoji", 24), fg=ACCENT2, bg=BG).pack(side="left")
        tk.Label(logo_frame, text=" TikTok", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_frame, text="Translator", font=("Impact", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(header, text="Extract & Translate video captions or spoken words (AI)", font=("Segoe UI", 10), fg=SUBTEXT, bg=BG).pack()
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)
        card = tk.Frame(self, bg=BG2, padx=24, pady=24)
        card.pack(fill="both", expand=True, padx=30, pady=20)
        tk.Label(card, text="🔗  TikTok Video Link", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        url_frame = tk.Frame(card, bg=BG3, pady=2)
        url_frame.pack(fill="x", pady=(8, 16))
        self.url_entry = tk.Entry(url_frame, textvariable=self.url_var, font=("Consolas", 11), bg=BG3, fg=TEXT, insertbackground=ACCENT2, relief="flat", bd=8)
        self.url_entry.pack(fill="x", padx=4)
        mode_frame = tk.Frame(card, bg=BG2)
        mode_frame.pack(fill="x", pady=(0, 16))
        tk.Label(mode_frame, text="🛠️ Translation Source:", font=("Segoe UI", 10, "bold"), fg=SUBTEXT, bg=BG2).pack(side="left")
        tk.Radiobutton(mode_frame, text="📝 Video Description", variable=self.trans_mode, value="desc", bg=BG2, fg=TEXT, activebackground=BG2, activeforeground=ACCENT2, selectcolor=BG).pack(side="left", padx=(15, 10))
        tk.Radiobutton(mode_frame, text="🎙️ Video Speech (AI)", variable=self.trans_mode, value="speech", bg=BG2, fg=ACCENT2, activebackground=BG2, activeforeground=ACCENT2, selectcolor=BG).pack(side="left")
        lang_frame = tk.Frame(card, bg=BG2)
        lang_frame.pack(fill="x", pady=(0, 16))
        tk.Label(lang_frame, text="🎯 Target Language", font=("Segoe UI", 9, "bold"), fg=SUBTEXT, bg=BG2).pack(anchor="w")
        self.lang_cb = ttk.Combobox(lang_frame, textvariable=self.output_lang, values=list(self.languages.keys()), state="readonly", style="T.TCombobox", font=("Segoe UI", 10))
        self.lang_cb.pack(fill="x", pady=(4, 0))
        self.trans_btn = tk.Button(card, text="🚀  START TRANSLATION", font=("Impact", 14), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", pady=12, command=self._start_translation)
        self.trans_btn.pack(fill="x", pady=(0, 20))
        tk.Label(card, text="📝  Result Text:", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        res_frame = tk.Frame(card, bg=BG3, pady=2)
        res_frame.pack(fill="both", expand=True, pady=(8, 8))
        self.res_text = tk.Text(res_frame, font=("Inter", 11), bg=BG3, fg=TEXT, relief="flat", bd=10, wrap="word", height=12)
        self.res_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(res_frame, orient="vertical", command=self.res_text.yview)
        sb.pack(side="right", fill="y")
        self.res_text.config(yscrollcommand=sb.set)
        tk.Button(card, text="📋 Copy to Clipboard", font=("Segoe UI", 9, "bold"), bg=BG3, fg=TEXT, relief="flat", cursor="hand2", padx=20, pady=5, command=self._copy_result).pack(side="right")
        status_bar = tk.Frame(self, bg=BG2, pady=5)
        status_bar.pack(fill="x", side="bottom")
        tk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9), bg=BG2, fg=SUBTEXT, padx=20).pack(side="left")

    def _copy_result(self):
        content = self.res_text.get("1.0", tk.END).strip()
        if content:
            self.clipboard_clear(); self.clipboard_append(content)
            messagebox.showinfo("Success", "Copied!")

    def _start_translation(self):
        url = self.url_var.get().strip()
        if not url: return
        self.res_text.delete("1.0", tk.END)
        self.is_cancelled = False
        self.current_proc = None
        self.trans_btn.config(state="disabled", text="⌛ PROCESSING...")
        self.cancel_btn.pack(fill="x", pady=(10, 0)) # Show cancel
        threading.Thread(target=self._process, args=(url,), daemon=True).start()

    def _cancel_translation(self):
        self.is_cancelled = True
        self.status_var.set("Cancelling...")
        if hasattr(self, 'current_proc') and self.current_proc:
            try:
                import psutil
                parent = psutil.Process(self.current_proc.pid)
                for child in parent.children(recursive=True): child.kill()
                parent.kill()
            except: pass
        self.cancel_btn.config(state="disabled", text="⌛ CANCELLING...")

    def _process(self, url):
        temp_audio = f"temp_trans_{int(time.time())}.mp3"
        try:
            ytdlp = find_tool("yt-dlp")
            if not ytdlp: raise Exception("yt-dlp not found")
            mode = self.trans_mode.get()
            source_text = ""
            si = None
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            if mode == "desc":
                self.after(0, lambda: self.status_var.set("🔍 Extracting metadata..."))
                cmd = [ytdlp, "--dump-json", "--skip-download", url]
                proc = subprocess.run(cmd, startupinfo=si, capture_output=True, text=True, encoding='utf-8')
                data = json.loads(proc.stdout)
                source_text = data.get("description") or data.get("title", "")
            else:
                self.after(0, lambda: self.status_var.set("🎵 Downloading audio..."))
                subprocess.run([ytdlp, "-x", "--audio-format", "mp3", "-o", temp_audio, url], startupinfo=si, check=True)
                self.after(0, lambda: self.status_var.set("🤖 AI Transcribing (Whisper)..."))
                model = whisper.load_model("base")
                result = model.transcribe(temp_audio)
                source_text = result.get("text", "").strip()

            target_lang = self.output_lang.get()
            target_code = self.languages.get(target_lang, "en")
            self.after(0, lambda: self.status_var.set(f"🌐 Translating..."))
            translated = GoogleTranslator(source='auto', target=target_code).translate(source_text)
            
            def done(t=translated, s=source_text):
                self.res_text.insert("1.0", f"--- SOURCE ---\n{s}\n\n--- TRANSLATED ---\n{t}")
                self.trans_btn.config(state="normal", text="🚀  START TRANSLATION")
                self.status_var.set("Done ✓")
            self.after(0, done)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.trans_btn.config(state="normal", text="🚀  START TRANSLATION")
        finally:
            if os.path.exists(temp_audio): os.remove(temp_audio)

class TikTokImageAgentTab(tk.Frame):
    """
    SnapTik-style Image Agent: Extracts hidden high-quality images from TikTok Photo Posts
    by reading the embedded JSON metadata.
    """
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Agent Ready ✓")
        self.images = [] 
        self.metadata = {}
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=20)
        header.pack(fill="x", padx=30)
        logo_frame = tk.Frame(header, bg=BG)
        logo_frame.pack()
        tk.Label(logo_frame, text="📸", font=("Segoe UI Emoji", 24), fg=ACCENT2, bg=BG).pack(side="left")
        tk.Label(logo_frame, text=" TikTok", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_frame, text="Image Agent", font=("Impact", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(header, text="Extract hidden high-quality images from photo posts (SnapTik Logic)", 
                 font=("Segoe UI", 10), fg=SUBTEXT, bg=BG).pack()

        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)

        card = tk.Frame(self, bg=BG2, padx=24, pady=24)
        card.pack(fill="both", expand=True, padx=30, pady=20)

        tk.Label(card, text="🔗  TikTok Photo Link", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        url_frame = tk.Frame(card, bg=BG3, pady=2)
        url_frame.pack(fill="x", pady=(8, 16))
        self.url_entry = tk.Entry(url_frame, textvariable=self.url_var, font=("Consolas", 11), bg=BG3, fg=TEXT, insertbackground=ACCENT2, relief="flat", bd=8)
        self.url_entry.pack(fill="x", padx=4)
        self.url_entry.bind("<Return>", lambda e: self._fetch_metadata())

        self.fetch_btn = tk.Button(card, text="🔍  SCAN METADATA & EXTRACT", font=("Impact", 14), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", pady=12, command=self._fetch_metadata)
        self.fetch_btn.pack(fill="x", pady=(0, 20))

        # Result Info
        self.info_f = tk.Frame(card, bg=BG2)
        self.info_f.pack(fill="x", pady=(0, 10))
        self.title_lbl = tk.Label(self.info_f, text="", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=BG2, wraplength=500, justify="left")
        self.title_lbl.pack(anchor="w")
        self.author_lbl = tk.Label(self.info_f, text="", font=("Segoe UI", 9), fg=SUBTEXT, bg=BG2)
        self.author_lbl.pack(anchor="w")

        # Results List
        res_container = tk.Frame(card, bg=BG3, pady=2)
        res_container.pack(fill="both", expand=True, pady=(8, 8))
        self.res_listbox = tk.Listbox(res_container, font=("Segoe UI", 10), bg=BG3, fg=TEXT, relief="flat", bd=10, selectbackground=ACCENT, selectforeground=TEXT, highlightthickness=0)
        self.res_listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(res_container, orient="vertical", command=self.res_listbox.yview)
        sb.pack(side="right", fill="y")
        self.res_listbox.config(yscrollcommand=sb.set)

        act_row = tk.Frame(card, bg=BG2)
        act_row.pack(fill="x", pady=(10, 0))
        self.dl_btn = tk.Button(act_row, text="💾 DOWNLOAD ALL (NO WATERMARK)", font=("Segoe UI", 10, "bold"), bg=SUCCESS, fg=BG, relief="flat", cursor="hand2", padx=20, pady=10, command=self._download_all, state="disabled")
        self.dl_btn.pack(side="right")

        status_bar = tk.Frame(self, bg=BG2, pady=5)
        status_bar.pack(fill="x", side="bottom")
        tk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9), bg=BG2, fg=SUBTEXT, padx=20).pack(side="left")

    def _fetch_metadata(self):
        url = self.url_var.get().strip()
        if not url: return
        self.fetch_btn.config(state="disabled", text="⌛ READING METADATA...")
        self.status_var.set("Scanning TikTok for hidden data...")
        threading.Thread(target=self._fetch_thread, args=(url,), daemon=True).start()

    def _fetch_thread(self, url):
        try:
            # --- TikWM API Approach ---
            tikwm_url = f"https://www.tikwm.com/api/?url={url}"
            images = []
            title, author = "TikTok Post", "Unknown"
            try:
                tik_resp = requests.get(tikwm_url, timeout=10)
                if tik_resp.status_code == 200:
                    tk_data = tik_resp.json()
                    if tk_data.get("code") == 0:
                        data = tk_data.get("data", {})
                        images = data.get("images", [])
                        title = data.get("title", title)
                        author = data.get("author", {}).get("nickname", author)
            except: pass

            # --- SnapTik Scraper Fallback ---
            if not images:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    pattern = r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>'
                    match = re.search(pattern, resp.text) or re.search(r'<script id="SIGI_STATE" type="application/json">(.*?)</script>', resp.text)
                    if match:
                        data = json.loads(match.group(1))
                        try:
                            if "__DEFAULT_SCOPE__" in data:
                                item = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
                                title = item.get("desc", title)
                                author = item.get("author", {}).get("nickname", author)
                                if "imagePost" in item:
                                    images = [img.get("display_image", {}).get("url_list", [None])[0] for img in item["imagePost"]["images"]]
                            elif "ItemModule" in data:
                                item_id = list(data["ItemModule"].keys())[0]
                                item = data["ItemModule"][item_id]
                                title = item.get("desc", title)
                                author = item.get("nickname", author)
                                if "imagePost" in item:
                                    images = [img.get("display_image", {}).get("url_list", [None])[0] for img in item["imagePost"]["images"]]
                        except: pass

            if not images: raise Exception("No images found. Is this a photo post?")
            self.images = [u for u in images if u]
            
            def update_ui():
                self.title_lbl.config(text=title[:120])
                self.author_lbl.config(text=f"Author: {author}")
                self.res_listbox.delete(0, tk.END)
                for i, img_url in enumerate(self.images):
                    self.res_listbox.insert("end", f"📷 Image {i+1}")
                self.dl_btn.config(state="normal")
                self.fetch_btn.config(state="normal", text="🔍 SCAN METADATA & EXTRACT")
                self.status_var.set(f"Extracted {len(self.images)} URLs ✓")
                self._show_gallery()

            self.after(0, update_ui)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Agent Error", str(e)))
            self.after(0, lambda: self.fetch_btn.config(state="normal", text="🔍 SCAN METADATA & EXTRACT"))
            self.after(0, lambda: self.status_var.set("Scanning failed ❌"))

    def _show_gallery(self):
        if not self.images: return
        # Find main app for save_path
        app = self.winfo_toplevel()
        save_dir = getattr(app, 'save_path', None)
        if save_dir: save_dir = save_dir.get()
        else: save_dir = os.path.expanduser("~/Downloads")
        
        gallery = ImageGallery(self, self.images, save_dir)
        gallery.lift()
        gallery.attributes('-topmost', True)
        gallery.after(500, lambda: gallery.attributes('-topmost', False))
        gallery.focus_force()

    def _download_all(self):
        self._show_gallery()

class ImageGallery(tk.Toplevel):
    def __init__(self, parent, images, save_dir):
        super().__init__(parent)
        self.title("TikTok Photo Gallery")
        self.configure(bg="#050505")
        self.images = images
        self.save_dir = save_dir
        self.selections = [tk.BooleanVar(value=True) for _ in images]
        
        # UI Styles
        self.accent = "#fe2c55"  # TikTok Red
        self.bg_card = "#1a1a1a"
        
        # --- Responsive Sizing ---
        # Detect actual screen dimensions
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        
        # Window = 92% of screen
        win_w = int(sw * 0.92)
        win_h = int(sh * 0.92)
        # Center on screen
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.resizable(True, True)
        
        # Thumbnail = each column gets ~45% of window width
        # 2 columns, minus padding (~80px per card)
        self.THUMB_W = max(300, (win_w - 120) // 2)
        self.THUMB_H = max(200, int(self.THUMB_W * 0.55))  # ~16:9 ratio
        self.COLS = 2 if win_w < 1400 else 3
        
        self._build_ui()

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg="#121212", pady=20)
        header.pack(fill="x")
        
        tk.Label(header, text=f"📸 {len(self.images)} PHOTOS FOUND", font=("Segoe UI", 16, "bold"), fg="white", bg="#121212").pack(side="left", padx=30)
        
        self.sel_all_var = tk.BooleanVar(value=True)
        tk.Checkbutton(header, text="Select All", variable=self.sel_all_var, command=self._toggle_all, font=("Segoe UI", 10), bg="#121212", fg="white", selectcolor="#333", activebackground="#121212").pack(side="right", padx=30)

        # Scrollable Area
        container = tk.Frame(self, bg="#0f0f0f")
        container.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.canvas = tk.Canvas(container, bg="#0f0f0f", highlightthickness=0)
        sb = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="#0f0f0f")
        
        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        inner_w = self.COLS * (self.THUMB_W + 50)
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw", width=inner_w)
        self.canvas.configure(yscrollcommand=sb.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        
        # Mouse wheel scrolling (works anywhere in the window)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        # Image Grid
        cols = self.COLS
        THUMB_W, THUMB_H = self.THUMB_W, self.THUMB_H
        for i, img_url in enumerate(self.images):
            frame = tk.Frame(self.scrollable_frame, bg=self.bg_card, padx=8, pady=8)
            frame.grid(row=i//cols, column=i%cols, padx=18, pady=18, sticky="nsew")
            
            # Fixed-size image preview canvas
            img_frame = tk.Frame(frame, bg="#111", width=THUMB_W, height=THUMB_H)
            img_frame.pack()
            img_frame.pack_propagate(False)  # Don't shrink to content
            
            lbl = tk.Label(img_frame, text="⌛ Loading...", font=("Segoe UI", 10), fg="#666", bg="#111")
            lbl.place(relx=0.5, rely=0.5, anchor="center")  # Centered in fixed frame
            lbl.bind("<Button-1>", lambda e, idx=i: self._toggle_item(idx))
            lbl.bind("<Double-Button-1>", lambda e, url=img_url: self._open_preview(url))
            
            # Tooltip
            tk.Label(frame, text="Click=Select  |  Double-click=Full Preview", font=("Segoe UI", 8), fg="#555", bg=self.bg_card).pack(pady=4)
            
            # Info Row
            info_row = tk.Frame(frame, bg=self.bg_card)
            info_row.pack(fill="x", pady=4)
            
            cb = tk.Checkbutton(info_row, text=f"Image {i+1}", variable=self.selections[i], font=("Segoe UI", 11, "bold"), bg=self.bg_card, fg="white", selectcolor="#333", activebackground=self.bg_card)
            cb.pack(side="left")
            
            res_lbl = tk.Label(info_row, text="loading...", font=("Segoe UI", 10), fg=self.accent, bg=self.bg_card)
            res_lbl.pack(side="right")
            
            threading.Thread(target=self._load_async, args=(img_url, lbl, res_lbl, THUMB_W, THUMB_H), daemon=True).start()

        # Footer Actions
        footer = tk.Frame(self, bg="#121212", pady=25)
        footer.pack(fill="x")
        
        self.upscale_var = tk.BooleanVar(value=False)
        tk.Checkbutton(footer, text="Apply 4x AI Upscale (Real-ESRGAN)", variable=self.upscale_var, font=("Segoe UI", 11), bg="#121212", fg="#aaa", selectcolor="#333").pack(side="left", padx=40)
        
        btn = tk.Button(footer, text="⬇ DOWNLOAD SELECTED", font=("Segoe UI", 12, "bold"), bg=self.accent, fg="white", padx=40, pady=12, relief="flat", cursor="hand2", command=self._start_download)
        btn.pack(side="right", padx=40)

    def _toggle_all(self):
        val = self.sel_all_var.get()
        for v in self.selections:
            v.set(val)

    def _toggle_item(self, idx):
        self.selections[idx].set(not self.selections[idx].get())

    def _open_preview(self, url):
        """Open a full-size preview in a popup window."""
        win = tk.Toplevel(self)
        win.title("Full Size Preview")
        win.configure(bg="#000")
        loading_lbl = tk.Label(win, text="Loading full image...", bg="#000", fg="white", font=("Segoe UI", 12))
        loading_lbl.pack(expand=True, fill="both", padx=40, pady=40)
        
        def _load():
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                resp = requests.get(url, headers=headers, timeout=15)
                img = Image.open(io.BytesIO(resp.content))
                w, h = img.size
                
                # Scale to fit screen (max 90% of screen)
                screen_w = win.winfo_screenwidth()
                screen_h = win.winfo_screenheight()
                max_w, max_h = int(screen_w * 0.85), int(screen_h * 0.85)
                img.thumbnail((max_w, max_h), Image.LANCZOS)
                
                photo = ImageTk.PhotoImage(img)
                dw, dh = img.size
                
                def show():
                    loading_lbl.destroy()
                    win.geometry(f"{dw}x{dh}")
                    img_lbl = tk.Label(win, image=photo, bg="#000")
                    img_lbl.image = photo
                    img_lbl.pack()
                    win.title(f"Full Preview — {w}x{h} px (showing at {dw}x{dh})")
                win.after(0, show)
            except Exception as e:
                win.after(0, lambda: loading_lbl.config(text=f"Failed: {e}", fg="red"))
        
        threading.Thread(target=_load, daemon=True).start()

    def _load_async(self, url, lbl, res_lbl, thumb_w=500, thumb_h=350):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10, stream=True)
            if resp.status_code == 200:
                img_data = resp.raw.read()
                img = Image.open(io.BytesIO(img_data))
                w, h = img.size
                
                lbl.after(0, lambda: res_lbl.config(text=f"{w}x{h} px"))
                
                # Contain-fit into the fixed preview frame (letterbox)
                preview = Image.new("RGB", (thumb_w, thumb_h), (17, 17, 17))
                thumb = img.copy()
                thumb.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
                offset_x = (thumb_w - thumb.width) // 2
                offset_y = (thumb_h - thumb.height) // 2
                preview.paste(thumb, (offset_x, offset_y))
                
                photo = ImageTk.PhotoImage(preview)
                lbl.after(0, lambda: lbl.config(image=photo, text=""))
                lbl.image = photo
        except:
            lbl.after(0, lambda: lbl.config(text="❌ Failed to load"))

    def _start_download(self):
        selected = [self.images[i] for i, v in enumerate(self.selections) if v.get()]
        if not selected:
            messagebox.showwarning("Warning", "Please select at least one image!")
            return
        
        upscale = self.upscale_var.get()
        self.destroy()
        threading.Thread(target=self._download_batch, args=(selected, upscale), daemon=True).start()

    def _download_batch(self, urls, upscale):
        os.makedirs(self.save_dir, exist_ok=True)
        count = 0
        for i, url in enumerate(urls):
            try:
                resp = requests.get(url, timeout=20)
                if resp.status_code == 200:
                    ext = ".jpg"
                    if "webp" in url: ext = ".webp"
                    elif "png" in url: ext = ".png"
                    
                    fname = f"TikTok_Photo_{int(time.time())}_{i}{ext}"
                    out_p = os.path.join(self.save_dir, fname)
                    
                    with open(out_p, "wb") as f:
                        f.write(resp.content)
                    count += 1
                    
                    # Optional Upscale would go here
            except: pass
            
        if count > 0:
            if messagebox.askyesno("Success", f"Downloaded {count} images to:\n{self.save_dir}\n\nOpen folder?"):
                os.startfile(self.save_dir)

class TikTokFrameUpscalerTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.save_path    = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.status_var   = tk.StringVar(value="Ready ✓")
        self.progress_var = tk.DoubleVar(value=0)
        self.hour_var     = tk.StringVar(value="00")
        self.min_var      = tk.StringVar(value="00")
        self.sec_var      = tk.StringVar(value="00")
        self.upscale_var  = tk.StringVar(value="🔺 2x (Fast)")
        self.is_active    = False
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=16)
        header.pack(fill="x", padx=30)
        tf = tk.Frame(header, bg=BG)
        tf.pack()
        tk.Label(tf, text="♪", font=("Segoe UI Emoji", 24), fg=ACCENT2, bg=BG).pack(side="left")
        tk.Label(tf, text=" TikTok", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(tf, text="Frame Extractor", font=("Impact", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(header, text="Download Video -> Extract Frames -> AI Upscale to PNG", font=("Segoe UI", 10), fg=SUBTEXT, bg=BG).pack()
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)
        card = tk.Frame(self, bg=BG2, padx=24, pady=18)
        card.pack(fill="both", expand=True, padx=30, pady=14)
        tk.Label(card, text="🔗  TikTok URL", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        url_frame = tk.Frame(card, bg=BG3, pady=2)
        url_frame.pack(fill="x", pady=(4, 12))
        self.url_entry = tk.Entry(url_frame, font=("Consolas", 11), bg=BG3, fg=TEXT, insertbackground=ACCENT2, relief="flat", bd=8)
        self.url_entry.pack(fill="x", padx=4)
        self.u_cb = ttk.Combobox(card, textvariable=self.upscale_var, values=["🔺 2x (Fast)", "🔺🔺 4x (Pro)"], state="readonly", style="T.TCombobox")
        self.u_cb.pack(fill="x", pady=(4, 12))

        # Time Offset (New Feature)
        tk.Label(card, text="⏰  Start Time (HH:MM:SS)", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        t_row = tk.Frame(card, bg=BG2)
        t_row.pack(fill="x", pady=(4, 12))
        
        for var in [self.hour_var, self.min_var, self.sec_var]:
            e = tk.Entry(t_row, textvariable=var, font=("Consolas", 11), bg=BG3, fg=TEXT, width=4, relief="flat", justify="center")
            e.pack(side="left", padx=(0, 5))
            if var != self.sec_var:
                tk.Label(t_row, text=":", bg=BG2, fg=TEXT).pack(side="left", padx=(0, 5))
        tk.Label(card, text="📁  Save Frames To", font=("Segoe UI", 10, "bold"), fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        pf = tk.Frame(card, bg=BG3)
        pf.pack(fill="x", pady=(4, 12))
        tk.Label(pf, textvariable=self.save_path, font=("Consolas", 9), fg=TEXT, bg=BG3, anchor="w", padx=8, pady=5).pack(side="left", fill="both", expand=True)
        tk.Button(pf, text="Browse", font=("Segoe UI", 8), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", command=self._choose_folder).pack(side="right", padx=4)
        self.dl_btn = tk.Button(card, text="🚀   START FRAME EXTRACTION", font=("Impact", 14), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", pady=12, command=self._start)
        self.dl_btn.pack(fill="x", pady=(10, 0))
        
        self.cancel_btn = tk.Button(card, text="🚫  CANCEL PROCESS", font=("Segoe UI", 10, "bold"), bg="#444", fg=TEXT, relief="flat", cursor="hand2", pady=10, command=self._cancel)
        # Hidden by default
        sb = tk.Frame(self, bg=BG3, pady=6)
        sb.pack(fill="x", side="bottom")
        tk.Label(sb, textvariable=self.status_var, font=("Segoe UI", 9), bg=BG3, fg=SUBTEXT, padx=16).pack(side="left")
        p_frame = tk.Frame(self, bg=BG)
        p_frame.pack(fill="x", side="bottom")
        ttk.Progressbar(p_frame, variable=self.progress_var, maximum=100).pack(fill="x")

    def _choose_folder(self):
        f = filedialog.askdirectory(); 
        if f: self.save_path.set(f)

    def _start(self):
        if self.is_active: return
        url = self.url_entry.get().strip()
        if not url: return
        self.is_active = True
        self.dl_btn.config(text="⏳ WORKING...", state="disabled", bg="#444")
        self.is_cancelled = False
        self.current_proc = None
        self.cancel_btn.pack(fill="x", pady=(10, 0))
        threading.Thread(target=self._process, args=(url,), daemon=True).start()

    def _cancel(self):
        self.is_cancelled = True
        self.status_var.set("Cancelling...")
        if hasattr(self, 'current_proc') and self.current_proc:
            try:
                import psutil
                parent = psutil.Process(self.current_proc.pid)
                for child in parent.children(recursive=True): child.kill()
                parent.kill()
            except: pass
        self.cancel_btn.config(state="disabled", text="⌛ CANCELLING...")

    def _process(self, url):
        try:
            ytdlp, ffmpeg, realesrgan = find_tool("yt-dlp"), find_tool("ffmpeg"), find_tool("realesrgan-ncnn-vulkan")
            if not all([ytdlp, ffmpeg, realesrgan]): raise Exception("Tools missing")
            
            output_dir = os.path.join(self.save_path.get(), f"TikTok_Frames_{int(time.time())}")
            os.makedirs(output_dir, exist_ok=True)
            temp_vid = os.path.join(output_dir, "temp.mp4")
            temp_frames = os.path.join(output_dir, "temp_frames"); os.makedirs(temp_frames, exist_ok=True)

            self.after(0, lambda: self.status_var.set("⬇ Downloading video..."))
            si = None
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            subprocess.run([ytdlp, url, "--format", "bestvideo+bestaudio/best", "--merge-output-format", "mp4", "-o", temp_vid], startupinfo=si, check=True)
            
            # Find the actual downloaded file (yt-dlp might change extension)
            downloaded_files = glob.glob(os.path.join(output_dir, "temp.*"))
            if not downloaded_files: raise Exception("Download failed, no file found")
            actual_temp_vid = downloaded_files[0]

            # Construct Time Offset
            hh, mm, ss = self.hour_var.get().zfill(2), self.min_var.get().zfill(2), self.sec_var.get().zfill(2)
            time_offset = f"{hh}:{mm}:{ss}"

            self.after(0, lambda: self.status_var.set(f"🖼️ Extracting frames from {time_offset}..."))
            # Use -ss BEFORE -i for fast seeking
            subprocess.run([ffmpeg, "-y", "-ss", time_offset, "-i", actual_temp_vid, "-frames:v", "60", os.path.join(temp_frames, "frame%08d.png")], startupinfo=si, check=True)
            
            self.after(0, lambda: self.status_var.set("🔺 AI Upscaling frames..."))
            scale = 2 if "2x" in self.upscale_var.get() else 4
            
            # Universal Upscale Fallback
            if GLOBAL_HW["has_cuda"]:
                subprocess.run([realesrgan, "-i", temp_frames, "-o", output_dir, "-n", "realesr-animevideov3", "-s", str(scale)], 
                               cwd=os.path.dirname(os.path.abspath(realesrgan)), startupinfo=si, check=True)
            else:
                self.after(0, lambda: self.status_var.set("🔺 CPU Upscaling (Compatibility Mode)..."))
                # Use standard high-quality resize for machines without GPU
                # Iterating through temp_frames
                for f in os.listdir(temp_frames):
                    if self.is_cancelled: break
                    if f.endswith(".png"):
                        f_path = os.path.join(temp_frames, f)
                        with Image.open(f_path) as img:
                            w, h = img.size
                            res = img.resize((w*scale, h*scale), Image.Resampling.LANCZOS)
                            res.save(os.path.join(output_dir, f))
            
            if os.path.exists(actual_temp_vid): os.remove(actual_temp_vid)
            shutil.rmtree(temp_frames, ignore_errors=True)
            self.after(0, lambda: self.status_var.set("Done ✓"))
            os.startfile(output_dir)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.is_active = False
            self.after(0, lambda: self.dl_btn.config(text="🚀   START FRAME EXTRACTION", state="normal", bg=ACCENT))
            self.after(0, lambda: self.cancel_btn.pack_forget())

# --- AI Models: LaMa Inpainter ---
class LamaInpainter:
    MODEL_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
    
    device = torch.device("cuda" if HAS_TORCH and torch.cuda.is_available() else "cpu") if HAS_TORCH else None
    SAFE_LIMIT = 1024 # Max dimension for AI processing to avoid OOM
    
    def __init__(self, model_path):
        self.model_path = model_path
        self.model = None
        self.device = torch.device("cuda" if HAS_TORCH and torch.cuda.is_available() and GLOBAL_SETTINGS.get("prefer_gpu") else "cpu") if HAS_TORCH else None
        
        # --- NEW: Cache for Anime Turbo ---
        self.last_patch = None
        self.last_res = None
        self.last_dilation = -1
        self.last_blur = -1

    def is_ready(self):
        return os.path.exists(self.model_path)

    def load(self):
        if not self.model:
            # We use torch.jit.load because big-lama.pt is a TorchScript model
            self.model = torch.jit.load(self.model_path, map_location=self.device)
            self.model.eval()

    @torch.no_grad()
    def inpaint_batch(self, frame_list: list, mask: Image.Image, dilation_amt: int = 5, blur_amt: int = 3) -> list:
        if not frame_list: return []
        self.load()
        
        orig_w, orig_h = frame_list[0].size
        mask_l = mask.convert("L")
        bbox = mask_l.getbbox()
        if not bbox: return frame_list
        
        pad = 64
        x0, y0, x1, y1 = max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(orig_w, bbox[2]+pad), min(orig_h, bbox[3]+pad)
        
        # Prepare Batch
        import torchvision.transforms.functional as F
        import cv2
        import numpy as np
        
        # Static mask processing (same for all frames in batch)
        patch_mask = mask.crop((x0, y0, x1, y1))
        work_w, work_h = patch_mask.size
        
        # Scaling if still huge
        scale_limit = 1024
        scale_factor = 1.0
        if max(work_w, work_h) > scale_limit:
            scale_factor = scale_limit / float(max(work_w, work_h))
            work_w, work_h = int(work_w * scale_factor), int(work_h * scale_factor)
            patch_mask = patch_mask.resize((work_w, work_h), Image.Resampling.NEAREST)
            
        pad_w, pad_h = (8-work_w%8)%8, (8-work_h%8)%8
        input_msk = patch_mask.convert("L")
        msk_np = np.array(input_msk)
        if dilation_amt > 0:
            msk_np = cv2.dilate(msk_np, np.ones((dilation_amt, dilation_amt), np.uint8), iterations=1)
        if blur_amt > 0:
            msk_np = cv2.GaussianBlur(msk_np, (blur_amt*2+1, blur_amt*2+1), 0)
        
        # Final mask tensor
        input_msk_pil = Image.fromarray(msk_np)
        if pad_w > 0 or pad_h > 0:
            final_mask = Image.new("L", (work_w+pad_w, work_h+pad_h), 0)
            final_mask.paste(input_msk_pil, (0,0))
        else:
            final_mask = input_msk_pil
        mask_t = (F.to_tensor(final_mask) > 0).unsqueeze(0).to(self.device).float() # [1, 1, H, W]
        
        batch_imgs = []
        for img in frame_list:
            p_img = img.crop((x0, y0, x1, y1))
            if scale_factor < 1.0:
                p_img = p_img.resize((work_w, work_h), Image.Resampling.LANCZOS)
            
            p_img_rgb = p_img.convert("RGB")
            if pad_w > 0 or pad_h > 0:
                final_input = Image.new("RGB", (work_w+pad_w, work_h+pad_h), (0,0,0))
                final_input.paste(p_img_rgb, (0,0))
            else:
                final_input = p_img_rgb
            
            batch_imgs.append(F.to_tensor(final_input))
            
        # Stack to [B, 3, H, W]
        imgs_t = torch.stack(batch_imgs).to(self.device).float()
        masks_t = mask_t.repeat(len(frame_list), 1, 1, 1)
        
        # Inference
        res_t_batch = self.model(imgs_t, masks_t)
        
        # Postprocess results
        results = []
        for i in range(len(frame_list)):
            res_img = F.to_pil_image(res_t_batch[i].cpu().float())
            if pad_w > 0 or pad_h > 0:
                res_img = res_img.crop((0, 0, work_w, work_h))
            if scale_factor < 1.0:
                res_img = res_img.resize((x1-x0, y1-y0), Image.Resampling.LANCZOS)
            
            # Blending
            out_frame = frame_list[i].copy()
            final_patch = frame_list[i].crop((x0, y0, x1, y1)).copy()
            final_patch.paste(res_img, (0,0), input_msk_pil.resize(final_patch.size))
            out_frame.paste(final_patch, (x0, y0))
            results.append(out_frame)
            
        return results

    @torch.no_grad()
    def inpaint(self, image: Image.Image, mask: Image.Image, dilation_amt: int = 5, blur_amt: int = 3) -> Image.Image:
        res = self.inpaint_batch([image], mask, dilation_amt, blur_amt)
        return res[0] if res else image

# --- TAB 6: AI Object Remover ---
class AIObjectRemoverTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.source_path = tk.StringVar()
        self.status_var  = tk.StringVar(value="Ready ✓")
        self.brush_size  = tk.IntVar(value=15)
        self.use_pro_ai  = tk.BooleanVar(value=True)
        self.mask_dilation = tk.IntVar(value=5)
        self.mask_blur     = tk.IntVar(value=3)
        
        # Rendering Range
        self.start_h = tk.StringVar(value="00")
        self.start_m = tk.StringVar(value="00")
        self.start_s = tk.StringVar(value="00")
        self.end_h   = tk.StringVar(value="00")
        self.end_m   = tk.StringVar(value="00")
        self.end_s   = tk.StringVar(value="00")
        
        self.is_active   = False
        self.is_cancelled = False # New
        self.is_video_mode = False
        
        # Viewport State
        self.zoom_level  = 1.0
        self.offset_x    = 0
        self.offset_y    = 0
        self.pan_start_x = 0
        self.pan_start_y = 0
        
        self.model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "big-lama.pt")
        self.inpainter  = LamaInpainter(self.model_path)
        
        # Video Scrubbing State
        self.video_duration = 0.0
        self.video_fps      = 30.0
        self.time_var       = tk.DoubleVar(value=0.0)
        self.progress_var   = tk.DoubleVar(value=0.0)
        self._seek_job      = None # For debouncing
        
        # State for drawing
        self.tk_img     = None
        self.original_img = None
        self.mask_img   = None # PIL image as mask
        self.draw_mask  = None # Canvas drawer
        self.last_x, self.last_y = None, None
        
        self.draw_mode   = tk.StringVar(value="brush")
        self.crop_box    = None # (x1, y1, x2, y2) in image space
        self.crop_start  = None # (sx, sy) in canvas space
        
        # Keyboard Shortcuts
        self.bind_all("<b>", lambda e: self.draw_mode.set("brush"))
        self.bind_all("<e>", lambda e: self.draw_mode.set("eraser"))
        self.bind_all("<c>", lambda e: self.draw_mode.set("crop"))
        
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=20)
        header.pack(fill="x", padx=30)
        logo_f = tk.Frame(header, bg=BG)
        logo_f.pack()
        tk.Label(logo_f, text="🪄", font=("Segoe UI Emoji", 24), fg=SUCCESS, bg=BG).pack(side="left")
        tk.Label(logo_f, text=" AI Object", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_f, text=" Remover", font=("Impact", 24), fg=ACCENT, bg=BG).pack(side="left")
        
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)
        
        main_c = tk.Frame(self, bg=BG2, padx=20, pady=20)
        main_c.pack(fill="both", expand=True, padx=30, pady=20)

        # Controls (Top)
        ctrl = tk.Frame(main_c, bg=BG2)
        ctrl.pack(fill="x", pady=(0, 15))
        
        tk.Button(ctrl, text="📂 LOAD MEDIA", font=("Segoe UI", 9, "bold"), 
                  bg=ACCENT2, fg=BG, relief="flat", cursor="hand2", padx=15,
                  command=self._load_media).pack(side="left")
        
        tk.Label(ctrl, text="Brush Size:", bg=BG2, fg=SUBTEXT, font=("Segoe UI", 9)).pack(side="left", padx=(20, 5))
        tk.Scale(ctrl, variable=self.brush_size, from_=2, to=50, orient="horizontal", 
                 bg=BG2, fg=TEXT, highlightthickness=0, length=120).pack(side="left")
        
        # Mode Selection
        mode_f = tk.Frame(ctrl, bg=BG2)
        mode_f.pack(side="left", padx=15)
        tk.Radiobutton(mode_f, text="🖌️", variable=self.draw_mode, value="brush", bg=BG2, fg=TEXT, selectcolor=BG3, indicatoron=0, width=3, relief="flat", font=("Segoe UI", 10)).pack(side="left")
        tk.Radiobutton(mode_f, text="🧽", variable=self.draw_mode, value="eraser", bg=BG2, fg=TEXT, selectcolor=BG3, indicatoron=0, width=3, relief="flat", font=("Segoe UI", 10)).pack(side="left")
        tk.Radiobutton(mode_f, text="✂️", variable=self.draw_mode, value="crop", bg=BG2, fg=TEXT, selectcolor=BG3, indicatoron=0, width=3, relief="flat", font=("Segoe UI", 10)).pack(side="left")

        tk.Button(ctrl, text="🗑️ RESET CROP", font=("Segoe UI", 8), bg=BG3, fg=WARN, relief="flat", padx=10, command=self._reset_crop).pack(side="left", padx=5)

        
        tk.Checkbutton(ctrl, text="✨ USE PRO AI", variable=self.use_pro_ai, bg=BG2, fg=SUCCESS, font=("Segoe UI", 9, "bold"),
                       activebackground=BG2, activeforeground=SUCCESS, selectcolor=BG, relief="flat").pack(side="left", padx=15)

        tk.Button(ctrl, text="🧹 CLEAR MASK", font=("Segoe UI", 9), 
                  bg=BG3, fg=TEXT, relief="flat", cursor="hand2", padx=10,
                  command=self._clear_mask).pack(side="left")
        
        self.rem_btn = tk.Button(ctrl, text="✨ REMOVE & RESTORE", font=("Segoe UI", 9, "bold"), 
                  bg=SUCCESS, fg=BG, relief="flat", cursor="hand2", padx=20,
                  command=self._start_process)
        self.rem_btn.pack(side="right")
        
        self.cancel_btn = tk.Button(ctrl, text="🚫 CANCEL", font=("Segoe UI", 9, "bold"), 
                  bg="#444", fg=TEXT, relief="flat", cursor="hand2", padx=15,
                  command=self._cancel)
        # Hidden by default

        tk.Button(ctrl, text="🔘 BATCH FOLDER", font=("Segoe UI", 9, "bold"), 
                  bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", padx=15,
                  command=self._start_batch_process).pack(side="right", padx=10)
        
        tk.Button(ctrl, text="🔍 RESET VIEW", font=("Segoe UI", 9), 
                  bg=BG3, fg=TEXT, relief="flat", cursor="hand2", padx=10,
                  command=self._reset_view).pack(side="right", padx=10)

        # Controls Row 2: Pro Healing
        ctrl2 = tk.Frame(main_c, bg=BG2)
        ctrl2.pack(fill="x", pady=(0, 15))
        
        tk.Label(ctrl2, text="✨ HEAL STRENGTH (Dilation):", bg=BG2, fg=ACCENT2, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Scale(ctrl2, variable=self.mask_dilation, from_=0, to=20, orient="horizontal", 
                 bg=BG2, fg=TEXT, highlightthickness=0, length=150).pack(side="left", padx=(5, 20))
        
        tk.Label(ctrl2, text="🌈 EDGE SOFTNESS (Blur):", bg=BG2, fg=SUCCESS, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Scale(ctrl2, variable=self.mask_blur, from_=0, to=15, orient="horizontal", 
                 bg=BG2, fg=TEXT, highlightthickness=0, length=150).pack(side="left", padx=(5, 0))
        
        tk.Label(ctrl2, text="(Increase for cleaner logo removal)", bg=BG2, fg=SUBTEXT, font=("Segoe UI", 8)).pack(side="left", padx=15)

        # Controls Row 3: Render Range
        self.range_ctrl = tk.Frame(main_c, bg=BG2)
        # Packed only for videos
        
        tk.Label(self.range_ctrl, text="⏰ RENDER RANGE:", bg=BG2, fg=WARN, font=("Segoe UI", 9, "bold")).pack(side="left")
        
        # Start Time
        tk.Label(self.range_ctrl, text="  Start:", bg=BG2, fg=SUBTEXT).pack(side="left")
        for var in [self.start_h, self.start_m, self.start_s]:
            tk.Entry(self.range_ctrl, textvariable=var, width=3, bg=BG3, fg=TEXT, relief="flat", justify="center").pack(side="left", padx=2)
            if var != self.start_s: tk.Label(self.range_ctrl, text=":", bg=BG2, fg=SUBTEXT).pack(side="left")
        
        tk.Button(self.range_ctrl, text="SET", font=("Segoe UI", 7), bg=BG3, fg=ACCENT2, relief="flat", command=lambda: self._set_time_from_slider("start")).pack(side="left", padx=5)

        # End Time
        tk.Label(self.range_ctrl, text="   End:", bg=BG2, fg=SUBTEXT).pack(side="left")
        for var in [self.end_h, self.end_m, self.end_s]:
            tk.Entry(self.range_ctrl, textvariable=var, width=3, bg=BG3, fg=TEXT, relief="flat", justify="center").pack(side="left", padx=2)
            if var != self.end_s: tk.Label(self.range_ctrl, text=":", bg=BG2, fg=SUBTEXT).pack(side="left")
            
        tk.Button(self.range_ctrl, text="SET", font=("Segoe UI", 7), bg=BG3, fg=ACCENT2, relief="flat", command=lambda: self._set_time_from_slider("end")).pack(side="left", padx=5)
        
        tk.Label(self.range_ctrl, text="(Leave 00:00:00 for full video)", bg=BG2, fg=SUBTEXT, font=("Segoe UI", 8)).pack(side="left", padx=10)

        # Canvas Area
        self.canvas_container = tk.Frame(main_c, bg=BG3, bd=1, relief="flat")
        self.canvas_container.pack(fill="both", expand=True)
        
        self.canvas = tk.Canvas(self.canvas_container, bg=BG, highlightthickness=0, cursor="pencil")
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind("<B1-Motion>", self._draw)
        self.canvas.bind("<Button-1>", self._start_draw)
        self.canvas.bind("<ButtonRelease-1>", self._stop_draw)
        
        # Zoom & Pan Bindings
        self.canvas.bind("<MouseWheel>", self._on_zoom)
        self.canvas.bind("<Button-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)

        # Video Time Controls
        self.time_ctrl = tk.Frame(main_c, bg=BG2)
        # Hidden by default, packed when video loaded
        
        tk.Label(self.time_ctrl, text="🕒", font=("Segoe UI Emoji", 12), fg=ACCENT2, bg=BG2).pack(side="left", padx=(0, 10))
        
        self.time_slider = tk.Scale(self.time_ctrl, variable=self.time_var, from_=0, to=100, orient="horizontal",
                                   bg=BG2, fg=TEXT, highlightthickness=0, troughcolor=BG3, activebackground=ACCENT,
                                   showvalue=False, command=self._on_time_slide)
        self.time_slider.pack(side="left", fill="x", expand=True)
        
        self.time_lbl = tk.Label(self.time_ctrl, text="00:00 / 00:00", font=("Consolas", 10), fg=SUBTEXT, bg=BG2, width=15)
        self.time_lbl.pack(side="right", padx=(10, 0))

        # Status
        sb = tk.Frame(self, bg=BG3, pady=5)
        sb.pack(fill="x", side="bottom")
        
        # Premium Progress Bar
        self.pbar = ttk.Progressbar(sb, variable=self.progress_var, maximum=100, mode="determinate", length=200)
        self.pbar.pack(side="right", padx=20, pady=2)
        
        tk.Label(sb, textvariable=self.status_var, font=("Segoe UI", 9), bg=BG3, fg=SUBTEXT, padx=20).pack(side="left")

    def _load_media(self):
        path = filedialog.askopenfilename(filetypes=[("Media Files", "*.jpg *.jpeg *.png *.webp *.bmp *.mp4 *.mov *.avi *.mkv")])
        if not path: return
        self.source_path.set(path)
        
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.mp4', '.mov', '.avi', '.mkv']:
            self.is_video_mode = True
            ffmpeg = find_tool("ffmpeg")
            ffprobe = find_tool("ffprobe")
            if not ffmpeg:
                messagebox.showerror("Error", "ffmpeg is required to load videos")
                return
            
            # Get Video Info
            self.status_var.set("Analyzing video...")
            if ffprobe:
                try:
                    # Duration
                    p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], capture_output=True, text=True)
                    self.video_duration = float(p.stdout.strip()) if p.stdout.strip() else 0.0
                    
                    # FPS
                    p = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", path], capture_output=True, text=True)
                    fr = p.stdout.strip()
                    if "/" in fr:
                        n, d = map(float, fr.split("/"))
                        self.video_fps = n / d if d > 0 else 30.0
                    else:
                        self.video_fps = float(fr) if fr else 30.0
                except Exception as e:
                    print(f"Probe error: {e}")
                    self.video_duration = 0.0
            
            self.time_slider.config(to=self.video_duration)
            self.time_var.set(0.0)
            self.time_ctrl.pack(fill="x", pady=(10, 0), before=self.canvas_container)
            self.range_ctrl.pack(fill="x", pady=(0, 10), before=self.canvas_container)
            
            # Reset range inputs
            for v in [self.start_h, self.start_m, self.start_s, self.end_h, self.end_m, self.end_s]: v.set("00")
            
            self.status_var.set("Loading preview frame...")
            self._seek_to_time(0)
            self.status_var.set(f"Video Loaded ({self._format_time(self.video_duration)}). Scrub to select frame.")
        else:
            self.is_video_mode = False
            self.time_ctrl.pack_forget()
            self.range_ctrl.pack_forget()
            self.original_img = Image.open(path).convert("RGB")
            self.status_var.set("Image Loaded")
            # Resize to fit canvas
            cw, ch = 800, 500 # Max dims
            self.original_img.thumbnail((cw, ch), Image.Resampling.LANCZOS)
            
            # Create mask
            self.mask_img = Image.new("L", self.original_img.size, 0)
            self.draw_mask = ImageDraw.Draw(self.mask_img)
            self._show_on_canvas()

    def _format_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0: return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _set_time_from_slider(self, target):
        curr = self.time_var.get()
        h = int(curr // 3600)
        m = int((curr % 3600) // 60)
        s = int(curr % 60)
        if target == "start":
            self.start_h.set(f"{h:02d}"); self.start_m.set(f"{m:02d}"); self.start_s.set(f"{s:02d}")
        else:
            self.end_h.set(f"{h:02d}"); self.end_m.set(f"{m:02d}"); self.end_s.set(f"{s:02d}")

    def _on_time_slide(self, val):
        if not self.is_video_mode: return
        # Debounce seeking
        if self._seek_job: self.after_cancel(self._seek_job)
        self._seek_job = self.after(100, lambda: self._seek_to_time(float(val)))

    def _seek_to_time(self, seconds):
        if not self.is_video_mode: return
        path = self.source_path.get()
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg: return

        import tempfile
        import time as pytime
        temp_img = os.path.join(tempfile.gettempdir(), f"seek_{int(pytime.time()*1000)}.jpg")
        
        # Formatted timestamp for ffmpeg
        ts = f"{seconds:.3f}"
        
        si = None
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        try:
            # Quick seek to timestamp and extract 1 frame
            # Use -ss before -i for speed
            cmd = [ffmpeg, "-y", "-ss", ts, "-i", path, "-frames:v", "1", "-q:v", "2", temp_img]
            subprocess.run(cmd, capture_output=True, startupinfo=si)
            
            if os.path.exists(temp_img):
                self.original_img = Image.open(temp_img).convert("RGB")
                cw, ch = 800, 500
                self.original_img.thumbnail((cw, ch), Image.Resampling.LANCZOS)
                
                # Keep existing mask or reset? Usually mask stays.
                if not self.mask_img or self.mask_img.size != self.original_img.size:
                    self.mask_img = Image.new("L", self.original_img.size, 0)
                    self.draw_mask = ImageDraw.Draw(self.mask_img)
                
                self.time_lbl.config(text=f"{self._format_time(seconds)} / {self._format_time(self.video_duration)}")
                self._show_on_canvas()
                
                try: os.remove(temp_img)
                except: pass
        except Exception as e:
            print(f"Seek error: {e}")

    def _show_on_canvas(self):
        if not self.original_img: return
        
        # Calculate zoomed dimensions
        w, h = self.original_img.size
        zw, zh = int(w * self.zoom_level), int(h * self.zoom_level)
        
        # Update canvas size
        self.canvas.config(width=800, height=500) # Fixed viewport
        
        # Display image with offset
        display_img = self.original_img.resize((zw, zh), Image.Resampling.LANCZOS)
        
        # Create a "layered" image for the canvas to show the mask too
        mask_overlay = self.mask_img.resize((zw, zh), Image.Resampling.NEAREST)
        # Convert mask to colored overlay
        overlay = Image.new("RGBA", (zw, zh), (0,0,0,0))
        overlay_mask = Image.new("RGBA", (zw, zh), (255, 60, 60, 100)) # Transparent Red
        display_img_rgba = display_img.convert("RGBA")
        display_img_rgba.paste(overlay_mask, (0,0), mask_overlay)
        
        self.tk_img = ImageTk.PhotoImage(display_img_rgba)
        self.canvas.delete("all")
        self.canvas.create_image(self.offset_x, self.offset_y, image=self.tk_img, anchor="nw")
        
        # Redraw persistent crop overlay if it exists
        if self.crop_box:
            l, t, r, b = self.crop_box
            cl, ct = l * self.zoom_level + self.offset_x, t * self.zoom_level + self.offset_y
            cr, cb = r * self.zoom_level + self.offset_x, b * self.zoom_level + self.offset_y
            self.canvas.create_rectangle(cl, ct, cr, cb, outline="white", dash=(4, 4), tags="crop_overlay")

    def _on_zoom(self, e):
        # Current mouse pos on canvas
        mx, my = e.x, e.y
        
        # Calculate new zoom factor
        old_z = self.zoom_level
        factor = 1.2 if e.delta > 0 else 0.8
        self.zoom_level *= factor
        
        # Limit zoom
        self.zoom_level = max(0.5, min(10.0, self.zoom_level))
        new_z = self.zoom_level
        
        if old_z != new_z:
            # Adjust offsets so mouse stays over same image point
            # Formula: new_offset = mouse_pos - (mouse_pos - old_offset) * (new_zoom / old_zoom)
            self.offset_x = mx - (mx - self.offset_x) * (new_z / old_z)
            self.offset_y = my - (my - self.offset_y) * (new_z / old_z)
            self._show_on_canvas()

    def _on_pan_start(self, e):
        self.pan_start_x, self.pan_start_y = e.x, e.y

    def _on_pan_move(self, e):
        self.offset_x += (e.x - self.pan_start_x)
        self.offset_y += (e.y - self.pan_start_y)
        self.pan_start_x, self.pan_start_y = e.x, e.y
        self._show_on_canvas()

    def _reset_view(self):
        self.zoom_level = 1.0
        self.offset_x, self.offset_y = 0, 0
        self._show_on_canvas()

    def _start_draw(self, e):
        self.last_x, self.last_y = e.x, e.y
        r = self.brush_size.get()
        mode = self.draw_mode.get()
        
        if mode == "crop":
            self.canvas.delete("crop_overlay")
            self.crop_start = (e.x, e.y)
            return
            
        vr = r * self.zoom_level
        self.canvas.create_oval(e.x-vr, e.y-vr, e.x+vr, e.y+vr, fill="#FF3C3C", outline="#FF3C3C", tags="live_mask")
        
        def to_img_coord(sx, sy):
            return (sx - self.offset_x) / self.zoom_level, (sy - self.offset_y) / self.zoom_level
        
        ix, iy = to_img_coord(e.x, e.y)
        ir = r # Fixed: Mask is always image-space, use raw radius
        if self.draw_mask:
            val = 255 if self.draw_mode.get() == "brush" else 0
            self.draw_mask.ellipse([ix-ir, iy-ir, ix+ir, iy+ir], fill=val)

    def _draw(self, e):
        if not self.original_img: return
        mode = self.draw_mode.get()
        
        if mode == "crop":
            if self.crop_start:
                self.canvas.delete("crop_overlay")
                self.canvas.create_rectangle(self.crop_start[0], self.crop_start[1], e.x, e.y, outline="white", dash=(4, 4), tags="crop_overlay")
            return
            
        if not self.mask_img: return
        r = self.brush_size.get()
        
        # Logic: Update PIL mask coordinates
        def to_img_coord(sx, sy):
            return (sx - self.offset_x) / self.zoom_level, (sy - self.offset_y) / self.zoom_level

        x1, y1 = to_img_coord(self.last_x, self.last_y)
        x2, y2 = to_img_coord(e.x, e.y)
        ir = r
        
        val = 255 if mode == "brush" else 0
        self.draw_mask.line([x1, y1, x2, y2], fill=val, width=int(ir*2))
        self.draw_mask.ellipse([x2-ir, y2-ir, x2+ir, y2+ir], fill=val)
        
        # Feedback
        if mode == "brush":
            vr = r * self.zoom_level
            self.canvas.create_line(self.last_x, self.last_y, e.x, e.y, width=vr*2, fill="#FF3C3C", capstyle="round", smooth=True, tags="live_mask")
            self.canvas.create_oval(e.x-vr, e.y-vr, e.x+vr, e.y+vr, fill="#FF3C3C", outline="#FF3C3C", tags="live_mask")
        elif mode == "eraser":
            # Eraser refresh
            if not hasattr(self, "_erase_counter"): self._erase_counter = 0
            self._erase_counter += 1
            if self._erase_counter % 2 == 0:
                self._show_on_canvas()
            
        self.last_x, self.last_y = e.x, e.y

    def _stop_draw(self, e):
        if self.draw_mode.get() == "crop" and self.crop_start:
            def to_img_coord(sx, sy):
                return (sx - self.offset_x) / self.zoom_level, (sy - self.offset_y) / self.zoom_level
            
            x1, y1 = to_img_coord(self.crop_start[0], self.crop_start[1])
            x2, y2 = to_img_coord(e.x, e.y)
            
            # Bound and sort
            w, h = self.original_img.size
            l, t = max(0, min(x1, x2)), max(0, min(y1, y2))
            r, b = min(w, max(x1, x2)), min(h, max(y1, y2))
            
            if r - l > 5 and b - t > 5:
                # Force even dimensions for encoder compatibility (Broken Pipe fix)
                cl, ct, cr, cb = int(l), int(t), int(r), int(b)
                if (cr - cl) % 2 != 0: cr -= 1
                if (cb - ct) % 2 != 0: cb -= 1
                self.crop_box = (cl, ct, cr, cb)
                
                # Clear mask as resolution will change
                self._clear_mask()
                self.status_var.set(f"Crop area set: {cr-cl}x{cb-ct} (Auto-snapped to even)")
            
            self.crop_start = None
            
        self.last_x, self.last_y = None, None
        self._show_on_canvas()

    def _reset_crop(self):
        self.crop_box = None
        self.canvas.delete("crop_overlay")
        self.status_var.set("Crop cleared.")
        self._show_on_canvas()

    def _clear_mask(self):
        self.canvas.delete("live_mask")
        if self.mask_img:
            self.mask_img = Image.new("L", self.original_img.size, 0)
            self.draw_mask = ImageDraw.Draw(self.mask_img)
        self._show_on_canvas()

    def _start_process(self):
        if self.is_active or not self.original_img: return
        
        if getattr(self, "is_video_mode", False):
            msg = ("You are about to run Object Removal on a Video.\n\n"
                   "The mask you drew will be applied identically to every single frame. This is ideal for static watermarks/logos.\n"
                   "Do you wish to proceed? Note: This process is heavy and may take time.")
            if not messagebox.askyesno("Video Mode Warning", msg):
                return
                
        self.is_active = True
        self.is_cancelled = False
        self.rem_btn.config(state="disabled", text="⌛ PROCESSING...")
        self.cancel_btn.pack(side="right", padx=10)
        
        if getattr(self, "is_video_mode", False):
            threading.Thread(target=self._process_video, daemon=True).start()
        else:
            threading.Thread(target=self._process, daemon=True).start()

    def _cancel(self):
        self.is_cancelled = True
        self.status_var.set("Cancelling...")
        self.cancel_btn.config(state="disabled", text="⌛ CANCELLING...")

    def _process(self):
        try:
            import cv2
            import numpy as np
            
            # 1. Check/Download Model if Pro AI
            if self.use_pro_ai.get():
                if not self.inpainter.is_ready():
                    self._download_weights()
            
            self.after(0, lambda: self.status_var.set("AI Healing in progress..."))
            
            if self.use_pro_ai.get() and self.inpainter.is_ready():
                # PRO MODE (LaMa)
                result = self.inpainter.inpaint(self.original_img, self.mask_img, 
                                               dilation_amt=self.mask_dilation.get(),
                                               blur_amt=self.mask_blur.get())
                self.original_img = result
            else:
                # BASIC MODE (OpenCV)
                img_cv = cv2.cvtColor(np.array(self.original_img), cv2.COLOR_RGB2BGR)
                mask_cv = np.array(self.mask_img)
                res = cv2.inpaint(img_cv, mask_cv, 3, cv2.INPAINT_TELEA)
                res_rgb = cv2.cvtColor(res, cv2.COLOR_BGR2RGB)
                self.original_img = Image.fromarray(res_rgb)
            
            if self.crop_box:
                self.original_img = self.original_img.crop(self.crop_box)
                
            self.after(0, self._show_on_canvas)
            self.after(0, self._clear_mask)
            self.after(0, lambda: self.status_var.set("Done ✓"))
            
            save_p = filedialog.asksaveasfilename(defaultextension=".png", initialfile="restored_image.png")
            if save_p:
                self.original_img.save(save_p)
                os.startfile(os.path.dirname(save_p))
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror("AI Error", f"Restoration failed: {err}"))
        finally:
            self.is_active = False
            self.after(0, lambda: self.rem_btn.config(state="normal", text="✨ REMOVE & RESTORE"))
            self.after(0, lambda: self.cancel_btn.pack_forget())

    def _process_video(self):
        try:
            import cv2
            import numpy as np
            import tempfile
            from PIL import Image
            import json
            
            ffmpeg = find_tool("ffmpeg")
            ffprobe = find_tool("ffprobe")
            if not ffmpeg: raise Exception("ffmpeg not found")
            
            input_path = self.source_path.get()
            
            # --- Handle Time Range ---
            def get_sec(h, m, s):
                try: return int(h.get())*3600 + int(m.get())*60 + int(s.get())
                except: return 0
            
            start_sec = get_sec(self.start_h, self.start_m, self.start_s)
            end_sec = get_sec(self.end_h, self.end_m, self.end_s)
            
            # 1. Detect Resolution & FPS
            self.after(0, lambda: self.status_var.set("Analyzing video stream..."))
            width, height = 1920, 1080
            fps = 30.0
            if ffprobe:
                try:
                    p = subprocess.run([ffprobe, "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", input_path], capture_output=True, text=True)
                    data = json.loads(p.stdout)
                    width = data['streams'][0]['width']
                    height = data['streams'][0]['height']
                    fps_raw = data['streams'][0]['r_frame_rate']
                    if "/" in fps_raw:
                        num, den = map(float, fps_raw.split("/"))
                        fps = num / den if den > 0 else 30.0
                    else: fps = float(fps_raw)
                except: pass
            
            # 1.1 Override with crop if set
            if self.crop_box:
                l, t, r, b = self.crop_box
                width = r - l
                height = b - t
                # Safety snap
                if width % 2 != 0: width -= 1
                if height % 2 != 0: height -= 1
            
            if end_sec <= 0:
                end_sec = self.video_duration
            proc_duration = end_sec - start_sec
            if proc_duration <= 0: raise Exception("Invalid time range")
            
            total_frames = int(proc_duration * fps)
            
            # 2. Setup FFmpeg Pipes (Pro Stream)
            self.after(0, lambda: self.status_var.set("Opening Pro Stream..."))
            
            # Input Pipe
            incmd = [ffmpeg, "-ss", str(start_sec), "-to", str(end_sec), "-i", input_path]
            if self.crop_box:
                l, t, r, b = self.crop_box
                incmd += ["-vf", f"crop={r-l}:{b-t}:{l}:{t}"]
            incmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
            reader = subprocess.Popen(incmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            
            # Hardware Acceleration Settings
            v_codec = "libx264"
            v_params = ["-crf", "18", "-preset", "fast"]
            if GLOBAL_HW.get("has_cuda"):
                try:
                    chk = subprocess.run([ffmpeg, "-encoders"], capture_output=True, text=True)
                    if "h264_nvenc" in chk.stdout:
                        v_codec = "h264_nvenc"
                        v_params = ["-preset", "p4", "-tune", "hq", "-cq", "18"]
                except: pass
            
            output_tmp = tempfile.mktemp(suffix="_pro.mp4")
            outcmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-c:v", v_codec] + v_params + ["-pix_fmt", "yuv420p", output_tmp]
            writer = subprocess.Popen(outcmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            
            # 3. Batch Processing Loop
            batch_size = GLOBAL_SETTINGS.get("batch_size") # Dynamic from Settings VRAM and speed
            frame_bytes = width * height * 3
            
            processed_count = 0
            self.after(0, lambda: self.status_var.set("AI Stream Engine Running..."))
            
            while True:
                if self.is_cancelled: break
                
                # Read Batch
                batch_frames = []
                for _ in range(batch_size):
                    raw = reader.stdout.read(frame_bytes)
                    if not raw: break
                    img_np = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
                    batch_frames.append(Image.fromarray(img_np))
                
                if not batch_frames: break
                
                # AI Batch Inpaint
                if self.use_pro_ai.get() and self.inpainter.is_ready():
                    # FIX: Resize mask to match frame resolution
                    scaled_mask = self.mask_img.resize((width, height), Image.Resampling.NEAREST)
                    results = self.inpainter.inpaint_batch(batch_frames, scaled_mask, 
                                                         dilation_amt=self.mask_dilation.get(),
                                                         blur_amt=self.mask_blur.get())
                else:
                    # Basic mode fallback (in-memory)
                    results = []
                    for img in batch_frames:
                        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                        # FIX: Resize mask to match frame resolution
                        scaled_mask = self.mask_img.resize(img.size, Image.Resampling.NEAREST)
                        mask_cv = np.array(scaled_mask)
                        res_cv = cv2.inpaint(img_cv, mask_cv, 3, cv2.INPAINT_TELEA)
                        results.append(Image.fromarray(cv2.cvtColor(res_cv, cv2.COLOR_BGR2RGB)))
                
                # Write Batch to Encoder
                for res in results:
                    try:
                        if writer.poll() is None:
                            writer.stdin.write(np.array(res).tobytes())
                        else:
                            raise Exception("FFmpeg writer process terminated unexpectedly")
                    except (OSError, BrokenPipeError) as e:
                        raise Exception(f"Pipe error during video encoding: {e}")
                
                processed_count += len(batch_frames)
                prog = min(100, (processed_count / total_frames) * 100)
                if processed_count % (batch_size * 5) == 0:
                    self.after(0, lambda p=prog, c=processed_count, t=total_frames: self.status_var.set(f"Streaming: {c}/{t} frames ({p:.1f}%)"))
                    self.after(0, lambda p=prog: self.progress_var.set(p))
            
            # 4. Finalize
            reader.terminate()
            if writer.stdin: writer.stdin.close()
            writer.wait()
            
            if self.is_cancelled: return
            
            save_p = filedialog.asksaveasfilename(defaultextension=".mp4", initialfile="restored_video.mp4", filetypes=[("MP4 Video", "*.mp4")])
            if not save_p: return
            
            self.after(0, lambda: self.status_var.set("Restoring audio track..."))
            audio_tmp = tempfile.mktemp(suffix=".aac")
            subprocess.run([ffmpeg, "-y", "-ss", str(start_sec), "-to", str(end_sec), "-i", input_path, "-vn", "-acodec", "copy", audio_tmp], capture_output=True)
            subprocess.run([ffmpeg, "-y", "-i", output_tmp, "-i", audio_tmp, "-map", "0:v", "-map", "1:a?", "-c", "copy", "-shortest", save_p], capture_output=True)
            
            self.after(0, lambda: self.status_var.set("Pro Video Finished ✓"))
            os.startfile(os.path.dirname(save_p))
            
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror("Pro Stream Error", f"Workflow failed: {err}"))
        finally:
            self.is_active = False
            self.after(0, lambda: self.rem_btn.config(state="normal", text="✨ REMOVE & RESTORE"))
            self.after(0, lambda: self.cancel_btn.pack_forget())
            # Cleanup temp files
            try:
                if 'output_tmp' in locals() and os.path.exists(output_tmp): os.remove(output_tmp)
                if 'audio_tmp' in locals() and os.path.exists(audio_tmp): os.remove(audio_tmp)
            except: pass

    def _start_batch_process(self):
        if self.is_active: return
        if not self.original_img:
            messagebox.showwarning("No Image Loaded", "Please load an image and draw a mask first to use as a template for the whole folder.")
            return
            
        # UX Confirmation Message
        msg = ("This feature will apply the CURRENT mask to ALL images in a folder.\n\n"
               "⚠️ IMPORTANT: This works best for subtitles or objects that stay in the EXACT SAME POSITION across all frames.\n\n"
               "Do you want to proceed and select the folder?")
        if not messagebox.askyesno("Batch Confirmation", msg):
            return
            
        target_dir = filedialog.askdirectory(title="Select Folder to Batch Process")
        if not target_dir: return
        
        self.is_active = True
        self.is_cancelled = False
        self.cancel_btn.pack(side="right", padx=10)
        threading.Thread(target=self._batch_process, args=(target_dir,), daemon=True).start()

    def _batch_process(self, input_dir):
        try:
            import cv2
            import numpy as np
            
            # 1. Weights Check
            if self.use_pro_ai.get() and not self.inpainter.is_ready():
                self._download_weights()
            
            valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
            files = [f for f in os.listdir(input_dir) if f.lower().endswith(valid_exts)]
            if not files:
                self.after(0, lambda: messagebox.showwarning("No Images", "No images found in the selected folder."))
                return

            out_dir = os.path.join(input_dir, "restored_batch")
            os.makedirs(out_dir, exist_ok=True)
            
            total = len(files)
            for i, f_name in enumerate(files):
                if self.is_cancelled: break
                self.after(0, lambda i=i, t=total: self.status_var.set(f"Batch Processing {i+1}/{t}..."))
                
                f_path = os.path.join(input_dir, f_name)
                img = Image.open(f_path).convert("RGB")
                
                # Make sure mask matches image size (Batch requires consistent resolution)
                mask = self.mask_img.resize(img.size, Image.Resampling.NEAREST)
                
                if self.use_pro_ai.get() and self.inpainter.is_ready():
                    res_img = self.inpainter.inpaint(img, mask)
                else:
                    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    mask_cv = np.array(mask)
                    res_cv = cv2.inpaint(img_cv, mask_cv, 3, cv2.INPAINT_TELEA)
                    res_img = Image.fromarray(cv2.cvtColor(res_cv, cv2.COLOR_BGR2RGB))
                
                # Apply crop to result if set
                if self.crop_box:
                    res_img = res_img.crop(self.crop_box)
                    
                res_img.save(os.path.join(out_dir, f_name))

            self.after(0, lambda: self.status_var.set(f"Batch Done ✓ {total} images saved to 'restored_batch'"))
            os.startfile(out_dir)
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror("Batch Error", f"Process failed: {err}"))
        finally:
            self.is_active = False
            self.after(0, lambda: self.status_var.set("Ready ✓"))
            self.after(0, lambda: self.cancel_btn.pack_forget())

    def _download_weights(self):
        import urllib.request
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        
        def reporthook(blocknum, blocksize, totalsize):
            if totalsize > 0:
                pct = (blocknum * blocksize / totalsize) * 100
                self.after(0, lambda: self.status_var.set(f"Downloading AI Weights: {pct:.1f}%"))
        
        self.after(0, lambda: self.status_var.set("Connecting to AI server..."))
        urllib.request.urlretrieve(self.inpainter.MODEL_URL, self.model_path, reporthook)

# --- Globals and Utilities ---

REALESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"

BG      = "#0d0d0f"
BG2     = "#16161a"
BG3     = "#1e1e24"
ACCENT  = "#fe2c55"
ACCENT2 = "#25f4ee"
TEXT    = "#ffffff"
SUBTEXT = "#8a8a9a"
SUCCESS = "#2dde98"
WARN    = "#ffbe0b"

QUALITY_OPTIONS = {
    "Auto (Best Available)": None,
    "Ultra HD (4K)":          2160,
    "QHD (1440p)":            1440,
    "Full HD (1080p)":        1080,
    "HD (720p)":              720,
    "SD (480p)":              480,
    "🎵 Audio Only (MP3)":   "audio",
}

UPSCALE_OPTIONS = {
    "❌ No Upscale":         None,
    "🔺 2x (Fast)":           2,
    "🔺🔺 4x (Ultra HD)":    4,
}

QUALITY_INFO = {
    "Auto (Best Available)": "🌟 Automatically choose the highest available quality (supports 4K)",
    "Ultra HD (4K)":          "🖥️ Highest resolution 2160p",
    "QHD (1440p)":            "🖥️ High resolution 1440p",
    "Full HD (1080p)":        "📺 Standard 1080p Full HD",
    "HD (720p)":              "💻 720p - Saves space",
    "SD (480p)":              "📱 480p - Mobile quality",
    "🎵 Audio Only (MP3)":   "🎵 High quality 320kbps MP3",
}

def build_format_chain(max_h, no_wm):
    chains = []
    if no_wm:
        chains += ["download_addr-0", "download_addr"]
    if max_h:
        chains += [
            f"bestvideo[height<={max_h}][ext=mp4]+bestaudio[ext=m4a]",
            f"bestvideo[height<={max_h}]+bestaudio",
            f"best[height<={max_h}]",
        ]
    chains += ["bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio", "best[ext=mp4]", "best"]
    return "/".join(chains)

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def find_tool(name):
    """Search for tool in sys._MEIPASS/bin, PATH, C:\Tools, and {app}\bin"""
    # 1. Check bundled folder (PyInstaller)
    bundled_bin = get_resource_path("bin")
    if os.path.exists(bundled_bin):
        for root, dirs, files in os.walk(bundled_bin):
            if f"{name}.exe" in files:
                return os.path.join(root, f"{name}.exe")
            if name in files:
                return os.path.join(root, name)

    # 2. Check PATH
    path = shutil.which(name)
    if path: return path
    
    # 3. Check common custom locations
    search_dirs = [
        "C:\\Tools",
        os.path.join(os.path.dirname(sys.executable), "bin"),
        os.path.abspath("bin"),
        os.path.join(os.path.expanduser("~"), "Downloads")
    ]
    
    for d in search_dirs:
        if not os.path.exists(d): continue
        for root, dirs, files in os.walk(d):
            if f"{name}.exe" in files:
                return os.path.join(root, f"{name}.exe")
            if name in files:
                return os.path.join(root, name)
    return None

def check_ffmpeg():
    return find_tool("ffmpeg") is not None

def check_realesrgan():
    """ตรวจสอบว่ามี realesrgan-ncnn-vulkan.exe"""
    exe = find_tool("realesrgan-ncnn-vulkan")
    if exe:
        models_dir = os.path.join(os.path.dirname(exe), "models")
        return os.path.isdir(models_dir)
    return False

def check_ytdlp():
    """ตรวจสอบว่ามี yt-dlp (exe หรือ path)"""
    return find_tool("yt-dlp") is not None

def upscale_video(input_path, scale, status_cb):
    """Upscale วิดีโอด้วย Real-ESRGAN + ffmpeg"""
    base, ext = os.path.splitext(input_path)
    frames_dir   = base + "_frames"
    upscaled_dir = base + "_upscaled"
    output_path  = base + f"_x{scale}K.mp4"
    audio_path   = base + "_audio.aac"

    # Helper to get FPS robustly
    def get_fps(path):
        ffprobe = find_tool("ffprobe") or "ffprobe"
        try:
            res = subprocess.run(
                [ffprobe, "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=r_frame_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1", os.path.normpath(path)],
                capture_output=True, text=True, check=True)
            fps_raw = res.stdout.strip()
            if "/" in fps_raw:
                num, den = map(float, fps_raw.split("/"))
                return str(num / den) if den > 0 else "30"
            return fps_raw if fps_raw else "30"
        except:
            return "30"

    ffmpeg = find_tool("ffmpeg")
    if not ffmpeg: raise FileNotFoundError("ไม่พบ ffmpeg.exe")

    try:
        fps = get_fps(input_path)

        # 1. แยก audio
        status_cb("🎵 กำลังแยกเสียง...", WARN)
        subprocess.run([
            ffmpeg, "-y", "-i", os.path.normpath(input_path),
            "-vn", "-acodec", "copy", os.path.normpath(audio_path)
        ], check=True, capture_output=True)

        # 2. แยก frames (Force Constant Frame Rate)
        status_cb(f"🖼️ กำลังแยก frames ({fps} FPS)...", WARN)
        subprocess.run([
            ffmpeg, "-y", "-i", os.path.normpath(input_path),
            "-vf", f"fps={fps}",
            os.path.normpath(os.path.join(frames_dir, "frame%08d.png"))
        ], check=True, capture_output=True)

        # 3. Real-ESRGAN upscale frames
        status_cb(f"🔺 กำลัง upscale {scale}x...", ACCENT2)
        exe = find_tool("realesrgan-ncnn-vulkan")
        
        if GLOBAL_HW["has_cuda"] and exe:
            subprocess.run([
                exe,
                "-i", os.path.normpath(frames_dir),
                "-o", os.path.normpath(upscaled_dir),
                "-n", "realesr-animevideov3",
                "-s", str(scale),
                "-f", "png"
            ], check=True, cwd=os.path.dirname(os.path.abspath(exe)))
        else:
            status_cb(f"🔺 CPU Upscaling (Compatibility Mode)...", WARN)
            for f in os.listdir(frames_dir):
                if f.endswith(".png"):
                    f_path = os.path.join(frames_dir, f)
                    with Image.open(f_path) as img:
                        w, h = img.size
                        res = img.resize((w*scale, h*scale), Image.Resampling.LANCZOS)
                        res.save(os.path.join(upscaled_dir, f))

        # 4. รวม frames + audio กลับเป็นวิดีโอ
        status_cb("🎬 กำลังรวมวิดีโอ...", WARN)
        subprocess.run([
            ffmpeg, "-y",
            "-framerate", fps,
            "-i", os.path.normpath(os.path.join(upscaled_dir, "frame%08d.png")),
            "-i", os.path.normpath(audio_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            "-preset", "slow",
            "-c:a", "aac",
            "-shortest",
            os.path.normpath(output_path)
        ], check=True, capture_output=True)

        return output_path

    finally:
        # Cleanup temp folders
        shutil.rmtree(frames_dir,   ignore_errors=True)
        shutil.rmtree(upscaled_dir, ignore_errors=True)
        if os.path.exists(audio_path):
            os.remove(audio_path)


class SettingsTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.gpu_var = tk.BooleanVar(value=GLOBAL_SETTINGS.get("prefer_gpu"))
        self.batch_var = tk.IntVar(value=GLOBAL_SETTINGS.get("batch_size"))
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=20)
        header.pack(fill="x", padx=30)
        logo_f = tk.Frame(header, bg=BG)
        logo_f.pack()
        tk.Label(logo_f, text="⚙️", font=("Segoe UI Emoji", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(logo_f, text=" System", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_f, text=" Settings", font=("Impact", 24), fg=ACCENT2, bg=BG).pack(side="left")
        
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)
        
        main_c = tk.Frame(self, bg=BG2, padx=40, pady=30)
        main_c.pack(fill="both", expand=True, padx=30, pady=20)

        # Hardware Section
        section1 = tk.LabelFrame(main_c, text=" HARDWARE ACCELERATION ", font=("Segoe UI", 10, "bold"), bg=BG2, fg=ACCENT2, padx=20, pady=20)
        section1.pack(fill="x", pady=(0, 20))
        
        tk.Label(section1, text="Detected GPU:", bg=BG2, fg=SUBTEXT).grid(row=0, column=0, sticky="w")
        tk.Label(section1, text=f"{GLOBAL_HW['gpu_name']}", bg=BG2, fg=TEXT, font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=10)
        
        gpu_cb = tk.Checkbutton(section1, text="Use NVIDIA GPU (CUDA) for AI Processing", variable=self.gpu_var, 
                                bg=BG2, fg=SUCCESS, font=("Segoe UI", 10, "bold"), activebackground=BG2, activeforeground=SUCCESS,
                                command=self._on_change)
        gpu_cb.grid(row=1, column=0, columnspan=2, sticky="w", pady=(15, 5))
        tk.Label(section1, text="Disabling this will force all AI tasks to run on the CPU (Much Slower).", bg=BG2, fg=SUBTEXT, font=("Segoe UI", 8)).grid(row=2, column=0, columnspan=2, sticky="w")

        # Performance Section
        section2 = tk.LabelFrame(main_c, text=" VIDEO PERFORMANCE (PRO STREAM) ", font=("Segoe UI", 10, "bold"), bg=BG2, fg=SUCCESS, padx=20, pady=20)
        section2.pack(fill="x")
        
        tk.Label(section2, text="Batch Size (Concurrent Frames):", bg=BG2, fg=SUBTEXT).pack(side="left")
        for val in [1, 2, 4, 8]:
            tk.Radiobutton(section2, text=str(val), variable=self.batch_var, value=val, bg=BG2, fg=TEXT, 
                           selectcolor=BG3, activebackground=BG2, command=self._on_change).pack(side="left", padx=10)
        
        tk.Label(main_c, text="* Settings are saved automatically.", font=("Segoe UI", 8, "italic"), bg=BG2, fg=SUBTEXT).pack(pady=20)

        # NEW: Troubleshooting Section
        section3 = tk.LabelFrame(main_c, text=" TROUBLESHOOTING & REPAIR ", font=("Segoe UI", 10, "bold"), bg=BG2, fg=WARN, padx=20, pady=20)
        section3.pack(fill="x", pady=(0, 20))
        
        tk.Label(section3, text="Fix missing AI libraries, redownload core dependencies, and rebuild the application CLI/Python environment.", bg=BG2, fg=SUBTEXT, font=("Segoe UI", 9)).pack(side="left")
        
        tk.Button(section3, text="🔧 Run System Repair", font=("Segoe UI", 9, "bold"), bg=WARN, fg=BG, relief="flat", cursor="hand2", activebackground=ACCENT, padx=15, pady=5, command=lambda: self.winfo_toplevel()._run_system_repair()).pack(side="right", padx=10)
        
        tk.Button(section3, text="📜 Create Local Cert", font=("Segoe UI", 9, "bold"), bg=ACCENT2, fg=BG, relief="flat", cursor="hand2", activebackground=ACCENT, padx=15, pady=5, command=lambda: self.winfo_toplevel()._create_local_certificate()).pack(side="right", padx=10)

    def _on_change(self):
        GLOBAL_SETTINGS.set("prefer_gpu", self.gpu_var.get())
        GLOBAL_SETTINGS.set("batch_size", self.batch_var.get())
        messagebox.showinfo("Settings Saved", "Hardware settings updated. Please restart the AI process for changes to take effect.")

class VideoDrawTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.source_path = tk.StringVar()
        self.status_var  = tk.StringVar(value="Ready ✓")
        self.brush_size  = tk.IntVar(value=5)
        self.draw_color  = tk.StringVar(value="#fe2c55")
        
        # Rendering Range (H:M:S)
        self.start_h = tk.StringVar(value="00")
        self.start_m = tk.StringVar(value="00")
        self.start_s = tk.StringVar(value="00")
        self.end_h   = tk.StringVar(value="00")
        self.end_m   = tk.StringVar(value="00")
        self.end_s   = tk.StringVar(value="00")
        
        self.draw_mode   = tk.StringVar(value="brush")
        # Keyboard Shortcuts
        self.bind_all("<b>", lambda e: self.draw_mode.set("brush"))
        self.bind_all("<e>", lambda e: self.draw_mode.set("eraser"))
        self.bind_all("<r>", lambda e: self._start_render())
        
        self.drawings    = [] # List of dicts
        self.is_active   = False
        self.is_cancelled = False
        
        # Viewport State (Same as Object Remover)
        self.zoom_level  = 1.0
        self.offset_x    = 0
        self.offset_y    = 0
        self.pan_start_x = 0
        self.pan_start_y = 0
        
        self.video_duration = 0.0
        self.time_var       = tk.DoubleVar(value=0.0)
        self._seek_job      = None
        self.tk_img         = None
        self.original_img   = None
        self.last_x, self.last_y = None, None
        self.current_stroke = []
        
        self.progress_var = tk.DoubleVar(value=0.0)
        self.real_w = 1920
        self.real_h = 1080
        
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG, pady=20)
        header.pack(fill="x", padx=30)
        logo_f = tk.Frame(header, bg=BG)
        logo_f.pack()
        tk.Label(logo_f, text="🎨", font=("Segoe UI Emoji", 24), fg=ACCENT2, bg=BG).pack(side="left")
        tk.Label(logo_f, text=" Video", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_f, text=" Drawer", font=("Impact", 24), fg=SUCCESS, bg=BG).pack(side="left")
        
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)
        
        main_c = tk.Frame(self, bg=BG2, padx=20, pady=20)
        main_c.pack(fill="both", expand=True, padx=30, pady=20)

        # Controls
        ctrl = tk.Frame(main_c, bg=BG2)
        ctrl.pack(fill="x", pady=(0, 15))
        
        tk.Button(ctrl, text="📂 LOAD MEDIA", font=("Segoe UI", 9, "bold"), 
                  bg=ACCENT2, fg=BG, relief="flat", cursor="hand2", padx=15,
                  command=self._load_media).pack(side="left")
        
        # Color Palette
        cp = tk.Frame(ctrl, bg=BG2)
        cp.pack(side="left", padx=20)
        colors = ["#fe2c55", "#25f4ee", "#2dde98", "#ffbe0b", "#ffffff", "#000000"]
        for c in colors:
            btn = tk.Button(cp, bg=c, width=2, height=1, relief="flat", cursor="hand2", 
                            command=lambda col=c: self.draw_color.set(col))
            btn.pack(side="left", padx=2)
            
        # Tool Mode Selection
        mode_f = tk.Frame(ctrl, bg=BG2)
        mode_f.pack(side="left", padx=15)
        tk.Radiobutton(mode_f, text="🖌️", variable=self.draw_mode, value="brush", bg=BG2, fg=TEXT, selectcolor=BG3, indicatoron=0, width=3, relief="flat", font=("Segoe UI", 10)).pack(side="left")
        tk.Radiobutton(mode_f, text="🧽", variable=self.draw_mode, value="eraser", bg=BG2, fg=TEXT, selectcolor=BG3, indicatoron=0, width=3, relief="flat", font=("Segoe UI", 10)).pack(side="left")
        
        tk.Label(ctrl, text="Size:", bg=BG2, fg=SUBTEXT).pack(side="left", padx=(10, 5))
        tk.Scale(ctrl, variable=self.brush_size, from_=1, to=30, orient="horizontal", 
                 bg=BG2, fg=TEXT, highlightthickness=0, length=100).pack(side="left")

        # Timeline Settings for CURRENT stroke
        time_f = tk.Frame(main_c, bg=BG3, pady=10, padx=15)
        time_f.pack(fill="x", pady=(0, 15))
        
        tk.Label(time_f, text="⏱️ DRAWING DURATION:", font=("Segoe UI", 9, "bold"), bg=BG3, fg=ACCENT2).pack(side="left")
        
        # Start Time
        tk.Label(time_f, text=" Start:", bg=BG3, fg=SUBTEXT).pack(side="left", padx=(10, 0))
        for var in [self.start_h, self.start_m, self.start_s]:
            tk.Entry(time_f, textvariable=var, width=3, bg=BG2, fg=TEXT, relief="flat", justify="center").pack(side="left", padx=2)
            if var != self.start_s: tk.Label(time_f, text=":", bg=BG3, fg=SUBTEXT).pack(side="left")
            
        tk.Button(time_f, text="SET", font=("Segoe UI", 7), bg=BG2, fg=ACCENT, relief="flat", command=lambda: self._set_time_from_slider("start")).pack(side="left", padx=10)
        
        # End Time
        tk.Label(time_f, text=" End:", bg=BG3, fg=SUBTEXT).pack(side="left", padx=(10, 0))
        for var in [self.end_h, self.end_m, self.end_s]:
            tk.Entry(time_f, textvariable=var, width=3, bg=BG2, fg=TEXT, relief="flat", justify="center").pack(side="left", padx=2)
            if var != self.end_s: tk.Label(time_f, text=":", bg=BG3, fg=SUBTEXT).pack(side="left")
        
        tk.Button(time_f, text="SET", font=("Segoe UI", 7), bg=BG2, fg=ACCENT, relief="flat", command=lambda: self._set_time_from_slider("end")).pack(side="left", padx=5)
        
        tk.Button(time_f, text="🗑 CLEAR ALL", font=("Segoe UI", 8), bg="#444", fg=TEXT, relief="flat", command=self._clear_all).pack(side="right")

        # Canvas Area
        self.canvas_container = tk.Frame(main_c, bg=BG3, bd=1)
        self.canvas_container.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.canvas_container, bg=BG, highlightthickness=0, cursor="pencil")
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind("<B1-Motion>", self._draw)
        self.canvas.bind("<Button-1>", self._start_draw)
        self.canvas.bind("<ButtonRelease-1>", self._stop_draw)
        self.canvas.bind("<MouseWheel>", self._on_zoom)
        self.canvas.bind("<Button-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_move)

        # Video Scrubber
        self.time_ctrl = tk.Frame(main_c, bg=BG2)
        self.time_slider = tk.Scale(self.time_ctrl, variable=self.time_var, from_=0, to=100, orient="horizontal",
                                   bg=BG2, fg=TEXT, highlightthickness=0, troughcolor=BG3, activebackground=ACCENT,
                                   showvalue=False, command=self._on_time_slide)
        self.time_slider.pack(side="left", fill="x", expand=True)
        self.time_lbl = tk.Label(self.time_ctrl, text="00:00 / 00:00", font=("Consolas", 10), fg=SUBTEXT, bg=BG2, width=15)
        self.time_lbl.pack(side="right", padx=(10, 0))

        # Status & Action Bar
        sb = tk.Frame(self, bg=BG2, pady=10)
        sb.pack(fill="x", side="bottom")
        
        # Action Buttons
        ab = tk.Frame(sb, bg=BG2)
        ab.pack(side="right", padx=20)
        
        self.cancel_btn = tk.Button(ab, text="🚫 CANCEL", font=("Segoe UI", 9, "bold"), 
                  bg="#444", fg=TEXT, relief="flat", cursor="hand2", padx=15,
                  command=self._cancel)
        # Cancel is hidden by default
        
        self.render_btn = tk.Button(ab, text="🚀 RENDER VIDEO", font=("Segoe UI", 11, "bold"), 
                  bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", padx=40, pady=5,
                  command=self._start_render)
        self.render_btn.pack(side="right")
        
        self.pbar = ttk.Progressbar(sb, variable=self.progress_var, maximum=100, mode="determinate", length=250)
        self.pbar.pack(side="right", padx=20)
        
        tk.Label(sb, textvariable=self.status_var, font=("Segoe UI", 10), bg=BG2, fg=SUBTEXT, padx=20).pack(side="left")

    def _set_time_from_slider(self, target):
        curr = self.time_var.get()
        h = int(curr // 3600)
        m = int((curr % 3600) // 60)
        s = int(curr % 60)
        if target == "start":
            self.start_h.set(f"{h:02d}"); self.start_m.set(f"{m:02d}"); self.start_s.set(f"{s:02d}")
        else:
            self.end_h.set(f"{h:02d}"); self.end_m.set(f"{m:02d}"); self.end_s.set(f"{s:02d}")

    def _clear_all(self):
        if messagebox.askyesno("Confirm", "Delete all drawings?"):
            self.drawings = []
            self._show_on_canvas()

    def _load_media(self):
        path = filedialog.askopenfilename(filetypes=[("Media Files", "*.jpg *.jpeg *.png *.webp *.mp4 *.mov *.avi *.mkv")])
        if not path: return
        self.source_path.set(path)
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.mp4', '.mov', '.avi', '.mkv']:
            self.is_video_mode = True
            ffprobe = find_tool("ffprobe")
            if ffprobe:
                # Get duration
                p = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], capture_output=True, text=True)
                self.video_duration = float(p.stdout.strip()) if p.stdout.strip() else 0.0
                # Get resolution
                p = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", path], capture_output=True, text=True)
                import json
                data = json.loads(p.stdout)
                self.real_w = data['streams'][0]['width']
                self.real_h = data['streams'][0]['height']
            self.time_slider.config(to=self.video_duration)
            self.time_ctrl.pack(fill="x", pady=(10, 0), before=self.canvas_container)
            
            # Auto-set END time to video duration (Fix disappearing drawing bug)
            h = int(self.video_duration // 3600)
            m = int((self.video_duration % 3600) // 60)
            s = int(self.video_duration % 60)
            self.end_h.set(f"{h:02d}"); self.end_m.set(f"{m:02d}"); self.end_s.set(f"{s:02d}")
            
            self._seek_to_time(0)
        else:
            self.is_video_mode = False
            self.time_ctrl.pack_forget()
            img = Image.open(path).convert("RGB")
            self.real_w, self.real_h = img.size
            self.original_img = img.copy()
            self.original_img.thumbnail((800, 500), Image.Resampling.LANCZOS)
            self._show_on_canvas()

    def _on_time_slide(self, val):
        if self._seek_job: self.after_cancel(self._seek_job)
        self._seek_job = self.after(100, lambda: self._seek_to_time(float(val)))

    def _seek_to_time(self, seconds):
        if not self.is_video_mode: return
        ffmpeg = find_tool("ffmpeg")
        import tempfile
        import time as pytime
        temp_img = os.path.join(tempfile.gettempdir(), f"draw_seek_{int(pytime.time()*1000)}.jpg")
        subprocess.run([ffmpeg, "-y", "-ss", str(seconds), "-i", self.source_path.get(), "-frames:v", "1", "-q:v", "2", temp_img], capture_output=True)
        if os.path.exists(temp_img):
            self.original_img = Image.open(temp_img).convert("RGB")
            self.original_img.thumbnail((800, 500), Image.Resampling.LANCZOS)
            self.time_lbl.config(text=f"{self._format_time(seconds)} / {self._format_time(self.video_duration)}")
            self._show_on_canvas()
            try: os.remove(temp_img)
            except: pass

    def _format_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0: return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _show_on_canvas(self):
        if not self.original_img: return
        w, h = self.original_img.size
        zw, zh = int(w * self.zoom_level), int(h * self.zoom_level)
        display_img = self.original_img.resize((zw, zh), Image.Resampling.LANCZOS).convert("RGBA")
        
        # Draw active strokes for current timestamp
        draw = ImageDraw.Draw(display_img)
        curr_t = self.time_var.get()
        
        # Scale factor from real resolution to thumbnail resolution
        sw = zw / self.real_w
        sh = zh / self.real_h
        
        for d in self.drawings:
            # Check if active for current time if video
            if self.is_video_mode:
                if not (d['start'] <= curr_t <= d['end']): continue
            
            # Re-scale points from REAL space to ZOOMED thumb space
            pts = [(p[0] * sw, p[1] * sh) for p in d['points']]
            if len(pts) > 1:
                # Fixed: Use visual brush width relative to zoomed canvas
                visual_w = d['width'] * self.zoom_level
                draw.line(pts, fill=d['color'], width=int(max(1, visual_w)), joint="round")
            
        self.tk_img = ImageTk.PhotoImage(display_img)
        self.canvas.delete("all")
        self.canvas.create_image(self.offset_x, self.offset_y, image=self.tk_img, anchor="nw")

    def _to_real_img_coords(self, sx, sy):
        if not self.original_img: return 0, 0
        # 1. Canvas to Thumbnail space
        tx = (sx - self.offset_x) / self.zoom_level
        ty = (sy - self.offset_y) / self.zoom_level
        # 2. Thumbnail to Real space
        tw, th = self.original_img.size
        rx = tx * (self.real_w / tw)
        ry = ty * (self.real_h / th)
        return rx, ry

    def _start_draw(self, e):
        self.last_x, self.last_y = e.x, e.y
        px, py = self._to_real_img_coords(e.x, e.y)
        if self.draw_mode.get() == "eraser":
            self._erase_at(px, py)
        else:
            self.current_stroke = [(px, py)]

    def _draw(self, e):
        if not self.original_img: return
        px, py = self._to_real_img_coords(e.x, e.y)
        
        if self.draw_mode.get() == "eraser":
            self._erase_at(px, py)
        else:
            # Feedback on canvas
            self.canvas.create_line(self.last_x, self.last_y, e.x, e.y, fill=self.draw_color.get(), 
                                    width=self.brush_size.get()*self.zoom_level, capstyle="round", tags="temp")
            self.current_stroke.append((px, py))
        
        self.last_x, self.last_y = e.x, e.y

    def _erase_at(self, px, py):
        if not self.drawings: return
        # Boosted sensitivity for high-res screens
        tw, th = self.original_img.size
        threshold = self.brush_size.get() * 4.0 * (self.real_w / tw)
        curr_t = self.time_var.get()
        to_remove = []
        
        for i, d in enumerate(self.drawings):
            # Only erase visible strokes
            if self.is_video_mode:
                if not (d['start'] <= curr_t <= d['end']): continue
            
            # Check proximity to any segment
            pts = d['points']
            found = False
            for j in range(len(pts)-1):
                p1, p2 = pts[j], pts[j+1]
                # Distance point to segment math
                dx, dy = p2[0]-p1[0], p2[1]-p1[1]
                l2 = dx*dx + dy*dy
                if l2 == 0:
                    dist_sq = (px-p1[0])**2 + (py-p1[1])**2
                else:
                    t = ((px - p1[0]) * dx + (py - p1[1]) * dy) / l2
                    t = max(0, min(1, t))
                    dist_sq = (px - (p1[0] + t * dx))**2 + (py - (p1[1] + t * dy))**2
                
                if dist_sq < threshold*threshold:
                    found = True
                    break
            
            if found:
                to_remove.append(i)
        
        if to_remove:
            # Remove in reverse to maintain indices
            for index in sorted(to_remove, reverse=True):
                self.drawings.pop(index)
            self._show_on_canvas()

    def _stop_draw(self, e):
        if self.draw_mode.get() == "brush" and len(self.current_stroke) > 1:
            try:
                # Parse HH:MM:SS to total seconds
                sh = int(self.start_h.get() or 0)
                sm = int(self.start_m.get() or 0)
                ss = int(self.start_s.get() or 0)
                start_total = sh * 3600 + sm * 60 + ss
                
                eh = int(self.end_h.get() or 0)
                em = int(self.end_m.get() or 0)
                es = int(self.end_s.get() or 0)
                end_total = eh * 3600 + em * 60 + es
                
                self.drawings.append({
                    'points': self.current_stroke,
                    'color': self.draw_color.get(),
                    'width': self.brush_size.get(),
                    'start': start_total,
                    'end': end_total
                })
            except Exception as ex:
                print(f"Time parse error: {ex}")
        self.current_stroke = []
        self._show_on_canvas()

    def _on_zoom(self, e):
        old_z = self.zoom_level
        factor = 1.2 if e.delta > 0 else 0.8
        self.zoom_level = max(0.5, min(10.0, self.zoom_level * factor))
        self.offset_x = e.x - (e.x - self.offset_x) * (self.zoom_level / old_z)
        self.offset_y = e.y - (e.y - self.offset_y) * (self.zoom_level / old_z)
        self._show_on_canvas()

    def _on_pan_start(self, e): self.pan_start_x, self.pan_start_y = e.x, e.y
    def _on_pan_move(self, e):
        self.offset_x += (e.x - self.pan_start_x); self.offset_y += (e.y - self.pan_start_y)
        self.pan_start_x, self.pan_start_y = e.x, e.y; self._show_on_canvas()

    def _cancel(self): self.is_cancelled = True; self.status_var.set("Cancelled")

    def _start_render(self):
        if not self.original_img or not self.drawings: return
        self.is_active = True; self.is_cancelled = False
        self.render_btn.config(state="disabled", text="⌛ RENDERING...")
        self.cancel_btn.pack(side="right", padx=10)
        threading.Thread(target=self._render_process, daemon=True).start()

    def _render_process(self):
        try:
            import cv2
            import numpy as np
            import tempfile
            from PIL import Image, ImageDraw
            
            ffmpeg = find_tool("ffmpeg")
            ffprobe = find_tool("ffprobe")
            input_path = self.source_path.get()
            
            if not self.is_video_mode:
                # Image Mode
                save_p = filedialog.asksaveasfilename(defaultextension=".jpg", filetypes=[("Image Files", "*.jpg *.png")])
                if not save_p: return
                img = self.original_img.copy()
                draw = ImageDraw.Draw(img)
                for d in self.drawings:
                    if len(d['points']) > 1:
                        draw.line(d['points'], fill=d['color'], width=d['width'], joint="round")
                img.save(save_p)
                self.after(0, lambda: self.status_var.set("Image Saved Done ✓"))
                os.startfile(os.path.dirname(save_p))
                return

            # Video Mode (Pro Stream Renderer)
            width, height = 1920, 1080
            fps = 30.0
            p = subprocess.run([ffprobe, "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", input_path], capture_output=True, text=True)
            data = json.loads(p.stdout)
            width, height = data['streams'][0]['width'], data['streams'][0]['height']
            fps_raw = data['streams'][0]['r_frame_rate']
            n, d = map(float, fps_raw.split("/"))
            fps = n/d if d>0 else 30.0
            
            # 1.1 Force Even Dimensions (Broken Pipe Fix)
            if width % 2 != 0: width -= 1
            if height % 2 != 0: height -= 1
            
            total_frames = int(self.video_duration * fps)
            incmd = [ffmpeg, "-i", input_path, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
            reader = subprocess.Popen(incmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            
            v_codec = "libx264"
            v_params = ["-crf", "18", "-preset", "fast"]
            if GLOBAL_HW.get("has_cuda"):
                chk = subprocess.run([ffmpeg, "-encoders"], capture_output=True, text=True)
                if "h264_nvenc" in chk.stdout:
                    v_codec = "h264_nvenc"
                    v_params = ["-preset", "p4", "-tune", "hq", "-cq", "18"]
            
            output_tmp = tempfile.mktemp(suffix="_drawn.mp4")
            outcmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-c:v", v_codec] + v_params + ["-pix_fmt", "yuv420p", output_tmp]
            writer = subprocess.Popen(outcmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            
            frame_bytes = width * height * 3
            for i in range(total_frames):
                if self.is_cancelled: break
                raw = reader.stdout.read(frame_bytes)
                if not raw: break
                
                curr_t = i / fps
                img = Image.frombuffer("RGB", (width, height), raw)
                draw = ImageDraw.Draw(img)
                
                # Scaled width for render
                tw, th = self.original_img.size # The 800x500 reference
                scale_w = width / tw
                
                for d in self.drawings:
                    if d['start'] <= curr_t <= d['end']:
                        if len(d['points']) > 1:
                            render_w = d['width'] * scale_w
                            draw.line(d['points'], fill=d['color'], width=int(render_w), joint="round")
                
                try:
                    if writer.poll() is None:
                        writer.stdin.write(np.array(img).tobytes())
                    else:
                        raise Exception("FFmpeg writer process terminated unexpectedly")
                except (OSError, BrokenPipeError) as e:
                    raise Exception(f"Pipe error during video encoding: {e}")
                if i % 30 == 0:
                    prog = (i / total_frames) * 100
                    self.after(0, lambda p=prog: self.progress_var.set(p))
                    self.after(0, lambda i=i, t=total_frames: self.status_var.set(f"Rendering: {i}/{t} frames"))
            
            reader.terminate(); writer.stdin.close(); writer.wait()
            if self.is_cancelled: return
            
            save_p = filedialog.asksaveasfilename(defaultextension=".mp4", initialfile="drawn_video.mp4")
            if save_p:
                audio_tmp = tempfile.mktemp(suffix=".aac")
                subprocess.run([ffmpeg, "-y", "-i", input_path, "-vn", "-acodec", "copy", audio_tmp], capture_output=True)
                subprocess.run([ffmpeg, "-y", "-i", output_tmp, "-i", audio_tmp, "-map", "0:v", "-map", "1:a?", "-c", "copy", "-shortest", save_p], capture_output=True)
                self.after(0, lambda: self.status_var.set("Render Done ✓"))
                os.startfile(os.path.dirname(save_p))
                
        except Exception as e:
            self.after(0, lambda err=e: messagebox.showerror("Render Error", str(err)))
        finally:
            self.is_active = False
            self.after(0, lambda: self.render_btn.config(state="normal", text="🚀 RENDER VIDEO"))
            self.after(0, lambda: self.cancel_btn.pack_forget())

class TikTokDownloader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pro Media Suite — Single File Edition 2.0")
        self.geometry("1024x720")
        self.state("zoomed")
        self.resizable(True, True)
        self.minsize(1024, 720)
        self.configure(bg=BG)

        self.save_path    = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        
        # --- TAB 1: Media Downloader State ---
        self.dl_status_var   = tk.StringVar(value="Media Downloader — Ready ✓")
        self.dl_progress_var = tk.DoubleVar(value=0)
        self.is_dl_active    = False
        self.url_queue       = [] # Batch download queue
        
        # --- TAB 2: Local Upscaler State ---
        self.up_status_var   = tk.StringVar(value="Local Upscaler — Ready ✓")
        self.up_progress_var = tk.DoubleVar(value=0)
        self.is_up_active    = False
        self.local_files     = [] # File list for batch upscale
        
        self.no_watermark = tk.BooleanVar(value=True)
        self.quality_var  = tk.StringVar(value="Auto (Best Available)")
        self.upscale_var  = tk.StringVar(value="❌ No Upscale")
        self.use_movie_mode = tk.BooleanVar(value=True)
        self.perf_var     = tk.StringVar(value="Auto (Recommended)")
        self.perf_t       = 100
        self.perf_j       = "1:1:1:1"
        self.detected_hw  = "Checking..."
        self.current_proc = None
        
        # Shortcuts
        self.bind_all("<Alt-q>", lambda e: self._show_help())
        self.bind_all("<Alt-Q>", lambda e: self._show_help())

        self._build_ui()
        # Initialize hardware detection
        threading.Thread(target=self._auto_tune_hardware, daemon=True).start()
        self.after(500, self._auto_setup) 

    def _create_local_certificate(self):
        """Generate a local self-signed certificate for code signing."""
        if os.name != 'nt':
            messagebox.showinfo("Info", "Certificate generation is currently only supported on Windows.")
            return
            
        cert_name = "AI_Media_Suite_Local"
        # Using a more robust PowerShell script with error handling
        ps_script = f"""
        $ErrorActionPreference = 'Stop'
        try {{
            if (!(Get-PSDrive -Name Cert -ErrorAction SilentlyContinue)) {{
                Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue
            }}
            $cert = New-SelfSignedCertificate -Subject "CN={cert_name}" -CertStoreLocation "Cert:\\CurrentUser\\My" -Type CodeSigningCert -FriendlyName "{cert_name}" -NotAfter (Get-Date).AddYears(10)
            $cert_path = Join-Path $env:TEMP "{cert_name}.cer"
            Export-Certificate -Cert $cert -FilePath $cert_path | Out-Null
            Import-Certificate -FilePath $cert_path -CertStoreLocation "Cert:\\CurrentUser\\Root" | Out-Null
            Remove-Item $cert_path
            Write-Host "SUCCESS"
        }} catch {{
            Write-Error $_.Exception.Message
            exit 1
        }}
        """
        
        self.after(0, lambda: self.dl_status_var.set("Generating Local Certificate..."))
        
        def run_ps():
            try:
                # Use -NoProfile to avoid environment conflicts
                proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, check=True)
                self.after(0, lambda: messagebox.showinfo("Success", f"Local certificate '{cert_name}' created and installed to Trusted Root.\nYou can now use this to sign your EXE."))
                self.after(0, lambda: self.dl_status_var.set("Certificate Created ✓"))
            except subprocess.CalledProcessError as e:
                # Filter out common type data warnings that are often mistaken for errors
                err_msg = e.stderr if e.stderr else e.stdout
                clean_msg = "\n".join([line for line in err_msg.splitlines() if "member" not in line.lower() and "already present" not in line.lower()])
                if not clean_msg.strip(): clean_msg = err_msg
                self.after(0, lambda m=clean_msg: messagebox.showerror("Error", f"Failed to create certificate:\n{m}"))
                self.after(0, lambda: self.dl_status_var.set("Certificate Failed ❌"))
            except Exception as e:
                self.after(0, lambda m=str(e): messagebox.showerror("Error", f"Unexpected error: {m}"))
                self.after(0, lambda: self.dl_status_var.set("Error ❌"))

        threading.Thread(target=run_ps, daemon=True).start()

    def _auto_setup(self):
        """Automatically check and download missing dependencies."""
        setup_flag = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".setup_prompted")
        
        missing_critical = not check_ytdlp() or not check_ffmpeg()
        missing_ai = not check_realesrgan()
        lama_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "big-lama.pt")
        missing_lama = not os.path.exists(lama_path)
        missing_py_libs = not HAS_DEEP_TRANS or not HAS_WHISPER or not HAS_TORCH
        
        if (missing_py_libs or missing_critical or missing_ai or missing_lama) and not os.path.exists(setup_flag):
            msg = "Welcome to AI Media Suite!\n\nIt looks like this is your first run or some components are missing.\n\nWould you like to automatically download and install the required AI models and tools? (Approx. 2-5GB total)"
            if messagebox.askyesno("First Run Setup", msg):
                if missing_py_libs:
                    self.after(500, self._run_system_repair)
                else:
                    self.after(500, self._install_ai_tools)
            else:
                # Create flag so we don't ask again next time
                try:
                    with open(setup_flag, "w") as f: f.write("1")
                except: pass
                self._check_deps()
        else:
            self._check_deps()

    def _check_deps(self):
        missing = []
        if not check_ffmpeg():
            missing.append("ffmpeg/ffprobe")
        if not check_realesrgan():
            missing.append("Real-ESRGAN")
            
        if missing:
            msg = f"⚠️  Missing: {', '.join(missing)}"
            if "Real-ESRGAN" in missing:
                msg += " (Click Install below)"
                # Show install button in status bar area if missing
                self.setup_btn.pack(side="right", padx=16)
            self._set_status(msg, WARN)
        else:
            if hasattr(self, 'setup_btn'):
                self.setup_btn.pack_forget()
            self._set_status("Ready ✓", SUCCESS)

    def _build_ui(self):
        # Notebook for Tabs
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG2, foreground=SUBTEXT, padding=[20, 5])
        style.map("TNotebook.Tab", background=[("selected", BG3)], foreground=[("selected", ACCENT)])

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)

        self.tab1 = tk.Frame(self.tabs, bg=BG)
        self.tab2 = tk.Frame(self.tabs, bg=BG)
        self.tab3 = tk.Frame(self.tabs, bg=BG)
        self.tab4 = tk.Frame(self.tabs, bg=BG)
        self.tab5 = tk.Frame(self.tabs, bg=BG)
        self.tab6 = tk.Frame(self.tabs, bg=BG)
        self.tab7 = tk.Frame(self.tabs, bg=BG)
        self.tab8 = tk.Frame(self.tabs, bg=BG)
        self.tab9 = tk.Frame(self.tabs, bg=BG)
        
        self.tabs.add(self.tab1, text="  🌐 Media Downloader  ")
        self.tabs.add(self.tab2, text="  📁 Local File Upscaler  ")
        
        if HAS_WHISPER and HAS_DEEP_TRANS:
            self.tabs.add(self.tab3, text="  🎙️ AI Translator  ")
            self.translator_tab = TiktokTranslatorTab(self.tab3)
            self.translator_tab.pack(fill="both", expand=True)
        else:
            self.tabs.add(self.tab3, text="  🎙️ AI Translator (Missing Deps)  ")
            err_lbl = tk.Label(self.tab3, text="⚠️  AI Translator Unavailabe\n\nMissing 'whisper' or 'deep_translator' packages.\nPlease run 'pip install openai-whisper deep-translator'",
                               font=("Segoe UI", 12), fg=WARN, bg=BG, pady=100)
            err_lbl.pack(fill="both", expand=True)

        self.tabs.add(self.tab4, text="  🔍 Image Finder  ")
        self.finder_tab = ImageFinderTab(self.tab4)
        self.finder_tab.pack(fill="both", expand=True)

        self.tabs.add(self.tab5, text="  🖼️ Extractor  ")
        self.frame_tab = TikTokFrameUpscalerTab(self.tab5)
        self.frame_tab.pack(fill="both", expand=True)

        self.tabs.add(self.tab6, text="  🪄 Object Remover  ")
        self.remover_tab = AIObjectRemoverTab(self.tab6)
        self.remover_tab.pack(fill="both", expand=True)

        self.tabs.add(self.tab7, text="  🎨 Video Draw  ")
        self.draw_tab = VideoDrawTab(self.tab7)
        self.draw_tab.pack(fill="both", expand=True)

        self.tabs.add(self.tab9, text="  📸 Image Agent  ")
        self.img_agent_tab = TikTokImageAgentTab(self.tab9)
        self.img_agent_tab.pack(fill="both", expand=True)

        self.tabs.add(self.tab8, text="  ⚙️ Settings  ")
        self.settings_tab = SettingsTab(self.tab8)
        self.settings_tab.pack(fill="both", expand=True)

        # --- TAB 1: DOWNLOADER ---
        # Header
        header = tk.Frame(self.tab1, bg=BG, pady=16)
        header.pack(fill="x", padx=30)
        tf = tk.Frame(header, bg=BG)
        tf.pack()
        tk.Label(tf, text="🚀",           font=("Segoe UI Emoji", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(tf, text=" Pro Media",        font=("Impact", 24),         fg=TEXT,    bg=BG).pack(side="left")
        tk.Label(tf, text=" Downloader",         font=("Impact", 24),         fg=ACCENT2,  bg=BG).pack(side="left")
        tk.Label(header, text="Download + Automatic AI Upscale (up to 4K)",
                 font=("Segoe UI", 10), fg=SUBTEXT, bg=BG).pack()

        tk.Frame(self.tab1, bg=ACCENT, height=2).pack(fill="x", padx=30)

        card = tk.Frame(self.tab1, bg=BG2, padx=24, pady=30)
        card.pack(fill="both", expand=True, padx=30, pady=14)

        # URL
        tk.Label(card, text="🔗  Video or Audio Link", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT, bg=BG2, anchor="w").pack(fill="x")
        
        url_row = tk.Frame(card, bg=BG2)
        url_row.pack(fill="x", pady=(4, 12))
        
        # (Queue moved to bottom)
        
        url_frame = tk.Frame(url_row, bg=BG3, pady=2)
        url_frame.pack(side="left", fill="both", expand=True)
        self.url_entry = tk.Entry(url_frame, font=("Consolas", 12),
                                  bg=BG3, fg=TEXT, insertbackground=ACCENT2,
                                  relief="flat", bd=8,
                                  highlightthickness=1, highlightcolor=ACCENT, highlightbackground=BG3)
        self.url_entry.pack(side="left", fill="both", expand=True)
        self.url_entry.insert(0, "Paste links here (TikTok, YouTube, etc.)...")
        self.url_entry.config(fg=SUBTEXT)
        self.url_entry.bind("<FocusIn>",  self._clear_ph)
        self.url_entry.bind("<FocusOut>", self._restore_ph)
        self.url_entry.bind("<Return>",   lambda e: self._add_url())

        # Buttons beside entry
        tk.Button(url_row, text="➕ Add", font=("Segoe UI", 9, "bold"),
                  bg=ACCENT2, fg=BG, relief="flat", cursor="hand2",
                  activebackground=SUCCESS, command=self._add_url, padx=10).pack(side="left", padx=4)
        
        tk.Button(url_row, text="📋 Paste", font=("Segoe UI", 9),
                  bg=BG3, fg=SUBTEXT, relief="flat", cursor="hand2",
                  command=self._paste, padx=8).pack(side="left")

        tk.Button(url_row, text="🗑️ Remove", font=("Segoe UI", 9),
                  bg=BG3, fg=ACCENT, relief="flat", cursor="hand2",
                  command=self._remove_url, padx=8).pack(side="right", padx=(4,0))

        # Quality + Upscale side by side
        two_col = tk.Frame(card, bg=BG2)
        two_col.pack(fill="x", pady=(0, 4))

        left = tk.Frame(two_col, bg=BG2)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = tk.Frame(two_col, bg=BG2)
        right.pack(side="right", fill="both", expand=True)

        # Quality
        tk.Label(left, text="🎬  Video Quality", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT, bg=BG2, anchor="w").pack(fill="x")
        q_frame = tk.Frame(left, bg=BG3, pady=4)
        q_frame.pack(fill="x", pady=(4, 0))

        style = ttk.Style()
        style.theme_use("default")
        style.configure("C.TCombobox",
                         fieldbackground=BG3, background=BG3,
                         foreground=TEXT, selectbackground=ACCENT,
                         selectforeground=TEXT, arrowcolor=ACCENT2)
        style.configure("T1.Horizontal.TProgressbar",
                         troughcolor=BG3, background=ACCENT,
                         thickness=10, bordercolor=BG,
                         lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("T2.Horizontal.TProgressbar",
                         troughcolor=BG3, background=ACCENT2,
                         thickness=10, bordercolor=BG,
                         lightcolor=ACCENT2, darkcolor=ACCENT2)

        self.q_cb = ttk.Combobox(q_frame, textvariable=self.quality_var,
                                  values=list(QUALITY_OPTIONS.keys()),
                                  font=("Segoe UI", 10), state="readonly", style="C.TCombobox")
        self.q_cb.pack(fill="x", padx=8, pady=2)
        self.q_cb.bind("<<ComboboxSelected>>", self._on_quality)

        # Upscale
        tk.Label(right, text="🔺  AI Upscale", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        u_frame = tk.Frame(right, bg=BG3, pady=4)
        u_frame.pack(fill="x", pady=(4, 0))

        self.u_cb = ttk.Combobox(u_frame, textvariable=self.upscale_var,
                                  values=list(UPSCALE_OPTIONS.keys()),
                                  font=("Segoe UI", 10), state="readonly", style="C.TCombobox")
        self.u_cb.pack(fill="x", padx=8, pady=2)
        self.u_cb.bind("<<ComboboxSelected>>", self._on_upscale)
        
        self.movie_chk = tk.Checkbutton(u_frame, text="🎬 Movie Mode (Chunking over 3m)", variable=self.use_movie_mode, bg=BG3, fg=TEXT, selectcolor=BG2, activebackground=BG3, activeforeground=TEXT, font=("Segoe UI", 9))
        self.movie_chk.pack(anchor="w", padx=4, pady=(2, 4))

        # --- DOWNLOAD QUEUE (Bottom Expanding) ---
        tk.Label(card, text="📋  Download Queue", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x", pady=(10, 0))
        
        queue_container = tk.Frame(card, bg=BG3, pady=2)
        queue_container.pack(fill="both", expand=True, pady=(4, 8))
        
        self.queue_listbox = tk.Listbox(queue_container, font=("Consolas", 10),
                                        bg=BG3, fg=TEXT, height=5, relief="flat",
                                        borderwidth=0, highlightthickness=0,
                                        selectbackground=ACCENT, selectforeground=TEXT)
        self.queue_listbox.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        
        v_sb = ttk.Scrollbar(queue_container, orient="vertical", command=self.queue_listbox.yview)
        v_sb.pack(side="right", fill="y")
        h_sb = ttk.Scrollbar(queue_container, orient="horizontal", command=self.queue_listbox.xview)
        h_sb.pack(side="bottom", fill="x")
        
        self.queue_listbox.config(yscrollcommand=v_sb.set, xscrollcommand=h_sb.set)
        self.queue_listbox.bind("<<ListboxSelect>>", self._on_queue_select)
        self.url_metadata_cache = {}

        # --- TAB 1 Down Button and Watermark logic (grouped correctly) ---
        opt = tk.Frame(card, bg=BG2)
        opt.pack(fill="x", pady=(0, 12))
        self.wm_chk = tk.Checkbutton(opt,
                                      text="  ⚡ No Watermark (TikTok Only)",
                                      variable=self.no_watermark,
                                      font=("Segoe UI", 10),
                                      fg=TEXT, bg=BG2, selectcolor=BG3,
                                      activebackground=BG2, activeforeground=TEXT,
                                      cursor="hand2")
        self.wm_chk.pack(side="left")

        # Download btn
        btn_row1 = tk.Frame(card, bg=BG2)
        btn_row1.pack(fill="x")
        
        self.dl_btn = tk.Button(btn_row1, text="⬇   DOWNLOAD + UPSCALE",
                                 font=("Impact", 14),
                                 bg=ACCENT, fg=TEXT, relief="flat",
                                 cursor="hand2", pady=12,
                                 activebackground="#cc2244",
                                 command=self._start)
        self.dl_btn.pack(side="left", fill="x", expand=True)
        self._hover(self.dl_btn, ACCENT, "#cc2244")

        # Footer Status
        status_bar = tk.Frame(self.tab1, bg=BG2, pady=5)
        status_bar.pack(fill="x", side="bottom")
        self.dl_status_lbl = tk.Label(status_bar, textvariable=self.dl_status_var, font=("Segoe UI", 9),
                                      bg=BG2, fg=SUBTEXT, padx=20)
        self.dl_status_lbl.pack(side="left")

        # Integrated Progress & Info
        self.pbar1 = ttk.Progressbar(card, variable=self.dl_progress_var,
                                     maximum=100, style="T1.Horizontal.TProgressbar")
        self.pbar1.pack(fill="x", pady=(10, 5))
        
        self.info_lbl1 = tk.Label(card, text="", font=("Segoe UI", 9),
                                  bg=BG2, fg=SUBTEXT, anchor="w")
        self.info_lbl1.pack(fill="x")

        self.cancel_btn1 = tk.Button(btn_row1, text="❌ CANCEL",
                                     font=("Segoe UI", 10, "bold"),
                                     bg=BG3, fg=ACCENT, relief="flat",
                                     cursor="hand2", padx=15,
                                     command=lambda: self._cancel_process("dl"))
        # Hidden by default

        # Move ESRGAN & Performance to SettingsTab
        sett_body = tk.Frame(self.settings_tab, bg=BG2, padx=40, pady=0)
        sett_body.pack(fill="x", padx=30, pady=(0, 20))

        # --- OUTPUT FOLDER (Moved to Settings) ---
        folder_card = tk.LabelFrame(sett_body, text=" 📁  Save / Output Folder ", font=("Segoe UI", 10, "bold"), bg=BG2, fg=ACCENT, padx=20, pady=15)
        folder_card.pack(fill="x", pady=(0, 20))
        tk.Label(folder_card, text="All downloaded media, upscaled images and processed files will be saved here.", font=("Segoe UI", 9), fg=SUBTEXT, bg=BG2, wraplength=600, justify="left").pack(anchor="w", pady=(0, 8))
        pf = tk.Frame(folder_card, bg=BG3)
        pf.pack(fill="x")
        tk.Label(pf, textvariable=self.save_path, font=("Consolas", 10), fg=TEXT, bg=BG3, anchor="w", padx=8, pady=6).pack(side="left", fill="both", expand=True)
        tk.Button(pf, text="Browse...", font=("Segoe UI", 9), bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", activebackground="#cc2244", padx=14, pady=4, command=self._choose_folder).pack(side="right", padx=4, pady=4)

        
        # ESRGAN path
        esrgan_frame = tk.Frame(sett_body, bg=BG3)
        esrgan_frame.pack(fill="x", pady=(0, 20))
        tk.Label(esrgan_frame, text="📂 Real-ESRGAN path:",
                 font=("Segoe UI", 9), fg=SUBTEXT, bg=BG3).pack(anchor="w", padx=8, pady=(4,0))
        esrgan_row = tk.Frame(esrgan_frame, bg=BG3)
        esrgan_row.pack(fill="x", padx=8, pady=(2,6))
        self.esrgan_entry = tk.Entry(esrgan_row, font=("Consolas", 9),
                                      bg=BG3, fg=TEXT, insertbackground=ACCENT2,
                                      relief="flat", bd=4,
                                      highlightthickness=1, highlightcolor=BG3, highlightbackground=BG3)
        self.esrgan_entry.pack(side="left", fill="both", expand=True)
        # Auto-fill if found
        found_esr = find_tool("realesrgan-ncnn-vulkan")
        self.esrgan_entry.insert(0, found_esr if found_esr else "realesrgan-ncnn-vulkan.exe")
        tk.Button(esrgan_row, text="Browse...", font=("Segoe UI", 8),
                  bg=BG2, fg=TEXT, relief="flat", cursor="hand2",
                  padx=6, command=self._choose_esrgan).pack(side="right", padx=(4,0))

        # Performance Engine
        perf_frame = tk.LabelFrame(sett_body, text=" PERFORMANCE ENGINE (AI UPSCALE) ", font=("Segoe UI", 10, "bold"), bg=BG2, fg=ACCENT2, padx=20, pady=20)
        perf_frame.pack(fill="x", pady=(0, 20))
        
        tk.Label(perf_frame, text="⚡ Select Engine:", font=("Segoe UI", 9, "bold"),
                 fg=SUBTEXT, bg=BG2).pack(side="left")
        
        self.perf_cb = ttk.Combobox(perf_frame, textvariable=self.perf_var,
                                     values=["Auto (Recommended)", "🧊 Ice Mode (Safe)", "⚡ Balanced Mode", "🚀 Turbo Mode", "🎯 Extreme Mode"],
                                     state="readonly", width=22, style="C.TCombobox")
        self.perf_cb.pack(side="left", padx=10)
        
        self.hw_lbl = tk.Label(perf_frame, text="Detecting GPU...", font=("Segoe UI", 9),
                               fg=SUBTEXT, bg=BG2)
        self.hw_lbl.pack(side="left", padx=10)
        self.local_files = [] # Queue for tab 2
        self.scale_var2 = tk.StringVar(value="4x")
        self.mode_var2 = tk.StringVar(value="🏆 Best Quality")
        
        l_header = tk.Frame(self.tab2, bg=BG, pady=16)
        l_header.pack(fill="x", padx=30)
        ltf = tk.Frame(l_header, bg=BG)
        ltf.pack()
        tk.Label(ltf, text="🔺",          font=("Segoe UI Emoji", 24), fg=ACCENT, bg=BG).pack(side="left")
        tk.Label(ltf, text=" Local File", font=("Impact", 24),         fg=TEXT,   bg=BG).pack(side="left")
        tk.Label(ltf, text=" Upscaler",   font=("Impact", 24),         fg=ACCENT2, bg=BG).pack(side="left")
        
        tk.Frame(self.tab2, bg=ACCENT2, height=2).pack(fill="x", padx=30)
        
        l_card = tk.Frame(self.tab2, bg=BG2, padx=24, pady=30)
        l_card.pack(fill="both", expand=True, padx=30, pady=14)
        
        # File List
        tk.Label(l_card, text="📋  File Queue (Images/Videos)", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")
        
        l_queue_frame = tk.Frame(l_card, bg=BG3, pady=2)
        l_queue_frame.pack(fill="both", expand=True, pady=(4, 8))
        
        self.local_listbox = tk.Listbox(l_queue_frame, font=("Consolas", 9),
                                        bg=BG3, fg=TEXT, height=12, relief="flat",
                                        borderwidth=0, highlightthickness=0,
                                        selectbackground=ACCENT2, selectforeground=BG)
        self.local_listbox.pack(side="left", fill="both", expand=True, padx=8, pady=4)
        
        v_lsb = ttk.Scrollbar(l_queue_frame, orient="vertical", command=self.local_listbox.yview)
        v_lsb.pack(side="right", fill="y")
        h_lsb = ttk.Scrollbar(l_queue_frame, orient="horizontal", command=self.local_listbox.xview)
        h_lsb.pack(side="bottom", fill="x")
        self.local_listbox.config(yscrollcommand=v_lsb.set, xscrollcommand=h_lsb.set)
        
        # Add/Clear buttons
        l_btn_row = tk.Frame(l_card, bg=BG2)
        l_btn_row.pack(fill="x", pady=(0, 10))
        
        tk.Button(l_btn_row, text="➕ Add Files", font=("Segoe UI", 9, "bold"),
                  bg=ACCENT2, fg=BG, relief="flat", cursor="hand2",
                  command=self._add_local_files, padx=15).pack(side="left")
        
        tk.Button(l_btn_row, text="🗑️ Clear List", font=("Segoe UI", 9),
                  bg=BG3, fg=SUBTEXT, relief="flat", cursor="hand2",
                  command=self._clear_local_list, padx=10).pack(side="right")

        # Local Settings
        l_sett = tk.Frame(l_card, bg=BG2)
        l_sett.pack(fill="x", pady=5)
        
        # Scale 2
        tk.Label(l_sett, text="📐 Scale:", font=("Segoe UI", 9, "bold"), 
                 fg=ACCENT2, bg=BG2).pack(side="left")
        ttk.Combobox(l_sett, textvariable=self.scale_var2, values=["2x", "4x"], 
                     width=5, state="readonly", style="C.TCombobox").pack(side="left", padx=10)
        
        # Mode 2
        m_row = tk.Frame(l_sett, bg=BG2)
        m_row.pack(side="left", padx=(15, 0))
        tk.Label(m_row, text="⚡ Mode:", font=("Segoe UI", 9, "bold"), 
                 fg=ACCENT2, bg=BG2).pack(side="left")
        ttk.Combobox(m_row, textvariable=self.mode_var2, 
                     values=["⚡ Ultra Fast (Anime)", "🏆 Best Quality"], 
                     width=18, state="readonly", style="C.TCombobox").pack(side="left", padx=8)

        # Process Type 2
        p_row = tk.Frame(l_sett, bg=BG2)
        p_row.pack(side="left", padx=(15, 0))
        tk.Checkbutton(p_row, text="🎬 Movie Mode (>3 min)", variable=self.use_movie_mode, bg=BG2, fg=SUBTEXT, selectcolor=BG, activebackground=BG2, activeforeground=TEXT).pack(side="left")
        
        # Footer Status
        status_bar2 = tk.Frame(self.tab2, bg=BG2, pady=5)
        status_bar2.pack(fill="x", side="bottom")
        self.up_status_lbl = tk.Label(status_bar2, textvariable=self.up_status_var, font=("Segoe UI", 9),
                                      bg=BG2, fg=SUBTEXT, padx=20)
        self.up_status_lbl.pack(side="left")

        # Integrated Progress & Info
        self.pbar2 = ttk.Progressbar(l_card, variable=self.up_progress_var,
                                     maximum=100, style="T2.Horizontal.TProgressbar")
        self.pbar2.pack(fill="x", pady=(10, 5))

        # Local Start Button
        btn_row2 = tk.Frame(l_card, bg=BG2)
        btn_row2.pack(fill="x", pady=(10, 0))
        
        self.local_btn = tk.Button(btn_row2, text="🚀  START BATCH UPSCALE",
                                  font=("Impact", 14),
                                  bg=ACCENT2, fg=BG, relief="flat",
                                  cursor="hand2", pady=12,
                                  command=self._start_local_batch)
        self.local_btn.pack(side="left", fill="x", expand=True)
        self._hover(self.local_btn, ACCENT2, "#00d2ca")
        
        self.info_lbl2 = tk.Label(l_card, text="", font=("Segoe UI", 9),
                                  bg=BG2, fg=SUBTEXT, anchor="w")
        self.info_lbl2.pack(fill="x")
    
        sb = tk.Frame(self, bg=BG3, pady=6)
        sb.pack(fill="x", side="bottom")
        tk.Label(sb, text="Suite Engine Active",
                 font=("Segoe UI", 9, "bold"), fg="#444",
                 bg=BG3, padx=16).pack(side="left")
        
        self.setup_btn = tk.Button(sb, text="⚙️ Install AI Tools",
                                   font=("Segoe UI", 9, "bold"),
                                   bg=BG, fg=TEXT, relief="flat", cursor="hand2",
                                   activebackground=BG2, padx=10,
                                   command=self._install_ai_tools)
        # self.setup_btn will be packed by _check_deps if needed

        tk.Label(sb, text="yt-dlp + Real-ESRGAN",
                 font=("Segoe UI", 9), fg="#333", bg=BG3, padx=16).pack(side="right")

        # --- FIRST RUN CHECK ---
        self.after(1000, self._auto_setup)

    # ─────────────────────────────────────────
    def _hover(self, w, n, h):
        w.bind("<Enter>", lambda e: w.config(bg=h))
        w.bind("<Leave>", lambda e: w.config(bg=n))

    def _clear_ph(self, e):
        ph = "Paste links here (TikTok, YouTube, etc.)..."
        if self.url_entry.get() == ph:
            self.url_entry.delete(0, "end")
            self.url_entry.config(fg=TEXT)

    def _restore_ph(self, e):
        if not self.url_entry.get():
            ph = "Paste links here (TikTok, YouTube, etc.)..."
            self.url_entry.insert(0, ph)
            self.url_entry.config(fg=SUBTEXT)

    def _paste(self):
        try:
            t = self.clipboard_get()
            self.url_entry.delete(0, "end")
            self.url_entry.config(fg=TEXT)
            self.url_entry.insert(0, t.strip())
        except: pass

    def _choose_folder(self):
        f = filedialog.askdirectory(initialdir=self.save_path.get())
        if f: self.save_path.set(f)

    def _choose_esrgan(self):
        f = filedialog.askopenfilename(
            title="Select realesrgan-ncnn-vulkan.exe",
            filetypes=[("Executable", "*.exe"), ("All", "*.*")])
        if f:
            self.esrgan_entry.delete(0, "end")
            self.esrgan_entry.insert(0, f)

    def _on_quality(self, e=None):
        q = self.quality_var.get()
        if "Audio" in q:
            self.no_watermark.set(False)
            self.wm_chk.config(state="disabled")
            self.u_cb.config(state="disabled")
            self.upscale_var.set("❌ No Upscale")
            self.info_lbl1.config(text="")
        else:
            self.wm_chk.config(state="normal")
            self.u_cb.config(state="readonly")

    def _on_upscale(self, e=None):
        scale = UPSCALE_OPTIONS[self.upscale_var.get()]
        if scale:
            self.info_lbl1.config(
                text=f"⚠️  Requires: Real-ESRGAN + ffmpeg  |  Processing takes time (frame by frame)",
                fg=WARN)
            self.dl_btn.config(text="⬇   DOWNLOAD + UPSCALE")
        else:
            self.info_lbl1.config(text="")
            self.dl_btn.config(text="⬇   DOWNLOAD")

    def _add_url(self):
        url = self.url_entry.get().strip()
        ph = "Paste links here (TikTok, YouTube, etc.)..."
        if not url or url == ph: return
        
        if url not in self.url_queue:
            self.url_queue.append(url)
            self.queue_listbox.insert("end", url)
            self.url_entry.delete(0, "end")
            self._set_status(f"Added! ({len(self.url_queue)} links in queue)", ACCENT, tab=1)
            # Fetch metadata in background
            threading.Thread(target=self._fetch_url_metadata, args=(url,), daemon=True).start()
        else:
            self._set_status("This link is already in queue", WARN, tab=1)

    def _on_queue_select(self, event):
        selected = self.queue_listbox.curselection()
        if not selected: return
        url = self.url_queue[selected[0]]
        
        if url in self.url_metadata_cache:
            self._update_quality_options(self.url_metadata_cache[url])
        else:
            # Re-fetch if missing
            self.q_cb.config(values=list(QUALITY_OPTIONS.keys()))
            threading.Thread(target=self._fetch_url_metadata, args=(url,), daemon=True).start()

    def _fetch_url_metadata(self, url):
        ytdlp = find_tool("yt-dlp")
        if not ytdlp: return
        
        try:
            cmd = [ytdlp, "--quiet", "--no-warnings", "--dump-json", url]
            si = None
            if os.name == 'nt':
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', startupinfo=si)
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                self.url_metadata_cache[url] = info
                self.after(0, lambda: self._update_quality_options(info, url))
        except: pass

    def _update_quality_options(self, info, url=None):
        # Only update if the URL is still selected
        current_sel = self.queue_listbox.curselection()
        if url and (not current_sel or self.url_queue[current_sel[0]] != url):
             return

        formats = info.get("formats", [])
        heights = set()
        for f in formats:
            h = f.get("height")
            if h and h >= 144: heights.add(h)
        
        sorted_h = sorted(list(heights), reverse=True)
        new_vals = ["Auto (Best Available)"]
        for h in sorted_h:
            label = f"{h}p"
            if h >= 2160: label = f"Ultra HD ({h}p)"
            elif h >= 1440: label = f"QHD ({h}p)"
            elif h >= 1080: label = f"Full HD ({h}p)"
            new_vals.append(label)
        
        new_vals.append("🎵 Audio Only (MP3)")
        
        # Update ComboBox
        self.q_cb.config(values=new_vals)
        self._set_status("Quality options updated for this video ✓", SUCCESS, tab=1)

    def _remove_url(self):
        selected = self.queue_listbox.curselection()
        if not selected: return
        for idx in reversed(selected):
            self.url_queue.pop(idx)
            self.queue_listbox.delete(idx)
        self._set_status(f"Removed ({len(self.url_queue)} items remaining)", WARN, tab=1)

    def _launch_upscaler(self):
        try:
            # Check if running as bundle or script
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Upscale.py")
            if not os.path.exists(script_path):
                # Fallback for frozen EXE
                script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Upscale_Portable.exe")
            
            import sys
            if script_path.endswith(".py"):
                subprocess.Popen([sys.executable, script_path])
            else:
                subprocess.Popen([script_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not launch the Upscale tool: {e}")

    def _show_image_gallery(self, urls, save_dir):
        gallery = ImageGallery(self, urls, save_dir)
        gallery.focus_set()
        # Reset downloading state since gallery handles it
        self.is_dl_active = False
        self.dl_btn.config(text="⬇   DOWNLOAD", state="normal", bg=ACCENT)

    def _show_help(self):
        help_text = (
            "📖 How to use TikTok Downloader:\n\n"
            "1. Copy Link: Copy any TikTok video or photo link.\n"
            "2. Add Link: Paste into the box and click 'Add' (or press Enter).\n"
            "3. Queue Many: You can add multiple links to download them all at once.\n"
            "4. Settings: Select Quality and AI Upscale level (2x or 4x).\n"
            "5. Start: Click 'DOWNLOAD + UPSCALE' and wait for completion.\n\n"
            "💡 Shortcut: Press Alt + Q anytime to show this guide."
        )
        messagebox.showinfo("Guide", help_text)

    def _add_local_files(self):
        files = filedialog.askopenfilenames(
            title="Select Media Files",
            filetypes=[("Media Files", "*.mp4 *.mov *.mkv *.avi *.jpg *.jpeg *.png *.webp"),
                       ("Videos", "*.mp4 *.mov *.mkv *.avi"),
                       ("Images", "*.jpg *.jpeg *.png *.webp")]
        )
        if files:
            for f in files:
                if f not in self.local_files:
                    self.local_files.append(f)
                    tag = "IMG" if self._is_image(f) else "VID"
                    self.local_listbox.insert("end", f" [{tag}] {os.path.basename(f)}")
            self._set_status(f"Added {len(files)} files to local queue", ACCENT2, tab=2)

    def _clear_local_list(self):
        self.local_files = []
        self.local_listbox.delete(0, "end")
        self._set_status("Local queue cleared", WARN, tab=2)

    def _is_image(self, path):
         ext = os.path.splitext(path)[1].lower()
         return ext in ['.jpg', '.jpeg', '.png', '.webp']

    def _start_local_batch(self):
        if self.is_up_active: return
        if not self.local_files:
            messagebox.showwarning("Warning", "Please add files to the local queue first.")
            return
            
        self.is_up_active = True
        self.local_btn.config(text="⏳ PROCESSING...", state="disabled", bg="#444")
        self.up_progress_var.set(0)
        
        threading.Thread(target=self._process_local_queue, daemon=True).start()

    def _cancel_process(self, task_type=None):
        """Cancel processes with clean termination of child processes"""
        target_proc_attr = "current_proc"
        if task_type == "dl":
            self.is_dl_active = False
            self._set_status("Cancelling Download...", WARN, tab=1)
            target_proc_attr = "dl_proc"
        elif task_type == "up":
            self.is_up_active = False
            self._set_status("Cancelling Upscale...", WARN, tab=2)
            target_proc_attr = "up_proc"
        else:
            self.is_dl_active = False
            self.is_up_active = False

        proc = getattr(self, target_proc_attr, None)
        if proc:
            try:
                import psutil
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    try: child.terminate()
                    except: pass
                proc.terminate()
            except:
                try: proc.terminate()
                except:
                    try: proc.kill()
                    except: pass
            setattr(self, target_proc_attr, None)
        
        self.after(0, lambda: self._on_batch_complete())

    def _process_local_queue(self):
        total = len(self.local_files)
        success_count = 0
        
        realesrgan = find_tool("realesrgan-ncnn-vulkan")
        ffmpeg = find_tool("ffmpeg")
        
        if not realesrgan:
            self.after(0, lambda: messagebox.showerror("Error", "Real-ESRGAN not found! Please install AI tools."))
            self._finish_local_batch(0, total)
            return

        processing_list = list(self.local_files)
        for i, path in enumerate(processing_list):
            if not self.is_up_active: break # Allow stop
            
            filename = os.path.basename(path)
            try:
                self.after(0, lambda idx=i: self.local_listbox.selection_clear(0, "end"))
                self.after(0, lambda idx=i: self.local_listbox.selection_set(idx))
                self.after(0, lambda idx=i: self.local_listbox.see(idx))
                
                self._set_status(f"Processing ({i+1}/{total}): {filename}", ACCENT2, tab=2)
                
                scale = int(self.scale_var2.get().replace("x", ""))
                mode = self.mode_var2.get()
                
                if self._is_image(path):
                    ext = os.path.splitext(path)[1]
                    output_path = os.path.join(self.save_path.get(), os.path.splitext(filename)[0] + f"_x{scale}{ext}")
                    self._upscale_image_standalone(realesrgan, path, output_path, scale, mode)
                else:
                    if not ffmpeg:
                         self._set_status(f"Skipping {filename} (FFmpeg missing)", WARN, tab=2)
                         continue
                    output_path = os.path.join(self.save_path.get(), os.path.splitext(filename)[0] + f"_x{scale}.mp4")
                    self._upscale_video_standalone(ffmpeg, find_tool("ffprobe"), realesrgan, path, output_path, scale)
                
                success_count += 1
                # Remove from original list and UI
                def update_list(p=path):
                    if p in self.local_files:
                        idx = self.local_files.index(p)
                        self.local_files.remove(p)
                        self.local_listbox.delete(idx)
                self.after(0, update_list)
                
            except Exception as e:
                print(f"Error processing {path}: {e}")
                self._set_status(f"Failed: {filename} ({str(e)[:40]}...)", ACCENT, tab=2)
        self._finish_local_batch(success_count, total)

    def _finish_local_batch(self, success, total):
        self.is_up_active = False
        self.after(0, lambda: self.local_btn.config(text="🚀  START BATCH UPSCALE", state="normal", bg=ACCENT2))
        self.after(0, lambda: self.up_progress_var.set(100 if success > 0 else 0))
        failed = total - success
        if total > 0:
            self._set_status(f"Finished! Success: {success}, Failed: {failed}", SUCCESS if failed==0 else WARN, tab=2)
            messagebox.showinfo("Batch Complete", f"Processed {total} files.\n\n✅ Success: {success}, Failed: {failed}")

    def _upscale_video_standalone(self, ffmpeg, ffprobe, realesrgan, input_p, output_p, scale):
        def status_cb(msg, col, p=None):
            self.after(0, lambda: self._set_status(msg, col, tab=2))
            self.after(0, lambda: self.info_lbl2.config(text=msg))
            if p is not None: self.up_progress_var.set(p)
        
        esr_exe = self.esrgan_entry.get().strip() or realesrgan
        self._execute_upscale_core(input_p, output_p, scale, esr_exe, ffmpeg, ffprobe, status_cb, active_check=lambda: self.is_up_active)

    def _upscale_image_standalone(self, realesrgan, input_path, output_path, scale, mode="Best"):
        si = None
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # --- Resolution Check ---
        t_val, j_val = self._resolve_perf_settings()
        try:
            from PIL import Image
            with Image.open(input_path) as img:
                w, h = img.size
                if w >= 3840 or h >= 3840:
                    t_val = min(t_val, 100)
                    if t_val == 0: t_val = 100
        except: pass

        # --- Safe Path Handling ---
        is_unicode = any(ord(c) > 127 for c in input_path) or any(ord(c) > 127 for c in output_path)
        working_input = input_path
        working_output = output_path
        temp_dir = None
        
        if is_unicode:
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="esr_img_")
            working_input = os.path.join(temp_dir, "input" + os.path.splitext(input_path)[1])
            working_output = os.path.join(temp_dir, "output" + os.path.splitext(output_path)[1])
            shutil.copy2(input_path, working_input)

        model = "realesrgan-x4plus"
        if "Anime" in mode or "Fast" in mode:
            model = "realesr-animevideov3"
            
        cmd = [
            realesrgan,
            "-i", os.path.normpath(working_input),
            "-o", os.path.normpath(working_output),
            "-n", model,
            "-s", str(scale),
            "-f", (os.path.splitext(output_path)[1][1:] or "jpg").lower(),
            "-t", str(t_val),
            "-j", j_val
        ]
        
        try:
            subprocess.run(cmd, startupinfo=si, check=True, cwd=os.path.dirname(os.path.abspath(realesrgan)))
            if is_unicode:
                shutil.copy2(working_output, output_path)
        finally:
            if temp_dir: shutil.rmtree(temp_dir, ignore_errors=True)

    def _resolve_perf_settings(self):
        choice = self.perf_var.get()
        if "Auto" in choice:
            profile = self.detected_profile
        elif "Ice" in choice:
            profile = "Ice"
        elif "Balanced" in choice:
            profile = "Balanced"
        elif "Turbo" in choice:
            profile = "Turbo"
        else:
            profile = "Extreme"
            
        settings = {
            "Ice":      (100, "1:2:2"),
            "Balanced": (200, "2:2:2"),
            "Turbo":    (256, "2:4:2"),
            "Extreme":  (400, "4:8:4")
        }
        return settings.get(profile, (100, "1:2:2"))

    def _auto_tune_hardware(self):
        gpu_name = "Generic/Integrated"
        try:
            res = subprocess.run(["wmic", "path", "win32_VideoController", "get", "name"], capture_output=True, text=True)
            lines = [l.strip() for l in res.stdout.split('\n') if l.strip() and 'Name' not in l]
            if lines: gpu_name = lines[0]
        except: pass
        
        self.detected_hw = gpu_name
        self.detected_profile = "Ice"
        
        ghw = gpu_name.upper()
        if any(x in ghw for x in ["RTX", "GTX", "NVIDIA", "AMD", "RADEON"]):
            self.detected_profile = "Balanced"
            if any(x in ghw for x in ["RTX 30", "RTX 40", "RTX 50", "6800", "6900", "7800", "7900"]):
                self.detected_profile = "Turbo"
                
        self.after(0, lambda: self.hw_lbl.config(text=f"Detected: {gpu_name} ({self.detected_profile})"))

    def _safe_run(self, cmd, active_check, proc_attr=None, **kwargs):
        """Run subprocess and track it for cancellation"""
        if not active_check(): return None
        
        si = None
        if os.name == 'nt':
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        kwargs['startupinfo'] = si
        
        # subprocess.Popen doesn't support capture_output. Convert if needed.
        if kwargs.pop('capture_output', False):
            kwargs['stdout'] = subprocess.PIPE
            kwargs['stderr'] = subprocess.PIPE
            
        proc = subprocess.Popen(cmd, **kwargs)
        if proc_attr:
            setattr(self, proc_attr, proc)
        else:
            self.current_proc = proc
        
        # Use communicate() if pipes are involved to avoid deadlocks
        if kwargs.get('stdout') == subprocess.PIPE:
            proc.communicate()
        else:
            proc.wait()
            
        if proc_attr and getattr(self, proc_attr) == proc:
            setattr(self, proc_attr, None)
            
        return proc

    def _execute_upscale_core(self, input_path, output_path, scale, esrgan_exe, ffmpeg, ffprobe, status_cb, active_check=None):
        if active_check is None: active_check = lambda: True
        t_val, j_val = self._resolve_perf_settings()
        input_path = os.path.abspath(input_path)
        base, ext = os.path.splitext(input_path)
        
        # Check resolution for dynamic tile size
        width = 1920 # default
        if ffprobe:
            try:
                p = subprocess.run([ffprobe, "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "default=noprint_wrappers=1:nokey=1", input_path], capture_output=True, text=True)
                if p.stdout.strip(): width = int(p.stdout.strip())
            except: pass
        
        # Guard for 4K+ - force smaller tile size
        if width >= 3840:
             t_val = min(t_val, 100)
             if t_val == 0: t_val = 100 # don't use auto for 4K

        # --- Safe Path Handling ---
        # If path contains non-ASCII, Real-ESRGAN might fail. Use a temp location if needed.
        is_unicode = any(ord(c) > 127 for c in input_path)
        temp_dir = None
        working_input = input_path
        
        if is_unicode:
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="pro_media_")
            working_input = os.path.join(temp_dir, f"input{ext}")
            shutil.copy2(input_path, working_input)
            process_base = os.path.join(temp_dir, "process")
        else:
            process_base = base
            
        process_dir  = os.path.normpath(process_base + f"_process_{scale}x")
        frames_dir   = os.path.abspath(os.path.join(process_dir, "original_frames"))
        upscaled_dir = os.path.abspath(os.path.join(process_dir, f"upscaled_{scale}x_frames"))
        if not output_path:
             output_path  = os.path.abspath(base + f"_x{scale}.mp4")
        else:
             output_path = os.path.abspath(output_path)
        audio_path   = os.path.abspath(os.path.join(process_dir, "audio.aac"))

        shutil.rmtree(process_dir, ignore_errors=True)
        os.makedirs(process_dir,  exist_ok=True)
        os.makedirs(frames_dir,   exist_ok=True)
        os.makedirs(upscaled_dir, exist_ok=True)

        try:
            # Get Duration Check Movie Mode
            duration = 0
            if ffprobe:
                try:
                    p = subprocess.run([ffprobe, "-v", "quiet", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", working_input], capture_output=True, text=True)
                    if p.stdout.strip(): duration = float(p.stdout.strip())
                except: pass

            MOVIE_MODE = self.use_movie_mode.get() 
            p_attr = "up_proc" if "Upscale" in self.up_status_var.get() else "dl_proc"

            # FPS check
            fps = "30"
            if ffprobe:
                try:
                    p = subprocess.run([ffprobe, "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "default=noprint_wrappers=1:nokey=1", working_input], capture_output=True, text=True)
                    fps_raw = p.stdout.strip()
                    if "/" in fps_raw:
                        num, den = map(float, fps_raw.split("/"))
                        fps = str(num / den) if den > 0 else "30"
                    elif fps_raw: fps = fps_raw
                except: pass

            status_cb("🎵 Extracting audio...", WARN)
            self._safe_run([ffmpeg, "-y", "-i", working_input, "-vn", "-c:a", "aac", "-b:a", "192k", audio_path], active_check, proc_attr=p_attr, capture_output=True)
            if not active_check(): return

            if MOVIE_MODE:
                status_cb("🎬 Movie Mode Activated. Slicing video...", WARN)
                chunks_dir = os.path.join(process_dir, "chunks")
                os.makedirs(chunks_dir, exist_ok=True)
                
                self._safe_run([ffmpeg, "-y", "-i", working_input, "-c", "copy", "-map", "0:v", "-f", "segment", "-segment_time", "180", "-reset_timestamps", "1", os.path.join(chunks_dir, "chunk%04d.mp4")], active_check, proc_attr=p_attr, capture_output=True)
                if not active_check(): return

                chunk_files = sorted([f for f in os.listdir(chunks_dir) if f.startswith("chunk") and f.endswith(".mp4")])
                total_chunks = len(chunk_files)
                
                if total_chunks == 0:
                    raise Exception("Movie Mode Error: Splitting failed.")

                concat_list_path = os.path.join(process_dir, "concat.txt")
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for chunk in chunk_files:
                        f.write(f"file '{os.path.join(chunks_dir, 'up_' + chunk).replace(os.sep, '/')}'\n")

                for i, chunk in enumerate(chunk_files):
                    if not active_check(): return
                    chunk_path = os.path.join(chunks_dir, chunk)
                    chunk_up   = os.path.join(chunks_dir, 'up_' + chunk)
                    
                    shutil.rmtree(frames_dir, ignore_errors=True)
                    shutil.rmtree(upscaled_dir, ignore_errors=True)
                    os.makedirs(frames_dir, exist_ok=True)
                    os.makedirs(upscaled_dir, exist_ok=True)
                    
                    status_cb(f"🎬 Chunk {i+1}/{total_chunks}: Extracting...", WARN)
                    self._safe_run([ffmpeg, "-y", "-i", chunk_path, "-q:v", "2", "-vf", f"fps={fps}", os.path.join(frames_dir, "frame%08d.jpg")], active_check, capture_output=True)
                    if not active_check(): return
                    
                    status_cb(f"🔺 Chunk {i+1}/{total_chunks}: Upscaling...", ACCENT)
                    esr_cmd = [esrgan_exe, "-i", frames_dir, "-o", upscaled_dir, "-n", "realesr-animevideov3", "-s", str(scale), "-t", str(t_val), "-f", "jpg", "-j", j_val, "-g", "0"]
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    proc = subprocess.Popen(esr_cmd, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True, cwd=os.path.dirname(os.path.abspath(esrgan_exe)), startupinfo=si)
                    setattr(self, p_attr, proc)

                    last_error_log = []
                    for line in proc.stderr:
                        if not active_check(): break
                        clean_line = line.strip()
                        if clean_line: last_error_log.append(clean_line)
                        if len(last_error_log) > 5: last_error_log.pop(0)

                        if "%" in line:
                            try:
                                upscale_pct = float(line.strip().split("%")[0].strip())
                                base_prog = (i / total_chunks) * 100
                                chunk_prog = (upscale_pct / 100) * (100 / total_chunks)
                                display_pct = base_prog + chunk_prog
                                status_cb(f"🎬 Movie Mode... {display_pct:.1f}%", ACCENT, p=display_pct)
                            except: pass

                    if not active_check():
                        if proc: proc.kill()
                        return

                    proc.wait()
                    if getattr(self, p_attr) == proc: setattr(self, p_attr, None)
                    if proc.returncode != 0: 
                        err_msg = "\n".join(last_error_log)
                        raise Exception(f"Real-ESRGAN chunk error:\n{err_msg}")

                    status_cb(f"🎬 Chunk {i+1}/{total_chunks}: Encoding...", WARN)
                    merge_args = [ffmpeg, "-y", "-loglevel", "error", "-framerate", fps, "-start_number", "1", "-i", os.path.join(upscaled_dir, "frame%08d.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast", chunk_up]
                    self._safe_run(merge_args, active_check)
                    
                    shutil.rmtree(frames_dir, ignore_errors=True)
                    shutil.rmtree(upscaled_dir, ignore_errors=True)
                    try: os.remove(chunk_path)
                    except: pass
                
                status_cb(f"🍿 Merging Movie Chunks...", WARN)
                concat_args = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-i", audio_path, "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", output_path]
                self._safe_run(concat_args, active_check)
                
            else:
                # STANDARD MODE
                status_cb(f"🖼️ Extracting frames ({fps} FPS)...", WARN)
                self._safe_run([ffmpeg, "-y", "-i", working_input, "-q:v", "2", "-vf", f"fps={fps}", os.path.join(frames_dir, "frame%08d.jpg")], active_check, capture_output=True)
                
                if not active_check(): return

                status_cb(f"🔺 AI Upscaling {scale}x...", ACCENT)
                esr_cmd = [esrgan_exe, "-i", frames_dir, "-o", upscaled_dir, "-n", "realesr-animevideov3", "-s", str(scale), "-t", str(t_val), "-f", "jpg", "-j", j_val, "-g", "0"]
                
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                proc = subprocess.Popen(esr_cmd, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True, cwd=os.path.dirname(os.path.abspath(esrgan_exe)), startupinfo=si)
                setattr(self, p_attr, proc)

                last_error_log = []
                for line in proc.stderr:
                    if not active_check(): break
                    clean_line = line.strip()
                    if clean_line: last_error_log.append(clean_line)
                    if len(last_error_log) > 5: last_error_log.pop(0)

                    if "%" in line:
                        try:
                            upscale_pct = float(line.strip().split("%")[0].strip())
                            status_cb(f"🔺 Upscaling... {upscale_pct:.1f}%", ACCENT, p=upscale_pct)
                        except: pass
                
                if not active_check():
                    if proc: proc.kill()
                    return

                proc.wait()
                if getattr(self, p_attr) == proc: setattr(self, p_attr, None)
                
                if proc.returncode != 0: 
                    err_msg = "\n".join(last_error_log)
                    raise Exception(f"Real-ESRGAN failed:\n{err_msg}")

                status_cb(f"🎬 Merging video {fps} FPS...", WARN)
                merge_args = [ffmpeg, "-y", "-loglevel", "error", "-framerate", fps, "-start_number", "1", "-i", os.path.join(upscaled_dir, "frame%08d.jpg"), "-i", audio_path, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "fast", "-c:a", "aac", "-shortest", output_path]
                self._safe_run(merge_args, active_check)

            shutil.rmtree(process_dir, ignore_errors=True)
            if temp_dir: shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            shutil.rmtree(process_dir, ignore_errors=True)
            if temp_dir: shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    def _show_image_gallery(self, urls, save_dir):
        gallery = ImageGallery(self, urls, save_dir)
        gallery.lift()
        gallery.focus_force()

    def _set_status(self, msg, color=None, tab=1):
        if tab == 1:
            self.dl_status_var.set(msg)
            if color: self.dl_status_lbl.config(fg=color)
        else:
            self.up_status_var.set(msg)
            if color: self.up_status_lbl.config(fg=color)

    def _start(self):
        if self.is_dl_active: return
        current_entry = self.url_entry.get().strip()
        ph = "Paste links here (TikTok, YouTube, etc.)..."
        if current_entry and current_entry != ph:
            self._add_url()
        if not self.url_queue:
            messagebox.showwarning("Warning", "Please enter a valid video URL")
            return
        self.is_dl_active = True
        self.dl_btn.config(text="⏳ Working...", state="disabled", bg="#444")
        self.cancel_btn1.pack(side="right", padx=(10, 0), fill="y")
        self.dl_progress_var.set(0)
        self.info_lbl1.config(text="")
        threading.Thread(target=self._process_queue, daemon=True).start()

    def _process_queue(self):
        if not self.url_queue:
            self.after(0, self._on_batch_complete)
            return
        url = self.url_queue[0]
        self._set_status(f"Starting download... ({len(self.url_queue)} in queue)", WARN, tab=1)
        self._download(url)

    def _on_batch_complete(self):
        self.is_dl_active = False
        self.after(0, lambda: self.dl_btn.config(text="⬇ DOWNLOAD + UPSCALE", state="normal", bg=ACCENT))
        self.after(0, lambda: self.cancel_btn1.pack_forget())
        
        if "Cancelled" not in self.dl_status_var.get():
            self.dl_progress_var.set(100)
            self._set_status("All queued items completed!", SUCCESS, tab=1)
            messagebox.showinfo("Success!", "All queued items have been processed!")
        else:
            self.dl_progress_var.set(0)

    def _download(self, url):
        save_dir = self.save_path.get()
        no_wm    = self.no_watermark.get()
        quality  = self.quality_var.get()
        
        max_h = None
        if "Audio" in quality:
            max_h = "audio"
        elif "p" in quality:
            import re
            match = re.search(r'(\d+)p', quality)
            if match:
                max_h = match.group(1)
        
        is_audio = (max_h == "audio")
        scale    = UPSCALE_OPTIONS.get(self.upscale_var.get())

        ytdlp_exe = find_tool("yt-dlp")
        if not ytdlp_exe:
            self.after(0, lambda: self._on_error("yt-dlp.exe not found"))
            return

        fmt = build_format_chain(None if is_audio else max_h, no_wm and not is_audio)
        
        # 📸 PRO PHOTO DETECTION (TikWM + SnapTik Logic)
        photo_urls = []
        if "tiktok.com" in url:
            # Try TikWM API first (Very reliable for photo posts)
            try:
                tikwm_url = f"https://www.tikwm.com/api/?url={url}"
                tik_resp = requests.get(tikwm_url, timeout=10)
                if tik_resp.status_code == 200:
                    tik_json = tik_resp.json()
                    if tik_json.get("code") == 0:
                        photo_urls = tik_json.get("data", {}).get("images", [])
            except: pass

            # Fallback to local scraper
            if not photo_urls:
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        pattern = r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>'
                        match = re.search(pattern, resp.text) or re.search(r'<script id="SIGI_STATE" type="application/json">(.*?)</script>', resp.text)
                        if match:
                            data = json.loads(match.group(1))
                            if "__DEFAULT_SCOPE__" in data:
                                item = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
                                if "imagePost" in item:
                                    photo_urls = [img.get("display_image", {}).get("url_list", [None])[0] for img in item["imagePost"]["images"]]
                            elif "ItemModule" in data:
                                item_id = list(data["ItemModule"].keys())[0]
                                item = data["ItemModule"][item_id]
                                if "imagePost" in item:
                                    photo_urls = [img.get("display_image", {}).get("url_list", [None])[0] for img in item["imagePost"]["images"]]
                except: pass

        # Fallback to yt-dlp metadata
        try:
            cmd = [ytdlp_exe, "--quiet", "--no-warnings", "--dump-json", url]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                
                # 1. Manual scan for photo URLs in entries
                if not photo_urls:
                    entries = info.get("entries", [])
                    if entries:
                        for e in entries:
                            u = e.get("url")
                            if u and any(x in u.lower() for x in ['.jpg', '.jpeg', '.png', '.webp', 'tiktokcdn']):
                                photo_urls.append(u)
                    elif info.get("requested_downloads"):
                        for d in info.get("requested_downloads"):
                            u = d.get("url")
                            if u: photo_urls.append(u)
                
                # 3. Fallback: check all thumbnails for high-res sign pattern
                if not photo_urls and ("photo" in info.get("webpage_url", "").lower() or info.get("extractor") == "TikTok"):
                    thumbs = info.get("thumbnails", [])
                    if len(thumbs) > 2 and info.get("duration", 0) == 0:
                        for t in thumbs:
                            u = t.get("url")
                            if u and "p16" in u: # TikTok high-res pattern
                                photo_urls.append(u)

                if photo_urls:
                    photo_urls = [u for u in photo_urls if u]
                    self.after(0, lambda: self._set_status(f"📸 Detected {len(photo_urls)} Images!", SUCCESS))
                    self.after(0, lambda: self._show_image_gallery(photo_urls, save_dir))
                    # Clear queue/move on so main UI doesn't hang
                    self.after(500, self._on_success)
                    return

                t, up, dur = info.get("title",""), info.get("uploader",""), info.get("duration",0)
                msg = f"🎬 {t} |👤 {up} |⏱ {dur}s"
                self.after(0, lambda: self.info_lbl1.config(text=msg))
        except: pass

        # Download
        dl_cmd = [ytdlp_exe, url, "--format", fmt, "--merge-output-format", "mp4", "--output", os.path.join(save_dir, "%(title)s [%(uploader)s] [%(id)s].%(ext)s"), "--newline"]
        if is_audio: dl_cmd += ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "320"]

        try:
            self.dl_proc = subprocess.Popen(dl_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
            for line in self.dl_proc.stdout:
                if not self.is_dl_active: break
                if "[download]" in line and "%" in line:
                    try:
                        pct = float(line.split("%")[0].split()[-1])
                        self.dl_progress_var.set(pct * (0.5 if scale else 1))
                        self._set_status(f"⬇ Downloading... {pct}%", ACCENT, tab=1)
                    except: pass
            
            if not self.is_dl_active:
                if self.dl_proc: self.dl_proc.kill()
                return

            self.dl_proc.wait()
            self.dl_proc = None
            
            # Robust file detection (avoid glob bracket issues)
            import time
            valid_exts = [".mp3"] if is_audio else [".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv"]
            
            candidate_files = []
            for f in os.listdir(save_dir):
                if any(f.lower().endswith(ex) for ex in valid_exts):
                    full_p = os.path.join(save_dir, f)
                    # Only pick files created/modified in the last 5 minutes to avoid picking old downloads
                    if time.time() - os.path.getmtime(full_p) < 300:
                        candidate_files.append(full_p)
            
            if not candidate_files:
                # Fallback: check if any file exists at all regardless of time (for slow disks)
                for f in os.listdir(save_dir):
                    if any(f.lower().endswith(ex) for ex in valid_exts):
                        candidate_files.append(os.path.join(save_dir, f))

            if not candidate_files:
                raise Exception("Download failed: No output file found in the save directory. yt-dlp may have encountered an error or the file format is unsupported.")
            
            downloaded = max(candidate_files, key=os.path.getctime)

            if scale and not is_audio:
                esr_exe = self.esrgan_entry.get().strip() or find_tool("realesrgan-ncnn-vulkan")
                ffmpeg = find_tool("ffmpeg")
                ffprobe = find_tool("ffprobe")
                def status_cb(msg, col, p=None):
                    self.after(0, lambda: self._set_status(msg, col, tab=1))
                    self.after(0, lambda: self.info_lbl1.config(text=msg))
                    if p is not None: self.dl_progress_var.set(50 + (p * 0.5))
                self._execute_upscale_core(downloaded, None, scale, esr_exe, ffmpeg, ffprobe, status_cb, active_check=lambda: self.is_dl_active)
                self.after(0, lambda: self._on_success(downloaded, upscaled=True))
            else:
                self.after(0, lambda: self._on_success(downloaded, upscaled=False))
        except Exception as ex:
            self.after(0, lambda err=str(ex): self._on_error(err))

    def _on_success(self, path=None, upscaled=False):
        if self.url_queue:
            self.url_queue.pop(0)
            self.after(0, lambda: self.queue_listbox.delete(0))
        label = "✅ Success (Upscaled)" if upscaled else "✅ Success"
        self._set_status(label, SUCCESS, tab=1)
        if self.url_queue:
            self.after(1000, lambda: threading.Thread(target=self._process_queue, daemon=True).start())
        else:
            self.after(0, self._on_batch_complete)

    def _install_ai_tools(self):
        if self.is_dl_active: return
        self.is_dl_active = True
        self._set_status("Auto-Installing missing tools...", WARN, tab=1)
        threading.Thread(target=self._setup_all_thread, daemon=True).start()

    def _setup_all_thread(self, force=False):
        bin_dir = os.path.abspath("bin")
        os.makedirs(bin_dir, exist_ok=True)
        zip_path = os.path.join(bin_dir, "realesrgan.zip")
        ytdlp_path = os.path.join(bin_dir, "yt-dlp.exe")
        lama_path = os.path.join(bin_dir, "big-lama.pt")
        
        def reporthook(name):
            def _hook(bn, bs, ts):
                if ts > 0: self.dl_progress_var.set((bn * bs * 100) / ts)
                self._set_status(f"Downloading {name}...", ACCENT2, tab=1)
            return _hook

        try:
            if force or not check_ytdlp():
                url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
                urllib.request.urlretrieve(url, ytdlp_path, reporthook("yt-dlp"))
            
            if force or not check_ffmpeg():
                self._set_status("Downloading FFmpeg...", WARN, tab=1)
                ffmpeg_url = "https://github.com/GyanD/codexffmpeg/releases/download/6.1.1/ffmpeg-6.1.1-essentials_build.zip"
                ffmpeg_zip = os.path.join(bin_dir, "ffmpeg.zip")
                urllib.request.urlretrieve(ffmpeg_url, ffmpeg_zip, reporthook("FFmpeg"))
                with zipfile.ZipFile(ffmpeg_zip, 'r') as z:
                    for f in z.namelist():
                        if f.endswith('ffmpeg.exe') or f.endswith('ffprobe.exe'):
                            with open(os.path.join(bin_dir, os.path.basename(f)), 'wb') as out:
                                out.write(z.read(f))
                if os.path.exists(ffmpeg_zip): os.remove(ffmpeg_zip)

            if force or not check_realesrgan():
                urllib.request.urlretrieve(REALESRGAN_URL, zip_path, reporthook("AI Tools"))
                self._set_status("Extracting...", WARN, tab=1)
                with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(bin_dir)
                if os.path.exists(zip_path): os.remove(zip_path)
                
            if force or not os.path.exists(lama_path):
                LAMA_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
                urllib.request.urlretrieve(LAMA_URL, lama_path, reporthook("big-lama.pt"))
            
            self.after(0, self._check_deps)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Setup failed: {e}"))
        finally:
            self.is_dl_active = False
            self.after(0, lambda: self.dl_progress_var.set(0))

    def _run_system_repair(self):
        if self.is_dl_active: return
        self.is_dl_active = True
        
        top = tk.Toplevel(self)
        top.title("System Repair in Progress")
        top.geometry("600x400")
        top.config(bg=BG2)
        top.transient(self)
        top.grab_set()
        
        tk.Label(top, text="⚙️", font=("Segoe UI Emoji", 30), bg=BG2, fg=ACCENT).pack(pady=(15, 5))
        lbl = tk.Label(top, text="Initializing System Repair...", font=("Segoe UI", 10), bg=BG2, fg=TEXT)
        lbl.pack()
        
        log_txt = tk.Text(top, height=12, bg=BG3, fg=SUBTEXT, font=("Consolas", 8), bd=0, padx=10, pady=10)
        log_txt.pack(fill="both", expand=True, padx=20, pady=15)
        
        # Helper to safely update GUI even if window was closed
        def safe_log(text):
            try:
                log_txt.insert("end", text)
                log_txt.see("end")
            except tk.TclError: pass
            
        def safe_lbl(text, fg=TEXT):
            try: lbl.config(text=text, fg=fg)
            except tk.TclError: pass
            
        threading.Thread(target=self._repair_thread, args=(top, safe_lbl, safe_log), daemon=True).start()

    def _repair_thread(self, top, safe_lbl, safe_log):
        try:
            self.after(0, lambda: safe_lbl("Repairing AI Binaries..."))
            self._setup_all_thread(force=True)
            
            self.after(0, lambda: safe_lbl("Installing Python Libraries (May take 5+ mins for torch!)..."))
            env = os.environ.copy()
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            
            cf = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            
            def stream_pip(cmd):
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=cf, env=env)
                for line in iter(proc.stdout.readline, ''):
                    self.after(0, lambda l=line: safe_log(l))
                proc.wait()
            
            cmd1 = [sys.executable, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu118"]
            stream_pip(cmd1)
            
            self.after(0, lambda: safe_lbl("Installing Whisper, Translator, OpenCV, and more..."))
            auto_libs = ["openai-whisper", "deep-translator", "simple-lama-inpainting", "opencv-python", "psutil", "pillow", "tiktoken", "tqdm"]
            cmd2 = [sys.executable, "-m", "pip", "install"] + auto_libs
            stream_pip(cmd2)
            
            self.after(0, lambda: safe_lbl("Repair Complete! Restarting...", fg=SUCCESS))
            time.sleep(2)
            # Safe Restart Protocol
            subprocess.Popen([sys.executable] + sys.argv, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            os._exit(0)
        except Exception as e:
            self.after(0, lambda: safe_lbl(f"Error: {e}", fg=WARN))
            self.is_dl_active = False

    def _on_error(self, err):
        self.is_dl_active = False
        self.after(0, lambda: self.dl_btn.config(text="⬇ DOWNLOAD + UPSCALE", state="normal", bg=ACCENT))
        self.dl_progress_var.set(0)
        self._set_status(f"❌  {err[:70]}", ACCENT, tab=1)
        messagebox.showerror("Error", f"Item failed:\n\n{err}\n\nRemaining queue paused")

if __name__ == "__main__":
    app = TikTokDownloader()
    app.mainloop()
