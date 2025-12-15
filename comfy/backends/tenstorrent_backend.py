# SPDX-License-Identifier: Apache-2.0
#
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC

"""
Tenstorrent backend client for ComfyUI-tt_standalone.

Communicates with standalone SDXL server via Unix domain sockets.
Implements full inference bridge integration for text-to-image generation.

CRITICAL FIX (CRITICAL-1): Added thread safety via RLock for socket operations.
CRITICAL FIX (CRITICAL-2): Fixed shared memory cleanup protocol - client now
responsible for unlinking segments after receiving server response.
"""

import socket
import struct
import msgpack
import logging
import os
import uuid
import time
import threading
from typing import Dict, Any, Optional
from multiprocessing import shared_memory
import torch
import numpy as np

logger = logging.getLogger("comfy.backends.tenstorrent")


class TensorBridge:
    """
    Manages shared memory tensor transfer between ComfyUI and bridge server.

    Provides zero-copy tensor sharing via shared memory segments.
    
    Protocol (CRITICAL-2 fix):
    1. Client creates shared memory segment and writes tensor
    2. Client sends metadata to server
    3. Server reads tensor from shared memory
    4. Server responds with success
    5. Client unlinks shared memory after receiving response
    """

    def __init__(self):
        self._active_segments: Dict[str, shared_memory.SharedMemory] = {}
        self._lock = threading.Lock()  # Thread safety for segment tracking

    def tensor_to_shm(self, tensor: torch.Tensor) -> Dict[str, Any]:
        """
        Transfer a PyTorch tensor to shared memory.

        Args:
            tensor: PyTorch tensor to share

        Returns:
            Dictionary with metadata for reconstructing the tensor
        """
        # Ensure tensor is contiguous and on CPU
        if tensor.is_cuda:
            tensor = tensor.cpu()
        tensor = tensor.contiguous()

        # Get tensor metadata
        shape = tensor.shape
        dtype_str = str(tensor.dtype)

        # Convert to numpy for shared memory
        np_array = tensor.numpy()
        size_bytes = np_array.nbytes

        # Create unique name for this shared memory segment
        shm_name = f"tt_comfy_{uuid.uuid4().hex[:16]}"

        try:
            # Create shared memory
            shm = shared_memory.SharedMemory(
                create=True,
                size=size_bytes,
                name=shm_name
            )

            # Copy data to shared memory
            shm_array = np.ndarray(
                shape=np_array.shape,
                dtype=np_array.dtype,
                buffer=shm.buf
            )
            shm_array[:] = np_array[:]

            # Store reference (thread-safe)
            with self._lock:
                self._active_segments[shm_name] = shm

            # Return handle
            return {
                "shm_name": shm_name,
                "shape": list(shape),
                "dtype": dtype_str,
                "size_bytes": size_bytes
            }

        except Exception as e:
            logger.error(f"Failed to create shared memory: {e}")
            raise

    def tensor_from_shm(self, handle: Dict[str, Any]) -> torch.Tensor:
        """
        Reconstruct a PyTorch tensor from shared memory.

        Note: This method reads from server-created shared memory segments.
        After reading, the segment is unlinked (as per CRITICAL-2 protocol).

        Args:
            handle: Dictionary with shm_name, shape, dtype, size_bytes

        Returns:
            PyTorch tensor
        """
        shm_name = handle["shm_name"]
        shape = tuple(handle["shape"])
        dtype_str = handle["dtype"]

        try:
            # Attach to existing shared memory
            shm = shared_memory.SharedMemory(name=shm_name)

            # Parse dtype with extended support (MINOR-2 fix)
            np_dtype = self._parse_dtype(dtype_str)

            # Create numpy array view
            np_array = np.ndarray(
                shape=shape,
                dtype=np_dtype,
                buffer=shm.buf
            )

            # Copy to new tensor (to avoid shared memory lifetime issues)
            tensor = torch.from_numpy(np_array.copy())

            # Clean up shared memory (client reads from server-created segment)
            shm.close()
            try:
                shm.unlink()
            except FileNotFoundError:
                pass  # Already unlinked

            return tensor

        except Exception as e:
            logger.error(f"Failed to read from shared memory: {e}")
            raise

    def _parse_dtype(self, dtype_str: str) -> np.dtype:
        """
        Parse PyTorch dtype string to numpy dtype.
        
        Extended to support more types (MINOR-2 fix).
        """
        dtype_map = {
            'float32': np.float32,
            'float16': np.float16,
            'float64': np.float64,
            'int64': np.int64,
            'int32': np.int32,
            'int16': np.int16,
            'int8': np.int8,
            'uint8': np.uint8,
            'bfloat16': np.float32,  # bfloat16 not native to numpy, use float32
        }
        for key, np_dtype in dtype_map.items():
            if key in dtype_str:
                return np_dtype
        logger.warning(f"Unknown dtype {dtype_str}, using float32")
        return np.float32

    def cleanup_segment(self, shm_name: str):
        """
        Clean up a specific shared memory segment.
        
        CRITICAL-2 fix: Only delete from tracking if unlink succeeds.
        """
        with self._lock:
            if shm_name in self._active_segments:
                shm = self._active_segments[shm_name]
                try:
                    shm.close()
                    shm.unlink()
                    del self._active_segments[shm_name]  # Only delete if successful
                except Exception as e:
                    logger.warning(f"Failed to clean up shared memory {shm_name}: {e}")
                    # Leave in _active_segments for retry

    def cleanup_all(self):
        """Clean up all active shared memory segments."""
        with self._lock:
            for shm_name in list(self._active_segments.keys()):
                shm = self._active_segments[shm_name]
                try:
                    shm.close()
                    shm.unlink()
                    del self._active_segments[shm_name]
                except Exception as e:
                    logger.warning(f"Failed to clean up shared memory {shm_name}: {e}")


