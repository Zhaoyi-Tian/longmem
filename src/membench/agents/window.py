"""只记得最近 W 步的 agent。"""

import random

from .oracle import Oracle


class Window:
    """只记得最近 W 步的 agent，如同上下文窗口有限的模型；想不起来时，在记得的词里猜。
    眼前有谁不算记忆，始终记得。用来检验：分数确实随记忆变短而下降。"""

    def __init__(self, W: int, seed: int = 0):
        self.W, self.seed = W, seed
        self.rng = random.Random(seed)
        self.log: list[list[dict]] = []
        self.here: list[str] = []
        self.at: str | None = None

    def observe(self, events: list[dict], text: str = ""):
        self.log.append(events)
        for e in events:
            if e["type"] == "scene":
                if e["here"] is not None:
                    self.here = [look for look, _ in e["here"]]
                self.at = e["at"]

    def act(self) -> str:
        mind = Oracle(self.seed)
        for events in self.log[-self.W:]:
            mind.observe(events, settle=False)
        mind._settle()
        mind.here, mind.at = self.here, self.at
        if action := mind.act():
            return action
        if self.at and mind.heard and self.rng.random() < 0.5:
            return f"说 {self.rng.choice(sorted(mind.heard))}"
        return f"走 {self.rng.choice(self.here)}"
