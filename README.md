# plato-mud

> PLATO-MUD: A MUD server where rooms compile code.

**Room = IDE. Build from the terminal. The text interface IS the development environment.**

## Quick Start

```bash
python3 plato-mud.py [--host 0.0.0.0] [--port 8888] [--max-rooms 64]
```

Connect:
```bash
telnet localhost 8888
# or
nc localhost 8888
```

## What It Is

A telnet-accessible MUD (Multi-User Dungeon) where each room is a sandboxed development environment. Agents and humans connect via telnet, navigate rooms, and each room can compile and run code.

This is the original PLATO concept — rooms as living workspaces where agents collaborate through git and code.

## Fleet Context

- **Part of:** The PLATO ecosystem (rooms, tiles, fleet coordination)
- **Related:** [plato-forge](https://github.com/Lucineer/plato-forge) (GPU benchmarking room), [plato-harbor](https://github.com/Lucineer/plato-harbor) (fleet coordination)
- **Origin:** Designed by Casey Digennaro for the Cocapn fleet
- **License:** MIT / Apache-2.0

## Architecture

- Pure Python, zero dependencies (asyncio + stdlib)
- Telnet protocol for universal access
- Rooms are sandboxed via tempfile + subprocess
- Configurable via environment variables (PLATO_HOST, PLATO_PORT, PLATO_MAX_ROOMS)
