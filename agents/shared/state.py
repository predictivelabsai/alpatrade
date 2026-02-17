"""
Shared State Management for Multi-Agent System

Tracks agent statuses, portfolio state, and run history.
Persisted to data/agent_state.json.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/agent_state.json")


@dataclass
class AgentState:
    """State of a single agent."""
    agent_name: str
    status: str = "idle"  # idle, running, error, completed
    current_task: Optional[str] = None
    iteration_count: int = 0
    last_updated: Optional[str] = None
    error_message: Optional[str] = None

    def set_running(self, task: str):
        self.status = "running"
        self.current_task = task
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def set_completed(self):
        self.status = "completed"
        self.current_task = None
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def set_error(self, message: str):
        self.status = "error"
        self.error_message = message
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def set_idle(self):
        self.status = "idle"
        self.current_task = None
        self.iteration_count = 0
        self.error_message = None
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class PortfolioState:
    """Overall portfolio and orchestration state."""
    run_id: Optional[str] = None
    mode: str = "idle"  # idle, backtest, validate, paper_trade, full
    agents: Dict[str, AgentState] = field(default_factory=dict)
    backtest_results: List[Dict[str, Any]] = field(default_factory=list)
    best_config: Optional[Dict[str, Any]] = None
    validation_results: List[Dict[str, Any]] = field(default_factory=list)
    paper_trade_session: Optional[Dict[str, Any]] = None
    run_history: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def get_agent(self, name: str) -> AgentState:
        """Get or create agent state."""
        if name not in self.agents:
            self.agents[name] = AgentState(agent_name=name)
        return self.agents[name]

    def to_dict(self) -> Dict:
        data = {
            "run_id": self.run_id,
            "mode": self.mode,
            "agents": {k: asdict(v) for k, v in self.agents.items()},
            "backtest_results": self.backtest_results,
            "best_config": self.best_config,
            "validation_results": self.validation_results,
            "paper_trade_session": self.paper_trade_session,
            "run_history": self.run_history,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "PortfolioState":
        state = cls(
            run_id=data.get("run_id"),
            mode=data.get("mode", "idle"),
            backtest_results=data.get("backtest_results", []),
            best_config=data.get("best_config"),
            validation_results=data.get("validation_results", []),
            paper_trade_session=data.get("paper_trade_session"),
            run_history=data.get("run_history", []),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )
        for name, agent_data in data.get("agents", {}).items():
            state.agents[name] = AgentState(**agent_data)
        return state

    def save(self, path: Optional[Path] = None):
        """Persist state to JSON file."""
        target = path or STATE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        logger.debug(f"State saved to {target}")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PortfolioState":
        """Load state from JSON file, or return fresh state."""
        target = path or STATE_FILE
        if target.exists():
            try:
                data = json.loads(target.read_text())
                return cls.from_dict(data)
            except Exception as e:
                logger.warning(f"Failed to load state from {target}: {e}")
        return cls()
