from __future__ import annotations

import json
from pathlib import Path

from rfg.types import Roadmap, State, state_from_dict, state_to_dict
from rfg.yamlio import marshal_roadmap, unmarshal_roadmap

DIR = ".rfg"


def claim_held_payload(st: State) -> dict[str, str]:
    """Machine-readable holder for claim conflicts (claimed_by, claim_step)."""
    return {
        "claimed_by": st.claim_agent or "",
        "claim_step": st.claim_step or "",
    }


class Store:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def dir(self) -> Path:
        return self.root / DIR

    @property
    def roadmap_path(self) -> Path:
        return self.dir / "roadmap.yaml"

    @property
    def state_path(self) -> Path:
        return self.dir / "state.json"

    def exists(self) -> bool:
        return self.roadmap_path.is_file()

    def init(self, rm: Roadmap) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.save_roadmap(rm)
        self.write_state(State())

    def load_roadmap(self) -> Roadmap:
        if not self.roadmap_path.is_file():
            raise FileNotFoundError("no roadmap")
        return unmarshal_roadmap(self.roadmap_path.read_text(encoding="utf-8"))

    def save_roadmap(self, rm: Roadmap) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.roadmap_path.write_text(marshal_roadmap(rm), encoding="utf-8")

    def load_state(self) -> State:
        if not self.state_path.is_file():
            return State()
        return state_from_dict(json.loads(self.state_path.read_text(encoding="utf-8")))

    def write_state(self, st: State) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state_to_dict(st), indent=2) + "\n", encoding="utf-8")
