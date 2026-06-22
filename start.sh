#!/bin/bash
set -e

DISPLAY_NUM=${DISPLAY_NUM:-99}
VNC_PORT=${VNC_PORT:-5900}
VNC_PASS=${VNC_PASS:-""}

# ── Clean up stale Xvfb lock files from a previous crash / restart ──
echo "[*] Cleaning up stale display locks..."
rm -f /tmp/.X${DISPLAY_NUM}-lock
rm -f /tmp/.X11-unix/X${DISPLAY_NUM}

# ── Start virtual display ────────────────────────────────────────────
echo "[*] Starting Xvfb on :${DISPLAY_NUM}"
Xvfb :${DISPLAY_NUM} -screen 0 1280x800x24 &
XVFB_PID=$!
export DISPLAY=:${DISPLAY_NUM}

# ── Wait until Xvfb socket exists (up to 10 seconds) ─────────────────
echo "[*] Waiting for Xvfb to be ready..."
READY=0
for i in $(seq 1 20); do
    if [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
        echo "[*] Xvfb is ready (attempt ${i})"
        READY=1
        break
    fi
    sleep 0.5
done

if [ "$READY" -eq 0 ]; then
    echo "[!] ERROR: Xvfb did not start in time. Exiting."
    exit 1
fi

# ── Start VNC server (backgrounded, logs to /tmp/x11vnc.log) ─────────
echo "[*] Starting x11vnc on port ${VNC_PORT}"
if [ -n "$VNC_PASS" ]; then
    x11vnc -display :${DISPLAY_NUM} -forever -rfbport ${VNC_PORT} \
           -passwd "$VNC_PASS" -bg -o /tmp/x11vnc.log -quiet
else
    x11vnc -display :${DISPLAY_NUM} -forever -rfbport ${VNC_PORT} \
           -nopw -bg -o /tmp/x11vnc.log -quiet
fi

# ── Launch the app ───────────────────────────────────────────────────
echo "[*] Launching AI Media Suite..."
python /app/app.py

# Keep the container alive while Xvfb is running
wait $XVFB_PID
