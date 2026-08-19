"""
RoFormer-based separator using the melband-roformer-infer package's
built-in model registry, auto-download, and chunked inference utilities.
"""
import os
import sys
import torch
import numpy as np
import soundfile as sf
import yaml
from pathlib import Path
from typing import Dict, Optional, Tuple
from ml_collections import ConfigDict

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


class SafeLoaderWithTuple(yaml.SafeLoader):
    pass

def _tuple_constructor(loader, node):
    return loader.construct_sequence(node)

SafeLoaderWithTuple.add_constructor('tag:yaml.org,2002:python/tuple', _tuple_constructor)


class RoFormerSeparator:
    """
    High-fidelity separator using Mel-Band RoFormer architecture.
    Uses the melband-roformer-infer package's built-in model registry
    and auto-download system for reliable checkpoint management.
    """

    def __init__(
        self,
        model_key: str = "melband-roformer-kim-vocals",
        device: Optional[str] = None,
    ):
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        self.model_key = model_key
        self._load_model(model_key)

    def _load_model(self, model_key: str):
        """Download and load model using the package's built-in registry."""
        from mel_band_roformer.download import ensure_model_assets
        from mel_band_roformer.utils import get_model_from_config

        print(f"[RoFormer] Resolving model '{model_key}'...")
        model_path, config_path = ensure_model_assets(model_key)
        print(f"[RoFormer] Checkpoint: {model_path}")
        print(f"[RoFormer] Config: {config_path}")

        # Load config
        with open(config_path) as f:
            self.config = ConfigDict(yaml.load(f, Loader=SafeLoaderWithTuple))

        # Build model
        self.model = get_model_from_config("mel_band_roformer", self.config)
        self.model.load_state_dict(
            torch.load(model_path, map_location=torch.device("cpu"))
        )
        self.model.to(self.device)
        self.model.eval()

        self.sample_rate = getattr(self.config, 'audio', {}).get('sample_rate', 44100)
        if hasattr(self.config, 'audio') and hasattr(self.config.audio, 'sample_rate'):
            self.sample_rate = self.config.audio.sample_rate

        # Determine target instrument
        if hasattr(self.config, 'training'):
            self.target_instrument = getattr(self.config.training, 'target_instrument', None)
            self.instruments = getattr(self.config.training, 'instruments', ['vocals'])
        else:
            self.target_instrument = 'vocals'
            self.instruments = ['vocals']

        print(f"[RoFormer] Model loaded. Device: {self.device} | SR: {self.sample_rate}Hz")
        print(f"[RoFormer] Target: {self.target_instrument or self.instruments}")

    def separate(
        self,
        waveform: torch.Tensor,
    ) -> Dict[str, torch.Tensor]:
        """
        Separate audio using the built-in demix_track chunked inference.
        waveform: [channels, samples] float tensor
        Returns dict with stem names -> tensors [channels, samples]
        """
        from mel_band_roformer.utils import demix_track

        # demix_track expects [channels, samples] tensor
        mix = waveform.float()
        if mix.device != torch.device("cpu"):
            mix = mix.cpu()

        print("[RoFormer] Running separation...")
        result, _ = demix_track(self.config, self.model, mix, self.device)

        # Convert numpy arrays back to tensors
        stems = {}
        for name, arr in result.items():
            stems[name] = torch.from_numpy(arr).float()

        # Compute instrumental complement if we only got vocals
        if len(stems) == 1 and "vocals" in stems:
            stems["instrumental"] = waveform.cpu().float() - stems["vocals"]
        elif len(stems) == 1:
            key = list(stems.keys())[0]
            stems["other"] = waveform.cpu().float() - stems[key]

        print(f"[RoFormer] Separation complete. Stems: {list(stems.keys())}")
        return stems
