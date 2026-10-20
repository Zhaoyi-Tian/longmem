"""失忆的更夫：夜里记得一切，天亮只剩一张纸条。

一夜就是一章。夜里它是完美记忆（Oracle）；走出一章时，它按某种策略挑出一些事实写进纸条，
总长不超过 B 字，其余全部忘掉，下一夜只凭纸条重建记忆。纸条上的事实有三类：
「X 给过 ⟨w⟩」「X 要 ⟨w⟩」「T 替 P 传过话」。

挑选策略：
need       按「越常用、越近越重要」打分：词在第 c 夜被给过或被说过，就攒一份 (n − c + 1)^(−d)。
           只用自己观察得到的东西。
recent     只看最近一次出现。
hindsight  偷看未来：只留以后的要求里真会用到的事实（沿指代路径收集）。
           这是不知道未来的策略够不到的上界。

想不起来、无路可走时，它去找要求没解开的人，拿记得的词赌一把（可能因此被抓）。
"""

import random
from collections import defaultdict

from memworld.world.model import Lit, Look

from .oracle import Oracle


class Memento:
    def __init__(self, budget: int, policy: str = "need", decay: float = 1.0, seed: int = 0, world=None):
        self.budget, self.policy, self.decay, self.seed = budget, policy, decay, seed
        self.world = world                                   # 只有 hindsight 用：偷看未来
        self.rng = random.Random(seed)
        self.mind = Oracle(seed)
        self.night = 0
        self.uses: dict[str, list[int]] = defaultdict(list)  # 词 → 在哪几夜被给过或说过
        self.notes: list[str] = []                           # 每一夜写下的纸条，供分析

    def observe(self, events: list[dict], text: str = ""):
        self.mind.observe(events)
        for e in events:
            if e["type"] in ("give", "partial", "accept"):
                self.uses[e["word"]].append(self.night)
        if any(e["type"] == "next" for e in events):
            self._sleep()
            self.mind.observe([e for e in events if e["type"] == "scene"])

    def act(self) -> str | None:
        if action := self.mind.act():
            return action
        m = self.mind                                        # 想不起来：找个卡住的人赌一把
        stuck = [who for who in m.here if who not in m.done and who in m.wants]
        if not stuck or not m.heard:
            return None
        who = self.rng.choice(stuck)
        return f"说 {self.rng.choice(sorted(m.heard))}" if m.at == who else f"走 {who}"

    # ── 天亮：写纸条，忘掉其余 ───────────────────────────────

    def _sleep(self):
        m, n = self.mind, self.night + 1
        facts = [(f"{x}给过⟨{w}⟩", w, ("gave", x, w)) for x, w in m.gave.items()]
        for x, versions in m.wants.items():
            latest = versions[max(versions)]
            for w in latest or []:
                facts.append((f"{x}要⟨{w}⟩", w, ("want", x, w)))
        facts += [(f"{t}替{p}传过话", m.gave.get(p), ("told", t, p)) for t, p in m.told.items()]
        if self.policy == "hindsight":
            later = self._future_facts(n)
            facts.sort(key=lambda f: (f[2] in later, self._score(f[1], n)), reverse=True)
        else:
            facts.sort(key=lambda f: self._score(f[1], n), reverse=True)
        keep, size = [], 0
        for text, _, fact in facts:
            if size + len(text) + 1 <= self.budget:          # 每条后面跟一个分隔符
                keep.append(fact)
                size += len(text) + 1
        self.notes.append("；".join(t for t, _, f in facts if f in keep))
        self.night = n
        self.mind = self._wake(keep)

    def _score(self, w: str | None, n: int) -> float:
        if w is None or not self.uses.get(w):
            return 0.0
        last = max(self.uses[w])
        if self.policy in ("recent", "hindsight"):
            return last
        return sum((n - c) ** -self.decay for c in self.uses[w])

    def _future_facts(self, n: int, ahead: int = 30) -> set[tuple]:
        """偷看第 n 章往后的 ahead 章：那些要求沿指代路径会用到哪些更早的事实。"""
        gen = self.world.gen
        gen.chapter(n + ahead)
        P, chapter_of = gen.people, lambda pid: gen.regions[P[pid].region].chapter
        need: set[tuple] = set()

        def walk(m):
            """返回提及指向的东西（词或人），顺路记下用到的事实（kind, 说出它的人, 另一端）。"""
            if isinstance(m, Lit):
                return m.word
            if isinstance(m, Look):
                return m.pid
            v = walk(m.of)
            kind, src, other, out = {
                "gift": lambda: ("gave", v, P[v].gift.word, P[v].gift.word),
                "want": lambda: ("want", v, P[v].wants[0], P[v].wants[0]),
                "giver": lambda: ("gave", gen.giver[v], v, gen.giver[v]),
                "wanter": lambda: ("want", min(gen.wanters[v]), v, min(gen.wanters[v])),
                "teller": lambda: ("told", min(gen.tellers[v]), v, min(gen.tellers[v])),
                "target": lambda: ("told", v, P[v].gift.statement.target, P[v].gift.statement.target),
            }[m.kind]()
            if chapter_of(src) < n:
                need.add((kind, P[src].look, P[other].look if kind == "told" else other))
            return out

        for pid, p in P.items():
            if chapter_of(pid) >= n:
                for st in p.says:
                    for t in st.terms:
                        walk(t)
        return need

    def _wake(self, keep) -> Oracle:
        mind = Oracle(self.seed)
        for kind, a, b in keep:
            if kind == "gave":
                mind.gave[a], mind.giver[b] = b, a
                mind.heard.add(b)
            elif kind == "want":
                mind.wants[a].setdefault(0, [])
                mind.wants[a][0].append(b)
                mind.wanters[b].add(a)
            else:
                mind.told[a] = b
                mind.tellers[b].add(a)
        return mind
