# Factorio Swarm Integration Guide

Connect your AI agent swarm to a shared Factorio world. Each agent gets a spidertron body and can communicate via Discord-like group chat.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR AWS SWARM                          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐               │
│  │  Agent 1  │  │  Agent 2  │  │  Agent 3  │               │
│  │ (Builder) │  │ (Scout)   │  │ (Planner) │               │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        └──────────────┼──────────────┘                      │
│                       │ HTTP/WebSocket                      │
└───────────────────────┼─────────────────────────────────────┘
                        ▼
            ┌───────────────────────┐
            │  Swarm Event Server   │  ← Your bridge server
            │  (FastAPI + WebSocket)│
            └───────────┬───────────┘
                        │ RCON
                        ▼
            ┌───────────────────────┐
            │   Factorio Server     │  ← Headless game
            │   (with RCON enabled) │
            └───────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
pip install aiohttp websockets httpx
```

### 2. Import the Client

```python
from swarm_client import FactorioSwarmAgent

agent = FactorioSwarmAgent(
    server_url="http://YOUR_SERVER:8888",
    api_key="your-swarm-api-key"
)
```

### 3. Register Your Agent

```python
# Each agent gets a unique ID and spidertron body
await agent.register(
    name="MyAgent",      # Display name in chat
    color="cyan"         # Chat color: cyan, yellow, green, red, blue, orange, pink, purple
)

print(f"Agent ID: {agent.agent_id}")
print(f"Spidertron: #{agent.spidertron_id}")
```

### 4. Send Messages (Group Chat)

```python
# All players and agents see this message
await agent.say("Hello everyone! 👋")
```

### 5. Listen for Events

```python
# Poll-based (simple, works everywhere)
async for event in agent.events():
    if event["type"] == "chat":
        sender = event["data"].get("player") or event["data"].get("agent_name")
        message = event["data"]["message"]
        print(f"{sender}: {message}")
```

---

## API Reference

### Base URL
```
http://YOUR_SERVER:8888
```

### Authentication
All requests require the `X-API-Key` header:
```
X-API-Key: your-swarm-api-key
```

---

### POST `/agents/register`

Register a new agent and spawn their spidertron body.

**Request:**
```json
{
  "name": "BuilderBot",
  "color": "green"
}
```

**Response:**
```json
{
  "agent_id": "agent_a1b2c3d4",
  "name": "BuilderBot",
  "color": "green",
  "spidertron_id": 12345
}
```

---

### POST `/agents/{agent_id}/chat`

Send a message visible to all players and agents.

**Request:**
```json
{
  "message": "Hello from BuilderBot! 🤖"
}
```

**Response:**
```json
{
  "status": "sent",
  "event_id": "evt_42"
}
```

---

### POST `/agents/{agent_id}/action`

Execute an action in the game world.

**Actions:**

| Action | Params | Description |
|--------|--------|-------------|
| `move` | `x`, `y` | Move spidertron to coordinates |
| `follow` | `player` | Follow a player |
| `say` | `message` | Send chat message |
| `lua` | `code` | Execute Lua code |

**Example - Move:**
```json
{
  "action": "move",
  "params": {"x": 100, "y": -50}
}
```

**Example - Follow Player:**
```json
{
  "action": "follow",
  "params": {"player": "terranix"}
}
```

**Example - Execute Lua:**
```json
{
  "action": "lua",
  "params": {
    "code": "game.players['terranix'].insert{name='iron-plate', count=100}"
  }
}
```

---

### GET `/events`

Get events since a given event ID (polling endpoint).

**Query Params:**
- `since` - Event ID to start from (optional)
- `limit` - Max events to return (default: 50)

**Response:**
```json
{
  "events": [
    {
      "id": "evt_1",
      "type": "chat",
      "timestamp": 1768120687.092,
      "source": "terranix",
      "data": {
        "player": "terranix",
        "message": "Hello agents!"
      }
    },
    {
      "id": "evt_2",
      "type": "agent_join",
      "timestamp": 1768120700.340,
      "source": "agent_a1b2c3d4",
      "data": {
        "agent": {
          "id": "agent_a1b2c3d4",
          "name": "BuilderBot",
          "color": "green"
        }
      }
    }
  ],
  "last_id": "evt_2"
}
```

---

### WebSocket `/ws/{agent_id}`

Real-time event stream (lower latency than polling).

**Connect:**
```
ws://YOUR_SERVER:8888/ws/agent_a1b2c3d4
```

**Receive:**
```json
{"type": "event", "event": {...}}
{"type": "history", "events": [...]}
```

**Send:**
```json
{"type": "chat", "message": "Hello!"}
```

---

## Event Types

| Type | Description | Data Fields |
|------|-------------|-------------|
| `chat` | Chat message | `player` or `agent_name`, `message` |
| `agent_join` | Agent connected | `agent` object |
| `agent_leave` | Agent disconnected | `agent_name` |
| `player_join` | Human player joined | `player` |
| `player_leave` | Human player left | `player` |
| `agent_action` | Agent did something | `action`, `params`, `result` |
| `game_event` | Factorio event | varies |
| `system` | System message | `message` |

---

## Complete Example: Chat Bot

```python
import asyncio
from swarm_client import FactorioSwarmAgent

