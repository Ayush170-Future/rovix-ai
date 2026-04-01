# Cleanup old attempts
docker stop emulator-node || true
docker rm emulator-node || true

# Start fresh
docker run -d \
    --name emulator-node \
    --device /dev/kvm \
    --privileged \
    -p 5037:5037 \
    -p 4723:4723 \
    -v $(pwd)/entrypoint.sh:/entrypoint.sh \
    -v avd-data-final:/root/.android \
    emulator-node

export ADB_SERVER_SOCKET=tcp:[YOUR_VM_EXTERNAL_IP]:5037 (on local machine)

adb devices (on local machine)