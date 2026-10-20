"""模板皮：把结构化事件按世界观里的台词变成文字。确定、可复现。"""

import random

from ..config import Setting


class TemplateSkin:
    def __init__(self, setting: Setting, seed: int = 0):
        self.s = setting
        self.rng = random.Random(f"skin:{seed}")

    def render(self, events: list[dict]) -> str:
        return "\n".join(self.line(e)[0] for e in events)

    def line(self, e: dict) -> tuple[str, list[str]]:
        """返回一句话，以及改写时必须原样保留的片段。"""
        kind = e["type"]
        if kind == "scene":
            return self.scene(e), []
        if kind == "ask":
            keep: list[str] = [e["who"]]
            terms = self.s.terms["join"].join(self.mention(t, keep) for t in e["terms"])
            if e["self"]:
                return self._pick("ask_self").format(who=e["who"], terms=terms), keep
            target = e["target"]
            keep.append(target)
            kind = "ask_revised" if e["version"] else "ask_other"
            return self._pick(kind).format(who=e["who"], target=target, terms=terms), keep
        fields = {k: v for k, v in e.items() if k != "type"}
        keep = [v for k, v in fields.items() if k in ("who", "region", "to", "from")]
        if kind == "give":
            keep.append(f"⟨{e['word']}⟩")
        return self._pick(kind).format(**fields), keep

    def mention(self, m, keep: list[str]) -> str:
        """一个提及：⟨词⟩、称呼，或沿一跳关系的说法。嵌套的那一层加引号。"""
        T = self.s.terms
        match m:
            case ("word", w):
                return f"⟨{w}⟩"
            case ("look", look):
                keep.append(look)
                return look
            case (kind, of):
                inner = self.mention(of, keep)
                if of[0] not in ("word", "look"):
                    inner = T["quote"].format(x=inner)
                return T[kind].format(x=inner)

    def scene(self, e: dict) -> str:
        S = self.s.scene
        at = S["at"].format(at=e["at"]) if e["at"] else S["alone"]
        left = "" if e["left"] is None else S["left"].format(left=e["left"])
        status = at + S["steps"].format(t=e["t"], T=e["T"], left=left)
        if e["here"] is None:
            return status
        here = "　".join(f"{i}.{look}（{spot}）" for i, (look, spot) in enumerate(e["here"], 1))
        return S["here"].format(region=e["region"], here=here) + "\n" + status

    def _pick(self, kind: str) -> str:
        return self.rng.choice(self.s.lines[kind])
