"""生成「数据源示例」工作区的两源日线样本 CSV（可复现）.

示例表口径与 StockMaster 线上一致：10 只标的 × 近 5 年日线（单标的约 1,214 根）。

两张表一源一表，避免复权口径互相覆盖：

===============  ================  ==========  ==========
表               provider          复权        行数
===============  ================  ==========  ==========
股市日线         tencent_kline     前复权      10×约1210
股市日线-新浪    sina_kline        不复权      10×1023
===============  ================  ==========  ==========

用法::

    uv run python scripts/build_example_kline.py --start 2021-10-18 --end 2026-10-20

需要联网（腾讯 / 新浪走 HTTPS）。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    RequestSpec,
    SyncJobSpec,
    TimeWindowSpec,
)
from cndb.plugins.datasource.providers.sina_kline import SINA_KLINE_URL_TEMPLATE
from cndb.plugins.datasource.providers.tencent_kline import TENCENT_KLINE_URL_TEMPLATE
from cndb.plugins.datasource.services.pipeline import run_pipeline

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "examples" / "datasets" / "工作区-数据源示例"

# 10 只标的：跨行业，覆盖不同波动形态
SYMBOLS: dict[str, str] = {
    "sh600519": "贵州茅台",
    "sz000858": "五粮液",
    "sz000001": "平安银行",
    "sh600036": "招商银行",
    "sh601318": "中国平安",
    "sz300750": "宁德时代",
    "sz002594": "比亚迪",
    "sh601899": "紫金矿业",
    "sh600900": "长江电力",
    "sz000651": "格力电器",
}

# 腾讯 / 新浪的字段 → 表内中文列
_MAPPING: dict[str, FieldTransform] = {
    "symbol": FieldTransform(name="股票代码", field_type="text"),
    "trade_date": FieldTransform(name="交易日", field_type="date"),
    "open": FieldTransform(name="开盘价", field_type="float"),
    "high": FieldTransform(name="最高价", field_type="float"),
    "low": FieldTransform(name="最低价", field_type="float"),
    "close": FieldTransform(name="收盘价", field_type="float"),
    "volume": FieldTransform(name="成交量", field_type="int"),
}

_COLUMNS = ("股票代码", "股票名称", "交易日", "开盘价", "最高价", "最低价", "收盘价", "成交量")


def _job(
    provider: str,
    url_template: str,
    *,
    window: TimeWindowSpec,
    mapping: dict[str, FieldTransform],
) -> SyncJobSpec:
    return SyncJobSpec(
        request=RequestSpec(url_template=url_template, time_window=window),
        provider=provider,
        entrant_param="symbol",
        entrant_values=tuple(SYMBOLS),
        match_keys=("symbol", "trade_date"),
        field_mapping=mapping,
    )


def _fetch(job: SyncJobSpec, *, rate_limit_ms: int = 200) -> list[dict[str, Any]]:
    outcome = run_pipeline(job, rate_limit_ms=rate_limit_ms)
    if outcome.failures:
        for failure in outcome.failures[:5]:
            print(f"  ! {failure.label}: {failure.error}", file=sys.stderr)
    print(f"  {job.provider}: plans={outcome.plans} succeeded={outcome.succeeded} rows={len(outcome.rows)}")
    return outcome.rows


def _round_price(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    columns: Sequence[str],
    *,
    start: str = "",
    end: str = "",
) -> int:
    # 腾讯接口按「截至 end 的最近 320 根」返回，相邻 chunk 有重叠 → 按幂等键去重；
    # 首个窗口会带出 start 之前的数据，按区间裁剪，保持三源时间范围一致
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("股票代码") or "")
        day = str(row.get("交易日") or "")
        if not code or not day:
            continue
        if start and day < start:
            continue
        if end and day > end:
            continue
        unique.setdefault((code, day), row)
    ordered = sorted(unique.values(), key=lambda r: (str(r.get("股票代码") or ""), str(r.get("交易日") or "")))
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in ordered:
            symbol = str(row.get("股票代码") or "")
            record = {
                "股票代码": symbol,
                "股票名称": SYMBOLS.get(symbol, ""),
                "交易日": row.get("交易日") or "",
                "开盘价": _round_price(row.get("开盘价")),
                "最高价": _round_price(row.get("最高价")),
                "最低价": _round_price(row.get("最低价")),
                "收盘价": _round_price(row.get("收盘价")),
                "成交量": row.get("成交量") or "",
            }
            writer.writerow([record[column] for column in columns])
            count += 1
    print(f"  → {path.name}: {count} 行")
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成两源 A 股日线示例 CSV")
    parser.add_argument("--start", default="2021-10-18")
    parser.add_argument("--end", default="2026-10-20")
    parser.add_argument("--out", default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 腾讯单次最多 320 根（且语义为「截至 end 的最近 320 根」）→ 窗口按 440 自然日
    tencent_window = TimeWindowSpec(mode="range", start=args.start, end=args.end, chunk_days=440)

    print(f"[1/2] 腾讯 前复权 {args.start}~{args.end}")
    tencent_rows = _fetch(
        _job("tencent_kline", TENCENT_KLINE_URL_TEMPLATE, window=tencent_window, mapping=dict(_MAPPING)),
        rate_limit_ms=2000,
    )
    if tencent_rows:
        _write_csv(out_dir / "股市日线.csv", tencent_rows, _COLUMNS, start=args.start, end=args.end)
    else:
        print("  ! 腾讯抓取为空（可能被 WAF 限流），保留原文件", file=sys.stderr)

    print("[2/2] 新浪 不复权（最近 1023 根）")
    sina_rows = _fetch(
        _job("sina_kline", SINA_KLINE_URL_TEMPLATE, window=TimeWindowSpec(mode="none"), mapping=dict(_MAPPING))
    )
    if sina_rows:
        _write_csv(out_dir / "股市日线-新浪.csv", sina_rows, _COLUMNS, start=args.start, end=args.end)
    else:
        print("  ! 新浪抓取为空，保留原文件", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
