#!/usr/bin/env python3
"""
Integration Validation Script for ComfyUI-tt_standalone

This script tests the end-to-end workflow:
1. Connect to bridge server
2. Initialize SDXL model
3. Run inference
4. Verify output quality

Usage:
    python test_workflow.py [--quick] [--ssim-threshold 0.90]

Prerequisites:
    - Bridge server running: ./launch_comfyui_bridge.sh
    - ComfyUI (optional): python main.py --listen 0.0.0.0 --port 8188
"""

import argparse
import sys
import time
import os
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_bridge_connection():
    """Test 1: Verify bridge server connection."""
    logger.info("=" * 60)
    logger.info("TEST 1: Bridge Server Connection")
    logger.info("=" * 60)
    
    try:
        # Add path for backend import
        sys.path.insert(0, str(Path(__file__).parent / "comfy"))
        from backends.tenstorrent_backend import TenstorrentBackend
        
        backend = TenstorrentBackend()
        
        # Ping server
        result = backend.ping()
        
        logger.info(f"  Status: {result.get('status')}")
        logger.info(f"  Model loaded: {result.get('model_loaded')}")
        
        assert result.get("status") == "ok", "Ping failed"
        logger.info("  PASSED: Bridge connection successful")
        
        return backend, True
        
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return None, False


def test_model_initialization(backend, model_type="sdxl"):
    """Test 2: Initialize model on device."""
    logger.info("=" * 60)
    logger.info("TEST 2: Model Initialization")
    logger.info("=" * 60)
    
    try:
        start_time = time.time()
        
        # Check if model already loaded
        ping_result = backend.ping()
        if ping_result.get("model_loaded"):
            model_id = ping_result.get("model_id")
            logger.info(f"  Model already loaded: {model_id}")
            return model_id, True
        
        logger.info(f"  Initializing {model_type} model...")
        logger.info("  (This may take 3-5 minutes for first load)")
        
        model_id = backend.init_model(model_type)
        
        elapsed = time.time() - start_time
        logger.info(f"  Model ID: {model_id}")
        logger.info(f"  Load time: {elapsed:.1f}s")
        
        assert model_id is not None, "Model initialization returned None"
        logger.info("  PASSED: Model initialized successfully")
        
        return model_id, True
        
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return None, False


def test_inference(backend, model_id, quick_mode=False):
    """Test 3: Run inference and generate image."""
    logger.info("=" * 60)
    logger.info("TEST 3: Image Generation")
    logger.info("=" * 60)
    
    try:
        import torch
        
        # Test parameters
        params = {
            "prompt": "a beautiful mountain landscape at sunset, golden hour lighting, dramatic clouds, 8k, highly detailed",
            "negative_prompt": "blurry, low quality, distorted, ugly, watermark",
            "num_inference_steps": 12 if quick_mode else 20,
            "guidance_scale": 5.0,
            "width": 1024,
            "height": 1024,
            "seed": 42
        }
        
        logger.info(f"  Prompt: {params['prompt'][:50]}...")
        logger.info(f"  Steps: {params['num_inference_steps']}")
        logger.info(f"  Size: {params['width']}x{params['height']}")
        logger.info(f"  Seed: {params['seed']}")
        
        start_time = time.time()
        
        result = backend.full_denoise(model_id=model_id, **params)
        
        elapsed = time.time() - start_time
        logger.info(f"  Inference time: {elapsed:.2f}s")
        
        # Check result
        assert "images_shm" in result, f"No images_shm in result: {result.keys()}"
        
        # Read image from shared memory
        images = backend.tensor_bridge.tensor_from_shm(result["images_shm"])
        
        logger.info(f"  Image shape: {images.shape}")
        logger.info(f"  Image dtype: {images.dtype}")
        logger.info(f"  Value range: [{images.min():.3f}, {images.max():.3f}]")
        
        # Validate image
        assert images.ndim == 4, f"Expected 4D tensor, got {images.ndim}D"
        assert images.shape[0] == 1, f"Expected batch size 1, got {images.shape[0]}"
        assert images.shape[1] == params["height"], f"Height mismatch"
        assert images.shape[2] == params["width"], f"Width mismatch"
        assert images.shape[3] == 3, f"Expected 3 channels, got {images.shape[3]}"
        
        # Save output image
        output_path = Path(__file__).parent / "output" / "test_validation.png"
        output_path.parent.mkdir(exist_ok=True)
        
        # Convert to PIL and save
        from PIL import Image
        import numpy as np
        
        img_np = (images[0].numpy() * 255).astype(np.uint8)
        img = Image.fromarray(img_np)
        img.save(str(output_path))
        
        logger.info(f"  Saved to: {output_path}")
        logger.info("  PASSED: Image generation successful")
        
        return images, output_path, True
        
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None, None, False


