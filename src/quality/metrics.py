"""
Reference-free (and optionally reference-based) quality diagnostics for stem
separation. These exist so that "clarity" and "no hollow / broken sound" are
*measured*, not asserted.

Everything here runs on your actual song (no ground-truth stems needed), except
`si_sdr`, which requires reference stems (e.g. from MUSDB18) and is the standard
academic metric for when you have them.

Metric guide
------------
- reconstruction.residual_energy_db : energy left over when stems are summed and
      subtracted from the mix. Lower = less lost/added. Below -30 dB means the
      stems reconstruct the song almost perfectly -> nothing was thrown away ->
      no "hollow at the ensemble level". This is the single most important
      no-hollow guarantee.
- spectral_completeness.worst_band_db : the frequency band where reconstruction
      loses the most energy vs the mix. Near 0 dB everywhere = full-spectrum,
      not hollow. A band at, say, -6 dB means that part of the spectrum went
      missing across all stems (audible hollowness).
- leakage.mean_offdiagonal : how correlated stems' energy envelopes are (0..1).
      Lower = cleaner separation, less bleed between stems.
- sanity : per-stem peak/RMS/clipping/NaN checks (catches "broken" output).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np
import torch


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _to_mono(x: torch.Tensor) -> torch.Tensor:
    """[C, N] or [N] -> [N] float32 on CPU."""
    x = x.detach().to("cpu", torch.float32)
    if x.dim() == 2:
        x = x.mean(dim=0)
    return x


def _align(*tensors: torch.Tensor) -> List[torch.Tensor]:
    n = min(t.shape[-1] for t in tensors)
    return [t[..., :n] for t in tensors]


def _mag_pow(x: torch.Tensor, n_fft: int, hop: int) -> torch.Tensor:
    """Average power spectrum per frequency bin -> [F]."""
    win = torch.hann_window(n_fft)
    S = torch.stft(x, n_fft, hop, window=win, return_complex=True).abs()
    return (S ** 2).mean(dim=-1)


# --------------------------------------------------------------------------- #
# reference-based (needs ground-truth stems)
# --------------------------------------------------------------------------- #
def si_sdr(estimate: torch.Tensor, reference: torch.Tensor, eps: float = 1e-8) -> float:
    """Scale-invariant SDR in dB. Higher is better. The standard MSS metric."""
    est, ref = _align(_to_mono(estimate).double(), _to_mono(reference).double())
    ref = ref - ref.mean()
    est = est - est.mean()
    alpha = (est * ref).sum() / (ref.pow(2).sum() + eps)
    target = alpha * ref
    noise = est - target
    return float(10 * torch.log10((target.pow(2).sum() + eps) / (noise.pow(2).sum() + eps)))


# --------------------------------------------------------------------------- #
# reference-free (runs on your real song)
# --------------------------------------------------------------------------- #
def reconstruction_report(mix: torch.Tensor, stems: Dict[str, torch.Tensor]) -> dict:
    """How faithfully sum(stems) reconstructs the mix. This is the anti-hollow
    guarantee: if it reconstructs, no content was lost."""
    stem_sum = None
    for s in stems.values():
        m = _to_mono(s)
        stem_sum = m if stem_sum is None else _align(stem_sum, m)[0] + _align(stem_sum, m)[1]
    mix_m, recon = _align(_to_mono(mix), stem_sum)
    residual = mix_m - recon
    mix_e = mix_m.pow(2).sum().item() + 1e-12
    res_e = residual.pow(2).sum().item()
    corr = torch.nn.functional.cosine_similarity(
        mix_m.reshape(1, -1), recon.reshape(1, -1)
    ).item()
    return {
        "residual_energy_db": round(10 * math.log10(res_e / mix_e + 1e-12), 2),
        "reconstruction_correlation": round(corr, 4),
        "verdict": _grade_reconstruction(10 * math.log10(res_e / mix_e + 1e-12), corr),
    }


def _grade_reconstruction(res_db: float, corr: float) -> str:
    if res_db < -30 and corr > 0.99:
        return "excellent (no energy lost / not hollow)"
    if res_db < -15 and corr > 0.95:
        return "good"
    if res_db < -6:
        return "fair (some content lost across stems)"
    return "poor (significant content missing or altered -> hollow risk)"


def spectral_completeness(
    mix: torch.Tensor,
    stems: Dict[str, torch.Tensor],
    sr: int = 44100,
    n_bands: int = 8,
    n_fft: int = 4096,
    hop: int = 1024,
) -> dict:
    """Per-band energy of sum(stems) vs mix. Detects hollowness in specific
    frequency ranges (a band well below 0 dB = that part of the spectrum went
    missing across all stems)."""
    stem_sum = None
    for s in stems.values():
        m = _to_mono(s)
        stem_sum = m if stem_sum is None else _align(stem_sum, m)[0] + _align(stem_sum, m)[1]
    mix_m, recon = _align(_to_mono(mix), stem_sum)

    Pm = _mag_pow(mix_m, n_fft, hop)
    Pr = _mag_pow(recon, n_fft, hop)
    F = Pm.shape[0]
    freqs = torch.linspace(0, sr / 2, F)

    edges = torch.logspace(math.log10(30.0), math.log10(sr / 2), n_bands + 1)
    bands = []
    worst = {"band_hz": None, "ratio_db": 0.0}
    for i in range(n_bands):
        lo, hi = edges[i].item(), edges[i + 1].item()
        sel = (freqs >= lo) & (freqs < hi)
        if sel.sum() == 0:
            continue
        em = Pm[sel].sum().item() + 1e-12
        er = Pr[sel].sum().item() + 1e-12
        ratio_db = round(10 * math.log10(er / em), 2)
        bands.append({"band_hz": f"{int(lo)}-{int(hi)}", "ratio_db": ratio_db})
        if ratio_db < worst["ratio_db"]:
            worst = {"band_hz": f"{int(lo)}-{int(hi)}", "ratio_db": ratio_db}

    overall = round(10 * math.log10((Pr.sum().item() + 1e-12) / (Pm.sum().item() + 1e-12)), 2)
    return {"overall_db": overall, "worst_band": worst, "bands": bands}


def leakage_matrix(stems: Dict[str, torch.Tensor], n_fft: int = 2048, hop: int = 512) -> dict:
    """Correlation of stems' energy envelopes. High off-diagonal = the same
    events show up in multiple stems = bleed. Proxy metric (labeled as such)."""
    win = torch.hann_window(n_fft)
    envs = {}
    for n, s in stems.items():
        S = torch.stft(_to_mono(s), n_fft, hop, window=win, return_complex=True).abs()
        envs[n] = S.sum(dim=0)  # [frames]
    L = min(e.shape[-1] for e in envs.values())

    def pearson(a: torch.Tensor, b: torch.Tensor) -> float:
        a = a[:L] - a[:L].mean()
        b = b[:L] - b[:L].mean()
        return float((a * b).sum() / (a.norm() * b.norm() + 1e-9))

    names = list(envs)
    pairs, offdiag = {}, []
    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            if j <= i:
                continue
            c = round(pearson(envs[ni], envs[nj]), 3)
            pairs[f"{ni}~{nj}"] = c
            offdiag.append(abs(c))
    return {
        "mean_offdiagonal": round(sum(offdiag) / max(1, len(offdiag)), 3),
        "pairs": pairs,
    }


def sanity_report(stems: Dict[str, torch.Tensor]) -> dict:
    out = {}
    for n, s in stems.items():
        x = s.detach().to("cpu", torch.float32)
        peak = x.abs().max().item()
        rms = x.pow(2).mean().sqrt().item()
        out[n] = {
            "peak_dbfs": round(20 * math.log10(peak + 1e-9), 2),
            "rms_dbfs": round(20 * math.log10(rms + 1e-9), 2),
            "clip_pct": round((x.abs() >= 0.999).float().mean().item() * 100, 3),
            "nan_or_inf": bool(torch.isnan(x).any() or torch.isinf(x).any()),
        }
    return out


def full_report(
    mix: torch.Tensor,
    stems: Dict[str, torch.Tensor],
    sr: int = 44100,
    references: Optional[Dict[str, torch.Tensor]] = None,
) -> dict:
    """Run the whole diagnostic suite. `references` (optional) enables SI-SDR."""
    report = {
        "n_stems": len(stems),
        "stems": list(stems.keys()),
        "reconstruction": reconstruction_report(mix, stems),
        "spectral_completeness": spectral_completeness(mix, stems, sr=sr),
        "leakage": leakage_matrix(stems),
        "sanity": sanity_report(stems),
    }
    if references:
        sisdr = {}
        for name, est in stems.items():
            if name in references:
                sisdr[name] = round(si_sdr(est, references[name]), 2)
        if sisdr:
            report["si_sdr_db"] = sisdr
    return report


def print_report(report: dict) -> None:
    r = report
    print("\n===================  QUALITY DIAGNOSTICS  ===================")
    print(f"Elements separated : {r['n_stems']}  ->  {', '.join(r['stems'])}")
    rec = r["reconstruction"]
    print("\n-- No-hollow / integrity (reconstruction) --")
    print(f"   residual energy      : {rec['residual_energy_db']} dB   (lower is better; <-30 = excellent)")
    print(f"   mix correlation      : {rec['reconstruction_correlation']}")
    print(f"   verdict              : {rec['verdict']}")
    sc = r["spectral_completeness"]
    print("\n-- Full-spectrum completeness (per-band recon vs mix) --")
    print(f"   overall              : {sc['overall_db']} dB")
    print(f"   worst band           : {sc['worst_band']['band_hz']} Hz @ {sc['worst_band']['ratio_db']} dB")
    lk = r["leakage"]
    print("\n-- Separation cleanliness (stem cross-bleed, proxy) --")
    print(f"   mean off-diagonal    : {lk['mean_offdiagonal']}  (lower = cleaner; 0 = perfectly independent)")
    print("\n-- Sanity (broken-output checks) --")
    for name, s in r["sanity"].items():
        flag = "  <-- CHECK" if (s["nan_or_inf"] or s["clip_pct"] > 0.1) else ""
        print(f"   {name:<10} peak {s['peak_dbfs']:>7} dBFS | rms {s['rms_dbfs']:>7} dBFS | clip {s['clip_pct']}%{flag}")
    if "si_sdr_db" in r:
        print("\n-- SI-SDR vs reference (higher is better) --")
        for name, v in r["si_sdr_db"].items():
            print(f"   {name:<10} {v} dB")
    print("=============================================================\n")
