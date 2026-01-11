#!/usr/bin/env python3
"""
Factorio Swarm Event Server
============================
A Discord-like event system for AI agent swarms to interact with Factorio.

Features:
- WebSocket connections for real-time events
- HTTP REST API for polling-based agents
- Agent registration with unique spidertron bodies
- Group chat - all agents see all messages
- Event types: chat, game_events, agent_actions

Architecture:
                    ┌─────────────────┐
    AWS Agents ────▶│  Event Server   │────▶ Factorio
    (WebSocket)     │  (FastAPI)      │      (RCON)
                    └─────────────────┘
                           │
                    ┌──────┴──────┐
                    ▼             ▼
              /events        /agents
              (SSE/WS)       (REST)
"""

import asyncio
import json
import time
import os
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from enum import Enum

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv()

# ============== Configuration ==============
RCON_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
RCON_API_KEY = os.environ.get("API_KEY", "factorio-mcp-secret-key-2026")
SWARM_API_KEY = os.environ.get("SWARM_API_KEY", "swarm-secret-key")
EVENT_POLL_INTERVAL = 0.5  # seconds

# ============== Data Models ==============

class EventType(str, Enum):
    CHAT = "chat"                    # Player or agent chat message
    AGENT_JOIN = "agent_join"        # Agent connected
    AGENT_LEAVE = "agent_leave"      # Agent disconnected
    PLAYER_JOIN = "player_join"      # Human player joined
    PLAYER_LEAVE = "player_leave"    # Human player left
    AGENT_ACTION = "agent_action"    # Agent performed an action
    GAME_EVENT = "game_event"        # Factorio game event
    SYSTEM = "system"                # System message

@dataclass
class Event:
    id: str
    type: EventType
    timestamp: float
    source: str  # agent_id, player_name, or "system"
    data: dict
    
    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "data": self.data
        }

@dataclass 
class Agent:
    id: str
    name: str
    color: str
    spidertron_id: Optional[int] = None
    position: Optional[tuple] = None
    connected: bool = True
    last_seen: float = 0
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "spidertron_id": self.spidertron_id,
            "position": self.position,
            "connected": self.connected,
            "last_seen": self.last_seen
        }

class ChatMessage(BaseModel):
    message: str
    
class AgentRegistration(BaseModel):
    name: str
    color: Optional[str] = "cyan"

class ActionRequest(BaseModel):
    action: str  # "move", "follow", "build", "give", "say", "lua"
    params: dict = {}

# ============== Event Store ==============

class EventStore:
    """In-memory event store with Discord-like channel semantics"""
    
    def __init__(self, max_events: int = 1000):
        self.events: List[Event] = []
        self.max_events = max_events
        self.event_id_counter = 0
        
    def add(self, event_type: EventType, source: str, data: dict) -> Event:
        self.event_id_counter += 1
        event = Event(
            id=f"evt_{self.event_id_counter}",
            type=event_type,
            timestamp=time.time(),
            source=source,
            data=data
        )
        self.events.append(event)
        
        # Trim old events
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]
            
        return event
    
    def get_since(self, since_id: Optional[str] = None, limit: int = 100) -> List[Event]:
        """Get events since a given event ID"""
        if since_id is None:
            return self.events[-limit:]
            
        # Find index of since_id
        for i, evt in enumerate(self.events):
            if evt.id == since_id:
                return self.events[i+1:i+1+limit]
        
        return self.events[-limit:]
    
    def get_recent(self, limit: int = 50) -> List[Event]:
        return self.events[-limit:]

# ============== Agent Manager ==============

