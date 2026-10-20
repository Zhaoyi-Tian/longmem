"""bench 入口：membench {demo,check,curve,notes,llm}。"""

import argparse
import json
import sys
from pathlib import Path

from memworld import LLMSkin, World, load

from . import Oracle, run, summary
from .run import check, curve, llm, notes


def main():
    ap = argparse.ArgumentParser(prog="membench", description="在 memworld 上跑 bench")
    ap.add_argument("mode", choices=["demo", "check", "curve", "notes", "llm"],
                    help="demo 看完美记忆 agent 走一局；check 验证世界可解；curve 记忆长度曲线；"
                         "notes 失忆更夫的纸条曲线（程序参照）；llm 用 LLM 实测")
    ap.add_argument("--config", help="叠加在 config/default.toml 之上的配置文件，例如 config/memory.toml")
    ap.add_argument("--seed", type=int, help="demo：覆盖配置里的 seed")
    ap.add_argument("--T", type=int, help="覆盖配置里的步数上限")
    ap.add_argument("--llm", action="store_true", help="demo：用 LLM 润色台词")
    ap.add_argument("--seeds", type=int, help="check / curve / notes / llm 用多少个 seed")
    ap.add_argument("--chapters", type=int, default=20, help="check 每局走几章")
    ap.add_argument("--modes", default="full,m800,m3200",
                    help="llm：full 全上下文，mB 失忆纸条 B 字，book 开卷")
    ap.add_argument("--out", default="results", help="llm：每局结果存放的目录")
    a = ap.parse_args()

    cfg = load(a.config)
    if a.mode == "check":
        sys.exit(1 if check(a.seeds or 50, a.chapters) else 0)
    if a.mode == "curve":
        return curve(cfg, a.seeds or 10, a.T or cfg.T)
    if a.mode == "notes":
        return notes(cfg, a.seeds or 5, a.T or cfg.T)
    if a.mode == "llm":
        return llm(cfg, a.modes.split(","), a.seeds or 2, a.T or 400, Path(a.out))

    seed = cfg.seed if a.seed is None else a.seed
    skin = LLMSkin.from_config(cfg.setting, cfg.skin, seed) if a.llm or cfg.skin["llm"] else None
    world = World(cfg, seed, a.T, skin)
    print(world.instructions, "\n")
    run(world, Oracle(seed), echo=True)
    print(json.dumps(summary(world.trace, world.chapter), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
