sudo mkfs.ext4 /dev/sda

sudo mkdir -p /mnt/docker-data
sudo mount /dev/sda /mnt/docker-data

/mnt/docker-data

sudo systemctl stop docker
sudo systemctl stop docker.socket

sudo rsync -aP /var/lib/docker/ /mnt/docker-data/

/etc/docker/daemon.json

{
  "data-root": "/mnt/docker-data"
}

sudo systemctl start docker

docker info | grep "Docker Root Dir"

/mnt/docker-data



# Build the image (run from the emulator/ directory)
docker build -t emulator-node .

# Cleanup old attempts
docker stop emulator-node || true
docker rm emulator-node || true

# Start fresh
# --device /dev/kvm is passed only if KVM is available on this host (not on N4A ARM VMs).
# Without it the emulator falls back to software emulation (slower but functional).
KVM_FLAG=""
[ -e /dev/kvm ] && KVM_FLAG="--device /dev/kvm"

docker run -d \
    --name emulator-node \
    $KVM_FLAG \
    --privileged \
    -p 5037:5037 \
    -p 4723:4723 \
    -v avd-data:/root/.android \
    emulator-node

# On your local Mac — replace with the N4A VM's external IP
export ADB_SERVER_SOCKET=tcp:[YOUR_VM_EXTERNAL_IP]:5037
adb devices