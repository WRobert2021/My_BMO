"""Wake-word detection and Whisper transcription."""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

from bmo.audio import choose_input_samplerate


class WhisperTranscriber:
    def __init__(self, binary: str | Path, model: str | Path, threads: int = 4) -> None:
        self.binary = Path(binary)
        self.model = Path(model)
        self.threads = threads

    def transcribe(
        self,
        filename: str | Path,
        archive_directory: str | Path | None = None,
    ) -> str:
        print("Transcribing...", flush=True)
        try:
            result = subprocess.run(
                [
                    str(self.binary),
                    "-m",
                    str(self.model),
                    "-l",
                    "en",
                    "-t",
                    str(self.threads),
                    "-f",
                    str(filename),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if archive_directory:
                archive_path = Path(archive_directory)
                archive_path.mkdir(parents=True, exist_ok=True)
                (archive_path / "whisper_stdout.txt").write_text(
                    result.stdout, encoding="utf-8"
                )
                (archive_path / "whisper_stderr.txt").write_text(
                    result.stderr, encoding="utf-8"
                )
            if result.returncode != 0:
                error = result.stderr.strip() or f"exit code {result.returncode}"
                print(f"Transcription Error: {error}", flush=True)
                return ""

            lines = result.stdout.strip().splitlines()
            if not lines or not lines[-1].strip():
                transcription = ""
            else:
                last_line = lines[-1].strip()
                transcription = last_line.split("]", 1)[1].strip() if "]" in last_line else last_line

            print(f"Heard: '{transcription}'", flush=True)
            return transcription.strip()
        except Exception as exc:
            print(f"Transcription Error: {exc}", flush=True)
            if archive_directory:
                try:
                    Path(archive_directory, "whisper_error.txt").write_text(
                        str(exc) + "\n", encoding="utf-8"
                    )
                except OSError:
                    pass
            return ""


class WakeWordDetector:
    CHUNK_SIZE = 1280
    SAMPLE_RATE = 16000

    def __init__(
        self,
        model_path: str | Path,
        threshold: float,
        input_device: int | None,
        preferred_rate: int | None,
    ) -> None:
        self.model_path = Path(model_path)
        self.threshold = threshold
        self.input_device = input_device
        self.preferred_rate = preferred_rate
        self.model: Model | None = None
        self._load_model()

    @property
    def available(self) -> bool:
        return self.model is not None

    def _load_model(self) -> None:
        print("[INIT] Loading Wake Word...", flush=True)
        if not self.model_path.exists():
            print(f"[CRITICAL] Model not found: {self.model_path}", flush=True)
            return
        try:
            self.model = Model(
                wakeword_models=[str(self.model_path)],
                inference_framework="onnx",
            )
            print("[INIT] Wake Word Loaded.", flush=True)
        except Exception as exc:
            print(f"[CRITICAL] Failed to load model: {exc}", flush=True)

    def wait_for_trigger(
        self,
        ptt_event: threading.Event,
        shutdown_event: threading.Event | None = None,
        alternate_event: threading.Event | None = None,
    ) -> str:
        ptt_event.clear()
        if alternate_event and alternate_event.is_set():
            return "ALTERNATE"
        if self.model:
            self.model.reset()
        else:
            while not (shutdown_event and shutdown_event.is_set()):
                if alternate_event and alternate_event.is_set():
                    return "ALTERNATE"
                if ptt_event.wait(timeout=0.1):
                    ptt_event.clear()
                    return "PTT"
            return "STOP"

        input_rate = choose_input_samplerate(self.input_device, self.preferred_rate)
        use_resampling = input_rate != self.SAMPLE_RATE
        input_chunk_size = (
            int(self.CHUNK_SIZE * (input_rate / self.SAMPLE_RATE))
            if use_resampling
            else self.CHUNK_SIZE
        )
        stream_args: dict[str, Any] = {
            "samplerate": input_rate,
            "channels": 1,
            "dtype": "int16",
            "blocksize": input_chunk_size,
            "device": self.input_device,
        }

        try:
            self._listen_loop(
                stream_args,
                input_chunk_size,
                self.CHUNK_SIZE,
                use_resampling,
                ptt_event,
                shutdown_event,
                alternate_event,
            )
        except StopIteration as trigger:
            return str(trigger)
        except Exception as exc:
            if shutdown_event and shutdown_event.is_set():
                return "STOP"
            print(
                f"[AUDIO] Stream failed with defaults: {exc}. "
                "Retrying with loose settings...",
                flush=True,
            )
            if self.model:
                self.model.reset()
            try:
                stream_args["blocksize"] = 1024
                stream_args["latency"] = "high"
                self._listen_loop(
                    stream_args,
                    1024,
                    self.CHUNK_SIZE,
                    True,
                    ptt_event,
                    shutdown_event,
                    alternate_event,
                )
            except StopIteration as trigger:
                return str(trigger)
            except Exception as second_exc:
                if shutdown_event and shutdown_event.is_set():
                    return "STOP"
                print(f"[CRITICAL] Wake Word Stream Error: {second_exc}", flush=True)
                while not (shutdown_event and shutdown_event.is_set()):
                    if alternate_event and alternate_event.is_set():
                        return "ALTERNATE"
                    if ptt_event.wait(timeout=0.1):
                        ptt_event.clear()
                        return "PTT"
                return "STOP"

        return "STOP" if shutdown_event and shutdown_event.is_set() else "WAKE"

    def _listen_loop(
        self,
        stream_args: dict[str, Any],
        input_chunk_size: int,
        target_chunk_size: int,
        use_resampling: bool,
        ptt_event: threading.Event,
        shutdown_event: threading.Event | None = None,
        alternate_event: threading.Event | None = None,
    ) -> None:
        if self.model is None:
            raise RuntimeError("wake-word model is unavailable")

        input_rate = int(stream_args["samplerate"])
        model_input_size = (
            int(round(target_chunk_size * input_rate / self.SAMPLE_RATE))
            if use_resampling
            else target_chunk_size
        )
        pending_audio = np.empty(0, dtype=np.int16)

        with sd.InputStream(**stream_args) as stream:
            print(
                f"[AUDIO] Listening with rate {stream_args['samplerate']} "
                f"and block {stream_args['blocksize']}",
                flush=True,
            )
            while not (shutdown_event and shutdown_event.is_set()):
                if alternate_event and alternate_event.is_set():
                    raise StopIteration("ALTERNATE")
                if ptt_event.is_set():
                    ptt_event.clear()
                    raise StopIteration("PTT")

                try:
                    readable, _, _ = select.select([sys.stdin], [], [], 0.001)
                except (OSError, ValueError):
                    readable = []
                if readable:
                    sys.stdin.readline()
                    raise StopIteration("CLI")

                try:
                    data, overflow = stream.read(input_chunk_size)
                    if shutdown_event and shutdown_event.is_set():
                        return
                    if overflow:
                        print(
                            "[AUDIO] Input overflow; discarding stale audio.",
                            flush=True,
                        )
                        pending_audio = np.empty(0, dtype=np.int16)
                        self.model.reset()
                        continue
                except Exception as exc:
                    raise RuntimeError(f"Audio read failed: {exc}") from exc

                audio_data = np.frombuffer(data, dtype=np.int16)
                if audio_data.ndim > 1:
                    audio_data = audio_data.flatten()
                pending_audio = np.concatenate((pending_audio, audio_data))

                while len(pending_audio) >= model_input_size:
                    model_audio = pending_audio[:model_input_size]
                    pending_audio = pending_audio[model_input_size:]

                    if use_resampling:
                        step = len(model_audio) / target_chunk_size
                        indices = np.arange(0, len(model_audio), step)[
                            :target_chunk_size
                        ].astype(int)
                        model_audio = model_audio[indices]

                    current_max = int(np.max(np.abs(model_audio)))
                    # OpenWakeWord is a streaming model. Feed quiet chunks too so
                    # its temporal context matches real time instead of joining
                    # unrelated loud fragments from different moments.
                    self.model.predict(model_audio)
                    for model_name in self.model.prediction_buffer.keys():
                        score = list(self.model.prediction_buffer[model_name])[-1]
                        if score > 0.1:
                            print(
                                f"\r[Oww] Score: {score:.3f} | Vol: "
                                f"{current_max}   ",
                                end="",
                                flush=True,
                            )
                        if score > self.threshold:
                            print(
                                f"\n[WAKE] Triggered on '{model_name}' "
                                f"with score: {score:.2f}",
                                flush=True,
                            )
                            self.model.reset()
                            return


def extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from model output."""
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass
    return None
