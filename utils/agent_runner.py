"""
Process Manager for AlpaTrade Agents
Spawns background agents disconnected from the UI.
Tracks PIDs in `data/pids/`.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
PIDS_DIR = PROJECT_ROOT / "data" / "pids"
PIDS_DIR.mkdir(parents=True, exist_ok=True)
RUN_SCRIPT = PROJECT_ROOT / "run_agent.py"

def _get_pid_file(run_id: str) -> Path:
    return PIDS_DIR / f"{run_id}.json"

def spawn_agent(mode: str, config: dict, user_id: Optional[str] = None, account_id: Optional[str] = None) -> str:
    """
    Spawns a new background agent process.
    Returns the run_id.
    """
    run_id = str(uuid.uuid4())
    
    cmd = [
        sys.executable, str(RUN_SCRIPT),
        "--run-id", run_id,
        "--mode", mode,
        "--config", json.dumps(config)
    ]
    if user_id:
        cmd.extend(["--user-id", str(user_id)])
    if account_id:
        cmd.extend(["--account-id", str(account_id)])

    logger.info(f"Spawning background agent {run_id} ({mode})")
    
    # Use Popen to detach process
    if os.name == 'nt':
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        # DETACHED_PROCESS = 0x00000008
        creationflags = 0x00000008 | 0x00000200
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), creationflags=creationflags, close_fds=True)
    else:
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), start_new_session=True, close_fds=True)

    # Save PID file
    pid_data = {
        "run_id": run_id,
        "pid": proc.pid,
        "mode": mode,
        "user_id": user_id,
        "account_id": account_id,
        "started_at": time.time(),
        "config": config
    }
    _get_pid_file(run_id).write_text(json.dumps(pid_data))
    
    return run_id


def get_agent_status(run_id: str) -> Optional[Dict]:
    """Check if an agent is still running. Removes stale PID file if dead."""
    pid_file = _get_pid_file(run_id)
    if not pid_file.exists():
        return None
        
    try:
        data = json.loads(pid_file.read_text())
        pid = data.get("pid")
        if pid and psutil.pid_exists(pid):
            proc = psutil.Process(pid)
            if proc.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                pid_file.unlink()
                return None
            return data
        else:
            pid_file.unlink()
            return None
    except Exception as e:
        logger.error(f"Error checking agent status {run_id}: {e}")
        # Clean up corrupted file
        try:
            pid_file.unlink()
        except:
            pass
        return None


def get_all_running_agents(user_id: Optional[str] = None) -> List[Dict]:
    """Return a list of all currently running agents, optionally filtered by user_id."""
    running = []
    for pid_file in PIDS_DIR.glob("*.json"):
        run_id = pid_file.stem
        status = get_agent_status(run_id)
        if status:
            if user_id:
                if status.get("user_id") == str(user_id):
                    running.append(status)
            else:
                running.append(status)
    return running


def stop_agent(run_id: str) -> bool:
    """Stop a background agent process by run_id."""
    status = get_agent_status(run_id)
    if not status:
        return False
        
    pid = status.get("pid")
    if pid:
        try:
            if os.name == 'nt':
                # Windows
                os.kill(pid, signal.CTRL_BREAK_EVENT)
                time.sleep(1)
                if psutil.pid_exists(pid):
                   subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)])
            else:
                # Unix
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                if psutil.pid_exists(pid):
                    os.kill(pid, signal.SIGKILL)
            
            # Clean up pid file
            pid_file = _get_pid_file(run_id)
            if pid_file.exists():
                pid_file.unlink()
            return True
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.error(f"Error stopping agent {run_id} (PID {pid}): {e}")
            
    return False
