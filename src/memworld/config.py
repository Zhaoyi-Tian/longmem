"""读取配置（规则旋钮、运行、润色）和世界观。"""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # 仓库根目录：config/、settings/ 在这里
DEFAULT = ROOT / "config" / "default.toml"


@dataclass(frozen=True)
class Params:
    """规则旋钮，含义见 config/default.toml。"""
    # 指代
    recall: float
    decay: float
    indirect: float
    # 转述
    relay: float
    revise: float
    # 补给
    size: int
    depth: int
    # 爬坡
    ramp: int

    def __post_init__(self):
        for k in ("recall", "indirect", "relay", "revise"):
            assert 0 <= getattr(self, k) < 1, f"{k} 是概率，须在 [0, 1) 之间"
        assert self.size >= 1 and self.depth >= 0 and self.decay >= 0 and self.ramp >= 0


@dataclass(frozen=True)
class Family:
    patterns: list[str]
    grow: str


@dataclass
class Setting:
    """世界观：只决定怎么说。"""
    name: str
    background: str
    tone: str
    intro: str
    syllables: str
    spots: list[str]
    roles: dict[str, str]
    slots: dict[str, list[str]]
    names: dict[str, Family]
    terms: dict[str, str]
    scene: dict[str, str]
    lines: dict[str, list[str]]

    @classmethod
    def load(cls, path: str | Path) -> "Setting":
        d = tomllib.loads(Path(path).read_text())
        d["slots"] = {**d["slots"], "role": list(d["roles"])}
        d["names"] = {k: Family(**v) for k, v in d["names"].items()}
        for p in d["names"]["look"].patterns:
            assert p.endswith("{role}"), "人的称呼须以 {role} 结尾"
        return cls(**{f.name: d[f.name] for f in fields(cls)})

    def persona(self, look: str) -> str | None:
        roles = [r for r in self.roles if look.endswith(r)]
        return self.roles[max(roles, key=len)] if roles else None


@dataclass
class Config:
    params: Params
    seed: int
    T: int
    strikes: int
    setting: Setting
    skin: dict


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return out


def load(path: str | Path | None = None, **knobs) -> Config:
    """读 default.toml，再叠加 path 指定的配置，最后叠加关键字参数里的规则旋钮，
    例如 load("config/hard.toml", decay=2)。"""
    d = tomllib.loads(DEFAULT.read_text())
    if path:
        d = _merge(d, tomllib.loads(Path(path).read_text()))
    run = d["run"]
    params = Params(**{**d["memory"], **d["structure"], **knobs})
    return Config(params, run["seed"], run["T"], run["strikes"],
                  Setting.load(ROOT / run["setting"]), d["skin"])


def secret(name: str) -> str | None:
    """从环境变量读取；没有的话，从项目根目录往上找 .env（几个项目可以共用一份）。"""
    if name in os.environ:
        return os.environ[name]
    for d in (ROOT, *ROOT.parents[:2]):
        env = d / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() == name:
                    return v.strip()
    return None
