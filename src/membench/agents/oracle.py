"""完美记忆的参照 agent：只用听到的内容，从不忘记，从不乱猜。

它读的是 info["events"]，内容与文字完全相同，只是省去了解析中文。
用途是验证生成器：任何 seed、任何走法下，听到的内容都足以走下去。
它记三类事实：谁给过你什么词、谁要什么词、谁替谁传过话；指代就是沿这些事实走。
"""

import random
from collections import defaultdict


class Oracle:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        # 事实
        self.gave: dict[str, str] = {}                         # 人 → 他给过的词
        self.giver: dict[str, str] = {}                        # 词 → 给它的人
        self.wants: dict[str, dict[int, list[str] | None]] = defaultdict(dict)  # 人 → {版本: 词}
        self.wanters: dict[str, set[str]] = defaultdict(set)   # 词 → 要过它的人
        self.told: dict[str, str] = {}                         # 传话的人 → 他替谁传话
        self.tellers: dict[str, set[str]] = defaultdict(set)   # 人 → 替他传过话的人
        self.pending: list[dict] = []                          # 还没想明白的话
        # 行动
        self.heard: set[str] = set()
        self.met: set[str] = set()
        self.done: set[str] = set()
        self.said: dict[str, set[str]] = defaultdict(set)
        self.here: list[str] = []
        self.at: str | None = None

    def observe(self, events: list[dict], text: str = "", settle: bool = True):
        for e in events:
            who = e.get("who")
            match e["type"]:
                case "scene":
                    if e["here"] is not None:
                        self.here = [look for look, _ in e["here"]]
                    self.at = e["at"]
                case "meet":
                    self.met.add(who)
                case "ask":
                    about = who if e["self"] else e["target"]
                    self.wants[about].setdefault(e["version"], None)   # 知道有这一版，词还没想明白
                    if not e["self"]:
                        self.told[who] = about
                        self.tellers[about].add(who)
                        self.done.add(who)
                    self.pending.append({**e, "about": about})
                case "give":
                    self.gave[who] = e["word"]
                    self.giver[e["word"]] = who
                    self.heard.add(e["word"])
                    self.done.add(who)
                case "enter" | "next":
                    self.done.add(who)
                    if e["type"] == "next":
                        self._forget_here()
                case "leave":
                    self._forget_here()
                case "partial" | "accept":
                    self.said[who].add(e["word"])
        if settle:
            self._settle()

    def _forget_here(self):
        """走过的地方回不去：先把能想明白的想明白，那里剩下没想明白的话就丢掉。"""
        self._settle()
        self.pending = [s for s in self.pending if s["about"] not in self.here]

    def _settle(self):
        """把能想明白的话都想明白；一句想明白了，可能让另一句也能想明白。"""
        changed = True
        while changed:
            changed = False
            for s in list(self.pending):
                words = [self.word(t) for t in s["terms"]]
                if None not in words:
                    self.wants[s["about"]][s["version"]] = words
                    for w in words:
                        self.wanters[w].add(s["about"])
                    self.pending.remove(s)
                    changed = True

    def word(self, m) -> str | None:
        match m:
            case ("word", w):
                return w
            case ("gift", of):
                return self.gave.get(self.person(of))
            case ("want", of):
                versions = self.wants.get(self.person(of), {})
                only = versions.get(0)
                return only[0] if len(versions) == 1 and only and len(only) == 1 else None

    def person(self, m) -> str | None:
        match m:
            case ("look", look):
                return look
            case ("giver", of):
                return self.giver.get(self.word(of))
            case ("wanter", of):
                return _only(self.wanters.get(self.word(of)))
            case ("teller", of):
                return _only(self.tellers.get(self.person(of)))
            case ("target", of):
                return self.told.get(self.person(of))

    def act(self) -> str | None:
        for who in self.here:
            if who in self.done or not self.wants.get(who):
                continue
            words = self.wants[who][max(self.wants[who])]          # 以最新的说法为准
            if words is None or not self.heard.issuperset(words):
                continue
            todo = [w for w in words if w not in self.said[who]]
            if todo:
                return f"说 {todo[0]}" if self.at == who else f"走 {who}"
        unmet = [who for who in self.here if who not in self.met]
        return f"走 {self.rng.choice(unmet)}" if unmet else None


def _only(xs: set[str] | None) -> str | None:
    return next(iter(xs)) if xs and len(xs) == 1 else None
