"""
Jsplit clarity-first separation engine.

Design principles (in priority order, matching the project goals):

1. CLARITY  -> use the best model per source. Kim Mel-Band RoFormer for vocals
   (cleaner, less "hollow" than Demucs vocals), HTDemucs for everything else.
2. ELEMENTS -> `full`/`max` use htdemucs_6s: vocals, drums, bass, guitar, piano,
   other  (6 elements). RoFormer replaces the vocal with a cleaner one.
3. NO HOLLOW / NO BROKEN -> we do NOT apply spectral gating, phase-vocoder
   smoothing, or "harmonic inpainting". Those are the classic causes of
   underwater/hollow artifacts. Instead we trust the model and construct the
   stem set so that sum(stems) == mix (nothing is discarded). The residual of
   the vocal-remover is folded back into `other`, so no energy goes missing.
4. OPTIMIZATION -> tiers trade quality for speed; device auto-detects CUDA;
   overlap/shifts are exposed. See scripts/benchmark.py for measurement.

There is deliberately no default post-processing. `conservative_cleanup()` is
available and OFF by default; it only does safe, reversible things.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import torch

from src.audio.io import load_audio, save_audio
from src.models.separator import AudioSeparator


# tier -> config. `roformer_vocals` swaps the Demucs vocal for the RoFormer one.
QUALITY_TIERS: Dict[str, dict] = {
    "fast":     {"model": "htdemucs",    "overlap": 0.10, "roformer_vocals": False},
    "balanced": {"model": "htdemucs_ft", "overlap": 0.25, "roformer_vocals": False},
    "full":     {"model": "htdemucs_6s", "overlap": 0.25, "roformer_vocals": False},
    "max":      {"model": "htdemucs_6s", "overlap": 0.50, "roformer_vocals": True},
}


class StemSplitter:
    def __init__(
        self,
        quality: str = "full",
        device: Optional[str] = None,
        model: Optional[str] = None,          # override the tier's Demucs model
        roformer_vocals: Optional[bool] = None,  # override the tier's vocal choice
    ):
        if quality not in QUALITY_TIERS:
            raise ValueError(f"quality must be one of {list(QUALITY_TIERS)}, got {quality!r}")
        cfg = QUALITY_TIERS[quality]

        self.quality = quality
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model or cfg["model"]
        self.overlap = cfg["overlap"]
        self.use_roformer = cfg["roformer_vocals"] if roformer_vocals is None else roformer_vocals

        print(f"[Jsplit] quality={quality} | demucs={self.model_name} | "
              f"roformer_vocals={self.use_roformer} | device={self.device}")

        # Demucs backbone (always used, for instruments).
        self.demucs = AudioSeparator(model_name=self.model_name, device=self.device)
        self.sample_rate = self.demucs.sample_rate

        # RoFormer is heavy to import; only load when needed.
        self.roformer = None
        if self.use_roformer:
            from src.models.roformer_separator import RoFormerSeparator
            self.roformer = RoFormerSeparator(
                model_key="melband-roformer-kim-vocals", device=self.device
            )

    # ------------------------------------------------------------------ #
    def separate(self, waveform: torch.Tensor, shifts: int = 1) -> Dict[str, torch.Tensor]:
        if self.use_roformer:
            return self._separate_hybrid(waveform, shifts=shifts)
        return self._align_lengths(self.demucs.separate(waveform, shifts=shifts, overlap=self.overlap))

    def _separate_hybrid(self, waveform: torch.Tensor, shifts: int = 1) -> Dict[str, torch.Tensor]:
        """RoFormer extracts the vocal; Demucs decomposes the instrumental.
        The Demucs vocal residual is folded into `other` so sum(stems) == mix."""
        print("  [hybrid] RoFormer vocal extraction ...")
        rf = self.roformer.separate(waveform.detach().cpu().float())
        vocals = rf["vocals"]
        instrumental = rf.get("instrumental")
        if instrumental is None:  # safety: derive it if the model only gave vocals
            v, w = self._match(vocals, waveform.detach().cpu().float())
            instrumental = w - v

        print("  [hybrid] Demucs instrument decomposition ...")
        dem = self.demucs.separate(instrumental.to(self.device), shifts=shifts, overlap=self.overlap)

        # Fold Demucs's own (residual) vocal back into `other` -> no lost energy.
        if "vocals" in dem:
            resid = dem.pop("vocals")
            if "other" in dem:
                o, r = self._match(dem["other"], resid)
                dem["other"] = o + r
            else:
                dem["other"] = resid

        stems = {"vocals": vocals, **dem}
        return self._align_lengths(stems)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _match(a: torch.Tensor, b: torch.Tensor):
        n = min(a.shape[-1], b.shape[-1])
        return a[..., :n], b[..., :n]

    @staticmethod
    def _align_lengths(stems: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        n = min(s.shape[-1] for s in stems.values())
        return {k: v[..., :n].detach().cpu().float() for k, v in stems.items()}

    # ------------------------------------------------------------------ #
    def process_file(
        self,
        input_file: str,
        output_dir: str = "outputs_jsplit",
        shifts: int = 1,
        start: float = 0.0,
        duration: Optional[float] = None,
        bit_depth: str = "PCM_24",
        run_metrics: bool = True,
        keep_stems: Optional[list] = None,   # only export these (None = all)
        progress_cb: Optional[callable] = None,  # str -> None, for GUI status
    ) -> dict:
        in_path = Path(input_file)
        out_dir = Path(output_dir) / in_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        def _notify(msg: str):
            print(msg)
            if progress_cb:
                try:
                    progress_cb(msg)
                except Exception:
                    pass

        _notify(f"[1/4] Loading: {input_file}")
        waveform, sr = load_audio(str(in_path), target_sr=self.sample_rate, channels=2, device=self.device)

        # Optional crop (used for quick tests / benchmarks).
        if start > 0 or duration is not None:
            s0 = int(start * sr)
            s1 = int((start + duration) * sr) if duration is not None else waveform.shape[-1]
            waveform = waveform[..., s0:s1]
        dur = waveform.shape[-1] / sr
        print(f"  {dur:.1f}s @ {sr}Hz, {waveform.shape[0]}ch")

        _notify(f"[2/4] Separating (quality={self.quality}, shifts={shifts}) — this can take a while ...")
        stems = self.separate(waveform, shifts=shifts)

        _notify("[3/4] Exporting stems ...")
        saved = {}
        for name, tensor in stems.items():
            if keep_stems is not None and name not in keep_stems:
                continue
            out_file = out_dir / f"{name}.wav"
            save_audio(tensor, str(out_file), sr=sr, bit_depth=bit_depth, normalize=False)
            saved[name] = str(out_file)
            _notify(f"  [OK] {name}")

        result = {
            "track": in_path.stem,
            "quality": self.quality,
            "model": self.model_name,
            "n_elements": len(stems),
            "elements": list(stems.keys()),
            "sample_rate": sr,
            "duration_sec": round(dur, 2),
            "output_dir": str(out_dir),
            "stems": saved,
        }

        if run_metrics:
            print("\n[4/4] Measuring quality ...")
            from src.quality import metrics
            report = metrics.full_report(waveform.detach().cpu(), stems, sr=sr)
            metrics.print_report(report)
            result["metrics"] = report
        else:
            print("\n[4/4] Metrics skipped.")

        return result
