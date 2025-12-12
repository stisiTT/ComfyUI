# ComfyUI-tt_standalone Architecture

**Version:** 1.0.0  
**Date:** 2025-12-12

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Details](#component-details)
4. [Data Flow](#data-flow)
5. [Protocol Specification](#protocol-specification)
6. [Extension Points](#extension-points)
7. [Design Decisions](#design-decisions)

---

## System Overview

ComfyUI-tt_standalone implements a bridge architecture that connects ComfyUI's frontend to Tenstorrent's tt-metal SDXL implementation. The system is designed for:

- **Separation of Concerns**: ComfyUI handles UI/workflow, bridge handles hardware interface
- **Zero-Copy Performance**: Shared memory for tensor transfer
- **Low-Latency IPC**: Unix domain sockets for minimal overhead
- **Extensibility**: Modular design for adding new models and operations

### Key Principles

1. **Single Responsibility**: Each component has one clear purpose
2. **Loose Coupling**: Components communicate via well-defined interfaces
3. **High Cohesion**: Related functionality grouped together
4. **Fail-Safe Design**: Graceful degradation on errors

---

## Architecture Diagram

```
+------------------------------------------------------------------+
|                        ComfyUI Frontend                          |
|                     (Web UI / HTTP API)                          |
+------------------------------------------------------------------+
                              |
                              | HTTP/WebSocket
                              v
+------------------------------------------------------------------+
|                    ComfyUI Execution Engine                       |
|    +----------------------------------------------------------+  |
|    |              Custom Nodes (tenstorrent_nodes/)           |  |
|    |  +------------------+  +------------------+              |  |
|    |  | TT_CheckpointLoader |  | TT_FullDenoise |              |  |
|    |  +------------------+  +------------------+              |  |
|    |  | TT_ModelInfo     |  | TT_UnloadModel   |              |  |
|    |  +------------------+  +------------------+              |  |
|    +----------------------------------------------------------+  |
|                              |                                    |
|    +----------------------------------------------------------+  |
|    |           TenstorrentBackend (tenstorrent_backend.py)    |  |
|    |  +------------------+  +------------------+              |  |
|    |  | Socket Client    |  | TensorBridge     |              |  |
|    |  | (thread-safe)    |  | (shared memory)  |              |  |
|    |  +------------------+  +------------------+              |  |
|    +----------------------------------------------------------+  |
+------------------------------------------------------------------+
                              |
                              | Unix Socket (/tmp/tt-comfy.sock)
                              | Protocol: msgpack + length prefix
                              |
+------------------------------------------------------------------+
|                    ComfyUI Bridge Server                          |
|                   (comfyui_bridge/ in tt-metal)                   |
|    +----------------------------------------------------------+  |
|    |              server.py (ComfyUIBridgeServer)             |  |
|    |  - Socket listener                                       |  |
|    |  - Request routing                                       |  |
|    |  - Signal handling                                       |  |
|    +----------------------------------------------------------+  |
|                              |                                    |
|    +----------------------------------------------------------+  |
|    |              handlers.py (OperationHandler)              |  |
|    |  +------------------+  +------------------+              |  |
|    |  | handle_init_model|  | handle_full_denoise |           |  |
|    |  | handle_ping      |  | handle_unload_model |           |  |
|    |  +------------------+  +------------------+              |  |
|    |  +------------------+                                    |  |
|    |  | TensorBridge     | (server-side shared memory)       |  |
|    |  +------------------+                                    |  |
|    +----------------------------------------------------------+  |
|                              |                                    |
|    +----------------------------------------------------------+  |
|    |              SDXLRunner (sdxl_runner.py)                 |  |
|    |  - Model loading                                         |  |
|    |  - Device management                                     |  |
|    |  - Inference execution                                   |  |
|    +----------------------------------------------------------+  |
+------------------------------------------------------------------+
                              |
                              | ttnn API
                              v
+------------------------------------------------------------------+
|              Tenstorrent Hardware (Wormhole / T3000)             |
|    +----------------------------------------------------------+  |
|    |  Text Encoders (CLIP-L, CLIP-G) -> UNet -> VAE Decoder  |  |
|    +----------------------------------------------------------+  |
+------------------------------------------------------------------+
```

---

## Component Details

### 1. Custom Nodes (`tenstorrent_nodes/`)

**Location:** `/home/tt-admin/ComfyUI-tt_standalone/custom_nodes/tenstorrent_nodes/`

**Files:**
- `__init__.py` - Node registration
- `nodes.py` - Node implementations
- `wrappers.py` - Model wrapper classes
- `utils.py` - Utility functions

**Purpose:** Provide ComfyUI-compatible nodes that interface with Tenstorrent hardware.

**Key Classes:**

| Class | Purpose |
|-------|---------|
| `TT_CheckpointLoader` | Initialize model on device |
| `TT_FullDenoise` | Run text-to-image inference |
| `TT_ModelInfo` | Display model information |
| `TT_UnloadModel` | Release device resources |

---

### 2. TenstorrentBackend (`tenstorrent_backend.py`)

**Location:** `/home/tt-admin/ComfyUI-tt_standalone/comfy/backends/tenstorrent_backend.py`

**Purpose:** Client for communicating with the bridge server.

**Key Classes:**

#### TensorBridge
```python
class TensorBridge:
    """Zero-copy tensor transfer via POSIX shared memory."""
    
    def tensor_to_shm(tensor) -> Dict  # Write tensor to shared memory
    def tensor_from_shm(handle) -> Tensor  # Read tensor from shared memory
    def cleanup_segment(name)  # Clean up specific segment
    def cleanup_all()  # Clean up all segments
```

#### TenstorrentBackend
```python
class TenstorrentBackend:
    """Thread-safe client for bridge server communication."""
    
    def init_model(model_type, config) -> str  # Initialize model
    def full_denoise(model_id, **params) -> Dict  # Run inference
    def ping() -> Dict  # Health check
    def unload_model(model_id)  # Unload model
    def close()  # Close connection
```

**Thread Safety:** Uses `threading.RLock` for socket operations (CRITICAL-1 fix).

---

### 3. Bridge Server (`comfyui_bridge/`)

**Location:** `/home/tt-admin/tt-metal/comfyui_bridge/`

**Files:**
- `server.py` - Unix socket server
- `handlers.py` - Operation implementations
- `protocol.py` - Message protocol

**Purpose:** Bridge between ComfyUI client and SDXLRunner.

#### ComfyUIBridgeServer
```python
class ComfyUIBridgeServer:
    """Unix socket server for ComfyUI communication."""
    
    def start()  # Start server loop
    def _handle_client(sock)  # Handle single connection
    def _dispatch_operation(op, data) -> Dict  # Route to handler
```

#### OperationHandler
```python
class OperationHandler:
    """Maps operations to SDXLRunner calls."""
    
    def handle_init_model(data) -> Dict
    def handle_full_denoise(data) -> Dict
    def handle_ping(data) -> Dict
    def handle_unload_model(data) -> Dict
```

---

### 4. SDXLRunner

**Location:** `/home/tt-admin/tt-metal/sdxl_runner.py`

**Purpose:** Execute SDXL inference on Tenstorrent hardware.

**Key Methods:**
- `initialize_device()` - Initialize TT device
- `load_model()` - Load and warmup SDXL model
- `run_inference(requests)` - Execute inference batch
- `close_device()` - Release device resources

---

## Data Flow

### Model Initialization Flow

```
1. User adds TT_CheckpointLoader node
2. ComfyUI executes load_checkpoint()
3. TenstorrentBackend.init_model() called
4. Request sent via Unix socket:
   {
     "operation": "init_model",
     "data": {"model_type": "sdxl", "device_id": "0"}
   }
5. Bridge receives, calls handler.handle_init_model()
6. SDXLRunner.initialize_device() + load_model()
7. Response returned with model_id
8. TTModelWrapper created and returned to ComfyUI
```

### Inference Flow

```
1. User connects TT_FullDenoise and queues prompt
2. ComfyUI executes denoise()
3. TenstorrentBackend.full_denoise() called
4. Request sent via Unix socket:
   {
     "operation": "full_denoise",
     "data": {
       "model_id": "sdxl_abc123",
       "prompt": "a sunset...",
       "num_inference_steps": 20,
       ...
     }
   }
5. Bridge receives, calls handler.handle_full_denoise()
6. SDXLRunner.run_inference([request])
7. PIL Image converted to tensor
8. Tensor written to shared memory
9. Response returned with shm_handle
10. Client reads tensor from shared memory
11. Client unlinks shared memory (CRITICAL-2 protocol)
12. Image tensor returned to ComfyUI
```

### Shared Memory Protocol (CRITICAL-2)

```
Client (ComfyUI) sends tensor:
  1. Client creates shm segment
  2. Client writes tensor data
  3. Client sends handle via socket
  4. Server reads tensor (copies data)
  5. Server closes shm (no unlink)
  6. Server responds success
  7. Client unlinks shm after response

Server (Bridge) sends tensor:
  1. Server creates shm segment
  2. Server writes tensor data
  3. Server sends handle via socket
  4. Client reads tensor (copies data)
  5. Client unlinks shm after reading
```

---

## Protocol Specification

### Message Format

```
[4 bytes: length (big-endian uint32)]
[N bytes: msgpack-encoded payload]
```

### Request Structure

```python
{
    "operation": str,      # Operation name
    "data": dict,          # Operation parameters
    "request_id": str      # Optional tracking ID
}
```

### Response Structure

```python
# Success
{
    "status": "success",
    "error": "",
    "data": dict           # Operation result
}

# Error
{
    "status": "error",
    "error": str,          # Error message
    "data": {}
}
```

### Shared Memory Handle

```python
{
    "shm_name": str,       # POSIX shm segment name
    "shape": list[int],    # Tensor shape
    "dtype": str,          # PyTorch dtype string
    "size_bytes": int      # Total size in bytes
}
```

### Operations

| Operation | Input | Output |
|-----------|-------|--------|
| `ping` | `{}` | `{status, model_loaded, model_id}` |
| `init_model` | `{model_type, config, device_id}` | `{model_id, status}` |
| `full_denoise` | `{model_id, prompt, negative_prompt, ...}` | `{images_shm, num_images}` |
| `unload_model` | `{model_id}` | `{status}` |

---

## Extension Points

### Adding New Models

1. **Bridge Handler** (`handlers.py`):
   ```python
   def handle_init_model(self, data):
       model_type = data.get("model_type")
       if model_type == "new_model":
           self.new_runner = NewModelRunner(...)
   ```

2. **Custom Node** (`nodes.py`):
   ```python
   class TT_NewModelLoader:
       @classmethod
       def INPUT_TYPES(cls):
           return {"required": {"model_type": (["new_model"], ...)}}
   ```

3. **Model Config** (`utils.py`):
   ```python
   configs["new_model"] = {
       "latent_channels": 4,
       "model_size_gb": 5.0,
       ...
   }
   ```

### Adding New Operations

1. **Handler Method** (`handlers.py`):
   ```python
   def handle_new_operation(self, data):
       # Implementation
       return {"result": ...}
   ```

2. **Server Dispatch** (`server.py`):
   ```python
   elif operation == "new_operation":
       return self.handler.handle_new_operation(data)
   ```

3. **Client Method** (`tenstorrent_backend.py`):
   ```python
   def new_operation(self, model_id, **params):
       return self._send_receive("new_operation", {...})
   ```

---

## Design Decisions

### Why Unix Sockets?

- **Low latency**: ~100us vs ~1ms for TCP
- **No network overhead**: Kernel-optimized IPC
- **Security**: File permissions for access control
- **Simplicity**: No port management needed

### Why Shared Memory?

- **Zero-copy**: Large tensors (100MB+) transferred without serialization
- **Performance**: ~1-10ms vs ~100ms for socket transfer
- **Memory efficiency**: Single copy in physical memory

### Why msgpack?

- **Compact**: Smaller messages than JSON
- **Fast**: Faster serialization than JSON/pickle
- **Cross-platform**: Standard format
- **Binary support**: Native binary data handling

### Why Singleton Backend?

- **Resource efficiency**: Single connection per ComfyUI instance
- **State management**: Consistent model state across nodes
- **Thread safety**: Centralized locking

---

## Security Considerations

### Socket Permissions

Current: `0o777` (world-readable/writable)

**Recommendation for production:**
```python
os.chmod(self.socket_path, 0o770)  # Owner + group only
```

### Input Validation

- Tensor size limits (default: 1GB max)
- Shape dimension limits (default: 16384 max per dim)
- Message size limits (default: 100MB max)

### Resource Limits

Recommended limits for production:
- Max concurrent connections: 1 (single-client mode)
- Max shared memory segments: 100
- Max total shared memory: 10GB

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-12  
**Maintainer:** Tenstorrent AI ULC
