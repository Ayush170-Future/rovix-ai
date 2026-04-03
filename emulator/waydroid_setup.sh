#!/bin/bash
# =============================================================================
# Waydroid + headless Weston + ADB + Appium — GCP N4A (ARM64) and similar VMs
#
# Target: Ubuntu 22.04+ ARM64, kernel with binder_linux (GCP N4A ships this).
# Nested KVM is NOT required; Waydroid uses LXC + host kernel (no QEMU ABI mismatch
# for arm64-only APKs).
#
# Before first run from your laptop, open GCP firewall TCP: 5037 (adb), 4723 (Appium)
# to this VM's external IP (or use IAP tunneling).
#
# ADB runs as a true daemon (adb start-server with ADB_SERVER_SOCKET=tcp:0.0.0.0:5037).
# Appium runs under tmux so SSH disconnects do not kill it:
#   tmux attach -t appium   → watch Appium logs
#
# Re-run `adb connect <waydroid-ip>:5555` whenever adb server restarts.
# =============================================================================
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — binder_linux (required for Waydroid)
# On kernel 6.x, /dev/binder may not exist until Waydroid mounts binderfs — that is OK.
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 1: binder_linux ==="
if modinfo binder_linux &>/dev/null; then
  echo "✓ binder_linux module present"
else
  echo "✗ Installing linux-modules-extra for binder_linux..."
  sudo apt update
  KERNEL="$(uname -r)"
  sudo apt install -y "linux-modules-extra-${KERNEL}"
  sudo modprobe binder_linux num_devices=254
  echo binder_linux | sudo tee /etc/modules-load.d/binder.conf
  echo 'options binder_linux num_devices=254' | sudo tee /etc/modprobe.d/binder.conf
  echo "→ Reboot: sudo reboot  — then re-run this script from STEP 2."
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Load modules
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 2: modprobe ==="
sudo modprobe binder_linux num_devices=254
sudo modprobe ashmem_linux 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — OS packages (Node 20 installed in STEP 3b)
# pulseaudio: Waydroid LXC bind-mounts /run/user/.../pulse/native
# android-sdk-platform-tools: Appium needs ANDROID_HOME + platform-tools
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 3: apt dependencies ==="
sudo apt update
sudo apt install -y \
  curl \
  ca-certificates \
  weston \
  openjdk-17-jdk \
  adb \
  pulseaudio \
  tmux \
  unzip \
  wget \
  lxc \
  python3-lxc \
  android-sdk-platform-tools

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3b — Node.js 20+ (Appium 3.x; Ubuntu node 18 breaks Appium)
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 3b: Node.js 20 (NodeSource) ==="
if ! command -v node >/dev/null; then
  NEED_NODE=1
else
  NODE_MAJOR="$(node -v 2>/dev/null | sed -n 's/^v\([0-9]*\).*/\1/p')"
  [[ -z "${NODE_MAJOR}" || "${NODE_MAJOR}" -lt 20 ]] && NEED_NODE=1 || NEED_NODE=0
