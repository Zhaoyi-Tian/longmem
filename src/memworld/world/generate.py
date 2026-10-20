"""按章生成世界。三条规则：

补给  每个被要的词，都有唯一一个给出者；给出者可以是一个人，也可以是一片区域。
指代  提到的词和人，都可以不直说，而是沿着过去的事实指过去，层层嵌套；
      要的词也可以是很久以前听过的旧词。
转述  一个人要什么，可以由别人说出，也可以被后来的人改说，以最新的说法为准。

不变量：一个人要的一切，在你能满足他之前都已经有人说出。
指代和转述只用他的「祖先」（满足他之前必须先满足的人）说过的事实，所以不变量自动成立。
"""

import random
from collections import defaultdict, deque
from types import SimpleNamespace

from ..config import Params, Setting
from .model import Lit, Look, Mention, Person, Region, Rel, Road, Statement, Tell, Word
from .names import Namer

EXPAND = 0.5      # 在嵌套层数允许时，一个给出者展开成一片区域的概率
MAX_HOPS = 6      # 一个提及最多绕几步，只为让句子还读得下去


class Generator:
    def __init__(self, seed: int, params: Params, setting: Setting):
        self.seed, self.p, self.setting = seed, params, setting
        self.people: dict[int, Person] = {}
        self.regions: dict[int, Region] = {}
        self.chapters: list[int] = []                    # 第 n 章 → 区域
        self.giver: dict[str, int] = {}                  # 词 → 唯一的给出者
        self.wanters: dict[str, set[int]] = defaultdict(set)
        self.tellers: dict[int, set[int]] = defaultdict(set)   # 人 → 替他传过话的人
        self.seen: dict[str, list[int]] = defaultdict(list)    # 词 → 它被必然用到过的各章
        self.necessary: set[int] = set()                 # 已过各章的必经之人：此后所有人的祖先
        self.namer = Namer(setting)

    def chapter(self, n: int) -> Region:
        """第 n 章（从 0 起）。各章依次生成，世界没有尽头。"""
        while len(self.chapters) <= n:
            self._chapter(len(self.chapters))
        return self.regions[self.chapters[n]]

    def _chapter(self, n: int):
        rng = random.Random(f"{self.seed}:{n}")
        # 难度爬坡：推理类的旋钮在前 ramp 章里从 0 升到配置值；记忆负担则随旧事实自然累积
        f = min(1.0, n / self.p.ramp) if self.p.ramp else 1.0
        self.q = SimpleNamespace(**{k: getattr(self.p, k) * f
                                    for k in ("recall", "indirect", "relay", "revise")})
        self._new: list[Person] = []
        self._new_regions: list[Region] = []
        # 旧词被再次要到的机会：它每被用过一次就攒一份，越久远的那份越淡（越常用、越近越容易被想起）
        self._old = list(self.seen)
        self._old_w = [sum((n - c + 1) ** -self.p.decay for c in self.seen[w]) for w in self._old]

        R = self._region(None, n, rng)
        if self.chapters:
            R.entrance = self.regions[self.chapters[-1]].exit
        self.chapters.append(R.rid)

        exit_ = self._supply(R, Road(None), rng)
        skeleton = list(self._new)
        anc = self._ancestors()
        for p in skeleton:
            self._recall(p, anc[p.pid], rng)
        for p in skeleton:
            if p.wants:
                self._relay(p, anc[p.pid], rng)
        self._index()
        anc = self._ancestors()                         # 代说的人也算祖先
        for p in self._new:
            for s in p.says:
                self._phrase(s, anc, rng)
        self._dress(rng)
        used = set()                                    # 这一章必然用到的词：必经之人给出的和要的
        for a in anc[exit_.pid] | {exit_.pid}:
            q = self.people[a]
            used |= set(q.wants) | ({q.gift.word} if isinstance(q.gift, Word) else set())
        for w in sorted(used):
            self.seen[w].append(n)
        self.necessary |= anc[exit_.pid] | {exit_.pid}

    # ── 补给 ─────────────────────────────────────────────

    def _supply(self, R: Region, gift, rng) -> Person:
        """从出口往回长：每个被要的新词，安排一个给出者，直到这片区域的人数用完。"""
        x = self._person(R.rid, gift)
        R.exit = x.pid
        x.wants = [self.namer.word(rng)]
        queue = deque(x.wants)
        while queue:
            w = queue.popleft()
            g = self._person(R.rid, Word(w))
            if len(R.members) + len(queue) < self.p.size:
                g.wants = [self.namer.word(rng)]
                if R.depth < self.p.depth and rng.random() < EXPAND:
                    # 从外面看，这片区域就是 g：要 g 要的词，里面的出口给出 w
                    S = self._region(R, R.chapter, rng)
                    S.entrance, g.gift = g.pid, Road(S.rid)
                    self._supply(S, Word(w), rng)
            queue.extend(g.wants)
        return x

    # ── 指代 ─────────────────────────────────────────────

    def _recall(self, p: Person, ancestors: set[int], rng):
        """要的词也可以是旧词：本章祖先给过的，或前几章必然用到过的。
        挑中的机会按 Σ (n − c + 1)^(−decay)：本章的词算一份，越常用、越近的旧词越容易被挑中。"""
        if rng.random() >= self.q.recall:
            return
        local = [self.people[a].gift.word for a in sorted(ancestors)
                 if isinstance(self.people[a].gift, Word)]
        pool, weights = self._old + local, self._old_w + [1.0] * len(local)
        for _ in range(4):
            if pool and (w := rng.choices(pool, weights)[0]) not in p.wants:
                p.wants.append(w)
                return

    def _phrase(self, s: Statement, anc: dict[int, set[int]], rng):
        """决定一句要求怎么说：要的词可以沿祖先的事实指过去。
        这句话说的是谁，总是直呼其名——不知道说的是谁，就谈不上记住它。"""
        local = set(anc[s.target])
        for g in s.via:
            local |= anc[g] | {g}
        allowed = _Either(local, self.necessary)        # 本章的祖先，加上前几章的必经之人
        avoid = {("p", s.target), ("p", s.teller)}
        # 答案从不出现在要求里：至少绕一步，指向它在哪段过去里
        s.terms = [self._word_ref(w, allowed, avoid | {("w", w)}, rng, 0, force=True) for w in s.words]

    def _word_ref(self, w: str, allowed, avoid, rng, depth, force=False) -> Mention:
        """提到词 w：直说，或经由「给出它的人」「要它的人」指过去。"""
        if depth < MAX_HOPS and (force or rng.random() < self.q.indirect):
            g = self.giver[w]
            opts = [("gift", g)] if g in allowed and ("p", g) not in avoid else []
            opts += [("want", x) for x in sorted(self.wanters[w])
                     if x in allowed and ("p", x) not in avoid and self._only_want(x) == w]
            if opts:
                kind, x = rng.choice(opts)
                return Rel(kind, self._person_ref(x, allowed, avoid | {("p", x)}, rng, depth + 1))
        return Lit(w)

    def _person_ref(self, x: int, allowed, avoid, rng, depth) -> Mention:
        """提到人 x：叫名字，或经由他给过的词、他要过的词、他替谁传过话、谁替他传过话指过去。
        只用祖先说过的事实，并且每个事实在全世界唯一地指向 x。"""
        if depth < MAX_HOPS and rng.random() < self.q.indirect:
            X, opts = self.people[x], []
            if x in allowed:
                if isinstance(X.gift, Word) and ("w", X.gift.word) not in avoid:
                    opts.append(("giver", "w", X.gift.word))
                opts += [("wanter", "w", u) for u in X.wants         # 每一版都要它，才一定听说过
                         if self.wanters[u] == {x} and ("w", u) not in avoid
                         and all(u in v.words for v in X.says)]
                if isinstance(X.gift, Tell):
                    y = X.gift.statement.target
                    if self.tellers[y] == {x} and y in allowed and ("p", y) not in avoid:
                        opts.append(("teller", "p", y))
            opts += [("target", "p", y) for y in sorted(self.tellers[x])
                     if y in allowed and ("p", y) not in avoid]
            if opts:
                kind, t, v = rng.choice(opts)
                if t == "w":
                    return Rel(kind, self._word_ref(v, allowed, avoid | {("w", v)}, rng, depth + 1))
                return Rel(kind, self._person_ref(v, allowed, avoid | {("p", v)}, rng, depth + 1))
        return Look(x)

    def _only_want(self, x: int) -> str | None:
        X = self.people[x]
        return X.wants[0] if len(X.wants) == 1 and len(X.says) == 1 else None

    # ── 转述 ─────────────────────────────────────────────

    def _relay(self, p: Person, ancestors: set[int], rng):
        """谁来说 p 要什么：本人，或一个新来的人。之后还可能有人来改口，可以改不止一次。
        改口时在边 w → p 上插入一个新的给出者 g（要 w，给 w′），p 改要 w′：
        原有的依赖一条不少，不会出现捷径；对 p 说 w 从此算过期。"""
        s = Statement(p.pid, list(p.wants), p.pid)
        if rng.random() < self.q.relay:
            t = self._person(p.region, Tell(s))
            s.teller = t.pid
            self._recall(t, ancestors, rng)
        p.says = [s]
        while rng.random() < self.q.revise:
            last = p.says[-1]
            w = rng.choice(last.words)
            g = self._person(p.region, Word(self.namer.word(rng)))
            g.wants = [w]
            new = Statement(p.pid, [g.gift.word if u == w else u for u in last.words], -1,
                            version=len(p.says), via=last.via + [g.pid])
            r = self._person(p.region, Tell(new))
            new.teller = r.pid
            self._recall(r, ancestors, rng)
            p.says.append(new)

    # ── 工具 ─────────────────────────────────────────────

    def _index(self):
        """补齐每个人的最初说法，并登记「谁要过什么」「谁替谁传过话」，指代要用它们判断唯一。"""
        for p in self._new:
            if p.wants and not p.says:
                p.says = [Statement(p.pid, list(p.wants), p.pid)]
            for s in p.says:
                for w in s.words:
                    self.wanters[w].add(p.pid)
                if s.teller != p.pid:
                    self.tellers[p.pid].add(s.teller)

    def _ancestors(self) -> dict[int, set[int]]:
        """本章每个人的本章祖先：给他所要之词的人、替他传话的人（没改过口时）、放他进这片地方的人，
        以及这些人的祖先。更早各章的祖先由 self.seen 概括。"""
        local = {p.pid for p in self._new}
        memo: dict[int, set[int]] = {}

        def anc(pid):
            if pid not in memo:
                p = self.people[pid]
                deps = {self.giver[w] for w in p.wants}
                if len(p.says) == 1 and p.says[0].teller != pid:
                    deps.add(p.says[0].teller)      # 改过口的人，从哪个版本得知都行，传话人就不是必经的
                if (e := self.regions[p.region].entrance) is not None:
                    deps.add(e)
                memo[pid] = set().union(*({d} | anc(d) for d in deps if d in local))
            return memo[pid]

        for pid in local:
            anc(pid)
        return memo

    def _dress(self, rng):
        for p in self._new:
            p.look = self.namer.name("look", rng)
            if isinstance(p.gift, Road) and p.gift.region is not None:
                p.spot = self.regions[p.gift.region].name + "前"
            else:
                p.spot = rng.choice(self.setting.spots)
        for R in self._new_regions:
            rng.shuffle(R.members)

    def _person(self, rid: int, gift) -> Person:
        p = Person(len(self.people), rid, gift)
        self.people[p.pid] = p
        self.regions[rid].members.append(p.pid)
        self._new.append(p)
        if isinstance(gift, Word):
            self.giver[gift.word] = p.pid
        return p

    def _region(self, parent: Region | None, chapter: int, rng) -> Region:
        R = Region(len(self.regions), self.namer.name("inner" if parent else "outer", rng),
                   parent.rid if parent else None, parent.depth + 1 if parent else 0, chapter)
        self.regions[R.rid] = R
        self._new_regions.append(R)
        return R


class _Either:
    """几个集合的并，只用来判断属于与否，不必真的合并。"""

    def __init__(self, *sets):
        self.sets = sets

    def __contains__(self, x) -> bool:
        return any(x in s for s in self.sets)
