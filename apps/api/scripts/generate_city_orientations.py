"""Generate the three bounded Roamstead city-orientation assets once.

This administrative command is intentionally not part of an API request or scheduler.
It uploads private media to Cloud Storage and persists judge-visible model proof in
Firestore. Property evidence never consumes these generated assets.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from google.genai import types

from app.city_orientations import CITY_ORIENTATIONS, DISCLAIMER, NARRATION_MODEL, VIDEO_MODEL
from app.cloud import configure_credentials, persist_document, upload_city_orientation


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _configure_cloud_credentials() -> None:
    token = os.getenv("GCP_ACCESS_TOKEN")
    if not token:
        return
    from google.oauth2.credentials import Credentials

    configure_credentials(Credentials(token=token))


def _write_audio(path: Path, data: bytes, mime_type: str) -> None:
    if "wav" in mime_type.casefold():
        path.write_bytes(data)
        return
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(data)


def _generate_video(client: genai.Client, prompt: str, path: Path) -> None:
    operation = client.models.generate_videos(
        model=VIDEO_MODEL,
        prompt=prompt,
        config=types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=8,
            aspect_ratio="16:9",
            resolution="720p",
        ),
    )
    deadline = time.monotonic() + 12 * 60
    while not operation.done:
        if time.monotonic() >= deadline:
            raise TimeoutError("Veo city-orientation generation exceeded 12 minutes")
        time.sleep(10)
        operation = client.operations.get(operation)
    videos = operation.response.generated_videos if operation.response else []
    if not videos:
        raise RuntimeError("Veo returned no city-orientation video")
    video = videos[0].video
    client.files.download(file=video)
    video.save(str(path))


def _generate_narration(client: genai.Client, city: str, transcript: str, path: Path) -> None:
    response = client.models.generate_content(
        model=NARRATION_MODEL,
        contents=(
            f"Read this concise city orientation in a warm, calm, trustworthy American English voice. "
            f"Do not add or remove facts. City: {city}. Script: {transcript}"
        ),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code="en-US",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                ),
            ),
        ),
    )
    parts = response.candidates[0].content.parts if response.candidates else []
    audio = next((part.inline_data for part in parts if part.inline_data and part.inline_data.data), None)
    if not audio:
        raise RuntimeError("Gemini TTS returned no narration audio")
    _write_audio(path, audio.data, audio.mime_type or "audio/L16;rate=24000")


def generate(city_slugs: list[str]) -> None:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required")
    _configure_cloud_credentials()
    client = genai.Client(api_key=api_key)
    with tempfile.TemporaryDirectory(prefix="roamstead-city-orientations-") as temp_dir:
        root = Path(temp_dir)
        for slug in city_slugs:
            definition = CITY_ORIENTATIONS[slug]
            print(f"Generating bounded city orientation: {definition['city']}", flush=True)
            video_path = root / f"{slug}.mp4"
            audio_path = root / f"{slug}.wav"
            generated_at = datetime.now(timezone.utc).isoformat()
            record = {
                "slug": slug,
                "city": definition["city"],
                "country": definition["country"],
                "headline": definition["headline"],
                "transcript": definition["transcript"],
                "video_model": VIDEO_MODEL,
                "narration_model": NARRATION_MODEL,
                "video_status": "GENERATING",
                "narration_status": "GENERATING",
                "video_duration_seconds": 8,
                "prompt_hash": _hash(definition["video_prompt"]),
                "transcript_hash": _hash(definition["transcript"]),
                "generated_at": generated_at,
                "disclaimer": DISCLAIMER,
                "property_evidence_eligible": False,
            }
            persist_document("city_orientations", slug, record)
            try:
                _generate_video(client, definition["video_prompt"], video_path)
                record["video_object"] = upload_city_orientation(slug, "video", str(video_path), "video/mp4")
                record["video_status"] = "READY"
                persist_document("city_orientations", slug, record)
                _generate_narration(client, definition["city"], definition["transcript"], audio_path)
                record["audio_object"] = upload_city_orientation(slug, "audio", str(audio_path), "audio/wav")
                record["narration_status"] = "READY"
                persist_document("city_orientations", slug, record)
            except Exception as exc:
                if record["video_status"] != "READY":
                    record["video_status"] = "FAILED"
                if record["narration_status"] != "READY":
                    record["narration_status"] = "FAILED"
                record["error_code"] = type(exc).__name__
                persist_document("city_orientations", slug, record)
                raise
            print(f"Persisted {definition['city']} with Veo and Gemini TTS proof", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-bounded-generation", action="store_true")
    parser.add_argument("--city", choices=sorted(CITY_ORIENTATIONS), action="append")
    args = parser.parse_args()
    if not args.confirm_bounded_generation:
        raise SystemExit("Pass --confirm-bounded-generation to acknowledge exactly one 8-second video per selected city.")
    generate(args.city or list(CITY_ORIENTATIONS))
