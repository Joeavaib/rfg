# rfg in Grok Build

v1 of rfg is a local CLI. Grok Build talks to it in two ways; both are in this repo.

## 1. Skill (always)

`.grok/skills/rfg/SKILL.md` — slash `/rfg`, or auto when the prompt is a multi-step refactor.

The agent must run:

```
python3 rfg.py --format json <command>
```

Loop: `next` → `apply --dry-run` → `apply` → `verify`; on verify exit 2, `rollback last`.

## 2. MCP (optional, this project)

`.grok/config.toml` starts:

```
python3 rfg.py mcp
```

stdio, LSP `Content-Length` framing. Tools match the CLI (`status`, `next`, `apply`, …). Trust the project folder so Grok loads project MCP. Reload MCP with `r` on the MCP tab or a new session.

## 3. Other repos

Copy the skill to `~/.grok/skills/rfg/` and put this checkout on `PYTHONPATH`, or add a user MCP server with `args` pointing at this `rfg.py`.

Plugin marketplace packaging is not required for v1; skill + project MCP is the integration.
