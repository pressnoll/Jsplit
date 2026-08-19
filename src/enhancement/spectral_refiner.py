import torch
import numpy as np
from typing import Dict, Optional, Tuple
from scipy.signal import medfilt


class SpectralRefiner:
    """
    Advanced spectral refinement engine that eliminates the hollow/metallic artifacts
    left by standard source separation. Addresses the core clarity research gaps:
    
    1. Spectral Gating: Removes low-energy ghost bleed below psychoacoustic masking threshold
    2. Harmonic Inpainting: Detects and fills spectral holes from aggressive mask overlap
    3. Phase Smoothing: Reduces phase discontinuities that cause underwater/swirling artifacts
    4. Transient Preservation: Protects attack transients while cleaning sustained tones
    """

    def __init__(self, sample_rate: int = 44100, n_fft: int = 2048, hop_length: int = 512):
        self.sr = sample_rate
        self.n_fft = n_fft
        self.hop_length = hop_length

    def refine_all_stems(
        self,
        stems: Dict[str, torch.Tensor],
        original_mix: torch.Tensor,
        gate_threshold_db: float = -45.0,
        inpaint_strength: float = 0.3,
        phase_smooth_strength: float = 0.15
    ) -> Dict[str, torch.Tensor]:
        """
        Applies the full spectral refinement chain to each stem.
        """
        refined = {}
        for name, stem in stems.items():
            print(f"    Refining {name.upper()}...")

            # Step 1: Spectral Gate (remove ghost bleed)
            stem = self.spectral_gate(stem, threshold_db=gate_threshold_db, stem_type=name)

            # Step 2: Harmonic Inpainting (fill spectral holes)
            stem = self.harmonic_inpaint(stem, original_mix, strength=inpaint_strength, stem_type=name)

            # Step 3: Phase Smoothing (reduce underwater artifacts)
            stem = self.phase_smooth(stem, strength=phase_smooth_strength)

            # Step 4: Stem-specific transient/tonal refinement
            if name == "drums":
                stem = self._refine_drums(stem)
            elif name == "vocals":
                stem = self._refine_vocals(stem)
            elif name == "bass":
                stem = self._refine_bass(stem)

            refined[name] = stem

        return refined

    def spectral_gate(
        self,
        waveform: torch.Tensor,
        threshold_db: float = -45.0,
        stem_type: str = "other"
    ) -> torch.Tensor:
        """
        Spectral noise gate: removes frequency bins below a dynamic threshold.
        This kills the faint ghost bleed that makes stems sound muddy.
        
        Uses a per-frame adaptive threshold based on the local spectral energy,
        so quiet passages aren't destroyed while loud bleed in dense sections is cleaned.
        """
        window = torch.hann_window(self.n_fft, device=waveform.device)
        stft = torch.stft(waveform, self.n_fft, self.hop_length, window=window, return_complex=True)
        
        mag = torch.abs(stft)
        phase = torch.angle(stft)
        
        # Convert to dB
        mag_db = 20 * torch.log10(mag + 1e-8)
        
        # Adaptive threshold: per-frame median energy + offset
        # This adapts to quiet vs loud sections naturally
        frame_median = torch.median(mag_db, dim=-2, keepdim=True).values
        adaptive_threshold = torch.maximum(
            frame_median + threshold_db + 10,  # relative to local median
            torch.tensor(threshold_db, device=waveform.device)  # absolute floor
        )
        
        # Soft gate (smooth rolloff instead of hard cutoff to avoid clicks)
        gate_steepness = 0.5  # dB per unit of sigmoid
        gate = torch.sigmoid((mag_db - adaptive_threshold) * gate_steepness)
        
        # Apply gate
        gated_mag = mag * gate
        gated_stft = torch.polar(gated_mag, phase)
        
        result = torch.istft(gated_stft, self.n_fft, self.hop_length, window=window, length=waveform.shape[-1])
        return result

    def harmonic_inpaint(
        self,
        waveform: torch.Tensor,
        original_mix: torch.Tensor,
        strength: float = 0.3,
        stem_type: str = "other"
    ) -> torch.Tensor:
        """
        Detects spectral holes (frequency bins that were aggressively zeroed out during
        mask-based separation) and fills them with harmonically consistent content
        from the original mix, weighted by the stem's local spectral envelope.
        
        This is what restores the warmth and body that standard splitters destroy.
        """
        window = torch.hann_window(self.n_fft, device=waveform.device)
        
        min_len = min(waveform.shape[-1], original_mix.shape[-1])
        stem_wav = waveform[..., :min_len]
        mix_wav = original_mix[..., :min_len].to(waveform.device)
        
        stem_stft = torch.stft(stem_wav, self.n_fft, self.hop_length, window=window, return_complex=True)
        mix_stft = torch.stft(mix_wav, self.n_fft, self.hop_length, window=window, return_complex=True)
        
        stem_mag = torch.abs(stem_stft)
        mix_mag = torch.abs(mix_stft)
        
        # Detect spectral holes: bins where stem energy is very low but mix energy is present
        # This indicates content was removed that maybe shouldn't have been
        ratio = stem_mag / (mix_mag + 1e-8)
        
        # Holes are where ratio is very low (stem has almost nothing but mix had content)
        hole_mask = (ratio < 0.05) & (mix_mag > torch.quantile(mix_mag.float(), 0.3))
        
        # Compute the stem's spectral envelope (smoothed magnitude profile)
        # We use this to scale the inpainted content so it sounds natural
        kernel_size = 5
        stem_envelope = torch.nn.functional.avg_pool1d(
            stem_mag.reshape(-1, 1, stem_mag.shape[-1]),
            kernel_size=kernel_size,
            stride=1,
            padding=kernel_size // 2
        ).reshape(stem_mag.shape)
        
        envelope_ratio = stem_envelope / (stem_envelope.max() + 1e-8)
        
        # Inpaint: blend a fraction of the mix's content into the holes
        inpaint_contribution = mix_stft * hole_mask.float() * strength * envelope_ratio
        
        result_stft = stem_stft + inpaint_contribution
        
        result = torch.istft(result_stft, self.n_fft, self.hop_length, window=window, length=min_len)
        
        # Pad back to original length if needed
        if waveform.shape[-1] > min_len:
            result = torch.nn.functional.pad(result, (0, waveform.shape[-1] - min_len))
        
        return result

    def phase_smooth(
        self,
        waveform: torch.Tensor,
        strength: float = 0.15
    ) -> torch.Tensor:
        """
        Reduces phase discontinuities between adjacent frames that cause
        the characteristic underwater/metallic swirling of separated stems.
        
        Uses weighted averaging of phase between neighboring frames
        to create smoother phase transitions while preserving transients.
        """
        window = torch.hann_window(self.n_fft, device=waveform.device)
        stft = torch.stft(waveform, self.n_fft, self.hop_length, window=window, return_complex=True)
        
        mag = torch.abs(stft)
        phase = torch.angle(stft)
        
        # Compute phase derivative (instantaneous frequency deviation)
        phase_diff = torch.diff(phase, dim=-1, prepend=phase[..., :1])
        
        # Wrap to [-pi, pi]
        phase_diff = torch.atan2(torch.sin(phase_diff), torch.cos(phase_diff))
        
        # Detect phase jumps (large deviations indicate transients - preserve these)
        jump_threshold = 2.0  # radians
        is_transient = torch.abs(phase_diff) > jump_threshold
        
        # Smooth phase derivative for non-transient frames
        smooth_kernel = torch.tensor([0.15, 0.7, 0.15], device=waveform.device).reshape(1, 1, 3)
        
        # Process each frequency bin
        pd_flat = phase_diff.reshape(-1, 1, phase_diff.shape[-1])
        smoothed_pd = torch.nn.functional.conv1d(pd_flat, smooth_kernel, padding=1)
        smoothed_pd = smoothed_pd.reshape(phase_diff.shape)
        
        # Blend: keep original phase at transients, use smoothed elsewhere
        blended_pd = torch.where(
            is_transient,
            phase_diff,
            phase_diff * (1 - strength) + smoothed_pd * strength
        )
        
        # Reconstruct phase from smoothed derivative via cumulative sum
        smoothed_phase = torch.cumsum(blended_pd, dim=-1) + phase[..., :1]
        
        # Reconstruct
        smoothed_stft = torch.polar(mag, smoothed_phase)
        result = torch.istft(smoothed_stft, self.n_fft, self.hop_length, window=window, length=waveform.shape[-1])
        
        return result

    def _refine_drums(self, waveform: torch.Tensor) -> torch.Tensor:
        """Enhance drum transient attack while cleaning sustained bleed."""
        # Emphasize transients via differential envelope
        diff = torch.diff(torch.abs(waveform), dim=-1, prepend=torch.abs(waveform[..., :1]))
        transient_mask = torch.clamp(diff * 3.0, 0, 1)
        
        # Boost transient portions slightly
        enhanced = waveform * (1.0 + transient_mask * 0.15)
        return torch.clamp(enhanced, -1.0, 1.0)

    def _refine_vocals(self, waveform: torch.Tensor) -> torch.Tensor:
        """Restore vocal presence and air band clarity."""
        window = torch.hann_window(self.n_fft, device=waveform.device)
        stft = torch.stft(waveform, self.n_fft, self.hop_length, window=window, return_complex=True)
        
        mag = torch.abs(stft)
        phase = torch.angle(stft)
        freq_bins = mag.shape[-2]
        
        # Presence band boost (2kHz - 5kHz): this is where vocal clarity lives
        presence_start = int(freq_bins * (2000 / (self.sr / 2)))
        presence_end = int(freq_bins * (5000 / (self.sr / 2)))
        
        # Air band boost (10kHz+): restores sibilance and breathiness
        air_start = int(freq_bins * (10000 / (self.sr / 2)))
        
        boost = torch.ones(freq_bins, device=waveform.device)
        # Gentle presence lift
        boost[presence_start:presence_end] = 1.06
        # Gentle air lift with smooth ramp
        if air_start < freq_bins:
            air_boost = torch.linspace(1.0, 1.10, freq_bins - air_start, device=waveform.device)
            boost[air_start:] = air_boost
        
        enhanced_mag = mag * boost.unsqueeze(-1).unsqueeze(0)
        enhanced_stft = torch.polar(enhanced_mag, phase)
        
        result = torch.istft(enhanced_stft, self.n_fft, self.hop_length, window=window, length=waveform.shape[-1])
        return torch.clamp(result, -1.0, 1.0)

    def _refine_bass(self, waveform: torch.Tensor) -> torch.Tensor:
        """Tighten low-end and suppress high-frequency bleed into bass stem."""
        window = torch.hann_window(self.n_fft, device=waveform.device)
        stft = torch.stft(waveform, self.n_fft, self.hop_length, window=window, return_complex=True)
        
        freq_bins = stft.shape[-2]
        cutoff_bin = int(freq_bins * (4000 / (self.sr / 2)))
        
        # Smooth rolloff above 4kHz
        mask = torch.ones(freq_bins, device=waveform.device)
        if cutoff_bin < freq_bins:
            rolloff = torch.linspace(1.0, 0.02, freq_bins - cutoff_bin, device=waveform.device)
            mask[cutoff_bin:] = rolloff
        
        filtered_stft = stft * mask.unsqueeze(-1).unsqueeze(0)
        result = torch.istft(filtered_stft, self.n_fft, self.hop_length, window=window, length=waveform.shape[-1])
        return torch.clamp(result, -1.0, 1.0)
