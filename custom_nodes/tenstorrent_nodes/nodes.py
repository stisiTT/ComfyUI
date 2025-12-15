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


class TT_Denoise:
    """
    Run denoising on Tenstorrent hardware, returning latents.

    This node performs CLIP encoding and UNet denoising but does NOT run
    VAE decode. Output latents can be passed to TT_VAEDecode or standard
    VAEDecode for final image generation.

    Supports both txt2img and img2img workflows.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {
                    "tooltip": "Model from TT_CheckpointLoader"
                }),
                "positive": ("CONDITIONING", {
                    "tooltip": "Positive conditioning (from CLIPTextEncode)"
                }),
                "negative": ("CONDITIONING", {
                    "tooltip": "Negative conditioning (from CLIPTextEncode)"
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
                    "max": 150,
                    "step": 1,
                    "tooltip": "Number of denoising steps"
                }),
                "cfg": ("FLOAT", {
                    "default": 5.0,
                    "min": 0.0,
                    "max": 30.0,
                    "step": 0.1,
                    "tooltip": "Classifier-Free Guidance scale"
                }),
                "guidance_rescale": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Guidance rescale factor (0.0 = disabled)"
                }),
            },
            "optional": {
                "latent_image": ("LATENT", {
                    "tooltip": "Input latents for img2img (optional)"
                }),
                "denoise": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Denoise strength (1.0 = full denoise, <1.0 = img2img)"
                }),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("samples",)
    OUTPUT_TOOLTIPS = ("Denoised latent tensors",)
    FUNCTION = "denoise"
    CATEGORY = "Tenstorrent/sampling"
    DESCRIPTION = "Run CLIP encoding and UNet denoising on Tenstorrent hardware, returns latent tensors"

    def denoise(self, model, positive, negative, seed, steps, cfg,
                guidance_rescale, latent_image=None, denoise=1.0) -> Tuple:
        """
        Execute denoising operation on Tenstorrent hardware.

        Args:
            model: TTModelWrapper from TT_CheckpointLoader
            positive: Positive CONDITIONING from CLIPTextEncode
            negative: Negative CONDITIONING from CLIPTextEncode
            seed: Random seed for latent generation
            steps: Number of denoising steps
            cfg: Guidance scale
            guidance_rescale: Guidance rescale factor
            latent_image: Optional input latent for img2img (LATENT dict)
            denoise: Denoise strength (1.0 = full denoise)

        Returns:
            Tuple containing LATENT dictionary with "samples" tensor
        """
        if not hasattr(model, 'model_id') or not hasattr(model, 'backend'):
            raise RuntimeError(
                "TT_Denoise requires a Tenstorrent model from TT_CheckpointLoader."
            )

        logger.info("=" * 80)
        logger.info("TT_DENOISE - Starting denoising (returns latents)")
        logger.info("=" * 80)
        logger.info(f"Model: {model.model_id}")
        logger.info(f"Steps: {steps}, CFG: {cfg}, Guidance rescale: {guidance_rescale}, Seed: {seed}")
        logger.info(f"Denoise strength: {denoise}")

        try:
            import torch

            backend = model.backend

            # Extract conditioning data from ComfyUI CONDITIONING format
            # CONDITIONING format: [(embedding_tensor, metadata_dict), ...]
            # For text-based conditioning, we need to extract the prompts from metadata
            # or pass the embeddings directly if they're pre-encoded

            positive_text = None
            negative_text = None

            # Try to extract text from conditioning metadata
            if isinstance(positive, list) and len(positive) > 0:
                cond_data = positive[0]
                if isinstance(cond_data, tuple) and len(cond_data) >= 2:
                    metadata = cond_data[1]
                    if isinstance(metadata, dict):
                        # Check if this is text-based conditioning
                        if "pooled_output" in metadata or "prompt" in metadata:
                            positive_text = metadata.get("prompt", "")

            if isinstance(negative, list) and len(negative) > 0:
                cond_data = negative[0]
                if isinstance(cond_data, tuple) and len(cond_data) >= 2:
                    metadata = cond_data[1]
                    if isinstance(metadata, dict):
                        if "pooled_output" in metadata or "prompt" in metadata:
                            negative_text = metadata.get("prompt", "")

            # If we couldn't extract text, use default prompts
            if positive_text is None:
                logger.warning("Could not extract positive prompt from CONDITIONING, using placeholder")
                positive_text = "a beautiful landscape"

            if negative_text is None:
                logger.warning("Could not extract negative prompt from CONDITIONING, using placeholder")
                negative_text = "blurry, low quality"

            logger.info(f"Positive prompt: {positive_text[:100]}...")
            logger.info(f"Negative prompt: {negative_text[:100]}...")

            # Prepare parameters for bridge server
            params = {
                "model_id": model.model_id,
                "prompt": positive_text,
                "negative_prompt": negative_text,
                "num_inference_steps": steps,
                "guidance_scale": cfg,
                "seed": seed,
            }

            # Add guidance_rescale if non-zero
            if guidance_rescale > 0.0:
                params["guidance_rescale"] = guidance_rescale

            # For SDXL, send same prompt as prompt_2 if not specified
            if model.model_type == "sdxl":
                params["prompt_2"] = positive_text
                params["negative_prompt_2"] = negative_text

            # Handle optional latent_image input for img2img
            latents_shm = None
            if latent_image is not None:
                logger.info("Using provided latent_image for img2img")
                latents = latent_image["samples"]
                logger.info(f"Input latents shape: {latents.shape}, dtype: {latents.dtype}")

                # Transfer to shared memory
                latents_shm = backend.tensor_bridge.tensor_to_shm(latents)
                params["latent_image_shm"] = latents_shm
                params["denoise_strength"] = denoise

            # Call bridge server for denoise_only operation
            logger.info("Calling bridge server for denoise_only (CLIP + UNet, no VAE)...")

            try:
                response = backend._send_receive("denoise_only", params)

                # Check response
                if "latents_shm" not in response:
                    raise RuntimeError(f"Bridge did not return latents_shm. Response keys: {list(response.keys())}")

                # Deserialize latents from shared memory
                latents = backend.tensor_bridge.tensor_from_shm(response["latents_shm"])

                logger.info(f"Received latents: shape={latents.shape}, dtype={latents.dtype}")
                logger.info(f"Latent value range: [{latents.min().item():.3f}, {latents.max().item():.3f}]")

                # Return in ComfyUI LATENT format
                # LATENT format: {"samples": tensor [B, C, H, W], "batch_index": [0, 1, ...]}
                batch_size = latents.shape[0]
                result = {
                    "samples": latents,
                    "batch_index": list(range(batch_size))
                }

                logger.info("=" * 80)
                logger.info("TT_DENOISE - Complete! Latents ready for VAE decode")
                logger.info("=" * 80)

                return (result,)

            finally:
                # Clean up input shared memory if we created it
                if latents_shm is not None:
                    backend.tensor_bridge.cleanup_segment(latents_shm["shm_name"])

        except Exception as e:
            logger.error(f"Error in TT_Denoise: {e}", exc_info=True)
            raise RuntimeError(f"TT_Denoise failed: {e}")


class TT_VAEDecode:
    """
    Decode latent tensors to images using Tenstorrent VAE.

    This node accepts LATENT tensors from TT_Denoise, standard KSampler,
    or any other source and decodes them to pixel-space images using
    the VAE on Tenstorrent hardware.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT", {
                    "tooltip": "Latent tensors from TT_Denoise or KSampler"
                }),
                "vae": ("VAE", {
                    "tooltip": "VAE from TT_CheckpointLoader"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    OUTPUT_TOOLTIPS = ("Decoded images in [0, 1] range",)
    FUNCTION = "decode"
    CATEGORY = "Tenstorrent/latent"
    DESCRIPTION = "Decode latent tensors to images using Tenstorrent VAE"

    def decode(self, samples, vae) -> Tuple:
        """
        Decode latent tensors using Tenstorrent VAE.

        Args:
            samples: LATENT dictionary with "samples" tensor [B, C, H, W]
            vae: TTVAEWrapper from TT_CheckpointLoader

        Returns:
            Tuple containing IMAGE tensor [B, H, W, C] in range [0, 1]
        """
        if not hasattr(vae, 'model_id') or not hasattr(vae, 'backend'):
            raise RuntimeError(
                "TT_VAEDecode requires a Tenstorrent VAE from TT_CheckpointLoader."
            )

        logger.info("=" * 80)
        logger.info("TT_VAEDECODE - Starting VAE decode")
        logger.info("=" * 80)
        logger.info(f"VAE: {vae.model_id}")

        try:
            import torch

            backend = vae.backend

            # Extract latents from LATENT format
            if not isinstance(samples, dict) or "samples" not in samples:
                raise RuntimeError(
                    f"TT_VAEDecode requires LATENT format with 'samples' key. "
                    f"Got: {type(samples)}"
                )

            latents = samples["samples"]
            logger.info(f"Input latents shape: {latents.shape}, dtype: {latents.dtype}")
            logger.info(f"Latent value range: [{latents.min().item():.3f}, {latents.max().item():.3f}]")

            # Transfer latents to shared memory
            latents_shm = backend.tensor_bridge.tensor_to_shm(latents)

            # Prepare parameters for bridge server
            params = {
                "model_id": vae.model_id,
                "latents_shm": latents_shm,
            }

            # Call bridge server for vae_decode operation
            logger.info("Calling bridge server for vae_decode...")

            try:
                response = backend._send_receive("vae_decode", params)

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

                # Clamp to [0, 1] range
                images = images.clamp(0.0, 1.0)

                logger.info("=" * 80)
                logger.info("TT_VAEDECODE - Complete!")
                logger.info("=" * 80)

                return (images,)

            finally:
                # Clean up input shared memory
                backend.tensor_bridge.cleanup_segment(latents_shm["shm_name"])

        except Exception as e:
            logger.error(f"Error in TT_VAEDecode: {e}", exc_info=True)
            raise RuntimeError(f"TT_VAEDecode failed: {e}")


class TT_VAEEncode:
    """
    Encode images to latent tensors using Tenstorrent VAE.

    This node accepts pixel-space images and encodes them to latent
    tensors using the VAE on Tenstorrent hardware. Useful for img2img
    workflows where you start from an existing image.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pixels": ("IMAGE", {
                    "tooltip": "Input images from LoadImage or other source"
                }),
                "vae": ("VAE", {
                    "tooltip": "VAE from TT_CheckpointLoader"
                }),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("samples",)
    OUTPUT_TOOLTIPS = ("Encoded latent tensors",)
    FUNCTION = "encode"
    CATEGORY = "Tenstorrent/latent"
    DESCRIPTION = "Encode images to latent tensors using Tenstorrent VAE"

    def encode(self, pixels, vae) -> Tuple:
        """
        Encode images using Tenstorrent VAE.

        Args:
            pixels: IMAGE tensor [B, H, W, C] in range [0, 1] (ComfyUI format)
            vae: TTVAEWrapper from TT_CheckpointLoader

        Returns:
            Tuple containing LATENT dictionary with "samples" tensor
        """
        if not hasattr(vae, 'model_id') or not hasattr(vae, 'backend'):
            raise RuntimeError(
                "TT_VAEEncode requires a Tenstorrent VAE from TT_CheckpointLoader."
            )

        logger.info("=" * 80)
        logger.info("TT_VAEENCODE - Starting VAE encode")
        logger.info("=" * 80)
        logger.info(f"VAE: {vae.model_id}")

        try:
            import torch

            backend = vae.backend

            # Validate input format
            if not isinstance(pixels, torch.Tensor):
                raise RuntimeError(
                    f"TT_VAEEncode requires IMAGE tensor input. Got: {type(pixels)}"
                )

            logger.info(f"Input images shape: {pixels.shape}, dtype: {pixels.dtype}")
            logger.info(f"Image value range: [{pixels.min().item():.3f}, {pixels.max().item():.3f}]")

            # ComfyUI IMAGE format is [B, H, W, C] in range [0, 1]
            # Validate shape
            if pixels.ndim != 4:
                raise RuntimeError(
                    f"TT_VAEEncode expects 4D image tensor [B, H, W, C]. Got shape: {pixels.shape}"
                )

            # Transfer images to shared memory
            images_shm = backend.tensor_bridge.tensor_to_shm(pixels)

            # Prepare parameters for bridge server
            params = {
                "model_id": vae.model_id,
                "images_shm": images_shm,
            }

            # Call bridge server for vae_encode operation
            logger.info("Calling bridge server for vae_encode...")

            try:
                response = backend._send_receive("vae_encode", params)

                # Check response
                if "latents_shm" not in response:
                    raise RuntimeError(f"Bridge did not return latents_shm. Response keys: {list(response.keys())}")

                # Deserialize latents from shared memory
                latents = backend.tensor_bridge.tensor_from_shm(response["latents_shm"])

                logger.info(f"Received latents: shape={latents.shape}, dtype={latents.dtype}")
                logger.info(f"Latent value range: [{latents.min().item():.3f}, {latents.max().item():.3f}]")

                # Return in ComfyUI LATENT format
                # LATENT format: {"samples": tensor [B, C, H, W], "batch_index": [0, 1, ...]}
                batch_size = latents.shape[0]
                result = {
                    "samples": latents,
                    "batch_index": list(range(batch_size))
                }

                logger.info("=" * 80)
                logger.info("TT_VAEENCODE - Complete! Latents ready for denoising")
                logger.info("=" * 80)

                return (result,)

            finally:
                # Clean up input shared memory
                backend.tensor_bridge.cleanup_segment(images_shm["shm_name"])

        except Exception as e:
            logger.error(f"Error in TT_VAEEncode: {e}", exc_info=True)
            raise RuntimeError(f"TT_VAEEncode failed: {e}")
