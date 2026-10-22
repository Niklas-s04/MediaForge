"""Bounded ClamAV TCP gateway. Only an INSTREAM request starts the engine.

The supervisor owns freshclam and clamd; neither process is daemonized. Health
means the updater is alive and signature files are present/recent, not that a
resident scan engine is consuming memory. clamd validates databases on startup.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import sys
import time


def database_ready(directory: Path, max_age: float) -> bool:
    try:
        files = []
        for name in ("main", "daily", "bytecode"):
            candidates = [directory / (name + suffix) for suffix in (".cvd", ".cld")]
            files.append(next(p for p in candidates if p.is_file() and p.stat().st_size > 0))
        return time.time() - files[1].stat().st_mtime <= max_age
    except (OSError, StopIteration):
        return False


async def terminate(process):
    if process is None or process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 10)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


def clean_scratch(directory: Path):
    # This private directory belongs exclusively to clamd, which must be stopped.
    for entry in directory.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()


class Engine:
    def __init__(self, command, port=3311, startup_seconds=180, idle_seconds=60, scratch=None):
        self.command = command
        self.port = port
        self.startup_seconds = startup_seconds
        self.idle_seconds = idle_seconds
        self.scratch = scratch
        self.process = None

    async def start(self):
        if self.process is not None and self.process.returncode is None:
            return
        self.process = await asyncio.create_subprocess_exec(*self.command)
        try:
            async with asyncio.timeout(self.startup_seconds):
                while self.process.returncode is None:
                    writer = None
                    try:
                        async with asyncio.timeout(1):
                            reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
                            writer.write(b"zPING\0")
                            await writer.drain()
                            if await reader.readuntil(b"\0") == b"PONG\0":
                                return
                    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                        pass
                    finally:
                        if writer:
                            writer.close()
                    await asyncio.sleep(.05)
                raise RuntimeError("clamd exited before readiness")
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        await terminate(self.process)
        if self.scratch:
            clean_scratch(self.scratch)


class Gateway:
    def __init__(self, engine, ready, request_seconds=900, max_bytes=2147483648, max_connections=8):
        self.engine = engine
        self.ready = ready
        self.request_seconds = request_seconds
        self.max_bytes = max_bytes
        self.max_connections = max_connections
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.idle_task = None
        self.closed = False

    def accept(self, reader, writer):
        if self.closed or len(self.tasks) >= self.max_connections:
            writer.close()
            return
        task = asyncio.create_task(self.handle(reader, writer))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def idle_stop(self):
        await asyncio.sleep(self.engine.idle_seconds)
        async with self.lock:
            await self.engine.stop()

    async def scan(self, reader, writer):
        async with self.lock:
            if not self.ready():
                raise RuntimeError("signatures or updater unavailable")
            if self.idle_task:
                self.idle_task.cancel()
                await asyncio.gather(self.idle_task, return_exceptions=True)
            backend = None
            try:
                await self.engine.start()
                upstream, backend = await asyncio.open_connection("127.0.0.1", self.engine.port, limit=65536)
                backend.write(b"zINSTREAM\0")
                total = 0
                while True:
                    header = await reader.readexactly(4)
                    size, = struct.unpack(">I", header)
                    total += size
                    if total > self.max_bytes:
                        raise ValueError("stream limit exceeded")
                    backend.write(header)
                    if size == 0:
                        break
                    while size:
                        chunk = await reader.readexactly(min(size, 65536))
                        size -= len(chunk)
                        backend.write(chunk)
                        await backend.drain()
                await backend.drain()
                response = await upstream.readuntil(b"\0")
                if not self.ready():
                    raise RuntimeError("updater unavailable")
                writer.write(response)
                await writer.drain()
            except BaseException:
                # A partial stream must not leave background work or temp files.
                await self.engine.stop()
                raise
            finally:
                if backend:
                    backend.close()
                self.idle_task = asyncio.create_task(self.idle_stop())

    async def handle(self, reader, writer):
        try:
            async with asyncio.timeout(self.request_seconds):
                # Read bytewise only for the small command, preserving coalesced data.
                command = bytearray()
                async with asyncio.timeout(10):
                    while len(command) < 16:
                        command.extend(await reader.readexactly(1))
                        if command[-1] == 0:
                            break
                if command == b"zPING\0" and self.ready():
                    writer.write(b"PONG\0")
                    await writer.drain()
                elif command == b"zINSTREAM\0":
                    await self.scan(reader, writer)
                else:
                    raise ValueError("unsupported command or unhealthy service")
        except (OSError, ValueError, RuntimeError, asyncio.TimeoutError,
                asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                writer.write(b"stream: scanner unavailable ERROR\0")
                async with asyncio.timeout(1):
                    await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                async with asyncio.timeout(1):
                    await writer.wait_closed()

    async def close(self):
        self.closed = True
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.idle_task:
            self.idle_task.cancel()
            await asyncio.gather(self.idle_task, return_exceptions=True)
        await self.engine.stop()


def env_int(name, default, minimum=1, maximum=2147483648):
    value = int(os.environ.get(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} out of range")
    return value


async def main():
    scratch = Path("/scratch/clamav")
    clean_scratch(scratch)
    engine = Engine(["clamd", "--foreground", "--config-file=/etc/clamav/clamd.conf"],
                    idle_seconds=env_int("CLAMAV_IDLE_SECONDS", 60),
                    startup_seconds=env_int("CLAMAV_STARTUP_SECONDS", 180), scratch=scratch)
    # Reject invalid settings before creating any child processes.
    max_age = env_int("CLAMAV_DATABASE_MAX_AGE_SECONDS", 604800)
    request_seconds = env_int("CLAMAV_REQUEST_SECONDS", 900)
    max_bytes = env_int("CLAMAV_MAX_BYTES", 2147483648)
    max_connections = env_int("CLAMAV_MAX_CONNECTIONS", 8, maximum=64)
    updater = await asyncio.create_subprocess_exec(
        "freshclam", "--daemon", "--foreground", "--stdout", "--user=clamav",
        "--config-file=/etc/clamav/freshclam.conf",
        f"--checks={env_int('FRESHCLAM_CHECKS', 12, maximum=50)}")
    service = Gateway(engine, lambda: updater.returncode is None and
                      database_ready(Path("/var/lib/clamav"), max_age),
                      request_seconds=request_seconds, max_bytes=max_bytes,
                      max_connections=max_connections)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    server = None
    waiters = []
    try:
        server = await asyncio.start_server(service.accept, "0.0.0.0", 3310, limit=65536, backlog=16)
        waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(updater.wait())]
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if server:
            server.close()
            await server.wait_closed()
        for task in waiters:
            task.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        await service.close()
        await terminate(updater)
    if not stop.is_set():
        raise RuntimeError("freshclam exited; refusing to serve stale signatures")


def healthcheck():
    with socket.create_connection(("127.0.0.1", 3310), timeout=2) as client:
        client.sendall(b"zPING\0")
        return 0 if client.makefile("rb").read(5) == b"PONG\0" else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--healthcheck"]:
        try:
            sys.exit(healthcheck())
        except OSError:
            sys.exit(1)
    asyncio.run(main())
