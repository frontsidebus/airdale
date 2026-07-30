"""Tests for aviation-weighted ASR scoring.

The central requirement: the metric must distinguish a harmless error from a
dangerous one. A backend that drops filler words should score well; one that
mishears an altitude must not, even if its headline WER is lower.
"""

from __future__ import annotations

import pytest

from orchestrator.eval.aviation_wer import (
    AviationScore,
    classify,
    extract_values,
    normalize_tokens,
    score_corpus,
    score_transcript,
)


class TestNormalization:
    def test_spoken_digits_collapse_into_one_run(self) -> None:
        assert normalize_tokens("two seven zero") == ["270"]

    def test_spoken_and_numeric_forms_converge(self) -> None:
        assert normalize_tokens("heading two seven zero") == normalize_tokens("heading 270")

    def test_icao_pronunciation_variants(self) -> None:
        """'niner', 'tree', 'fife' are what pilots actually say."""
        assert normalize_tokens("niner tree fife") == ["935"]

    def test_oh_is_treated_as_zero(self) -> None:
        assert normalize_tokens("one oh five") == ["105"]

    def test_decimal_frequency_preserved(self) -> None:
        assert "121.5" in normalize_tokens("contact tower on 121.5")

    def test_punctuation_and_case_ignored(self) -> None:
        assert normalize_tokens("Gear UP, now!") == normalize_tokens("gear up now")

    def test_empty_input(self) -> None:
        assert normalize_tokens("") == []
        assert normalize_tokens("   ") == []

    def test_digit_run_broken_by_a_word(self) -> None:
        assert normalize_tokens("two seven zero at one five zero") == ["270", "at", "150"]


class TestClassification:
    @pytest.mark.parametrize(
        ("token", "expected"),
        [
            ("270", "digits"),
            ("121.5", "digits"),
            ("alpha", "phonetic"),
            ("zulu", "phonetic"),
            ("vref", "vspeed"),
            ("v1", "vspeed"),
            ("altitude", "aviation_noun"),
            ("squawk", "aviation_noun"),
            ("the", None),
            ("uh", None),
        ],
    )
    def test_categories(self, token: str, expected: str | None) -> None:
        assert classify(token) == expected


class TestValueExtraction:
    def test_magnitude_word_binds_to_its_digits(self) -> None:
        assert extract_values(normalize_tokens("descend to one zero thousand")) == ["10 thousand"]

    def test_bare_digits_have_no_magnitude(self) -> None:
        assert extract_values(normalize_tokens("heading two seven zero")) == ["270"]

    def test_vspeeds_are_values(self) -> None:
        assert "vref" in extract_values(normalize_tokens("vref plus five"))


class TestSafetyDiscrimination:
    """The reason this module exists."""

    def test_filler_only_errors_leave_values_intact(self) -> None:
        score = score_transcript(
            "uh descend and maintain one zero thousand feet",
            "descend and maintain one zero thousand feet",
        )
        assert score.wer > 0  # a real word was dropped
        assert score.cter == 0.0  # but nothing operational was lost
        assert score.value_recall == 1.0

    def test_altitude_misrecognition_is_caught(self) -> None:
        """'one zero thousand' -> 'one thousand' is the canonical dangerous error."""
        score = score_transcript(
            "descend and maintain one zero thousand feet",
            "descend and maintain one thousand feet",
        )
        assert score.value_recall < 1.0
        assert "10 thousand" in score.missed_values
        assert score.per_category.get("digits", 0) >= 1

    def test_a_lower_wer_can_still_be_the_worse_backend(self) -> None:
        """This is the case published WER cannot see."""
        reference = "uh so descend and maintain one zero thousand feet please"
        chatty_but_accurate = "so descend and maintain one zero thousand feet"
        clean_but_wrong = "uh so descend and maintain one thousand feet please"

        safe = score_transcript(reference, chatty_but_accurate)
        unsafe = score_transcript(reference, clean_but_wrong)

        assert safe.wer > unsafe.wer, "precondition: the unsafe hypothesis has a better WER"
        assert safe.value_recall == 1.0
        assert unsafe.value_recall < 1.0
        assert unsafe.cter > safe.cter

    def test_squawk_code_digit_error(self) -> None:
        score = score_transcript("squawk seven seven zero zero", "squawk seven seven two zero")
        assert score.value_recall == 0.0
        assert score.missed_values == ["7700"]

    def test_frequency_error_caught(self) -> None:
        score = score_transcript("contact tower on 121.5", "contact tower on 121.9")
        assert score.value_recall == 0.0

    def test_phonetic_callsign_error_is_critical(self) -> None:
        score = score_transcript(
            "cleared to land november one two three alpha bravo",
            "cleared to land november one two three alpha delta",
        )
        assert score.cter > 0
        assert score.per_category.get("phonetic", 0) >= 1

    def test_perfect_transcript_scores_clean(self) -> None:
        text = "cleared for takeoff runway two seven left"
        score = score_transcript(text, text)
        assert score.wer == 0.0
        assert score.cter == 0.0
        assert score.value_recall == 1.0

    def test_duplicate_values_must_both_appear(self) -> None:
        """Hearing one '270' when two were said is a miss, not a match."""
        score = score_transcript(
            "turn two seven zero then hold two seven zero",
            "turn two seven zero then hold",
        )
        assert score.values_expected == 2
        assert score.values_found == 1
        assert score.value_recall == pytest.approx(0.5)


class TestEdgeCases:
    def test_empty_reference_is_not_a_division_error(self) -> None:
        score = score_transcript("", "")
        assert score.wer == 0.0
        assert score.value_recall == 1.0

    def test_total_miss(self) -> None:
        score = score_transcript("gear up", "")
        assert score.wer == 1.0
        assert score.deletions == 2

    def test_no_values_in_reference_yields_full_recall(self) -> None:
        """Absence of values must not be reported as a failure."""
        score = score_transcript("roger that", "roger that")
        assert score.values_expected == 0
        assert score.value_recall == 1.0


class TestCorpusAggregation:
    def test_rates_come_from_summed_counts_not_averaged_rates(self) -> None:
        """A one-word utterance must not outweigh a twenty-word one."""
        long_utterance = "descend and maintain one zero thousand feet on heading two seven zero now"
        # Normalizes to 10 tokens -- the spoken digit runs collapse to "10" and "270".
        assert len(normalize_tokens(long_utterance)) == 10
        pairs = [
            ("gear", "flaps"),  # 1 token, 1 substitution
            (long_utterance, long_utterance),  # 10 tokens, no errors
        ]
        score = score_corpus(pairs)
        assert score.ref_tokens == 11
        # Averaging per-utterance rates would give 50%; summed counts give 1/11.
        assert score.wer == pytest.approx(1 / 11)

    def test_counts_and_misses_accumulate(self) -> None:
        pairs = [
            ("squawk seven seven zero zero", "squawk seven seven two zero"),
            ("heading two seven zero", "heading two seven zero"),
        ]
        score = score_corpus(pairs)
        assert score.values_expected == 2
        assert score.values_found == 1
        assert score.missed_values == ["7700"]

    def test_empty_corpus(self) -> None:
        score = score_corpus([])
        assert isinstance(score, AviationScore)
        assert score.wer == 0.0
        assert score.value_recall == 1.0

    def test_summary_is_renderable(self) -> None:
        score = score_corpus([("heading two seven zero", "heading two seven zero")])
        assert "value-recall" in score.summary()
