import os
import torch
from pathlib import Path
from typing import Dict, Optional, Any
from src.audio.io import load_audio, save_audio
from src.audio.processing import check_energy_conservation
from src.models.separator import AudioSeparator
from src.enhancement.spectral_refiner import SpectralRefiner


class StudioStemSplitter:
    """
    Studio-Grade High-Clarity Stem Splitting Pipeline (Phase 2).

    Engines:
      - 'demucs'       : HTDemucs 4-stem (drums, bass, other, vocals)
      - 'demucs_ft'    : HTDemucs fine-tuned 4-stem
      - 'demucs_6s'    : HTDemucs 6-stem (+ guitar, piano)
      - 'roformer'     : Mel-Band RoFormer vocal isolation (SOTA clarity)
      - 'hybrid'       : RoFormer vocals + Demucs for drums/bass/other (best of both)

    Post-Processing:
      - Spectral gating (removes ghost bleed)
      - Harmonic inpainting (fills spectral holes / restores warmth)
      - Phase smoothing (eliminates hollow/underwater artifacts)
      - Stem-specific transient and tonal refinement
    """

    DEMUCS_MODELS = {
        "demucs": "htdemucs",
        "demucs_ft": "htdemucs_ft",
        "demucs_6s": "htdemucs_6s",
    }

    def __init__(
        self,
        engine: str = "hybrid",
        enhance_clarity: bool = True,
        device: Optional[str] = None
    ):
        self.device = device if device else ("cuda" if torch.cuda.is_available() else "cpu")
        self.engine = engine
        self.enhance_clarity = enhance_clarity

        # Initialize the appropriate separation backend(s)
        if engine in self.DEMUCS_MODELS:
            self.demucs = AudioSeparator(
                model_name=self.DEMUCS_MODELS[engine],
                device=self.device
            )
            self.roformer = None
            self.sample_rate = self.demucs.sample_rate

        elif engine == "roformer":
            from src.models.roformer_separator import RoFormerSeparator
            self.roformer = RoFormerSeparator(
                model_key="melband-roformer-kim-vocals",
                device=self.device
            )
            self.demucs = None
            self.sample_rate = self.roformer.sample_rate

        elif engine == "hybrid":
            # Best-of-both: RoFormer for vocals, Demucs for instruments
            from src.models.roformer_separator import RoFormerSeparator
            print("\n--- Hybrid Engine: Loading RoFormer (vocals) + Demucs (instruments) ---")
            self.roformer = RoFormerSeparator(
                model_key="melband-roformer-kim-vocals",
                device=self.device
            )
            self.demucs = AudioSeparator(
                model_name="htdemucs_ft",
                device=self.device
            )
            self.sample_rate = self.demucs.sample_rate
        elif engine == "onnx":
            from src.models.onnx_separator import ONNXSeparator
            
            onnx_model_path = Path("models/onnx/htdemucs_ft.onnx")
            if not onnx_model_path.exists():
                raise FileNotFoundError(
                    f"ONNX model not found at {onnx_model_path}. "
                    "Run 'python scripts/export_onnx.py --model htdemucs_ft' first."
                )
                
            print("\n--- Optimized ONNX Engine ---")
            self.onnx_engine = ONNXSeparator(
                model_path=str(onnx_model_path),
                stems=["drums", "bass", "other", "vocals"]
            )
            self.demucs = None
            self.roformer = None
            self.sample_rate = self.onnx_engine.sample_rate
            
        elif engine == "opt_pytorch":
            from src.models.opt_separator import OptimizedPyTorchSeparator
            print("\n--- Highly Optimized PyTorch Engine (FP16/Compile) ---")
            self.opt_engine = OptimizedPyTorchSeparator(model_name="htdemucs_ft", device=self.device)
            self.demucs = None
            self.roformer = None
            self.sample_rate = self.opt_engine.sample_rate

        else:
            raise ValueError(f"Unknown engine: {engine}")

        # Initialize spectral refiner
        if enhance_clarity:
            self.refiner = SpectralRefiner(sample_rate=self.sample_rate)

    def process_file(
        self,
        input_file: str,
        output_dir: str = "outputs",
        shifts: int = 1,
        bit_depth: str = "PCM_24",
        normalize: bool = False
    ) -> Dict[str, Any]:
        """
        Full pipeline: load -> separate -> refine -> export.
        """
        in_path = Path(input_file)
        out_dir = Path(output_dir) / in_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        # === LOAD ===
        print(f"\n[1/4] Loading audio: {input_file}")
        waveform, sr = load_audio(
            str(in_path),
            target_sr=self.sample_rate,
            channels=2,
            device=self.device
        )
        duration_sec = waveform.shape[-1] / sr
        print(f"  Loaded: {duration_sec:.1f}s | {sr}Hz | {waveform.shape[0]}ch")

        # === SEPARATE ===
        print(f"\n[2/4] Running separation (engine: {self.engine})...")
        raw_stems = self._run_separation(waveform, shifts=shifts)

        # === REFINE ===
        if self.enhance_clarity and self.refiner:
            print("\n[3/4] Applying spectral refinement (anti-hollow processing)...")
            final_stems = self.refiner.refine_all_stems(
                raw_stems,
                original_mix=waveform.cpu(),
                gate_threshold_db=-42.0,
                inpaint_strength=0.25,
                phase_smooth_strength=0.12
            )
        else:
            print("\n[3/4] Skipping refinement.")
            final_stems = raw_stems

        # === EXPORT ===
        print("\n[4/4] Verifying & exporting stems...")
        energy_report = check_energy_conservation(waveform.cpu(), final_stems)

        saved_files = {}
        for stem_name, stem_tensor in final_stems.items():
            out_file = out_dir / f"{stem_name}.wav"
            save_audio(stem_tensor, str(out_file), sr=sr, bit_depth=bit_depth, normalize=normalize)
            saved_files[stem_name] = str(out_file)
            print(f"  [OK] {stem_name.upper()}: {out_file.name}")

        return {
            "track_name": in_path.stem,
            "engine": self.engine,
            "duration_seconds": duration_sec,
            "sample_rate": sr,
            "saved_stems": saved_files,
            "output_directory": str(out_dir),
            "diagnostics": energy_report
        }

    def _run_separation(
        self,
        waveform: torch.Tensor,
        shifts: int = 1
    ) -> Dict[str, torch.Tensor]:
        """Route to the appropriate separation backend."""

        if self.engine in self.DEMUCS_MODELS:
            return self.demucs.separate(waveform, shifts=shifts)

        elif self.engine == "roformer":
            return self.roformer.separate(waveform)

        elif self.engine == "hybrid":
            return self._hybrid_separate(waveform, shifts=shifts)
            
        elif self.engine == "onnx":
            return self.onnx_engine.separate(waveform)
            
        elif self.engine == "opt_pytorch":
            return self.opt_engine.separate(waveform, shifts=shifts)

    def _hybrid_separate(
        self,
        waveform: torch.Tensor,
        shifts: int = 1
    ) -> Dict[str, torch.Tensor]:
        """
        Hybrid separation: uses RoFormer for superior vocal isolation,
        then Demucs on the instrumental residual for drums/bass/other.
        
        This gives the best-of-both-worlds:
        - RoFormer's cleaner, less hollow vocal extraction
        - Demucs's strong drum/bass/other instrument separation
        """
        # Step 1: RoFormer extracts vocals with maximum clarity
        print("  [Hybrid] Step 1: RoFormer vocal extraction...")
        roformer_stems = self.roformer.separate(waveform.cpu())
        vocals = roformer_stems["vocals"]
        instrumental = roformer_stems["instrumental"]

        # Step 2: Feed the instrumental into Demucs to split drums/bass/other
        print("  [Hybrid] Step 2: Demucs instrument decomposition...")
        demucs_stems = self.demucs.separate(instrumental.to(self.device), shifts=shifts)

        # Build the final stem dictionary
        # Use RoFormer's vocals (cleaner) + Demucs's instrument breakdown
        hybrid_stems = {
            "vocals": vocals,
            "drums": demucs_stems.get("drums", torch.zeros_like(vocals)),
            "bass": demucs_stems.get("bass", torch.zeros_like(vocals)),
            "other": demucs_stems.get("other", torch.zeros_like(vocals)),
        }

        # If Demucs gave us guitar/piano (6-stem model), include those too
        for extra in ["guitar", "piano"]:
            if extra in demucs_stems:
                hybrid_stems[extra] = demucs_stems[extra]

        return hybrid_stems
