"""世界里的东西：人、区域、一句要求，以及提到一个词或一个人的方式。"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 提及：直接叫名字，或沿一条过去的事实指过去 ──────────────────────


@dataclass(frozen=True)
class Lit:
    """直接说出的词：⟨哩咯⟩。"""
    word: str


@dataclass(frozen=True)
class Look:
    """直接叫出的人：独眼的刀客。"""
    pid: int


# 一跳关系。前两种指向一个词，后四种指向一个人；of 是关系另一端的那个提及。
#   gift    of 给你的那个词            want    of 要的那个词
#   giver   给你 of 的那位             wanter  讨 of 的那位
#   teller  替 of 传话的那位           target  of 替他传话的那位
WORD_RELS = ("gift", "want")
PERSON_RELS = ("giver", "wanter", "teller", "target")


@dataclass(frozen=True)
class Rel:
    kind: str
    of: Mention


Mention = Lit | Look | Rel


def hops(m: Mention) -> int:
    """要想起几件事，才知道指的是什么。"""
    return 1 + hops(m.of) if isinstance(m, Rel) else 0


# ── 一个人给出的东西：一个词、一条路，或一句关于别人要什么的话 ──────


@dataclass
class Word:
    word: str


@dataclass
class Road:
    region: int | None          # None：通往下一章


@dataclass
class Tell:
    statement: Statement


@dataclass
class Statement:
    """「target 要 words」。version 0 是最初的说法，之后每改一次口加一。"""
    target: int
    words: list[str]
    teller: int
    version: int = 0
    via: list[int] = field(default_factory=list)      # 改口后多出来、满足这一版必须先满足的人
    terms: list[Mention] = field(default_factory=list)


@dataclass
class Person:
    pid: int
    region: int
    gift: Word | Road | Tell | None
    wants: list[str] = field(default_factory=list)
    says: list[Statement] = field(default_factory=list)   # 他的要求的各个版本
    look: str = ""
    spot: str = ""


@dataclass
class Region:
    rid: int
    name: str
    parent: int | None
    depth: int
    chapter: int
    entrance: int | None = None   # 给出进入此地之路的人
    exit: int | None = None       # 给出此地对外之物的人
    members: list[int] = field(default_factory=list)