class TenstorrentBackend:
    """
    Client for communicating with standalone SDXL server.

    Uses Unix domain sockets for low-latency IPC with the bridge server
    that wraps tt-metal model implementations.
    
    CRITICAL-1 fix: All socket operations are thread-safe via RLock.
    """

    def __init__(self, socket_path: Optional[str] = None):
        """
        Initialize Tenstorrent backend client.

        Args:
            socket_path: Path to Unix domain socket (default: /tmp/tt-comfy.sock)
        """
        self.socket_path = socket_path or os.getenv("TT_COMFY_SOCKET", "/tmp/tt-comfy.sock")
        self.sock: Optional[socket.socket] = None
        self.tensor_bridge = TensorBridge()
        self._lock = threading.RLock()  # CRITICAL-1: Thread safety for socket operations
        self._connect()
        logger.info(f"Tenstorrent backend initialized, socket: {self.socket_path}")

    def _connect(self, max_retries: int = 3, initial_delay: float = 0.5):
        """
        Connect to bridge server with retry logic (SIGNIFICANT-1 fix).
        
        Args:
            max_retries: Maximum number of connection attempts
            initial_delay: Initial delay between retries (exponential backoff)
        """
        for attempt in range(max_retries):
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(30.0)  # MINOR-1: Socket timeout
                self.sock.connect(self.socket_path)
                logger.info("Connected to standalone SDXL server")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    logger.warning(f"Connection attempt {attempt+1} failed, retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to connect to server at {self.socket_path}: {e}")
                    raise RuntimeError(f"Cannot connect to Tenstorrent bridge server after {max_retries} attempts: {e}")

    def _send_receive(self, operation: str, data: Dict[str, Any], request_id: Optional[str] = None, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Send a request to the bridge server and receive response.

        CRITICAL-1 fix: This method is thread-safe via RLock.

        Args:
            operation: Operation type (init_model, full_denoise, etc.)
            data: Operation data
            request_id: Optional request ID for tracking
            timeout: Optional timeout in seconds for this operation (default: use socket's current timeout)

        Returns:
            Response data dictionary
        """
        with self._lock:  # CRITICAL-1: Thread-safe socket operations
            # Save original timeout and set custom timeout if provided
            original_timeout = self.sock.gettimeout()
            if timeout is not None:
                self.sock.settimeout(timeout)

            try:
                # Build request
                request = {
                    "operation": operation,
                    "data": data,
                    "request_id": request_id or uuid.uuid4().hex[:8]
                }

                # Serialize with msgpack
                msg = msgpack.packb(request, use_bin_type=True)
                length = struct.pack('>I', len(msg))

                # Send
                try:
                    self.sock.sendall(length + msg)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    logger.warning("Connection lost, reconnecting...")
                    self._connect()
                    self.sock.sendall(length + msg)

                # Receive response length
                resp_length_bytes = self._recv_exactly(4)
                if len(resp_length_bytes) < 4:
                    raise RuntimeError("Failed to receive response length from bridge server")

                resp_length = struct.unpack('>I', resp_length_bytes)[0]

                # Receive response data
                resp_data = self._recv_exactly(resp_length)
                if len(resp_data) < resp_length:
                    raise RuntimeError("Connection closed while receiving response")

                # Deserialize
                response = msgpack.unpackb(resp_data, raw=False)

                # Check for errors
                if response.get("status") == "error":
                    error_msg = response.get("error", "Unknown error")
                    logger.error(f"Bridge server error: {error_msg}")
                    raise RuntimeError(f"Bridge server error: {error_msg}")

                return response.get("data", {})
            finally:
                # Restore original timeout
                if timeout is not None:
                    self.sock.settimeout(original_timeout)

    def _recv_exactly(self, n_bytes: int) -> bytes:
        """
        Receive exactly n_bytes from socket.
        
        Args:
            n_bytes: Number of bytes to receive
            
        Returns:
            Received bytes
        """
        data = b""
        while len(data) < n_bytes:
            chunk = self.sock.recv(min(4096, n_bytes - len(data)))
            if not chunk:
                break  # Connection closed
            data += chunk
        return data

    def init_model(self, model_type: str, config: Optional[Dict[str, Any]] = None) -> str:
        """
        Initialize a model on the bridge server.

        Args:
            model_type: Model type ("sdxl", "sd35", "sd14")
            config: Optional model configuration

        Returns:
            Model ID for subsequent operations
        """
        logger.info(f"Initializing {model_type} model (this may take up to 10 minutes on first load)...")
        logger.info("Loading weights, compiling to device, and capturing traces...")

        result = self._send_receive(
            operation="init_model",
            data={
                "model_type": model_type,
                "config": config or {},
                "device_id": "0"
            },
            timeout=600.0  # 10 minutes for model initialization
        )

        model_id = result.get("model_id")
        status = result.get("status")

        logger.info(f"Model {model_id} initialization status: {status}")
        return model_id

    def full_denoise(self, model_id: str, **params) -> Dict[str, Any]:
        """
        Run full denoising inference (text-to-image).

        This operation runs the complete inference pipeline on the server,
        from text encoding through denoising to VAE decode.

        Args:
            model_id: Model ID from init_model
            **params: Inference parameters including:
                - prompt: str - Positive prompt
                - negative_prompt: str - Negative prompt
                - prompt_2: str (optional) - Second positive prompt for SDXL
                - negative_prompt_2: str (optional) - Second negative prompt for SDXL
                - num_inference_steps: int - Number of denoising steps
                - guidance_scale: float - CFG guidance scale
                - width: int - Output width
                - height: int - Output height
                - seed: int - Random seed

        Returns:
            Dictionary with "images_shm" key containing shared memory handle
        """
        logger.info(f"Running full denoise on model {model_id}")

        data = {"model_id": model_id}
        data.update(params)

        result = self._send_receive(operation="full_denoise", data=data, timeout=120.0)

        num_images = result.get("num_images", 0)
        logger.info(f"Full denoise complete, generated {num_images} image(s)")

        return result

    def denoise_only(self, model_id: str, **params) -> Dict[str, Any]:
        """
        Run denoising without VAE decode (staged pipeline operation).

        This operation runs CLIP encoding and UNet denoising but stops before
        VAE decode, returning latent tensors. Useful for staged workflows.

        Args:
            model_id: Model ID from init_model
            **params: Inference parameters including:
                - prompt: str - Positive prompt (or prompt_embeds_shm for pre-encoded)
                - negative_prompt: str - Negative prompt
                - prompt_2: str (optional) - Second positive prompt for SDXL
                - negative_prompt_2: str (optional) - Second negative prompt for SDXL
                - num_inference_steps: int - Number of denoising steps
                - guidance_scale: float - CFG guidance scale
                - guidance_rescale: float - Guidance rescale factor
                - width: int - Output width (txt2img)
                - height: int - Output height (txt2img)
                - seed: int - Random seed
                - input_latents_shm: dict (optional) - Input latents for img2img
                - denoise_strength: float (optional) - Denoise strength for img2img

        Returns:
            Dictionary with "latents" key containing shared memory handle
        """
        logger.info(f"Running denoise_only on model {model_id}")

        data = {"model_id": model_id}
        data.update(params)

        result = self._send_receive(operation="denoise_only", data=data, timeout=120.0)

        logger.info(f"Denoise complete, latents ready in shared memory")

        return result

    def vae_decode(self, model_id: str, latents_shm: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decode latent tensors to images (staged pipeline operation).

        This operation accepts latent tensors and runs VAE decode to produce
        final images. Useful for staged workflows after denoise_only.

        Args:
            model_id: Model ID from init_model
            latents_shm: Shared memory handle for latents from denoise_only

        Returns:
            Dictionary with "images" key containing shared memory handle
        """
        logger.info(f"Running vae_decode on model {model_id}")

        data = {
            "model_id": model_id,
            "latents_shm": latents_shm
        }

        result = self._send_receive(operation="vae_decode", data=data, timeout=60.0)

        logger.info(f"VAE decode complete, images ready in shared memory")

        return result

    def vae_encode(self, model_id: str, images_shm: Dict[str, Any]) -> Dict[str, Any]:
        """
        Encode images to latent space (staged pipeline operation).

        This operation accepts pixel images and runs VAE encode to produce
        latent tensors. Useful for img2img workflows.

        Args:
            model_id: Model ID from init_model
            images_shm: Shared memory handle for input images

        Returns:
            Dictionary with "latents" key containing shared memory handle
        """
        logger.info(f"Running vae_encode on model {model_id}")

        data = {
            "model_id": model_id,
            "images_shm": images_shm
        }

        result = self._send_receive(operation="vae_encode", data=data, timeout=60.0)

        logger.info(f"VAE encode complete, latents ready in shared memory")

        return result

    def encode_prompts(self, model_id: str, prompt: str, negative_prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Encode text prompts (optional, mainly for debugging).

        Args:
            model_id: Model ID from init_model
            prompt: Positive prompt
            negative_prompt: Negative prompt
            **kwargs: Additional parameters (prompt_2, negative_prompt_2 for SDXL)

        Returns:
            Encoded prompt data
        """
        logger.debug(f"Encoding prompts for model {model_id}")

        data = {
            "model_id": model_id,
            "prompt": prompt,
            "negative_prompt": negative_prompt
        }
        data.update(kwargs)

        return self._send_receive(operation="encode_prompt", data=data)

    def ping(self) -> Dict[str, Any]:
        """
        Ping the bridge server for health check.

        Returns:
            Server status information
        """
        return self._send_receive(operation="ping", data={})

    def unload_model(self, model_id: str):
        """
        Unload a model from the bridge server.

        Args:
            model_id: Model ID to unload
        """
        logger.info(f"Unloading model {model_id}")
        self._send_receive(operation="unload_model", data={"model_id": model_id})

    def is_connected(self) -> bool:
        """
        Check if socket is still connected (MINOR-11 health check).
        
        Returns:
            True if connected, False otherwise
        """
        if self.sock is None:
            return False
        try:
            # Peek at socket without consuming data
            self.sock.setblocking(False)
            try:
                data = self.sock.recv(1, socket.MSG_PEEK)
                return len(data) > 0 or True  # Empty peek is OK
            except BlockingIOError:
                return True  # No data but connected
            except (ConnectionResetError, BrokenPipeError):
                return False
            finally:
                self.sock.setblocking(True)
                self.sock.settimeout(30.0)
        except Exception:
            return False

    def close(self):
        """Close connection to bridge server."""
        # Cleanup shared memory
        if hasattr(self, 'tensor_bridge'):
            self.tensor_bridge.cleanup_all()

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
            logger.info("Closed connection to bridge server")

    def __del__(self):
        """Cleanup on deletion."""
        self.close()


# Global backend instance with thread-safe singleton
_backend_instance: Optional[TenstorrentBackend] = None
_backend_lock = threading.Lock()


def get_backend(socket_path: Optional[str] = None) -> TenstorrentBackend:
    """
    Get or create global backend instance (thread-safe singleton).

    Args:
        socket_path: Optional socket path to use for new instance

    Returns:
        Global TenstorrentBackend instance
    """
    global _backend_instance
    with _backend_lock:
        if _backend_instance is None:
            _backend_instance = TenstorrentBackend(socket_path=socket_path)
        return _backend_instance
