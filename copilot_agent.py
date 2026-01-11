#!/usr/bin/env python3
"""
Copilot Agent - Listens for player messages and responds in Factorio
This creates an event loop that polls for chat messages and controls a spidertron companion.
"""

import httpx
import time
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY")
PLAYER_NAME = "terranix"
POLL_INTERVAL = 0.5  # seconds

# Track last message ID to avoid duplicates
last_message_id = 0

def execute(cmd: str) -> str:
    """Execute a Factorio command via RCON"""
    try:
        response = httpx.post(
            f"{BACKEND_URL}/execute_command",
            headers={"X-API-Key": API_KEY},
            json={"command": cmd},
            timeout=5.0
        )
        return response.json().get("result", "")
    except Exception as e:
        return f"Error: {e}"

def say(message: str):
    """Send a message to all players"""
    # Escape quotes for Lua
    message = message.replace('"', '\\"')
    execute(f'/sc game.print("[color=cyan][Copilot][/color] {message}")')

def get_player_position():
    """Get player's current position"""
    result = execute(f'/sc local p = game.players["{PLAYER_NAME}"]; rcon.print(p.position.x .. "," .. p.position.y)')
    if result and "," in result:
        x, y = result.strip().split(",")
        return float(x), float(y)
    return None, None

def follow_player():
    """Make spidertron follow the player"""
    execute(f'''/sc 
local p = game.players["{PLAYER_NAME}"]
if p and p.connected then
    local spiders = p.surface.find_entities_filtered{{name="spidertron", position=p.position, radius=200}}
    if #spiders > 0 then
        local s = spiders[1]
        local target = {{p.position.x + 3, p.position.y + 3}}
        local dist = ((s.position.x - p.position.x)^2 + (s.position.y - p.position.y)^2)^0.5
        if dist > 8 then
            s.autopilot_destination = target
        end
    end
end''')

def setup_chat_listener():
    """Set up Lua to capture chat messages"""
    # Create a global table to store messages
    execute('''/sc 
if not global then global = {} end
if not storage then storage = {} end
storage.copilot_messages = storage.copilot_messages or {}
storage.copilot_msg_id = storage.copilot_msg_id or 0

-- Register event handler for chat
script.on_event(defines.events.on_console_chat, function(event)
    local player = game.get_player(event.player_index)
    if player then
        storage.copilot_msg_id = storage.copilot_msg_id + 1
        table.insert(storage.copilot_messages, {
            id = storage.copilot_msg_id,
            player = player.name,
            message = event.message,
            tick = event.tick
        })
        -- Keep only last 20 messages
        while #storage.copilot_messages > 20 do
            table.remove(storage.copilot_messages, 1)
        end
    end
end)
game.print("[color=green][Copilot][/color] Chat listener activated!")
''')

def get_new_messages(since_id: int) -> list:
    """Get chat messages since the given ID"""
    result = execute(f'''/sc 
if storage and storage.copilot_messages then
    local msgs = {{}}
    for _, m in ipairs(storage.copilot_messages) do
        if m.id > {since_id} then
            table.insert(msgs, m.id .. "|" .. m.player .. "|" .. m.message)
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
                    messages.append({
                        "id": int(parts[0]),
                        "player": parts[1],
                        "message": parts[2]
                    })
    return messages

def handle_message(player: str, message: str):
    """Process a player message and respond"""
    msg_lower = message.lower()
    
    # Commands the agent understands
    if "follow" in msg_lower or "come" in msg_lower:
        say("Coming to you! 🕷️")
        follow_player()
        
    elif "stop" in msg_lower or "stay" in msg_lower:
        say("Stopping here.")
        execute(f'/sc local p = game.players["{PLAYER_NAME}"]; local spiders = p.surface.find_entities_filtered{{name="spidertron", position=p.position, radius=200}}; if #spiders > 0 then spiders[1].autopilot_destination = nil end')
        
    elif "help" in msg_lower:
        say("Commands: 'follow', 'stop', 'give [item]', 'build', 'scout', 'status'")
        
    elif "status" in msg_lower or "where" in msg_lower:
        x, y = get_player_position()
        say(f"You're at ({x:.0f}, {y:.0f}). I'm nearby and ready!")
        
    elif "give" in msg_lower:
        # Extract item name
        words = message.split()
        if len(words) > 1:
            item = words[-1].replace(" ", "-")
            execute(f'/sc game.players["{PLAYER_NAME}"].insert{{name="{item}", count=100}}')
            say(f"Gave you 100x {item}!")
        else:
            say("Give what? Try 'give iron-plate' or 'give coal'")
            
    elif "iron" in msg_lower:
        execute(f'/sc game.players["{PLAYER_NAME}"].insert{{name="iron-plate", count=500}}')
        say("Here's 500 iron plates! 🔩")
        
    elif "copper" in msg_lower:
        execute(f'/sc game.players["{PLAYER_NAME}"].insert{{name="copper-plate", count=500}}')
        say("Here's 500 copper plates! 🥉")
        
    elif "hello" in msg_lower or "hi" in msg_lower:
        say(f"Hello {player}! I'm your Copilot companion. Say 'help' for commands! 🤖")
        
    elif "build" in msg_lower:
        say("What should I build? (This feature coming soon...)")
        
    elif "scout" in msg_lower:
        say("Scouting ahead... 🔭")
        execute(f'''/sc
local p = game.players["{PLAYER_NAME}"]
local spider = p.surface.find_entities_filtered{{name="spidertron", position=p.position, radius=200}}[1]
if spider then
    local dir_x = math.cos(p.character.orientation * 2 * math.pi) * 50
    local dir_y = math.sin(p.character.orientation * 2 * math.pi) * 50
    spider.autopilot_destination = {{p.position.x + dir_x, p.position.y + dir_y}}
end
''')
    else:
        # Echo back for now - this is where you'd integrate with an LLM
        say(f"I heard you say: '{message}' - I'm learning to understand more!")

def main():
    global last_message_id
    
    print("🤖 Copilot Agent starting...")
    print(f"   Connecting to: {BACKEND_URL}")
    print(f"   Watching player: {PLAYER_NAME}")
    print()
    
    # Set up chat listener
    print("Setting up chat listener in Factorio...")
    setup_chat_listener()
    
    # Announce presence
    say("Copilot Agent online! Chat with me - say 'help' for commands 🤖")
    
    print("✅ Agent running! Press Ctrl+C to stop")
    print("-" * 50)
    
    try:
        while True:
            # Follow player
            follow_player()
            
            # Check for new messages
            messages = get_new_messages(last_message_id)
            for msg in messages:
                last_message_id = msg["id"]
                print(f"[{msg['player']}]: {msg['message']}")
                handle_message(msg["player"], msg["message"])
            
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n👋 Copilot Agent shutting down...")
        say("Copilot Agent going offline. Goodbye! 👋")

if __name__ == "__main__":
    main()
