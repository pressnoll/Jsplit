"""
Evaluate already-separated stems (reference-free) — great for A/B'ing the old
pipeline's output against Jsplit's, or scoring any folder of stems.

Usage:
  # score a folder of stems against the original mix
  python scripts/evaluate.py --mix song.mp3 --stems outputs_jsplit/song

  # if you have ground-truth stems (e.g. MUSDB), add SI-SDR:
  python scripts/evaluate.py --mix song.wav --stems out/song --reference truth/song
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch

from src.audio.io import load_audio
from src.quality import metrics

AUDIO_EXT = {".wav", ".flac", ".mp3", ".m4a", ".ogg"}


def _load_dir(folder: str, sr: int):
    stems = {}
    for f in sorted(Path(folder).iterdir()):
        if f.suffix.lower() in AUDIO_EXT:
            wav, _ = load_audio(str(f), target_sr=sr, channels=2, device="cpu")
            stems[f.stem] = wav
    return stems


def main():
    p = argparse.ArgumentParser(description="Evaluate saved stems")
    p.add_argument("--mix", required=True, help="original mix file")
    p.add_argument("--stems", required=True, help="folder of separated stems")
    p.add_argument("--reference", default=None, help="folder of ground-truth stems (enables SI-SDR)")
    p.add_argument("--sr", type=int, default=44100)
    args = p.parse_args()

    mix, sr = load_audio(args.mix, target_sr=args.sr, channels=2, device="cpu")
    stems = _load_dir(args.stems, sr)
    if not stems:
        print(f"No audio stems found in {args.stems}")
        return
    references = _load_dir(args.reference, sr) if args.reference else None

    report = metrics.full_report(mix, stems, sr=sr, references=references)
    metrics.print_report(report)


if __name__ == "__main__":
    main()
