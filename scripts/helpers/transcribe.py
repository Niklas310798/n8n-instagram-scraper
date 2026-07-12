"""Transcribe audio to text.

Two backends, switched via WHISPER_MODE:
  - LOCAL: faster-whisper (CTranslate2, runs on CPU, no torch needed)
  - API:   OpenAI whisper-1
"""
import os
import subprocess
from typing import Any, Dict
from config import WHISPER_MODE, WHISPER_MODEL, WHISPER_COMPUTE_TYPE, OPENAI_API_KEY

_EMPTY = {"language": None, "text": "", "segments": []}


def _has_audio(path: str) -> bool:
    """True if the file contains at least one audio stream (ffprobe)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        return b"audio" in out.stdout
    except Exception:
        return True  # if probing fails, let the transcriber try (and error loudly)

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

    # Silent videos (animations, text-only clips) have no audio stream at all —
    # skip transcription instead of crashing inside the decoder.
    if not _has_audio(audio_path):
        return dict(_EMPTY)

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
