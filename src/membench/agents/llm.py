"""把一个 LLM 接到世界上。三种跑法：

全上下文        整局的文字经过都在上下文里，没有遗忘。
失忆（memento） 每一夜（一章）之内看得到这一夜的全部经过和昨夜的纸条；走出一章时先写一张
               不超过 B 字的纸条，然后忘掉其余一切。考的是「给明天的自己记什么」。
开卷（open_book）每一步直接给它一份完美记忆整理好的事实清单，不需要自己记，
               做得好坏只取决于理解、推理和策略。

同一个模型三种跑法相比：当夜的首答正确率反映推理和绑定，隔夜的反映记忆。
"""

import json
import random

ACTION = '每一步只输出 JSON：{"action": "走 <编号或称呼>" 或 "说 <词>"}'

FULL = f"\n\n下面是到目前为止的全部经过。{ACTION}"

OPEN_BOOK = f"\n\n你不用自己记：每一步都会给你一份到目前为止听到的全部事实。{ACTION}"

MEMENTO = ("\n\n你每走出一个地方（天亮），就会忘掉之前的一切，只剩口袋里的一张纸条，最多 {budget} 字。"
           "天亮前会让你写纸条；之后的地方可能还会用到以前的切口和人，想清楚该记什么。\n")

NOTE = ('\n\n天亮了。你马上会忘掉这一夜的一切。写下给明天的自己的纸条，最多 {budget} 字，超出部分会被截掉。'
        '只输出 JSON：{{"note": "纸条内容"}}')


class LLMAgent:
    def __init__(self, chat, instructions: str, memento: int | None = None, open_book=None, seed: int = 0):
        self.chat, self.memento, self.book = chat, memento, open_book
        self.instructions = instructions
        self.system = instructions + (MEMENTO.format(budget=memento) + ACTION if memento else
                                      OPEN_BOOK if open_book else FULL)
        self.rng = random.Random(seed)
        self.history: list[str] = []      # 全上下文：整局；失忆：这一夜
        self.note = ""                    # 失忆：昨夜写下的纸条
        self.nights: list[str] = []       # 失忆：每一夜写下的纸条，供分析
        self.last = ""                    # 开卷：上一步的动作和观察
        self.here: list[str] = []
        self.failures = 0                 # 回复无法解析的次数

    def observe(self, events: list[dict], text: str):
        if self.book:
            self.book.observe(events)
        for e in events:
            if e["type"] == "scene" and e["here"] is not None:
                self.here = [f"{i}.{look}" for i, (look, _) in enumerate(e["here"], 1)]
        self.last += text
        self.history.append(text)
        if self.memento and any(e["type"] == "next" for e in events):
            self._sleep(text)

    def act(self) -> str:
        if self.memento:
            user = self._night()
        elif self.book:
            user = (f"【听到过的全部事实】\n{self._facts()}\n\n"
                    f"【眼前】{'　'.join(self.here)}\n\n【刚才】\n{self.last}")
        else:
            user = "\n".join(self.history)
        try:
            action = str(json.loads(self.chat(self.system, user, temperature=0.3))["action"]).strip()
        except Exception:
            self.failures += 1
            action = f"走 {self.rng.randint(1, max(1, len(self.here)))}"
        self.last = f"> {action}\n"
        self.history.append(f"\n> {action}")
        return action

    def _sleep(self, text: str):
        """天亮：写纸条，忘掉其余，只留纸条和新一夜的开头。"""
        try:
            prompt = self.instructions + NOTE.format(budget=self.memento)
            reply = json.loads(self.chat(prompt, self._night(), temperature=0.3))
            self.note = str(reply["note"])[:self.memento]
        except Exception:
            self.failures += 1
        self.nights.append(self.note)
        self.history = [text]

    def _night(self) -> str:
        return f"【昨夜的纸条】\n{self.note or '（空）'}\n\n【这一夜的经过】\n" + "\n".join(self.history)

    def _facts(self) -> str:
        """把完美记忆的三类事实写成清单。"""
        f = self.book
        lines = [f"{who} 给过你 ⟨{w}⟩" for who, w in f.gave.items()]
        for who, versions in f.wants.items():
            for v, words in sorted(versions.items()):
                if words:
                    lines.append(f"{who} 要{'（改口后）' if v else ''} " + "、".join(f"⟨{w}⟩" for w in words))
        lines += [f"{t} 替 {p} 传过话" for t, p in f.told.items()]
        lines += [f"{who} 已经满足了" for who in f.done]
        return "\n".join(lines) or "（还没有）"
