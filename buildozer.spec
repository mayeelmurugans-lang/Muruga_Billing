[app]

# --- Basic identity ---
title = Guhan Billing
package.name = guhanbilling
package.domain = org.guhanenterprises

# --- Source ---
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
version = 0.1

# --- Python dependencies ---
# reportlab and openpyxl are pure Python and should build fine as pip recipes; pillow and
# requests have well-established p4a recipes. If a build fails on one of these, that's the
# first thing to search "python-for-android recipe <name>" for -- it usually just means
# pinning to a slightly older/newer version.
requirements = python3,kivy==2.3.0,reportlab,openpyxl,pillow,requests

# --- Android permissions ---
# INTERNET: needed for the Firebase cloud-sync counter.
# WRITE/READ_EXTERNAL_STORAGE: needed only for the "External storage" choice in the app;
# harmless to request even if the user always picks Internal.
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

# --- Android target/API ---
# These are reasonable current defaults; bump them if buildozer's own default recipe
# versions have moved on by the time you build.
android.api = 34
android.minapi = 23
android.archs = arm64-v8a,armeabi-v7a

orientation = portrait
fullscreen = 0

[buildozer]
log_level = 2
warn_on_root = 1

# --- HOW TO BUILD ---
# Buildozer only runs on Linux or macOS (it drives the Android NDK/SDK toolchain, which
# isn't supported natively on Windows). If you're on Windows:
#   1. Install WSL2 (Windows Subsystem for Linux) with an Ubuntu image, OR use a Linux VM.
#   2. Inside that Linux environment:
#        pip3 install buildozer cython
#        sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
#            autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev \
#            libtinfo5 cmake libffi-dev libssl-dev
#   3. cd into this project folder (with main.py, billing_core.py, cloud_sync.py,
#      buildozer.spec all together) and run:
#        buildozer -v android debug
#      The first run downloads the Android SDK/NDK automatically -- it's slow (30-60+
#      minutes) and needs a few GB of disk. The APK lands in ./bin/*.apk when it finishes.
#   4. Copy the APK to your phone (or `buildozer android deploy run` with the phone plugged
#      in over USB with Developer Options / USB debugging on) and install it.
#
# Test on desktop first with `python main.py` (after `pip install kivy`) -- much faster
# iteration than a full Android build for checking the UI and logic work.
