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
COPY extract_json.py .
COPY debug_tiktok.py .
# Copy the bin/ directory (Real-ESRGAN binary, etc.) if present
COPY bin/ ./bin/

# --- VNC startup script ---
# Creates a virtual display, launches the app, and starts a VNC server
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
DISPLAY_NUM=${DISPLAY_NUM:-99}\n\
VNC_PORT=${VNC_PORT:-5900}\n\
VNC_PASS=${VNC_PASS:-""}\n\
\n\
echo "[*] Starting Xvfb on :$DISPLAY_NUM"\n\
Xvfb :$DISPLAY_NUM -screen 0 1280x800x24 &\n\
XVFB_PID=$!\n\
export DISPLAY=:$DISPLAY_NUM\n\
sleep 1\n\
\n\
echo "[*] Starting x11vnc on port $VNC_PORT"\n\
if [ -n "$VNC_PASS" ]; then\n\
    x11vnc -display :$DISPLAY_NUM -forever -rfbport $VNC_PORT -passwd "$VNC_PASS" &\n\
else\n\
    x11vnc -display :$DISPLAY_NUM -forever -rfbport $VNC_PORT -nopw &\n\
fi\n\
\n\
echo "[*] Launching AI Media Suite..."\n\
python /app/app.py\n\
\n\
wait $XVFB_PID\n\
' > /start.sh && chmod +x /start.sh

# --- Expose VNC port ---
EXPOSE 5900

# --- Default command ---
CMD ["/start.sh"]
