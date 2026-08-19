"""
Jsplit benchmark harness — turns "optimization" from guesswork into numbers.

Reports, per quality tier, on a fixed-length slice of your song:
  - wall time
  - RTF (real-time factor) = audio_seconds / process_seconds   (>1 = faster than realtime)
  - peak RAM (if psutil is installed)
  - device + thread count

Usage:
  python scripts/benchmark.py -i song.mp3 --duration 20 --tiers fast balanced full
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from src.engine import StemSplitter, QUALITY_TIERS
from src.audio.io import load_audio


def _peak_ram_mb():
    try:
        import psutil, os
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description="Benchmark Jsplit engines")
    p.add_argument("--input", "-i", required=True)
    p.add_argument("--duration", type=float, default=20.0, help="slice length to benchmark on")
    p.add_argument("--start", type=float, default=30.0, help="slice start (skip intros)")
    p.add_argument("--shifts", type=int, default=1)
    p.add_argument("--tiers", nargs="+", default=["fast", "balanced"], choices=list(QUALITY_TIERS))
    p.add_argument("--device", default=None)
    args = p.parse_args()

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    print("=" * 64)
    print(f"Device: {device} | torch: {torch.__version__} | threads: {torch.get_num_threads()}")
    print(f"Slice : {args.duration}s @ start {args.start}s | shifts={args.shifts}")
    print("=" * 64)

    rows = []
    for tier in args.tiers:
        print(f"\n--- Benchmarking tier: {tier} ---")
        try:
            splitter = StemSplitter(quality=tier, device=device)
            sr = splitter.sample_rate
            wav, _ = load_audio(args.input, target_sr=sr, channels=2, device=device)
            s0 = int(args.start * sr)
            wav = wav[..., s0:s0 + int(args.duration * sr)]
            audio_sec = wav.shape[-1] / sr

            t0 = time.perf_counter()
            stems = splitter.separate(wav, shifts=args.shifts)
            elapsed = time.perf_counter() - t0

            rows.append({
                "tier": tier,
                "elements": len(stems),
                "sec": round(elapsed, 1),
                "rtf": round(audio_sec / elapsed, 2),
                "ram_mb": round(_peak_ram_mb() or 0),
            })
        except Exception as e:
            rows.append({"tier": tier, "elements": "-", "sec": "-", "rtf": "-", "ram_mb": f"ERR: {e}"})

    print("\n" + "=" * 64)
    print(f"{'tier':<10}{'elems':<7}{'time(s)':<9}{'RTF':<7}{'RAM(MB)':<10}")
    print("-" * 64)
    for r in rows:
        print(f"{r['tier']:<10}{str(r['elements']):<7}{str(r['sec']):<9}{str(r['rtf']):<7}{str(r['ram_mb']):<10}")
    print("=" * 64)
    print("RTF > 1.0 = faster than real time. To estimate a full 4-min song:")
    for r in rows:
        if isinstance(r["rtf"], float) and r["rtf"] > 0:
            print(f"  {r['tier']:<10} ~{round(240 / r['rtf'])}s for a 4-min track")


if __name__ == "__main__":
    main()
