from tradingagents.dataflows.models import DataQualityReport
from tradingagents.technical.product_evidence import ProductTechnicalEvidenceBundle
from tradingagents.technical.report_validation import validate_product_report


def _bundle():
    return ProductTechnicalEvidenceBundle(
        analysis_product="passive_equity_etf",
        subject_quality=DataQualityReport(grade="A", decision="allow", source_status="PRIMARY_OK"),
        bundle_snapshot_id="sha256:bundle",
        product_assessment={"product_state": "standalone_vehicle_only"},
    )


def test_unsupported_terms_are_blocked_when_asserted():
    result = validate_product_report("组合快照：sha256:bundle；存在折溢价和套利机会。", _bundle())
    assert not result.valid
    assert "prohibited_product_term:折溢价" in result.issues


def test_negated_unavailable_terms_are_allowed():
    result = validate_product_report(
        "组合快照：sha256:bundle；未取得 NAV/IOPV，不输出折溢价、正式跟踪误差或套利机会。",
        _bundle(),
    )
    assert result.valid
