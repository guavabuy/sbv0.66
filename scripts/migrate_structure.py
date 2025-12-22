from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _info(msg: str) -> None:
    print(f"[migrate] {msg}")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _move_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        _info(f"skip (target exists): {dst}")
        return
    _ensure_dir(dst.parent)
    _info(f"move: {src} -> {dst}")
    shutil.move(str(src), str(dst))


def main() -> None:
    data_dir = ROOT / "data"
    raw_dir = data_dir / "raw"
    logs_dir = ROOT / "logs"
    dialogs_dir = logs_dir / "dialogs"

    _ensure_dir(raw_dir)
    _ensure_dir(dialogs_dir)

    # outputs -> data
    _move_if_exists(ROOT / "outputs" / "corpus.jsonl", data_dir / "corpus.jsonl")
    _move_if_exists(ROOT / "outputs" / "user_profile.md", data_dir / "user_profile.md")
    _move_if_exists(ROOT / "outputs" / "brain_memory.md", data_dir / "brain_memory.md")

    # outputs/dialogs -> logs/dialogs
    _move_if_exists(ROOT / "outputs" / "dialogs", dialogs_dir)

    # data_sources -> data/raw（仅在 raw_dir 为空时迁移，避免覆盖）
    data_sources = ROOT / "data_sources"
    if data_sources.exists():
        try:
            has_any = any(raw_dir.iterdir())
        except Exception:
            has_any = False

        if has_any:
            _info("skip moving data_sources -> data/raw (data/raw not empty)")
        else:
            _info(f"move children: {data_sources} -> {raw_dir}")
            _ensure_dir(raw_dir)
            for child in data_sources.iterdir():
                _move_if_exists(child, raw_dir / child.name)
            try:
                data_sources.rmdir()
            except Exception:
                pass

    _info("done.")


if __name__ == "__main__":
    main()


