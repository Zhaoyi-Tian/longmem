"""环境本身：确定性、命名、改口、润色皮的回退。"""

import json
import random
import unittest

from memworld import LLMSkin, World, load
from memworld.world.names import Namer

CFG = load()


class TestEnv(unittest.TestCase):
    def test_same_seed_same_world(self):
        def people(seed):
            world = World(CFG, seed)
            world.reset()
            world.gen.chapter(5)
            return [(p.look, p.wants, p.gift) for p in world.people.values()]
        self.assertEqual(people(7), people(7))
        self.assertNotEqual(people(7), people(8))

    def test_revision_makes_old_word_stale(self):
        world = World(load(revise=0.6, relay=0.0, ramp=0), 0)
        world.reset()
        p = next(q for q in world.people.values() if len(q.says) > 1)
        old = next(w for w in p.says[0].words if w not in p.says[1].words)
        world.heard_ver[p.pid][1] = 0        # 假装已经听过改口
        world.region, world.at = p.region, p.pid
        world._say(old)
        self.assertEqual(world.trace[-1]["kind"], "stale")

    def test_names_never_run_out(self):
        namer, rng = Namer(CFG.setting), random.Random(0)
        looks = [namer.name("look", rng) for _ in range(20000)]
        words = [namer.word(rng) for _ in range(20000)]
        self.assertEqual(len(set(looks)), len(looks))
        self.assertEqual(len(set(words)), len(words))

    def test_llm_skin_keeps_words_or_falls_back(self):
        events = [{"type": "give", "who": "独眼的刀客", "word": "哩咯"},
                  {"type": "give", "who": "光头的和尚", "word": "喳嗬"}]

        def chat(system, user, temperature=1.0):
            return '{"lines": ["独眼的刀客把 ⟨哩咯⟩ 塞进你手里。", "和尚念了句 ⟨喳⟩。"]}'

        text = LLMSkin(CFG.setting, chat).render(events)
        self.assertIn("塞进你手里", text)          # 第一行合格，用润色句
        self.assertIn("⟨喳嗬⟩", text)              # 第二行改了切口，退回模板句

    def test_llm_skin_checks_indirect_mentions_by_back_translation(self):
        ask = {"type": "ask", "who": "独眼的刀客", "self": True, "version": 0,
               "target": None, "terms": [("gift", ("target", ("look", "光头的和尚")))]}
        polished = "独眼的刀客眯眼：「光头的和尚替谁带过话？那人塞给你的那句，说来听听。」"

        def skin(steps):
            def chat(system, user, temperature=1.0):
                if "核对" in system:            # 回译
                    return json.dumps({"lines": [{"items": [{"anchor": "光头的和尚", "steps": steps}]}]})
                return json.dumps({"lines": [polished]}, ensure_ascii=False)
            return LLMSkin(CFG.setting, chat).render([ask])

        self.assertEqual(skin(["target", "gift"]), polished)        # 回译一致，采用
        self.assertNotEqual(skin(["teller", "gift"]), polished)     # 关系错了，退回模板句


if __name__ == "__main__":
    unittest.main()
