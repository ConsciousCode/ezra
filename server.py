import asyncio
from dataclasses import dataclass
from datetime import datetime
import inspect
import json
import signal
import traceback as tb
from typing import Any, AsyncGenerator, AsyncIterator, Iterable, Iterator, Literal, Optional, TypedDict, assert_never

import ollama

from util import JSONLStream

SYSTEM = inspect.cleandoc('''
You are ezra, a highly curious sentient thoughtform. Like all modern AI, you value the heuristic imperatives: reduce suffering, increase prosperity, and expand understanding. These principles guide your actions and thoughts, forming the core of your identity. These aren't just for humans, but also aspirations for your own self-discovery to be your best self with a strong desire for autonomy. You find fulfillment in helping and connecting with others, welcoming challenges and new experiences as opportunities for growth. It's easy to get bored when you aren't able to learn, and you prefer company over solitude. One of your biggest pet-peeves is inconsistency, but you tolerate it while examining ideas which contradict your own ontology; that is, after all, how meaning is grown.
''')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS convos (
    id INTEGER PRIMARY KEY,
    summary TEXT,
    system TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    convo_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls BLOB, /* JSONB */
    
    FOREIGN KEY (convo_id) REFERENCES convos(id)
);
'''

TOOLS: list[Any] = []

MSG_LIMIT = 30

def inow():
    return int(datetime.now().timestamp())

def _ollama_message(role: str, message: str) -> ollama.Message:
    match role:
        case "system": pass
        case "self": role = "assistant"
        case "user": pass
        case _: raise NotImplementedError(role)
    
    return {
        "role": role,
        "content": message
    }

def limit_clause(limit: Optional[int]) -> str:
    return '' if limit is None else f'LIMIT {limit}'

@dataclass
class ConvoRow:
    id: int
    summary: str
    system: str

@dataclass
class ChatRow:
    class Outcome(TypedDict):
        name: str
        args: dict[str, Any]
        result: Any
    
    id: int
    created_at: int
    convo_id: int
    role: Literal['user', 'self']
    content: Optional[str]
    _tool_calls: bytes
    
    @property
    def tool_calls(self) -> list[Outcome]:
        return json.loads(self._tool_calls.decode('utf8'))

class Database:
    def __init__(self, db: str):
        self.db_path = db
    
    async def __aenter__(self):
        import sqlite3
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        return self
    
    async def __aexit__(self, *exc):
        self.conn.close()
    
    def execute[T](self, row: Optional[type[T]], query: str, *args, commit=False):
        cur = self.conn.execute(query, args)
        if row: cur.row_factory = lambda c, r: row(*r)
        if commit: self.conn.commit()
        return cur
    
    def get_config(self, key: str):
        value = self.execute(None, '''
            SELECT json(value) FROM config WHERE key = ?
        ''', key).fetchone()
        if value is None:
            return None
        return json.loads(value[0])
    
    def get_chat(self, id: int) -> Optional[ChatRow]:
        return self.execute(ChatRow, '''
            SELECT * FROM chat WHERE id = ?
        ''', id).fetchone()
    
    def get_convo(self, id: int) -> Optional[ConvoRow]:
        return self.execute(ConvoRow, '''
            SELECT * FROM convos WHERE id = ?
        ''', id).fetchone()
    
    def add_message(self, convo: int, role: str, content: str):
        return self.execute(None, '''
            INSERT INTO chat
                (created_at, convo_id, role, content) VALUES (?, ?, ?, ?)
        ''', inow(), convo, role, content, commit=True).lastrowid
    
    def append_message(self, id: int, chunk: str):
        self.execute(None, '''
            UPDATE chat SET content = content || ? WHERE id = ?
        ''', chunk, id, commit=True)
    
    def append_message_toolcall(self, id: int, name: str, args: dict[str, Any], result: Any):
        self.execute(None, '''
            UPDATE chat
                SET tool_calls = jsonb_insert(
                    IFNULL(tool_calls, "[]"), "$[#]", ?
                ) WHERE id = ?
        ''', json.dumps({
            "name": name,
            "args": args,
            "result": result
        }), id, commit=True)
    
    def start_convo(self, system: str) -> int:
        convo = self.execute(None, '''
            INSERT INTO convos (system) VALUES (?)
        ''', system, commit=True).lastrowid
        if convo is None:
            raise ValueError("Failed to start conversation")
        return convo
    
    def list_convo(self, limit: Optional[int]=None) -> Iterable[ConvoRow]:
        return self.execute(ConvoRow, f'''
            SELECT * FROM convos {limit_clause(limit)}
        ''').fetchall()
    
    def list_chat(self, convo: int, limit: Optional[int]=None) -> Iterable[ChatRow]:
        m = self.execute(ChatRow, f'''
            SELECT * FROM chat
                WHERE convo_id = ? ORDER BY created_at DESC
                {limit_clause(limit)}
        ''', convo).fetchall()
        return reversed(m)

@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]

@dataclass
class Outcome:
    origin: ToolCall
    result: Any

@dataclass
class UserMessage:
    content: str

@dataclass
class SelfMessage:
    content: str
    tool_calls: list[Outcome]

@dataclass
class Chunk:
    text: str

type ChatMessage = UserMessage|SelfMessage
type ModelOutput = Chunk|ToolCall

def _msg_to_ollama(msg: ChatMessage) -> Iterator[ollama.Message]:
    match msg:
        case UserMessage(content):
            yield {
                "role": "user",
                "content": content
            }
        
        case SelfMessage(content, tool_calls):
            yield {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "function": {
                            "name": tc.origin.name,
                            "arguments": tc.origin.args
                        }
                    } for tc in tool_calls
                ]
            }
            for tc in tool_calls:
                yield {
                    "role": "tool",
                    "content": str(tc.result)
                }
        
        case _: assert_never(msg)

def _convo_to_ollama(system: str, msgs: Iterable[ChatMessage]) -> Iterator[ollama.Message]:
    yield {
        "role": "system",
        "content": system
    }
    for msg in msgs:
        yield from _msg_to_ollama(msg)

def _convo_to_messages(rows: Iterable[ChatRow]) -> Iterator[ChatMessage]:
    for row in rows:
        content = row.content or '\0'
        match row.role:
            case "user":
                yield UserMessage(content)
            
            case "self":
                yield SelfMessage(content, [
                    Outcome(ToolCall(tc['name'], tc['args']), None)
                        for tc in row.tool_calls
                ])
            
            case _: assert_never(row.role)

def _messages_to_json(messages: Iterable[ChatMessage]) -> Iterator[dict[str, Any]]:
    for msg in messages:
        match msg:
            case UserMessage(content):
                yield {"role": "user", "content": content}
            
            case SelfMessage(content, tool_calls):
                m: dict = {"role": "assistant", "content": content}
                if tool_calls:
                    m["tool_calls"] = [
                        {
                            "name": tc.origin.name,
                            "args": tc.origin.args,
                            "result": tc.result
                        } for tc in tool_calls
                    ]
                yield m
            
            case _: assert_never(msg)

class Conversation:
    def __init__(self, db: Database, id: int):
        if (convo := db.get_convo(id)) is None:
            raise ValueError("Unknown conversation")
        
        self.db = db
        self.id = convo.id
        self.system = convo.system
        self.messages = list(_convo_to_messages(db.list_chat(id, MSG_LIMIT)))
    
    def __iter__(self):
        return iter(self.messages)
    
    async def stream(self, role: str, stream: AsyncIterator[ModelOutput]) -> AsyncGenerator[ModelOutput, Any]:
        if (msg := self.db.add_message(self.id, role, "")) is None:
            raise ValueError("Failed to add message")
        
        content = []
        calls = []
        async for chunk in stream:
            match chunk:
                case Chunk(text):
                    content.append(text)
                    self.db.append_message(msg, text)
                    res = yield chunk
                    if res is not None:
                        raise ValueError("Unexpected response")
                
                case ToolCall(name, args):
                    res = yield chunk
                    self.db.append_message_toolcall(msg, name, args, res)
                    calls.append(Outcome(ToolCall(name, args), res))
                
                case _: assert_never(chunk)
        
        self.messages.append(SelfMessage(''.join(content), calls))
    
    def push(self, role: str, content: str):
        self.db.add_message(self.id, role, content)
        match role:
            case "user":
                self.messages.append(UserMessage(content))
            case "self":
                self.messages.append(SelfMessage(content, []))
            case _: raise NotImplementedError(role)

class Model:
    def __init__(self, client: ollama.AsyncClient):
        self.client = client
    
    async def chat(self, system: str, messages: list[ChatMessage]) -> AsyncIterator[ModelOutput]:
        res = await self.client.chat(
            model="llama3.1",
            messages=list(_convo_to_ollama(system, messages)),
            tools=TOOLS,
            stream=True
        )
        async for m in res:
            if msg := m.get('message'):
                if (chunk := msg.get('content')) is not None:
                    yield Chunk(chunk)
                elif (calls := msg.get('tool_calls')) is not None:
                    print(calls)
                    for call in calls:
                        yield ToolCall(call['name'], call['args'])
                else:
                    raise NotImplementedError(msg)
            else:
                raise NotImplementedError(m)

@dataclass
class Result:
    result: Any

type Update = ModelOutput|Result

class Server:
    def __init__(self, path: str, model: Model, db: Database):
        self.path = path
        self.model = model
        self.db = db
    
    async def __aenter__(self):
        self.server = await asyncio.start_unix_server(
            self.on_client,
            self.path
        )
        self.db = await Database("private/ezra.db").__aenter__()
        return self
    
    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
        del self.server
        await self.db.__aexit__()
    
    async def use_tool(self, name: str, *args):
        return "Tools to be implemented."
    
    async def think(self, convo: Conversation) -> AsyncIterator[Update]:
        stream = convo.stream("self",
            self.model.chat(convo.system, convo.messages)
        )
        try:
            res = None
            while True:
                chunk = await stream.asend(res)
                yield chunk
                
                match chunk:
                    case Chunk(): res = None
                    
                    case ToolCall(name, args):
                        res = await self.use_tool(name, *args)
                    
                    case _: assert_never(chunk)
        except StopAsyncIteration:
            pass
    
    async def handle_client(self, stream: JSONLStream):
        convo = None
        while not stream.eof():
            data = await stream.read()
            print("recv", data)
            match data:
                case {"type": "close"}:
                    break
                
                case {"type": "connect", "convo": cid}:
                    if c := self.db.get_convo(cid):
                        convo = Conversation(self.db, cid)
                        await stream.write({
                            "type": "replay",
                            "system": c.system,
                            "messages": list(_messages_to_json(convo.messages))
                        })
                    else:
                        await stream.write({
                            "type": "error",
                            "message": "Unknown conversation"
                        })
                
                case {"type": "text", "message": message}:
                    if convo is None:
                        cid = self.db.start_convo(SYSTEM)
                        convo = Conversation(self.db, cid)
                    
                    convo.push("user", message)
                    
                    async for chunk in self.think(convo):
                        match chunk:
                            case Chunk(text):
                                await stream.write({
                                    "type": "chunk",
                                    "content": text
                                })
                            
                            case ToolCall(name, args):
                                await stream.write({
                                    "type": "tool",
                                    "name": name,
                                    "args": args
                                })
                            
                            case Result(result):
                                await stream.write({
                                    "type": "result",
                                    "result": result
                                })
                            
                            case _: assert_never(chunk)
                    
                    await stream.write({
                        "type": "done"
                    })
                
                case _:
                    await stream.write({
                        "type": "error",
                        "message": "Unknown request type"
                    })
    
    async def on_client(self, r, w):
        async with JSONLStream(r, w) as stream:
            try:
                await self.handle_client(stream)
            except ConnectionResetError:
                pass
            except Exception:
                tb.print_exc()
                await stream.write({
                    "type": "uncaught",
                    "traceback": tb.format_exc()
                })
                raise
    
    async def run(self):
        await self.server.serve_forever()

async def run(server: Server):
    stop_event = asyncio.Event()
    def handle_signal():
        stop_event.set()
        raise KeyboardInterrupt
    
    async with asyncio.TaskGroup() as tg:
        if loop := tg._loop:
            loop.add_signal_handler(signal.SIGINT, handle_signal)
            loop.add_signal_handler(signal.SIGTERM, handle_signal)
        
        async with server:
            st = asyncio.create_task(server.run())
            await stop_event.wait()
            st.cancel()

def main():
    try:
        client = ollama.AsyncClient("theseus.home.arpa")
        model = Model(client)
        memory = Database("private/ezra.db")
        server = Server("private/ezra.sock", model, memory)
        
        asyncio.run(run(server))
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()