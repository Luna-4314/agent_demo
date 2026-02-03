# stt_gcp.py
from google.cloud import speech_v1 as speech

def transcribe_wav(
    wav_path: str,
    language_code: str = "en-US",
    sample_rate_hz: int = 16000
) -> str:
    """
    Transcribe a local WAV file using Google Cloud Speech-to-Text.
    Expect: LINEAR16 PCM, mono, sample_rate_hz (default 16k).
    """
    client = speech.SpeechClient()

    with open(wav_path, "rb") as f:
        content = f.read()

    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate_hz,
        language_code=language_code,
        enable_automatic_punctuation=True,
    )

    response = client.recognize(config=config, audio=audio)

    parts = []
    for result in response.results:
        if result.alternatives:
            parts.append(result.alternatives[0].transcript)

    return " ".join(parts).strip()
