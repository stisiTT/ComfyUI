# ComfyUI-tt_standalone User Guide

**Version:** 1.0.0  
**Date:** 2025-12-12  
**Status:** Production Ready

---

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Using Tenstorrent Nodes](#using-tenstorrent-nodes)
6. [Example Workflows](#example-workflows)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)
9. [FAQ](#faq)

---

## Introduction

ComfyUI-tt_standalone enables Stable Diffusion XL (SDXL) image generation on Tenstorrent Wormhole and Galaxy hardware through ComfyUI's visual workflow interface. The system uses a bridge architecture that connects ComfyUI to tt-metal's optimized SDXL implementation.

### Key Features

- **Hardware Acceleration**: Run SDXL inference on Tenstorrent accelerators
- **Visual Workflows**: Build image generation pipelines with ComfyUI's node-based interface
- **Zero-Copy Transfers**: Efficient shared memory tensor transfer between components
- **Simple Integration**: Drop-in custom nodes for Tenstorrent hardware

### Supported Hardware

| Hardware | Support Level | Notes |
|----------|--------------|-------|
| Wormhole (n150/n300) | Full | Single device inference |
| T3000 (Galaxy) | Full | Multi-device with higher throughput |

---

## Prerequisites

### Hardware Requirements

- Tenstorrent Wormhole or T3000 device
- 32GB+ system RAM
- 100GB+ free disk space (for models and cache)

### Software Requirements

- Ubuntu 22.04 LTS (recommended)
- tt-metal SDK installed and configured
- Python 3.10+
- CUDA drivers (for GPU fallback, optional)

### Verify tt-metal Installation

```bash
# Check device availability
python3 -c "import ttnn; print(f'Devices: {ttnn.get_num_devices()}')"

# Expected output:
# Devices: 1  (for Wormhole)
# Devices: 4  (for T3000)
```

---

## Installation

### Step 1: Clone Repositories

```bash
# ComfyUI standalone with Tenstorrent support
cd /home/tt-admin
git clone <repository-url> ComfyUI-tt_standalone

# tt-metal (if not already installed)
cd /home/tt-admin
git clone <tt-metal-url> tt-metal
```

### Step 2: Setup Python Environment

```bash
# Create virtual environment
cd /home/tt-admin/ComfyUI-tt_standalone
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install torch torchvision torchaudio
pip install msgpack numpy pillow
pip install aiohttp
pip install -r requirements.txt
```

### Step 3: Setup Bridge Server Environment

```bash
cd /home/tt-admin/tt-metal
source python_env/bin/activate

# Verify dependencies
python3 -c "import msgpack; import torch; import ttnn; print('All dependencies OK')"
```

### Step 4: Download SDXL Model Weights

The system automatically downloads SDXL weights from HuggingFace on first run. Ensure you have:

```bash
# Set HuggingFace cache directory (optional)
export HF_HOME=/path/to/huggingface/cache

# Pre-download models (optional)
python3 -c "
from diffusers import StableDiffusionXLPipeline
pipe = StableDiffusionXLPipeline.from_pretrained(
    'stabilityai/stable-diffusion-xl-base-1.0',
    torch_dtype=torch.float16
)
print('Model downloaded successfully')
"
```

---

## Quick Start

### Step 1: Start the Bridge Server

Open a terminal and run:

```bash
cd /home/tt-admin/tt-metal
./launch_comfyui_bridge.sh

# For faster startup during development:
./launch_comfyui_bridge.sh --dev
```

Wait for the message: `Bridge server ready, waiting for connections...`

**Note:** First startup takes 3-5 minutes for model loading and warmup.

### Step 2: Start ComfyUI

Open a second terminal and run:

```bash
cd /home/tt-admin/ComfyUI-tt_standalone
source venv/bin/activate
python main.py --listen 0.0.0.0 --port 8188
```

### Step 3: Access ComfyUI

Open a web browser and navigate to:

```
http://localhost:8188
```

Or from another machine on the network:

```
http://<server-ip>:8188
```

---

## Using Tenstorrent Nodes

### Available Nodes

The following custom nodes are available in the "Tenstorrent" category:

| Node | Description |
|------|-------------|
| **TT Checkpoint Loader** | Load SDXL model on Tenstorrent hardware |
| **TT Full Denoise** | Run complete text-to-image generation |
| **TT Model Info** | Display loaded model information |
| **TT Unload Model** | Explicitly unload model from device |

### Basic Workflow

1. **Add TT Checkpoint Loader**
   - Right-click canvas > Add Node > Tenstorrent > TT Checkpoint Loader
   - Set `model_type` to "sdxl"
   - Set `device_id` to 0 (or your device ID)

2. **Add TT Full Denoise**
   - Right-click canvas > Add Node > Tenstorrent > TT Full Denoise
   - Connect `model` output from TT Checkpoint Loader to `model` input
   - Enter your prompt text
   - Adjust parameters (steps, CFG, size, seed)

3. **Add Save Image**
   - Right-click canvas > Add Node > image > Save Image
   - Connect `images` output from TT Full Denoise to `images` input

4. **Queue Prompt**
   - Click "Queue Prompt" to generate

### Node Parameters

#### TT Checkpoint Loader

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| model_type | choice | sdxl | Model architecture (sdxl, sd35, sd14) |
| device_id | int | 0 | Tenstorrent device ID (0-31) |

#### TT Full Denoise

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| model | MODEL | - | Model from TT Checkpoint Loader |
| positive | string | - | Positive prompt text |
| negative | string | - | Negative prompt text |
| seed | int | 0 | Random seed for reproducibility |
| steps | int | 20 | Number of denoising steps |
| cfg | float | 7.0 | Classifier-Free Guidance scale |
| width | int | 1024 | Output image width |
| height | int | 1024 | Output image height |

---

## Example Workflows

### Minimal Text-to-Image

```json
{
  "1": {
    "class_type": "TT_CheckpointLoader",
    "inputs": {
      "model_type": "sdxl",
      "device_id": 0
    }
  },
  "2": {
    "class_type": "TT_FullDenoise",
    "inputs": {
      "model": ["1", 0],
      "positive": "a beautiful sunset over mountains, dramatic lighting, 8k",
      "negative": "blurry, low quality, distorted",
      "seed": 42,
      "steps": 20,
      "cfg": 7.0,
      "width": 1024,
      "height": 1024
    }
  },
  "3": {
    "class_type": "SaveImage",
    "inputs": {
      "images": ["2", 0],
      "filename_prefix": "tt_output"
    }
  }
}
```

### High-Quality Generation

For higher quality output, increase steps and adjust CFG:

```json
{
  "2": {
    "class_type": "TT_FullDenoise",
    "inputs": {
      "model": ["1", 0],
      "positive": "portrait of a wise wizard, intricate details, fantasy art style",
      "negative": "ugly, deformed, extra limbs, blurry",
      "seed": 12345,
      "steps": 50,
      "cfg": 5.0,
      "width": 1024,
      "height": 1024
    }
  }
}
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TT_COMFY_SOCKET` | Unix socket path for bridge | `/tmp/tt-comfy.sock` |
| `SDXL_DEV_MODE` | Enable fast startup mode | `false` |
| `TT_VISIBLE_DEVICES` | Device IDs (comma-separated) | `0` |
| `HF_HOME` | HuggingFace cache directory | `~/.cache/huggingface` |

### Bridge Server Options

```bash
./launch_comfyui_bridge.sh [OPTIONS]

Options:
  --dev               Enable dev mode (fast warmup, 12 steps)
  --socket-path PATH  Custom Unix socket path
  --device-id ID      Tenstorrent device ID (default: 0)
  -h, --help          Show help message
```

### Performance Tuning

#### For Development/Testing
```bash
# Fast startup with reduced warmup
./launch_comfyui_bridge.sh --dev
```

#### For Production
```bash
# Full warmup for optimal performance
./launch_comfyui_bridge.sh
```

---

## Troubleshooting

### Bridge Server Issues

#### "Connection refused" when starting ComfyUI

**Cause:** Bridge server not running or wrong socket path.

**Solution:**
```bash
# Check if bridge is running
ps aux | grep comfyui_bridge

# Start bridge server
cd /home/tt-admin/tt-metal
./launch_comfyui_bridge.sh

# Verify socket exists
ls -la /tmp/tt-comfy.sock
```

#### "Failed to initialize device"

**Cause:** Device busy or unavailable.

**Solution:**
```bash
# Check device availability
python3 -c "import ttnn; print(ttnn.get_num_devices())"

# Kill any existing processes using the device
pkill -f sdxl_runner
pkill -f comfyui_bridge

# Restart bridge
./launch_comfyui_bridge.sh
```

### ComfyUI Issues

#### Tenstorrent nodes not appearing

**Cause:** Custom nodes not loaded properly.

**Solution:**
```bash
# Check custom nodes directory
ls -la /home/tt-admin/ComfyUI-tt_standalone/custom_nodes/tenstorrent_nodes/

# Restart ComfyUI
python main.py --listen 0.0.0.0 --port 8188
```

#### "Model not initialized" error

**Cause:** TT Checkpoint Loader not executed before TT Full Denoise.

**Solution:**
1. Ensure TT Checkpoint Loader is connected to TT Full Denoise
2. Click "Queue Prompt" to execute the workflow

### Performance Issues

#### Slow first generation

**Expected Behavior:** First inference after model load includes warmup.
- Dev mode: ~30s first image
- Production mode: ~60s first image

Subsequent images will be faster (~2-10s depending on step count).

#### Out of memory

**Solution:**
1. Reduce image resolution (512x512 for testing)
2. Reduce batch size
3. Unload model when not in use (TT Unload Model node)

---

## FAQ

### Q: Which models are supported?

Currently, SDXL (Stable Diffusion XL) is fully supported. SD 3.5 and SD 1.4 support is planned for future releases.

### Q: Can I use LoRAs or ControlNet?

Not yet. LoRA and ControlNet integration is planned for future releases. See ROADMAP.md for details.

### Q: What image sizes work best?

- **Optimal:** 1024x1024 (SDXL native resolution)
- **Supported:** 512x512 to 2048x2048 (multiples of 64)
- **Recommended:** Square or near-square aspect ratios

### Q: How do I update to a new version?

```bash
cd /home/tt-admin/ComfyUI-tt_standalone
git pull origin main

cd /home/tt-admin/tt-metal
git pull origin main

# Restart both services
```

### Q: Where are generated images saved?

By default, images are saved to:
```
/home/tt-admin/ComfyUI-tt_standalone/output/
```

---

## Support

For issues and feature requests:
- File issues on the repository
- Check existing documentation in `/docs/`
- Review logs in bridge server terminal

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-12  
**Maintainer:** Tenstorrent AI ULC
