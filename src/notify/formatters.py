from __future__ import annotations

from datetime import datetime

from src.providers.base import ProductQuote
from src.scoring.deal_score import DealMetrics


def format_alert(
    ts: datetime,
    q: ProductQuote,
    m: DealMetrics,
    final_score: float | None = None,
    preference_tags: list[str] | None = None,
    preference_reason: str = "",
) -> str:
    reason = (
        f"직전대비 {m.drop_prev:+.1%}, 7일대비 {m.drop_7d:+.1%}, 30일대비 {m.drop_30d:+.1%}, "
        f"30일저점근접={bool(m.near_low)}"
    )
    score_line = f"점수: {m.deal_score:.1f}/100"
    if final_score is not None and abs(float(final_score) - float(m.deal_score)) >= 0.05:
        score_line = f"점수: {final_score:.1f}/100 (기본 {m.deal_score:.1f} + 선호보정)"
    pref_line = ""
    if preference_tags:
        pref_line = f"선호태그: {', '.join(preference_tags)}"
        if preference_reason:
            pref_line += f" | 근거: {preference_reason}"
        pref_line += "\n"
    return (
        f"[KST {ts.strftime('%Y-%m-%d %H:%M')}] 핫딜 감지\n"
        f"{q.title}\n"
        f"{score_line}\n"
        f"가격: {int(m.current):,}원 (직전 {int(m.prev):,}원)\n"
        f"{pref_line}"
        f"근거: {reason}\n"
        f"리뷰/평점 신뢰도: {m.reliability:.2f}\n"
        f"링크: {q.url}\n"
        "※ 자동 탐지 결과이며 구매 추천이 아닙니다."
    )


def format_discovery_summary(ts: datetime, total_fetched: int, total_inserted: int, tracked: int) -> str:
    return (
        f"[KST {ts.strftime('%Y-%m-%d %H:%M')}] 핫딜 Discovery 요약\n"
        f"수집 상품: {total_fetched}\n"
        f"신규/갱신 추적: {total_inserted}\n"
        f"활성 추적 수: {tracked}"
    )


def format_discovery_summary_with_items(
    ts: datetime,
    total_fetched: int,
    total_inserted: int,
    tracked: int,
    items: list[ProductQuote],
) -> str:
    lines = [
        f"[KST {ts.strftime('%Y-%m-%d %H:%M')}] 핫딜 Discovery 요약",
        f"수집 상품: {total_fetched}",
        f"신규/갱신 추적: {total_inserted}",
        f"활성 추적 수: {tracked}",
    ]
    if items:
        lines.append("")
        lines.append("이번에 반영된 상품 예시")
        for i, q in enumerate(items[:5], start=1):
            price_txt = f"{int(q.price):,}원" if q.price > 0 else "가격미상"
            lines.append(f"{i}) {q.title[:48]} | {price_txt}")
    return "\n".join(lines)


def format_nightly_summary(ts: datetime, tracked: int, history_rows: int, alerts_24h: int) -> str:
    return (
        f"[KST {ts.strftime('%Y-%m-%d %H:%M')}] 핫딜 야간 리포트\n"
        f"활성 추적 상품: {tracked}\n"
        f"누적 가격 히스토리: {history_rows}\n"
        f"최근 24h 알림 수: {alerts_24h}"
    )
