import argparse
import json
import time
import wave

from stenograph.audio import pcm_to_float
from stenograph.config import enforce_offline


def main():
    parser = argparse.ArgumentParser(description="Локальный замер скорости на реальном фрагменте речи")
    parser.add_argument("--model", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    enforce_offline()
    from faster_whisper import WhisperModel

    with wave.open(args.audio) as audio:
        if audio.getsampwidth() != 2:
            raise ValueError("Нужен 16-bit PCM WAV")
        duration = audio.getnframes() / audio.getframerate()
        samples = pcm_to_float(audio.readframes(audio.getnframes()), audio.getnchannels(), audio.getframerate())
    model = WhisperModel(args.model, local_files_only=True, device=args.device,
                         compute_type="int8" if args.device == "cpu" else "int8_float16")
    started = time.perf_counter()
    segments, _ = model.transcribe(samples, language="ru", beam_size=1, vad_filter=True)
    text = " ".join(s.text for s in segments)
    elapsed = time.perf_counter() - started
    print(json.dumps({"duration_seconds": duration, "inference_seconds": round(elapsed, 2),
                      "rtf": round(elapsed / max(duration, 0.001), 3), "text": text}, ensure_ascii=False, indent=2))
    print("Один источник: RTF < 1. Два источника: сумма RTF < 1; желателен запас 30%. Замерьте несколько записей.")


if __name__ == "__main__":
    main()
