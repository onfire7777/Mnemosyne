"""Descriptive native LoCoMo category summaries, with no invented uncertainty."""
import math
import re

KIND = "locomo-native-category/v1"
FIELDS = {"summary_kind", "name", "family", "category", "value", "unit", "confidence_interval",
          "uncertainty_method", "numerator", "denominator", "source_count", "observed_count",
          "missing_count", "not_applicable_count", "status", "scorer_digest"}


def category_metric(group, category, *, family, scorer_digest):
    qa = family == "reference_qa"
    source, observed = group["source_count"], group["scored_count"]
    denominator = source if qa else group["native_recall_count"]
    numerator = group["rounded_qa_sum"] if qa else group["native_recall_sum"]
    missing = group["missing_count"]
    status = ("absent-category" if not source else "incomplete" if missing
              else "not-applicable" if not denominator else "measured")
    return {"summary_kind": KIND, "name": f'{"qa" if qa else "evidence_recall"}_category_{category}',
            "family": family, "category": category, "value": numerator / denominator if denominator else None,
            "unit": "ratio", "confidence_interval": None, "uncertainty_method": "not-estimated",
            "numerator": numerator, "denominator": denominator, "source_count": source,
            "observed_count": observed, "missing_count": missing,
            "not_applicable_count": 0 if qa else observed - denominator,
            "status": status, "scorer_digest": scorer_digest}


def validate_category_metric(metric, pointer):
    """Validate schema and arithmetic; these checks do not authenticate a run."""
    if not isinstance(metric, dict) or set(metric) != FIELDS:
        return [pointer]
    errors = []
    for key, expected in (("summary_kind", KIND), ("unit", "ratio"),
                          ("confidence_interval", None), ("uncertainty_method", "not-estimated")):
        if metric[key] != expected:
            errors.append(f"{pointer}/{key}")
    family, category = metric["family"], metric["category"]
    if family not in ("reference_qa", "retrieval"):
        errors.append(f"{pointer}/family")
    if type(category) is not int or category not in range(1, 6):
        errors.append(f"{pointer}/category")
    name = f'{"qa" if family == "reference_qa" else "evidence_recall"}_category_{category}'
    if metric["name"] != name:
        errors.append(f"{pointer}/name")
    if not isinstance(metric["scorer_digest"], str) or not re.fullmatch("sha256:[0-9a-f]{64}", metric["scorer_digest"]):
        errors.append(f"{pointer}/scorer_digest")
    counts = ("denominator", "source_count", "observed_count", "missing_count", "not_applicable_count")
    if any(type(metric[key]) is not int or metric[key] < 0 for key in counts):
        return errors + [f"{pointer}/counts"]
    source, observed, missing = (metric[key] for key in ("source_count", "observed_count", "missing_count"))
    denominator, na = metric["denominator"], metric["not_applicable_count"]
    if observed + missing != source or na > observed:
        errors.append(f"{pointer}/counts")
    if denominator != (source if family == "reference_qa" else observed - na) or (family == "reference_qa" and na):
        errors.append(f"{pointer}/denominator")
    numerator = metric["numerator"]
    if type(numerator) not in (int, float) or not math.isfinite(numerator) or not 0 <= numerator <= observed - na:
        errors.append(f"{pointer}/numerator")
    elif denominator:
        value = metric["value"]
        if type(value) not in (int, float) or not math.isfinite(value) or value != numerator / denominator:
            errors.append(f"{pointer}/value")
    elif metric["value"] is not None or numerator != 0:
        errors.append(f"{pointer}/value")
    expected_status = ("absent-category" if not source else "incomplete" if missing
                       else "not-applicable" if not denominator else "measured")
    if metric["status"] != expected_status:
        errors.append(f"{pointer}/status")
    return errors
