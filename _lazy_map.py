"""
_lazy_map.py — Phase 2 FIX2 (2026-06-06)
=========================================
import-time-safe 唯讀 lazy Mapping 代理。

延遲 loader 到「首次真正存取」才執行，避免 module import 當下就讀
owner_projection.generated.json —— 那會讓 `--force-skip-validation`/`--help`/
test import 在 JSON 缺/壞時直接炸（Phase 2 三審 r1 Codex P0-3）。

用法
----
    from _lazy_map import LazyMap
    OWNER_MAP = LazyMap(_load_owner_map)   # import 時零 I/O
    OWNER_MAP.keys()                        # 首次存取才呼叫 loader

支援 mapping 唯讀全套：`[]` / `in` / `iter` / `len` / `keys` / `values` /
`items` / `get` / `== dict` / `**unpack` / `dict(x)` / `sorted(x)`。
不可變、不可 hash（與「會變內容的 mapping」一致）。json.dumps 請用 .as_dict()。
"""
from __future__ import annotations

import threading
from collections.abc import Mapping


class LazyMap(Mapping):
    """延遲建構的唯讀 dict 代理；loader 必回 dict；首次存取才呼叫（thread-safe）。"""

    __slots__ = ("_loader", "_data", "_lock")
    __hash__ = None  # 定義了 __eq__ 的可變語義 mapping 不可 hash（與 dict 一致）

    def __init__(self, loader):
        self._loader = loader
        self._data = None
        self._lock = threading.RLock()

    def _materialize(self) -> dict:
        if self._data is None:
            with self._lock:
                if self._data is None:  # double-checked
                    d = self._loader()
                    if not isinstance(d, dict):
                        raise TypeError(
                            f"LazyMap loader 必須回 dict，得到 {type(d).__name__}"
                        )
                    self._data = d
        return self._data

    def __getitem__(self, key):
        return self._materialize()[key]

    def __iter__(self):
        return iter(self._materialize())

    def __len__(self):
        return len(self._materialize())

    def __eq__(self, other):
        if isinstance(other, LazyMap):
            other = other._materialize()
        return self._materialize() == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return f"LazyMap(loaded={self._data is not None})"

    def as_dict(self) -> dict:
        """底層 dict 的淺拷貝（給 json.dumps / debug；不影響 lazy 語義）。"""
        return dict(self._materialize())
