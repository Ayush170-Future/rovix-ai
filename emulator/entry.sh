cat << 'EOF' > entrypoint.sh
#!/bin/bash
set -e

echo "--- PHASE 1: KEY SETUP ---"
mkdir -p /root/.android
adb keygen /root/.android/adbkey || true
# Your Mac's public key for seamless ADB connection
echo "QAAAAOFlxXDfYbJiuRbLMSDRhSq0LPnWuLFJ7dO5oazkaSZPf44UiJisLQhfbZ4GTC6hwYv1RJfjwfzG/Xl+mDGk+AapNVK1xeWfWbJ69Y53zJPU5Y19L4fhQeBnMNTGDG7SJUf0a9xMNFPihF/okl4F3IEbzWrzNIzojUZvE1syyeXIWlmXhtUXOobBNMpDeV6POeHDoZm4VURyfhk91gAH+cUDnDGUJxiVPhZE3H14/Jz0dDLx9dyvH6CnD4eKsgot0zwVTj5/Y5jAN/gLgpml/n5J7ljDwtl9pvJL3IoF+d8ilUCkXOWgp6Qba+3AK8lh0z8c5sadubyyhxqahP0YLgoHEG21Z02eqY72terMU/CTKR3eSFZlaxy3/+ffkCw5FipQKRC0Z5cfkmNbKSKw1CqzBdJLkM6ObI8GyOwsE1kkcpKrBw9scFSp0Y0Vg/H822MqnAvyXsPVkMZGRlRr38fu/epOjSiHQp5telavpOmeEWTto4ifWi4tU6Gvw10o4kwOFdcbkF1LyKVZLOrKmWK8sikYbGjA50P3RWLjau8CD/zGATeKgDdJYyrUlQtEJoipVXCFgSeSseF/6QILv24kdAw8ag51mqjjpaT5bPA/pN7OrhntnU0AuXLUfiHrojG3iecLJctcUcc2l66Rfqm1+5sEQ3ChCBIQJtrg65i8bzr4UgEAAQA= ayushsingh@Ayushs-MacBook-Pro.local" > /root/.android/adbkey.pub
chmod 600 /root/.android/adbkey
chmod 644 /root/.android/adbkey.pub
export ADB_VENDOR_KEYS=/root/.android

echo "--- PHASE 2: ADB SERVER ---"
adb kill-server || true
adb -a -P 5037 nodaemon server &
sleep 5

echo "--- PHASE 3: AVD CREATION ---"
echo "no" | avdmanager create avd -f -n pixel_device_1 -k "system-images;android-34;google_apis;arm64-v8a" -d "pixel_6"

echo "--- PHASE 4: EMULATOR START (GPU GUEST FIX) ---"
# -gpu guest ensures Unity games don't crash on GPU-less VMs
emulator -avd pixel_device_1 \
    -no-window \
    -no-audio \
    -gpu guest \
    -no-snapshot-load \
    -no-snapshot-save \
    -no-boot-anim \
    -accel on \
    -memory 3072 &

echo "--- PHASE 5: WAITING FOR BOOT ---"
adb wait-for-device
while [ "$(adb shell getprop sys.boot_completed | tr -d '\r')" != "1" ] ; do
  echo "Still booting..."
  sleep 7
done

# Disable animations for faster, more stable Appium testing
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0

echo "--- PHASE 6: APPIUM ---"
exec appium --address 0.0.0.0 --port 4723
EOF

chmod 755 entrypoint.sh