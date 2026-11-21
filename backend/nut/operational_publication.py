"""Schema-2 publication and bounded framing primitives for operational capture."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Callable

from continuous_capture import (
    AtomicSamplePublisher, ID_RE, MAX_SAMPLE_FILE_BYTES,
    _check_private_dir, _same_directory_identity,
)
from continuous_protocol import (
    MAX_LINE_BYTES,
    MAX_SAFE_INTEGER,
    OperationalEnd,
    OperationalSample,
    ProtocolError,
    parse_line_v2,
)


OPERATIONAL_TERMINAL_REASONS = frozenset({
    "cancelled", "device_lost", "session_lost", "guard_error", "output_error",
    "protocol_error", "capture_limit", "deadline", "child_failed", "child_unreaped",
    "io_error", "cleanup_unresolved",
})
_SESSION_RE = re.compile(r"^[0-9a-f]{32}$", re.ASCII)
MAX_INPUT_CHUNK_BYTES = 65_536
MAX_PENDING_BYTES = MAX_LINE_BYTES - 1


def _timestamp(value: object) -> bool:
    return type(value) is int and 0 <= value <= MAX_SAFE_INTEGER


class OperationalPublicationAdmissionError(OSError):
    """Fixed admission failure, retaining an owner only after ambiguous close."""

    def __init__(self, publisher: AtomicOperationalPublisher | None) -> None:
        self.publisher = publisher
        super().__init__("publication_admission_failed")


class AtomicOperationalPublisher(AtomicSamplePublisher):
    """Publish schema-2 envelopes through the base class's guarded atomic writer."""

    def __init__(self, directory, source_id: str, session_id: str) -> None:
        if not isinstance(source_id, str) or ID_RE.fullmatch(source_id) is None:
            raise ValueError("invalid_source_id")
        if not isinstance(session_id, str) or _SESSION_RE.fullmatch(session_id) is None:
            raise ValueError("invalid_session_id")
        self.directory = Path(directory)
        self.parent_directory = self.directory.parent
        self.source_id, self.session_id = source_id, session_id
        self.parent_fd = self.dir_fd = -1
        self._close_failed = False
        try:
            _check_private_dir(self.directory)
            self.parent_fd = os.open(self.parent_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.dir_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            opened = os.fstat(self.dir_fd)
            named = os.stat(self.directory, follow_symlinks=False)
            parent_opened = os.fstat(self.parent_fd)
            parent_named = os.stat(self.parent_directory, follow_symlinks=False)
            if (not _same_directory_identity(opened, named)
                    or not _same_directory_identity(parent_opened, parent_named)):
                raise OSError("unsafe_directory")
        except Exception:
            try:
                self.close()
            except Exception:
                raise OperationalPublicationAdmissionError(self) from None
            raise OperationalPublicationAdmissionError(None) from None

    def close(self) -> None:
        # Detach each owned number before close: an interrupted/failed close may
        # already have consumed it. Retrying could close another thread's fd.
        if self._close_failed:
            raise OSError("publication_cleanup_unresolved")
        failed = False
        for attribute in ("dir_fd", "parent_fd"):
            descriptor = getattr(self, attribute)
            setattr(self, attribute, -1)
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except Exception:
                    failed = True
        if failed:
            self._close_failed = True
            raise OSError("publication_cleanup_unresolved")

    def publish(
        self,
        *,
        state: str,
        started_at_unix_ms: int,
        terminal_reason: str | None,
        sample: dict[str, object] | None,
        published_at_unix_ms: int,
    ) -> None:
        if state not in ("active", "stopped", "failed"):
            raise ValueError("invalid_state")
        if not _timestamp(started_at_unix_ms) or not _timestamp(published_at_unix_ms):
            raise ValueError("invalid_timestamp")
        if state == "active":
            if terminal_reason is not None:
                raise ValueError("invalid_terminal_reason")
        elif state == "stopped":
            if terminal_reason != "cancelled":
                raise ValueError("invalid_terminal_reason")
        elif (type(terminal_reason) is not str
              or terminal_reason not in OPERATIONAL_TERMINAL_REASONS):
            raise ValueError("invalid_terminal_reason")
        if sample is not None:
            if type(sample) is not dict:
                raise ValueError("invalid_sample")
            try:
                line = (json.dumps(sample, ensure_ascii=True, separators=(",", ":"),
                                    allow_nan=False) + "\n").encode("ascii")
                record = parse_line_v2(line)
            except (ProtocolError, TypeError, ValueError, UnicodeError):
                raise ValueError("invalid_sample") from None
            if type(record) is not OperationalSample:
                raise ValueError("invalid_sample")
        self._verify_directories()
        payload = {
            "schema_version": 2,
            "protocol": "ups-monitor.continuous.v2",
            "source_id": self.source_id,
            "session_id": self.session_id,
            "state": state,
            "started_at_unix_ms": started_at_unix_ms,
            "published_at_unix_ms": published_at_unix_ms,
            "terminal_reason": terminal_reason,
            "sample": sample,
        }
        data = (json.dumps(payload, ensure_ascii=True, separators=(",", ":"),
                           allow_nan=False) + "\n").encode("ascii")
        if len(data) > MAX_SAMPLE_FILE_BYTES:
            raise OSError("capture_limit")
        self._publish_bytes(data)


class OperationalFramer:
    """Parse bounded schema-2 NDJSON chunks without retaining record history."""

    def __init__(self, on_record: Callable[[OperationalSample | OperationalEnd], bool]) -> None:
        if not callable(on_record):
            raise TypeError("invalid_callback")
        self._on_record = on_record
        self._pending = bytearray()
        self._failed = False
        self._eof = False

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)

    @property
    def failed(self) -> bool:
        return self._failed

    @property
    def eof(self) -> bool:
        return self._eof

    def _fail(self, code: str) -> None:
        self._failed = True
        self._pending.clear()
        raise ProtocolError(code)

    def accept(self, chunk: bytes) -> bool:
        if type(chunk) is not bytes:
            self._fail("invalid_chunk")
        if self._failed:
            raise ProtocolError("framer_failed")
        if chunk == b"" and self._eof:
            return False
        if self._eof:
            self._fail("input_after_eof")
        if len(chunk) > MAX_INPUT_CHUNK_BYTES:
            self._fail("chunk_limit")
        if chunk == b"":
            self._eof = True
            if self._pending:
                self._fail("missing_newline")
            return False

        accepted_sample = False
        offset = 0
        while offset < len(chunk):
            newline = chunk.find(b"\n", offset)
            stop = len(chunk) if newline < 0 else newline + 1
            piece_length = stop - offset
            limit = MAX_PENDING_BYTES if newline < 0 else MAX_LINE_BYTES
            if len(self._pending) + piece_length > limit:
                self._fail("invalid_line_framing")
            self._pending.extend(chunk[offset:stop])
            if newline < 0:
                if len(self._pending) > MAX_PENDING_BYTES:
                    self._fail("invalid_line_framing")
                break
            line = bytes(self._pending)
            self._pending.clear()
            try:
                record = parse_line_v2(line)
            except ProtocolError:
                self._failed = True
                raise
            try:
                callback_result = self._on_record(record)
            except BaseException:
                self._failed = True
                self._pending.clear()
                raise
            if type(callback_result) is not bool:
                self._fail("consumer_error")
            if type(record) is OperationalSample and callback_result:
                accepted_sample = True
            offset = stop
        return accepted_sample
