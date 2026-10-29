"""Bounded local lexical retrieval of controller-verified evidence quotations.

No network fetching or semantic/embedding claims. Source text is untrusted data;
only the caller controls workflow state and human approval.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import threading
from urllib.parse import urlparse


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _atomic(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.evidence-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _terms(value: str) -> set[str]:
    value = value.casefold()
    words = set(re.findall(r'[a-z0-9]+(?:[.%-][a-z0-9]+)*', value))
    for segment in re.findall(r'[\u3400-\u9fff]+', value):
        # Bigrams allow queries without Chinese word segmentation to match phrases.
        words.update(segment[i:i + 2] for i in range(len(segment) - 1))
        if len(segment) == 1:
            words.add(segment)
    return words


class EvidenceStore:
    MAX_SOURCE_BYTES = 2_000_000
    MAX_TOTAL_BYTES = 8_000_000
    MAX_SOURCES = 32
    MAX_CARDS = 512
    MAX_CONTEXT_CHARS = 100_000
    MAX_QUOTE_CHARS = 2000

    def __init__(self, project_dir: Path, run_dir: Path):
        self.project = Path(project_dir).resolve(strict=True)
        candidate = Path(run_dir)
        expected = self.project / '08_evidence' / 'coursework-runs'
        if candidate.parent.resolve() != expected.resolve() or not _inside(candidate.resolve(), self.project):
            raise ValueError('Evidence run must be directly under this project/08_evidence/coursework-runs.')
        self.run = candidate.resolve()
        self.directory = self.run / 'evidence-store'
        self.directory.mkdir(parents=True, exist_ok=True)
        if not _inside(self.directory.resolve(), self.run):
            raise ValueError('Unsafe evidence directory.')
        self.index = self.directory / 'index.json'
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(self.run), threading.RLock())

    def _read(self) -> dict:
        if (not _inside(self.run.resolve(), self.project)
                or not _inside(self.directory.resolve(), self.run)):
            raise ValueError('Evidence run directory moved outside its project/run boundary.')
        if not self.index.exists():
            return {'version': 1, 'project': str(self.project), 'run': str(self.run), 'sources': [], 'evidence': []}
        if self.index.is_symlink() or self.index.stat().st_size > 5_000_000:
            raise ValueError('Unsafe or oversized evidence index.')
        try:
            state = json.loads(self.index.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ValueError('Evidence index cannot be read.') from error
        if (not isinstance(state, dict) or state.get('version') != 1 or state.get('project') != str(self.project)
                or state.get('run') != str(self.run) or not isinstance(state.get('sources'), list)
                or not isinstance(state.get('evidence'), list)
                or len(state['sources']) > self.MAX_SOURCES or len(state['evidence']) > self.MAX_CARDS):
            raise ValueError('Evidence index belongs to another project/run or has an invalid format.')
        source_ids = set()
        for source in state['sources']:
            if (not isinstance(source, dict) or not re.fullmatch(r'S\d{4}', str(source.get('id', '')))
                    or source['id'] in source_ids or not re.fullmatch(r'[0-9a-f]{64}', str(source.get('sha256', '')))
                    or not isinstance(source.get('byte_size'), int) or not 0 < source['byte_size'] <= self.MAX_SOURCE_BYTES):
                raise ValueError('Invalid registered source record.')
            source_ids.add(source['id'])
        card_ids = set()
        for card in state['evidence']:
            if (not isinstance(card, dict) or not re.fullmatch(r'E\d{4}', str(card.get('id', '')))
                    or card['id'] in card_ids or not isinstance(card.get('claim'), str)
                    or not isinstance(card.get('locator'), str)):
                raise ValueError('Invalid registered evidence card.')
            card_ids.add(card['id'])
        return state

    def _save(self, state: dict) -> None:
        _atomic(self.index, json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8'))

    def _project_file(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or len(relative) > 1000:
            raise ValueError('Provide a relative project text path.')
        path = Path(relative)
        if path.is_absolute() or PureWindowsPath(relative).drive or '..' in path.parts or '..' in PureWindowsPath(relative).parts:
            raise ValueError('Source path must remain relative to the current project.')
        try:
            full = (self.project / path).resolve(strict=True)
        except OSError as error:
            raise ValueError('Source file does not exist.') from error
        if not _inside(full, self.project) or not full.is_file() or full.suffix.lower() not in {'.txt', '.md'}:
            raise ValueError('Only UTF-8 .txt/.md files inside the current project are supported.')
        return full

    def _body(self, source: dict) -> str:
        relative = source.get('body_path', '')
        if not isinstance(relative, str) or not re.fullmatch(r'evidence-store/S\d{4}\.txt', relative):
            raise ValueError('Unsafe registered source body path.')
        body_path = self.run / relative
        if not _inside(body_path.resolve(), self.directory.resolve()) or body_path.is_symlink():
            raise ValueError('Unsafe registered source body.')
        try:
            if body_path.stat().st_size > self.MAX_SOURCE_BYTES:
                raise ValueError('Source body exceeds the size limit.')
            data = body_path.read_bytes()
            if _sha(data) != source.get('sha256'):
                raise ValueError('Registered source body changed; import a new source and rerun evidence extraction.')
            return data.decode('utf-8')
        except (OSError, UnicodeError) as error:
            raise ValueError('Registered source body is missing or not UTF-8.') from error

    def _validate(self, state: dict) -> None:
        for source in state['sources']:
            self._body(source)
            if source.get('original_path'):
                original = self._project_file(source['original_path'])
                if (str(original) != source.get('original_resolved_path')
                        or original.stat().st_size > self.MAX_SOURCE_BYTES
                        or _sha(original.read_bytes()) != source.get('original_sha256')):
                    raise ValueError('Original source changed; existing evidence and checks are invalid.')
        sources = {source['id']: source for source in state['sources']}
        for card in state['evidence']:
            source = sources.get(card.get('source_id'))
            if (not source or card.get('source_sha256') != source['sha256']
                    or not isinstance(card.get('text'), str) or card['text'] not in self._body(source)):
                raise ValueError('Evidence card does not match its registered source version.')

    def validate(self) -> None:
        with self.lock:
            self._validate(self._read())

    def ingest(self, source: dict) -> dict:
        if not isinstance(source, dict) or bool(source.get('path')) == bool(source.get('text')):
            raise ValueError('Provide exactly one local path or pasted text body.')
        with self.lock:
            state = self._read()
            self._validate(state)
            if len(state['sources']) >= self.MAX_SOURCES:
                raise ValueError('Source limit reached; split the assignment into smaller runs.')
            record = {}
            if source.get('path'):
                original = self._project_file(source['path'])
                if original.stat().st_size > self.MAX_SOURCE_BYTES:
                    raise ValueError('Source exceeds 2 MB; provide a scoped text excerpt.')
                data = original.read_bytes()
                try:
                    body = data.decode('utf-8-sig')
                except UnicodeError as error:
                    raise ValueError('Source must be UTF-8 text; extract PDF/Word content separately.') from error
                record.update(original_path=source['path'], original_resolved_path=str(original), original_sha256=_sha(data))
            else:
                body = source['text']
                if not isinstance(body, str):
                    raise ValueError('Pasted source text must be a string.')
            if not body.strip() or '\x00' in body:
                raise ValueError('Source must contain nonempty readable text.')
            data = body.encode('utf-8')
            if len(data) > self.MAX_SOURCE_BYTES or len(data) + sum(s['byte_size'] for s in state['sources']) > self.MAX_TOTAL_BYTES:
                raise ValueError('Source exceeds the bounded local evidence store; import a scoped excerpt.')
            url = source.get('url', '')
            title = source.get('title') or source.get('path') or '粘贴资料'
            locator = source.get('locator', '')
            if any(not isinstance(value, str) or len(value) > maximum for value, maximum in [(url, 2000), (title, 300), (locator, 1000)]):
                raise ValueError('Source metadata is invalid or too long.')
            if url and urlparse(url).scheme not in {'http', 'https'}:
                raise ValueError('Attribution URL must use http or https; no remote fetching is performed.')
            identifier = f'S{len(state["sources"]) + 1:04d}'
            record.update(id=identifier, title=title, url=url, locator=locator,
                          access_scope='local_text' if source.get('path') else 'pasted_excerpt',
                          remote_fetched=False, sha256=_sha(data), byte_size=len(data),
                          body_path=f'evidence-store/{identifier}.txt')
            _atomic(self.run / record['body_path'], data)
            state['sources'].append(record)
            self._save(state)
            return dict(record)

    def sources(self) -> list:
        with self.lock:
            state = self._read()
            self._validate(state)
            return state['sources']

    def evidence(self) -> list:
        with self.lock:
            state = self._read()
            self._validate(state)
            return state['evidence']

    def raw_context(self) -> list:
        with self.lock:
            state = self._read()
            self._validate(state)
            result = []
            total = 0
            for source in state['sources']:
                body = self._body(source)
                total += len(body)
                if total > self.MAX_CONTEXT_CHARS:
                    raise ValueError(f'Raw source context exceeds {self.MAX_CONTEXT_CHARS} characters; nothing was silently truncated. Create a scoped excerpt run.')
                result.append({'source_id': source['id'], 'title': source['title'], 'text': body,
                               'locator': f'L1-L{body.count(chr(10)) + 1}', 'sha256': source['sha256']})
            return result

    def extract(self, source_id: str, quote: str, locator: str, claim: str) -> dict:
        with self.lock:
            state = self._read()
            self._validate(state)
            source = next((item for item in state['sources'] if item['id'] == source_id), None)
            if not source:
                raise ValueError('Unknown source ID.')
            if not isinstance(quote, str) or len(quote.strip()) < 8 or len(quote) > self.MAX_QUOTE_CHARS:
                raise ValueError('Extract a meaningful exact quotation of 8–2000 characters.')
            if any(not isinstance(value, str) or not value.strip() or len(value) > 2000 for value in [locator, claim]):
                raise ValueError('Provide a bounded locator and the claim supported by this quotation.')
            body = self._body(source)
            start = body.find(quote)
            if start < 0:
                raise ValueError('Quotation is not an exact substring of the registered source.')
            if quote.strip() == body.strip():
                raise ValueError('Extract a focused passage, not the whole source body.')
            for previous in state['evidence']:
                if previous['source_id'] == source_id and previous['text'] == quote and previous['claim'] == claim:
                    return previous
            if len(state['evidence']) >= self.MAX_CARDS:
                raise ValueError('Evidence card limit reached.')
            start_line = body.count('\n', 0, start) + 1
            end_line = start_line + quote.count('\n')
            card = {'id': f'E{len(state["evidence"]) + 1:04d}', 'source_id': source_id, 'text': quote,
                    'locator': f'L{start_line}-L{end_line}; chars {start + 1}-{start + len(quote)}',
                    'attributed_locator': locator, 'claim': claim, 'source_sha256': source['sha256']}
            state['evidence'].append(card)
            self._save(state)
            return dict(card)

    def search(self, query: str, limit: int = 8) -> list:
        if not isinstance(query, str) or len(query) > 2000 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 32:
            raise ValueError('Provide a query up to 2000 characters and a limit from 1 to 32.')
        tokens = _terms(query)
        cards = self.evidence()
        if not tokens:
            return []
        ranked = []
        for card in cards:
            overlap = tokens & _terms(card['text'] + ' ' + card['claim'])
            if overlap:
                ranked.append((len(overlap) / len(tokens), card))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]['id']))
        return [dict(card, score=round(score, 4), retrieval_method='lexical: words and Chinese bigrams') for score, card in ranked[:limit]]

    def packet(self, evidence_ids: list | None = None) -> dict:
        with self.lock:
            state = self._read()
            self._validate(state)
            known = {card['id']: card for card in state['evidence']}
            if evidence_ids is not None and (not isinstance(evidence_ids, list) or len(evidence_ids) > self.MAX_CARDS
                    or any(not isinstance(identifier, str) or identifier not in known for identifier in evidence_ids)):
                raise ValueError('Unknown or invalid evidence IDs.')
            cards = list(known.values()) if evidence_ids is None else [known[identifier] for identifier in dict.fromkeys(evidence_ids)]
            used = {card['source_id'] for card in cards}
            return {'evidence': cards, 'sources': [source for source in state['sources'] if source['id'] in used],
                    'retrieval_method': 'lexical: words and Chinese bigrams; exact quotation verified, claim support requires review'}
