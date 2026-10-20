"""跑一局；以及几种检验：世界可解、记忆长度曲线、纸条曲线（程序参照）、LLM 实测。"""

import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from memworld import Config, World, load
from memworld.chat import from_config
from memworld.config import ROOT

from .agents import LLMAgent, Oracle, Window
from .agents.memento import Memento
from .measure import first_tries, night_bucket, summary


def run(world: World, agent, chapters: int | None = None, echo: bool = False) -> bool:
    """跑一局。agent 无路可走时返回 False。"""
    obs = world.reset()
    agent.observe(world.first_events, obs)
    if echo:
        print(obs, flush=True)
    done = False
    while not done and (chapters is None or world.chapter < chapters):
        action = agent.act()
        if action is None:
            return False
        obs, done, info = world.step(action)
        agent.observe(info["events"], obs)
        if echo:
            print(f"\n> {action}\n{obs}", flush=True)
    return True


def check(seeds: int = 50, chapters: int = 20) -> int:
    """在三档难度上让完美记忆 agent 走，任何一局卡住或说错都算失败。返回失败局数。"""
    configs = {"默认": load(), "hard": load(ROOT / "config/hard.toml"),
               "全开": load(recall=0.8, indirect=0.7, relay=0.8, revise=0.5)}
    bad = 0
    for name, cfg in configs.items():
        for seed in range(seeds):
            world = World(cfg, seed, T=10**6)
            ok = run(world, Oracle(seed), chapters)
            kinds = {e["kind"] for e in world.trace}
            if not ok or kinds - {"ok"}:
                bad += 1
                print(f"失败：{name} seed={seed} 第 {world.chapter} 章 {kinds}")
        print(f"{name}：{seeds} 个 seed × {chapters} 章")
    print("全部可解，完美记忆从未说错" if not bad else f"{bad} 局失败")
    return bad


def curve(cfg: Config, seeds: int = 10, T: int = 1000, windows=(10, 30, 100, 300, 1000, None)):
    """只记得最近 W 步的 agent 能走多远；None 表示完美记忆。不设被抓：只看记忆长度。"""
    cfg = replace(cfg, strikes=0)
    print(f"T = {T} 步，{seeds} 个 seed 的平均")
    print(f"{'记忆':>8}  {'走出章数':>8}  {'首答正确':>8}")
    for W in windows:
        chapters, acc = [], []
        for seed in range(seeds):
            world = World(cfg, seed, T)
            run(world, Window(W, seed) if W else Oracle(seed))
            s = summary(world.trace, world.chapter)
            chapters.append(s["chapters"])
            acc.append(s["first_try"] or 0)
        name = f"{W} 步" if W else "完美"
        print(f"{name:>8}  {statistics.mean(chapters):>8.1f}  {statistics.mean(acc):>8.2f}")


def notes(cfg: Config, seeds: int = 5, T: int = 1000, budgets=(0, 400, 800, 1600, 3200, 6400)):
    """失忆的更夫（程序参照）：三种写纸条的策略，在不同纸条长度下的隔夜首答正确率和走出章数。"""
    cfg = replace(cfg, strikes=0)
    decay = cfg.params.decay
    print(f"T = {T} 步，{seeds} 个 seed。每格：隔夜首答正确率 / 平均走出章数")
    print(f"{'纸条字数':>9}" + "".join(f"{b:>13}" for b in budgets))
    for policy in ("hindsight", "need", "recent"):
        row = []
        for B in budgets:
            ok = n = 0
            ch = []
            for seed in range(seeds):
                world = World(cfg, seed, T)
                run(world, Memento(B, policy, decay, seed, world=world))
                ch.append(world.chapter)
                for e in first_tries(world.trace):
                    if night_bucket(e) == "隔夜":
                        ok, n = ok + (e["kind"] == "ok"), n + 1
            row.append(f"{ok / n if n else 0:.0%} / {statistics.mean(ch):.1f}")
        print(f"{policy:>9}" + "".join(f"{x:>13}" for x in row))


def llm(cfg: Config, modes: list[str], seeds: int, T: int, out: Path):
    """用 LLM 跑：full 全上下文，mB 失忆（纸条 B 字），book 开卷。每局一个 JSON，最后汇总首答正确率。"""
    chat = from_config(cfg.skin, timeout=90, max_tokens=1500)
    out.mkdir(parents=True, exist_ok=True)

    def one(mode: str, seed: int) -> dict:
        world = World(cfg, seed, T)
        agent = LLMAgent(chat, world.instructions, seed=seed,
                         memento=int(mode[1:]) if mode.startswith("m") else None,
                         open_book=Oracle(seed) if mode == "book" else None)
        run(world, agent)
        r = {"mode": mode, "seed": seed, "T": T, "summary": summary(world.trace, world.chapter),
             "caught": world.caught, "failures": agent.failures, "nights": agent.nights,
             "trace": world.trace, "history": agent.history}
        (out / f"{mode}_s{seed}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        return r

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda a: one(*a), [(m, s) for m in modes for s in range(seeds)]))
    for mode in modes:
        rs = [r for r in results if r["mode"] == mode]
        tally = {"当夜": [0, 0], "隔夜": [0, 0]}
        for r in rs:
            for e in first_tries(r["trace"]):
                t = tally[night_bucket(e)]
                t[0], t[1] = t[0] + (e["kind"] == "ok"), t[1] + 1
        cell = {k: f"{a}/{b}" + (f" = {a / b:.0%}" if b else "") for k, (a, b) in tally.items()}
        print(f"{mode:>6}  章 {[r['summary']['chapters'] for r in rs]}  "
              f"首答 当夜 {cell['当夜']}  隔夜 {cell['隔夜']}")
