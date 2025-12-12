"""
Custom ComfyUI nodes for Tenstorrent hardware.

Provides nodes for loading models and running inference on Tenstorrent accelerators.
Communicates with the bridge server via the TenstorrentBackend.
"""

import logging
from typing import Tuple
import sys
import os

# Add comfy to path for imports
comfy_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "comfy")
if comfy_path not in sys.path:
    sys.path.insert(0, comfy_path)

try:
    from comfy.backends.tenstorrent_backend import get_backend
    print("✓ Successfully imported get_backend from tenstorrent_backend")
except ImportError as e:
    print(f"❌ Failed to import get_backend: {e}")
    import traceback
    traceback.print_exc()
    get_backend = None

from .wrappers import TTModelWrapper, TTCLIPWrapper, TTVAEWrapper
from .utils import get_model_config, format_bytes

logger = logging.getLogger(__name__)


class TT_CheckpointLoader:
    """
    Load a model checkpoint on Tenstorrent hardware.

    This node initializes a model on the TT bridge server and returns
    wrapped MODEL, CLIP, and VAE objects for use in workflows.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_type": (["sdxl", "sd35", "sd14"], {
                    "default": "sdxl",
                    "tooltip": "Type of Stable Diffusion model to load"
                }),
                "device_id": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 31,
                    "step": 1,
                    "display": "number",
                    "tooltip": "Tenstorrent device ID (0-31)"
                }),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    RETURN_NAMES = ("model", "clip", "vae")
    OUTPUT_TOOLTIPS = (
        "Diffusion model for denoising (routes to Tenstorrent hardware)",
        "CLIP text encoder (routes to Tenstorrent hardware)",
        "VAE encoder/decoder (routes to Tenstorrent hardware)"
    )
    FUNCTION = "load_checkpoint"
    CATEGORY = "Tenstorrent"
    DESCRIPTION = "Load a Stable Diffusion model on Tenstorrent hardware via the bridge server"

    def load_checkpoint(self, model_type: str, device_id: int) -> Tuple:
        """
        Initialize model on bridge server and return wrappers.

        Args:
            model_type: Type of model (sdxl, sd35, sd14)
            device_id: Tenstorrent device ID

        Returns:
            Tuple of (model, clip, vae) wrappers
        """
        if get_backend is None:
            raise RuntimeError(
                "Tenstorrent backend not available. "
                "Make sure the bridge server is running and accessible."
            )

        logger.info(f"Loading {model_type} on Tenstorrent device {device_id}")

        try:
            # Get backend singleton
            backend = get_backend()

            # Get model config for size estimation
            config = get_model_config(model_type)
            estimated_size = config.get("model_size_gb", 7.0)
            logger.info(f"Estimated model size: {estimated_size:.2f} GB")

            # Initialize model on bridge server
            logger.info("Initializing model on bridge server (this may take a few minutes)...")
            model_id = backend.init_model(model_type, {
                "device_id": str(device_id)
            })

            logger.info(f"Model initialized with ID: {model_id}")

            # Create lightweight wrappers
            model = TTModelWrapper(model_id, backend, model_type)
            clip = TTCLIPWrapper(model_id, backend, model_type)
            vae = TTVAEWrapper(model_id, backend, model_type)

            logger.info("Successfully created model wrappers")

            return (model, clip, vae)

        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            raise RuntimeError(
                f"Failed to load {model_type} on Tenstorrent device {device_id}: {e}\n"
                f"Make sure the bridge server is running."
            )


class TT_FullDenoise:
    """
    Run complete denoising loop on Tenstorrent hardware.

    This node performs end-to-end text-to-image generation on the bridge server:
    - Text encoding (CLIP)
    - Denoising loop (UNet)
    - VAE decode

    Returns final images ready for saving.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "Model from TT_CheckpointLoader"
                }),
                "positive": ("STRING", {
                    "multiline": True,
                    "default": "a beautiful landscape",
                    "tooltip": "Positive prompt"
                }),
                "negative": ("STRING", {
                    "multiline": True,
                    "default": "blurry, low quality",
                    "tooltip": "Negative prompt"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff,
                    "tooltip": "Random seed for reproducibility"
                }),
                "steps": ("INT", {
                    "default": 20,
                    "min": 1,
                    "max": 100,
                    "step": 1,
                    "tooltip": "Number of denoising steps"
                }),
                "cfg": ("FLOAT", {
                    "default": 7.0,
                    "min": 0.0,
                    "max": 20.0,
                    "step": 0.1,
                    "tooltip": "Classifier-Free Guidance scale"
                }),
                "width": ("INT", {
                    "default": 1024,
                    "min": 256,
                    "max": 2048,
                    "step": 64,
                    "tooltip": "Image width"
                }),
                "height": ("INT", {
                    "default": 1024,
                    "min": 256,
                    "max": 2048,
                    "step": 64,
                    "tooltip": "Image height"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    OUTPUT_TOOLTIPS = ("Generated images ready for saving",)
    FUNCTION = "denoise"
    CATEGORY = "Tenstorrent"
    DESCRIPTION = "Run complete text-to-image generation on Tenstorrent hardware"

    def denoise(self, model, positive, negative, seed, steps, cfg, width, height) -> Tuple:
        """
        Run complete text-to-image generation on bridge server.

        Args:
            model: TTModelWrapper from TT_CheckpointLoader
            positive: Positive prompt text
            negative: Negative prompt text
            seed: Random seed
            steps: Number of denoising steps
            cfg: CFG scale
            width: Image width
            height: Image height

        Returns:
            Tuple with image tensor [B, H, W, C] in range [0, 1]
        """
        if not hasattr(model, 'model_id') or not hasattr(model, 'backend'):
            raise RuntimeError(
                "TT_FullDenoise requires a Tenstorrent model from TT_CheckpointLoader."
            )

        logger.info("=" * 80)
        logger.info("TT_FULLDENOISE - Starting bridge-owned inference")
        logger.info("=" * 80)
        logger.info(f"Model: {model.model_id}")
        logger.info(f"Positive: {positive[:100]}...")
        logger.info(f"Negative: {negative[:100]}...")
        logger.info(f"Steps: {steps}, CFG: {cfg}, Size: {width}x{height}, Seed: {seed}")

        try:
            import torch

            # Call bridge server for full inference
            backend = model.backend

            # Prepare parameters
            params = {
                "model_id": model.model_id,
                "prompt": positive,
                "negative_prompt": negative,
                "num_inference_steps": steps,
                "guidance_scale": cfg,
                "width": width,
                "height": height,
                "seed": seed,
            }

            # For SDXL, send same prompt as prompt_2 if not specified
            if model.model_type == "sdxl":
                params["prompt_2"] = positive
                params["negative_prompt_2"] = negative

            logger.info("Calling bridge server for full inference (CLIP + UNet + VAE)...")
            response = backend.full_denoise(**params)

            # Check response
            if "images_shm" not in response:
                raise RuntimeError(f"Bridge did not return images_shm. Response keys: {list(response.keys())}")

            # Deserialize images from shared memory
            images = backend.tensor_bridge.tensor_from_shm(response["images_shm"])

            logger.info(f"Received images: shape={images.shape}, dtype={images.dtype}")
            logger.info(f"Image value range: [{images.min().item():.3f}, {images.max().item():.3f}]")

            # Ensure correct format for ComfyUI: [B, H, W, C] in range [0, 1]
            if images.ndim == 4:
                # Check if format is [B, C, H, W] and convert to [B, H, W, C]
                if images.shape[1] == 3 or images.shape[1] == 4:
                    images = images.permute(0, 2, 3, 1)
                    logger.info(f"Converted images to [B, H, W, C]: {images.shape}")

            # Ensure range [0, 1]
            if images.max() > 1.0:
                images = images / 255.0
                logger.info("Normalized images from [0, 255] to [0, 1]")

            logger.info("=" * 80)
            logger.info("TT_FULLDENOISE - Complete!")
            logger.info("=" * 80)

            return (images,)

        except Exception as e:
            logger.error(f"Error in TT_FullDenoise: {e}", exc_info=True)
            raise RuntimeError(f"TT_FullDenoise failed: {e}")


class TT_ModelInfo:
    """
    Display information about a loaded Tenstorrent model.

    Useful for debugging and monitoring which models are loaded.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "Model to inspect"
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    OUTPUT_TOOLTIPS = ("Model information as text",)
    FUNCTION = "get_info"
    CATEGORY = "Tenstorrent/utils"
    OUTPUT_NODE = True
    DESCRIPTION = "Display information about a Tenstorrent model"

    def get_info(self, model) -> Tuple[str]:
        """
        Extract and display model information.

        Args:
            model: Model wrapper to inspect

        Returns:
            Tuple with info string
        """
        try:
            if hasattr(model, 'model_id'):
                # This is a Tenstorrent model
                info_lines = [
                    "=== Tenstorrent Model Info ===",
                    f"Model ID: {model.model_id}",
                    f"Model Type: {model.model_type}",
                    f"Backend: Tenstorrent Bridge",
                ]

                if hasattr(model, 'config'):
                    config = model.config
                    info_lines.extend([
                        "",
                        "Configuration:",
                        f"  Latent Channels: {config.get('latent_channels', 'N/A')}",
                        f"  CLIP Dim: {config.get('clip_dim', 'N/A')}",
                        f"  VAE Scale Factor: {config.get('vae_scale_factor', 'N/A')}",
                    ])

                if hasattr(model, 'model_size'):
                    size_bytes = model.model_size()
                    info_lines.append(f"  Estimated Size: {format_bytes(size_bytes)}")

                info = "\n".join(info_lines)

            else:
                # Not a Tenstorrent model
                info = "Not a Tenstorrent model\n"
                info += f"Type: {type(model).__name__}"

            logger.info(f"Model info requested:\n{info}")
            return (info,)

        except Exception as e:
            error_info = f"Error getting model info: {e}"
            logger.error(error_info)
            return (error_info,)


class TT_UnloadModel:
    """
    Explicitly unload a model from Tenstorrent device.

    Useful for freeing memory when switching between models or
    when you're done with generation.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "Model to unload"
                }),
            }
        }

    RETURN_TYPES = ()
    FUNCTION = "unload"
    CATEGORY = "Tenstorrent/utils"
    OUTPUT_NODE = True
    DESCRIPTION = "Unload a model from Tenstorrent hardware to free memory"

    def unload(self, model) -> Tuple:
        """
        Unload model from bridge server.

        Args:
            model: Model wrapper to unload

        Returns:
            Empty tuple (this is an output node)
        """
        try:
            if hasattr(model, 'model_id') and hasattr(model, 'backend'):
                logger.info(f"Unloading model {model.model_id}")
                model.backend.unload_model(model.model_id)
                logger.info(f"Successfully unloaded model {model.model_id}")
            else:
                logger.warning("Model is not a Tenstorrent model, nothing to unload")

        except Exception as e:
            logger.error(f"Error unloading model: {e}")
            # Don't raise - unload failures shouldn't break the workflow

        return ()
