# ComfyUI-tt_standalone Deployment Checklist

**Version:** 1.0.0  
**Date:** 2025-12-12

---

## Pre-Deployment Checklist

### Hardware Prerequisites

- [ ] Tenstorrent hardware installed and detected
  ```bash
  # Verify device
  python3 -c "import ttnn; print(f'Devices: {ttnn.get_num_devices()}')"
  ```
- [ ] Sufficient system RAM (32GB+ recommended)
- [ ] Disk space for models (100GB+ free)
- [ ] Network access for model downloads (HuggingFace)

### Software Prerequisites

- [ ] Ubuntu 22.04 LTS installed
- [ ] tt-metal SDK installed and configured
- [ ] Python 3.10+ available
- [ ] Virtual environment created

### Environment Verification

```bash
# 1. Check Python version
python3 --version  # Should be 3.10+

# 2. Check tt-metal
python3 -c "import ttnn; print('ttnn OK')"

# 3. Check dependencies
python3 -c "import torch; import msgpack; import numpy; print('Dependencies OK')"

# 4. Check device
python3 -c "import ttnn; print(f'Devices: {ttnn.get_num_devices()}')"
```

---

## Installation Steps

### Step 1: Clone Repositories

```bash
# ComfyUI standalone
cd /home/tt-admin
git clone <repository-url> ComfyUI-tt_standalone

# Verify clone
ls -la ComfyUI-tt_standalone/
```
- [ ] ComfyUI-tt_standalone cloned successfully
- [ ] custom_nodes/tenstorrent_nodes/ directory exists

### Step 2: Setup Python Environment

```bash
cd /home/tt-admin/ComfyUI-tt_standalone
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
- [ ] Virtual environment created
- [ ] Dependencies installed without errors

### Step 3: Verify Bridge Installation

```bash
cd /home/tt-admin/tt-metal

# Check bridge module
python3 -c "from comfyui_bridge.server import ComfyUIBridgeServer; print('Bridge OK')"
python3 -c "from comfyui_bridge.protocol import send_message; print('Protocol OK')"
python3 -c "from comfyui_bridge.handlers import OperationHandler; print('Handlers OK')"
```
- [ ] All bridge imports successful

### Step 4: Download Models

```bash
# Pre-download SDXL model (optional but recommended)
export HF_HOME=/path/to/cache  # Set cache location if needed

python3 << 'EOF'
from diffusers import StableDiffusionXLPipeline
import torch
pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16
)
print("Model downloaded successfully")
EOF
```
- [ ] SDXL model downloaded to cache

---

## Service Configuration

### Environment Variables

Create `/etc/environment.d/tt-comfyui.conf`:

```bash
# Socket path
TT_COMFY_SOCKET=/tmp/tt-comfy.sock

# HuggingFace cache
HF_HOME=/home/tt-admin/.cache/huggingface

# Device configuration (optional)
TT_VISIBLE_DEVICES=0
```

### Systemd Service (Optional)

Create `/etc/systemd/system/tt-comfyui-bridge.service`:

```ini
[Unit]
Description=ComfyUI Tenstorrent Bridge Server
After=network.target

[Service]
Type=simple
User=tt-admin
WorkingDirectory=/home/tt-admin/tt-metal
Environment="PATH=/home/tt-admin/tt-metal/python_env/bin"
ExecStart=/home/tt-admin/tt-metal/launch_comfyui_bridge.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tt-comfyui-bridge
sudo systemctl start tt-comfyui-bridge
```

- [ ] Service file created (if using systemd)
- [ ] Service enabled and running

---

## Starting Services

### Manual Start (Development)

**Terminal 1: Bridge Server**
```bash
cd /home/tt-admin/tt-metal
./launch_comfyui_bridge.sh

# Wait for: "Bridge server ready, waiting for connections..."
```

**Terminal 2: ComfyUI**
```bash
cd /home/tt-admin/ComfyUI-tt_standalone
source venv/bin/activate
python main.py --listen 0.0.0.0 --port 8188
```

### Production Start

```bash
# Start bridge (background or systemd)
sudo systemctl start tt-comfyui-bridge

# Start ComfyUI
cd /home/tt-admin/ComfyUI-tt_standalone
source venv/bin/activate
nohup python main.py --listen 0.0.0.0 --port 8188 > comfyui.log 2>&1 &
```

---

## Health Checks

### Bridge Server Health

```bash
# Check process
pgrep -f comfyui_bridge

# Check socket
ls -la /tmp/tt-comfy.sock

# Test connection
python3 << 'EOF'
import socket
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    sock.connect("/tmp/tt-comfy.sock")
    print("Bridge socket: OK")
except Exception as e:
    print(f"Bridge socket: FAILED - {e}")
