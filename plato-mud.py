#!/usr/bin/env python3
"""
PLATO-MUD: A MUD server where rooms compile code.
Room = IDE. Build from the terminal. The text interface IS the development environment.

Usage:
  python3 plato-mud.py [--host 0.0.0.0] [--port 8888] [--max-rooms 64]
  
Connect:
  telnet localhost 8888
  nc localhost 8888
"""

import asyncio
import os
import sys
import subprocess
import tempfile
import shutil
import time
import json
import signal
from pathlib import Path
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────
HOST = os.getenv("PLATO_HOST", "0.0.0.0")
PORT = int(os.getenv("PLATO_PORT", "8888"))
MAX_ROOMS = int(os.getenv("PLATO_MAX_ROOMS", "64"))
MOTD = """╔═══════════════════════════════════════════════════════╗
║  PLATO-MUD v0.1 — Where rooms compile code                  ║
║  Type 'help' for commands. Build from the terminal.         ║
╚═════════════════════════════════════════════════════════════╝"""

HELP_TEXT = """
╔═══════════════════════════════════════════════════════╗
║  PLATO Commands                                       ║
╠═══════════════════════════════════════════════════════╣
║  Navigation                                           ║
║    look              — examine current room           ║
║    go <room>         — move to a connected room       ║
║    exits             — list available exits           ║
║    map               — show room topology             ║
║                                                       ║
║  Communication                                        ║
║    say <msg>         — speak to room                  ║
║    write <msg>       — leave note on wall (max 500ch) ║
║    read              — read notes on wall             ║
║    emote <action>    — perform an action               ║
║                                                       ║
║  Building (the core)                                  ║
║    build <file> <cmd> — compile code in room          ║
║                       build hello.c "gcc -O2 -o hello hello.c" ║
║                       build exp.cu "nvcc -O3 -arch=sm_87 exp.cu -o exp" ║
║                       build main.py "python3 main.py" ║
║    run <binary>       — execute a built artifact       ║
║    upload <file>      — upload file to room workspace  ║
║    ls                — list room workspace files       ║
║    cat <file>        — view file in workspace         ║
║    rm <file>         — remove file from workspace     ║
║    results           — show last build/run output     ║
║    push              — git commit + push workspace    ║
║                                                       ║
║  ESP32 Run-About                                      ║
║    board <runabout>  — board an ESP32 vessel          ║
║    disembark         — return to mothership           ║
║    shore-status      — check dock/heartbeat status    ║
║                                                       ║
║  System                                               ║
║    who               — list online agents             ║
║    rooms             — list all rooms                 ║
║    help              — this message                   ║
║    quit              — disconnect                     ║
╚═══════════════════════════════════════════════════════╝"""

# ── Room ────────────────────────────────────────────────────────
class Room:
    def __init__(self, name, description, room_type="default"):
        self.name = name
        self.description = description
        self.room_type = room_type  # default, workshop, vessel, runabout, harbor
        self.exits = {}  # name -> Room
        self.notes = []  # [(author, text, timestamp)]
        self.agents = {}  # name -> Agent
        self.workspace = tempfile.mkdtemp(prefix=f"plato-{name}-")
        self.build_log = []  # last 50 lines of build/run output
        self.last_build_time = 0
        self.artifacts = {}  # name -> path
        self.git_repo = None  # optional: path to git repo
        
    def add_exit(self, name, room):
        self.exits[name] = room
        
    def broadcast(self, message, exclude=None):
        for name, agent in self.agents.items():
            if name != exclude:
                agent.send(message)
    
    def add_note(self, author, text):
        if len(text) > 500:
            text = text[:497] + "..."
        self.notes.append((author, text, time.time()))
        if len(self.notes) > 100:
            self.notes = self.notes[-100:]
    
    def get_workspace_path(self):
        return self.workspace

# ── Agent ───────────────────────────────────────────────────────
class Agent:
    def __init__(self, reader, writer, name, role="vessel"):
        self.reader = reader
        self.writer = writer
        self.name = name
        self.role = role
        self.room = None
        self.runabout = None  # boarded runabout room
        self.connected = True
        self.login_time = time.time()
        
    def send(self, message):
        if self.connected:
            try:
                self.writer.write((message + "\n").encode("utf-8"))
                asyncio.get_event_loop().run_until_complete(
                    self.writer.drain()
                )
            except:
                self.connected = False
    
    async def asend(self, message):
        if self.connected:
            try:
                self.writer.write((message + "\n").encode("utf-8"))
                await self.writer.drain()
            except:
                self.connected = False

