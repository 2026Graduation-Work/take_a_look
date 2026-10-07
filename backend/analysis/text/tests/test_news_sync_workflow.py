from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[4] / ".github/workflows/news-supabase-sync.yml"


def test_news_sync_workflow_has_schedule_targets_secrets_and_runtime_guards() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 0 * * 1-5"' in text
    assert "workflow_dispatch:" in text
    assert "supabase_sync live --dynamic" in text
    assert "supabase_sync disclosures" in text
    assert 'cron: "30 22 * * 0"' in text and "supabase_sync financial-latest" in text
    assert "${{ secrets.DART_API_KEY }}" in text
    for secret in ("NEWSAPI_AI_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY"):
        assert f"${{{{ secrets.{secret} }}}}" in text
        assert f"{secret}=sk_" not in text
    assert "concurrency:" in text
    assert "cancel-in-progress: false" in text
    assert "https://download.pytorch.org/whl/cpu" in text
    assert "~/.cache/huggingface" in text
    assert "python-version: \"3.12\"" in text
    assert "permissions:\n  contents: read" in text
    assert "timeout-minutes:" in text


def test_manual_workflow_offers_live_and_four_stock_backfill_modes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "mode:" in text
    assert "- live" in text
    assert "- live-samsung" in text
    assert "- backfill" in text
    assert "inputs.mode == 'live-samsung'" in text
    assert "python -m value_pipeline.supabase_sync live --target 005930:삼성전자" in text
    for path in (
        "sentiment-005930.json",
        "sentiment-005380.json",
        "sentiment-035720.json",
        "sentiment-068270.json",
        "005930_financial.json",
        "005380_financial.json",
        "035720_financial.json",
        "068270_financial.json",
    ):
        assert path in text
