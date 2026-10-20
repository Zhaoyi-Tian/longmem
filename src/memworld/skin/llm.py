"""LLM 润色皮：在模板句之上，以世界观为背景、以说话人的人设为口吻改写，指代也用自然的话说出来。

每一步的台词一次送出，改写后过两道检查，任何一道不过，那一行退回模板句：
1. 字面：所有 ⟨词⟩、人物称呼和地名原样保留。
2. 回译：让 LLM 只看改写后的句子，说出每个要的词是从谁出发、沿哪几步关系找到的，
   必须和程序生成的指代完全一致。指的是什么由程序决定，LLM 只决定怎么说。
结果按原句缓存：同一句话永远得到同一种润色。
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..chat import from_config as chat_from_config
from ..config import ROOT, Setting
from .template import TemplateSkin

TOKEN = re.compile(r"⟨[^⟩]*⟩")
# who 是说话人的事件
SPEECH = {"ask", "give", "accept", "partial", "reject", "premature", "caught", "ignore", "quiet", "silent"}

# 六种关系，从起点往外走一步。程序、改写、回译共用这一份定义
RELATIONS = {
    "gift": "这个人给过你的那个词",
    "want": "这个人要的那个词",
    "giver": "给过你这个词的那个人",
    "wanter": "要过这个词的那个人",
    "teller": "替这个人传过话（转述过他要什么）的那个人",
    "target": "这个人替他传过话的那个人（他转述过谁要什么）",
}
RELATION_DOC = "\n".join(f"  {k}：{v}" for k, v in RELATIONS.items())

POLISH = """你在为文字冒险游戏《{name}》润色台词。

背景：{background}
文风：{tone}

用户给出若干行原句，有的行注明了说话人的人设。把每一行改写得更有画面感、更贴合人设与文风，长度不超过原句的两倍。
人设只用来定口吻和动作，不要照抄人设原文。旁白里的「你」是玩家，不要把别人的人设套到「你」身上。

有的行里有「【线索1】」这样的占位：那是一个没有直说的词，要你从一个起点出发，沿着关系一步步找到。关系的含义：
{relations}
把每个占位换成说话人口吻的一段话，把线索一步步讲出来：可以拆成几个短句，可以用「那人」「那句」这样的代词。
起点必须原样出现，每一步都要说到，顺序不能乱，不能多也不能少；最后要让人明白要的就是走到的那个词。
不要写成「……的那位给你的那句切口」这样层层套叠的长定语。例如：
  占位：【线索1】：起点「红灯笼的掌柜」 → 这个人给过你的那个词 → 要过这个词的那个人 → 这个人给过你的那个词
  讲法：红灯笼的掌柜给过你一句切口，有人跟你讨过那句——那人后来也塞给你一句，就要那句。
  占位：【线索1】：起点「瘸腿的郎中」 → 替这个人传过话的那个人 → 这个人要的那个词
  讲法：有人替瘸腿的郎中跑过腿、传过话，那人自己也在等一句切口——就是那句。
  占位：【线索1】：起点「⟨哩咯⟩」 → 给过你这个词的那个人 → 这个人替他传过话的那个人 → 这个人给过你的那个词
  讲法：⟨哩咯⟩是谁给你的，你记得吧？那人替别人带过话；被带话的那位，也给过你一句。

硬性要求：
1. ⟨⟩ 和其中的字一个都不能改，不能增减 ⟨⟩。
2. 人物称呼（如「独眼的刀客」）和地名必须一字不差地出现。
3. 意思不变：谁对谁要什么、给什么，必须与原句一致。不得添加新的要求、线索、暗示或人物。
4. 一行对一行，不拆不并。
用 JSON 输出：{{"lines": ["第 1 行改写", "第 2 行改写", ...]}}"""

CHECK = """你在核对文字冒险游戏里的台词。每句台词里，说话人要你说出若干个词（切口），有的直接用 ⟨⟩ 说出，
有的没有直说，而是从一个起点（一个人物称呼，或一个 ⟨词⟩）出发，沿着关系一步步指过去。关系的含义：
{relations}

