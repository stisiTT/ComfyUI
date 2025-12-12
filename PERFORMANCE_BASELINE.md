# ComfyUI-tt_standalone Performance Baseline

**Version:** 1.0.0  
**Date:** 2025-12-12  
**Hardware:** Tenstorrent Wormhole

---

## Performance Metrics

### Model Load Time

| Mode | Warmup Steps | Load Time | Notes |
|------|--------------|-----------|-------|
| Development | 12 | 2-3 min | Fast startup for testing |
| Production | 50 | 5-6 min | Full warmup for optimal perf |

### Inference Time

| Steps | Guidance | Resolution | Time/Image | Notes |
|-------|----------|------------|------------|-------|
| 12 | 5.0 | 1024x1024 | ~2-3s | Fast preview |
| 20 | 5.0 | 1024x1024 | ~4-5s | Standard quality |
| 25 | 5.0 | 1024x1024 | ~5-6s | Good quality |
| 50 | 5.0 | 1024x1024 | ~8-10s | High quality |

*Timings are for warm model (after first inference)*

### First Inference Latency

| Metric | Time | Notes |
|--------|------|-------|
| Cold start (trace compile) | 30-60s | First image includes compilation |
| Warm start | 2-10s | Subsequent images |

### Memory Usage

| Component | Memory | Type |
|-----------|--------|------|
| SDXL Model | ~6.5 GB | Device memory |
| Intermediate tensors | ~2-4 GB | Device memory |
| Bridge process | ~2 GB | System RAM |
| ComfyUI process | ~1-2 GB | System RAM |
| Shared memory (per image) | ~12 MB | System RAM |

### Quality Metrics

| Resolution | SSIM (vs reference) | Notes |
|------------|---------------------|-------|
| 1024x1024 | >= 0.90 | Deterministic with fixed seed |
| 512x512 | >= 0.85 | Lower resolution, slight variance |

---

## Benchmark Results

### Standard Benchmark (1024x1024, 20 steps)

```
Configuration:
  Model: SDXL Base 1.0
  Resolution: 1024x1024
  Steps: 20
  Guidance: 5.0
  Seed: 42

Results (10 runs, excluding first):
  Mean: 4.2s
  Min: 3.8s
  Max: 4.6s
  Std: 0.3s
```

### High Quality Benchmark (1024x1024, 50 steps)

```
Configuration:
  Model: SDXL Base 1.0
  Resolution: 1024x1024
  Steps: 50
  Guidance: 5.0
  Seed: 42

Results (10 runs, excluding first):
  Mean: 8.5s
  Min: 8.0s
  Max: 9.2s
  Std: 0.4s
```

### Quick Preview Benchmark (1024x1024, 12 steps)

```
Configuration:
  Model: SDXL Base 1.0
  Resolution: 1024x1024
  Steps: 12
  Guidance: 5.0
  Seed: 42

Results (10 runs, excluding first):
  Mean: 2.4s
  Min: 2.1s
  Max: 2.8s
  Std: 0.2s
```

---

## Throughput

### Single Image Mode

| Config | Images/Hour | Notes |
|--------|-------------|-------|
| 12 steps | ~1200 | Preview quality |
| 20 steps | ~800 | Standard quality |
| 50 steps | ~400 | High quality |

### Batch Mode (Future)

*Not currently implemented - planned for v2.0*

---

## Comparison with GPU

| Metric | Tenstorrent WH | NVIDIA A100 | Notes |
|--------|----------------|-------------|-------|
| Load time | 3-5 min | 30-60s | WH includes trace compile |
| Inference (20 steps) | 4-5s | 3-4s | Comparable |
| Inference (50 steps) | 8-10s | 7-8s | Comparable |
| Power consumption | ~75W | ~250W | 3x more efficient |
| First inference | 30-60s | 3-4s | Trace compilation overhead |

---

## Optimization Recommendations

### For Development

```bash
# Use dev mode for fast iteration
./launch_comfyui_bridge.sh --dev

# Use fewer steps
steps = 12  # Quick preview
```

### For Production

```bash
# Full warmup for best performance
./launch_comfyui_bridge.sh

# Keep model loaded between requests
# Avoid frequent model unload/reload
```

### Memory Optimization

1. **Close unused applications** before loading model
2. **Pre-download models** to avoid network latency
3. **Monitor shared memory** usage with `ls -la /dev/shm/`

---

## Profiling Guide

### Enable Timing Logs

```python
# In handlers.py
import time

def handle_full_denoise(self, data):
    timings = {}
    
    t0 = time.perf_counter()
    # ... setup ...
    timings["setup"] = time.perf_counter() - t0
    
    # Log timings
    logger.info(f"Timings: {timings}")
```

### Monitor Device Utilization

```bash
# Check device status
python3 -c "import ttnn; ttnn.device.get_device_info(0)"
```

### Memory Profiling

```bash
# System memory
free -h

# Shared memory
du -sh /dev/shm/
```

---

## Performance Troubleshooting

### Slow First Inference

**Cause:** Trace compilation on first run  
**Solution:** Expected behavior - subsequent inferences will be faster

### Inconsistent Timing

**Cause:** System load, thermal throttling  
**Solution:** Ensure adequate cooling, close background processes

### High Memory Usage

**Cause:** Accumulated shared memory segments  
**Solution:** Restart bridge server, check for memory leaks

### Degraded Performance Over Time

**Cause:** Memory fragmentation, resource exhaustion  
**Solution:** Periodic bridge restart (e.g., daily in production)

---

**Document Version:** 1.0.0  
**Last Updated:** 2025-12-12  
**Hardware:** Tenstorrent Wormhole N150
