# Quick Start: Tenstorrent Backend

## File Locations

```
/home/tt-admin/ComfyUI-tt_standalone/
├── comfy/
│   ├── backends/
│   │   ├── __init__.py              ✓ New
│   │   ├── tenstorrent_backend.py   ✓ New (394 lines)
│   │   └── tt_utils.py              ✓ New (225 lines)
│   ├── model_management.py          ✓ Modified (+20 lines)
│   └── cli_args.py                  ✓ Modified (+3 args)
└── BACKEND_IMPLEMENTATION_SUMMARY.md ✓ Documentation
```

## Quick Tests

### 1. Test Imports
```bash
cd /home/tt-admin/ComfyUI-tt_standalone
python3 -c "from comfy.backends.tenstorrent_backend import TensorBridge; print('✓ Import OK')"
```

### 2. Test Model Config
```bash
python3 -c "from comfy.backends.tt_utils import get_model_config; print(get_model_config('sdxl'))"
```

### 3. Test CLI Args
```bash
python3 -c "from comfy.cli_args import parser; args = parser.parse_args(['--tenstorrent']); print(f'✓ Tenstorrent enabled: {args.tenstorrent}')"
```

### 4. Show Help
```bash
python3 main.py --help | grep -A3 tenstorrent
```

## Usage

### Start with Tenstorrent Backend
```bash
python3 main.py --tenstorrent
```

### Custom Socket Path
```bash
python3 main.py --tenstorrent --tt-socket /custom/path.sock
```

### Specific Device
```bash
python3 main.py --tenstorrent --tt-device 1
```

## API Reference

### Backend Initialization
```python
from comfy.backends.tenstorrent_backend import get_backend

backend = get_backend()
# or with custom socket
backend = get_backend(socket_path="/tmp/custom.sock")
```

### Full Inference
```python
model_id = backend.init_model("sdxl")
result = backend.full_denoise(
    model_id=model_id,
    prompt="your prompt",
    negative_prompt="negative",
    steps=30,
    guidance_scale=7.5,
    width=1024,
    height=1024,
    seed=42
)
images = result['images']
```

### Utilities
```python
from comfy.backends.tt_utils import *

# Get model config
config = get_model_config('sdxl')
print(config['latent_channels'])  # 4

# Validate params
params = validate_inference_params({
    'prompt': 'test',
    'negative_prompt': '',
    'steps': 20,
    'guidance_scale': 7.5,
    'width': 1024,
    'height': 1024
})

# Format memory
print(format_bytes(1024*1024*1024))  # "1.00 GB"
```

## Status: ✅ Ready for Phase 2 (Custom Nodes)
