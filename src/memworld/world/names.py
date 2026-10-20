"""切口、称呼、地名。词库来自世界观；全局不重复，因此任何描述在整个世界里都唯一。
组合用尽时自动加长或叠一层，所以永远有新名字，世界可以无限长下去。"""

import random
from string import Formatter

from ..config import Setting


class Namer:
    def __init__(self, setting: Setting):
        self.s = setting
        self.used: set[str] = set()
        self.longer = 0          # 切口用尽后加长的字数

    def _take(self, s: str) -> bool:
        if s in self.used:
            return False
        self.used.add(s)
        return True

    def word(self, rng: random.Random) -> str:
        while True:
            for _ in range(200):
                w = "".join(rng.choices(self.s.syllables, k=rng.choice((2, 2, 3)) + self.longer))
                if len(set(w)) == len(w) and self._take(w):
                    return w
            self.longer += 1

    def name(self, family: str, rng: random.Random) -> str:
        fam = self.s.names[family]
        for _ in range(200):
            s = self._fill(rng.choice(fam.patterns), rng)
            if self._take(s):
                return s
        while not self._take(s):
            s = self._fill(fam.grow, rng, base=s)
        return s

    def _fill(self, pattern: str, rng: random.Random, **fixed) -> str:
        keys = {f for _, f, _, _ in Formatter().parse(pattern) if f} - fixed.keys()
        return pattern.format(**{k: rng.choice(self.s.slots[k]) for k in sorted(keys)}, **fixed)
