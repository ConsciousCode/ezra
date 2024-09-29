import asyncio
import traceback as tb
import signal

from util import JSONLStream

class EzraServer:
    def __init__(self, path):
        self.path = path
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *exc):
        await self.close()
    
    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        del self.server
    
    async def handle_client(self, r, w):
        async with JSONLStream(r, w) as stream:
            try:
                while not stream.eof():
                    print("Before")
                    data = await stream.read()
                    print("data", data)
                    match data:
                        case {"type": "close"}:
                            break
                        
                        case {"type": "text", "message": message}:
                            await stream.write({
                                "type": "text",
                                "message": message
                            })
                        
                        case _:
                            await stream.write({
                                "type": "error",
                                "message": "Unknown request type"
                            })
                print("eof")
            except ConnectionResetError:
                pass
            except Exception:
                tb.print_exc()
                await stream.write({
                    "type": "uncaught",
                    "traceback": tb.format_exc()
                })
                raise
    
    async def start(self):
        self.server = await asyncio.start_unix_server(
            self.handle_client,
            self.path
        )
        await self.server.serve_forever()

async def main():
    async with EzraServer("./ezra.sock") as server:
        await server.start()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass