import torch
import numpy as np
from typing import Dict

def check_energy_conservation(
    original_mix: torch.Tensor,
    stems: Dict[str, torch.Tensor]
) -> Dict[str, float]:
    """
    Evaluates whether the reconstructed sum of stems conserves energy and phase fidelity
    relative to the original mixed track.
    """
    stem_sum = sum(stems.values())
    
    # Align lengths
    min_len = min(original_mix.shape[-1], stem_sum.shape[-1])
    orig = original_mix[..., :min_len]
    recon = stem_sum[..., :min_len]
    
    residual = orig - recon
    
    orig_energy = torch.sum(orig ** 2).item() + 1e-9
    residual_energy = torch.sum(residual ** 2).item()
    
    # Residual Error Ratio in dB
    residual_ratio_db = 10 * np.log10(residual_energy / orig_energy)
    
    # Correlation coefficient
    orig_flat = orig.flatten()
    recon_flat = recon.flatten()
    corr = torch.cosine_similarity(orig_flat.unsqueeze(0), recon_flat.unsqueeze(0)).item()
    
    return {
        "residual_energy_ratio_db": round(residual_ratio_db, 2),
        "reconstruction_correlation": round(corr, 4),
        "is_phase_aligned": corr > 0.98
    }

def compute_spectrogram(
    waveform: torch.Tensor,
    n_fft: int = 2048,
    hop_length: int = 512
) -> torch.Tensor:
    """
    Computes complex STFT spectrogram.
    waveform: [channels, samples]
    Returns complex tensor: [channels, freq_bins, frames]
    """
    window = torch.hann_window(n_fft, device=waveform.device)
    stft = torch.stft(
        waveform,
        n_fft=n_fft,
        hop_length=hop_length,
        window=window,
        return_complex=True
    )
    return stft
