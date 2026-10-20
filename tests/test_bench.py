"""用参照 agent 检验世界：可解、有长程依赖、分数随记忆长度变化。"""

import unittest
from dataclasses import replace

from membench import Memento, Oracle, Window, run
from membench.measure import first_tries, night_bucket
from memworld import World, load

CFG = load()


def oracle_run(seed, T, cfg=CFG):
    world = World(cfg, seed, T)
    run(world, Oracle(seed))
    return world


class TestBench(unittest.TestCase):
    def test_perfect_memory_never_stuck_never_wrong(self):
        heavy = load(size=7, depth=2, recall=0.8, indirect=0.7, relay=0.8, revise=0.5)
        for cfg in (CFG, heavy, load(decay=0), load(decay=3)):
            for seed in range(5):
                world = World(cfg, seed, T=10**6)
                self.assertTrue(run(world, Oracle(seed), chapters=8))
                self.assertEqual({e["kind"] for e in world.trace}, {"ok"})

    def test_same_seed_same_transcript(self):
        a, b = oracle_run(7, 200), oracle_run(7, 200)
        self.assertEqual(a.trace, b.trace)

    def test_long_range_recall_exists(self):
        ages = [e["need"][e["word"]]["age"] for e in oracle_run(3, 1500).trace]
        self.assertGreater(max(ages), 500)

    def test_decay_pulls_recall_toward_recent(self):
        def mean_age(decay):
            ages = [e["need"][e["word"]]["age"] for e in oracle_run(3, 1500, load(decay=decay)).trace]
            return sum(ages) / len(ages)
        self.assertLess(mean_age(3), mean_age(0))

    def test_shorter_memory_goes_less_far(self):
        def chapters(W):
            world = World(replace(CFG, strikes=0), 1, T=800)     # 只看记忆长度，不让乱猜被抓
            run(world, Window(W, 1))
            return world.chapter
        self.assertLess(chapters(30), chapters(300))


    def test_longer_notes_remember_more_across_nights(self):
        cfg = replace(load("config/memory.toml"), strikes=0)

        def across(B):
            ok = n = 0
            for seed in range(3):
                world = World(cfg, seed, T=500)
                run(world, Memento(B, "need", cfg.params.decay, seed, world=world))
                for e in first_tries(world.trace):
                    if night_bucket(e) == "隔夜":
                        ok, n = ok + (e["kind"] == "ok"), n + 1
            return ok / n

        self.assertLess(across(200), across(6400))
        self.assertEqual(across(10**6), 1.0)            # 纸条不限，等于完美记忆


if __name__ == "__main__":
    unittest.main()
