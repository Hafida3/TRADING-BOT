"""
Self-tuning: allows the LLM to adjust trading parameters within safe bounds.
Changes are written to .env, applied to the live config object immediately
(no restart required), and logged to memory.md.

Per-key cooldown: a parameter cannot be changed again within TUNE_COOLDOWN_HOURS
of its last change. Cooldown state is persisted to a JSON file so it survives
restarts. Rejected directives are logged with [TUNE_COOLDOWN].
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import config

_ENV_PATH      = Path(__file__).parent.parent.parent / ".env"
_MEMORY_PATH   = Path(__file__).parent.parent.parent / "memory.md"
_COOLDOWN_PATH = Path(__file__).parent.parent.parent / "tune_cooldowns.json"

TUNE_COOLDOWN_HOURS = 6

SAFE_BOUNDS: dict[str, tuple[float, float]] = {
    "BUY_THRESHOLD":   (0.42, 0.65),
    "SELL_THRESHOLD":  (0.35, 0.55),
    "STOP_LOSS_PCT":   (0.002, 0.012),
    "TAKE_PROFIT_PCT": (0.004, 0.024),
}

ALLOWED_PARAMS = set(SAFE_BOUNDS)


# ── Cooldown persistence ───────────────────────────────────────────────────────

def _load_cooldowns() -> dict[str, float]:
    """Return {key: last_change_unix_timestamp}. Returns {} on any read error."""
    try:
        if _COOLDOWN_PATH.exists():
            return json.loads(_COOLDOWN_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cooldowns(state: dict[str, float]) -> None:
    try:
        _COOLDOWN_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[Tuner] cooldown save failed: {exc}")


def _cooldown_remaining(key: str, state: dict[str, float]) -> float:
    """Seconds remaining on cooldown for key, or 0.0 if not in cooldown."""
    last = state.get(key)
    if last is None:
        return 0.0
    elapsed = time.time() - last
    remaining = TUNE_COOLDOWN_HOURS * 3600 - elapsed
    return max(0.0, remaining)


# ── Public API ─────────────────────────────────────────────────────────────────

def update_parameter(key: str, value: float, reason: str) -> tuple[bool, str]:
    """
    Validate, check cooldown, persist to .env, apply to live config, log to memory.md.
    Returns (success, message).
    """
    if key not in ALLOWED_PARAMS:
        return False, f"TUNE rejected: '{key}' not in whitelist"

    lo, hi = SAFE_BOUNDS[key]
    if not (lo <= value <= hi):
        return False, f"TUNE rejected: {key}={value} outside safe bounds [{lo}, {hi}]"

    old_val = getattr(config, key, None)
    if old_val == value:
        return False, f"TUNE skipped: {key} already {value}"

    # Cooldown check
    cooldowns = _load_cooldowns()
    remaining = _cooldown_remaining(key, cooldowns)
    if remaining > 0:
        hours_left = remaining / 3600
        msg = (
            f"[TUNE_COOLDOWN] {key} {old_val} → {value} REJECTED "
            f"— cooldown {hours_left:.1f}h remaining "
            f"(last change: {datetime.fromtimestamp(cooldowns[key], tz=timezone.utc).strftime('%H:%M UTC')})"
        )
        print(msg)
        return False, msg

    try:
        _write_env(key, value)
    except Exception as exc:
        return False, f"TUNE .env write failed: {exc}"

    # Apply immediately — no restart needed
    os.environ[key] = str(value)
    setattr(config, key, float(value))

    # Record timestamp for this key's cooldown
    cooldowns[key] = time.time()
    _save_cooldowns(cooldowns)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"- **[TUNE {date_str}]** {key}: {old_val} → {value} | {reason}\n"
    try:
        with _MEMORY_PATH.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    except Exception as exc:
        print(f"[Tuner] memory.md write failed: {exc}")

    msg = f"{key} {old_val} → {value} ({reason})"
    print(f"[Tuner] TUNE applied: {msg}")
    return True, msg


def _write_env(key: str, value: float) -> None:
    """Replace or append key=value in .env, preserving all other lines."""
    content = _ENV_PATH.read_text(encoding="utf-8") if _ENV_PATH.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        content = content.rstrip("\n") + f"\n{new_line}\n"
    _ENV_PATH.write_text(content, encoding="utf-8")


def parse_tune_directives(text: str) -> list[tuple[str, float, str]]:
    """
    Extract TUNE: KEY=value (reason) patterns from LLM response text.
    Returns list of (key, value, reason) tuples ready to pass to update_parameter().
    """
    pattern = re.compile(r'TUNE:\s*([A-Z_]+)\s*=\s*([\d.]+)\s*\(([^)]+)\)')
    results = []
    for m in pattern.finditer(text):
        key, val_str, reason = m.group(1), m.group(2), m.group(3)
        try:
            results.append((key, float(val_str), reason.strip()))
        except ValueError:
            pass
    return results