fi
if [[ "${NEED_NODE:-0}" -eq 1 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
fi
node --version

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3c — ANDROID_HOME for Appium
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 3c: ANDROID_HOME ==="
ANDROID_HOME="/usr/lib/android-sdk"
if [[ ! -d "${ANDROID_HOME}/platform-tools" ]]; then
  echo "ERROR: ${ANDROID_HOME}/platform-tools missing. Install android-sdk-platform-tools."
  exit 1
fi
sudo tee /etc/profile.d/android-sdk.sh >/dev/null <<EOF
export ANDROID_HOME=${ANDROID_HOME}
export ANDROID_SDK_ROOT=\${ANDROID_HOME}
export PATH="\${PATH}:\${ANDROID_HOME}/platform-tools"
EOF
# shellcheck source=/dev/null
source /etc/profile.d/android-sdk.sh
echo "✓ ANDROID_HOME=${ANDROID_HOME}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Waydroid package
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 4: install Waydroid ==="
curl -fsSL https://repo.waydro.id | sudo bash
sudo apt install -y waydroid

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Initialise Android image (skip if already present)
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 5: waydroid init ==="
if [[ ! -f /var/lib/waydroid/waydroid.cfg ]]; then
  sudo waydroid init -s GAPPS -f
else
  echo "waydroid.cfg exists — skipping init (wipe /var/lib/waydroid to re-init)."
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — waydroid.cfg: auto ADB, no freeze, SwiftShader (no duplicate [properties])
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 6: waydroid.cfg tuning ==="
sudo sed -i 's/auto_adb = False/auto_adb = True/' /var/lib/waydroid/waydroid.cfg 2>/dev/null || true
sudo sed -i 's/suspend_action = freeze/suspend_action = none/' /var/lib/waydroid/waydroid.cfg 2>/dev/null || true

if ! grep -q '^ro.hardware.egl=swiftshader$' /var/lib/waydroid/waydroid.cfg 2>/dev/null; then
  sudo sed -i '/^\[properties\]$/{ N; s/\[properties\]\n\[properties\]/[properties]/; }' /var/lib/waydroid/waydroid.cfg 2>/dev/null || true
  if grep -q '^\[properties\]$' /var/lib/waydroid/waydroid.cfg; then
    sudo sed -i '/^\[properties\]$/a ro.hardware.gralloc=default\nro.hardware.egl=swiftshader' /var/lib/waydroid/waydroid.cfg
  else
    printf '\n[properties]\nro.hardware.gralloc=default\nro.hardware.egl=swiftshader\n' | sudo tee -a /var/lib/waydroid/waydroid.cfg >/dev/null
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — PulseAudio (before Waydroid session)
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 7: PulseAudio ==="
pulseaudio --start --daemonize=yes 2>/dev/null || true
sleep 1

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Weston headless — landscape 1920x1080
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 8: Weston (headless, landscape) ==="
pkill -f "weston.*headless-backend" 2>/dev/null || true
sleep 1
weston \
  --backend=headless-backend.so \
  --socket=wayland-1 \
  --width=1920 \
  --height=1080 \
  &>/tmp/weston.log &
export WAYLAND_DISPLAY=wayland-1
sleep 3

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — Waydroid session (idempotent — skip if already RUNNING)
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 9: Waydroid session ==="
if waydroid status 2>/dev/null | grep -q 'Session:.*RUNNING'; then
  echo "✓ Waydroid session already running — skipping start."
else
  echo "Starting Waydroid session..."
  waydroid session start &
  # Poll for session readiness instead of a fixed sleep
  echo -n "Waiting for session"
  for _ in $(seq 1 40); do
    waydroid status 2>/dev/null | grep -q 'Session:.*RUNNING' && break
    echo -n "."
    sleep 3
  done
  echo ""
fi
waydroid status

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10 — ADB: bind *:5037 as a true daemon, TCP 5555, keys, boot wait
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 10: ADB setup ==="

# Kill any stale server
adb kill-server 2>/dev/null || true
sleep 1

# ADB_SERVER_SOCKET tells the ADB daemon which address/port to bind.
# Using start-server (true daemon) — fully detached, survives SSH disconnect
# and does NOT need tmux. Unlike `nodaemon server &` this won't die if the
# parent shell exits.
export ADB_SERVER_SOCKET=tcp:0.0.0.0:5037
adb start-server
echo "✓ ADB daemon started (bound to 0.0.0.0:5037)"

# Poll until ADB server is responsive — removes the fragile `sleep 2` race
echo -n "Waiting for ADB server"
until adb devices &>/dev/null; do
  echo -n "."
  sleep 1
done
echo " ready."

# Read Waydroid container IP
WAYDROID_IP="$(waydroid status 2>/dev/null | awk '/IP address/ {print $NF}')"
if [[ -z "${WAYDROID_IP}" ]]; then
  echo "ERROR: could not read Waydroid IP from 'waydroid status'"
  exit 1
fi
echo "Waydroid container IP: ${WAYDROID_IP}"

# Generate ADB keypair if not present
mkdir -p "${HOME}/.android"
[[ -f "${HOME}/.android/adbkey" ]] || adb keygen "${HOME}/.android/adbkey"

# Configure adbd inside Waydroid to listen on TCP 5555
sudo waydroid shell -- sh -c "echo 'persist.adb.tcp.port=5555' > /data/local.prop && chmod 600 /data/local.prop" || true
sudo waydroid shell -- sh -c "setprop service.adb.tcp.port 5555; stop adbd; sleep 2; start adbd" || true
sleep 3

# Push ADB public key into the container so we don't get auth prompts
if [[ -f "${HOME}/.android/adbkey.pub" ]]; then
  cat "${HOME}/.android/adbkey.pub" | sudo waydroid shell -- sh -c \
    "mkdir -p /data/misc/adb && cat > /data/misc/adb/adb_keys && chmod 640 /data/misc/adb/adb_keys" || true
  sudo waydroid shell -- sh -c "stop adbd; sleep 2; start adbd" || true
  sleep 2
fi

# Connect ADB to Waydroid container
adb disconnect "${WAYDROID_IP}:5555" 2>/dev/null || true
adb connect "${WAYDROID_IP}:5555"
sleep 3
adb devices

# Unfreeze container if needed
if waydroid status 2>/dev/null | grep -q 'Container:.*FROZEN'; then
  echo "Container FROZEN — unfreezing..."
  sudo lxc-unfreeze -n waydroid -P /var/lib/waydroid/lxc || true
fi

# Wait for Android boot — poll sys.boot_completed instead of a fixed sleep
echo -n "Waiting for Android boot"
BOOT_STATE=""
for _ in $(seq 1 60); do
  BOOT_STATE="$(adb -s "${WAYDROID_IP}:5555" getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  [[ "${BOOT_STATE}" == "1" ]] && break
  echo -n "."
  sleep 3
done
echo ""

if [[ "${BOOT_STATE}" != "1" ]]; then
  echo "WARNING: Android did not signal boot_completed in time. Continuing anyway."
else
  echo "✓ Android fully booted."
fi

# Disable animations for faster Appium interactions
adb -s "${WAYDROID_IP}:5555" shell settings put global window_animation_scale 0
adb -s "${WAYDROID_IP}:5555" shell settings put global transition_animation_scale 0
adb -s "${WAYDROID_IP}:5555" shell settings put global animator_duration_scale 0

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11 — Appium + uiautomator2 driver install
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 11: Appium ==="
# shellcheck source=/dev/null
source /etc/profile.d/android-sdk.sh
export ANDROID_HOME ANDROID_SDK_ROOT PATH
sudo npm install -g appium
appium driver install uiautomator2 2>/dev/null || appium driver install uiautomator2

# ─────────────────────────────────────────────────────────────────────────────
# STEP 12 — Launch Appium inside a persistent tmux session
# Appium still needs tmux because it is not a daemon — it runs in the foreground.
# ADB does NOT need tmux (it is a true daemon after start-server).
# ─────────────────────────────────────────────────────────────────────────────
echo "=== STEP 12: Appium tmux session ==="
if tmux has-session -t appium 2>/dev/null; then
  echo "✓ tmux session 'appium' already exists — skipping."
  echo "  To restart Appium: tmux kill-session -t appium && re-run this script."
else
  tmux new-session -d -s appium \
    "source /etc/profile.d/android-sdk.sh && appium --address 0.0.0.0 --port 4723"
  echo "✓ Appium started in tmux session 'appium'."
fi

echo ""
echo "=== SETUP COMPLETE ==="
PUBLIC_IP="$(curl -fsSL --connect-timeout 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo "Device:         ${WAYDROID_IP}:5555"
echo "ADB server:     ${PUBLIC_IP}:5037"
echo "  → on backend VM: export ADB_SERVER_SOCKET=tcp:${PUBLIC_IP}:5037"
echo "Appium:         http://${PUBLIC_IP}:4723"
echo ""
echo "Useful commands:"
echo "  adb devices                                         # verify device listed"
echo "  tmux attach -t appium                               # watch Appium logs"
echo "  curl -s http://127.0.0.1:4723/status | python3 -m json.tool"
echo "  adb -s ${WAYDROID_IP}:5555 shell getprop ro.product.cpu.abi"
echo ""
echo "GCP firewall: ingress TCP 5037, 4723"