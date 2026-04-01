cat << 'EOF' > entrypoint.sh
#!/bin/bash
set -e

echo "--- PHASE 1: KEY SETUP ---"
mkdir -p /root/.android
adb keygen /root/.android/adbkey || true
# Replace with your actual Mac public key string
echo "QAAAAOFlxXD... ayushsingh@Ayushs-MacBook-Pro.local" > /root/.android/adbkey.pub
chmod 600 /root/.android/adbkey
chmod 644 /root/.android/adbkey.pub
export ADB_VENDOR_KEYS=/root/.android

echo "--- PHASE 2: ADB SERVER ---"
adb kill-server || true
adb -a -P 5037 nodaemon server &
sleep 5

echo "--- PHASE 3: AVD CREATION ---"
echo "no" | avdmanager create avd -f -n pixel_device_1 -k "system-images;android-34;google_apis;x86_64" -d "pixel_6"

echo "--- PHASE 4: EMULATOR START ---"
emulator -avd pixel_device_1 -no-window -no-audio -gpu swiftshader_indirect -no-snapshot -no-boot-anim -accel on -memory 3072 &

echo "--- PHASE 5: WAITING FOR BOOT ---"
adb wait-for-device
while [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" != "1" ] ; do
  echo "Still booting..."
  sleep 7
done

echo "--- PHASE 6: APPIUM ---"
exec appium --address 0.0.0.0 --port 4723
EOF

# Strip hidden carriage returns and make executable
sed -i 's/\r$//' entrypoint.sh
chmod +x entrypoint.sh