"""自选股种子 —— 一只股一行，行内嵌多周期复权 K 线 JSON.

数据来源：

- ``examples/datasets/工作区-数据源示例/自选股.json``：标的元数据（代码/名称/市场/行业）；
- ``examples/datasets/工作区-数据源示例/股市日线.csv``：离线日线样本，按股票代码聚合后
  生成「日线前复权」JSON，并在 Python 内派生周线 / 月线前复权。

设计取舍：

- 手动建表（而不是 ``create_table_from_json_data``），确保 K 线列是 ``json`` 类型；
  自动推断会把 list 值提升成 multiselect，导致物理列无法存 JSON 数组。
- seed 全量重建，函数内仍做同名表存在性检查，便于单测重复调用。
- 后复权 / 不复权列留空，由通用 ``http_json`` 同步任务按字段映射分列填充（部分列 upsert）。
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

# 自选股表字段定义：(字段名, 字段类型, config, required, is_unique)
# float 列必须显式配 decimals：默认 0 位会把最新价/涨跌幅四舍五入成整数
_STOCK_FIELDS: tuple[tuple[str, str, dict[str, Any], bool, bool], ...] = (
    ("股票代码", "text", {}, True, True),
    ("股票名称", "text", {}, True, False),
    ("市场", "select", {"options": ["A股", "港股", "美股"]}, False, False),
    ("行业", "text", {}, False, False),
    ("是否自选", "boolean", {}, False, False),
    ("最新价", "float", {"decimals": 2}, False, False),
    ("涨跌幅", "float", {"decimals": 2}, False, False),
    ("最新交易日", "date", {}, False, False),
    ("成交量", "float", {"decimals": 0}, False, False),
    ("成交额", "float", {"decimals": 2}, False, False),
    ("日线前复权", "json", {}, False, False),
    ("日线后复权", "json", {}, False, False),
    ("日线不复权", "json", {}, False, False),
    ("周线前复权", "json", {}, False, False),
    ("月线前复权", "json", {}, False, False),
    ("更新时间", "datetime", {}, False, False),
)

_TABLE_NAME = "自选股"
_DEFAULT_FOLDER = "工作区-数据源示例"
_CSV_NAME = "股市日线.csv"
_META_NAME = "自选股.json"

# 字段级默认值：标的发现类同步任务（通用 http_json 适配器）只提供代码/名称/市场，
# 新行的「是否自选」由默认值落 false；已存在的行在部分列 upsert 下保持原值，
# 不会被重新发现时把用户手动勾选的 true 覆盖掉。
_FIELD_DEFAULTS: dict[str, Any] = {"是否自选": False}


def _seed_stock_quotes(
    db: Any,
    engine: Any,
    ws: Any,
    owner_id: int | None,
    datasets_dir: Path | None,
    folder_name: str = _DEFAULT_FOLDER,
) -> tuple[int, Any | None]:
    """创建「自选股」表并写入示例数据.

    Returns:
        ``(创建的表数量 0/1, DataTable 或 None)``；目录/元数据缺失时返回 ``(0, None)``。
    """
    from cndb.plugins.tables.models import DataField, DataTable, ensure_default_view
    from cndb.plugins.tables.services.core.ddl import create_table
    from cndb.plugins.tables.services.core.records import bulk_create

    if datasets_dir is None:
        return 0, None
    folder = datasets_dir / folder_name
    if not folder.is_dir():
        return 0, None

    existing = db.query(DataTable).filter(DataTable.workspace_id == ws.id, DataTable.name == _TABLE_NAME).first()
    if existing is not None:
        print(f"[seed-K线] 自选股表已存在，跳过: {ws.name}/{_TABLE_NAME}")
        return 0, existing

    meta = _load_meta(folder / _META_NAME)
    series_by_code = _load_daily_series(folder / _CSV_NAME)
    rows = _build_rows(meta, series_by_code)
    if not rows:
        print(f"[seed-K线] 未发现自选股数据，跳过: {folder}")
        return 0, None

    dt = DataTable(
        workspace_id=ws.id,
        owner_id=owner_id,
        name=_TABLE_NAME,
        description="一只股一行，行内嵌日/周/月多周期复权 K 线（JSON）",
        order=1,
    )
    dt.ensure_db_name()
    db.add(dt)
    db.commit()
    db.refresh(dt)

    for idx, (name, field_type, config, required, is_unique) in enumerate(_STOCK_FIELDS):
        field = DataField(
            table_id=dt.id,
            name=name,
            field_type=field_type,
            config=config,
            order=idx,
            required=required,
            is_unique=is_unique,
            default_value=_FIELD_DEFAULTS.get(name),
        )
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(dt)

    create_table(engine, dt)
    ensure_default_view(db, dt, owner_id=owner_id, commit=True)
    bulk_create(engine, dt, rows, db=db)
    print(f"[seed-K线] 建表: {ws.name}/{_TABLE_NAME} → {len(rows)} 只标的 (id={dt.id})")
    return 1, dt


# ── 元数据 / CSV 读取 ──────────────────────────────


def _load_meta(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[seed-K线] 自选股元数据读取失败，跳过: {path}: {exc}")
        return []
    if isinstance(payload, dict):
        payload = payload.get("symbols") or payload.get("stocks") or []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _load_daily_series(path: Path) -> dict[str, list[dict[str, Any]]]:
    """读取日线 CSV，按股票代码聚合为升序 K 线数组."""
    if not path.is_file():
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                code = str(raw.get("股票代码") or "").strip()
                trade_date = str(raw.get("交易日") or "").strip()
                if not code or not trade_date:
                    continue
                point = {
                    "date": trade_date,
                    "open": _to_float(raw.get("开盘价")),
                    "close": _to_float(raw.get("收盘价")),
                    "high": _to_float(raw.get("最高价")),
                    "low": _to_float(raw.get("最低价")),
                    "volume": _to_float(raw.get("成交量")),
                    "amount": _to_float(raw.get("成交额")),
                    "amplitude": None,
                    "pct_change": None,
                    "change": None,
                    "turnover": None,
                }
                grouped.setdefault(code, []).append(point)
    except OSError as exc:
        print(f"[seed-K线] 日线 CSV 读取失败，跳过: {path}: {exc}")
        return {}
    for points in grouped.values():
        points.sort(key=lambda p: str(p.get("date") or ""))
        _enrich_changes(points)
    return grouped


def _build_rows(
    meta: list[dict[str, Any]],
    series_by_code: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """合并元数据与 K 线序列；CSV 中存在但元数据缺失的代码自动补一行."""
    now = datetime.now()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in meta:
        code = str(item.get("股票代码") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append(_build_row(code, item, series_by_code.get(code, []), now))

    for code, points in series_by_code.items():
        if code in seen:
            continue
        name = ""
        if points:
            # CSV 没有名称列时用代码占位，避免行无法识别
            name = code
        rows.append(_build_row(code, {"股票名称": name}, points, now))
    return rows


def _build_row(
    code: str,
    meta: dict[str, Any],
    points: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    latest = points[-1] if points else {}
    return {
        "股票代码": code,
        "股票名称": str(meta.get("股票名称") or code).strip(),
        "市场": str(meta.get("市场") or _market_from_code(code)).strip(),
        "行业": str(meta.get("行业") or "").strip(),
        "是否自选": bool(meta.get("是否自选", True)),
        "最新价": latest.get("close"),
        "涨跌幅": latest.get("pct_change"),
        "最新交易日": _parse_date(latest.get("date")),
        "成交量": latest.get("volume"),
        "成交额": latest.get("amount"),
        "日线前复权": points or None,
        "日线后复权": None,
        "日线不复权": None,
        "周线前复权": _resample(points, "week") or None,
        "月线前复权": _resample(points, "month") or None,
        "更新时间": now,
    }


# ── K 线派生 ──────────────────────────────────────


def _enrich_changes(points: list[dict[str, Any]]) -> None:
    prev_close: float | None = None
    for point in points:
        close = point.get("close")
        if prev_close not in (None, 0) and close is not None:
            point["change"] = round(close - prev_close, 4)
            point["pct_change"] = round((close - prev_close) / prev_close * 100, 4)
        prev_close = close


def _resample(points: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """日线 → 周线 / 月线（open 首日、close 末日、high/low 极值、量额求和）."""
    if not points:
        return []
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for point in points:
        day = _parse_date(point.get("date"))
        if day is None:
            continue
        key = (day.isocalendar().year, day.isocalendar().week) if period == "week" else (day.year, day.month)
        groups.setdefault(key, []).append(point)

    result: list[dict[str, Any]] = []
    prev_close: float | None = None
    for group in groups.values():
        highs = [p["high"] for p in group if p.get("high") is not None]
        lows = [p["low"] for p in group if p.get("low") is not None]
        volumes = [p["volume"] for p in group if p.get("volume") is not None]
        amounts = [p["amount"] for p in group if p.get("amount") is not None]
        close = group[-1].get("close")
        change = round(close - prev_close, 4) if close is not None and prev_close not in (None, 0) else None
        pct_change = (
            round((close - prev_close) / prev_close * 100, 4)
            if close is not None and prev_close not in (None, 0)
            else None
        )
        result.append(
            {
                "date": group[-1].get("date"),
                "open": group[0].get("open"),
                "close": close,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "volume": sum(volumes) if volumes else None,
                "amount": sum(amounts) if amounts else None,
                "amplitude": None,
                "pct_change": pct_change,
                "change": change,
                "turnover": None,
            }
        )
        prev_close = close
    return result


# ── 小工具 ────────────────────────────────────────


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _market_from_code(code: str) -> str:
    lower = code.lower()
    if lower.startswith(("sh", "sz")):
        return "A股"
    if lower.startswith("hk"):
        return "港股"
    if lower.startswith("us"):
        return "美股"
    return "其他"


__all__ = ["_seed_stock_quotes"]