对每句台词，按它字面上的意思，列出它要的每一个词：起点是什么，从起点往外依次走了哪几步关系。
直接说出的词，起点就是那个 ⟨词⟩，步骤为空。只依据句子本身，不要猜测。
用 JSON 输出：{{"lines": [{{"items": [{{"anchor": "起点", "steps": ["关系", ...]}}, ...]}}, ...]}}"""


def chain(m) -> tuple[str, tuple[str, ...]]:
    """把一个提及拆成（起点，从起点往外的步骤）。"""
    steps = []
    while m[0] not in ("word", "look"):
        steps.append(m[0])
        m = m[1]
    anchor = f"⟨{m[1]}⟩" if m[0] == "word" else m[1]
    return anchor, tuple(reversed(steps))


def _norm(anchor: str) -> str:
    return re.sub(r"[⟨⟩「」『』\"'\s]", "", str(anchor))


def _same(want: list[tuple[str, tuple]], got: list[tuple[str, tuple]]) -> bool:
    """步骤必须完全一致；起点只要互相包含就算对上（称呼是否原样出现，字面检查已经管了）。"""
    got = list(got)
    for anchor, steps in want:
        a = _norm(anchor)
        hit = next((g for g in got if g[1] == steps and g[0] and (g[0] in a or a in g[0])), None)
        if hit is None:
            return False
        got.remove(hit)
    return not got


@dataclass
class Row:
    text: str
    draft: str                                           # 给模型看的原句：绕着说的地方换成【线索n】
    keep: list[str]
    persona: str | None
    chains: list[tuple[str, tuple[str, ...]]] | None    # 只有要求句才有
    key: str

    @property
    def indirect(self) -> bool:
        return bool(self.chains) and any(steps for _, steps in self.chains)


class LLMSkin(TemplateSkin):
    def __init__(self, setting: Setting, chat, seed: int = 0, cache: str | Path | None = None):
        super().__init__(setting, seed)
        self.chat = chat
        fill = {"name": setting.name, "background": setting.background.strip(),
                "tone": setting.tone, "relations": RELATION_DOC}
        self.polish_prompt = POLISH.format(**fill)
        self.check_prompt = CHECK.format(**fill)
        self.cache_path = Path(cache) if cache else None
        self.cache: dict[str, str] = (json.loads(self.cache_path.read_text())
                                      if self.cache_path and self.cache_path.exists() else {})

    @classmethod
    def from_config(cls, setting: Setting, skin: dict, seed: int = 0) -> "LLMSkin":
        return cls(setting, chat_from_config(skin, timeout=30), seed, ROOT / skin["cache"])

    def render(self, events: list[dict]) -> str:
        out: list[str | Row] = []
        for e in events:
            text, keep = self.line(e)
            if e["type"] == "scene":
                out.append(text)
                continue
            persona = self.s.persona(e["who"]) if e["type"] in SPEECH else None
            chains = [chain(t) for t in e["terms"]] if e["type"] == "ask" else None
            draft = text
            for n, t in enumerate(e.get("terms") or [], 1):
                if t[0] not in ("word", "look"):
                    draft = draft.replace(self.mention(t, []), f"【线索{n}】", 1)
            key = hashlib.sha1(f"{text}|{persona}".encode()).hexdigest()
            out.append(Row(text, draft, keep, persona, chains, key))
        todo = [r for r in out if isinstance(r, Row) and r.key not in self.cache]
        if todo:
            self._polish(todo)
        return "\n".join(r if isinstance(r, str) else self.cache.get(r.key, r.text) for r in out)

    def _polish(self, rows: list[Row]):
        try:
            new = self._ask(self.polish_prompt, [self._brief(r) for r in rows])
        except Exception:
            return            # 本次不缓存，退回模板句，下次再试
        new = [re.sub(r"^\d+\.\s*", "", str(s)).strip() for s in new]
        ok = [bool(s) and sorted(TOKEN.findall(s)) == sorted(TOKEN.findall(r.text))
              and all(k in s for k in r.keep) for r, s in zip(rows, new, strict=True)]
        check = [i for i, r in enumerate(rows) if ok[i] and r.indirect]
        if check:
            try:
                for i, same in zip(check, self._check([rows[i] for i in check], [new[i] for i in check]),
                                   strict=True):
                    ok[i] = same
            except Exception:
                return
        for r, s, good in zip(rows, new, ok, strict=True):
            self.cache[r.key] = s if good else r.text
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0))

    def _brief(self, r: Row) -> str:
        """把原句里绕着说的那几处挖掉，换成【线索n】，另附线索链：模型没有现成的拼接可抄。"""
        s, clues = r.draft, ""
        for n, (anchor, steps) in enumerate(r.chains or [], 1):
            if steps:
                clues += f"\n   【线索{n}】：起点「{anchor}」" + "".join(f" → {RELATIONS[k]}" for k in steps)
        return (f"（说话人人设：{r.persona}）" if r.persona else "") + s + clues

    def _check(self, rows: list[Row], texts: list[str]) -> list[bool]:
        """回译：只看改写后的句子，还原出的指代必须和原来一致（顺序不论）。"""
        got = self._ask(self.check_prompt, [f"{t}\n   （要的词共 {len(r.chains)} 个）"
                                            for r, t in zip(rows, texts, strict=True)], temperature=0)
        return [_same(r.chains, [(_norm(it["anchor"]), tuple(it["steps"])) for it in line["items"]])
                for r, line in zip(rows, got, strict=True)]

    def _ask(self, system: str, lines: list[str], temperature: float = 1.0) -> list:
        user = "\n".join(f"{i}. {s}" for i, s in enumerate(lines, 1))
        out = json.loads(self.chat(system, user, temperature=temperature))["lines"]
        if len(out) != len(lines):
            raise ValueError("行数不符")
        return out
