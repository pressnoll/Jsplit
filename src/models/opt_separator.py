import os
import torch
import numpy as np
from typing import Dict, Optional
from pathlib import Path
from src.models.separator import AudioSeparator

class OptimizedPyTorchSeparator(AudioSeparator):
    """
    Optimized native PyTorch engine.
    Uses FP16 (Half Precision) and torch.compile() for massive speedups on both CPU and GPU
    without needing a flaky ONNX export.
    """
    def __init__(self, model_name: str = "htdemucs_ft", device: Optional[str] = None):
        super().__init__(model_name=model_name, device=device)
        
        print(f"[Opt-PyTorch] Applying hardware optimizations for {self.device}...")
        
        # 1. Hardware-Specific Precision & Quantization
        if "cuda" in self.device:
            # GPU: Use FP16 (Half Precision) for Tensor Cores
            print("[Opt-PyTorch] Applying FP16 precision for GPU...")
            self.model = self.model.half()
        else:
            # CPU: Use INT8 Dynamic Quantization (Massive speedup on standard CPUs)
            print("[Opt-PyTorch] Applying INT8 Dynamic Quantization for CPU...")
            import torch.ao.quantization
            # We quantize the heavy Linear and LSTM layers to 8-bit integers
            self.model = torch.ao.quantization.quantize_dynamic(
                self.model,
                {torch.nn.Linear, torch.nn.LSTM, torch.nn.GRU},
                dtype=torch.qint8
            )
            # Optimize CPU thread count (prevents context switching overhead)
            num_cores = os.cpu_count() or 4
            torch.set_num_threads(max(1, num_cores - 1))
            
        # 2. Torch Compile (Graph Optimization / Fusion)
        # Note: torch.compile can take a minute on first run, but provides 2x speedup.
        try:
            print("[Opt-PyTorch] Compiling model graph (this takes a moment)...")
            # We use backend='aot_eager' or 'inductor' depending on OS compatibility
            backend = "inductor" if os.name != "nt" else "aot_eager" 
            self.model = torch.compile(self.model, backend=backend, fullgraph=False)
            print("[Opt-PyTorch] Compilation successful.")
        except Exception as e:
            print(f"[Opt-PyTorch] torch.compile skipped: {e}")

    def separate(self, waveform: torch.Tensor, shifts: int = 1) -> Dict[str, torch.Tensor]:
        # Convert waveform to half precision if using GPU
        if "cuda" in self.device:
            waveform = waveform.half()
            
        # Run separation
        with torch.no_grad(), torch.autocast(device_type="cuda" if "cuda" in self.device else "cpu"):
            result = super().separate(waveform, shifts=shifts)
            
        # Convert back to float32 for post-processing and saving
        return {k: v.float() for k, v in result.items()}