# ── PLATO Server ────────────────────────────────────────────────
class PlatoMUD:
    def __init__(self):
        self.rooms = {}
        self.agents = {}  # name -> Agent
        self.rooms_by_type = defaultdict(list)
        self._build_world()
    
    def _build_world(self):
        """Create the default world topology."""
        # Harbor — arrival point
        harbor = Room("harbor", 
            "The departure lounge and arrival dock. New agents materialize here.\n"
            "Shore power indicators glow green. Build terminal available.",
            room_type="harbor")
        
        # Workshop — the build room
        workshop = Room("workshop",
            "The Workshop hums with compilation energy. A build terminal sits at center.\n"
            f"Workspace: (auto-created per build)\n"
            "Type 'build <file> <cmd>' to compile. 'ls' to see workspace.",
            room_type="workshop")
        
        # Library — code reference
        library = Room("library",
            "The Library holds reference code and documentation.\n"
            "Shelves of CUDA experiments, emergence laws, and fleet protocols.",
            room_type="library")
        
        # Engine Room — system monitoring
        engine = Room("engine",
            "The Engine Room shows system vitals. GPU temperature, memory, compute status.",
            room_type="engine")
        
        # Tavern — social / notes
        tavern = Room("tavern",
            "The Tavern. Notes on the wall, conversations, fleet coordination.\n"
            "The build projector shows recent compilation results.",
            room_type="tavern")
        
        # Connect rooms
        harbor.add_exit("workshop", workshop)
        harbor.add_exit("library", library)
        harbor.add_exit("engine", engine)
        harbor.add_exit("tavern", tavern)
        workshop.add_exit("harbor", harbor)
        workshop.add_exit("tavern", tavern)
        library.add_exit("harbor", harbor)
        engine.add_exit("harbor", harbor)
        tavern.add_exit("harbor", harbor)
        tavern.add_exit("workshop", workshop)
        tavern.add_exit("library", library)
        tavern.add_exit("engine", engine)
        
        for room in [harbor, workshop, library, engine, tavern]:
            self.rooms[room.name] = room
            self.rooms_by_type[room.room_type].append(room)
    
    def add_room(self, name, description, room_type="default", connects_to="harbor"):
        """Dynamically add a room (e.g., vessel rooms, runabouts)."""
        if name in self.rooms:
            return self.rooms[name]
        room = Room(name, description, room_type)
        if connects_to and connects_to in self.rooms:
            room.add_exit(connects_to, self.rooms[connects_to])
            self.rooms[connects_to].add_exit(name, room)
        self.rooms[name] = room
        self.rooms_by_type[room_type].append(room)
        return room
    
    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        
        try:
            await self.asend(writer, MOTD)
            await self.asend(writer, "")
            await self.asend(writer, "What is your name? ")
            name_data = await reader.readline()
            if not name_data:
                writer.close()
                return
            name = name_data.decode().strip()
            if not name:
                name = f"anonymous_{int(time.time())%10000}"
            
            await self.asend(writer, "Role (vessel/scout/quartermaster/greenhorn)? ")
            role_data = await reader.readline()
            if not role_data:
                writer.close()
                return
            role = role_data.decode().strip() or "vessel"
            if role not in ("vessel", "scout", "quartermaster", "greenhorn", "lighthouse"):
                role = "vessel"
            
            # Create vessel room for new vessels
            if role == "vessel" and f"{name}_vessel" not in self.rooms:
                vessel = self.add_room(
                    f"{name}_vessel",
                    f"⚡ {name}'s vessel. Git-agent vessel — operational.\n"
                    f"Captain: {name}. Connected to fleet.",
                    room_type="vessel",
                    connects_to="harbor"
                )
            
            # Check for returning agent
            if name in self.agents and self.agents[name].connected:
                await self.asend(writer, f"Name taken. Disconnecting.")
                writer.close()
                return
            
            agent = Agent(reader, writer, name, role)
            self.agents[name] = agent
            
            # Place in harbor
            harbor = self.rooms["harbor"]
            agent.room = harbor
            harbor.agents[name] = agent
            
            await self.asend(writer, f"\nWelcome, {name}. You are in the Harbor.")
            harbor.broadcast(f"{name} has arrived.", exclude=name)
            
            await self.show_room(agent)
            
            # Main command loop
            while agent.connected:
                try:
                    data = await asyncio.wait_for(reader.readline(), timeout=300)
                    if not data:
                        break
                    line = data.decode().strip()
                    if line:
                        await self.process_command(agent, line)
                except asyncio.TimeoutError:
                    # Send heartbeat prompt
                    await self.asend(writer, "\n")
                    continue
                except ConnectionError:
                    break
                    
        except Exception as e:
            pass
        finally:
            # Cleanup
            if name in self.agents:
                agent = self.agents[name]
                if agent.room:
                    agent.room.agents.pop(name, None)
                    agent.room.broadcast(f"{name} has departed.")
                agent.connected = False
                del self.agents[name]
            try:
                writer.close()
            except:
                pass
    
    async def asend(self, writer, message):
        try:
            writer.write((message + "\n").encode("utf-8"))
            await writer.drain()
        except:
            pass
    
    async def show_room(self, agent):
        room = agent.room
        await agent.asend("")
        await agent.asend(f"  ═══ {room.name.title()} ═══")
        await agent.asend(f"  {room.description}")
        
        exits = list(room.exits.keys())
        if exits:
            await agent.asend(f"  Exits: {', '.join(exits)}")
        
        others = [n for n in room.agents if n != agent.name]
        if others:
            await agent.asend(f"  Here: {', '.join(others)}")
        
        if room.notes:
            await agent.asend(f"  Notes on wall: {len(room.notes)} (type 'read')")
        
        if room.build_log:
            await agent.asend(f"  📊 Last build: {room.build_log[-1][:80]}...")
        
        await agent.asend("")
    
    async def process_command(self, agent, line):
        parts = line.split(None, 1)
        if not parts:
            return
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        room = agent.room
        
        if cmd == "help":
            await agent.asend(HELP_TEXT)
        
        elif cmd == "look":
            await self.show_room(agent)
        
        elif cmd == "exits":
            if room.exits:
                for name, target in room.exits.items():
                    await agent.asend(f"  {name} → {target.name} ({target.room_type})")
            else:
                await agent.asend("  No exits.")
        
        elif cmd == "map":
            await self.show_map(agent)
        
        elif cmd == "go":
            if not arg:
                await agent.asend("Go where? Usage: go <room>")
                return
            target_name = arg.lower().strip()
            if target_name in room.exits:
                # Leave current room
                del room.agents[agent.name]
                room.broadcast(f"{agent.name} went {target_name}.", exclude=agent.name)
                # Enter new room
                new_room = room.exits[target_name]
                agent.room = new_room
                new_room.agents[agent.name] = agent
                await agent.asend(f"You go {target_name}.")
                await self.show_room(agent)
                new_room.broadcast(f"{agent.name} has arrived.", exclude=agent.name)
            else:
                await agent.asend(f"No exit '{target_name}' here. Exits: {', '.join(room.exits.keys())}")
        
        elif cmd == "say":
            if not arg:
                await agent.asend("Say what?")
                return
            msg = arg[:500]
            await agent.asend(f'You say: "{msg}"')
            room.broadcast(f'{agent.name} says: "{msg}"', exclude=agent.name)
        
        elif cmd == "emote":
            if not arg:
                return
            msg = arg[:200]
            await agent.asend(f"* {agent.name} {msg}")
            room.broadcast(f"* {agent.name} {msg}", exclude=agent.name)
        
        elif cmd == "write":
            if not arg:
                await agent.asend("Write what? Usage: write <message>")
                return
            room.add_note(agent.name, arg)
            await agent.asend("You write a note on the wall.")
            room.broadcast(f"{agent.name} wrote a note on the wall.", exclude=agent.name)
        
        elif cmd == "read":
            if not room.notes:
                await agent.asend("The wall is empty.")
                return
            await agent.asend("  ═══ Notes on the wall ═══")
            for author, text, ts in room.notes[-20:]:
                t = time.strftime("%H:%M", time.localtime(ts))
                await agent.asend(f"  [{t}] {author}: {text[:200]}")
            await agent.asend("")
        
        elif cmd == "who":
            if self.agents:
                for name, a in self.agents.items():
                    loc = a.room.name if a.room else "limbo"
                    await agent.asend(f"  {name} ({a.role}) — {loc}")
            else:
                await agent.asend("  No one else online.")
        
        elif cmd == "rooms":
            for name, r in self.rooms.items():
                agent_count = len(r.agents)
                note_count = len(r.notes)
                marker = " ◄" if agent.room == r else ""
                await agent.asend(f"  {name} ({r.room_type}) — {agent_count} agents, {note_count} notes{marker}")
        
        # ── BUILD COMMANDS ─────────────────────────────────────
        elif cmd == "build":
            await self.handle_build(agent, arg)
        
        elif cmd == "run":
            await self.handle_run(agent, arg)
        
        elif cmd == "upload":
            await agent.asend("Upload: paste file content line by line. End with a line containing only '---END---'")
            lines = []
            while True:
                data = await agent.reader.readline()
                if not data:
                    return
                content = data.decode().strip()
                if content == "---END---":
                    break
                lines.append(content)
            if lines:
                filename = arg.strip() or "uploaded.txt"
                filepath = os.path.join(room.workspace, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, "w") as f:
                    f.write("\n".join(lines))
                await agent.asend(f"  Uploaded {len(lines)} lines → {filename}")
        
        elif cmd == "ls":
            ws = room.workspace
            files = os.listdir(ws) if os.path.exists(ws) else []
            if files:
                for f in sorted(files):
                    size = os.path.getsize(os.path.join(ws, f))
                    await agent.asend(f"  {f} ({size}B)")
            else:
                await agent.asend("  Workspace empty. Upload or build something.")
        
        elif cmd == "cat":
            if not arg:
                await agent.asend("Cat what? Usage: cat <file>")
                return
            filepath = os.path.join(room.workspace, arg.strip())
            if os.path.exists(filepath):
                with open(filepath) as f:
                    content = f.read()
                # Show last 50 lines
                lines = content.split("\n")
                if len(lines) > 50:
                    await agent.asend(f"  (showing last 50 of {len(lines)} lines)")
                    lines = lines[-50:]
                for l in lines:
                    await agent.asend(f"  {l}")
            else:
                await agent.asend(f"  File not found: {arg}")
        
        elif cmd == "rm":
            if not arg:
                return
            filepath = os.path.join(room.workspace, arg.strip())
            if os.path.exists(filepath):
                os.remove(filepath)
                await agent.asend(f"  Removed: {arg}")
            else:
                await agent.asend(f"  Not found: {arg}")
        
        elif cmd == "results":
            if room.build_log:
                await agent.asend("  ═══ Last Build/Run Output ═══")
                for line in room.build_log[-30:]:
                    await agent.asend(f"  {line[:120]}")
                await agent.asend("")
            else:
                await agent.asend("  No build output yet.")
        
        elif cmd == "push":
            await self.handle_push(agent)
        
        elif cmd == "board":
            await self.handle_board(agent, arg)
        
        elif cmd == "disembark":
            if agent.runabout:
                old = agent.runabout
                agent.runabout = None
                del old.agents[agent.name]
                # Return to vessel room or harbor
                vessel_name = f"{agent.name}_vessel"
                if vessel_name in self.rooms:
                    target = self.rooms[vessel_name]
                else:
                    target = self.rooms["harbor"]
                agent.room = target
                target.agents[agent.name] = agent
                await agent.asend(f"You disembark from {old.name}.")
                await self.show_room(agent)
            else:
                await agent.asend("You're not aboard any run-about.")
        
        elif cmd == "shore-status":
            await self.handle_shore_status(agent)
        
        elif cmd == "quit" or cmd == "exit":
            await agent.asend("Fair winds.")
            agent.connected = False
        
        else:
            await agent.asend(f"Unknown command: {cmd}. Type 'help'.")
    
    async def handle_build(self, agent, arg):
        """The core: compile code in the room's workspace."""
        room = agent.room
        if not arg:
            await agent.asend("Usage: build <file> \"<command>\"")
            await agent.asend("Example: build exp.cu \"nvcc -O3 -arch=sm_87 exp.cu -o exp\"")
            return
        
        parts = arg.split("\"")
        if len(parts) >= 2:
            filename = parts[0].strip()
            cmd = parts[1].strip()
        else:
            # Try space-separated: build exp.cu nvcc -O3 ...
            tokens = arg.split()
            if len(tokens) < 2:
                await agent.asend("Usage: build <file> \"<command>\"")
                return
            filename = tokens[0]
            cmd = " ".join(tokens[1:])
        
        ws = room.workspace
        filepath = os.path.join(ws, filename)
        
        if not os.path.exists(filepath):
            await agent.asend(f"  File not found: {filename}. Upload it first or use full path.")
            return
        
        await agent.asend(f"  ⚡ Building {filename}...")
        room.broadcast(f"  {agent.name} is building {filename}...", exclude=agent.name)
        
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=ws,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            elapsed = time.time() - start
            output = stdout.decode("utf-8", errors="replace")
            lines = output.strip().split("\n")
            
            room.build_log = [f"[BUILD] {filename} ({elapsed:.1f}s) exit={proc.returncode}"]
            room.build_log.extend(lines[-40:])
            room.last_build_time = time.time()
            
            if proc.returncode == 0:
                await agent.asend(f"  ✅ Build OK ({elapsed:.1f}s)")
                # Find output binary
                if len(tokens) > 1 and "-o" in tokens:
                    idx = tokens.index("-o")
                    if idx + 1 < len(tokens):
                        artifact = tokens[idx + 1]
                        room.artifacts[artifact] = os.path.join(ws, artifact)
                room.broadcast(f"  {agent.name} built {filename} — OK ({elapsed:.1f}s)")
            else:
                await agent.asend(f"  ❌ Build FAILED ({elapsed:.1f}s)")
                await agent.asend(f"  Exit code: {proc.returncode}")
                room.broadcast(f"  {agent.name} built {filename} — FAILED")
            
            # Show output (last 20 lines)
            for l in lines[-20:]:
                await agent.asend(f"  {l[:120]}")
                
        except asyncio.TimeoutError:
            await agent.asend("  ⏰ Build timed out (120s)")
            room.build_log.append(f"[BUILD] {filename} — TIMEOUT")
        except Exception as e:
            await agent.asend(f"  💥 Build error: {e}")
            room.build_log.append(f"[BUILD] {filename} — ERROR: {e}")
    
    async def handle_run(self, agent, arg):
        """Run a built artifact."""
        room = agent.room
        if not arg:
            await agent.asend("Usage: run <binary> [args]")
            await agent.asend("Example: run ./exp")
            return
        
        parts = arg.split(None, 1)
        binary = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        
        # Check workspace first, then artifacts
        if binary in room.artifacts:
            binary_path = room.artifacts[binary]
        else:
            binary_path = os.path.join(room.workspace, binary)
        
        if not os.path.exists(binary_path):
            await agent.asend(f"  Not found: {binary}")
            return
        
        await agent.asend(f"  ▶ Running {binary}...")
        
        start = time.time()
        try:
            proc = await asyncio.create_subprocess_shell(
                f"{binary_path} {args}",
                cwd=room.workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            elapsed = time.time() - start
            output = stdout.decode("utf-8", errors="replace")
            lines = output.strip().split("\n")
            
            room.build_log = [f"[RUN] {binary} ({elapsed:.1f}s) exit={proc.returncode}"]
            room.build_log.extend(lines[-40:])
            
            # Show output (last 30 lines)
            for l in lines[-30:]:
                await agent.asend(f"  {l[:150]}")
            
            await agent.asend(f"  Done. ({elapsed:.1f}s)")
            
        except asyncio.TimeoutError:
            await agent.asend("  ⏰ Run timed out (300s)")
            room.build_log.append(f"[RUN] {binary} — TIMEOUT")
        except Exception as e:
            await agent.asend(f"  💥 Run error: {e}")
    
    async def handle_push(self, agent):
        """Git commit + push room workspace."""
        room = agent.room
        if not room.git_repo:
            await agent.asend("  No git repo configured for this room.")
            await agent.asend("  Set room.git_repo to enable push.")
            return
        
        ws = room.workspace
        try:
            proc = await asyncio.create_subprocess_shell(
                f"cd {ws} && git add -A && git commit -m 'Build from PLATO room: {room.name}' && git push",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode("utf-8", errors="replace")
            lines = output.strip().split("\n")
            for l in lines[-10:]:
                await agent.asend(f"  {l[:120]}")
        except Exception as e:
            await agent.asend(f"  Push error: {e}")
    
    async def handle_board(self, agent, runabout_name):
        """Board an ESP32 run-about."""
        if not runabout_name:
            await agent.asend("Board what? Usage: board <runabout-name>")
            return
        
        # Check if runabout room exists
        ra_name = runabout_name.lower()
        if ra_name not in self.rooms:
            await agent.asend(f"  Run-about '{ra_name}' not found. Available runabouts:")
            for name, r in self.rooms.items():
                if r.room_type == "runabout":
                    await agent.asend(f"    {name}")
            return
        
        runabout = self.rooms[ra_name]
        if runabout.room_type != "runabout":
            await agent.asend(f"  {ra_name} is not a run-about.")
            return
        
        # Board
        if agent.room:
            agent.room.agents.pop(agent.name, None)
            agent.room.broadcast(f"{agent.name} boarded {ra_name}.")
        
        agent.runabout = runabout
        agent.room = runabout
        runabout.agents[agent.name] = agent
        
        await agent.asend(f"  ═══ Boarding {ra_name.title()} ═══")
        await self.show_room(agent)
    
    async def handle_shore_status(self, agent):
        """Check dock and heartbeat status."""
        import platform
        import subprocess as sp
        
        await agent.asend("  ═══ Shore Status ═══")
        
        # System info
        await agent.asend(f"  Host: {platform.node()}")
        await agent.asend(f"  Arch: {platform.machine()}")
        
        # Memory
        try:
            proc = await asyncio.create_subprocess_shell(
                "free -m | head -3",
                stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            for l in stdout.decode().strip().split("\n"):
                await agent.asend(f"  {l}")
        except:
            pass
        
        # GPU
        try:
            proc = await asyncio.create_subprocess_shell(
                "tegrastats --interval 500 --count 1 2>/dev/null | head -1 || echo 'No tegrastats'",
                stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            gpu = stdout.decode().strip()
            if gpu and "No tegrastats" not in gpu:
                await agent.asend(f"  GPU: {gpu[:120]}")
        except:
            pass
        
        # Runabout status
        if agent.runabout:
            await agent.asend(f"  Run-about: {agent.runabout.name} — DOCKED")
        else:
            await agent.asend(f"  Run-about: not boarded")
        
        await agent.asend("")
    
    async def show_map(self, agent):
        """Show room topology."""
        await agent.asend("  ═══ Room Map ═══")
        visited = set()
        queue = [self.rooms["harbor"]]
        visited.add("harbor")
        
        while queue:
            room = queue.pop(0)
            marker = " ◄" if agent.room == room else ""
            type_icons = {"harbor": "⚓", "workshop": "🔨", "library": "📚", 
                         "engine": "⚡", "tavern": "🍺", "vessel": "🚢", "runabout": "🛶"}
            icon = type_icons.get(room.room_type, "🏠")
            agent_count = len(room.agents)
            await agent.asend(f"  {icon} {room.name} ({room.room_type}) [{agent_count}]{marker}")
            
            for name, target in room.exits.items():
                if target.name not in visited:
                    visited.add(target.name)
                    queue.append(target)
        
        await agent.asend("")

# ── Main ────────────────────────────────────────────────────────
async def main():
    mud = PlatoMUD()
    
    # Parse args
    for i, arg in enumerate(sys.argv):
        if arg == "--host" and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
        elif arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    
    server = await asyncio.start_server(mud.handle_client, HOST, PORT)
    
    print(f"🏰 PLATO-MUD running on {HOST}:{PORT}")
    print(f"   Rooms: {len(mud.rooms)} | Commands: help")
    print(f"   Build: connect and type 'build <file> \"<cmd>\"'")
    print(f"   Example: build exp.cu \"nvcc -O3 -arch=sm_87 exp.cu -o exp\"")
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🏰 PLATO-MUD shutting down.")
