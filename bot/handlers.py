"""
DriveSuite — aiogram message and callback handlers.
"""

from __future__ import annotations

import json
from typing import Any

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.fsm.context import FSMContext

from bot import state_machine
from bot.agent import process_message

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = Router(name="drivesuite")

# ---------------------------------------------------------------------------
# Conversation history store (in-memory for now; persist later if needed)
# ---------------------------------------------------------------------------

_conversations: dict[int, list[dict[str, str]]] = {}


def _get_history(user_id: int) -> list[dict[str, str]]:
    return _conversations.setdefault(user_id, [])


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """Send a welcome message with quick-action buttons."""
    user_id = message.from_user.id
    state_machine.set_state(user_id, state_machine.IDLE)
    _conversations[user_id] = []

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Search Movie", callback_data="cmd:search_movie"),
                InlineKeyboardButton(text="Search Series", callback_data="cmd:search_series"),
            ],
            [
                InlineKeyboardButton(text="Active Downloads", callback_data="cmd:list_downloads"),
                InlineKeyboardButton(text="Media Status", callback_data="cmd:media_status"),
            ],
            [
                InlineKeyboardButton(text="Help", callback_data="cmd:help"),
            ],
        ]
    )

    await message.answer(
        "Welcome to **DriveSuite**! \n\n"
        "I manage your home media stack. Search for movies and series, "
        "download episodes, monitor active transfers, and more.\n\n"
        "Just tell me what you want, or use the buttons below.",
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    """Send a help message with natural-language examples."""
    await message.answer(
        "**DriveSuite Help** \n\n"
        "You can ask me things like:\n\n"
        "- *\"Find The Matrix\"*\n"
        "- *\"Search for Breaking Bad\"*\n"
        "- *\"Show me the episodes of The Office season 2\"*\n"
        "- *\"Download The Mandalorian S01E01\"*\n"
        "- *\"Add Interstellar to my library\"*\n"
        "- *\"What's downloading right now?\"*\n"
        "- *\"Check the media stack status\"*\n"
        "- *\"Download a YouTube video\"*\n"
        "- *\"Browse books about space\"*\n\n"
        "I will always show you a plan before downloading anything, "
        "so you can confirm or cancel.\n\n"
        "Commands:\n"
        "/start — Reset and show quick actions\n"
        "/help — This message",
    )


# ---------------------------------------------------------------------------
# Plain-text message handler (the main interaction path)
# ---------------------------------------------------------------------------


@router.message(F.text)
async def handle_message(message: Message) -> None:
    """Process an incoming text message through the LLM agent."""
    user_id = message.from_user.id
    text = message.text.strip()

    if not text:
        return

    # Retrieve current state
    current_state = state_machine.get_state(user_id)
    history = _get_history(user_id)

    # Send a typing indicator
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Process through the agent
    result = await process_message(text, user_id, history, current_state)

    reply_text: str = result["reply"]
    new_state: str = result["new_state"]
    tool_calls = result.get("tool_calls")

    # Append to conversation history
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply_text})

    # Build inline buttons for AWAITING_CONFIRMATION
    reply_markup = None
    if new_state == state_machine.AWAITING_CONFIRMATION:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Confirm", callback_data="confirm"),
                    InlineKeyboardButton(text="Cancel", callback_data="cancel"),
                ]
            ]
        )

    await message.answer(reply_text, reply_markup=reply_markup)


# ---------------------------------------------------------------------------
# Callback query handler
# ---------------------------------------------------------------------------


@router.callback_query()
async def handle_callback(callback: CallbackQuery) -> None:
    """Handle inline button presses.

    - ``confirm`` / ``cancel`` — accept or reject a pending download plan.
    - ``cmd:...`` — quick-action buttons from the welcome screen.
    """
    user_id = callback.from_user.id
    data = callback.data

    if not data:
        await callback.answer()
        return

    await callback.answer()

    # ---- Quick-action commands ----
    if data.startswith("cmd:"):
        command = data[4:]
        await _handle_quick_action(callback, command)
        return

    # ---- Confirmation / cancellation ----
    if data == "confirm":
        plan = state_machine.get_pending_plan(user_id)
        if plan is None:
            await callback.message.edit_text("No pending plan to confirm.")
            return

        # Parse the plan and try to execute
        try:
            plan_obj = json.loads(plan)
            action = plan_obj.get("action")
        except (json.JSONDecodeError, KeyError):
            await callback.message.edit_text(
                "Sorry, I could not understand the saved plan. Please start over."
            )
            state_machine.clear_pending_plan(user_id)
            state_machine.set_state(user_id, state_machine.IDLE)
            return

        # Execute confirmed destructive action
        # (import here to avoid circular import at module level)
        from bot.tools import execute_tool

        kwargs = {k: v for k, v in plan_obj.items() if k != "action"}
        result = await execute_tool(action, **kwargs)

        state_machine.clear_pending_plan(user_id)
        state_machine.set_state(user_id, state_machine.DONE)

        await callback.message.edit_text(
            f"Confirmed! Plan executed:\n\n```\n{plan}\n```\n\n{result}"
        )
        return

    if data == "cancel":
        state_machine.clear_pending_plan(user_id)
        state_machine.set_state(user_id, state_machine.IDLE)
        await callback.message.edit_text("Plan cancelled. What else can I help with?")
        return

    # Fallback
    await callback.message.answer("Unknown action.")


async def _handle_quick_action(callback: CallbackQuery, command: str) -> None:
    """Process a quick-action button press by injecting a faux user message."""
    user_id = callback.from_user.id
    prompts: dict[str, str] = {
        "search_movie": "I want to search for a movie.",
        "search_series": "I want to search for a TV series.",
        "list_downloads": "What's downloading right now?",
        "media_status": "Check the media stack status.",
        "help": "/help",
    }

    prompt = prompts.get(command)
    if not prompt:
        await callback.message.answer(f"Unknown quick action: {command}")
        return

    # Treat it as a normal message
    current_state = state_machine.get_state(user_id)
    history = _get_history(user_id)

    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action="typing")

    result = await process_message(prompt, user_id, history, current_state)
    reply_text = result["reply"]
    new_state = result["new_state"]

    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": reply_text})

    reply_markup = None
    if new_state == state_machine.AWAITING_CONFIRMATION:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Confirm", callback_data="confirm"),
                    InlineKeyboardButton(text="Cancel", callback_data="cancel"),
                ]
            ]
        )

    await callback.message.answer(reply_text, reply_markup=reply_markup)
