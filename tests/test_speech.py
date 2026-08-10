"""Regression tests for wake-word audio streaming."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

import numpy as np

from bmo.speech import WakeWordDetector


class _TriggeringModel:
    def __init__(self) -> None:
        self.prediction_buffer = {"wakeword": [0.0]}
        self.predict_calls: list[np.ndarray] = []
        self.reset_calls = 0

    def predict(self, audio: np.ndarray) -> None:
        self.predict_calls.append(audio.copy())
        self.prediction_buffer["wakeword"] = [1.0]

    def reset(self) -> None:
        self.reset_calls += 1


class _InputStream:
    def __init__(self, responses: list[tuple[np.ndarray, bool]]) -> None:
        self.responses = iter(responses)
        self.read_calls = 0

    def __enter__(self) -> _InputStream:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, frames: int) -> tuple[np.ndarray, bool]:
        del frames
        self.read_calls += 1
        return next(self.responses)


class WakeWordStreamingTests(unittest.TestCase):
    @staticmethod
    def _detector(model: _TriggeringModel) -> WakeWordDetector:
        detector = WakeWordDetector.__new__(WakeWordDetector)
        detector.threshold = 0.5
        detector.model = model
        return detector

    def _listen(
        self,
        detector: WakeWordDetector,
        stream: _InputStream,
        *,
        input_rate: int,
        input_chunk_size: int,
        use_resampling: bool,
    ) -> None:
        with (
            patch("bmo.speech.sd.InputStream", return_value=stream),
            patch("bmo.speech.select.select", return_value=([], [], [])),
        ):
            detector._listen_loop(
                {
                    "samplerate": input_rate,
                    "channels": 1,
                    "dtype": "int16",
                    "blocksize": input_chunk_size,
                    "device": None,
                },
                input_chunk_size,
                detector.CHUNK_SIZE,
                use_resampling,
                threading.Event(),
            )

    def test_safe_mode_accumulates_real_time_before_resampling(self) -> None:
        model = _TriggeringModel()
        detector = self._detector(model)
        stream = _InputStream(
            [
                (np.full(1024, index + 1, dtype=np.int16), False)
                for index in range(4)
            ]
        )

        self._listen(
            detector,
            stream,
            input_rate=44100,
            input_chunk_size=1024,
            use_resampling=True,
        )

        self.assertEqual(stream.read_calls, 4)
        self.assertEqual(len(model.predict_calls), 1)
        self.assertEqual(len(model.predict_calls[0]), detector.CHUNK_SIZE)

    def test_quiet_chunks_are_sent_to_streaming_model(self) -> None:
        model = _TriggeringModel()
        detector = self._detector(model)
        stream = _InputStream(
            [(np.zeros(detector.CHUNK_SIZE, dtype=np.int16), False)]
        )

        self._listen(
            detector,
            stream,
            input_rate=detector.SAMPLE_RATE,
            input_chunk_size=detector.CHUNK_SIZE,
            use_resampling=False,
        )

        self.assertEqual(len(model.predict_calls), 1)
        np.testing.assert_array_equal(
            model.predict_calls[0],
            np.zeros(detector.CHUNK_SIZE, dtype=np.int16),
        )

    def test_one_overflow_resets_state_and_keeps_listening(self) -> None:
        model = _TriggeringModel()
        detector = self._detector(model)
        stream = _InputStream(
            [
                (np.ones(detector.CHUNK_SIZE, dtype=np.int16), True),
                (np.ones(detector.CHUNK_SIZE, dtype=np.int16), False),
            ]
        )

        self._listen(
            detector,
            stream,
            input_rate=detector.SAMPLE_RATE,
            input_chunk_size=detector.CHUNK_SIZE,
            use_resampling=False,
        )

        self.assertEqual(stream.read_calls, 2)
        self.assertEqual(len(model.predict_calls), 1)
        self.assertEqual(model.reset_calls, 2)


if __name__ == "__main__":
    unittest.main()
