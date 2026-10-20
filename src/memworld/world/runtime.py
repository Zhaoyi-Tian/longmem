"""运行时：agent 在世界里走、说话。

step 返回的文本是 agent 唯一应看的东西。info["events"] 是同一段文本的结构化形式，
info["trace"] 记录每次开口的来龙去脉，两者只用于测试和事后分析。
"""

from collections import defaultdict

from ..config import Config
from ..skin.template import TemplateSkin
from .generate import Generator
from .model import Lit, Look, Mention, Person, Rel, Road, Statement, Tell, Word, hops

# 规则说明对所有世界观都一样，世界观只在前面加一段开场白
RULES = """\
目标：在步数用完之前，走出尽可能多的地方。

动作（每个动作算一步）：
  走 <编号或称呼>   走到某人身边
  说 <词>           对身边的人说一个 ⟨⟩ 里的词，不必带括号

每个人只开口一次：初见时说他要什么，被满足时给你东西，之后不再重复。
要的词从不直说，只告诉你它在哪段过去里：「某人给你的那句」就是那人亲口给过你的词，
「某人要的那句」就是那人跟你要过的词，「替某人传话的那位」「讨某词的那位」指的是人，可以层层套。
有人会替别人传话；有人会改主意，以改过的说法为准。
说错有代价：明明拿到过那句切口却说错，就算一次；次数用完，你就被抓了。
还没拿到就开口，对方只会让你先去拿——不算错，但白费一步。
听过的话不会再听到第二遍，要靠你自己记住。"""


