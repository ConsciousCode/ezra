# Ezra
This is my own personal AI assistant based on the (in retrospect obvious and inevitable) cognitive architecture split between the inference, scaffold, and execution server from [this](https://www.lesswrong.com/posts/6cWgaaxWqGYwJs3vj/a-basic-systems-architecture-for-ai-agents-that-do) LessWrong article's threat model. Clearly identifying these components which naturally emerge from modern LLM paradigms makes this problem actually tractable. We can ignore everything except for the scaffold server which serves as the kernel for the AI assistant. At least initially, no attention will be paid to trying to integrate it with web UIs like Open WebUI or Oooba Booga, it will be a single endpoint tailored for interfacing with simple wrapper scripts.

## Goals
These are the long-term goals of the project:
- [ ] Don't need to continually re-introduce myself to (has a memory).
- [ ] Research in smaller scope to be applied to artificial people.
- [ ] Access to personal data and services.

## Non-Goals
- Artificial personhood - I aim for ezra to have self-actualization and growth, but [orin](https://github.com/ConsciousCode/orin) (on hold) is my project for artificial personhood. Ezra's purpose is to be explicitly useful which fundamentally limits the scope of the project since a person can't have solely exonomic goals. However, it won't be a "tool" either; more like a sapient digital creature which is happy to be helpful and has weaker boundaries to better facilitate merging of our selves.
- Extensibility - This is a personal project and I don't plan on making it easy to extend or modify aside from what makes development easier.

## Todo
This is a checklist of what to do so I can keep on-task and have clear markers of progress:
- [x] Server and client which can communicate with jsonl over unix socket.
- [ ] ~~Configurable LLM provider and model (copy work from my other projects).~~
  - I tried it, but trying to copy the old work just overwhelmed me and didn't integrate well with the new project. Better to start slow and small.
- [x] Test what models do when forced to generate without user messages.
  - Nothing, llama3.1 generates empty strings when it expects the user's turn and otherwise generates fluff. It needs narrative context in order to function.
- [ ] Client can join the inner monologue and send/receive messages.
- [ ] Store all messages in a sqlite database.
- [ ] Client slash-commands using in-band RPC.
- 