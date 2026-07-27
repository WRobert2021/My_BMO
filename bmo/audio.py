"""Audio-device selection, recording, effects, and Piper speech output."""

from __future__ import annotations

import os
import random
import re
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import scipy.signal
import sounddevice as sd


def resolve_input_device(config: dict[str, Any]) -> int | None:
    """Resolve a configured device index or case-insensitive name fragment."""
    requested = config.get("input_device")
    if requested in (None, "", "default"):
        return None

    try:
        devices = sd.query_devices()
    except Exception as exc:
        print(f"[AUDIO] Device query failed: {exc}", flush=True)
        return None

    if isinstance(requested, int) or (
        isinstance(requested, str) and requested.isdigit()
    ):
        index = int(requested)
        if 0 <= index < len(devices):
            return index
        print(f"[AUDIO] Input device index not found: {index}", flush=True)
        return None

    requested_lower = str(requested).lower()
    for index, device in enumerate(devices):
        print(
            f"[AUDIO DEBUG] Index {index}: {device.get('name')} "
            f"(In: {device.get('max_input_channels')})",
            flush=True,
        )
        if (
            device.get("max_input_channels", 0) > 0
            and requested_lower in device.get("name", "").lower()
        ):
            return index

    print(f"[AUDIO] Input device name not found: {requested}", flush=True)
    return None


def describe_input_device(device: int | None) -> None:
    if device is None:
        return
    try:
        info = sd.query_devices(device)
        print(f"[AUDIO] Using input device: {info.get('name', device)}", flush=True)
    except Exception:
        print(f"[AUDIO] Using input device index: {device}", flush=True)


def _query_input_device_info(device: int | None) -> Any:
    """Return one input-device record, including when the default is requested."""
    if device is None:
        return sd.query_devices(kind="input")
    return sd.query_devices(device)


def choose_input_samplerate(device: int | None, preferred: int | None = None) -> int:
    """Return the first supported mono int16 input sample rate."""
    candidates: list[int] = []
    if preferred:
        candidates.append(int(preferred))

    try:
        device_info = _query_input_device_info(device)
        print(f"[AUDIO DEBUG] Device Info: {device_info}", flush=True)
        default_rate = device_info.get("default_samplerate")
        if default_rate:
            candidates.append(int(default_rate))
    except Exception as exc:
        print(f"[AUDIO DEBUG] Query failed: {exc}", flush=True)

    candidates.extend([48000, 44100, 32000, 16000])
    seen: set[int] = set()
    for rate in candidates:
        if not rate or rate in seen:
            continue
        seen.add(rate)
        try:
            sd.check_input_settings(
                device=device,
                samplerate=rate,
                channels=1,
                dtype="int16",
            )
            return rate
        except Exception:
            continue

    return candidates[0] if candidates else 44100


class AudioRecorder:
    """Own microphone recording and WAV serialization."""

    def __init__(self, input_device: int | None, preferred_rate: int | None) -> None:
        self.input_device = input_device
        self.preferred_rate = preferred_rate

    def record_adaptive(
        self,
        filename: str = "input.wav",
        shutdown_event: threading.Event | None = None,
    ) -> str | None:
        print("Recording (Adaptive)...", flush=True)
        time.sleep(0.5)
        sample_rate = choose_input_samplerate(self.input_device, self.preferred_rate)

        silence_threshold = 0.006
        silence_duration = 1.5
        max_record_time = 30.0
        buffer: list[np.ndarray] = []
        silent_chunks = 0
        chunk_duration = 0.05
        chunk_size = int(sample_rate * chunk_duration)
        num_silent_chunks = int(silence_duration / chunk_duration)
        max_chunks = int(max_record_time / chunk_duration)
        recorded_chunks = 0
        silence_started = False

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            nonlocal silent_chunks, recorded_chunks, silence_started
            volume_norm = np.linalg.norm(indata) / np.sqrt(len(indata))
            buffer.append(indata.copy())
            recorded_chunks += 1
            if recorded_chunks < 5:
                return
            if volume_norm < silence_threshold:
                silent_chunks += 1
                if silent_chunks >= num_silent_chunks:
                    silence_started = True
            else:
                silent_chunks = 0

        try:
            sd.stop()
            time.sleep(0.2)
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                callback=callback,
                device=self.input_device,
                blocksize=chunk_size,
            ):
                while (
                    not silence_started
                    and recorded_chunks < max_chunks
                    and not (shutdown_event and shutdown_event.is_set())
                ):
                    sd.sleep(int(chunk_duration * 1000))
        except Exception as exc:
            print(f"[AUDIO ERROR] Adaptive Recording Failed: {exc}", flush=True)
            return None

        return self.save_audio_buffer(buffer, filename, sample_rate)

    def record_ptt(
        self,
        recording_active: threading.Event,
        filename: str = "input.wav",
        shutdown_event: threading.Event | None = None,
    ) -> str | None:
        print("Recording (PTT)...", flush=True)
        time.sleep(0.5)
        sample_rate = choose_input_samplerate(self.input_device, self.preferred_rate)
        buffer: list[np.ndarray] = []

        def callback(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            buffer.append(indata.copy())

        try:
            sd.stop()
            time.sleep(0.2)
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                callback=callback,
                device=self.input_device,
            ):
                while recording_active.is_set() and not (
                    shutdown_event and shutdown_event.is_set()
                ):
                    sd.sleep(50)
        except Exception as exc:
            print(f"[AUDIO ERROR] PTT Recording Failed: {exc}", flush=True)
            return None

        return self.save_audio_buffer(buffer, filename, sample_rate)

    @staticmethod
    def save_audio_buffer(
        buffer: list[np.ndarray],
        filename: str,
        sample_rate: int = 16000,
    ) -> str | None:
        if not buffer:
            return None

        audio_data = np.concatenate(buffer, axis=0).flatten()
        audio_data = np.nan_to_num(audio_data, nan=0.0, posinf=0.0, neginf=0.0)
        audio_data = (audio_data * 32767).astype(np.int16)
        with wave.open(filename, "wb") as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(sample_rate)
            wave_file.writeframes(audio_data.tobytes())
        return filename


