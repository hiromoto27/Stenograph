import json
import wave

import numpy as np

from stenograph.audio import pcm_to_float, recover_audio
from stenograph.db import Database


def test_stereo_resampling_preserves_duration_and_amplitude():
    rate = 48000
    tone = np.sin(2 * np.pi * 440 * np.arange(rate) / rate) * 16000
    stereo = np.column_stack([tone, tone]).astype("<i2").tobytes()
    result = pcm_to_float(stereo, 2, rate)
    assert result.shape == (16000,)
    assert 0.47 < np.max(result) < 0.51
    assert np.isfinite(result).all()


def test_recover_recording_sidecar_after_restart(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    mid = db.new_meeting("Прерванная запись")
    folder = tmp_path / "audio" / str(mid)
    folder.mkdir(parents=True)
    path = folder / "partial.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(32000))
    path.with_suffix(".json").write_text(json.dumps({"meeting_id": mid, "source": "Микрофон", "offset": 3}))
    count, errors = recover_audio(db, tmp_path)
    assert count == 1 and errors == []
    assert db.rows("SELECT duration FROM chunks")[0]["duration"] == 1
    assert recover_audio(db, tmp_path) == (0, [])
