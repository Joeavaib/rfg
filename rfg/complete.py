COMMANDS = [
    "init",
    "status",
    "plan",
    "next",
    "context",
    "tick",
    "apply",
    "verify",
    "land",
    "rollback",
    "claim",
    "release",
    "audit",
    "baseline",
    "repro",
    "progress",
    "digest",
    "why",
    "impact",
    "index",
    "import-scip",
    "mcp",
    "edges",
    "scan",
    "fuzz",
    "sbom",
    "boundaries",
    "fleet",
    "export",
    "recipe",
    "packs",
    "migrate",
    "doctor",
    "completion",
    "man",
    "version",
]


GLOBAL_FLAGS = ["--format", "--root", "--dry-run", "--diff", "--show-risk", "--max-chars", "--help"]


def bash() -> str:
    opts = " ".join(COMMANDS)
    flags = " ".join(GLOBAL_FLAGS)
    return f"""# rfg bash completion
_rfg() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  COMPREPLY=( $(compgen -W "{opts} {flags}" -- "$cur") )
}}
complete -F _rfg rfg
complete -F _rfg rfg.py
"""


def zsh() -> str:
    opts = " ".join(COMMANDS)
    return f"""#compdef rfg rfg.py
_arguments '1:command:({opts})' '--format[json]' '--root[dir]' '--dry-run' '--diff' '--show-risk' '--max-chars[chars]' '--help'
"""


def fish() -> str:
    lines = ["complete -c rfg -f"]
    for c in COMMANDS:
        lines.append(f"complete -c rfg -n '__fish_use_subcommand' -a {c}")
    lines.append("complete -c rfg -l format -l root -l dry-run -l diff -l show-risk -l max-chars -l help")
    return "\n".join(lines) + "\n"


def render(shell: str) -> str:
    if shell == "bash":
        return bash()
    if shell == "zsh":
        return zsh()
    if shell == "fish":
        return fish()
    raise ValueError("shell must be bash, zsh, or fish")
