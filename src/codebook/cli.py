"""`codebook` command line: setup, play, train, eval, and inspect partner memories."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from codebook import config, keys
from codebook import cypher as C
from codebook.db import Db, DbError
from codebook.memory import Memory
from codebook.memory import now as memory_now

app = typer.Typer(help="Codebook: an AI clue-giver that remembers each partner, in FalkorDB.",
                  pretty_exceptions_show_locals=False,
                  no_args_is_help=True, add_completion=False)

COLOUR = {"team": "TEAM", "opponent": "opponent", "neutral": "neutral", "assassin": "BOMB"}


def _git_commit() -> str:
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10).stdout
        return out.stdout.strip() + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _memory() -> tuple[config.Settings, Memory]:
    settings = config.load()
    db = Db(settings)
    try:
        db.ping()
    except DbError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    return settings, Memory(db)


@app.command()
def setup(swow: Path = typer.Option(None, help="Path to SWOW-EN18.zip (default: data/SWOW-EN18.zip)"),
          source: str = typer.Option("swow", help="swow (default) | conceptnet (fallback if SWOW is unavailable)"),
          vectors: bool = typer.Option(False, help="Also build the GloVe/word2vec caches for the bot partners"),
          force: bool = typer.Option(False, help="Delete and rebuild everyone's memory")) -> None:
    """Build everyone's memory (codebook:population) from the Small World of Words data."""
    from codebook import loader  # noqa: PLC0415
    from codebook.harness import clue_wordlist, pool_words  # noqa: PLC0415

    settings, memory = _memory()
    if source == "conceptnet":
        path = settings.data_dir / "conceptnet" / loader.CONCEPTNET_FILE
        if not path.exists():
            typer.echo(f"error: {path} not found; download {loader.CONCEPTNET_URL}", err=True)
            raise typer.Exit(2)
        digest, dataset, version, min_count = loader.sha256(path), "ConceptNet", "5.7.0", 1
        if digest != loader.CONCEPTNET_SHA256:
            typer.echo(f"error: {path} has SHA-256 {digest}, expected {loader.CONCEPTNET_SHA256}", err=True)
            raise typer.Exit(2)
        vocab = loader.frequent_words(settings.data_dir / "vectors" / "glove-wiki-gigaword-300.gz")
        vocab |= set(clue_wordlist()) | set(pool_words())
        typer.echo(f"reading ConceptNet English assertions over {len(vocab)} words ...")
        links = loader.read_conceptnet(path, vocab)
    else:
        path = swow or settings.data_dir / loader.SWOW_FILE
        if not path.exists():
            typer.echo(f"error: {path} not found. Download SWOW-EN18 from {loader.SWOW_PAGE} (accept the "
                       f"CC BY-NC-ND licence) and save it as {settings.data_dir / loader.SWOW_FILE}", err=True)
            raise typer.Exit(2)
        digest, dataset, version, min_count = loader.sha256(path), "SWOW-EN18", "1.0", loader.MIN_COUNT
        if digest != loader.SWOW_SHA256:
            typer.echo(f"error: {path} has SHA-256 {digest}, expected {loader.SWOW_SHA256} (the published release)",
                       err=True)
            raise typer.Exit(2)
        typer.echo("reading the association-strength table ...")
        links = loader.read_links(path)
    if force:
        memory.db.delete_graph(keys.POPULATION)
    word_rows, link_rows = loader.select(links, clue_wordlist(), pool_words(), min_count=min_count)
    typer.echo(f"{len(links)} cue-response pairs read; loading {len(word_rows)} words, {len(link_rows)} links")
    loader.load(memory.db, word_rows, link_rows, dataset=dataset, version=version, digest=digest,
                min_count=min_count, progress=typer.echo)
    missing = [r[0] for r in word_rows if r[3] and not r[1]]
    typer.echo(f"done. board words that are not SWOW cues: {len(missing)}")
    if vectors:
        from codebook.partners import embedding  # noqa: PLC0415
        vocab = set(clue_wordlist()) | set(pool_words())
        for name in ("glove", "w2v"):
            embedding.build_cache(name, settings, vocab, log=typer.echo)


