"""Aviation-weighted ASR scoring.

General WER is the wrong gate for an aviation copilot. A backend that drops
"uh" and "the" while nailing every altitude is safe; one with a better headline
WER that hears "one zero thousand" as "one thousand" is not. Published
leaderboard WER is dominated by conversational filler, so it does not
discriminate between those two cases at all.

This module therefore reports three numbers, in increasing order of importance:

``wer``
    Standard word error rate over normalized tokens. Included for continuity
    with published benchmarks -- not the gate.

``cter``
    Critical token error rate: WER restricted to tokens that carry operational
    meaning (digits, phonetic alphabet, V-speeds, aviation nouns).

``value_recall``
    Fraction of reference *values* -- digit sequences, frequencies, V-speeds --
    that survived into the hypothesis at all. This is the safety metric: it asks
    "did MERLIN hear the right altitude", independent of surrounding wording.

Normalization deliberately maps spoken digits to characters ("two seven zero"
-> "270") because ICAO phraseology is digit-by-digit, so a hypothesis and
reference can be lexically different while carrying identical meaning.

Known limitation: compound magnitudes ("one zero thousand") are normalized to
their digit run plus the magnitude word, not evaluated arithmetically. Comparing
"10 thousand" against "1 thousand" therefore registers as a value miss, which is
the desired outcome, but this module does not claim to fully parse numerals.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: Spoken digit -> character. Includes the ICAO pronunciation variants that
#: radio operators actually use, which off-the-shelf normalizers miss.
_DIGIT_WORDS: dict[str, str] = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "tree": "3",
    "four": "4",
    "fower": "4",
    "five": "5",
    "fife": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "ait": "8",
    "nine": "9",
    "niner": "9",
}

_PHONETIC = frozenset(
    [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
        "quebec",
        "romeo",
        "sierra",
        "tango",
        "uniform",
        "victor",
        "whiskey",
        "xray",
        "x-ray",
        "yankee",
        "zulu",
    ]
)

_VSPEEDS = frozenset(
    [
        "v1",
        "vr",
        "v2",
        "vref",
        "vne",
        "vno",
        "vs0",
        "vs1",
        "vfe",
        "vle",
        "vlo",
        "vmc",
        "vx",
        "vy",
        "va",
    ]
)

#: Operational nouns whose loss changes meaning. Not exhaustive -- extend as
#: real misrecognitions show up in the corpus.
_AVIATION_NOUNS = frozenset(
    [
        "altitude",
        "heading",
        "airspeed",
        "squawk",
        "runway",
        "flaps",
        "gear",
        "trim",
        "throttle",
        "mixture",
        "altimeter",
        "climb",
        "descend",
        "maintain",
        "cleared",
        "takeoff",
        "landing",
        "approach",
        "abort",
        "mayday",
        "panpan",
        "pan-pan",
        "feet",
        "knots",
        "left",
        "right",
        "level",
        "flight",
        "taxi",
        "hold",
        "short",
        "gonogo",
        "go-around",
        "missed",
        "ils",
        "vor",
        "ndb",
        "dme",
        "atis",
        "metar",
        "taf",
        "qnh",
        "qfe",
    ]
)

_MAGNITUDES = frozenset({"hundred", "thousand", "point", "decimal"})

CRITICAL_CATEGORIES = ("digits", "phonetic", "vspeed", "aviation_noun")

_PUNCT = re.compile(r"[^\w\s.\-]")
_MULTISPACE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_tokens(text: str) -> list[str]:
    """Lowercase, strip punctuation, and fold spoken digits into digit runs.

    Consecutive spoken digits collapse into one token so that "two seven zero"
    and "270" compare equal -- both become ``["270"]``.
    """
    text = unicodedata.normalize("NFKC", text).lower()
    text = _PUNCT.sub(" ", text)
    text = _MULTISPACE.sub(" ", text).strip()
    if not text:
        return []

    tokens: list[str] = []
    digit_run: list[str] = []

    def flush() -> None:
        if digit_run:
            tokens.append("".join(digit_run))
            digit_run.clear()

    for raw in text.split(" "):
        word = raw.strip(".-")
        if not word:
            continue
        if word in _DIGIT_WORDS:
            digit_run.append(_DIGIT_WORDS[word])
            continue
        # A bare numeral contributes its digits to the same run, so "fl 350"
        # and "flight level three five zero" converge.
        if word.isdigit():
            digit_run.append(word)
            continue
        # Decimal numerals ("121.5") keep their point as a value token.
        if re.fullmatch(r"\d+\.\d+", word):
            flush()
            tokens.append(word)
            continue
        flush()
        tokens.append(word)

    flush()
    return tokens


def classify(token: str) -> str | None:
    """Return the critical category of *token*, or ``None`` if it is filler."""
    if re.fullmatch(r"[\d.]+", token):
        return "digits"
    if token in _PHONETIC:
        return "phonetic"
    if token in _VSPEEDS:
        return "vspeed"
    if token in _AVIATION_NOUNS:
        return "aviation_noun"
    return None


def extract_values(tokens: list[str]) -> list[str]:
    """Pull the operationally meaningful values out of a normalized token list.

    Digit runs and decimals carry a magnitude word when one immediately follows,
    so "10 thousand" stays distinguishable from a bare "10".
    """
    values: list[str] = []
    for i, token in enumerate(tokens):
        if re.fullmatch(r"[\d.]+", token):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            values.append(f"{token} {nxt}" if nxt in _MAGNITUDES else token)
        elif token in _VSPEEDS:
            values.append(token)
    return values


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _edit_ops(ref: list[str], hyp: list[str]) -> tuple[int, int, int, list[tuple[str, str, str]]]:
    """Levenshtein alignment returning (subs, dels, ins, per-op trace)."""
    n, m = len(ref), len(hyp)
    # dp[i][j] = cost of aligning ref[:i] with hyp[:j]
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j - 1], dp[i - 1][j], dp[i][j - 1])

    subs = dels = ins = 0
    trace: list[tuple[str, str, str]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            trace.append(("ok", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            subs += 1
            trace.append(("sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dels += 1
            trace.append(("del", ref[i - 1], ""))
            i -= 1
        else:
            ins += 1
            trace.append(("ins", "", hyp[j - 1]))
            j -= 1
    trace.reverse()
    return subs, dels, ins, trace


@dataclass
class AviationScore:
    """Scores for one utterance or an aggregated corpus."""

    wer: float = 0.0
    cter: float = 0.0
    value_recall: float = 1.0
    ref_tokens: int = 0
    critical_tokens: int = 0
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0
    critical_errors: int = 0
    values_expected: int = 0
    values_found: int = 0
    per_category: dict[str, int] = field(default_factory=dict)
    missed_values: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """One-line human-readable form for CLI output."""
        return (
            f"WER {self.wer:6.2%} | CTER {self.cter:6.2%} | "
            f"value-recall {self.value_recall:6.2%} "
            f"({self.values_found}/{self.values_expected} values, "
            f"{self.critical_errors}/{self.critical_tokens} critical errors)"
        )


def score_transcript(reference: str, hypothesis: str) -> AviationScore:
    """Score a single hypothesis against its reference."""
    ref = normalize_tokens(reference)
    hyp = normalize_tokens(hypothesis)
    subs, dels, ins, trace = _edit_ops(ref, hyp)

    critical_total = 0
    critical_errors = 0
    per_category: dict[str, int] = {}
    for op, ref_tok, _hyp_tok in trace:
        category = classify(ref_tok) if ref_tok else None
        if category is None:
            continue
        critical_total += 1
        if op != "ok":
            critical_errors += 1
            per_category[category] = per_category.get(category, 0) + 1

    expected = extract_values(ref)
    available = list(extract_values(hyp))
    found = 0
    missed: list[str] = []
    for value in expected:
        if value in available:
            available.remove(value)  # consume, so duplicates must both appear
            found += 1
        else:
            missed.append(value)

    return AviationScore(
        wer=(subs + dels + ins) / len(ref) if ref else 0.0,
        cter=critical_errors / critical_total if critical_total else 0.0,
        value_recall=found / len(expected) if expected else 1.0,
        ref_tokens=len(ref),
        critical_tokens=critical_total,
        substitutions=subs,
        deletions=dels,
        insertions=ins,
        critical_errors=critical_errors,
        values_expected=len(expected),
        values_found=found,
        per_category=per_category,
        missed_values=missed,
    )


def score_corpus(pairs: list[tuple[str, str]]) -> AviationScore:
    """Aggregate scores over ``(reference, hypothesis)`` pairs.

    Rates are computed from summed counts rather than averaged per-utterance, so
    a long utterance carries proportional weight instead of one short mistake
    dominating the corpus.
    """
    total = AviationScore()
    for reference, hypothesis in pairs:
        s = score_transcript(reference, hypothesis)
        total.ref_tokens += s.ref_tokens
        total.critical_tokens += s.critical_tokens
        total.substitutions += s.substitutions
        total.deletions += s.deletions
        total.insertions += s.insertions
        total.critical_errors += s.critical_errors
        total.values_expected += s.values_expected
        total.values_found += s.values_found
        total.missed_values.extend(s.missed_values)
        for category, count in s.per_category.items():
            total.per_category[category] = total.per_category.get(category, 0) + count

    errors = total.substitutions + total.deletions + total.insertions
    total.wer = errors / total.ref_tokens if total.ref_tokens else 0.0
    total.cter = total.critical_errors / total.critical_tokens if total.critical_tokens else 0.0
    total.value_recall = (
        total.values_found / total.values_expected if total.values_expected else 1.0
    )
    return total
