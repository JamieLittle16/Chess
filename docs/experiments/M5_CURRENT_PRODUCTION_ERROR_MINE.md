# M5 current-production Stockfish error mine

Status: diagnostic only; no production chess change.

This experiment mines the immutable 200-game acceptance PGN for mutation-free legality filtering v1 with full-strength Stockfish 19. It is intended to choose the next high-upside strength hypothesis from evidence rather than from generic engine folklore.

## Frozen source

- accepted experiment: mutation-free legality filtering v1
- acceptance Actions run: `34136520700`
- artifact ID: `10024462155`
- target engine: `Chess-M4-static-legality-v1-accept@1f44bb9d867c`
- PGN SHA-256: `429c8c40f79782de1355ffa14c3c6a07d440b348fb4e0937af76150781e3df8e`

## Teacher protocol

- Stockfish 19 immutable `sf_19` release
- Threads=1
- Hash=32 MiB
- 20,000 nodes for the unrestricted search
- 20,000 nodes for the root-restricted search of the move actually played
- analyse plies 15 through 60 across all 200 retained games

The first pass is deliberately broad. It should reveal whether current losses are concentrated in forcing tactics, quiet positional decisions, exchanges, or particular game phases. Once the dominant clusters are known, the worst positions can be re-analysed at a much larger teacher budget before designing production changes.

## Outputs

The workflow retains the standard strength-lab `manifest.json`, `summary.json`, `positions.jsonl` and `positions.csv`, plus `actionable-summary.json` ranking severe/blunder clusters and the top 100 positions by WDL-expectation loss.
