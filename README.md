# drivesuite-agent

The brain of DriveSuite — a conversational AI agent that controls your home media stack via natural language.

## Architecture

```
Telegram message → aiogram handler → State Machine check → LLM (DeepSeek Pro)
                                    ↓
                              MCP client → drivesuite-mcp servers → Sonarr/Radarr/etc.
```

## Stack

- **aiogram 3** — async Telegram bot framework
- **Anthropic SDK** — LLM interface (DeepSeek via /anthropic endpoint)
- **State Machine** — SQLite-backed, 5 states (IDLE → BROWSING → AWAITING_CONFIRMATION → DOWNLOADING → DONE)
- **MCP Client** — discovers and calls tools from drivesuite-mcp servers
- **Intent Preview** — every download requires explicit user confirmation

## Project Structure

```
bot/
├── __init__.py
├── main.py              # aiogram dispatcher, polling loop
├── state_machine.py     # Per-user conversation state (SQLite)
├── agent.py             # LLM interface + system prompt
├── mcp_client.py        # MCP client for tool discovery
├── handlers.py          # Telegram message + callback handlers
└── tools.py             # Tool definitions for the LLM
```

## Conversation Flow

```
User: "I want Cowboy Bebop season 1 first 5 episodes"
  → State: IDLE → BROWSING
  → LLM searches Sonarr via MCP
  → Bot shows results with episode picker

User: [taps First 5]
  → State: BROWSING → AWAITING_CONFIRMATION
  → Bot shows plan: ~12GB, Jellyfin → TV → Cowboy Bebop → S01
  → [Confirm] [Cancel]

User: [Confirm]
  → State: AWAITING_CONFIRMATION → DOWNLOADING
  → LLM triggers episode downloads via MCP
  → Bot notifies as each episode completes
```

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with TELEGRAM_BOT_TOKEN, DEEPSEEK_DRIVESUITE_API_KEY
python -m bot.main
```