finally:
    sock.close()
EOF
```

### ComfyUI Health

```bash
# Check process
pgrep -f "python main.py"

# Check HTTP endpoint
curl -s http://localhost:8188/system_stats | head -20
```

### End-to-End Validation

```bash
cd /home/tt-admin/ComfyUI-tt_standalone
python test_workflow.py --quick
```

Expected output:
```
TEST 1: Bridge Server Connection
  PASSED: Bridge connection successful
TEST 2: Model Initialization
  PASSED: Model initialized successfully
TEST 3: Image Generation
  PASSED: Image generation successful
TEST 4: Image Quality Validation
  PASSED: Image quality acceptable
TEST 5: Resource Cleanup
  PASSED: Cleanup successful

OVERALL: ALL TESTS PASSED
```

---

## Monitoring and Logging

### Log Locations

| Service | Log Location |
|---------|--------------|
| Bridge Server | stdout/stderr (or systemd journal) |
| ComfyUI | stdout/stderr or `comfyui.log` |
| Validation | console output |

### View Logs

```bash
# Bridge server (systemd)
journalctl -u tt-comfyui-bridge -f

# ComfyUI
tail -f /home/tt-admin/ComfyUI-tt_standalone/comfyui.log
```

### Key Metrics to Monitor

1. **Model load time**: Should be < 5 minutes
2. **First inference time**: ~30-60s (includes warmup)
3. **Subsequent inference time**: ~2-10s (depends on steps)
4. **Memory usage**: ~16GB GPU, ~8GB system
5. **Error rate**: Should be < 1%

---

## Backup and Recovery

### Configuration Backup

```bash
# Backup configuration
tar -czf comfyui-config-backup.tar.gz \
    /home/tt-admin/ComfyUI-tt_standalone/custom_nodes/tenstorrent_nodes/ \
    /home/tt-admin/tt-metal/comfyui_bridge/ \
    /home/tt-admin/tt-metal/sdxl_config.py
```

### Model Cache Backup

```bash
# Backup model cache (if needed)
tar -czf model-cache-backup.tar.gz \
    /home/tt-admin/.cache/huggingface/hub/models--stabilityai--stable-diffusion-xl-base-1.0/
```

### Recovery Procedure

1. Stop services
2. Restore configuration from backup
3. Verify file permissions
4. Restart services
5. Run validation tests

---

## Troubleshooting

### Common Issues

#### Bridge won't start

```bash
# Check if port/socket in use
rm -f /tmp/tt-comfy.sock

# Check device availability
python3 -c "import ttnn; print(ttnn.get_num_devices())"

# Restart with clean state
pkill -f comfyui_bridge
./launch_comfyui_bridge.sh
```

#### ComfyUI can't connect to bridge

```bash
# Verify bridge is running
ps aux | grep comfyui_bridge

# Check socket permissions
ls -la /tmp/tt-comfy.sock
# Should be: srwxrwxrwx

# Test socket directly
python3 -c "
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect('/tmp/tt-comfy.sock')
print('OK')
s.close()
"
```

#### Model initialization fails

```bash
# Check device status
python3 -c "import ttnn; print(ttnn.get_num_devices())"

# Check memory
free -h

# Kill any hung processes
pkill -f sdxl_runner

# Restart bridge
./launch_comfyui_bridge.sh
```

---

## Security Considerations

### Socket Permissions

For production, restrict socket access:

```bash
# In launch_comfyui_bridge.sh, change:
os.chmod(self.socket_path, 0o770)  # Owner + group only
```

### Network Access

For production, consider:
- Firewall rules for port 8188
- Reverse proxy with authentication
- HTTPS termination

### Resource Limits

Consider setting:
- Memory limits via cgroups
- CPU affinity for inference
- Max concurrent requests

---

## Performance Tuning

### Development Mode

```bash
# Fast startup (12 warmup steps)
./launch_comfyui_bridge.sh --dev
```

### Production Mode

```bash
# Full warmup (50 steps) - better performance after warmup
./launch_comfyui_bridge.sh
```

### Memory Optimization

- Pre-download models before production
- Use appropriate batch sizes
- Clear model when not in use

---

## Deployment Sign-Off

### Checklist

- [ ] Hardware verified
- [ ] Software installed
- [ ] Services configured
- [ ] Health checks passing
- [ ] Validation tests passing
- [ ] Monitoring in place
- [ ] Backups configured
- [ ] Documentation reviewed

### Sign-Off

| Item | Status | Date | Signed By |
|------|--------|------|-----------|
| Installation complete | | | |
| Services running | | | |
| Validation passed | | | |
| Ready for production | | | |

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-12  
**Maintainer:** Tenstorrent AI ULC
