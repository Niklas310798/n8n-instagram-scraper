"""Transcribe audio to text.

Two backends, switched via WHISPER_MODE:
  - LOCAL: faster-whisper (CTranslate2, runs on CPU, no torch needed)
  - API:   OpenAI whisper-1
"""
import os
from typing import Any, Dict
from config import WHISPER_MODE, WHISPER_MODEL, WHISPER_COMPUTE_TYPE, OPENAI_API_KEY

# Lazily-initialised local model so importing this module stays cheap.
_local = None


def _local_model():
    global _local
    if _local is None:
        from faster_whisper import WhisperModel
        _local = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)
    return _local


def transcribe_audio(audio_path: str) -> Dict[str, Any]:
    """Return {language, text, segments:[{start,end,text}]} for an audio file."""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if WHISPER_MODE == "LOCAL":
        model = _local_model()
        segments, info = model.transcribe(audio_path)
        seg_list, texts = [], []
        for s in segments:
            text = s.text.strip()
            seg_list.append({"start": s.start, "end": s.end, "text": text})
            texts.append(text)
        return {"language": info.language, "text": " ".join(texts).strip(), "segments": seg_list}

    # OpenAI API mode
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    with open(audio_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    seg_list = [
        {"start": s.start, "end": s.end, "text": s.text.strip()}
        for s in (result.segments or [])
    ]
    return {"language": result.language, "text": result.text.strip(), "segments": seg_list}
