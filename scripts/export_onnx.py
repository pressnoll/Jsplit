"""
ONNX Export Utility for Stem Separation Models.

Exports PyTorch models (Demucs, RoFormer) to ONNX format for
hardware-accelerated inference on CPU (INT8), GPU (FP16/TensorRT),
and Apple Silicon (CoreML).
"""
import os
import sys
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def export_demucs_to_onnx(
    model_name: str = "htdemucs",
    output_dir: str = "models/onnx",
    chunk_seconds: float = 8.0,
    sample_rate: int = 44100,
    opset_version: int = 17
):
    """
    Export a Demucs model to ONNX format.
    
    The exported model takes a stereo audio chunk and outputs
    separated stems (drums, bass, other, vocals).
    """
    from demucs.pretrained import get_model

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Export] Loading Demucs model '{model_name}'...")
    bag = get_model(model_name)
    model = bag.models[0]
    model.eval()
    model.cpu()

    # Create a wrapper that simplifies the model's interface for ONNX
    class DemucsONNXWrapper(nn.Module):
        def __init__(self, demucs_model):
            super().__init__()
            self.model = demucs_model

        def forward(self, x):
            # x: [batch, channels, samples]
            # output: [batch, num_sources, channels, samples]
            return self.model(x)

    wrapper = DemucsONNXWrapper(model)
    wrapper.eval()

    # Create dummy input: [batch=1, channels=2, samples]
    chunk_samples = int(chunk_seconds * sample_rate)
    dummy_input = torch.randn(1, 2, chunk_samples)

    output_path = out_dir / f"{model_name}.onnx"
    print(f"[Export] Exporting to ONNX (opset {opset_version})...")
    print(f"[Export] Chunk size: {chunk_samples} samples ({chunk_seconds}s)")

    try:
        torch.onnx.export(
            wrapper,
            dummy_input,
            str(output_path),
            input_names=["audio_input"],
            output_names=["stems_output"],
            dynamic_axes={
                "audio_input": {0: "batch", 2: "audio_length"},
                "stems_output": {0: "batch", 3: "audio_length"}
            },
            opset_version=opset_version,
            do_constant_folding=True,
        )
        print(f"[OK] Exported: {output_path}")
        print(f"[OK] File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
        return str(output_path)

    except Exception as e:
        print(f"[ERROR] ONNX export failed: {e}")
        print("[INFO] Trying with fixed input shape (no dynamic axes)...")

        # Fallback: fixed shape export
        torch.onnx.export(
            wrapper,
            dummy_input,
            str(output_path),
            input_names=["audio_input"],
            output_names=["stems_output"],
            opset_version=opset_version,
            do_constant_folding=True,
        )
        print(f"[OK] Exported (fixed shape): {output_path}")
        print(f"[OK] File size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
        return str(output_path)


def quantize_onnx_int8(
    onnx_model_path: str,
    output_path: str = None,
):
    """
    Apply INT8 dynamic quantization to an ONNX model for
    maximum CPU inference speed (3-4x faster than FP32).
    """
    from onnxruntime.quantization import quantize_dynamic, QuantType

    if output_path is None:
        p = Path(onnx_model_path)
        output_path = str(p.parent / f"{p.stem}_int8{p.suffix}")

    print(f"[Quantize] INT8 dynamic quantization: {onnx_model_path}")
    quantize_dynamic(
        model_input=onnx_model_path,
        model_output=output_path,
        weight_type=QuantType.QInt8,
    )
    
    orig_size = Path(onnx_model_path).stat().st_size / 1024 / 1024
    quant_size = Path(output_path).stat().st_size / 1024 / 1024
    print(f"[OK] Quantized: {output_path}")
    print(f"[OK] Size: {orig_size:.1f}MB -> {quant_size:.1f}MB ({quant_size/orig_size*100:.0f}%)")
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export stem separation models to ONNX")
    parser.add_argument("--model", default="htdemucs", choices=["htdemucs", "htdemucs_ft", "htdemucs_6s"])
    parser.add_argument("--output-dir", default="models/onnx")
    parser.add_argument("--quantize", action="store_true", help="Also create INT8 quantized version")
    parser.add_argument("--chunk-seconds", type=float, default=8.0)
    args = parser.parse_args()

    onnx_path = export_demucs_to_onnx(
        model_name=args.model,
        output_dir=args.output_dir,
        chunk_seconds=args.chunk_seconds
    )

    if args.quantize and onnx_path:
        quantize_onnx_int8(onnx_path)
