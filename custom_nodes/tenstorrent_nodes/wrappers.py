"""
Wrapper classes for Tenstorrent hardware models.

These lightweight wrappers store model metadata and provide the interface
expected by ComfyUI nodes. Actual inference is handled by the bridge server.
"""

import torch
import logging
from typing import Dict, Any
from .utils import get_model_config, format_bytes

logger = logging.getLogger(__name__)


class TTModelWrapper:
    """
    Lightweight wrapper for Tenstorrent UNet/DiT models.

    Stores model ID and metadata. Does not implement the full ModelPatcher
    interface - actual inference is handled by TT_FullDenoise node.
    """

    def __init__(self, model_id: str, backend, model_type: str):
        """
        Initialize model wrapper.

        Args:
            model_id: Model identifier from bridge server
            backend: TenstorrentBackend instance
            model_type: Model type (sdxl, sd35, sd14)
        """
        self.model_id = model_id
        self.backend = backend
        self.model_type = model_type
        self.config = get_model_config(model_type)

        logger.info(f"Initialized TTModelWrapper for {model_type} (ID: {model_id})")

    def model_size(self) -> int:
        """
        Estimate model size in bytes.

        Returns:
            Estimated size in bytes
        """
        size_gb = self.config.get("model_size_gb", 7.0)
        return int(size_gb * 1024 * 1024 * 1024)

    def __repr__(self) -> str:
        return f"TTModelWrapper(model_id={self.model_id}, type={self.model_type})"


class TTCLIPWrapper:
    """
    Lightweight wrapper for Tenstorrent CLIP text encoders.

    Stores model ID and metadata. Text encoding is handled by the bridge server
    as part of the full_denoise operation.
    """

    def __init__(self, model_id: str, backend, model_type: str):
        """
        Initialize CLIP wrapper.

        Args:
            model_id: Model identifier from bridge server
            backend: TenstorrentBackend instance
            model_type: Model type (sdxl, sd35, sd14)
        """
        self.model_id = model_id
        self.backend = backend
        self.model_type = model_type
        self.config = get_model_config(model_type)

        logger.info(f"Initialized TTCLIPWrapper for {model_type} (ID: {model_id})")

    def __repr__(self) -> str:
        return f"TTCLIPWrapper(model_id={self.model_id}, type={self.model_type})"


class TTVAEWrapper:
    """
    Lightweight wrapper for Tenstorrent VAE encoder/decoder.

    Stores model ID and metadata. VAE decoding is handled by the bridge server
    as part of the full_denoise operation (which returns final images).
    """

    def __init__(self, model_id: str, backend, model_type: str):
        """
        Initialize VAE wrapper.

        Args:
            model_id: Model identifier from bridge server
            backend: TenstorrentBackend instance
            model_type: Model type (sdxl, sd35, sd14)
        """
        self.model_id = model_id
        self.backend = backend
        self.model_type = model_type
        self.config = get_model_config(model_type)

        logger.info(f"Initialized TTVAEWrapper for {model_type} (ID: {model_id})")

    def __repr__(self) -> str:
        return f"TTVAEWrapper(model_id={self.model_id}, type={self.model_type})"
