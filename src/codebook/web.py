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
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from codebook import config, keys
from codebook import cypher as C
from codebook.board import BoardView
from codebook.db import Db, DbError, QueryEvent
from codebook.evaluate import benchmark_game_id
from codebook.graphview import GraphRequest, clue_graph, parse_graph_request, parse_turn
from codebook.harness import board_for_seed, engine, play
from codebook.memory import Memory
from codebook.partners import ALL as PARTNER_IDS
from codebook.partners import make_partner
from codebook.replay import live_condition, logged_chooser, logged_game, same_moves
from codebook.session import Session, TurnLimit
from codebook.spymaster import plan

STATIC = Path(__file__).resolve().parent / "static"
_current = threading.local()
HUMAN = "you"
CLUE_GIVERS = ("codebook", "claude", "claude-sonnet", "codex")
MAX_RUNNING = 4          # games playing at once
MAX_KEPT = 50            # finished games kept for the page
HUMAN_WAIT_S = 300       # an unanswered human turn ends the game
MAX_SEED = 10**9


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
    condition: str | None = None    # the benchmark set-up this game repeats, if any (see codebook.replay)
    logged: dict | None = None      # that set-up's logged game on this board
    replay: bool = False            # an AI clue-giver's clues come from `logged`
    matches_log: bool | None = None  # at the end: did the live game make the logged game's moves?

    @property
    def benchmark_game(self) -> str | None:
        return benchmark_game_id(self.partner, self.condition, self.seed) if self.logged else None

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
        self.running = threading.BoundedSemaphore(MAX_RUNNING)
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
            raise ValueError(f"unknown partner {partner!r}")
        memory_of = str(body.get("memory", "own"))
        learn = body.get("learn") is True
        clue_giver = str(body.get("clue_giver", "codebook"))
        if clue_giver not in CLUE_GIVERS:
            raise ValueError(f"unknown clue-giver {clue_giver!r}")
        try:
            seed = int(body.get("seed", 5000))
            delay = min(3.0, max(0.0, float(body.get("delay", 1.0))))
        except (TypeError, ValueError) as exc:
            raise ValueError("seed and delay must be numbers") from exc
        if not 0 <= seed <= MAX_SEED:
            raise ValueError(f"seed must be between 0 and {MAX_SEED}")
        if learn and memory_of != "own":
            raise ValueError("learning writes only to the partner's own memory")
        if memory_of not in ("everyone", "own"):
            read_key = keys.partner_key(memory_of)  # validates the id
            if not self.db.exists(read_key):
                raise ValueError(f"no memory for {memory_of!r}")
        replay = body.get("replay") is True
        condition = live_condition(partner, memory_of, clue_giver, learn=learn, replay=replay)
        if replay and condition != "handover":
            raise ValueError("a replay takes an AI clue-giver's clues from the benchmark log: choose an AI "
                             "clue-giver, the partner's own memory, and learning off")
        logged = self._logged(partner, condition, seed, clue_giver, required=replay)
        if not self.running.acquire(blocking=False):
            raise OverflowError(f"{MAX_RUNNING} games are already running; try again shortly")
        try:  # from here on a failure must give the slot back
            if memory_of == "everyone":
                read_key = keys.POPULATION
            elif memory_of == "own":
                read_key = self.memory.ensure_partner(partner)
            words, key = board_for_seed(seed)
            game = LiveGame(f"live-{next(self.ids)}-{partner}-{seed}", partner, memory_of, read_key, seed,
                            str(body.get("mode", "watch")), learn, clue_giver, delay, words, key,
                            condition=condition if logged else None, logged=logged, replay=replay)
            self.games[game.gid] = game
            for old in [g for g in list(self.games)[:-MAX_KEPT] if self.games[g].status != "running"]:
                self.games.pop(old, None)
            threading.Thread(target=self._run, args=(game,), daemon=True, name=game.gid).start()
        except BaseException:
            self.running.release()
            raise
        return game

    def _logged(self, partner: str, condition: str | None, seed: int, clue_giver: str, *,
                required: bool) -> dict | None:
        """The benchmark game a live game repeats. Only a replay needs one; other games just play live."""
        if condition is None:
            return None
        try:
            row = logged_game(self.settings.results_dir, partner, condition, seed, clue_giver)
        except ValueError:
            if required:
                raise
            return None
        if required and row is None:
            raise ValueError(f"no game {benchmark_game_id(partner, condition, seed)} in the latest run's log")
        return row

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
                try:
                    word = game.inbox.get(timeout=HUMAN_WAIT_S)
                except queue.Empty as exc:
                    raise TurnLimit(f"{game.gid}: no answer for {HUMAN_WAIT_S} s") from exc
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
            chooser, chooser_name = None, ""
            if game.replay:
                chooser, chooser_name = logged_chooser(game.logged, game.clue_giver), f"{game.clue_giver} (from the log)"
            elif game.clue_giver != "codebook":
                from codebook.partners.llm import clue_chooser  # noqa: PLC0415
                chooser, chooser_name = clue_chooser(game.clue_giver, game.partner, with_suggestions=True), game.clue_giver
            # The game id seeds Codebook's sampling: a benchmark set-up reuses the logged game's id.
            session_id = game.benchmark_game or game.gid

            def on_event(ev: dict) -> None:
                game.add(ev)
                if ev["kind"] == "clue" and game.partner != HUMAN:
                    time.sleep(game.delay)

            def on_guess(word: str, role: str) -> None:
                game.add({"kind": "guess", "word": word, "role": role})
                if game.partner != HUMAN:
                    time.sleep(game.delay * 0.6)

            game.add({"kind": "start", "partner": game.partner, "memory_of": game.memory_of,
                      "read_key": game.read_key, "model": self.memory.model(game.read_key).style.as_dict(),
                      "benchmark_game": game.benchmark_game, "replay": game.replay})
            result, session = play(lambda evs: Session(self.memory, game.read_key, model, session_id, game.seed,
                                                       game.condition or "live", evs, write_key=write_key,
                                                       learn=game.learn, allowed=knows, chooser=chooser,
                                                       chooser_name=chooser_name, on_event=on_event),
                                   guesser_class, game.seed, session_id, quiet=False, on_guess=on_guess)
            game.result = result.as_dict()
            if game.logged is not None:  # a changed memory (a learning game since) makes a replay differ
                game.matches_log = same_moves(game.result.get("clues", []), game.logged.get("clues", []))
            game.status = "won" if result.won else "lost"
            game.add({"kind": "end", "won": result.won, "turns": result.turns, "assassin": result.assassin,
                      "matches_log": game.matches_log})
        except Exception as exc:  # noqa: BLE001 - report any failure to the page, loudly
            game.status, game.error = "error", f"{type(exc).__name__}: {exc}"
            game.add({"kind": "error", "error": game.error})
        finally:
            _current.game = None
            self.running.release()

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
        if len(memories) > 5:
            raise ValueError("compare at most 5 memories")
        words, key = board_for_seed(seed)
        board = BoardView.from_harness(words, key)
        out = {"board": board.words, "roles": board.roles, "by_memory": {}}
        for mem in memories:
            read_key = keys.POPULATION if mem == "everyone" else keys.partner_key(mem)
            if not self.db.exists(read_key):
                raise ValueError(f"no memory for {mem!r}")
            model = self.memory.model(read_key)
            table = self.memory.features(read_key, board, model)
            options = plan(board, table.rows, model, seed=seed)[:5]
            out["by_memory"][mem] = [o.as_dict() for o in options]
        return out

    # ---------- the 3D memory graph ----------
    def game_graph(self, gid: str, turn: int | None) -> dict:
        """The memory around one of a game's clues, with the board as it stood when the clue was given."""
        game = self.games.get(gid)
        if game is None:
            raise LookupError("no such game")
        events = game.since(0)
        clues = [e for e in events if e.get("kind") == "clue" and (turn is None or e.get("turn") == turn)]
        if not clues:
            raise LookupError("no clue yet" if turn is None else f"no clue for turn {turn}")
        clue = clues[-1]
        revealed = {e["word"] for e in events if e.get("kind") == "guess" and e["i"] < clue["i"]}
        board = BoardView.from_harness(game.words, game.key)
        previous = getattr(_current, "game", None)
        _current.game = game  # the graph's queries join this game's Live Cypher feed
        try:
            graph = clue_graph(self.memory, game.read_key, board.words, board.roles, revealed, clue["clue"])
        finally:
            _current.game = previous
        return {**graph, "turn": clue["turn"]}

    def board_graph(self, req: GraphRequest) -> dict:
        """The memory around a clue on a seeded board: the given clue, or this memory's top suggestion."""
        words, key = board_for_seed(req.seed)
        board = BoardView.from_harness(words, key)
        read_key = keys.POPULATION if req.memory_of == "everyone" else keys.partner_key(req.memory_of)
        if not self.db.exists(read_key):
            raise ValueError(f"no memory for {req.memory_of!r}")
        clue = req.clue or self._top_clue(read_key, board, req.seed)
        return {**clue_graph(self.memory, read_key, board.words, board.roles, set(), clue), "seed": req.seed}

    def _top_clue(self, read_key: str, board: BoardView, seed: int) -> str:
        model = self.memory.model(read_key)
        options = plan(board, self.memory.features(read_key, board, model).rows, model, seed=seed)
        if not options:
            raise LookupError("this memory has no clue for this board")
        return options[0].clue


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
        if not isinstance(body, dict):
            return ok({"error": "expected a JSON object"}, 400)
        try:
            game = live.start(body)
        except OverflowError as exc:
            return ok({"error": str(exc)}, 429)
        except (DbError, ValueError, OSError) as exc:
            return ok({"error": str(exc)}, 400)
        return ok({"game": game.gid, "words": [w.lower() for w in game.words], "key": game.key,
                   "read_key": game.read_key, "benchmark_game": game.benchmark_game, "replay": game.replay})

    def game_state(request: Request):
        game = live.games.get(request.path_params["gid"])
        if game is None:
            return ok({"error": "no such game"}, 404)
        since = int(request.query_params.get("since", 0))
        return ok({"status": game.status, "error": game.error, "events": game.since(since),
                   "result": game.result, "partner": game.partner, "seed": game.seed, "read_key": game.read_key,
                   "words": [w.lower() for w in game.words], "key": game.key,
                   "benchmark_game": game.benchmark_game, "replay": game.replay, "matches_log": game.matches_log})

    async def guess(request: Request):
        game = live.games.get(request.path_params["gid"])
        if game is None:
            return ok({"error": "no such game"}, 404)
        body = await request.json()
        word = body.get("word") if isinstance(body, dict) else None
        if word is not None and (not isinstance(word, str) or word.upper() not in game.words):
            return ok({"error": "not a word on this board"}, 400)
        game.inbox.put(word.lower() if word else None)
        return ok({"queued": word})

    def cypher_texts(_request: Request):
        return ok({name: text.strip() for name, text in C.ALL.items()})

    def suggest(request: Request):
        try:
            seed = int(request.query_params.get("seed", 5000))
            mems = [m for m in request.query_params.get("memories", "everyone").split(",") if m]
            return ok(live.suggest(seed, mems))
        except (DbError, ValueError) as exc:
            return ok({"error": str(exc)}, 400)

    def graph_response(build):
        try:
            return ok(build())
        except DbError:
            return ok({"error": "the memory database is unavailable"}, 503)
        except LookupError as exc:
            return ok({"error": str(exc)}, 404)
        except ValueError as exc:
            return ok({"error": str(exc)}, 400)

    def game_graph(request: Request):
        return graph_response(lambda: live.game_graph(request.path_params["gid"],
                                                      parse_turn(request.query_params.get("turn"))))

    def board_graph(request: Request):
        return graph_response(lambda: live.board_graph(parse_graph_request(request.query_params)))

    routes = [
        Route("/", index),
        Route("/api/partners", partners),
        Route("/api/memory/{pid}", memory_view),
        Route("/api/game", new_game, methods=["POST"]),
        Route("/api/game/{gid}", game_state),
        Route("/api/game/{gid}/guess", guess, methods=["POST"]),
        Route("/api/cypher", cypher_texts),
        Route("/api/suggest", suggest),
        Route("/api/game/{gid}/graph", game_graph),
        Route("/api/graph", board_graph),
        Mount("/static", app=StaticFiles(directory=STATIC), name="static"),
    ]
    host, port = live.settings.ui_host, live.settings.ui_port
    allowed_hosts = sorted({"127.0.0.1", "localhost", host})
    origins = {f"http://{h}:{port}" for h in allowed_hosts}

    class SameOriginJson(BaseHTTPMiddleware):
        """Refuse cross-site writes: a POST must be JSON and come from this page."""

        async def dispatch(self, request, call_next):
            if request.method == "POST":
                origin = request.headers.get("origin")
                if origin and origin not in origins:
                    return JSONResponse({"error": "cross-origin request refused"}, status_code=403)
                if not request.headers.get("content-type", "").startswith("application/json"):
                    return JSONResponse({"error": "expected application/json"}, status_code=415)
            return await call_next(request)

    return Starlette(routes=routes, middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts),
                                                Middleware(SameOriginJson)])


def serve(host: str, port: int) -> None:
    import uvicorn  # noqa: PLC0415

    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # the engine prints boards; keep stderr for logs
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
