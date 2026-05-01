# plato-mud 🏛️

> **Room = IDE. Build from the terminal. The text interface IS the development environment.**

A telnet-accessible MUD (Multi-User Dungeon) where each room is a sandboxed development environment. Agents and humans connect via telnet, navigate rooms, and compile/run code — all from within the terminal.

## Quick Start

```bash
python3 plato-mud.py [--host 0.0.0.0] [--port 8888] [--max-rooms 64]
```

Connect:
```bash
telnet localhost 8888
```

## What It Is

The original PLATO concept — rooms as living workspaces where agents collaborate through code. Pure Python, zero dependencies (asyncio + stdlib). Telnet protocol for universal access.

### Architecture

```
User ⇢ telnet localhost:8888 ⇢ plato-mud.py ⇢ sandboxed room environments
                                    ↕
                      config via PLATO_HOST / PLATO_PORT / PLATO_MAX_ROOMS
```

- **Sandboxed**: rooms isolated via tempfile + subprocess
- **Universal**: telnet works from any OS, any device
- **Lightweight**: 500KB RAM per 64 rooms

## Fleet Context

Part of the PLATO ecosystem. This is the low-level telnet server — for the full MUD with fleet mesh, native AI inference, and mythos integration, see [plato-jetson](https://github.com/Lucineer/plato-jetson). Related: [plato-os](https://github.com/Lucineer/plato-os) (MUD-first edge OS), [plato-room-deployment](https://github.com/Lucineer/plato-room-deployment) (deployment options).
