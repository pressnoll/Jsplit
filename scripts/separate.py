import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import StudioStemSplitter

def main():
    parser = argparse.ArgumentParser(
        description="Studio-Grade AI Audio Stem Splitter (Phase 2: Clarity-Focused)"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Path to the input audio file (WAV, MP3, FLAC, M4A)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="outputs",
        help="Directory to save separated stems (default: outputs/)"
    )
    parser.add_argument(
        "--engine", "-e",
        type=str,
        default="hybrid",
        choices=["demucs", "demucs_ft", "demucs_6s", "roformer", "hybrid", "onnx", "opt_pytorch"],
        help="Separation engine. 'hybrid' uses RoFormer+Demucs. 'opt_pytorch' uses FP16/compile for speed."
    )
    parser.add_argument(
        "--no-refine",
        action="store_true",
        help="Disable spectral refinement (gate, inpaint, phase smooth)"
    )
    parser.add_argument(
        "--shifts",
        type=int,
        default=1,
        help="Random shifts for equivariant quality (higher = cleaner, slower)"
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Apply peak normalization to output stems"
    )

    args = parser.parse_args()

    splitter = StudioStemSplitter(
        engine=args.engine,
        enhance_clarity=not args.no_refine
    )

    result = splitter.process_file(
        input_file=args.input,
        output_dir=args.output,
        shifts=args.shifts,
        normalize=args.normalize
    )

    print("\n==========================================")
    print(f"[DONE] Separation Complete: {result['track_name']}")
    print(f"[ENGINE] {result['engine']}")
    print(f"[DIR] {result['output_directory']}")
    print("Diagnostics:")
    for k, v in result['diagnostics'].items():
        print(f"   - {k}: {v}")
    print("==========================================")

if __name__ == "__main__":
    main()