def test_image_quality(image_path, ssim_threshold=0.90):
    """Test 4: Validate image quality (basic checks)."""
    logger.info("=" * 60)
    logger.info("TEST 4: Image Quality Validation")
    logger.info("=" * 60)
    
    try:
        from PIL import Image
        import numpy as np
        
        img = Image.open(image_path)
        img_np = np.array(img)
        
        # Basic quality checks
        checks = []
        
        # Check 1: Image dimensions
        if img.size == (1024, 1024):
            checks.append(("Dimensions", True, "1024x1024"))
        else:
            checks.append(("Dimensions", False, f"{img.size}"))
        
        # Check 2: Non-uniform (not all black/white)
        std_dev = img_np.std()
        if std_dev > 10:
            checks.append(("Non-uniform", True, f"std={std_dev:.1f}"))
        else:
            checks.append(("Non-uniform", False, f"std={std_dev:.1f}"))
        
        # Check 3: Reasonable value distribution
        mean_val = img_np.mean()
        if 20 < mean_val < 235:
            checks.append(("Value range", True, f"mean={mean_val:.1f}"))
        else:
            checks.append(("Value range", False, f"mean={mean_val:.1f}"))
        
        # Check 4: All channels have variation
        channel_stds = [img_np[:,:,c].std() for c in range(3)]
        if all(s > 5 for s in channel_stds):
            checks.append(("Channel variance", True, f"stds={[f'{s:.1f}' for s in channel_stds]}"))
        else:
            checks.append(("Channel variance", False, f"stds={[f'{s:.1f}' for s in channel_stds]}"))
        
        # Report results
        all_passed = True
        for name, passed, details in checks:
            status = "PASS" if passed else "FAIL"
            logger.info(f"  [{status}] {name}: {details}")
            if not passed:
                all_passed = False
        
        # SSIM comparison (if reference available)
        reference_path = Path(__file__).parent / "reference_images" / "test_validation_ref.png"
        if reference_path.exists():
            try:
                from skimage.metrics import structural_similarity as ssim
                
                ref_img = np.array(Image.open(reference_path))
                ssim_score = ssim(img_np, ref_img, channel_axis=2)
                
                if ssim_score >= ssim_threshold:
                    logger.info(f"  [PASS] SSIM: {ssim_score:.4f} >= {ssim_threshold}")
                else:
                    logger.info(f"  [FAIL] SSIM: {ssim_score:.4f} < {ssim_threshold}")
                    all_passed = False
                    
            except ImportError:
                logger.info("  [SKIP] SSIM: skimage not available")
        else:
            logger.info(f"  [SKIP] SSIM: No reference image at {reference_path}")
            logger.info(f"         (Copy generated image there to enable SSIM checks)")
        
        if all_passed:
            logger.info("  PASSED: Image quality acceptable")
        else:
            logger.warning("  WARNING: Some quality checks failed")
        
        return all_passed
        
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return False


def test_cleanup(backend, model_id):
    """Test 5: Clean up resources."""
    logger.info("=" * 60)
    logger.info("TEST 5: Resource Cleanup")
    logger.info("=" * 60)
    
    try:
        # Note: We don't unload the model by default to keep it warm for further tests
        # Uncomment below to test unload:
        # backend.unload_model(model_id)
        # logger.info(f"  Unloaded model {model_id}")
        
        # Just verify connection is still good
        result = backend.ping()
        assert result.get("status") == "ok"
        
        logger.info("  Connection healthy after tests")
        logger.info("  PASSED: Cleanup successful")
        
        return True
        
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return False


def run_validation(quick_mode=False, ssim_threshold=0.90):
    """Run complete validation suite."""
    logger.info("=" * 60)
    logger.info("ComfyUI-tt_standalone Integration Validation")
    logger.info("=" * 60)
    logger.info(f"Mode: {'Quick' if quick_mode else 'Full'}")
    logger.info(f"SSIM threshold: {ssim_threshold}")
    logger.info("")
    
    results = {}
    
    # Test 1: Bridge connection
    backend, success = test_bridge_connection()
    results["bridge_connection"] = success
    
    if not success:
        logger.error("\nBridge connection failed. Is the server running?")
        logger.error("Start with: ./launch_comfyui_bridge.sh")
        return results
    
    # Test 2: Model initialization
    model_id, success = test_model_initialization(backend)
    results["model_init"] = success
    
    if not success:
        logger.error("\nModel initialization failed. Check device availability.")
        return results
    
    # Test 3: Inference
    images, output_path, success = test_inference(backend, model_id, quick_mode)
    results["inference"] = success
    
    if not success:
        logger.error("\nInference failed. Check logs for details.")
        return results
    
    # Test 4: Image quality
    success = test_image_quality(output_path, ssim_threshold)
    results["quality"] = success
    
    # Test 5: Cleanup
    success = test_cleanup(backend, model_id)
    results["cleanup"] = success
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        logger.info(f"  {test_name}: {status}")
        if not passed:
            all_passed = False
    
    logger.info("")
    if all_passed:
        logger.info("OVERALL: ALL TESTS PASSED")
    else:
        logger.info("OVERALL: SOME TESTS FAILED")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Integration validation for ComfyUI-tt_standalone"
    )
    parser.add_argument(
        "--quick", "-q",
        action="store_true",
        help="Quick mode (fewer inference steps)"
    )
    parser.add_argument(
        "--ssim-threshold",
        type=float,
        default=0.90,
        help="SSIM threshold for quality check (default: 0.90)"
    )
    
    args = parser.parse_args()
    
    results = run_validation(
        quick_mode=args.quick,
        ssim_threshold=args.ssim_threshold
    )
    
    # Exit with appropriate code
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