@app.command()
def status() -> None:
    """Show everyone's memory and every partner memory on the server."""
    _, memory = _memory()
    if not memory.db.exists(keys.POPULATION):
        typer.echo("everyone's memory: missing (run `codebook setup`)")
        raise typer.Exit(1)
    src = memory.db.ro_query(keys.POPULATION, C.SOURCE_GET, name="source_get").records()
    counts = memory.db.ro_query(keys.POPULATION, C.COUNTS, name="counts").records()[0]
    typer.echo(f"everyone's memory  {keys.POPULATION}: {counts['words']} words, {counts['links']} links, "
               f"{memory.db.memory_mb(keys.POPULATION)} MB, source {src[0] if src else '?'}")
    for pid in memory.partners():
        info = memory.info(pid)
        typer.echo(f"partner {pid:16s} {info.key}: {info.games} games, {info.turns} turns, "
                   f"{info.learned_words} links reweighted, style {info.style.as_dict()}, {info.memory_mb} MB")


@app.command()
def reset(partner: str) -> None:
    """Start a partner's memory over from everyone's memory (GRAPH.COPY)."""
    _, memory = _memory()
    typer.echo(f"reset {memory.reset_partner(partner)}")


@app.command()
def train(partner: str, games: int = 20, fresh: bool = True) -> None:
    """Play training boards with learning on, building this partner's memory."""
    from codebook.evaluate import train_partner  # noqa: PLC0415
    _memory()
    train_partner(partner, games, fresh=fresh, log=typer.echo)


@app.command()
def play(partner: str = typer.Option("glove", help="Who guesses"),
         seed: int = typer.Option(5000, help="Board seed (the engine deals the same board for a seed)"),
         memory_of: str = typer.Option("own", "--memory", help="own | everyone | <another partner id>"),
         learn: bool = typer.Option(False, help="Learn from this game (writes the partner's memory)"),
         clue_giver: str = typer.Option("codebook", help="codebook | claude | claude-sonnet | codex"),
         as_json: bool = typer.Option(False, "--json", help="Print the game record as JSON")) -> None:
    """Play one seeded game and print every clue, guess and block."""
    from codebook.harness import play as play_game  # noqa: PLC0415
    from codebook.partners import make_partner  # noqa: PLC0415
    from codebook.session import Session  # noqa: PLC0415

    settings, memory = _memory()
    memory.require_population()
    spec = make_partner(partner, settings=settings, memory=memory)
    if memory_of == "everyone":
        read_key = keys.POPULATION
    else:
        read_key = memory.ensure_partner(partner if memory_of == "own" else memory_of)
    write_key = read_key if learn and read_key != keys.POPULATION else None
    model = memory.model(read_key)
    chooser = None
    if clue_giver != "codebook":
        from codebook.partners.llm import clue_chooser  # noqa: PLC0415
        chooser = clue_chooser(clue_giver, partner, with_suggestions=True)

    out = sys.__stdout__  # the engine's prints are silenced during a game; ours go to the real terminal

    def show(event: dict) -> None:
        if as_json:
            return
        kind = event["kind"]
        if kind == "clue":
            o = event["option"]
            typer.echo(f"\nclue {event['turn']}: {o['clue'].upper()} {o['count']}  (by {event['proposed_by']}; "
                       f"aiming at {', '.join(o['targets'])}; expected {o['expected_hits']}, "
                       f"bomb risk {o['p_assassin']})", file=out)
        elif kind == "block":
            typer.echo(f"  BLOCKED {event['clue'].upper()}: {' -> '.join(event['path']) or 'model'} "
                       f"(strength {event['strength']}, bomb risk {event['p_assassin']})", file=out)
        elif kind == "graded":
            typer.echo("  guesses: " + ", ".join(f"{w} [{COLOUR[r]}]" for w, r in event["guesses"]), file=out)

    gid = f"{partner}-play-{seed}"
    result, session = play_game(lambda ev: Session(memory, read_key, model, gid, seed, "play", ev,
                                                    write_key=write_key, learn=learn, allowed=spec.knows,
                                                    chooser=chooser, chooser_name=clue_giver if chooser else "",
                                                    on_event=show), spec.guesser_class, seed, gid)
    if as_json:
        typer.echo(json.dumps(result.as_dict(), indent=1))
        return
    typer.echo(f"\n{'WON' if result.won else 'LOST'} in {result.turns} turns "
               f"(memory: {memory_of}, read {read_key}; bomb hit: {result.assassin})")


