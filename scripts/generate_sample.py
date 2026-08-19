import numpy as np
import soundfile as sf
from pathlib import Path

def generate_test_audio(output_path: str = "samples/test_mix.wav", duration: float = 6.0, sr: int = 44100):
    """
    Synthesizes a multi-instrument test mix with distinct musical layers:
    - Kick & Snare rhythm (Drums)
    - Sub-bassline (Bass)
    - Harmonic organ / chord progression (Keys / Other)
    - High melodic lead (Vocals / Lead)
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    
    # 1. Drums: Kick & Snare rhythm
    kick = np.zeros_like(t)
    snare = np.zeros_like(t)
    bpm = 120
    beat_dur = 60.0 / bpm
    
    for beat in range(int(duration / beat_dur)):
        beat_t = beat * beat_dur
        idx = int(beat_t * sr)
        # Kick on beat 0, 2
        if beat % 2 == 0:
            env = np.exp(-np.linspace(0, 10, int(0.3 * sr)))
            freq = np.linspace(150, 45, len(env))
            hit = np.sin(2 * np.pi * freq * np.linspace(0, 0.3, len(env))) * env
            end_idx = min(idx + len(hit), len(kick))
            kick[idx:end_idx] += hit[:end_idx - idx] * 0.8
        # Snare on beat 1, 3
        else:
            env = np.exp(-np.linspace(0, 8, int(0.25 * sr)))
            noise = (np.random.rand(len(env)) * 2 - 1) * env
            body = np.sin(2 * np.pi * 180 * np.linspace(0, 0.25, len(env))) * env
            hit = (noise * 0.7 + body * 0.3)
            end_idx = min(idx + len(hit), len(snare))
            snare[idx:end_idx] += hit[:end_idx - idx] * 0.6
            
    drums = kick + snare

    # 2. Bassline: 55Hz (A1) & 73Hz (D2)
    bass = np.zeros_like(t)
    for i, note_f in enumerate([55, 55, 73.4, 65.4]):
        start = int(i * 1.5 * sr)
        end = int(min((i + 1) * 1.5 * sr, len(t)))
        dur_note = (end - start) / sr
        t_note = np.linspace(0, dur_note, end - start)
        bass[start:end] = np.sin(2 * np.pi * note_f * t_note) * 0.6 + np.sin(2 * np.pi * note_f * 2 * t_note) * 0.2

    # 3. Keys / Chords (A minor progression: A - C - E)
    keys = (
        np.sin(2 * np.pi * 220.0 * t) * 0.2 +
        np.sin(2 * np.pi * 261.6 * t) * 0.2 +
        np.sin(2 * np.pi * 329.6 * t) * 0.2
    ) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t))  # Tremolo

    # 4. Lead Melody / Vocal Formants (Harmonics at 440Hz, 880Hz, 1320Hz)
    lead = (
        np.sin(2 * np.pi * 440.0 * t) * 0.3 +
        np.sin(2 * np.pi * 880.0 * t) * 0.15 +
        np.sin(2 * np.pi * 1320.0 * t) * 0.08
    ) * (np.sin(2 * np.pi * 2.0 * t) > 0).astype(float)

    # Master stereo mix
    left = drums * 0.8 + bass * 0.7 + keys * 0.5 + lead * 0.6
    right = drums * 0.8 + bass * 0.7 + keys * 0.5 + lead * 0.6
    
    stereo = np.vstack([left, right]).T
    # Normalize
    stereo = stereo / np.max(np.abs(stereo)) * 0.9

    sf.write(output_path, stereo, sr, subtype="PCM_24")
    print(f"[OK] Created synthetic multi-instrument test track: {output_path}")

if __name__ == "__main__":
    generate_test_audio()
