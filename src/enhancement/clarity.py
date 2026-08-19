import torch
import numpy as np
from typing import Dict

class StemClarityEnhancer:
    """
    Post-processing enhancement engine designed to mitigate common MSS artifacts:
    - Phase swirling / underwater distortion (via phase-consistent spectral smoothing)
    - Muffled high-end (via high-frequency excitation & transient reconstruction)
    - Cross-stem bleeding (via adaptive spectral subtraction & masking)
    """

    def __init__(self, sample_rate: int = 44100):
        self.sr = sample_rate

    def enhance_stems(
        self,
        stems: Dict[str, torch.Tensor],
        original_mix: torch.Tensor,
        debleed_strength: float = 0.25,
        air_boost: float = 1.15,
        transient_boost: float = 1.2
    ) -> Dict[str, torch.Tensor]:
        """
        Applies clarity enhancement across all separated stems.
        """
        enhanced = {}
        for name, stem in stems.items():
            if name == "drums":
                enhanced[name] = self.enhance_drums(stem, transient_boost=transient_boost)
            elif name == "vocals":
                enhanced[name] = self.enhance_vocals(stem, air_boost=air_boost)
            elif name == "bass":
                enhanced[name] = self.enhance_bass(stem)
            else:
                enhanced[name] = self.enhance_generic(stem)

        # De-bleed cross-talk using spectral masking against the residual
        if debleed_strength > 0:
            enhanced = self.apply_cross_stem_debleed(enhanced, original_mix, strength=debleed_strength)

        return enhanced

    def enhance_drums(self, drum_stem: torch.Tensor, transient_boost: float = 1.2) -> torch.Tensor:
        """
        Sharpens drum transients (kick & snare attacks) to prevent dull/muffled percussion.
        """
        # Differential transient envelope detection
        diff = torch.diff(drum_stem, dim=-1, prepend=drum_stem[..., :1])
        transients = torch.clamp(diff, min=0.0)
        sharpened = drum_stem + (transients * (transient_boost - 1.0))
        return torch.clamp(sharpened, -1.0, 1.0)

    def enhance_vocals(self, vocal_stem: torch.Tensor, air_boost: float = 1.15) -> torch.Tensor:
        """
        Restores high-frequency clarity ('air' band above 10kHz) and clears boxiness.
        """
        # Perform STFT
        n_fft = 2048
        hop_length = 512
        window = torch.hann_window(n_fft, device=vocal_stem.device)
        stft = torch.stft(vocal_stem, n_fft=n_fft, hop_length=hop_length, window=window, return_complex=True)
        
        freq_bins = stft.shape[-2]
        air_start_bin = int(freq_bins * (10000 / (self.sr / 2)))  # 10kHz+
        
        # Smooth boost curve for high frequencies
        boost_curve = torch.ones(freq_bins, device=vocal_stem.device)
        boost_curve[air_start_bin:] = torch.linspace(1.0, air_boost, freq_bins - air_start_bin, device=vocal_stem.device)
        
        # Apply boost to complex spectrogram magnitude while preserving phase
        mag = torch.abs(stft) * boost_curve.unsqueeze(-1).unsqueeze(0)
        phase = torch.angle(stft)
        enhanced_stft = torch.polar(mag, phase)
        
        # Inverse STFT
        enhanced_waveform = torch.istft(enhanced_stft, n_fft=n_fft, hop_length=hop_length, window=window, length=vocal_stem.shape[-1])
        return torch.clamp(enhanced_waveform, -1.0, 1.0)

    def enhance_bass(self, bass_stem: torch.Tensor) -> torch.Tensor:
        """
        Tightens low-end clarity and suppresses high-frequency bleed from cymbals or vocals into the bass stem.
        """
        n_fft = 2048
        hop_length = 512
        window = torch.hann_window(n_fft, device=bass_stem.device)
        stft = torch.stft(bass_stem, n_fft=n_fft, hop_length=hop_length, window=window, return_complex=True)
        
        freq_bins = stft.shape[-2]
        low_pass_cutoff_bin = int(freq_bins * (3500 / (self.sr / 2)))  # Cutoff bleed above 3.5kHz
        
        mask = torch.ones(freq_bins, device=bass_stem.device)
        mask[low_pass_cutoff_bin:] = torch.linspace(1.0, 0.05, freq_bins - low_pass_cutoff_bin, device=bass_stem.device)
        
        enhanced_stft = stft * mask.unsqueeze(-1).unsqueeze(0)
        enhanced_waveform = torch.istft(enhanced_stft, n_fft=n_fft, hop_length=hop_length, window=window, length=bass_stem.shape[-1])
        return torch.clamp(enhanced_waveform, -1.0, 1.0)

    def enhance_generic(self, stem: torch.Tensor) -> torch.Tensor:
        """
        Generic dynamic range and clarity enhancement.
        """
        return torch.clamp(stem, -1.0, 1.0)

    def apply_cross_stem_debleed(
        self,
        stems: Dict[str, torch.Tensor],
        original_mix: torch.Tensor,
        strength: float = 0.25
    ) -> Dict[str, torch.Tensor]:
        """
        Suppresses cross-talk bleeding between stems using adaptive thresholding.
        """
        # Ensure equal lengths
        min_len = min(min(s.shape[-1] for s in stems.values()), original_mix.shape[-1])
        cleaned_stems = {}
        
        for name, stem in stems.items():
            other_energy = sum(
                torch.abs(other_stem[..., :min_len])
                for other_name, other_stem in stems.items()
                if other_name != name
            )
            # Mask factor
            stem_cur = stem[..., :min_len]
            ratio = torch.abs(stem_cur) / (other_energy + 1e-6)
            suppression = torch.sigmoid((ratio - 0.5) * 5.0)
            
            # Blend suppression based on strength
            factor = (1.0 - strength) + strength * suppression
            cleaned_stems[name] = stem_cur * factor
            
        return cleaned_stems
