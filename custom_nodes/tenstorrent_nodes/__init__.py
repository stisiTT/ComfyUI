"""
Tenstorrent ComfyUI Nodes

Provides integration with Tenstorrent hardware via bridge server.
Implements custom nodes for SDXL inference on Tenstorrent accelerators.
"""

from .nodes import (
    TT_CheckpointLoader,
    TT_FullDenoise,
    TT_ModelInfo,
    TT_UnloadModel,
    TT_Denoise,
    TT_VAEDecode,
    TT_VAEEncode
)

NODE_CLASS_MAPPINGS = {
    "TT_CheckpointLoader": TT_CheckpointLoader,
    "TT_FullDenoise": TT_FullDenoise,
    "TT_ModelInfo": TT_ModelInfo,
    "TT_UnloadModel": TT_UnloadModel,
    "TT_Denoise": TT_Denoise,
    "TT_VAEDecode": TT_VAEDecode,
    "TT_VAEEncode": TT_VAEEncode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TT_CheckpointLoader": "TT Checkpoint Loader",
    "TT_FullDenoise": "TT Full Denoise",
    "TT_ModelInfo": "TT Model Info",
    "TT_UnloadModel": "TT Unload Model",
    "TT_Denoise": "TT Denoise (Latents)",
    "TT_VAEDecode": "TT VAE Decode",
    "TT_VAEEncode": "TT VAE Encode",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
