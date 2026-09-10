COMMANDS = [
    "init",
    "status",
    "plan",
    "next",
    "apply",
    "verify",
    "rollback",
    "why",
    "impact",
    "index",
    "import-scip",
    "mcp",
    "edges",
    "migrate",
    "doctor",
    "completion",
    "man",
    "version",
]


def bash() -> str:
    opts = " ".join(COMMANDS)
    return f"""# rfg bash completion
_rfg() {{
  local cur="${{COMP_WORDS[COMP_CWORD]}}"
  COMPREPLY=( $(compgen -W "{opts} --format --root --dry-run --help" -- "$cur") )
}}
complete -F _rfg rfg
complete -F _rfg rfg.py
"""


def zsh() -> str:
    opts = " ".join(COMMANDS)
    return f"""#compdef rfg rfg.py
_arguments '1:command:({opts})' '--format[json]' '--root[dir]' '--dry-run' '--help'
"""


def fish() -> str:
    lines = ["complete -c rfg -f"]
    for c in COMMANDS:
        lines.append(f"complete -c rfg -n '__fish_use_subcommand' -a {c}")
    lines.append("complete -c rfg -l format -l root -l dry-run -l help")
    return "\n".join(lines) + "\n"


def render(shell: str) -> str:
    if shell == "bash":
        return bash()
    if shell == "zsh":
        return zsh()
    if shell == "fish":
        return fish()
    raise ValueError("shell must be bash, zsh, or fish")
