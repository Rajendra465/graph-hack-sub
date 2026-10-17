"""Live view: watch Codebook play, see every Cypher statement it runs, or play as the guesser.

Games run in background threads on the same unmodified engine. Every query a game runs is
tagged with that game and streamed to the page with its exact Cypher text and timing.
"""

from __future__ import annotations

import itertools
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from codebook import config, keys
from codebook import cypher as C
from codebook.board import BoardView
from codebook.db import Db, DbError, QueryEvent
from codebook.harness import board_for_seed, engine, play
from codebook.memory import Memory
from codebook.partners import ALL as PARTNER_IDS
from codebook.partners import make_partner
from codebook.session import Session
from codebook.spymaster import plan

STATIC = Path(__file__).resolve().parent / "static"
_current = threading.local()
HUMAN = "you"


@dataclass
class LiveGame:
    gid: str
    partner: str
    memory_of: str
    read_key: str
    seed: int
    mode: str
    learn: bool
    clue_giver: str
    delay: float
    words: list
    key: list
    events: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    status: str = "running"
    result: dict | None = None
    error: str = ""
    inbox: "queue.Queue[str | None]" = field(default_factory=queue.Queue)

    def add(self, event: dict) -> None:
        with self.lock:
            event["i"] = len(self.events)
            event["t"] = round(time.time(), 3)
            self.events.append(event)

    def since(self, i: int) -> list[dict]:
        with self.lock:
            return self.events[i:]


class LiveApp:
    def __init__(self, settings: config.Settings) -> None:
        self.settings = settings
        self.db = Db(settings)
        self.db.ping()
        self.memory = Memory(self.db)
        self.games: dict[str, LiveGame] = {}
        self.ids = itertools.count(1)
        self.specs: dict[str, object] = {}
        self.db.on_query(self._on_query)

    def _on_query(self, ev: QueryEvent) -> None:
        game = getattr(_current, "game", None)
        if game is not None:
            game.add({"kind": "query", "name": ev.name, "key": ev.key, "ms": round(ev.ms, 1), "rows": ev.rows,
                      "ro": ev.ro, "ok": ev.ok, "cypher": ev.cypher, "params": ev.params, "error": ev.error})

    def spec(self, pid: str):
        if pid not in self.specs:
            self.specs[pid] = make_partner(pid, settings=self.settings, memory=self.memory)
        return self.specs[pid]

    # ---------- games ----------
    def start(self, body: dict) -> LiveGame:
        partner = str(body.get("partner", "glove"))
        if partner != HUMAN and partner not in PARTNER_IDS:
            raise ValueError(f"unknown partner {partner}")
        memory_of = str(body.get("memory", "own"))
        seed = int(body.get("seed", 5000))
        if memory_of == "everyone":
            read_key = keys.POPULATION
        else:
            read_key = self.memory.ensure_partner(partner if memory_of == "own" else memory_of)
        words, key = board_for_seed(seed)
        game = LiveGame(f"live-{next(self.ids)}-{partner}-{seed}", partner, memory_of, read_key, seed,
                        str(body.get("mode", "watch")), bool(body.get("learn", False)),
                        str(body.get("clue_giver", "codebook")), float(body.get("delay", 1.0)), words, key)
        self.games[game.gid] = game
        threading.Thread(target=self._run, args=(game,), daemon=True, name=game.gid).start()
        return game

    def _guesser_class(self, game: LiveGame):
        if game.partner != HUMAN:
            return self.spec(game.partner).guesser_class, self.spec(game.partner).knows
        engine()
        from players.guesser import Guesser  # noqa: PLC0415 - vendored package

        class WebGuesser(Guesser):
            def __init__(self):
                super().__init__()
                self.words, self.left = [], 0

            def set_board(self, words):
                self.words = words

            def set_clue(self, clue, num):
                self.left = int(num) + 1

            def keep_guessing(self):
                return self.left > 0

            def get_answer(self):
                game.add({"kind": "your_turn", "left": self.left})
                word = game.inbox.get()
                if word is None:
                    return None
                self.left -= 1
                return word.upper()

        return WebGuesser, (lambda _w: True)

    def _run(self, game: LiveGame) -> None:
        _current.game = game
        try:
            guesser_class, knows = self._guesser_class(game)
            model = self.memory.model(game.read_key)
            write_key = game.read_key if game.learn and keys.partner_of(game.read_key) else None
            chooser = None
            if game.clue_giver != "codebook":
                from codebook.partners.llm import clue_chooser  # noqa: PLC0415
                chooser = clue_chooser(game.clue_giver, game.partner, with_suggestions=True)

            def on_event(ev: dict) -> None:
                game.add(ev)
                if ev["kind"] == "clue" and game.partner != HUMAN:
                    time.sleep(game.delay)

            def on_guess(word: str, role: str) -> None:
                game.add({"kind": "guess", "word": word, "role": role})
                if game.partner != HUMAN:
                    time.sleep(game.delay * 0.6)

            game.add({"kind": "start", "partner": game.partner, "memory_of": game.memory_of,
                      "read_key": game.read_key, "model": self.memory.model(game.read_key).style.as_dict()})
            result, session = play(lambda evs: Session(self.memory, game.read_key, model, game.gid, game.seed,
                                                       "live", evs, write_key=write_key, learn=game.learn,
                                                       allowed=knows, chooser=chooser,
                                                       chooser_name=game.clue_giver if chooser else "",
                                                       on_event=on_event),
                                   guesser_class, game.seed, game.gid, quiet=False, on_guess=on_guess)
            game.result = result.as_dict()
            game.status = "won" if result.won else "lost"
            game.add({"kind": "end", "won": result.won, "turns": result.turns, "assassin": result.assassin})
        except Exception as exc:  # noqa: BLE001 - report any failure to the page, loudly
            game.status, game.error = "error", f"{type(exc).__name__}: {exc}"
            game.add({"kind": "error", "error": game.error})
        finally:
            _current.game = None

    # ---------- views ----------
    def partners(self) -> list[dict]:
        out = []
        for pid in self.memory.partners():
            info = self.memory.info(pid)
            out.append({"id": pid, "key": info.key, "games": info.games, "turns": info.turns,
                        "learned_links": info.learned_words, "style": info.style.as_dict(), "mb": info.memory_mb})
        return out

    def memory_view(self, pid: str) -> dict:
        key = keys.partner_key(pid)
        if not self.db.exists(key):
            raise DbError(f"no memory for {pid}")
        info = self.memory.info(pid)
        links = self.db.ro_query(key, C.LEARNED_LINKS, {"limit": 40}, name="learned_links").records()
        bias = sorted(self.db.ro_query(key, C.BIAS_GET, name="bias_get").rows, key=lambda r: -abs(r[1]))[:24]
        return {"id": pid, "key": key, "games": info.games, "turns": info.turns, "mb": info.memory_mb,
                "style": info.style.as_dict(), "learned_links": info.learned_words, "links": links,
                "bias": [{"word": w, "bias": round(b, 3)} for w, b in bias]}

    def suggest(self, seed: int, memories: list[str]) -> dict:
        words, key = board_for_seed(seed)
        board = BoardView.from_harness(words, key)
        out = {"board": board.words, "roles": board.roles, "by_memory": {}}
        for mem in memories:
            read_key = keys.POPULATION if mem == "everyone" else keys.partner_key(mem)
            model = self.memory.model(read_key)
            table = self.memory.features(read_key, board, model)
            options = plan(board, table.rows, model, seed=seed)[:5]
            out["by_memory"][mem] = [o.as_dict() for o in options]
        return out


