import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import shutil
from PIL import Image, ImageTk

# Styling Constants (Consistent with app.py)
BG      = "#0d0d0f"
BG2     = "#16161a"
BG3     = "#1e1e24"
ACCENT  = "#fe2c55"
ACCENT2 = "#25f4ee"
TEXT    = "#ffffff"
SUBTEXT = "#8a8a9a"
SUCCESS = "#2dde98"
WARN    = "#ffbe0b"

def compute_ahash(image_path):
    """Compute Average Hash (a-hash) for an image"""
    try:
        with Image.open(image_path) as img:
            # 1. Resize to 8x8 and convert to grayscale
            img = img.resize((8, 8), Image.Resampling.LANCZOS).convert('L')
            pixels = list(img.getdata())
            # 2. Compute average value
            avg = sum(pixels) / 64
            # 3. Create hash bit by bit
            diff = "".join(["1" if p >= avg else "0" for p in pixels])
            # 4. Return as integer for fast comparison
            return int(diff, 2)
    except:
        return None

def hamming_distance(h1, h2):
    """Calculate hamming distance between two integers (number of bits that differ)"""
    x = h1 ^ h2
    return bin(x).count("1")

class ImageFinderTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        
        self.source_img_path = tk.StringVar()
        self.target_dir      = tk.StringVar(value=os.path.expanduser("~/Pictures"))
        self.threshold_var   = tk.IntVar(value=5) # 0-64 bits. Lower means more similar.
        self.status_var      = tk.StringVar(value="Ready to find similar images ✓")
        self.progress_var    = tk.DoubleVar(value=0)
        self.is_searching    = False
        self.results         = [] # List of (path, distance)

        self._build_ui()

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=BG, pady=10)
        header.pack(fill="x", padx=30)
        
        logo_frame = tk.Frame(header, bg=BG)
        logo_frame.pack()
        tk.Label(logo_frame, text="🔍", font=("Segoe UI Emoji", 24), fg=ACCENT2, bg=BG).pack(side="left")
        tk.Label(logo_frame, text=" Image", font=("Impact", 24), fg=TEXT, bg=BG).pack(side="left")
        tk.Label(logo_frame, text="Finder", font=("Impact", 24), fg=ACCENT, bg=BG).pack(side="left")
        
        tk.Label(header, text="Find similar images in your folders using Perceptual Hashing (AI)", 
                 font=("Segoe UI", 10), fg=SUBTEXT, bg=BG).pack()

        # Separator
        tk.Frame(self, bg=ACCENT, height=2).pack(fill="x", padx=30)

        # Main Layout (Split Left/Right)
        main_body = tk.Frame(self, bg=BG, padx=30, pady=20)
        main_body.pack(fill="both", expand=True)

        # LEFT SIDE: Controls & Preview
        left_pane = tk.Frame(main_body, bg=BG, width=350)
        left_pane.pack(side="left", fill="both", padx=(0, 20))
        left_pane.pack_propagate(False)

        # Source Image Block
        tk.Label(left_pane, text="🖼️  SOURCE IMAGE", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG, anchor="w").pack(fill="x")
        
        self.preview_canvas = tk.Canvas(left_pane, width=300, height=200, bg=BG2, 
                                        highlightthickness=1, highlightbackground=BG3)
        self.preview_canvas.pack(pady=(8, 12))
        self.preview_canvas.create_text(150, 100, text="NO IMAGE SELECTED", fill=SUBTEXT, font=("Segoe UI", 9))

        tk.Button(left_pane, text="📁 SELECT SOURCE IMAGE", font=("Segoe UI", 9, "bold"),
                  bg=BG3, fg=TEXT, relief="flat", cursor="hand2", pady=8,
                  command=self._select_source).pack(fill="x", pady=(0, 20))

        # Folder Block
        tk.Label(left_pane, text="📂  TARGET FOLDER", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG, anchor="w").pack(fill="x")
        
        f_row = tk.Frame(left_pane, bg=BG)
        f_row.pack(fill="x", pady=(8, 12))
        
        entry_f = tk.Frame(f_row, bg=BG3, pady=2)
        entry_f.pack(side="left", fill="x", expand=True)
        self.folder_entry = tk.Entry(entry_f, textvariable=self.target_dir, font=("Consolas", 10),
                                     bg=BG3, fg=TEXT, insertbackground=ACCENT2, relief="flat", bd=5)
        self.folder_entry.pack(fill="x", padx=4)
        
        tk.Button(f_row, text="BROWSE", font=("Segoe UI", 8, "bold"), bg=ACCENT, fg=TEXT,
                  relief="flat", cursor="hand2", command=self._select_folder).pack(side="right", padx=(5, 0))

        # Precision Slider
        tk.Label(left_pane, text="🎯  SIMILARITY THRESHOLD", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG, anchor="w").pack(fill="x")
        
        slider_frame = tk.Frame(left_pane, bg=BG2, padx=10, pady=10)
        slider_frame.pack(fill="x", pady=(8, 20))
        
        tk.Scale(slider_frame, from_=0, to=20, variable=self.threshold_var, 
                 orient="horizontal", bg=BG2, fg=SUBTEXT, highlightthickness=0,
                 troughcolor=BG3, activebackground=ACCENT).pack(fill="x")
        tk.Label(slider_frame, text="(0 = Identical, 10 = Very Loose Match)", 
                 font=("Segoe UI", 8), fg=SUBTEXT, bg=BG2).pack()

        # Action Button
        self.search_btn = tk.Button(left_pane, text="🔍  FIND SIMILAR IMAGES", font=("Impact", 15),
                                   bg=ACCENT, fg=TEXT, relief="flat", cursor="hand2", pady=15,
                                   command=self._start_search)
        self.search_btn.pack(fill="x")

        # RIGHT SIDE: Results
        right_pane = tk.Frame(main_body, bg=BG2, padx=15, pady=15)
        right_pane.pack(side="right", fill="both", expand=True)

        tk.Label(right_pane, text="📄  SEARCH RESULTS", font=("Segoe UI", 10, "bold"),
                 fg=ACCENT2, bg=BG2, anchor="w").pack(fill="x")

        # Results List
        res_frame = tk.Frame(right_pane, bg=BG3, pady=2)
        res_frame.pack(fill="both", expand=True, pady=(10, 10))
        
        self.res_listbox = tk.Listbox(res_frame, bg=BG3, fg=TEXT, font=("Segoe UI", 10),
                                      relief="flat", bd=5, selectbackground=ACCENT, 
                                      selectforeground=TEXT, highlightthickness=0)
        self.res_listbox.pack(side="left", fill="both", expand=True)
        
        sb = ttk.Scrollbar(res_frame, orient="vertical", command=self.res_listbox.yview)
        sb.pack(side="right", fill="y")
        self.res_listbox.config(yscrollcommand=sb.set)
        
        # Result Actions
        act_row = tk.Frame(right_pane, bg=BG2)
        act_row.pack(fill="x")
        
        tk.Button(act_row, text="📂 Open Folder", font=("Segoe UI", 9),
                  bg=BG3, fg=TEXT, relief="flat", cursor="hand2", padx=15,
                  command=self._open_result_folder).pack(side="left")
        
        tk.Button(act_row, text="🖼️ Open File", font=("Segoe UI", 9, "bold"),
                  bg=ACCENT2, fg=BG, relief="flat", cursor="hand2", padx=20,
                  command=self._open_result_file).pack(side="right")

        # Footer Status
        status_bar = tk.Frame(self, bg=BG, pady=5)
        status_bar.pack(fill="x", side="bottom")
        
        progress_f = tk.Frame(status_bar, bg=BG)
        progress_f.pack(fill="x", side="bottom", padx=30, pady=(0, 5))
        
        self.pbar = ttk.Progressbar(progress_f, variable=self.progress_var, maximum=100)
        self.pbar.pack(fill="x")
        
        tk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9),
                 bg=BG, fg=SUBTEXT, padx=30).pack(side="left")

    def _select_source(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.webp *.bmp")])
        if path:
            self.source_img_path.set(path)
            self._update_preview(path)

    def _update_preview(self, path):
        try:
            img = Image.open(path)
            img.thumbnail((300, 200))
            self.tk_preview = ImageTk.PhotoImage(img)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(150, 100, image=self.tk_preview)
        except:
            pass

    def _select_folder(self):
        d = filedialog.askdirectory()
        if d: self.target_dir.set(d)

    def _start_search(self):
        if self.is_searching: return
        source = self.source_img_path.get()
        target = self.target_dir.get()
        
        if not source or not os.path.exists(source):
            messagebox.showwarning("Error", "Please select a source image.")
            return
        if not target or not os.path.isdir(target):
            messagebox.showwarning("Error", "Please select a valid folder to search.")
            return

        self.is_searching = True
        self.search_btn.config(text="⌛ SEARCHING...", state="disabled", bg="#444")
        self.res_listbox.delete(0, tk.END)
        self.results = []
        self.progress_var.set(0)
        self.status_var.set("Scanning folder...")
        
        threading.Thread(target=self._search_thread, args=(source, target), daemon=True).start()

    def _search_thread(self, source_path, target_dir):
        try:
            # 1. Compute source hash
            s_hash = compute_ahash(source_path)
            if s_hash is None: raise Exception("Failed to process source image.")
            
            # 2. Get all image files
            valid_exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
            all_files = []
            for root, dirs, files in os.walk(target_dir):
                for f in files:
                    if f.lower().endswith(valid_exts):
                        all_files.append(os.path.join(root, f))
            
            total = len(all_files)
            if total == 0:
                self.after(0, lambda: self.status_var.set("No images found in target folder."))
                return

            threshold = self.threshold_var.get()
            matches = []

            # 3. Compare each file
            for i, f_path in enumerate(all_files):
                if not self.is_searching: break
                
                f_hash = compute_ahash(f_path)
                if f_hash is not None:
                    dist = hamming_distance(s_hash, f_hash)
                    if dist <= threshold:
                        matches.append((f_path, dist))
                
                # Update progress
                if i % 10 == 0 or i == total - 1:
                    pct = ((i + 1) / total) * 100
                    self.after(0, lambda p=pct: self.progress_var.set(p))
                    self.after(0, lambda n=i+1, t=total: self.status_var.set(f"Processed {n}/{t} files..."))

            # 4. Sort results by similarity (distance)
            matches.sort(key=lambda x: x[1])
            self.results = matches

            # 5. Populate UI
            def update_ui():
                self.res_listbox.delete(0, tk.END)
                if not matches:
                    self.status_var.set("No similar images found.")
                else:
                    for path, dist in matches:
                        match_pct = ((64 - dist) / 64) * 100
                        self.res_listbox.insert("end", f"[{match_pct:.1f}%] {os.path.basename(path)}")
                    self.status_var.set(f"Finished! Found {len(matches)} matches ✓")
                
                self.search_btn.config(text="🔍  FIND SIMILAR IMAGES", state="normal", bg=ACCENT)
                self.is_searching = False

            self.after(0, update_ui)

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.after(0, lambda: self.search_btn.config(text="🔍  FIND SIMILAR IMAGES", state="normal", bg=ACCENT))
            self.is_searching = False

    def _open_result_folder(self):
        sel = self.res_listbox.curselection()
        if sel and self.results:
            path = self.results[sel[0]][0]
            os.startfile(os.path.dirname(path))

    def _open_result_file(self):
        sel = self.res_listbox.curselection()
        if sel and self.results:
            path = self.results[sel[0]][0]
            os.startfile(path)

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Image Finder Standalone")
    root.geometry("1000x700")
    root.configure(bg=BG)
    finder = ImageFinderTab(root)
    finder.pack(fill="both", expand=True)
    root.mainloop()
