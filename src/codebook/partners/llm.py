"""AI agents as partners and clue-givers: Claude Code headless (`claude -p`) and Codex (`codex exec`).

They see only what a player at the table sees (the words, the clue, and for a clue-giver the key
plus Codebook's ranked suggestions). They never get database credentials.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Sequence

from codebook.harness import engine
from codebook.partners import PartnerSpec

CLAUDE_MODELS = {"claude": "claude-haiku-5-5", "claude-sonnet": "claude-sonnet-5-5"}
GUESS_SCHEMA = {"type": "object", "properties": {"guesses": {"type": "array", "items": {"type": "string"}}},
                "required": ["guesses"], "additionalProperties": False}
CLUE_SCHEMA = {"type": "object", "properties": {"clue": {"type": "string"}, "count": {"type": "integer"}},
               "required": ["clue", "count"], "additionalProperties": False}

GUESS_PROMPT = """You are the guesser in a game of Codenames. Your partner gave a one-word clue and a number.
Words still on the board: {board}
Clue: {clue} {count}
List the board words your partner most likely means, best first, at most {count}. Use only words from the board.
Reply with only JSON: {{"guesses": ["WORD", ...]}}"""

CLUE_PROMPT = """You are the clue-giver (spymaster) in a game of Codenames, playing with partner "{partner}".
Your team's words: {team}
Avoid the opponent's words: {opponent}
Neutral words: {neutral}
The bomb (an instant loss if guessed): {assassin}
{suggestions}Give one English word as the clue (not a board word, not part of one) and how many of your team's
words it points to. Reply with only JSON: {{"clue": "word", "count": 2}}"""


class LLMError(RuntimeError):
    """The CLI failed, timed out, or replied without usable JSON."""


def _exe(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise LLMError(f"`{name}` CLI not found on PATH")
    return path


def run_claude(prompt: str, model: str, timeout: int = 180) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_CODE_"))}
    cmd = [_exe("claude"), "-p", prompt, "--model", model, "--setting-sources", "project",
           "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands",
           "--tools", "", "--output-format", "json"]
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(cmd, input="", capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, env=env, cwd=tmp)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"claude exited {proc.returncode}: {proc.stderr[-300:] or proc.stdout[-300:]}") from exc
    if data.get("is_error"):
        raise LLMError(f"claude error: {str(data.get('result'))[:300]}")
    return str(data.get("result", ""))


def run_codex(prompt: str, schema: dict, timeout: int = 300) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        schema_path, out_path = Path(tmp) / "schema.json", Path(tmp) / "out.txt"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        cmd = [_exe("codex"), "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
               "-c", 'model_reasoning_effort="low"', "--output-schema", str(schema_path),
               "-o", str(out_path), prompt]
        proc = subprocess.run(cmd, input="", capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout, cwd=tmp)
        if not out_path.exists():
            raise LLMError(f"codex exited {proc.returncode}: {proc.stderr[-300:]}")
        return out_path.read_text(encoding="utf-8")


def ask(agent: str, prompt: str, schema: dict) -> dict:
    """Send a prompt to an agent and return its JSON reply (one retry)."""
    last: Exception | None = None
    for _ in range(2):
        try:
            text = run_codex(prompt, schema) if agent == "codex" else run_claude(prompt, CLAUDE_MODELS[agent])
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                return json.loads(match.group(0))
            last = LLMError(f"no JSON in reply: {text[:200]}")
        except (LLMError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            last = exc
    raise LLMError(f"{agent}: {last}")


def parse_guesses(reply: dict, board: Sequence[str], limit: int) -> list[str]:
    live = {w.upper() for w in board if not w.startswith("*")}
    out: list[str] = []
    for g in reply.get("guesses", []):
        word = str(g).strip().upper()
        if word in live and word not in out:
            out.append(word)
    return out[:limit]


def partner(pid: str) -> PartnerSpec:
    engine()
    from players.guesser import Guesser  # noqa: PLC0415 - vendored package

    _exe("codex" if pid == "codex" else "claude")

    class AIGuesser(Guesser):
        def __init__(self):
            super().__init__()
            self.words, self.clue, self.num, self.queue = [], "", 0, None

        def set_board(self, words):
            self.words = words

        def set_clue(self, clue, num):
            self.clue, self.num, self.queue = clue, int(num), None

        def keep_guessing(self):
            return bool(self.queue)

        def get_answer(self):
            if self.queue is None:
                live = [w for w in self.words if not w.startswith("*")]
                prompt = GUESS_PROMPT.format(board=", ".join(live), clue=self.clue.upper(), count=self.num)
                try:
                    self.queue = parse_guesses(ask(pid, prompt, GUESS_SCHEMA), live, self.num)
                except LLMError:
                    self.queue = []
            while self.queue:
                word = self.queue.pop(0)
                if word in self.words:
                    return word
            return None

    AIGuesser.__name__ = f"{pid.title().replace('-', '')}Guesser"
    label = "Codex CLI (codex exec)" if pid == "codex" else f"Claude Code headless ({CLAUDE_MODELS[pid]})"
    return PartnerSpec(pid, "llm", label, lambda _w: True, AIGuesser)


def clue_chooser(agent: str, partner_id: str, *, with_suggestions: bool) -> Callable:
    """An AI clue-giver. With suggestions it sees Codebook's top options from the partner's memory."""

    def choose(board, options, rejected=()):
        def group(role):
            return ", ".join(w.upper() for w in board.with_role(role)) or "none"
        sugg = ""
        if with_suggestions and options:
            lines = [f"- {o.clue.upper()} {o.count}: aims at {', '.join(t.upper() for t in o.targets)}; "
                     f"expected {o.expected_hits:.1f} right; bomb risk {o.p_assassin:.0%}" for o in options[:8]]
            sugg = ("Suggestions from this partner's memory (Codebook), best first:\n" + "\n".join(lines) + "\n")
        if rejected:
            sugg += ("These clues were not allowed, choose a different one:\n"
                     + "\n".join(f"- {c.upper() or '(no answer)'}: {why}" for c, why in rejected) + "\n")
        prompt = CLUE_PROMPT.format(partner=partner_id, team=group("team"), opponent=group("opponent"),
                                    neutral=group("neutral"), assassin=group("assassin"), suggestions=sugg)
        try:
            reply = ask(agent, prompt, CLUE_SCHEMA)
            return str(reply["clue"]), int(reply["count"])
        except (LLMError, KeyError, TypeError, ValueError):
            return None

    return choose