def create_app(settings: config.Settings | None = None) -> Starlette:
    live = LiveApp(settings or config.load())

    def ok(data, status: int = 200) -> JSONResponse:
        return JSONResponse(data, status_code=status)

    async def index(_request: Request):
        return FileResponse(STATIC / "index.html")

    def partners(_request: Request):
        return ok({"partners": live.partners(), "available": list(PARTNER_IDS) + [HUMAN]})

    def memory_view(request: Request):
        try:
            return ok(live.memory_view(request.path_params["pid"]))
        except (DbError, ValueError) as exc:
            return ok({"error": str(exc)}, 404)

    async def new_game(request: Request):
        body = await request.json()
        try:
            game = live.start(body)
        except (DbError, ValueError, OSError) as exc:
            return ok({"error": str(exc)}, 400)
        return ok({"game": game.gid, "words": [w.lower() for w in game.words], "key": game.key,
                   "read_key": game.read_key})

    def game_state(request: Request):
        game = live.games.get(request.path_params["gid"])
        if game is None:
            return ok({"error": "no such game"}, 404)
        since = int(request.query_params.get("since", 0))
        return ok({"status": game.status, "error": game.error, "events": game.since(since),
                   "result": game.result})

    async def guess(request: Request):
        game = live.games.get(request.path_params["gid"])
        if game is None:
            return ok({"error": "no such game"}, 404)
        body = await request.json()
        word = body.get("word")
        game.inbox.put(str(word).lower() if word else None)
        return ok({"queued": word})

    def cypher_texts(_request: Request):
        return ok({name: text.strip() for name, text in C.ALL.items()})

    def suggest(request: Request):
        seed = int(request.query_params.get("seed", 5000))
        mems = [m for m in request.query_params.get("memories", "everyone").split(",") if m]
        try:
            return ok(live.suggest(seed, mems))
        except DbError as exc:
            return ok({"error": str(exc)}, 400)

    routes = [
        Route("/", index),
        Route("/api/partners", partners),
        Route("/api/memory/{pid}", memory_view),
        Route("/api/game", new_game, methods=["POST"]),
        Route("/api/game/{gid}", game_state),
        Route("/api/game/{gid}/guess", guess, methods=["POST"]),
        Route("/api/cypher", cypher_texts),
        Route("/api/suggest", suggest),
    ]
    return Starlette(routes=routes)


def serve(host: str, port: int) -> None:
    import uvicorn  # noqa: PLC0415

    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # the engine prints boards; keep stderr for logs
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
