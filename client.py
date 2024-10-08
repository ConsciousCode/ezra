'''
Connect to and interact with unix socket echo server
'''

import asyncio
import json

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from util import JSONLStream

style = Style.from_dict({
    'user': 'green',
    'ezra': 'yellow',
    'error': 'red',
    'uncaught': 'red',
})

def fprint(*args):
    print_formatted_text(FormattedText(
        ("", a) if isinstance(a, str) else a for a in args
    ), style=style)

class EzraClient:
    def __init__(self, path):
        self.path = path
    
    async def input(self, stream: JSONLStream):
        session = PromptSession()
        with patch_stdout():
            while True:
                data = await session.prompt_async(FormattedText([
                    ("", "<"),
                    ("class:user", "user"),
                    ("", "> ")
                ]), style=style)
                await stream.write({
                    "type": "text",
                    "message": data
                })
    
    async def output(self, stream: JSONLStream):
        try:
            while True:
                match await stream.read():
                    case {"type": "close"}:
                        break
                    case {"type": "text", "message": message}:
                        fprint("<", ("class:ezra", "ezra"), "> ", message)
                    case {"type": "error", "message": message}:
                        fprint(("class:error", message))
                    case {"type": "uncaught", "traceback": tb}:
                        fprint(("class:uncaught", tb))
                    
                    case data:
                        fprint(("class: error", json.dumps(data)))
        except ConnectionResetError:
            pass
    
    async def start(self):
        async with asyncio.TaskGroup() as tg:
            r, w = await asyncio.open_unix_connection(self.path)
            async with JSONLStream(r, w) as stream:
                _, pending = await asyncio.wait([
                    tg.create_task(self.input(stream)),
                    tg.create_task(self.output(stream)),
                ], return_when=asyncio.FIRST_COMPLETED)
                
                for task in pending:
                    task.cancel()
                
                await asyncio.gather(*pending, return_exceptions=True)

async def main():
    path = "private/ezra.sock"
    client = EzraClient(path)
    await client.start()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass