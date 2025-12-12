# Tenstorrent Backend Infrastructure - Implementation Summary

**Status**: ✅ COMPLETE  
**Date**: 2025-12-12  
**Phase**: 1 - Backend Infrastructure

## Overview

Successfully implemented the Tenstorrent backend infrastructure for ComfyUI-tt_standalone. This creates the communication layer for the Full Inference Bridge integration that connects ComfyUI to the standalone SDXL server.

## Files Created

### 1. `/comfy/backends/__init__.py` (12 lines)
- Package initialization
- Exports backend modules

### 2. `/comfy/backends/tenstorrent_backend.py` (394 lines)
**Core Components:**

#### TensorBridge Class (Lines 25-160)
- Manages shared memory tensor transfer
- Zero-copy tensor sharing via Unix shared memory
- Methods:
  - `tensor_to_shm()`: Transfer PyTorch tensor to shared memory
  - `tensor_from_shm()`: Reconstruct tensor from shared memory
  - `cleanup_segment()`: Clean up specific segment
  - `cleanup_all()`: Clean up all segments

#### TenstorrentBackend Class (Lines 162-361)
- Client for communicating with standalone SDXL server
- Unix domain socket IPC protocol
- Methods:
  - `init_model()`: Initialize model on server
  - `full_denoise()`: Run complete text-to-image inference
  - `encode_prompts()`: Encode text prompts (optional)
  - `ping()`: Health check
  - `unload_model()`: Unload model from server
  - `_send_receive()`: Core msgpack-based communication

**Key Modifications from Source:**
- Removed `apply_unet()` (not needed for full inference)
- Added `full_denoise()` operation handler
- Adapted for standalone server protocol

### 3. `/comfy/backends/tt_utils.py` (225 lines)
**Utility Functions:**
- `get_model_config()`: Get model configuration for sdxl/sd35/sd14
- `validate_tensor_shape()`: Validate tensor dimensions
- `validate_latent_shape()`: Validate latent tensor for model type
- `estimate_tensor_memory()`: Calculate tensor memory usage
- `format_bytes()`: Human-readable byte formatting
- `validate_inference_params()`: Validate inference parameters
- `get_supported_models()`: List supported model types
- `is_model_supported()`: Check if model type is supported
- `check_backend_available()`: Check backend availability

## Files Modified

### 4. `/comfy/model_management.py` (+20 lines)

**Line 42 - Added CPUState enum:**
```python
TENSTORRENT = 6  # Tenstorrent hardware acceleration
```

**Lines 171-187 - Added helper functions:**
```python
def is_tenstorrent_device(device):
    """Check if device is Tenstorrent hardware."""
    if isinstance(device, str):
        return device.lower() == 'tenstorrent' or device.lower() == 'tt'
    return False

def get_tenstorrent_backend():
    """Get Tenstorrent backend singleton."""
    try:
        from comfy.backends.tenstorrent_backend import get_backend
        return get_backend()
    except ImportError as e:
        logging.warning(f"Tenstorrent backend not available: {e}")
        return None
    except Exception as e:
        logging.warning(f"Failed to initialize Tenstorrent backend: {e}")
        return None
```

### 5. `/comfy/cli_args.py` (+3 lines)

**Lines 79-81 - Added CLI arguments:**
```python
parser.add_argument("--tenstorrent", action="store_true", 
                   help="Enable Tenstorrent hardware acceleration")
parser.add_argument("--tt-socket", type=str, default="/tmp/tt-comfy.sock", 
                   help="Path to Tenstorrent bridge Unix socket")
parser.add_argument("--tt-device", type=int, default=0, 
                   help="Tenstorrent device ID (0-31)")
```

## Validation Results

All validation tests passed:

### Import Tests ✓
- ✓ TensorBridge imported successfully
- ✓ TenstorrentBackend imported successfully
- ✓ get_backend imported successfully
- ✓ All utility functions imported and working

### CLI Arguments ✓
- ✓ `--tenstorrent` flag registered
- ✓ `--tt-socket` argument working
- ✓ `--tt-device` argument working

### TensorBridge Functionality ✓
- ✓ `tensor_to_shm()` working (tested with shape [2, 4, 8, 8])
- ✓ `tensor_from_shm()` working
- ✓ `cleanup_all()` working

### Utility Functions ✓
- ✓ `get_model_config()` returns correct configs for sdxl/sd35/sd14
- ✓ `validate_inference_params()` validates parameters correctly
- ✓ `format_bytes()` formats sizes correctly
- ✓ `get_supported_models()` returns ['sdxl', 'sd35', 'sd14']
- ✓ `is_model_supported()` checks model types correctly

### File Structure ✓
```
/comfy/backends/
├── __init__.py              (288 bytes)
├── tenstorrent_backend.py   (12,332 bytes)
└── tt_utils.py              (6,472 bytes)
```

## Protocol Overview

### Communication Protocol
- **Transport**: Unix domain sockets (low-latency IPC)
- **Serialization**: msgpack (binary, compact)
- **Tensor Transfer**: Shared memory (zero-copy)