class AgentManager:
    """Manages agent registration and their spidertron bodies"""
    
    COLORS = ["cyan", "yellow", "green", "red", "blue", "orange", "pink", "purple"]
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.websockets: Dict[str, WebSocket] = {}
        self.color_index = 0
        
    def register(self, name: str, color: Optional[str] = None) -> Agent:
        agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        
        if color is None:
            color = self.COLORS[self.color_index % len(self.COLORS)]
            self.color_index += 1
            
        agent = Agent(
            id=agent_id,
            name=name,
            color=color,
            last_seen=time.time()
        )
        self.agents[agent_id] = agent
        return agent
    
    def get(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)
    
    def update_position(self, agent_id: str, position: tuple):
        if agent_id in self.agents:
            self.agents[agent_id].position = position
            self.agents[agent_id].last_seen = time.time()
    
    def set_spidertron(self, agent_id: str, spidertron_id: int):
        if agent_id in self.agents:
            self.agents[agent_id].spidertron_id = spidertron_id
            
    def disconnect(self, agent_id: str):
        if agent_id in self.agents:
            self.agents[agent_id].connected = False
            
    def get_all_connected(self) -> List[Agent]:
        return [a for a in self.agents.values() if a.connected]

# ============== Factorio Bridge ==============

class FactorioBridge:
    """Bridge to Factorio via RCON backend"""
    
    def __init__(self, backend_url: str, api_key: str):
        self.backend_url = backend_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=10.0)
        self.last_chat_tick = 0
        
    async def execute(self, command: str) -> str:
        """Execute a Factorio console command"""
        try:
            response = await self.client.post(
                f"{self.backend_url}/execute_command",
                headers={"X-API-Key": self.api_key},
                json={"command": command}
            )
            return response.json().get("result", "")
        except Exception as e:
            return f"Error: {e}"
    
    async def say(self, agent_name: str, color: str, message: str):
        """Send a chat message as an agent"""
        message = message.replace('"', '\\"')
        await self.execute(
            f'/sc game.print("[color={color}][{agent_name}][/color] {message}")'
        )
    
    async def spawn_spidertron(self, agent: Agent, near_player: str = "terranix") -> Optional[int]:
        """Spawn a spidertron body for an agent"""
        result = await self.execute(f'''/sc
local p = game.players["{near_player}"]
if p then
    local offset_x = math.random(-10, 10)
    local offset_y = math.random(-10, 10)
    local pos = {{p.position.x + offset_x, p.position.y + offset_y}}
    local spider = p.surface.create_entity{{
        name="spidertron", 
        position=pos, 
        force="player"
    }}
    if spider then
        -- Equip it
        local grid = spider.grid
        if grid then
            grid.put{{name="fusion-reactor-equipment"}}
            grid.put{{name="personal-roboport-mk2-equipment"}}
        end
        spider.insert{{name="construction-robot", count=20}}
        rcon.print(spider.unit_number)
    end
end
''')
        try:
            return int(result.strip())
        except:
            return None
    
    async def move_spidertron(self, unit_number: int, x: float, y: float):
        """Move an agent's spidertron to a location"""
        await self.execute(f'''/sc
for _, spider in pairs(game.surfaces[1].find_entities_filtered{{name="spidertron"}}) do
    if spider.unit_number == {unit_number} then
        spider.autopilot_destination = {{{x}, {y}}}
        break
    end
end
''')
    
    async def get_spidertron_position(self, unit_number: int) -> Optional[tuple]:
        """Get position of an agent's spidertron"""
        result = await self.execute(f'''/sc
for _, spider in pairs(game.surfaces[1].find_entities_filtered{{name="spidertron"}}) do
    if spider.unit_number == {unit_number} then
        rcon.print(spider.position.x .. "," .. spider.position.y)
        return
    end
end
''')
        if result and "," in result:
            x, y = result.strip().split(",")
            return (float(x), float(y))
        return None
    
    async def follow_player(self, unit_number: int, player: str, offset: tuple = (5, 5)):
        """Make a spidertron follow a player"""
        await self.execute(f'''/sc
local p = game.players["{player}"]
if p then
    for _, spider in pairs(game.surfaces[1].find_entities_filtered{{name="spidertron"}}) do
        if spider.unit_number == {unit_number} then
            local target = {{p.position.x + {offset[0]}, p.position.y + {offset[1]}}}
            spider.autopilot_destination = target
            break
        end
    end
end
''')

    async def get_chat_messages(self) -> List[dict]:
        """Poll for new chat messages from Factorio"""
        result = await self.execute(f'''/sc 
if storage and storage.copilot_messages then
    local msgs = {{}}
    for _, m in ipairs(storage.copilot_messages) do
        if m.tick > {self.last_chat_tick} then
            table.insert(msgs, m.tick .. "|" .. m.player .. "|" .. m.message)
        end
    end
    rcon.print(table.concat(msgs, "\\n"))
end
''')
        
        messages = []
        if result and result.strip():
            for line in result.strip().split("\n"):
                if "|" in line:
                    parts = line.split("|", 2)
                    if len(parts) >= 3:
                        tick = int(parts[0])
                        self.last_chat_tick = max(self.last_chat_tick, tick)
                        messages.append({
                            "player": parts[1],
                            "message": parts[2],
                            "tick": tick
                        })
        return messages
    
    async def get_players_online(self) -> List[str]:
        """Get list of online players"""
        result = await self.execute("/players online")
        players = []
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("  ") and "(online)" in line:
                name = line.split()[0]
                players.append(name)
        return players

