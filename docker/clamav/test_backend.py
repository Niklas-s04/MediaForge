"""Subprocess fake implements just the real ClamAV protocol used by tests."""
import asyncio
import os
import struct
import sys


async def serve(reader, writer):
    try:
        command = await reader.readuntil(b"\0")
        if command == b"zPING\0":
            writer.write(b"PONG\0")
        elif command == b"zINSTREAM\0":
            data = bytearray()
            while True:
                size, = struct.unpack(">I", await reader.readexactly(4))
                if not size:
                    break
                data.extend(await reader.readexactly(size))
            if data == b"crash":
                os._exit(1)
            if data == b"slow":
                await asyncio.sleep(.3)
            writer.write(b"stream: Test FOUND\0" if data == b"virus" else b"stream: OK\0")
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    server = await asyncio.start_server(serve, "127.0.0.1", int(sys.argv[1]))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
