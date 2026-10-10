"""Release attempts must fail closed without independent net evidence."""
from copy import deepcopy

from app.research.v6hbr_release_readiness import (
    PROOF_KEYS, assess_release_readiness,
)


def complete_manifest():
    data = {
        "schema": 1,
        "candidate": "V6HBR",
        "reviewed_commit_sha": "a"*40,
        "source_hashes_frozen": True,
        "production_modified_by_research": False,
        "strategy_selected_using_holdout": False,
        "data_scope": "INDEPENDENT_MULTI_SYMBOL_VALIDATION_AND_HOLDOUT",
        "validation_resolved": 120,
        "validation_symbols": 15,
        "holdout_resolved": 110,
        "holdout_symbols": 12,
        "validation_net_r_after_costs": "7.4",
        "holdout_net_r_after_costs": "3.2",
        "validation_lower95_mean_net_r": "0.03",
        "holdout_lower95_mean_net_r": "0.01",
        "validation_stressed_net_r_after_costs": "1.1",
        "holdout_stressed_net_r_after_costs": "0.8",
        "candidate_mtm_max_drawdown_r": "6.1",
        "baseline_mtm_max_drawdown_r": "7.5",
        "operator_signoff": True,
        "independent_reviewer_signoff": True,
    }
    data.update({key: True for key in PROOF_KEYS})
    return data


def test_missing_manifests_never_enable_live_release():
    for data in (None, {}, {"schema": 1}, []):
        report = assess_release_readiness(data)
        assert report["decision"] == "NO_GO_FOR_LIVE_V6HBR"
        assert report["can_auto_deploy"] is False
        assert report["can_claim_high_accuracy"] is False


def test_btc_only_success_and_unit_tests_cannot_satisfy_live_gate():
    data = complete_manifest()
    data["data_scope"] = "BTC_APR_MAY_DEVELOPMENT_ONLY"
    data["validation_resolved"] = 24
    data["validation_symbols"] = 1
    data["validation_lower95_mean_net_r"] = "-0.1"
    data["holdout_resolved"] = 0
    data["holdout_symbols"] = 0
    data["holdout_net_r_after_costs"] = "0"
    data["operator_signoff"] = False
    report = assess_release_readiness(data)
    reasons = report["reasons"]
    assert report["decision"] == "NO_GO_FOR_LIVE_V6HBR"
    assert "INSUFFICIENT_DATA_SCOPE" in reasons
    assert "NET_EXPECTANCY_NOT_DEMONSTRATED:validation_lower95_mean_net_r" in reasons
    assert "OPERATOR_SIGNOFF_MISSING" in reasons


def test_synthetic_all_green_only_allows_manual_review_never_deployment():
    # Contract test only. THESE ARE FABRICATED FIXTURE VALUES, not MV outcomes.
    data = complete_manifest()
    before = deepcopy(data)
    report = assess_release_readiness(data)
    assert data == before
    assert report["decision"] == "ELIGIBLE_FOR_MANUAL_RELEASE_REVIEW_ONLY"
    assert report["reasons"] == []
    assert report["can_auto_deploy"] is False
    assert report["can_claim_high_accuracy"] is False


def test_worse_drawdown_contaminated_holdout_and_stress_losses_block():
    data = complete_manifest()
    data.update({
        "candidate_mtm_max_drawdown_r": "9.0",
        "strategy_selected_using_holdout": True,
        "holdout_stressed_net_r_after_costs": "-0.2",
    })
    report = assess_release_readiness(data)
    assert report["decision"] == "NO_GO_FOR_LIVE_V6HBR"
    assert "DRAWDOWN_WORSE_THAN_V4" in report["reasons"]
    assert "HOLDOUT_CONTAMINATION_NOT_EXCLUDED" in report["reasons"]
    assert "NET_EXPECTANCY_NOT_DEMONSTRATED:holdout_stressed_net_r_after_costs" in report["reasons"]


def test_missing_human_approval_and_unverified_proof_block():
    data = complete_manifest()
    data["recent_v4_failures_independently_audited"] = False
    data["independent_reviewer_signoff"] = False
    result = assess_release_readiness(data)
    assert result["decision"] == "NO_GO_FOR_LIVE_V6HBR"
    assert "MISSING_INDEPENDENT_PROOF:recent_v4_failures_independently_audited" in result["reasons"]
    assert "INDEPENDENT_REVIEW_MISSING" in result["reasons"]


def test_boolean_as_numeric_evidence_rejected():
    data = complete_manifest()
    data["holdout_resolved"] = True
    report = assess_release_readiness(data)
    assert report["decision"] == "NO_GO_FOR_LIVE_V6HBR"
    assert "INVALID_METRIC:holdout_resolved" in report["reasons"]
