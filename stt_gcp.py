from google.cloud import speech_v1 as speech

def transcribe_wav(
    wav_path: str,
    language_code: str = "en-US",
    sample_rate_hz: int = 1600
) -> str:
    
    client = speech.SpeechClient()

    #读取本地wav
    with open(wav_path, "rb") as f:
        content = f.read()

    #音频数据在content里
    audio = speech.RecognitionAudio(content=content)
    #识别
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate_hz,
        language_code=language_code,
        enable_automatic_punctuation=True,
    )

    #把音频同步发到Google，等待返回识别结果
    response = client.recognize(config=config, audio=audio)

    parts = []
    for result in response.results:
        if result.alternatives:
            parts.append(result.alternatives[0].transcript)

    return " ".join(parts).strip()

