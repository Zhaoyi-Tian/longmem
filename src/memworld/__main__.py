"""环境入口：memworld play，自己在世界里玩一局。跑 bench 用 membench。"""

import argparse

from . import LLMSkin, World, load


def main():
    ap = argparse.ArgumentParser(prog="memworld", description="长程记忆文字世界：自己玩一局")
    ap.add_argument("mode", choices=["play"])
    ap.add_argument("--config", help="叠加在 config/default.toml 之上的配置文件")
    ap.add_argument("--seed", type=int, help="覆盖配置里的 seed")
    ap.add_argument("--T", type=int, help="覆盖配置里的步数上限")
    ap.add_argument("--llm", action="store_true", help="用 LLM 润色台词")
    a = ap.parse_args()

    cfg = load(a.config)
    seed = cfg.seed if a.seed is None else a.seed
    skin = LLMSkin.from_config(cfg.setting, cfg.skin, seed) if a.llm or cfg.skin["llm"] else None
    world = World(cfg, seed, a.T, skin)

    print(world.instructions, "\n")
    print(world.reset())
    done = False
    while not done:
        try:
            action = input("\n> ")
        except EOFError:
            break
        obs, done, _ = world.step(action)
        print(obs)
    print(f"\n走出 {world.chapter} 章，用了 {world.t} 步。")


if __name__ == "__main__":
    main()
