import json
import time
from unittest.mock import patch

from tools.chunking import (
    split_into_chunks,
    ChunkReassembler,
    CHUNK_THRESHOLD,
    CHUNK_PAYLOAD_SIZE,
)


class TestSplitIntoChunks:
    def test_small_message_no_chunking(self):
        msg = "hello world"
        result = split_into_chunks(msg)
        assert result == [msg]

    def test_below_threshold(self):
        msg = "x" * (CHUNK_THRESHOLD - 1)
        result = split_into_chunks(msg)
        assert len(result) == 1
        assert result[0] == msg

    def test_large_message_splits_into_chunks(self):
        msg = "x" * (CHUNK_THRESHOLD + 1000)
        chunks = split_into_chunks(msg)

        # First chunk is chunk_start
        start = json.loads(chunks[0])
        assert start["type"] == "chunk_start"
        assert start["total_size"] == len(msg)
        assert start["total_chunks"] > 0

        # Last chunk is chunk_end
        end = json.loads(chunks[-1])
        assert end["type"] == "chunk_end"
        assert end["transfer_id"] == start["transfer_id"]

        # Middle chunks are chunk_data
        for i, chunk_str in enumerate(chunks[1:-1]):
            data = json.loads(chunk_str)
            assert data["type"] == "chunk_data"
            assert data["sequence"] == i
            assert data["transfer_id"] == start["transfer_id"]


class TestChunkReassembler:
    def test_is_chunk_message(self):
        r = ChunkReassembler()
        assert r.is_chunk_message("chunk_start") is True
        assert r.is_chunk_message("chunk_data") is True
        assert r.is_chunk_message("chunk_end") is True
        assert r.is_chunk_message("normal_message") is False

    def test_complete_transfer(self):
        r = ChunkReassembler()

        r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 2,
            "total_size": 10,
        })
        r.handle_chunk_message({
            "type": "chunk_data",
            "transfer_id": "t1",
            "sequence": 0,
            "data": "hello",
        })
        r.handle_chunk_message({
            "type": "chunk_data",
            "transfer_id": "t1",
            "sequence": 1,
            "data": "world",
        })
        result = r.handle_chunk_message({
            "type": "chunk_end",
            "transfer_id": "t1",
        })

        assert result == "helloworld"

    def test_incomplete_transfer(self):
        r = ChunkReassembler()

        r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 3,
            "total_size": 15,
        })
        r.handle_chunk_message({
            "type": "chunk_data",
            "transfer_id": "t1",
            "sequence": 0,
            "data": "hello",
        })
        # Missing sequence 1 and 2
        result = r.handle_chunk_message({
            "type": "chunk_end",
            "transfer_id": "t1",
        })

        assert result is None

    def test_unknown_transfer_chunk_data(self):
        r = ChunkReassembler()
        result = r.handle_chunk_message({
            "type": "chunk_data",
            "transfer_id": "unknown",
            "sequence": 0,
            "data": "hello",
        })
        assert result is None

    def test_unknown_transfer_chunk_end(self):
        r = ChunkReassembler()
        result = r.handle_chunk_message({
            "type": "chunk_end",
            "transfer_id": "unknown",
        })
        assert result is None

    def test_rejects_invalid_bounds_zero_chunks(self):
        r = ChunkReassembler()
        result = r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 0,
            "total_size": 100,
        })
        assert result is None
        # Transfer should not be registered
        assert "t1" not in r._transfers

    def test_rejects_invalid_bounds_negative_size(self):
        r = ChunkReassembler()
        result = r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 5,
            "total_size": -1,
        })
        assert result is None
        assert "t1" not in r._transfers

    def test_rejects_out_of_range_sequence(self):
        r = ChunkReassembler()
        r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 2,
            "total_size": 10,
        })
        result = r.handle_chunk_message({
            "type": "chunk_data",
            "transfer_id": "t1",
            "sequence": 5,  # Out of range
            "data": "bad",
        })
        assert result is None

    def test_cleanup_stale_transfers(self):
        r = ChunkReassembler()
        r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 2,
            "total_size": 10,
        })

        # Manually set started_at to the past
        r._transfers["t1"]["started_at"] = time.time() - 120

        r.cleanup_stale(timeout=60)
        assert "t1" not in r._transfers

    def test_cleanup_keeps_fresh_transfers(self):
        r = ChunkReassembler()
        r.handle_chunk_message({
            "type": "chunk_start",
            "transfer_id": "t1",
            "total_chunks": 2,
            "total_size": 10,
        })
        r.cleanup_stale(timeout=60)
        assert "t1" in r._transfers


class TestRoundtrip:
    def test_split_and_reassemble(self):
        original = "A" * (CHUNK_THRESHOLD + 5000)
        chunks = split_into_chunks(original)

        r = ChunkReassembler()
        result = None
        for chunk_str in chunks:
            msg = json.loads(chunk_str)
            result = r.handle_chunk_message(msg)

        assert result == original

    def test_unknown_msg_type_returns_none(self):
        """handle_chunk_message with unknown type returns None (line 181)."""
        r = ChunkReassembler()
        result = r.handle_chunk_message({
            "type": "unknown_type",
            "transfer_id": "x",
        })
        assert result is None

    def test_split_and_reassemble_large(self):
        # Test with message that produces multiple chunk_data messages
        original = "B" * (CHUNK_PAYLOAD_SIZE * 3 + 500)
        chunks = split_into_chunks(original)

        start = json.loads(chunks[0])
        assert start["total_chunks"] == 4  # ceil(3.5*14000 / 14000)

        r = ChunkReassembler()
        result = None
        for chunk_str in chunks:
            msg = json.loads(chunk_str)
            result = r.handle_chunk_message(msg)

        assert result == original