class SoundPlayer:
    """Play short WAV effects through sounddevice."""

    @staticmethod
    def random_sound(directory: Path) -> str | None:
        if not directory.exists():
            return None
        files = [path for path in directory.iterdir() if path.suffix.lower() == ".wav"]
        return str(random.choice(files)) if files else None

    @staticmethod
    def play(file_path: str | None) -> None:
        if not file_path or not os.path.exists(file_path):
            return
        try:
            with wave.open(file_path, "rb") as wave_file:
                file_rate = wave_file.getframerate()
                data = wave_file.readframes(wave_file.getnframes())
                audio = np.frombuffer(data, dtype=np.int16)

            try:
                device_info = sd.query_devices(kind="output")
                native_rate = int(device_info["default_samplerate"])
            except Exception:
                native_rate = 48000

            playback_rate = file_rate
            try:
                sd.check_output_settings(device=None, samplerate=file_rate)
            except Exception:
                playback_rate = native_rate
                sample_count = int(len(audio) * (native_rate / file_rate))
                audio = scipy.signal.resample(audio, sample_count).astype(np.int16)

            sd.play(audio, playback_rate)
            sd.wait()
        except Exception:
            pass

    @staticmethod
    def stop() -> None:
        """Do not globally abort PortAudio streams owned by other threads."""
        # sounddevice.stop() affects the process-wide convenience stream and can
        # crash Core Audio when another thread owns an active InputStream.
        return


def get_piper_command() -> list[str]:
    """Use the bundled Pi binary when present, otherwise the active Python env."""
    local_binary = Path("piper/piper")
    if local_binary.exists():
        return [str(local_binary)]
    return [sys.executable, "-m", "piper"]


class PiperSpeaker:
    """Stream Piper raw PCM output to the active sounddevice output."""

    PIPER_RATE = 22050

    def __init__(self, voice_model: str) -> None:
        self.voice_model = voice_model
        self.current_process: subprocess.Popen | None = None
        self.current_volume = 0

    def stop(self) -> None:
        if self.current_process and self.current_process.poll() is None:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=1)
            except Exception:
                pass

    def speak(
        self,
        text: str,
        interrupted: threading.Event,
        shutdown_event: threading.Event | None = None,
    ) -> None:
        clean = re.sub(r"[^\w\s,.!?:-]", "", text)
        if not clean.strip():
            return

        print(f"[PIPER SPEAKING] '{clean}'", flush=True)
        try:
            self.current_process = subprocess.Popen(
                [
                    *get_piper_command(),
                    "--model",
                    self.voice_model,
                    "--output-raw",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if self.current_process.stdin is None or self.current_process.stdout is None:
                raise RuntimeError("Piper process did not expose audio pipes")

            self.current_process.stdin.write(clean.encode() + b"\n")
            self.current_process.stdin.close()

            try:
                device_info = sd.query_devices(kind="output")
                native_rate = int(device_info["default_samplerate"])
            except Exception:
                native_rate = 48000

            use_native_rate = False
            try:
                sd.check_output_settings(device=None, samplerate=self.PIPER_RATE)
            except Exception:
                use_native_rate = True

            output_rate = native_rate if use_native_rate else self.PIPER_RATE
            with sd.RawOutputStream(
                samplerate=output_rate,
                channels=1,
                dtype="int16",
                device=None,
                latency="low",
                blocksize=2048,
            ) as stream:
                while True:
                    if interrupted.is_set() or (
                        shutdown_event and shutdown_event.is_set()
                    ):
                        break
                    data = self.current_process.stdout.read(4096)
                    if not data:
                        break

                    audio_chunk = np.frombuffer(data, dtype=np.int16)
                    if not len(audio_chunk):
                        self.current_volume = 0
                        continue

                    self.current_volume = int(np.max(np.abs(audio_chunk)))
                    if use_native_rate:
                        sample_count = int(
                            len(audio_chunk) * (native_rate / self.PIPER_RATE)
                        )
                        audio_chunk = scipy.signal.resample(
                            audio_chunk, sample_count
                        ).astype(np.int16)
                    stream.write(audio_chunk.tobytes())
                time.sleep(0.5)
        except Exception as exc:
            print(f"Audio Error: {exc}", flush=True)
        finally:
            self.current_volume = 0
            if self.current_process:
                if self.current_process.stdout:
                    self.current_process.stdout.close()
                if self.current_process.poll() is None:
                    self.current_process.terminate()
                self.current_process = None