class World:
    def __init__(self, config: Config, seed: int | None = None, T: int | None = None, skin=None):
        self.config = config
        self.seed = config.seed if seed is None else seed
        self.T = config.T if T is None else T
        self.skin = skin or TemplateSkin(config.setting, self.seed)
        self.instructions = f"{config.setting.intro}\n\n{RULES}"

    # ── 接口 ─────────────────────────────────────────────

    def reset(self) -> str:
        self.gen = Generator(self.seed, self.config.params, self.config.setting)
        self.people, self.regions = self.gen.people, self.gen.regions
        self.t = 0
        self.chapter = 0
        self.region = self.gen.chapter(0).rid
        self.at: int | None = None
        self.met: set[int] = set()
        self.done: set[int] = set()
        self.got: dict[int, set[str]] = defaultdict(set)
        self.heard: dict[str, int] = {}                    # 词 → 第一次听到的步
        self.heard_night: dict[str, int] = {}              # 词 → 第一次听到时在第几章
        self.heard_ver: dict[int, dict[int, int]] = defaultdict(dict)  # 人 → {版本: 步}
        self.trace: list[dict] = []
        self.wrong = 0                                     # 说错了几次
        self.first_events = [{"type": "begin", "region": self.regions[self.region].name},
                             self._scene(full=True)]
        return self.skin.render(self.first_events)

    def step(self, action: str) -> tuple[str, bool, dict]:
        self.t += 1
        n = len(self.trace)
        verb, _, arg = action.strip().partition(" ")
        arg = arg.strip()
        region, lost = self.region, False
        if verb in ("走", "go"):
            p = self._find(arg)
            events = self._meet(p) if p else [{"type": "nobody", "name": arg}]
            lost = p is None
        elif verb in ("说", "say"):
            events = self._say(arg.strip("⟨⟩<>「」\"' "))
        else:
            events = [{"type": "unknown", "action": action}]
        events.append(self._scene(full=lost or self.region != region))   # 只在换了地方或走错时列出众人
        info = {"events": events, "trace": self.trace[n:], "chapters": self.chapter, "t": self.t}
        return self.skin.render(events), self.t >= self.T or self.caught, info

    @property
    def caught(self) -> bool:
        return bool(self.config.strikes) and self.wrong >= self.config.strikes

    # ── 动作 ─────────────────────────────────────────────

    def _meet(self, p: Person) -> list[dict]:
        self.at = p.pid
        if p.pid in self.met:
            return [{"type": "quiet", "who": p.look}]
        self.met.add(p.pid)
        events = [{"type": "meet", "who": p.look}]
        if p.says and p.says[0].teller == p.pid:
            events.append(self._utter(p, p.says[0]))
        elif p.wants:
            events.append({"type": "silent", "who": p.look})
        if not p.wants:
            events += self._satisfy(p)
        return events

    def _say(self, w: str) -> list[dict]:
        if self.at is None:
            return [{"type": "void", "word": w}]
        p = self.people[self.at]
        if p.pid in self.done or not p.wants:
            return [{"type": "ignore", "who": p.look, "word": w}]
        v = max(self.heard_ver[p.pid], default=0)       # 以听到的最新说法为准
        need = p.says[v].words
        self.trace.append(self._record(p, v, w))
        if w not in need and self.trace[-1]["kind"] == "premature":
            return [{"type": "premature", "who": p.look, "word": w}]      # 还没拿到答案就开口：不算错
        if w not in need:
            self.wrong += 1
            events = [{"type": "reject", "who": p.look, "word": w}]
            return events + ([{"type": "caught", "who": p.look}] if self.caught else [])
        self.got[p.pid].add(w)
        if not set(need) <= self.got[p.pid]:
            return [{"type": "partial", "who": p.look, "word": w}]
        return [{"type": "accept", "who": p.look, "word": w}] + self._satisfy(p)

    def _satisfy(self, p: Person) -> list[dict]:
        self.done.add(p.pid)
        R = self.regions[p.region]
        match p.gift:
            case Word(w):
                self.heard.setdefault(w, self.t)
                self.heard_night.setdefault(w, self.chapter)
                events = [{"type": "give", "who": p.look, "word": w}]
            case Tell(s):
                events = [self._utter(p, s)]
            case Road(None):
                self.chapter += 1
                nxt = self.gen.chapter(self.chapter)
                events = [{"type": "next", "who": p.look, "from": R.name, "to": nxt.name}]
                self.region, self.at = nxt.rid, None
            case Road(rid):
                events = [{"type": "enter", "who": p.look, "region": self.regions[rid].name}]
                self.region, self.at = rid, None
        if p.pid == R.exit and isinstance(p.gift, Word):
            parent = self.regions[R.parent]
            events.append({"type": "leave", "region": R.name, "to": parent.name})
            self.region, self.at = parent.rid, None
        return events

    def _utter(self, speaker: Person, s: Statement) -> dict:
        self.heard_ver[s.target].setdefault(s.version, self.t)
        own = s.teller == s.target
        return {"type": "ask", "who": speaker.look, "self": own, "version": s.version,
                "target": None if own else self.people[s.target].look,
                "terms": [self._public(t) for t in s.terms]}

    # ── 观察与记录 ───────────────────────────────────────

    def _here(self) -> list[Person]:
        return [self.people[i] for i in self.regions[self.region].members]

    def _scene(self, full: bool) -> dict:
        return {"type": "scene", "region": self.regions[self.region].name,
                "here": [(p.look, p.spot) for p in self._here()] if full else None,
                "at": self.people[self.at].look if self.at is not None else None,
                "t": self.t, "T": self.T,
                "left": self.config.strikes - self.wrong if self.config.strikes else None}

    def _find(self, arg: str) -> Person | None:
        here = self._here()
        if arg.isdigit():
            i = int(arg) - 1
            return here[i] if 0 <= i < len(here) else None
        for match in ([p for p in here if p.look == arg],
                      [p for p in here if arg and arg in p.look]):
            if len(match) == 1:
                return match[0]
        return None

    def _public(self, m: Mention):
        """把提及换成 agent 能看到的形式：人只以称呼出现。"""
        match m:
            case Lit(w):
                return ("word", w)
            case Look(pid):
                return ("look", self.people[pid].look)
            case Rel(kind, of):
                return (kind, self._public(of))

    def _record(self, p: Person, v: int, w: str) -> dict:
        s = p.says[v]
        if w in s.words:
            kind = "ok"
        elif any(w in p.says[u].words for u in range(v)):
            kind = "stale"        # 说了改口之前的词
        elif not any(u in self.heard for u in s.words if u not in self.got[p.pid]):
            kind = "premature"    # 答案还没交到你手里就开口：怎么说都不可能对，只算急躁，不算记错
        elif w in self.heard:
            kind = "confused"     # 说了另一个听过的词
        else:
            kind = "unheard"      # 说了没听过的词
        return {
            "t": self.t, "chapter": self.chapter, "who": p.pid, "word": w, "kind": kind,
            "version": v,
            "knew": v in self.heard_ver[p.pid],   # 是否听过这条要求
            "ask_age": self.t - self.heard_ver[p.pid][v] if v in self.heard_ver[p.pid] else None,
            "need": {u: {"age": self.t - self.heard[u] if u in self.heard else None,
                         "nights": self.chapter - self.heard_night[u] if u in self.heard else None,
                         "hops": hops(term)} for u, term in zip(s.words, s.terms, strict=True)},
        }
