import os
import torch
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
from pathlib import Path
from typing import Dict, Optional, Callable
from demucs.pretrained import get_model
from demucs.apply import apply_model

class AudioSeparator:
    """
    Wrapper for state-of-the-art pre-trained deep learning source separation models.
    Supports:
      - 'htdemucs': High-quality 4-stem model (drums, bass, other, vocals)
      - 'htdemucs_6s': 6-stem model (drums, bass, other, vocals, guitar, piano)
      - 'htdemucs_ft': Fine-tuned 4-stem model for maximum isolation fidelity
    """

    SUPPORTED_MODELS = {
        "4stems": "htdemucs",
        "4stems_hq": "htdemucs_ft",
        "6stems": "htdemucs_6s"
    }

    def __init__(self, model_name: str = "htdemucs", device: Optional[str] = None):
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self.model_name = model_name
        print(f"Loading separation model '{model_name}' on device: {self.device}...")
        self.model = get_model(model_name)
        self.model.to(self.device)
        self.model.eval()
        self.sources = self.model.sources
        self.sample_rate = self.model.samplerate
        print(f"Model loaded successfully. Target sample rate: {self.sample_rate}Hz. Stems: {self.sources}")

    def separate(
        self,
        waveform: torch.Tensor,
        shifts: int = 1,
        overlap: float = 0.25,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> Dict[str, torch.Tensor]:
        """
        Runs separation on a waveform tensor [channels, samples].
        Returns a dictionary mapping stem name -> waveform tensor [channels, samples].
        """
        # Ensure batch dimension [1, channels, samples]
        if waveform.dim() == 2:
            wav_batch = waveform.unsqueeze(0).to(self.device)
        else:
            wav_batch = waveform.to(self.device)

        # Apply model with shifts for equivariant quality enhancement
        with torch.no_grad():
            sources = apply_model(
                self.model,
                wav_batch,
                shifts=shifts,
                overlap=overlap,
                device=self.device,
                progress=True
            )

        # Output shape: [batch, num_sources, channels, samples]
        sources = sources.squeeze(0)  # [num_sources, channels, samples]

        stem_dict = {}
        for idx, name in enumerate(self.sources):
            stem_dict[name] = sources[idx].cpu()

        return stem_dict
