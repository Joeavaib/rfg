# TODO

Fence first. Do not start inner-loop or modular rework until asked.
A rename, if ever, is an rfg campaign — not a stall.

The core loop already takes real hits (path traversal, backup id, claim
held-by, replace scope, lexeme skip, `.git` skip, land re-verify after
forged `state.json`). Do not “fix” those. The fence still has holes an
agent can walk through. That is the open work.

## Fence (now)

1. **Write target must resolve under root/worktree** — only real escape.
   `replace` followed `link.py` → `/tmp/...` and wrote outside the repo.
   Before every write: `Path.resolve()`; if the target is not under root
   or the worktree, Exit 4. Symlink in `path[]` → Exit 4, do not patch.

2. **`land` / `apply` only declared paths** — isolation is currently a lie.
   Land is `cp -a` of porcelain including untracked (`__pycache__`,
   `evil.bin`, `sneak.txt`). Apply stages undeclared `secret.py` as
   `extra` and copies it. Land only `path[]` + declared `extras`.
   Pyc/vendor never. Default: do not stage extras; `--allow-extra` if
   wanted. Otherwise `path[]` is decoration.

3. **`tick` JSON `ok` = exit 0** — agent contract is currently a lie.
   Failed ticks (`true` → 4, dirty `run` → 3) emit `"ok": true`.
   `emit_result(cmd, code, data)` with `ok = (code == 0)`. ~10 lines.

Then, still before rework:

4. **`--strict` at `tick` / `land`**, not only `plan --check`.
   Do not regex-hunt no-ops (`/bin/true`, `:`, `echo ok` all apply).
   Strict gate: verify command must name a file under `path[]`/`extras`.
   Without that, README must not say it stops the lie.

5. **`--agent` is not impersonation** — `RFG_AGENT=bob` + `--agent alice`
   steals the claim. Drop the flag, or allow it only when `RFG_AGENT`
   is empty.

6. **README / `docs/agent.md`: verify is a shell.** cwd is root or
   worktree; the command may write anywhere (`touch /tmp/...` works).
   Roadmap.yaml is a script host. “Writes only worktree/.rfg until land”
   is currently false. Say so. Do not pretend to sandbox the oracle.

Attack that must fail after 1–3:

```
path[] = app.py
+ undeclared secret.py + symlink into $HOME
verify = /bin/true
tick → json.ok true
land → secret + home file + pyc
```

Three of four steps already ran. Höflichkeit is the bug.

## Adoption (after the fence)

7. **hook-claim-bind** — PreToolUse must follow `claim_step`, not
   `dag.next_id`. MCP without an enforced hook is decoration.

8. **Core loop in the shop window** — HELP / first screen are the ~10
   verbs (`plan` `next` `tick` `apply` `verify` `land` `rollback`
   `claim` `doctor` `progress`). Honesty-layer (`scan` `sbom` `fleet`
   `risk` `impact`) stays, but is not the product.

## Not a task

Oracle quality is the user’s suite. Land-Gate / Cross-Verify amplify it;
they do not invent tests. Fleet, SBOM, C++ subset, inner-loop, cli-split
do not close the holes above.

Checker not factory. No LLM in rfg. FAIL sentence. Stdlib only.
Warn-first. Harvest outside. Exit 4 instead of guessing.