@app.command(name="eval")
def run_eval(partners: str = typer.Option("glove,w2v,persona-mirror,persona-leaper"),
             train_games: int = typer.Option(20, "--train"),
             test_games: int = typer.Option(100, "--test"),
             conditions: str = typer.Option("cold,warm,swap"),
             workers: int = typer.Option(6),
             ai: str = typer.Option("codex", help="AI clue-giver for plain/handover"),
             skip_train: bool = typer.Option(False, help="Reuse the partner memories already built"),
             run: str = typer.Option(None, "--run", help="Append to this run id instead of starting a new one"),
             snapshots: str = typer.Option("", help="Comma-separated game counts to snapshot during training")) -> None:
    """Train each partner's memory, then test every set-up on the same unseen boards."""
    from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415

    from codebook import evaluate as E  # noqa: PLC0415

    settings, memory = _memory()
    memory.require_population()
    pids = [p.strip() for p in partners.split(",") if p.strip()]
    conds = [c.strip() for c in conditions.split(",") if c.strip()]
    snaps = [int(s) for s in snapshots.split(",") if s.strip()]
    run_id = run or E.new_run_id()
    run_dir = settings.results_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = {"run": run_id, "partners": pids, "conditions": conds, "train": train_games, "test": test_games,
            "train_seeds": [E.TRAIN_SEED0, E.TRAIN_SEED0 + train_games - 1],
            "test_seeds": [E.TEST_SEED0, E.TEST_SEED0 + test_games - 1], "ai": ai, "snapshots": snaps,
            "skip_train": skip_train, "argv": sys.argv[1:], "commit": _git_commit(), "started": memory_now()}
    with (run_dir / "plan.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(plan) + "\n")
    typer.echo(f"run {run_id}: {plan}")
    sink = run_dir / "games.jsonl"
    if not skip_train:
        needed = sorted(set(pids) | {E.SWAPS[p] for p in pids if "swap" in conds})
        with ProcessPoolExecutor(max_workers=min(len(needed), workers)) as pool:
            futures = {pool.submit(E.train_partner, pid, train_games, snapshots=snaps): pid for pid in needed}
            for fut, pid in futures.items():
                rows = fut.result()
                with sink.open("a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps(row) + "\n")
                typer.echo(f"trained {pid}: {len(rows)} games")
    seeds = list(range(E.TEST_SEED0, E.TEST_SEED0 + test_games))
    rows = E.run_tests([(p, c) for p in pids for c in conds], seeds, workers=workers, sink=sink, ai=ai,
                       log=typer.echo)
    summary = E.summarize(rows)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    typer.echo(json.dumps(summary, indent=1))


@app.command()
def replay(partner: str = typer.Option("glove"), first: int = typer.Option(6000), games: int = typer.Option(20),
           memory_of: str = typer.Option("own", "--memory")) -> None:
    """Play frozen-memory games and print a fingerprint of every clue, pick and outcome.

    Run it, restart FalkorDB (`docker compose restart`), run it again in a new process: the same
    fingerprint means the partner's memory came back from FalkorDB, not from this process."""
    import hashlib  # noqa: PLC0415

    from codebook import evaluate as E  # noqa: PLC0415

    if memory_of not in ("own", "everyone"):
        typer.echo("error: --memory must be own or everyone", err=True)
        raise typer.Exit(2)
    _, memory = _memory()
    if memory_of == "own":
        info = memory.info(partner)
        typer.echo(f"memory {info.key}: {info.games} games, {info.turns} clues, {info.learned_words} links "
                   f"reweighted, style {info.style.as_dict()}")
    condition = "warm" if memory_of == "own" else "cold"
    rows = E.play_test_games(partner, condition, list(range(first, first + games)))
    transcript = [[r["seed"], r["turns"], r["won"], [[c["clue"], c["count"], c["guesses"]] for c in r["clues"]]]
                  for r in sorted(rows, key=lambda r: r["seed"])]
    digest = hashlib.sha256(json.dumps(transcript, sort_keys=True).encode()).hexdigest()
    for seed, turns, won, _ in transcript:
        typer.echo(f"  board {seed}: {'won' if won else 'lost'} in {turns} turns")
    typer.echo(f"fingerprint {digest[:16]} over {len(transcript)} games")


@app.command()
def report(run: str = typer.Argument(..., help="Run id under results/runs/"),
           title: str = typer.Option("Codebook results")) -> None:
    """Write results/<run>.md: the scorecard and the four promises, from a run's game log."""
    from codebook import evaluate as E  # noqa: PLC0415

    settings = config.load()
    run_dir = settings.results_dir / "runs" / run
    rows = [json.loads(line) for line in (run_dir / "games.jsonl").read_text(encoding="utf-8").splitlines() if line]
    _, memory = _memory()
    src = memory.db.ro_query(keys.POPULATION, C.SOURCE_GET, name="source_get").records()
    source = f"{src[0]['dataset']} {src[0]['version']}" if src else "unknown"
    text = E.report(rows, title=title, source=source)
    out = settings.results_dir / f"{run}.md"
    out.write_text(text, encoding="utf-8")
    (settings.results_dir / f"{run}.json").write_text(json.dumps(
        {"run": run, "source": source, **E.summarize(rows), "promises": E.promises(rows)}, indent=1), encoding="utf-8")
    typer.echo(text)


@app.command()
def ui(host: str = typer.Option(None), port: int = typer.Option(None)) -> None:
    """Open the live view: watch games, see every Cypher statement, or play as the guesser."""
    from codebook.web import serve  # noqa: PLC0415

    settings, _ = _memory()
    host, port = host or settings.ui_host, port or settings.ui_port
    typer.echo(f"Codebook live view on http://{host}:{port}")
    serve(host, port)


@app.command(name="export")
def export_memory(partner: str, out: Path = typer.Option(None, help="File to write (default: <partner>.codebook)")) -> None:
    """Write one partner's memory to a file you can carry to another FalkorDB server."""
    _, memory = _memory()
    path = out or Path(f"{partner}.codebook")
    data = memory.export_partner(partner)
    path.write_bytes(data)
    typer.echo(f"wrote {path} ({len(data) / 1e6:.1f} MB): {keys.partner_key(partner)}")


@app.command(name="import")
def import_memory(path: Path, as_partner: str = typer.Option(None, "--as", help="Partner id to restore as"),
                  replace: bool = typer.Option(False, help="Overwrite an existing memory with the same id")) -> None:
    """Restore a partner's memory from a file written by `codebook export`. Import only files you trust."""
    _, memory = _memory()
    try:
        key, header = memory.import_partner(path.read_bytes(), as_partner, replace=replace)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"restored {key}: {header['games']} games, {header['clues']} clues, exported {header['exported']}")


@app.command()
def acl(partner: str, revoke: bool = typer.Option(False, help="Delete the user instead")) -> None:
    """Create a database user that can read everyone's memory and touch only this partner's key."""
    from codebook import acl as A  # noqa: PLC0415

    _, memory = _memory()
    if revoke:
        A.revoke(memory.db, partner)
        typer.echo(f"deleted {keys.acl_user(partner)}")
        return
    memory.ensure_partner(partner)
    user, password = A.grant(memory.db, partner)
    typer.echo(f"user {user} may read {keys.POPULATION} and read/write {keys.partner_key(partner)} only.\n"
               f"CODEBOOK_DB_USER={user} CODEBOOK_DB_PASSWORD={password}   (shown once)")


@app.command()
def mcp() -> None:
    """Run the MCP server (stdio): agents use partner memories through tools, never the database."""
    from codebook.mcp_server import main  # noqa: PLC0415

    main()


if __name__ == "__main__":
    app()
