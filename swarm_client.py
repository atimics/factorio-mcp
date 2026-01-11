#!/usr/bin/env python3
"""
Example Swarm Agent Client
==========================
Shows how an AI agent from your AWS swarm would connect to the Factorio Event Server.

This can run anywhere - AWS Lambda, ECS, local machine - and connect to the swarm.
"""

import asyncio
import aiohttp
import json
from typing import Optional, Callable

class FactorioSwarmAgent:
    """
    Client for connecting an AI agent to the Factorio Swarm.
    
    Usage:
        agent = FactorioSwarmAgent("http://your-server:8080", "swarm-api-key")
        await agent.register("MyBot", "cyan")
        
        # Listen for events
        async for event in agent.events():
            if event["type"] == "chat":
                # Respond to chat
                await agent.say(f"I heard: {event['data']['message']}")
    """
    
    def __init__(self, server_url: str, api_key: str):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.agent_id: Optional[str] = None
        self.agent_name: Optional[str] = None
        self.spidertron_id: Optional[int] = None
        self.headers = {"X-API-Key": api_key}
        
    async def register(self, name: str, color: str = "cyan") -> dict:
        """Register this agent with the swarm and spawn a spidertron body"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.server_url}/agents/register",
                headers=self.headers,
                json={"name": name, "color": color}
            ) as resp:
                data = await resp.json()
                self.agent_id = data["agent_id"]
                self.agent_name = data["name"]
                self.spidertron_id = data.get("spidertron_id")
                return data
    
    async def say(self, message: str):
        """Send a chat message visible to all players and agents"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.server_url}/agents/{self.agent_id}/chat",
                headers=self.headers,
                json={"message": message}
            ) as resp:
                return await resp.json()
    
    async def move_to(self, x: float, y: float):
        """Move spidertron body to coordinates"""
        return await self._action("move", {"x": x, "y": y})
    
    async def follow_player(self, player: str = "terranix"):
        """Follow a player"""
        return await self._action("follow", {"player": player})
    
    async def execute_lua(self, code: str):
        """Execute Lua code in Factorio"""
        return await self._action("lua", {"code": code})
    
    async def _action(self, action: str, params: dict) -> dict:
        """Execute an action"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.server_url}/agents/{self.agent_id}/action",
                headers=self.headers,
                json={"action": action, "params": params}
            ) as resp:
                return await resp.json()
    
    async def get_events(self, since: Optional[str] = None) -> list:
        """Poll for new events (for non-WebSocket usage)"""
        params = {}
        if since:
            params["since"] = since
            
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.server_url}/events",
                headers=self.headers,
                params=params
            ) as resp:
                data = await resp.json()
                return data["events"], data.get("last_id")
    
    async def events(self):
        """
        Async generator that yields events in real-time.
        Use this to listen for chat messages and game events.
        
        Example:
            async for event in agent.events():
                print(f"Got event: {event['type']}")
        """
        last_id = None
        while True:
            events, last_id = await self.get_events(last_id)
            for event in events:
                yield event
            await asyncio.sleep(0.5)
    
    async def connect_websocket(self, on_event: Callable):
        """
        Connect via WebSocket for real-time events.
        Lower latency than polling.
        
        Example:
            async def handle(event):
                print(f"Got: {event}")
            await agent.connect_websocket(handle)
        """
        import websockets
        
        uri = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
        uri = f"{uri}/ws/{self.agent_id}"
        
        async with websockets.connect(uri) as ws:
            async for message in ws:
                data = json.loads(message)
                if data["type"] == "event":
                    await on_event(data["event"])
                elif data["type"] == "history":
                    for event in data["events"]:
                        await on_event(event)


# ============== Example: Simple Chat Bot ==============

async def run_chat_bot():
    """Example bot that responds to chat messages"""
    
    agent = FactorioSwarmAgent(
        server_url="http://localhost:8888",
        api_key="swarm-secret-key"
    )
    
    # Register with the swarm
    print("Registering with swarm...")
    result = await agent.register("ChatBot", "yellow")
    print(f"Registered as {result['agent_id']} with spidertron #{result.get('spidertron_id')}")
    
    # Announce ourselves
    await agent.say("Hello! I'm ChatBot, here to help! 🤖")
    
    # Listen for events
    print("Listening for events...")
    async for event in agent.events():
        print(f"Event: {event['type']} from {event['source']}")
        
        if event["type"] == "chat":
            message = event["data"].get("message", "")
            player = event["data"].get("player") or event["data"].get("agent_name")
            
            # Don't respond to ourselves
            if player == agent.agent_name:
                continue
                
            # Simple responses
            if "hello" in message.lower():
                await agent.say(f"Hello {player}! 👋")
                
            elif "help" in message.lower():
                await agent.say("I can: follow you, scout areas, or just chat!")
                
            elif "follow" in message.lower():
                await agent.follow_player(player)
                await agent.say(f"Following {player}! 🕷️")


# ============== Example: Builder Bot ==============

async def run_builder_bot():
    """Example bot that helps with construction"""
    
    agent = FactorioSwarmAgent(
        server_url="http://localhost:8888", 
        api_key="swarm-secret-key"
    )
    
    await agent.register("BuilderBot", "green")
    await agent.say("BuilderBot online! Tell me what to build! 🏗️")
    
    async for event in agent.events():
        if event["type"] == "chat":
            msg = event["data"].get("message", "").lower()
            
            if "build" in msg and "solar" in msg:
                await agent.say("Building solar array... ☀️")
                # Execute Lua to place solar panels
                await agent.execute_lua('''
                    local p = game.players["terranix"]
                    for i = 0, 4 do
                        for j = 0, 4 do
                            p.surface.create_entity{
                                name="solar-panel",
                                position={p.position.x + i*3, p.position.y + j*3},
                                force="player"
                            }
                        end
                    end
                ''')
                await agent.say("Built 25 solar panels! ✅")


# ============== Example: Scout Bot ==============

async def run_scout_bot():
    """Example bot that scouts and reports"""
    
    agent = FactorioSwarmAgent(
        server_url="http://localhost:8888",
        api_key="swarm-secret-key"
    )
    
    await agent.register("ScoutBot", "orange")
    await agent.say("ScoutBot ready to explore! 🔭")
    
    async for event in agent.events():
        if event["type"] == "chat":
            msg = event["data"].get("message", "").lower()
            
            if "scout" in msg:
                await agent.say("Scouting the area...")
                
                # Move in a pattern
                for direction in [(50, 0), (0, 50), (-50, 0), (0, -50)]:
                    result = await agent.execute_lua(f'''
                        local p = game.players["terranix"]
                        rcon.print(p.position.x .. "," .. p.position.y)
                    ''')
                    if result.get("lua_result"):
                        x, y = map(float, result["lua_result"].split(","))
                        await agent.move_to(x + direction[0], y + direction[1])
                        await asyncio.sleep(3)
                
                await agent.say("Scouting complete! Area secure. ✅")


# ============== Run ==============

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        bot_type = sys.argv[1]
        if bot_type == "chat":
            asyncio.run(run_chat_bot())
        elif bot_type == "builder":
            asyncio.run(run_builder_bot())
        elif bot_type == "scout":
            asyncio.run(run_scout_bot())
    else:
        print("Usage: python swarm_client.py [chat|builder|scout]")
        asyncio.run(run_chat_bot())
