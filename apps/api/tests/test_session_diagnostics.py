import asyncio
import base64
import json
import logging

from fastapi import FastAPI, HTTPException

from apps.api.app.diagnostics import install_diagnostics


def test_diagnostics_are_request_local_even_before_job_creation():
    app = FastAPI()
    install_diagnostics(app)

    @app.get('/api/failure/{device}')
    async def failure(device: str):
        logging.getLogger(__name__).warning('Upload from %s', device)
        await asyncio.sleep(0.01)
        try:
            raise OSError(f'{device}: temporary storage full')
        except OSError as exc:
            raise HTTPException(400, 'There was an error parsing the body') from exc

    @app.get('/api/ok')
    async def ok():
        return {'ok': True}

    @app.get('/api/crash')
    async def crash():
        raise RuntimeError('worker unavailable')

    async def request(path):
        messages = []

        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message):
            messages.append(message)

        await app({
            'type': 'http', 'method': 'GET', 'path': path, 'raw_path': path.encode(),
            'query_string': b'', 'headers': [], 'scheme': 'http',
            'server': ('test', 80), 'client': ('127.0.0.1', 1234),
            'http_version': '1.1',
        }, receive, send)
        start = next(message for message in messages if message['type'] == 'http.response.start')
        return start['status'], dict(start['headers'])

    async def check():
        first, second = await asyncio.gather(request('/api/failure/device-A'), request('/api/failure/device-B'))
        for own, other, (status, headers) in [('device-A', 'device-B', first), ('device-B', 'device-A', second)]:
            assert status == 400
            detail = json.loads(base64.b64decode(headers[b'x-mediaforge-diagnostic']))
            assert own in detail and other not in detail
            assert 'OSError' in detail and 'temporary storage full' in detail
            assert headers[b'cache-control'] == b'no-store'
        assert b'x-mediaforge-diagnostic' not in (await request('/api/ok'))[1]
        status, headers = await request('/api/crash')
        assert status == 500
        assert 'worker unavailable' in json.loads(base64.b64decode(headers[b'x-mediaforge-diagnostic']))

    asyncio.run(check())
