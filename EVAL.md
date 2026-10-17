# Evaluation plan (written before the first real test run)

This file is committed before any test board is played with real word data. The git history
shows its timestamp. Results are reported against it, including every promise that fails.

## Who keeps score

The unmodified Codenames AI Competition engine (MIT, `src/codebook/engine/`, checksums in
`tests/unit/test_engine_unmodified.py`) deals every board from a seed, checks every guess against
the hidden key, and counts turns. A lost game (bomb, or all 7 opponent words found) counts 25 turns,
the engine's own rule. Codebook never edits the engine's outcome.

## Boards

- Training boards: seeds 1000-1019 (20 games per partner, learning on).
- Test boards: seeds 5000-5199 (200 games) for the bot and planted partners; seeds 5000-5039
  (40 games) for set-ups that call an AI model on every turn. Memories are frozen during tests.
- Training and test seeds never overlap. Every set-up for a partner plays the same test boards.

## Partners (who guesses)

| id | what it is |
|---|---|
| `glove` | the competition's own GloVe guesser, unmodified (glove.6B.300d) |
| `w2v` | the competition's own word2vec guesser, unmodified (GoogleNews 300d) |
| `persona-mirror`, `persona-leaper` | planted test partners with known quirks (control) |
| `claude` | Claude Haiku through `claude -p` (headless Claude Code) |
| `codex` | Codex CLI through `codex exec`, if its login works on the day |

## Set-ups (who gives clues, with which memory)

| set-up | clue-giver | memory read |
|---|---|---|
| plain AI | an AI model (Codex, or Claude Sonnet if Codex is unavailable) with the board only | none |
| everyone's memory | Codebook | `codebook:population` only (also the no-partner-memory baseline) |
| your memory | Codebook | `codebook:partner:<id>` after 20 training games |
| wrong memory | Codebook | another partner's memory: glove/w2v, mirror/leaper, claude/glove |
| handover | the same AI model as "plain AI", choosing from Codebook's suggestions | `codebook:partner:<id>` |

The block (no clue whose chain reaches the bomb in this memory) applies to every Codebook set-up and
to the handover. It does not apply to the plain AI, which has no graph.

## Measures

Turns to finish (loss = 25), games won, bomb hits, clean clues (every pick for the clue was a team
word), team words per clue. Differences are paired by board: mean of (A - B) over shared seeds, with a
95% bootstrap interval (10,000 resamples, seed 7). "A beats B" means the whole interval is below zero.

## Four promises

1. **Your memory beats everyone's memory**: kept if "your memory" beats "everyone's memory" on turns
   for at least one of the two competition bots (glove, w2v).
2. **Your memory beats the wrong memory**: kept if "your memory" beats "wrong memory" on turns for at
   least one of the two competition bots.
3. **The handover keeps the score**: kept if, with the GloVe partner, the AI clue-giver using GloVe's
   memory (handover) beats the same AI without memory (plain AI) on turns.
4. **No more bomb hits than the plain AI**: kept if, with the GloVe partner, Codebook with "your memory"
   hits the bomb no more often than the plain AI on the same 40 boards.

**Stop rule.** If promise 1 fails for both competition bots, the partner-memory claim has failed; the
README says so in its first paragraph, and the planted partners are reported as a control only.

## Controls reported alongside (not promises)

- Planted partners: is the learned style closer to the planted style than the default is (cosine), and
  how many of the 25 planted favourite words are in the learned top 25?
- Persistence: after `docker compose restart`, a fresh process replays 20 "your memory" test games for
  GloVe and must reproduce the same clues and outcomes, with the memory read only from FalkorDB.
- Removal: with FalkorDB stopped, every command exits with an error naming FalkorDB; nothing falls back.
