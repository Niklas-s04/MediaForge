"""Offline CI check against the real clamd binary; never used by the app.

A temporary configuration permits a synthetic signature database. The shipped
configuration still accepts official databases only. No update/download needed.
"""
import asyncio
from pathlib import Path
import struct
import sys
import tempfile

sys.path.insert(0, "/opt/clamav")
from gateway import Engine, Gateway


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        payload = b"MEDIAFORGE-SCANNER-TEST"
        (root / "test.ndb").write_text("MediaForge.Test:0:*:" + payload.hex() + "\n")
        config = Path("/etc/clamav/clamd.conf").read_text()
        config = config.replace("OfficialDatabaseOnly yes", "OfficialDatabaseOnly no")
        config = config.replace("DatabaseDirectory /var/lib/clamav", f"DatabaseDirectory {root}")
        config = config.replace("TemporaryDirectory /scratch/clamav", f"TemporaryDirectory {root}")
        config_path = root / "clamd.conf"
        config_path.write_text(config)
        engine = Engine(["clamd", "--config-file=" + str(config_path)], idle_seconds=1)
        gateway = Gateway(engine, lambda: True, request_seconds=30)
        server = await asyncio.start_server(gateway.accept, "127.0.0.1", 3310)
        async def request(data):
            reader, writer = await asyncio.open_connection("127.0.0.1", 3310)
            try:
                writer.write(data)
                await writer.drain()
                return await asyncio.wait_for(reader.readuntil(b"\0"), 30)
            finally:
                writer.close()
                await writer.wait_closed()
        async def scan(data):
            return await request(b"zINSTREAM\0" + struct.pack(">I", len(data)) + data + b"\0" * 4)
        try:
            assert await request(b"zPING\0") == b"PONG\0"
            assert engine.process is None
            assert await scan(b"clean") == b"stream: OK\0"
            assert b"FOUND" in await scan(payload)
            process = engine.process
            await asyncio.wait_for(process.wait(), 15)
            assert await request(b"zPING\0") == b"PONG\0"
            assert await scan(b"clean again") == b"stream: OK\0"
            print("PASS: real clamd cold start, clean/infected scans, idle exit and restart")
        finally:
            server.close()
            await server.wait_closed()
            await gateway.close()


if __name__ == "__main__":
    asyncio.run(main())
