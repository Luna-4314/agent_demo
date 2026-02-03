import sounddevice as sd
from scipy.io.wavfile import write

def record_wav(
    out_path="recording.wav",
    seconds=10,
    sample_rate=16000,
    channels=1
):
    print(f"🎙️ Recording... ({seconds}s). Speak now.")
    audio = sd.rec(
        int(seconds * sample_rate),
        samplerate=sample_rate,
        channels=channels,
        dtype="int16"
    )
    sd.wait()
    write(out_path, sample_rate, audio)
    print(f"✅ Saved: {out_path}")
    return out_path