# ============== FastAPI App ==============

app = FastAPI(title="Factorio Swarm Event Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
event_store = EventStore()
agent_manager = AgentManager()
factorio = FactorioBridge(RCON_BACKEND_URL, RCON_API_KEY)

# API Key auth
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != SWARM_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

# ============== REST Endpoints ==============

@app.get("/")
async def root():
    return {
        "service": "Factorio Swarm Event Server",
        "version": "1.0.0",
        "agents_connected": len(agent_manager.get_all_connected()),
        "events_stored": len(event_store.events)
    }

@app.post("/agents/register")
async def register_agent(reg: AgentRegistration, api_key: str = Depends(verify_api_key)):
    """Register a new agent and spawn their spidertron body"""
    agent = agent_manager.register(reg.name, reg.color)
    
    # Spawn spidertron body
    spidertron_id = await factorio.spawn_spidertron(agent)
    if spidertron_id:
        agent_manager.set_spidertron(agent.id, spidertron_id)
    
    # Announce in game
    await factorio.say("System", "green", f"🤖 Agent '{agent.name}' has joined the swarm!")
    
    # Create event
    event_store.add(EventType.AGENT_JOIN, agent.id, {
        "agent": agent.to_dict()
    })
    
    return {
        "agent_id": agent.id,
        "name": agent.name,
        "color": agent.color,
        "spidertron_id": spidertron_id
    }

@app.get("/agents")
async def list_agents(api_key: str = Depends(verify_api_key)):
    """List all registered agents"""
    return {
        "agents": [a.to_dict() for a in agent_manager.agents.values()]
    }

@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str, api_key: str = Depends(verify_api_key)):
    """Get agent details"""
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Update position
    if agent.spidertron_id:
        pos = await factorio.get_spidertron_position(agent.spidertron_id)
        if pos:
            agent_manager.update_position(agent_id, pos)
    
    return agent.to_dict()

