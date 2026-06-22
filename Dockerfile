# ============================================================
# AI Media Suite - Docker Image
# Base: Python 3.10 on Debian (slim)
# GUI via: Xvfb (virtual display) + x11vnc (VNC server)
# ============================================================
FROM python:3.10-slim

# --- System dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # GUI / Display
    python3-tk \
    tk-dev \
    xvfb \
    x11vnc \
    x11-apps \
    xterm \
    # Media tools
    ffmpeg \
    # Networking / Misc
    curl \
    wget \
    ca-certificates \
    git \
    # Image library deps (for Pillow / OpenCV)
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1 \
    # Audio deps (for Whisper / ffmpeg)
    libsndfile1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Install yt-dlp ---
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp

# --- App working directory ---
WORKDIR /app

# --- Copy and install Python requirements first (layer cache) ---
COPY requirements.txt .

# Install PyTorch (CPU-only, ~700MB lighter than GPU version)
# Comment this line and uncomment the GPU line below if you need CUDA
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install remaining requirements (skip the torch comment line)
RUN grep -v '^\s*#' requirements.txt | grep -v '^\s*$' | pip install --no-cache-dir -r /dev/stdin

# --- Copy application source ---
COPY app.py .

# --- VNC startup script ---
# Creates a virtual display, launches the app, and starts a VNC server
COPY start.sh /start.sh
RUN chmod +x /start.sh

# --- Expose VNC port ---
EXPOSE 5900

# --- Default command ---
CMD ["/start.sh"]
