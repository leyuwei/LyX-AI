"""Local conversation archive; credentials and native writeback targets never enter it."""
from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
import json
import sqlite3
import uuid


def timestamp():
    return datetime.now().astimezone().isoformat(timespec='microseconds')


class HistoryStore:
    def __init__(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / 'history.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        # Connections live only for a transaction; never retain a desktop-wide lock.
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, session):
        raw = json.dumps(session, ensure_ascii=False, allow_nan=False)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, updated=excluded.updated, payload=excluded.payload',
                       (session['id'], session['title'], session['created'], timestamp(), raw))

    def new(self, **fields):
        now = timestamp()
        return dict(id=uuid.uuid4().hex, title=' '.join(fields.get('target', '').split())[:100] or 'LyX AI', created=now, turns=[], messages=[], **fields)

    def list(self, search='', limit=100):
        pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        with self.connect() as db:
            return db.execute('SELECT id, title, updated FROM sessions WHERE payload LIKE ? ESCAPE ? ORDER BY updated DESC, id LIMIT ?', (pattern, '\\', limit)).fetchall()

    def get(self, session_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM sessions WHERE id=?', (session_id,)).fetchone()
        if not row:
            return None
        session = json.loads(row[0])
        for turn in session['turns']:
            if turn['status'] == 'pending':
                turn['status'] = 'interrupted'
        return session

    def delete(self, session_id):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (session_id,))


def transcript(session):
    profile = session.get('profile', {})
    parts = [session['title'], profile.get('name', '') + ' · ' + profile.get('model', '')]
    for turn in session['turns']:
        model = turn.get('profile', profile).get('model', '')
        parts += ['────────────', turn['time'] + ' · ' + turn['status'] + ' · ' + model, 'USER\n' + turn['question']]
        if turn.get('reasoning'):
            parts.append('REASONING\n' + turn['reasoning'])
        parts.append('ASSISTANT\n' + turn.get('answer', ''))
        if turn.get('error'):
            parts.append('ERROR\n' + turn['error'])
    return '\n\n'.join(parts)
