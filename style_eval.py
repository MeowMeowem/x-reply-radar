"""Fit evaluation from the command line (the Learn page runs the same thing).

  python style_eval.py            current style notes + examples
  python style_eval.py --base     persona only, nothing learned (the baseline)
"""
import sys

import config
import store
from ai import style


def main():
    e = config.env()
    store.init()
    base = "--base" in sys.argv
    active = store.active_style_version()
    score = style.evaluate(e, label="baseline" if base else "current", use_learned=not base,
                           version_id=None if base else (active and active["id"]))
    print("no real replies to compare with yet" if score is None else f"fit score: {score:.2f} / 10")


if __name__ == "__main__":
    main()
