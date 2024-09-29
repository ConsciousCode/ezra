import asyncio
import json

class JSONLStream:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *exc):
        await self.close()
    
    async def close(self):
        await self.writer.drain()
        self.writer.close()
    
    def eof(self):
        return self.reader.at_eof()
    
    async def read(self):
        buf = b''
        while c := await self.reader.read(1):
            buf += c
            if c == b'\n':
                break
        if buf:
            return json.loads(buf.decode('utf8'))
        raise ConnectionResetError
    
    async def write(self, data):
        self.writer.write((json.dumps(data) + '\n').encode('utf8'))
        await self.writer.drain()