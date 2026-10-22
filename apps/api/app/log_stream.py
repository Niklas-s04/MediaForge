"""Bounded reads for resumable log streams (offsets are UTF-8 byte offsets)."""
import codecs
import os


def read_log_chunk(path: str, offset: int) -> tuple[str, int, bool]:
    try:
        with open(path, "rb") as source:
            size = os.fstat(source.fileno()).st_size
            offset = min(max(offset, 0), size)
            source.seek(offset)
            data = source.read(65536)
            more = offset + len(data) < size
            # Keep normal log lines together, but never let one long line
            # defeat the memory bound. Preserve incomplete UTF-8 characters.
            if more and b"\n" in data:
                data = data[:data.rfind(b"\n") + 1]
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            chunk = decoder.decode(data, final=not more)
            offset += len(data) - len(decoder.getstate()[0])
            return chunk, offset, offset < size
    except FileNotFoundError:
        return "", offset, False
