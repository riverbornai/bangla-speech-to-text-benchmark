"""
Google Cloud Speech-to-Text v2 (Chirp 2) -- streaming benchmark adapter.

Unlike google_stt.transcribe() (one-shot recognize on the whole file), this
simulates a live mic feed: the wav is split into fixed-size PCM chunks paced
in real time over a bidi StreamingRecognize call, and the timing of every
interim/final result is recorded. That's what makes latency numbers here
mean anything -- sending the whole file at once would make "first partial"
latency meaningless (no real streaming client can send audio it hasn't
recorded yet).

Returns a dict (not a str, unlike batch adapters) so the streaming runner
can capture streaming-specific metrics -- see run_streaming_transcription.py
and score_streaming.py.
"""
import os
import time
import wave

from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech

DEFAULT_CHUNK_MS = 100


def _read_pcm_chunks(wav_path: str, chunk_ms: int):
    with wave.open(wav_path, "rb") as w:
        sample_rate = w.getframerate()
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        n_frames = w.getnframes()
        duration_s = n_frames / sample_rate
        frames_per_chunk = max(1, int(sample_rate * chunk_ms / 1000))
        chunks = []
        while True:
            data = w.readframes(frames_per_chunk)
            if not data:
                break
            chunks.append(data)
    return chunks, sample_rate, channels, sampwidth, duration_s


def stream_transcribe(wav_path: str, cfg: dict) -> dict:
    project = os.environ[cfg["project_env"]]
    location = cfg.get("location", "us-central1")
    chunk_ms = cfg.get("chunk_ms", DEFAULT_CHUNK_MS)

    chunks, sample_rate, channels, sampwidth, audio_duration_s = _read_pcm_chunks(wav_path, chunk_ms)
    if sampwidth != 2:
        raise ValueError(f"{wav_path}: expected 16-bit PCM wav, got {sampwidth * 8}-bit")

    client = speech_v2.SpeechClient(
        client_options={"api_endpoint": f"{location}-speech.googleapis.com"}
    )
    recognizer = f"projects/{project}/locations/{location}/recognizers/_"

    recognition_config = cloud_speech.RecognitionConfig(
        explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            audio_channel_count=channels,
        ),
        language_codes=[cfg.get("language_code", "bn-BD")],
        model=cfg.get("model", "chirp_2"),
    )
    streaming_config = cloud_speech.StreamingRecognitionConfig(
        config=recognition_config,
        streaming_features=cloud_speech.StreamingRecognitionFeatures(interim_results=True),
    )

    def request_generator():
        yield cloud_speech.StreamingRecognizeRequest(
            recognizer=recognizer, streaming_config=streaming_config,
        )
        chunk_s = chunk_ms / 1000
        for chunk in chunks:
            t_chunk_start = time.perf_counter()
            yield cloud_speech.StreamingRecognizeRequest(audio=chunk)
            # Pace sends to real time -- without this every chunk lands
            # instantly and "first partial/final" latency stops meaning
            # anything relative to a live mic feed.
            sleep_for = chunk_s - (time.perf_counter() - t_chunk_start)
            if sleep_for > 0:
                time.sleep(sleep_for)

    t0 = time.perf_counter()
    responses = client.streaming_recognize(requests=request_generator())

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_segments = []
    partial_transcripts = []

    for response in responses:
        t_now = time.perf_counter() - t0
        for result in response.results:
            if not result.alternatives:
                continue
            transcript = result.alternatives[0].transcript
            if result.is_final:
                num_final += 1
                final_segments.append(transcript)
                if first_final_latency_s is None:
                    first_final_latency_s = t_now
            else:
                num_partial += 1
                partial_transcripts.append({"t": round(t_now, 3), "transcript": transcript})
                if first_partial_latency_s is None:
                    first_partial_latency_s = t_now
            last_result_latency_s = t_now

    total_latency_s = time.perf_counter() - t0

    return {
        "transcript": " ".join(final_segments).strip(),
        "audio_duration_s": round(audio_duration_s, 3),
        "total_latency_s": round(total_latency_s, 3),
        "first_partial_latency_s": round(first_partial_latency_s, 3) if first_partial_latency_s is not None else None,
        "first_final_latency_s": round(first_final_latency_s, 3) if first_final_latency_s is not None else None,
        "last_result_latency_s": round(last_result_latency_s, 3) if last_result_latency_s is not None else None,
        # time after the last audio chunk was sent until the final transcript
        # arrived -- the "tail" a real user would perceive after they stop talking
        "finalization_latency_s": round(total_latency_s - audio_duration_s, 3),
        "rtf": round(total_latency_s / audio_duration_s, 4) if audio_duration_s else None,
        "num_partial_results": num_partial,
        "num_final_results": num_final,
        "partial_transcripts": partial_transcripts,
    }