### Message Format
```python
Request:
{
    "operation": str,      # init_model, full_denoise, etc.
    "data": dict,          # Operation-specific data
    "request_id": str      # Optional tracking ID
}

Response:
{
    "status": str,         # "success" or "error"
    "data": dict,          # Response data
    "error": str           # Error message if status == "error"
}
```

### Supported Operations
1. **init_model**: Initialize model on server
   - Input: model_type, config, device_id
   - Output: model_id, status

2. **full_denoise**: Complete text-to-image inference
   - Input: model_id, prompt, negative_prompt, steps, guidance_scale, width, height, seed
   - Output: images (list of PIL Images), num_images

3. **encode_prompt**: Text encoding (optional/debug)
   - Input: model_id, prompt, negative_prompt
   - Output: encoded prompt data

4. **ping**: Health check
   - Input: none
   - Output: server status

5. **unload_model**: Unload model
   - Input: model_id
   - Output: confirmation

## Usage Examples

### Initialize Backend
```python
from comfy.backends.tenstorrent_backend import get_backend

backend = get_backend(socket_path="/tmp/tt-comfy.sock")
```

### Run Inference
```python
# Initialize model
model_id = backend.init_model("sdxl")

# Run full denoise
result = backend.full_denoise(
    model_id=model_id,
    prompt="a beautiful sunset over mountains",
    negative_prompt="blurry, low quality",
    steps=30,
    guidance_scale=7.5,
    width=1024,
    height=1024,
    seed=42
)

images = result['images']
```

### CLI Usage
```bash
# Start ComfyUI with Tenstorrent backend
python main.py --tenstorrent

# Custom socket path
python main.py --tenstorrent --tt-socket /custom/path/socket.sock

# Specific device
python main.py --tenstorrent --tt-device 1
```

## Integration Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ComfyUI-tt_standalone                    │
│                                                              │
│  ┌────────────────┐        ┌──────────────────────────┐    │
│  │  Custom Nodes  │───────▶│  TenstorrentBackend      │    │
│  │  (Phase 2)     │        │  - init_model()          │    │
│  └────────────────┘        │  - full_denoise()        │    │
│                            │  - encode_prompts()      │    │
│  ┌────────────────┐        └──────────┬───────────────┘    │
│  │   CLI Args     │                   │                     │
│  │  --tenstorrent │                   │ Unix Socket         │
│  │  --tt-socket   │                   │ msgpack protocol    │
│  └────────────────┘                   │                     │
│                                        │                     │
│  ┌────────────────┐        ┌──────────▼───────────────┐    │
│  │ TensorBridge   │───────▶│  Shared Memory          │    │
│  │  (zero-copy)   │        │  (tensor transfer)      │    │
│  └────────────────┘        └─────────────────────────┘    │
└──────────────────────────────────┬──────────────────────────┘
                                   │
                                   │ IPC
                                   ▼
                    ┌──────────────────────────────┐
                    │  Standalone SDXL Server      │
                    │  - tt-metal inference        │
                    │  - Full pipeline on TT hw    │
                    └──────────────────────────────┘
```

## Next Steps

### Phase 2: Custom Nodes (To Be Implemented)
1. Create `/custom_nodes/tenstorrent_nodes/`
2. Implement nodes:
   - `TenstorrentSDXLLoader`: Load model
   - `TenstorrentKSampler`: Run inference
   - `TenstorrentPromptEncoder`: Encode prompts (optional)
3. Register nodes with ComfyUI

### Phase 3: Testing
1. Start standalone SDXL server
2. Launch ComfyUI with `--tenstorrent`
3. Test workflow execution
4. Validate image quality

## Technical Notes

### Memory Management
- TensorBridge uses Unix shared memory (`/dev/shm`)
- Automatic cleanup on backend close
- Unique segment names prevent collisions

### Error Handling
- Connection retry on broken pipe
- Graceful degradation if backend unavailable
- Comprehensive error messages

### Performance Considerations
- Zero-copy tensor transfer via shared memory
- Binary msgpack serialization (faster than JSON)
- Unix domain sockets (lower latency than TCP)

## Dependencies

### Required Python Packages
- `torch`: PyTorch for tensor operations
- `msgpack`: Binary serialization
- `numpy`: Array operations
- Standard library: `socket`, `struct`, `multiprocessing`, `logging`

### System Requirements
- Unix-like OS (for Unix domain sockets)
- `/dev/shm` support (for shared memory)
- Tenstorrent hardware (for actual inference)

## Compatibility

- **ComfyUI Version**: Compatible with base ComfyUI-tt_standalone
- **Python Version**: 3.8+
- **PyTorch Version**: 1.10+
- **Platform**: Linux (primary), macOS (limited)

## License

SPDX-License-Identifier: Apache-2.0  
SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC

---

**Implementation Complete**: All backend infrastructure is in place and validated.  
**Status**: Ready for Phase 2 (Custom Nodes)
