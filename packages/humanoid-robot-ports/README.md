# humanoid-robot-ports

Port interfaces implemented by adapters.

Each port is a `typing.Protocol` (structural typing). Adapters do **not** have
to inherit from these classes — they only have to satisfy the interface. This
keeps adapter packages free of upward dependencies on ports.

Ports are grouped by concern:

- `event_bus` — pub/sub transport
- `robot` — hardware-facing capabilities of a physical robot
- `ai` — ASR / LLM / TTS / Embedding
- `knowledge` — vector store, document parsing, chunking
- `security` — secrets, RBAC
- `network` — wifi/eth/mDNS
