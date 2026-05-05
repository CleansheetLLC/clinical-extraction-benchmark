"""
MedASR Transcription Server

A lightweight FastAPI wrapper around Google's MedASR model for medical
speech-to-text. Designed to run on Athena (192.168.4.23) alongside Ollama.

Usage:
    pip install fastapi uvicorn torch librosa soundfile
    pip install git+https://github.com/huggingface/transformers.git@65dc261512cbdb1ee72b88ae5b222f2605aad8e5

    python medasr_server.py                    # default: 0.0.0.0:8002
    python medasr_server.py --port 8003        # custom port
    python medasr_server.py --device cpu       # force CPU

The model is ~420MB and loads on first request or at startup with --preload.
"""

import argparse
import io
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import librosa
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

MODEL_ID = "google/medasr"
SAMPLE_RATE = 16_000

# Global state
_pipe = None
_device = None


def get_pipeline():
    global _pipe, _device
    if _pipe is None:
        from transformers import pipeline as hf_pipeline

        _device = _device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Loading MedASR on {_device}...")
        t0 = time.time()
        _pipe = hf_pipeline(
            "automatic-speech-recognition",
            model=MODEL_ID,
            device=_device,
        )
        print(f"MedASR loaded in {time.time() - t0:.1f}s")
    return _pipe


@asynccontextmanager
async def lifespan(app: FastAPI):
    if app.state.preload:
        get_pipeline()
    yield


app = FastAPI(
    title="MedASR Transcription Server",
    description="Medical speech-to-text via Google MedASR",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model": MODEL_ID,
        "device": _device or ("cuda" if torch.cuda.is_available() else "cpu"),
        "loaded": _pipe is not None,
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """Transcribe an audio file. Accepts WAV, M4A, MP3, FLAC, OGG."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    t0 = time.time()

    try:
        audio_bytes = await file.read()
        # Try librosa/soundfile first (works for WAV, FLAC)
        try:
            speech, sr = librosa.load(io.BytesIO(audio_bytes), sr=SAMPLE_RATE, mono=True)
        except Exception:
            # Fallback: use ffmpeg to convert M4A/MP3/etc. to WAV
            suffix = Path(file.filename or "audio").suffix or ".m4a"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_in:
                tmp_in.write(audio_bytes)
                tmp_in_path = tmp_in.name
            tmp_out_path = tmp_in_path + ".wav"
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in_path, "-ar", str(SAMPLE_RATE),
                     "-ac", "1", "-f", "wav", tmp_out_path],
                    capture_output=True, check=True, timeout=30,
                )
                speech, sr = librosa.load(tmp_out_path, sr=SAMPLE_RATE, mono=True)
            finally:
                Path(tmp_in_path).unlink(missing_ok=True)
                Path(tmp_out_path).unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(400, f"Could not decode audio: {e}")

    audio_duration_s = len(speech) / SAMPLE_RATE

    pipe = get_pipeline()
    result = pipe(
        speech,
        chunk_length_s=20,
        stride_length_s=2,
    )

    processing_ms = round((time.time() - t0) * 1000)
    text = result.get("text", "") if isinstance(result, dict) else str(result)

    return JSONResponse({
        "text": text,
        "audio_duration_s": round(audio_duration_s, 2),
        "processing_ms": processing_ms,
        "realtime_factor": round(processing_ms / (audio_duration_s * 1000), 2) if audio_duration_s > 0 else 0,
        "model": MODEL_ID,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MedASR Transcription Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--device", default=None, help="cuda or cpu (auto-detect if omitted)")
    parser.add_argument("--preload", action="store_true", help="Load model at startup")
    args = parser.parse_args()

    _device = args.device
    app.state.preload = args.preload

    uvicorn.run(app, host=args.host, port=args.port)
