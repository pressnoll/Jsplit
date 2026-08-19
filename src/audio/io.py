import os
import torch
import torchaudio
import soundfile as sf
import numpy as np
from pathlib import Path
from typing import Tuple, Optional

def load_audio(
    file_path: str,
    target_sr: int = 44100,
    channels: int = 2,
    device: str = "cpu"
) -> Tuple[torch.Tensor, int]:
    """
    Loads an audio file reliably using soundfile, resamples if necessary,
    and returns a stereo float tensor [channels, samples].
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # Read audio array with soundfile
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    # data shape from soundfile is [samples, channels]
    # Convert to PyTorch [channels, samples]
    waveform = torch.from_numpy(data.T)

    # Resample if sample rate doesn't match
    if sr != target_sr:
        resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=target_sr)
        waveform = resampler(waveform)
        sr = target_sr

    # Ensure target channel count (stereo)
    if waveform.shape[0] == 1 and channels == 2:
        waveform = waveform.repeat(2, 1)
    elif waveform.shape[0] > 2 and channels == 2:
        waveform = waveform[:2, :]
    elif waveform.shape[0] == 2 and channels == 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    return waveform.to(device), sr

def save_audio(
    waveform: torch.Tensor,
    output_path: str,
    sr: int = 44100,
    bit_depth: str = "PCM_24",
    normalize: bool = False
) -> str:
    """
    Saves an audio tensor to disk as high-resolution WAV.
    waveform: shape [channels, samples] or [batch, channels, samples]
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if waveform.dim() == 3:
        waveform = waveform.squeeze(0)

    # Detach and move to cpu
    audio_np = waveform.detach().cpu().numpy()

    # Audio shape must be [samples, channels] for soundfile
    if audio_np.ndim == 2:
        audio_np = audio_np.T

    # Peak normalization if requested
    if normalize:
        peak = np.max(np.abs(audio_np))
        if peak > 0:
            audio_np = audio_np / peak * 0.95
    else:
        # Clipping protection
        audio_np = np.clip(audio_np, -1.0, 1.0)

    sf.write(str(out_path), audio_np, sr, subtype=bit_depth)
    return str(out_path)
