"""
Inter-Agent Message Bus

File-based JSON message bus for agent communication.
Messages are persisted to data/agent_messages/ and also kept in-memory for fast access.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class Message:
    """A single message between agents."""

    def __init__(self, from_agent: str, to_agent: str, msg_type: str,
                 payload: Dict, message_id: Optional[str] = None,
                 timestamp: Optional[str] = None):
        self.message_id = message_id or str(uuid.uuid4())
        self.from_agent = from_agent
        self.to_agent = to_agent
        self.type = msg_type
        self.payload = payload
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "message_id": self.message_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Message":
        return cls(
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            msg_type=data["type"],
            payload=data["payload"],
            message_id=data.get("message_id"),
            timestamp=data.get("timestamp"),
        )

    def __repr__(self) -> str:
        return f"Message({self.type}: {self.from_agent}->{self.to_agent})"


class MessageBus:
    """File-based + in-memory message bus for inter-agent communication."""

    # Valid message types
    VALID_TYPES = {
        "backtest_request",
        "backtest_result",
        "validation_request",
        "validation_result",
        "paper_trade_start",
        "paper_trade_result",
        "trade_update",
        "error",
        "correction",
        "reconciliation_request",
        "reconciliation_result",
    }

    def __init__(self, messages_dir: Optional[str] = None):
        self.messages_dir = Path(messages_dir or "data/agent_messages")
        self.messages_dir.mkdir(parents=True, exist_ok=True)
        self._messages: List[Message] = []
        self._subscribers: Dict[str, List[Callable]] = {}
        self._load_existing_messages()

    def _load_existing_messages(self):
        """Load previously persisted messages from disk."""
        for path in sorted(self.messages_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                self._messages.append(Message.from_dict(data))
            except Exception as e:
                logger.warning(f"Failed to load message {path}: {e}")

    def publish(self, from_agent: str, to_agent: str, msg_type: str,
                payload: Dict) -> Message:
        """Publish a message to the bus."""
        if msg_type not in self.VALID_TYPES:
            raise ValueError(f"Invalid message type: {msg_type}. Valid: {self.VALID_TYPES}")

        msg = Message(from_agent=from_agent, to_agent=to_agent,
                      msg_type=msg_type, payload=payload)

        # Persist to disk
        msg_path = self.messages_dir / f"{msg.message_id}.json"
        msg_path.write_text(json.dumps(msg.to_dict(), indent=2, default=str))

        # Keep in memory
        self._messages.append(msg)

        # Notify subscribers
        for subscriber_agent, callbacks in self._subscribers.items():
            if subscriber_agent == to_agent or subscriber_agent == "*":
                for cb in callbacks:
                    try:
                        cb(msg)
                    except Exception as e:
                        logger.error(f"Subscriber callback error: {e}")

        logger.info(f"Published: {msg}")
        return msg

    def subscribe(self, agent_name: str, callback: Callable):
        """Subscribe an agent to receive messages."""
        if agent_name not in self._subscribers:
            self._subscribers[agent_name] = []
        self._subscribers[agent_name].append(callback)

    def get_messages(self, to_agent: Optional[str] = None,
                     msg_type: Optional[str] = None,
                     since: Optional[str] = None) -> List[Message]:
        """Get messages, optionally filtered."""
        result = self._messages

        if to_agent:
            result = [m for m in result if m.to_agent == to_agent]
        if msg_type:
            result = [m for m in result if m.type == msg_type]
        if since:
            result = [m for m in result if m.timestamp > since]

        return result

    def get_latest(self, to_agent: str, msg_type: str) -> Optional[Message]:
        """Get the most recent message of a given type for an agent."""
        msgs = self.get_messages(to_agent=to_agent, msg_type=msg_type)
        return msgs[-1] if msgs else None

    def clear(self):
        """Clear all messages (in-memory and on disk)."""
        self._messages.clear()
        for path in self.messages_dir.glob("*.json"):
            path.unlink()
        logger.info("Message bus cleared")
