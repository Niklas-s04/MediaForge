"""Real TCP and subprocess tests; no ClamAV installation required."""
import asyncio
import importlib.util
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("gateway", HERE / "gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_configuration_does_not_spawn_updater(self):
        with patch.object(gateway, "clean_scratch"), \
                patch.dict(gateway.os.environ, {"CLAMAV_REQUEST_SECONDS": "invalid"}), \
                patch.object(gateway.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with self.assertRaises(ValueError):
                await gateway.main()
            spawn.assert_not_called()

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("main.cvd", "daily.cld", "bytecode.cvd"):
            (self.root / name).write_bytes(b"database")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.engine = gateway.Engine(
            command=[sys.executable, str(HERE / "test_backend.py"), str(port)],
            port=port, startup_seconds=3, idle_seconds=.15,
        )
        self.service = gateway.Gateway(self.engine, lambda: gateway.database_ready(self.root, 604800),
                                       request_seconds=4, max_bytes=100, max_connections=4)
        self.server = await asyncio.start_server(self.service.accept, "127.0.0.1", 0, limit=65536)
        self.address = self.server.sockets[0].getsockname()

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.service.close()
        self.temp.cleanup()

    async def request(self, payload):
        reader, writer = await asyncio.open_connection(*self.address)
        try:
            writer.write(payload)
            await writer.drain()
            return await asyncio.wait_for(reader.readuntil(b"\0"), 5)
        finally:
            writer.close()
            await writer.wait_closed()

    def stream(self, data):
        return b"zINSTREAM\0" + struct.pack(">I", len(data)) + data + b"\0\0\0\0"

    async def test_ping_leaves_engine_stopped_and_missing_database_fails_closed(self):
        self.assertEqual(await self.request(b"zPING\0"), b"PONG\0")
        self.assertIsNone(self.engine.process)
        (self.root / "daily.cld").unlink()
        self.assertIn(b"ERROR", await self.request(b"zPING\0"))
        self.assertIn(b"ERROR", await self.request(self.stream(b"clean")))
        self.assertIsNone(self.engine.process)

    async def test_cold_scan_coalesced_frames_and_idle_exit(self):
        self.assertEqual(await self.request(self.stream(b"clean")), b"stream: OK\0")
        process = self.engine.process
        self.assertIsNone(process.returncode)
        await asyncio.sleep(.35)
        self.assertIsNotNone(process.returncode)
        self.assertEqual(await self.request(self.stream(b"virus")), b"stream: Test FOUND\0")
        self.assertNotEqual(self.engine.process.pid, process.pid)

    async def test_concurrent_scans_serialize_and_ping_stays_responsive(self):
        scans = [asyncio.create_task(self.request(self.stream(b"slow"))) for _ in range(2)]
        await asyncio.sleep(.1)
        self.assertEqual(await asyncio.wait_for(self.request(b"zPING\0"), .5), b"PONG\0")
        self.assertEqual(await asyncio.gather(*scans), [b"stream: OK\0"] * 2)

    async def test_limits_malformed_commands_and_broken_backend_fail_closed(self):
        self.assertIn(b"ERROR", await self.request(b"zSHUTDOWN\0"))
        self.assertIn(b"ERROR", await self.request(self.stream(b"x" * 101)))
        self.assertIn(b"ERROR", await self.request(self.stream(b"crash")))
        self.assertEqual(await self.request(self.stream(b"clean")), b"stream: OK\0")

    async def test_fragmented_protocol_and_shutdown_reaps_engine(self):
        reader, writer = await asyncio.open_connection(*self.address)
        for byte in self.stream(b"clean"):
            writer.write(bytes([byte]))
            await writer.drain()
        self.assertEqual(await reader.readuntil(b"\0"), b"stream: OK\0")
        writer.close()
        await writer.wait_closed()
        process = self.engine.process
        await self.service.close()
        self.assertIsNotNone(process.returncode)

    async def test_request_timeout_stops_engine_and_allows_next_scan(self):
        self.service.request_seconds = .4
        reader, writer = await asyncio.open_connection(*self.address)
        writer.write(b"zINSTREAM\0" + struct.pack(">I", 10) + b"partial")
        await writer.drain()
        self.assertIn(b"ERROR", await asyncio.wait_for(reader.readuntil(b"\0"), 3))
        writer.close()
        await writer.wait_closed()
        self.assertIsNotNone(self.engine.process.returncode)
        self.service.request_seconds = 4
        self.assertEqual(await self.request(self.stream(b"clean")), b"stream: OK\0")

    async def test_stale_database_and_dead_updater_reject_scans(self):
        import os
        os.utime(self.root / "daily.cld", (0, 0))
        self.assertIn(b"ERROR", await self.request(self.stream(b"clean")))
        self.assertIsNone(self.engine.process)
        self.service.ready = lambda: False
        self.assertIn(b"ERROR", await self.request(b"zPING\0"))

    async def test_private_engine_scratch_cleaned_on_exit(self):
        scratch = self.root / "scratch"
        (scratch / "old").mkdir(parents=True)
        (scratch / "old" / "partial").write_bytes(b"old")
        self.engine.scratch = scratch
        self.assertEqual(await self.request(self.stream(b"clean")), b"stream: OK\0")
        await self.engine.stop()
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertTrue((self.root / "daily.cld").exists())


if __name__ == "__main__":
    unittest.main()
