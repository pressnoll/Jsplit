"""
Jsplit CLI — clarity-first stem separation.

Examples
--------
# Best clarity + most elements (RoFormer vocal + 6-stem Demucs):
python scripts/split.py -i song.mp3 --quality max

# 6 elements, faster:
python scripts/split.py -i song.mp3 --quality full

# Quick 20s test slice with full diagnostics:
python scripts/split.py -i song.mp3 --quality balanced --duration 20
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import StemSplitter, QUALITY_TIERS


def main():
    p = argparse.ArgumentParser(description="Jsplit — clarity-first AI stem splitter")
    p.add_argument("--input", "-i", required=True, help="input audio (wav/mp3/flac/m4a)")
    p.add_argument("--output", "-o", default="outputs_jsplit", help="output directory")
    p.add_argument("--quality", "-q", default="full", choices=list(QUALITY_TIERS),
                   help="fast=4stem quick | balanced=4stem ft | full=6stem | max=6stem+RoFormer vocal")
    p.add_argument("--model", default=None, help="override Demucs model (e.g. htdemucs_ft)")
    p.add_argument("--roformer-vocals", dest="roformer_vocals", action="store_true", default=None,
                   help="force RoFormer vocal replacement on any tier")
    p.add_argument("--shifts", type=int, default=1, help="test-time shifts (higher=cleaner, slower)")
    p.add_argument("--stems", default=None,
                   help="comma-separated stems to export (e.g. vocals,drums). Default: all.")
    p.add_argument("--start", type=float, default=0.0, help="start seconds (for slicing)")
    p.add_argument("--duration", type=float, default=None, help="seconds to process (for quick tests)")
    p.add_argument("--device", default=None, help="cpu | cuda (auto-detect if omitted)")
    p.add_argument("--no-metrics", action="store_true", help="skip quality diagnostics")
    p.add_argument("--json", action="store_true", help="print the result as JSON at the end")
    args = p.parse_args()

    splitter = StemSplitter(
        quality=args.quality,
        device=args.device,
        model=args.model,
        roformer_vocals=args.roformer_vocals,
    )
    keep = None
    if args.stems:
        keep = [s.strip() for s in args.stems.split(",") if s.strip()]

    result = splitter.process_file(
        input_file=args.input,
        output_dir=args.output,
        shifts=args.shifts,
        start=args.start,
        duration=args.duration,
        run_metrics=not args.no_metrics,
        keep_stems=keep,
    )

    print(f"[DONE] {len(result['stems'])} elements -> {result['output_dir']}")
    print(f"       elements: {', '.join(result['stems'].keys())}")
    # Stable, machine-parseable line for the VST bridge to read from stdout:
    print(f"JSPLIT_OUTPUT_DIR={result['output_dir']}")
    if args.json:
        print(json.dumps(result.get("metrics", {}), indent=2))


if __name__ == "__main__":
    main()