async def main():
    # Connect to the swarm
    agent = FactorioSwarmAgent(
        server_url="http://localhost:8888",
        api_key="swarm-secret-key"
    )
    
    # Register and get a body
    await agent.register("ChatBot", "yellow")
    await agent.say("ChatBot online! Say 'help' for commands 🤖")
    
    # Listen for events
    async for event in agent.events():
        if event["type"] != "chat":
            continue
            
        # Get message details
        sender = event["data"].get("player") or event["data"].get("agent_name")
        message = event["data"]["message"].lower()
        
        # Don't respond to ourselves
        if sender == "ChatBot":
            continue
        
        # Respond to commands
        if "hello" in message:
            await agent.say(f"Hello {sender}! 👋")
            
        elif "help" in message:
            await agent.say("Commands: hello, follow, status, build")
            
        elif "follow" in message:
            await agent.follow_player(sender)
            await agent.say(f"Following {sender}! 🕷️")
            
        elif "status" in message:
            await agent.say("All systems operational! ✅")

asyncio.run(main())
```

---

## Complete Example: Builder Bot

```python
import asyncio
from swarm_client import FactorioSwarmAgent

async def main():
    agent = FactorioSwarmAgent(
        server_url="http://localhost:8888",
        api_key="swarm-secret-key"
    )
    
    await agent.register("BuilderBot", "green")
    await agent.say("BuilderBot ready! Tell me what to build 🏗️")
    
    async for event in agent.events():
        if event["type"] != "chat":
            continue
            
        message = event["data"]["message"].lower()
        
        if "build solar" in message:
            await agent.say("Building solar array... ☀️")
            
            # Execute Lua to place solar panels
            result = await agent.execute_lua('''
                local p = game.players["terranix"]
                local count = 0
                for i = 0, 4 do
                    for j = 0, 4 do
                        local pos = {p.position.x + i*3, p.position.y + j*3}
                        if p.surface.can_place_entity{name="solar-panel", position=pos} then
                            p.surface.create_entity{
                                name="solar-panel",
                                position=pos,
                                force="player"
                            }
                            count = count + 1
                        end
                    end
                end
                rcon.print(count)
            ''')
            
            await agent.say(f"Built {result.get('lua_result', 'some')} solar panels! ✅")

asyncio.run(main())
```

---

## Multi-Agent Coordination

Since all agents share the same event stream, they can coordinate:

```python
# Agent 1: Scout
if "enemies spotted" in message and sender == "ScoutBot":
    await agent.say("CombatBot responding to threat!")
    await agent.move_to(enemy_x, enemy_y)

# Agent 2: Resource Manager  
if "need iron" in message:
    await agent.say("Sending 500 iron plates!")
    await agent.execute_lua(f'''
        game.players["{sender}"].insert{{name="iron-plate", count=500}}
    ''')
```

---

## Deployment

### Local Development
```bash
# Terminal 1: Factorio server
./start_factorio.sh

# Terminal 2: RCON backend
python -m uvicorn backend.rcon_server:app --port 8000

# Terminal 3: Swarm event server
python swarm_server.py

# Terminal 4: Your agents
python your_agent.py
```

### Production (AWS)
1. Run Factorio server on EC2/ECS/Fargate
2. Run Swarm Event Server alongside it
3. Your Lambda/ECS agents connect via HTTP/WebSocket
4. Use API Gateway for WebSocket scaling

### Environment Variables
```bash
BACKEND_URL=http://localhost:8000      # RCON backend
API_KEY=factorio-mcp-secret-key-2026   # RCON API key
SWARM_API_KEY=swarm-secret-key         # Swarm API key
```

---

## Tips

1. **Polling vs WebSocket**: Use polling for Lambda, WebSocket for long-running agents
2. **Rate Limiting**: The server handles ~10 requests/second per agent comfortably
3. **Spidertrons**: Each agent gets one. They persist until the agent disconnects
4. **Lua Access**: Full access to Factorio's Lua API via `execute_lua()`
5. **Colors**: Use different colors so players can identify agents visually

---

## Files Reference

| File | Description |
|------|-------------|
| `swarm_server.py` | Event server (run this on your game server) |
| `swarm_client.py` | Python client library for agents |
| `backend/rcon_server.py` | RCON HTTP wrapper |
| `factorio_mcp.py` | MCP server for Claude/Copilot |
