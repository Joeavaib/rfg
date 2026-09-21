# TODO

Checker first. Do not start `inner-loop` until it is asked for.
A rename of the project, if ever, is an rfg campaign — not a reason to stall.

## Adoption (this is the product)

1. **hook-claim-bind** — PreToolUse must follow `claim_step`, not `dag.next_id`.
   MCP without an enforced hook is decoration; agents skip the loop.
2. **Core loop in the shop window** — HELP / first screen are the ~10 verbs
   (`plan` `next` `tick` `apply` `verify` `land` `rollback` `claim` `doctor`
   `progress`). Honesty-layer verbs (`scan` `sbom` `fleet` `risk` `impact`)
   stay, but they are not the product. Do not look like a platform.
3. **Oracle is the ceiling** — Land-Gate and Cross-Verify amplify a real
   command. They do not invent tests. Do not “fix” thin suites inside rfg.
4. **Public tree = operate** — tests, dogfood fixtures, and campaign
   logbooks stay on disk, gitignored. Clones should run, not study theology.

## Later (not now)

5. **inner-loop**, then **cli-split** — one step run (claim → snapshot →
   verify → land) in one module; CLI / MCP / hook only dispatch. Do not
   split `cli.py` first. Do not copy the verify runner. Do not add a second
   `RFG_*` reader.
6. Loop friction that belongs *inside* that campaign, not as extra surface:
   apply still stages the dirty tree; Land-Gate timeout ≠ `RFG_VERIFY_TIMEOUT`;
   `next` ≠ `recommend`.

## Hold

Checker not factory. No LLM in rfg. FAIL sentence. Stdlib only. Warn-first.
Harvest outside. Exit 4 instead of guessing.
