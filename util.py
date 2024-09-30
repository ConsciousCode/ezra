from typing import Any, Protocol
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

class ToString(Protocol):
    def __str__(self) -> str: ...

def typename(obj):
    return type(obj).__name__

def to_value(value: str) -> Any:
    match value.lower():
        case 'false'|'f'|'no'|'n': return False
        case 'true'|'t'|'yes'|'y': return True
        case 'null'|'none': return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value

def q_values(value: list[str]) -> Any:
    '''Parse query parameters as values.'''
    if value:
        if len(value) > 1:
            return list(map(to_value, value))
        return to_value(value[0])
    raise ValueError("Empty value")