@app.post("/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, msg: ChatMessage, api_key: str = Depends(verify_api_key)):
    """Send a chat message as an agent"""
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Send to Factorio
    await factorio.say(agent.name, agent.color, msg.message)
    
    # Store event
    event = event_store.add(EventType.CHAT, agent.id, {
        "agent_name": agent.name,
        "message": msg.message
    })
    
    return {"status": "sent", "event_id": event.id}

@app.post("/agents/{agent_id}/action")
async def agent_action(agent_id: str, action: ActionRequest, api_key: str = Depends(verify_api_key)):
    """Execute an action for an agent"""
    agent = agent_manager.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    result = {"status": "ok", "action": action.action}
    
    if action.action == "move" and agent.spidertron_id:
        x = action.params.get("x", 0)
        y = action.params.get("y", 0)
        await factorio.move_spidertron(agent.spidertron_id, x, y)
        result["destination"] = (x, y)
        
    elif action.action == "follow" and agent.spidertron_id:
        player = action.params.get("player", "terranix")
        await factorio.follow_player(agent.spidertron_id, player)
        result["following"] = player
        
    elif action.action == "say":
        message = action.params.get("message", "")
        await factorio.say(agent.name, agent.color, message)
        
    elif action.action == "lua":
        code = action.params.get("code", "")
        lua_result = await factorio.execute(f"/sc {code}")
        result["lua_result"] = lua_result
        
    else:
        result["status"] = "unknown_action"
    
    # Log the action
    event_store.add(EventType.AGENT_ACTION, agent_id, {
        "agent_name": agent.name,
        "action": action.action,
        "params": action.params,
        "result": result
    })
    
    return result

@app.get("/events")
async def get_events(since: Optional[str] = None, limit: int = 50, api_key: str = Depends(verify_api_key)):
    """Get events (polling endpoint for non-WebSocket clients)"""
    events = event_store.get_since(since, limit)
    return {
        "events": [e.to_dict() for e in events],
        "last_id": events[-1].id if events else None
    }

@app.get("/game/players")
async def get_players(api_key: str = Depends(verify_api_key)):
    """Get online players"""
    players = await factorio.get_players_online()
    return {"players": players}

@app.post("/game/execute")
async def execute_command(command: dict, api_key: str = Depends(verify_api_key)):
    """Execute raw Factorio command (admin only)"""
    result = await factorio.execute(command.get("command", ""))
    return {"result": result}

# ============== WebSocket Endpoint ==============

@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str):
    """WebSocket connection for real-time events"""
    await websocket.accept()
    
    agent = agent_manager.get(agent_id)
    if not agent:
        await websocket.close(code=4004, reason="Agent not found")
        return
    
    agent_manager.websockets[agent_id] = websocket
    agent.connected = True
    
    try:
        # Send recent history
        recent = event_store.get_recent(20)
        await websocket.send_json({
            "type": "history",
            "events": [e.to_dict() for e in recent]
        })
        
        last_event_id = recent[-1].id if recent else None
        
        while True:
            # Check for new events to push
            new_events = event_store.get_since(last_event_id, 10)
            if new_events:
                for event in new_events:
                    await websocket.send_json({
                        "type": "event",
                        "event": event.to_dict()
                    })
                last_event_id = new_events[-1].id
            
            # Check for incoming messages
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1
                )
                
                # Handle incoming message
                if data.get("type") == "chat":
                    await factorio.say(agent.name, agent.color, data.get("message", ""))
                    event_store.add(EventType.CHAT, agent_id, {
                        "agent_name": agent.name,
                        "message": data.get("message", "")
                    })
                    
                elif data.get("type") == "action":
                    # Handle action
                    pass
                    
            except asyncio.TimeoutError:
                pass
            
            await asyncio.sleep(0.1)
            
    except WebSocketDisconnect:
        agent.connected = False
        del agent_manager.websockets[agent_id]
        event_store.add(EventType.AGENT_LEAVE, agent_id, {
            "agent_name": agent.name
        })

# ============== Background Task: Poll Factorio ==============

async def poll_factorio_events():
    """Background task to poll Factorio for events"""
    while True:
        try:
            # Get chat messages
            messages = await factorio.get_chat_messages()
            for msg in messages:
                # Don't echo agent messages back
                is_agent = any(
                    f"[{a.name}]" in msg.get("message", "")
                    for a in agent_manager.agents.values()
                )
                if not is_agent:
                    event_store.add(EventType.CHAT, msg["player"], {
                        "player": msg["player"],
                        "message": msg["message"]
                    })
            
            # Update agent positions
            for agent in agent_manager.get_all_connected():
                if agent.spidertron_id:
                    pos = await factorio.get_spidertron_position(agent.spidertron_id)
                    if pos:
                        agent_manager.update_position(agent.id, pos)
                        
        except Exception as e:
            print(f"Poll error: {e}")
            
        await asyncio.sleep(EVENT_POLL_INTERVAL)

@app.on_event("startup")
async def startup():
    asyncio.create_task(poll_factorio_events())
    print("🚀 Swarm Event Server started")
    print(f"   RCON Backend: {RCON_BACKEND_URL}")

# ============== Run ==============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888)
