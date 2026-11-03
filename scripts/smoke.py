"""Smoke test: ask the live brain about one message and print its decision.

Usage: uv run python scripts/smoke.py "how much for 100 black and white pages"
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.brain import Brain  # noqa: E402
from brain.kb import load_kb  # noqa: E402
from brain.llm import make_client  # noqa: E402
from brain.schema import IncomingMessage  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: python scripts/smoke.py "customer message"')
    kb = load_kb(ROOT / "kb" / "the-plug.md")
    brain = Brain(kb, make_client("gpt-6-luna", effort="medium"), allow_no_reply=False)
    result = brain.decide(IncomingMessage(text=" ".join(sys.argv[1:])))
    print(result.decision.model_dump_json(indent=2))
    print(
        f"model={brain.client.model} attempts={len(result.attempts)} fallback_used={result.fallback_used} "
        f"tokens: in={result.input_tokens} out={result.output_tokens} cache_read={result.cache_read_tokens}"
    )


if __name__ == "__main__":
    main()
