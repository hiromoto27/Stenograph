"""Delete only registered audio after its persisted, post-report deadline."""
from pathlib import Path

from .db import now_iso


def cleanup_audio(db, root, protected_meetings=(), at=None):
    root = Path(root).resolve()
    deleted, failures = 0, []
    rows = db.rows("""SELECT * FROM chunks WHERE state='done' AND purged_at IS NULL
        AND delete_after IS NOT NULL AND julianday(delete_after)<=julianday(?)""", (at or now_iso(),))
    for row in rows:
        if row['meeting_id'] in protected_meetings:
            continue
        try:
            path = Path(row['path'])
            expected = root / 'audio' / str(row['meeting_id'])
            # Reject paths escaping through '..', symlinks, another meeting or another file type.
            if path.is_symlink() or path.resolve().parent != expected or path.suffix.lower() != '.wav':
                raise ValueError('Путь аудио вне каталога этой встречи; автоматическое удаление пропущено.')
            path.unlink(missing_ok=True)
            db.execute('UPDATE chunks SET purged_at=?,purge_error=NULL WHERE id=?', (at or now_iso(), row['id']))
            deleted += 1
        except (OSError, ValueError) as exc:
            db.execute('UPDATE chunks SET purge_error=? WHERE id=?', (str(exc), row['id']))
            failures.append((row['id'], str(exc)))
    return deleted, failures
