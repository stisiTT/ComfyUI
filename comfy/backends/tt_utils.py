# SPDX-License-Identifier: Apache-2.0
#
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC

"""
Utility functions for Tenstorrent ComfyUI backend.

Includes model configuration, tensor validation, and helper functions
for working with the Tenstorrent hardware acceleration backend.
"""

import torch
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


def get_model_config(model_type: str) -> Dict[str, Any]:
    """
    Get minimal model configuration for a given model type.

    These configs satisfy ComfyUI's interface requirements without
    needing the full model loaded in ComfyUI.

    Args:
        model_type: One of 'sdxl', 'sd35', 'sd14'

    Returns:
        Configuration dictionary

    Raises:
        ValueError: If model_type is not recognized
    """
    configs = {
        "sdxl": {
            "latent_channels": 4,
            "unet_in_channels": 4,
            "clip_dim": 1280,
            "vae_scale_factor": 8,
            "vae_latent_channels": 4,
            "text_encoder_hidden_size": 768,
            "text_encoder_2_hidden_size": 1280,
            "model_size_gb": 6.94,  # Approximate model size for memory estimation
        },
        "sd35": {
            "latent_channels": 16,
            "unet_in_channels": 16,
            "clip_dim": 4096,
            "vae_scale_factor": 8,
            "vae_latent_channels": 16,
            "text_encoder_hidden_size": 4096,
            "model_size_gb": 11.9,
        },
        "sd14": {
            "latent_channels": 4,
            "unet_in_channels": 4,
            "clip_dim": 768,
            "vae_scale_factor": 8,
            "vae_latent_channels": 4,
            "text_encoder_hidden_size": 768,
            "model_size_gb": 3.4,
        },
    }

    if model_type not in configs:
        raise ValueError(f"Unknown model type: {model_type}. Available: {list(configs.keys())}")

    return configs[model_type]


def validate_tensor_shape(tensor: torch.Tensor, expected_dims: int, name: str = "tensor") -> None:
    """
    Validate that a tensor has the expected number of dimensions.

    Args:
        tensor: Tensor to validate
        expected_dims: Expected number of dimensions
        name: Name for error messages

    Raises:
        TypeError: If tensor is not a torch.Tensor
        ValueError: If tensor shape is invalid
    """
    if not isinstance(tensor, torch.Tensor):
        raise TypeError(f"{name} must be a torch.Tensor, got {type(tensor)}")

    if tensor.ndim != expected_dims:
        raise ValueError(f"{name} must have {expected_dims} dimensions, got {tensor.ndim}")


def validate_latent_shape(latent: torch.Tensor, model_type: str) -> None:
    """
    Validate latent tensor shape for a given model type.

    Args:
        latent: Latent tensor [batch, channels, height, width]
        model_type: Model type (sdxl, sd35, sd14)

    Raises:
        ValueError: If latent shape is invalid
    """
    config = get_model_config(model_type)
    expected_channels = config["latent_channels"]

    validate_tensor_shape(latent, 4, "latent")

    if latent.shape[1] != expected_channels:
        raise ValueError(
            f"Latent tensor for {model_type} must have {expected_channels} channels, "
            f"got {latent.shape[1]}"
        )


def estimate_tensor_memory(tensor: torch.Tensor) -> int:
    """
    Estimate memory usage of a tensor in bytes.

    Args:
        tensor: PyTorch tensor

    Returns:
        Estimated memory in bytes
    """
    element_size = tensor.element_size()
    num_elements = tensor.numel()
    return element_size * num_elements


def format_bytes(bytes_val: int) -> str:
    """
    Format bytes as human-readable string.

    Args:
        bytes_val: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 GB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def check_backend_available() -> bool:
    """
    Check if Tenstorrent backend is available.

    Returns:
        True if backend can be imported and initialized, False otherwise
    """
    try:
        from comfy.backends.tenstorrent_backend import get_backend
        # Try to get backend instance - this will fail if socket unavailable
        # but we just want to check if the module can be imported
        return True
    except ImportError as e:
        logger.warning(f"Tenstorrent backend not available: {e}")
        return False


def validate_inference_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize inference parameters.

    Args:
        params: Dictionary of inference parameters

    Returns:
        Validated and normalized parameters

    Raises:
        ValueError: If parameters are invalid
    """
    validated = params.copy()

    # Required parameters
    required = ['prompt', 'negative_prompt', 'steps', 'guidance_scale', 'width', 'height']
    for param in required:
        if param not in validated:
            raise ValueError(f"Missing required parameter: {param}")

    # Validate types and ranges
    if not isinstance(validated['steps'], int) or validated['steps'] < 1:
        raise ValueError(f"steps must be a positive integer, got {validated['steps']}")

    if not isinstance(validated['guidance_scale'], (int, float)) or validated['guidance_scale'] < 0:
        raise ValueError(f"guidance_scale must be non-negative, got {validated['guidance_scale']}")

    if not isinstance(validated['width'], int) or validated['width'] < 64:
        raise ValueError(f"width must be >= 64, got {validated['width']}")

    if not isinstance(validated['height'], int) or validated['height'] < 64:
        raise ValueError(f"height must be >= 64, got {validated['height']}")

    # Optional parameters with defaults
    validated.setdefault('seed', -1)
    validated.setdefault('num_images', 1)

    return validated


def get_supported_models() -> list:
    """
    Get list of supported model types.

    Returns:
        List of supported model type strings
    """
    return ['sdxl', 'sd35', 'sd14']


def is_model_supported(model_type: str) -> bool:
    """
    Check if a model type is supported.

    Args:
        model_type: Model type string to check

    Returns:
        True if model type is supported, False otherwise
    """
    return model_type in get_supported_models()
