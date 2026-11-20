#!/usr/bin/env python3
"""Generate a deterministic filler document of about N tokens, unique per session.

Why unique: prompt caching matches on the PREFIX. If two sessions pasted the same document, one session's call
would keep the other's cache warm and ruin the idle-gap measurement. The seed goes into the first line, so
every session diverges from every other one at the very start of the document.

Why a token estimate: counting tokens exactly needs a model or an API key, and this project uses neither
before the pilot. The size is `tokens * chars_per_token` characters. `chars_per_token` (cpt) is an ASSUMPTION
(default 4.0) until `analyze.py sizes` calibrates it from the real setup totals of the pilot.

Usage:  gen_context.py --tokens 12000 --label gap-small-1 [--cpt 4.0] > doc.txt
"""
import argparse
import hashlib
import random
import sys

MIN_TOKENS = 100

WORDS = (
    "system module request cache window record signal buffer thread queue token session branch commit review "
    "service gateway worker policy schema column index query result report budget limit error retry timeout "
    "agent tool prompt context memory prefix suffix window stream batch event handler config option default "
    "value field object array number string format output input filter sort merge split parse render deploy "
    "build test check verify measure compare select update create delete remove append insert rename replace "
    "network server client socket packet latency throughput bandwidth region cluster node volume mount path "
    "folder file archive backup restore snapshot version release patch feature flag toggle metric counter "
    "gauge trace span label tag owner team project ticket issue story epic sprint plan scope risk impact "
    "quarter weekly daily hourly monthly annual summary detail note draft final pending active closed open "
    "north south east west alpha beta gamma delta sigma lambda orbit anchor harbor meadow canyon summit river "
    "forest garden bridge lantern compass ledger ribbon marble copper silver amber cobalt violet scarlet "
    "gentle rapid steady quiet bright narrow broad simple complex stable fragile modern classic distant nearby"
).split()


def seed_for(label: str) -> int:
    """Stable integer seed from a text label such as 'gap-small-1'."""
    return int(hashlib.sha256(label.encode()).hexdigest()[:15], 16)


def generate(tokens: int, seed: int, cpt: float = 4.0) -> str:
    if tokens < MIN_TOKENS:
        raise ValueError(f"tokens must be at least {MIN_TOKENS}")
    target = int(tokens * cpt)
    rng = random.Random(seed)
    parts = [f"DOCUMENT {seed:016x}. Filler text for a caching measurement. It contains nothing to remember.\n\n"]
    size = len(parts[0])
    while size < target:
        sentences = []
        for _ in range(rng.randint(4, 8)):
            words = [rng.choice(WORDS) for _ in range(rng.randint(8, 18))]
            sentences.append(words[0].capitalize() + " " + " ".join(words[1:]) + ".")
        para = " ".join(sentences) + "\n\n"
        parts.append(para)
        size += len(para)
    return "".join(parts)[:target]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tokens", type=int, required=True)
    ap.add_argument("--cpt", type=float, default=4.0, help="chars per token (assumption until calibrated)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--label")
    g.add_argument("--seed", type=int)
    a = ap.parse_args(argv)
    seed = a.seed if a.seed is not None else seed_for(a.label)
    sys.stdout.write(generate(a.tokens, seed, a.cpt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
