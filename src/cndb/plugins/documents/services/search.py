"""FTS5 全文检索服务 + 中文子串兜底.

检索策略（两段式）：
1. **FTS5 MATCH**：分词 / 短语 / 前缀 / 布尔查询，bm25 排序 + highlight（西文与整词精确命中）；
2. **子串兜底（LIKE）**：仅当 FTS 命中为 0 时启用。原因：FTS5 的 ``unicode61`` 把连续中文当作
   单个 token（``销售管理总览``），用户输入「销售」「管理」这类常用词片段时命中为 0——中文
   用户期望的是**子串语义**。兜底通道对 title / summary / content 做大小写不敏感的子串匹配，
   多词之间取 AND，标题命中优先排序。

兜底只在 FTS 无结果时运行，因此**只增不减**（不会改变既有命中），代价是关键词特别生僻时多一次
扫描；当前数据规模（单库 MB 级、文档数十至数千）下可忽略，若将来文档量级上万，可改为
FTS5 ``trigram`` 影子表或分词列（见设计记录）。


底层仍是 SQLite FTS5 虚拟表（documents_fts），支持关键词（unicode61 分词）、前缀（``abc*``）、
精确短语（``"exact phrase"``）、布尔组合（AND / OR / NOT），以及 highlight() 高亮 + rank 排序。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError
from cndb.plugins.documents.models import DOC_STATUS_PUBLISHED

# FTS5 中作为运算符的裸词：仅在两侧确有词条时才保留为布尔语法（否则按字面词处理，
# 避免 "AND" / "a AND" / "NOT" 之类输入直接触发 fts5: syntax error → 500）
_FTS5_BOOLEAN = {"AND", "OR", "NOT"}

# 未被引号包裹时会被 FTS5 当作语法字符的裸字符：丢弃并断开当前词条
_FTS5_SYNTAX_CHARS = set("(){}[]:^~")

# sqlite FTS5 语法错误特征（用于把 500 收敛为 400；"no such table" 等结构问题不在此列）
_FTS5_SYNTAX_HINTS = (
    "fts5: syntax error",
    "malformed match",
    "unterminated string",
    "unknown special query",
    "parse error",
)

# FTS 建表缓存按"数据库连接目标"区分：同一进程可能先后操作多个库（`cndb seed`
# 的文件库、测试的内存库、备份恢复的临时库）。若只用一个进程级布尔标记，第二个库
# 会误判 `documents_fts` 已存在，写入时报 ``no such table: documents_fts``。
_fts_state: dict[str, Any] = {"ready": False, "bind": None}

_FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, content, summary, author,
    tokenize='unicode61'
)
"""

# trigram 影子表（0171）：unicode61 把连续中文当单 token，2 字以下短词无法索引；
# trigram 按 3 字符切分，可命中任意 ≥3 字符的子串（含中文）。两表并行维护，
# search 在 FTS 无命中时按「最长中文连续段 ≥3」分流到 trigram，否则保留 LIKE 兜底。
_FTS_TRI_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts_tri USING fts5(
    title, content, summary, author,
    tokenize='trigram'
)
"""


def ensure_fts_schema(db: Session) -> None:
    """幂等创建 FTS5 虚拟表（同一数据库内只执行一次）.

    生产路径由 alembic 迁移创建；本函数兜底 create_all 场景
    （全新数据库首次启动时 alembic 只 create_all ORM 表，不含虚拟表）。

    缓存按数据库连接目标（engine / connection 所属 engine）区分，避免同进程操作
    多个库时，后一个库误判前一个库建好的表也存在。
    """
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)
    if _fts_state["ready"] and _fts_state["bind"] is engine:
        return
    db.execute(text(_FTS_CREATE_SQL))
    db.execute(text(_FTS_TRI_CREATE_SQL))
    db.commit()
    # 存量回填（0171）：老库已有主表索引但 trigram 表为空时，从主表复制正文回填。
    # 主表 content 已是完整正文（写路径截 64KB），trigram 只需同内容即可，无需外存读取，
    # 避免迁移期依赖 data/docs 路径。逐行幂等（只补 trigram 缺行/空行）。
    tri_count = db.execute(text("SELECT count(*) FROM documents_fts_tri WHERE content != ''")).scalar_one()
    main_count = db.execute(text("SELECT count(*) FROM documents_fts WHERE content != ''")).scalar_one()
    if tri_count < main_count:
        db.execute(
            text(
                "INSERT OR REPLACE INTO documents_fts_tri(rowid, title, content, summary, author) "
                "SELECT rowid, title, content, summary, author FROM documents_fts WHERE content != ''"
            )
        )
        db.commit()
    _fts_state["ready"] = True
    _fts_state["bind"] = engine


def reset_fts_schema_cache() -> None:
    """重置进程内 FTS 建表缓存（seed 全量重建删表后调用）.

    ``cndb seed`` 会 drop 全部表（含 documents_fts 虚拟表），长驻进程内
    缓存的 ready 标记会误判虚拟表仍存在，导致后续文档写入报
    ``no such table: documents_fts``。seed 重建 schema 后调用本函数，
    让下一次写入重新执行幂等建表。
    """
    _fts_state["ready"] = False
    _fts_state["bind"] = None


def escape_query(query: str) -> str:
    """将用户输入转为安全的 FTS5 MATCH 表达式.

    规则：
    - 保留用户有意使用的 ``"..."``（短语）与 ``*``（前缀）；未闭合引号按短语收尾
    - ``AND`` / ``OR`` / ``NOT`` 仅在其前后确有词条且不与相邻运算符相连时保留为
      布尔语法，否则按字面词检索（例如单独输入 ``AND`` 等价于搜索 "AND"）
    - 其它裸词统一加引号，杜绝语法字符注入
    - 去掉纯符号词条后无剩余时抛 BadRequestError（400），不落库查询
    """
    query = query.strip()
    if not query:
        raise BadRequestError("搜索关键词不能为空")

    parts = _render_fts_tokens(_tokenize_fts_query(query))
    if not parts:
        raise BadRequestError("搜索关键词无效")
    return " ".join(parts)


def _tokenize_fts_query(query: str) -> list[tuple[bool, str]]:
    """切分查询串为 ``(是否短语, 文本)`` 词条.

    - 引号成对时内部为短语；未闭合的引号把剩余内容整体当作短语收尾；
    - 短语外遇到空白或 FTS5 语法字符即断开当前词条（语法字符本身丢弃）。
    """
    tokens: list[tuple[bool, str]] = []
    buf = ""
    in_phrase = False

    def _flush(phrase: bool) -> None:
        nonlocal buf
        text = buf.strip()
        if text:
            tokens.append((phrase, text))
        buf = ""

    for ch in query:
        if ch == '"':
            _flush(in_phrase)
            in_phrase = not in_phrase
            continue
        if not in_phrase and (ch.isspace() or ch in _FTS5_SYNTAX_CHARS):
            _flush(False)
            continue
        buf += ch
    _flush(in_phrase)
    return tokens


def _render_fts_tokens(tokens: list[tuple[bool, str]]) -> list[str]:
    """把词条渲染为 FTS5 表达式片段列表（空列表表示无有效词条）.

    候选分两类：``op``（裸布尔运算符，仅两侧均有词条时保留语法）与 ``lit``
    （已加引号的字面词/短语/前缀）。字面词条必须加引号，否则其中的 ``-``、``:``
    等字符会被 FTS5 解析成列过滤等语法（例如 ``purge-token-unique``）。
    """
    candidates: list[tuple[str, str]] = []  # (kind, text)
    for is_phrase, raw in tokens:
        if is_phrase:
            candidates.append(("lit", _quote_phrase(raw)))
            continue
        if raw.endswith("*"):
            stem = raw.rstrip("*").strip()
            if stem and _has_word_char(stem):
                candidates.append(("lit", f"{_quote_phrase(stem)}*"))
            continue
        if not _has_word_char(raw):
            continue  # 纯符号词条（如 "*"、"---"），丢弃
        candidates.append(("op", raw) if raw in _FTS5_BOOLEAN else ("lit", _quote_phrase(raw)))

    parts: list[str] = []
    prev_operator = False
    for index, (kind, chunk) in enumerate(candidates):
        if kind == "op" and 0 < index < len(candidates) - 1 and not prev_operator:
            parts.append(chunk)  # 两侧均有词条的布尔运算符
            prev_operator = True
        elif kind == "op":
            parts.append(_quote_phrase(chunk))  # 位置不合法的运算符按字面词处理
            prev_operator = False
        else:
            parts.append(chunk)
            prev_operator = False
    return parts


def _quote_phrase(text: str) -> str:
    """把任意文本包成 FTS5 短语（内部双引号按 FTS5 规则重复转义）."""
    return '"' + text.replace('"', '""') + '"'


def _has_word_char(text: str) -> bool:
    """判断词条是否含有可被分词的有效字符（纯符号词条无检索意义）."""
    return any(ch.isalnum() or ch == "_" for ch in text)


def search_documents(
    db: Session,
    query: str,
    *,
    workspace_id: int | None = None,
    tag_ids: list[int] | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    viewer_id: int | None = None,
    is_admin: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """执行 FTS5 搜索.

    Returns:
        (命中列表 [{...字段 + title_hit/summary_hit/rank}], 总命中数)
    """
    match_expr = escape_query(query)

    where_parts = ["documents_fts MATCH :q", "d.is_deleted = 0"]
    params: dict[str, Any] = {"q": match_expr}

    if workspace_id is not None:
        where_parts.append("d.workspace_id = :wid")
        params["wid"] = workspace_id
    if status:
        where_parts.append("d.status = :status")
        params["status"] = status
    if tag_ids:
        placeholders = ",".join(f":t{i}" for i in range(len(tag_ids)))
        where_parts.append(f"d.id IN (SELECT document_id FROM documents_documenttag WHERE tag_id IN ({placeholders}))")
        params.update({f"t{i}": tid for i, tid in enumerate(tag_ids)})
    # 可见性：非管理员只搜"已发布"或"自己创建"的文档，避免草稿/未发布内容被搜到
    if not is_admin and viewer_id is not None:
        where_parts.append("(d.status = :public_status OR d.created_by_id = :viewer_id)")
        params["public_status"] = DOC_STATUS_PUBLISHED
        params["viewer_id"] = viewer_id

    where_clause = " AND ".join(where_parts)
    # 兜底通道只关心筛选条件（workspace / status / tag）：剔除 MATCH 与重复的 is_deleted
    extra_filters = where_parts[2:]

    try:
        total = int(
            db.execute(
                text(
                    f"SELECT count(*) FROM documents_fts "
                    f"JOIN documents_document d ON documents_fts.rowid = d.id "
                    f"WHERE {where_clause}"
                ),
                params,
            ).scalar_one()
        )

        rows = db.execute(
            text(
                f"""
                SELECT d.id, d.title, d.workspace_id, d.status, d.content_type, d.updated_at,
                       highlight(documents_fts, 1, '<mark>', '</mark>') AS content_hit,
                       highlight(documents_fts, 2, '<mark>', '</mark>') AS summary_hit,
                       bm25(documents_fts) AS rank
                FROM documents_fts
                JOIN documents_document d ON documents_fts.rowid = d.id
                WHERE {where_clause}
                ORDER BY rank
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": limit, "offset": offset},
        ).all()
    except OperationalError as exc:
        # 兜底：解析层已尽量消除非法输入，仍被 sqlite 判为语法错误时收敛为 400，
        # 不让检索入口把用户输入问题暴露成 500（结构类错误如缺表仍向上抛）。
        if any(hint in str(exc).lower() for hint in _FTS5_SYNTAX_HINTS):
            raise BadRequestError("搜索表达式无效，请调整关键词或改用引号包裹短语") from exc
        raise

    if total == 0:
        # FTS 无命中：中文关键词片段（unicode61 整词分词）会走到这里。
        # 0171 混合策略：存在 ≥3 字符的中文连续段 → 先走 trigram 影子表（有索引，避免大库
        # 全表 LIKE）；否则（2 字短词 / 纯西文）维持原 LIKE 兜底。trigram 通道仅做候选
        # 收窄，完整 query 的 AND 语义与高亮/排序仍由 _search_by_substring 在候选集上执行，
        # 保证命中集合只增不减（trigram 候选 ⊇ LIKE 命中）。
        fallback_params = {key: value for key, value in params.items() if key != "q"}
        tri_term = _longest_cjk_term(query)
        if tri_term is not None:
            # 用子查询收窄候选，避免把大量 rowid 变成 bind 参数（SQLite 上限 999）。
            tri_filters = [
                *extra_filters,
                "d.id IN (SELECT rowid FROM documents_fts_tri WHERE documents_fts_tri MATCH :tri_q)",
            ]
            return _search_by_substring(
                db,
                query,
                tri_filters,
                {**fallback_params, "tri_q": _quote_phrase(tri_term)},
                limit=limit,
                offset=offset,
            )
        return _search_by_substring(
            db,
            query,
            extra_filters,
            fallback_params,
            limit=limit,
            offset=offset,
        )

    items = []
    for row in rows:
        content_hit = row.content_hit or ""
        # content 命中片段裁剪：取首个 <mark> 前后各 80 字符
        snippet = _snippet(content_hit)
        items.append(
            {
                "id": row.id,
                "title": row.title,
                "title_hit": f"<mark>{row.title}</mark>" if _query_hit_title(match_expr, row.title) else row.title,
                "summary_hit": row.summary_hit or snippet,
                "workspace_id": row.workspace_id,
                "status": row.status,
                "content_type": row.content_type,
                "updated_at": row.updated_at,
                "rank": float(row.rank) if row.rank is not None else 0.0,
            }
        )
    return items, total


_LIKE_ESCAPE = "\\"


def _split_substring_terms(query: str) -> list[str]:
    """把查询拆成子串检索用的关键词列表.

    去掉 FTS5 语法字符与布尔运算符（它们在 LIKE 语境下无意义），按空白切分；
    结果为空时由调用方视为「无有效关键词」。
    """
    cleaned = query
    for ch in _FTS5_SYNTAX_CHARS:
        cleaned = cleaned.replace(ch, " ")
    terms = [part.strip().strip('"') for part in cleaned.split()]
    return [term for term in terms if term and term.upper() not in _FTS5_BOOLEAN]


def _escape_like(term: str) -> str:
    """转义 LIKE 通配符，避免用户输入的 % / _ 变成通配（配合 ESCAPE '\\' 使用）."""
    return (
        term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", _LIKE_ESCAPE + "%").replace("_", _LIKE_ESCAPE + "_")
    )


def _mark(term: str, text: str) -> str:
    """在文本中把关键词片段包成 <mark>（大小写不敏感，逐词进行）."""
    if not text:
        return ""
    result = text
    lowered = result.lower()
    for token in _split_substring_terms(term):
        needle = token.lower()
        start = 0
        while needle:
            idx = lowered.find(needle, start)
            if idx == -1:
                break
            result = result[:idx] + "<mark>" + result[idx : idx + len(token)] + "</mark>" + result[idx + len(token) :]
            lowered = result.lower()
            start = idx + len("<mark>") + len(token) + len("</mark>")
    return result


def _longest_cjk_term(query: str) -> str | None:
    """取 query 中最长的连续中文片段（≥3 字符），供 trigram 候选收窄.

    trigram 按 3 字符切分，<3 字符无法命中；取最长段是为了尽量收窄候选集，
    完整 query 的多词 AND 语义仍由后续 LIKE 通道在候选集上执行（只增不减）。
    """
    best = ""
    current = ""
    for ch in query:
        if "\u4e00" <= ch <= "\u9fff":
            current += ch
        else:
            if len(current) > len(best):
                best = current
            current = ""
    if len(current) > len(best):
        best = current
    return best if len(best) >= 3 else None


def _search_by_substring(
    db: Session,
    query: str,
    where_extra: list[str],
    params: dict[str, Any],
    *,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """子串兜底检索：title / summary / content 做 LIKE 匹配，多词 AND.

    排序：标题命中 > 摘要命中 > 其余，再按更新时间倒序（FTS 的 bm25 无法直接用于 LIKE 通道）。
    """
    terms = _split_substring_terms(query)
    if not terms:
        return [], 0

    term_clauses: list[str] = []
    for i, term in enumerate(terms):
        key = f"s{i}"
        params[key] = f"%{_escape_like(term)}%"
        # 三个字段任一包含该词即算命中（ESCAPE 处理用户输入里的 % / _）
        term_clauses.append(
            f"(d.title LIKE :{key} ESCAPE '{_LIKE_ESCAPE}' "
            f"OR f.summary LIKE :{key} ESCAPE '{_LIKE_ESCAPE}' "
            f"OR f.content LIKE :{key} ESCAPE '{_LIKE_ESCAPE}')"
        )

    first_key = "s0"
    title_hit_sql = f"CASE WHEN d.title LIKE :{first_key} ESCAPE '{_LIKE_ESCAPE}' THEN 1 ELSE 0 END"
    summary_hit_sql = f"CASE WHEN f.summary LIKE :{first_key} ESCAPE '{_LIKE_ESCAPE}' THEN 1 ELSE 0 END"

    where_clause = " AND ".join(["d.is_deleted = 0", *term_clauses, *where_extra])

    total = int(
        db.execute(
            text(
                f"SELECT count(*) FROM documents_fts f JOIN documents_document d ON f.rowid = d.id WHERE {where_clause}"
            ),
            params,
        ).scalar_one()
    )

    rows = db.execute(
        text(
            f"""
            SELECT d.id, d.title, d.workspace_id, d.status, d.content_type, d.updated_at,
                   f.summary AS summary_raw, f.content AS content_raw,
                   {title_hit_sql} AS title_hit_rank,
                   {summary_hit_sql} AS summary_hit_rank
            FROM documents_fts f
            JOIN documents_document d ON f.rowid = d.id
            WHERE {where_clause}
            ORDER BY title_hit_rank DESC, summary_hit_rank DESC, d.updated_at DESC, d.id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()

    items = []
    for row in rows:
        content = row.content_raw or ""
        summary = row.summary_raw or ""
        idx = content.lower().find(terms[0].lower())
        snippet = content[max(0, idx - 30) : idx + 90] if idx >= 0 else ""
        items.append(
            {
                "id": row.id,
                "title": row.title,
                "title_hit": _mark(query, row.title),
                "summary_hit": _mark(query, summary) if summary else _mark(query, snippet),
                "workspace_id": row.workspace_id,
                "status": row.status,
                "content_type": row.content_type,
                "updated_at": row.updated_at,
                # 兜底通道无 bm25：用「标题命中 / 摘要命中」映射为负分值，保持「越小越靠前」的既有语义
                "rank": float(-int(row.title_hit_rank) * 2 - int(row.summary_hit_rank)),
            }
        )
    return items, total


def _query_hit_title(match_expr: str, title: str) -> bool:
    """粗判标题是否命中（用于标题高亮展示）。"""
    for tok in match_expr.replace('"', " ").split():
        tok = tok.strip("*")
        if tok and tok.lower() in title.lower():
            return True
    return False


def _snippet(content_hit: str, pad: int = 80) -> str:
    """裁剪长内容命中片段到首个 mark 标记附近."""
    idx = content_hit.find("<mark>")
    if idx == -1:
        return content_hit[: pad * 2]
    start = max(0, idx - pad)
    end = min(len(content_hit), idx + pad * 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content_hit) else ""
    return f"{prefix}{content_hit[start:end]}{suffix}"


_FTS_FINGERPRINT_CHARS = 64


def _fts_fingerprints(db: Session, table: str) -> dict[int, tuple[str, int, str]]:
    """读取 FTS 表的轻量指纹（标题 / 正文长度 / 前 64 字符），不加载完整正文.

    ``table`` 只接受内部常量（documents_fts / documents_fts_tri），不接受外部输入。
    """
    rows = db.execute(
        text(
            f"SELECT rowid, title, length(content), substr(content, 1, {_FTS_FINGERPRINT_CHARS}) FROM {table}"  # nosec B608 - 表名来自内部常量
        )
    ).all()
    return {int(row[0]): (str(row[1] or ""), int(row[2] or 0), str(row[3] or "")) for row in rows}


class FtsConsistencyReport:
    """FTS 索引一致性报告（0170）：只读，不含正文，仅含计数与文档 id."""

    def __init__(
        self,
        *,
        missing: list[int] | None = None,
        orphan: list[int] | None = None,
        mismatch: list[int] | None = None,
    ) -> None:
        self.missing = missing or []
        self.orphan = orphan or []
        self.mismatch = mismatch or []

    @property
    def consistent(self) -> bool:
        return not (self.missing or self.orphan or self.mismatch)

    def as_dict(self) -> dict[str, Any]:
        return {
            "consistent": self.consistent,
            "missing": self.missing,
            "orphan": self.orphan,
            "mismatch": self.mismatch,
            "counts": {
                "missing": len(self.missing),
                "orphan": len(self.orphan),
                "mismatch": len(self.mismatch),
            },
        }


def verify_fts_index(
    db: Session,
    *,
    workspace_id: int | None = None,
    check_trigram: bool = True,
) -> FtsConsistencyReport:
    """校验 FTS 索引与文档正文的一致性（0170，只读）.

    - missing：文档未删除且非文件夹，但 FTS 主表缺行或正文为空；
    - orphan：FTS 主表有正文，但文档不存在 / 已软删 / 是文件夹；
    - mismatch：FTS 主表 title 与文档 title 不符（内容漂移的轻量信号）；
    - 默认同时校验 trigram 影子表：与主表 rowid / 正文一致性。

    内存口径：不加载完整正文，只读取 ``length(content)`` 与前 64 字符指纹，
    避免万级文档时把数百 MB 正文拉进 Python（长度 + 前缀足以发现绝大多数漂移）。

    按 ``workspace_id`` 过滤时**跳过 orphan**：FTS 虚拟表没有 workspace 列，
    无法区分跨工作区行；只在全库校验时统计孤儿。

    只返回 id 与计数，不含正文或标题（H38：发现物只记定位信息）。
    """
    from sqlalchemy import select

    from cndb.plugins.documents.models import Document

    doc_q = select(Document.id, Document.title).where(
        Document.is_deleted == False,  # noqa: E712
        Document.is_folder == False,  # noqa: E712
    )
    if workspace_id is not None:
        doc_q = doc_q.where(Document.workspace_id == workspace_id)
    docs = {row[0]: row[1] for row in db.execute(doc_q).all()}

    fts_rows = _fts_fingerprints(db, "documents_fts")

    missing: list[int] = []
    mismatch: list[int] = []
    for doc_id, title in docs.items():
        row = fts_rows.get(doc_id)
        if row is None or row[1] == 0:
            missing.append(doc_id)
        elif row[0] != title:
            mismatch.append(doc_id)

    doc_ids = set(docs)
    # FTS 虚拟表无 workspace_id 列，无法区分跨工作区行；按工作区过滤时只报本区文档的
    # missing/mismatch，跳过 orphan（全库校验时才统计孤儿）。
    if workspace_id is None:
        orphan = sorted(doc_id for doc_id, row in fts_rows.items() if row[1] > 0 and doc_id not in doc_ids)
    else:
        orphan: list[int] = []

    if check_trigram:
        tri_rows = _fts_fingerprints(db, "documents_fts_tri")
        for doc_id in docs:
            tri = tri_rows.get(doc_id)
            main = fts_rows.get(doc_id)
            drifted = tri is not None and main is not None and tri[1:] != main[1:]
            if (tri is None or tri[1] == 0 or drifted) and doc_id not in missing:
                missing.append(doc_id)
        if workspace_id is None:
            for doc_id, row in tri_rows.items():
                if row[1] > 0 and doc_id not in doc_ids and doc_id not in orphan:
                    orphan.append(doc_id)

    return FtsConsistencyReport(missing=sorted(missing), orphan=sorted(orphan), mismatch=sorted(mismatch))


def rebuild_fts_index(db: Session) -> int:
    """全量重建 FTS5 索引（修复索引不一致时的兜底任务）.

    Returns:
        重建的文档数。
    """
    from sqlalchemy import select

    from cndb.plugins.documents.models import Document

    # 普通 FTS5 表（非 contentless）不支持 'delete-all' 特殊命令；直接 DELETE 全表。
    db.execute(text("DELETE FROM documents_fts"))
    db.execute(text("DELETE FROM documents_fts_tri"))
    docs = (
        db.execute(
            select(Document).where(
                Document.is_deleted == False,  # noqa: E712
                Document.is_folder == False,  # noqa: E712
            )
        )
        .scalars()
        .all()
    )

    from cndb.plugins.documents.services.content import latest_version, load_content

    count = 0
    params_list: list[dict[str, Any]] = []
    for doc in docs:
        v = latest_version(db, doc.id)
        content = load_content(v, doc)
        params_list.append(
            {
                "id": doc.id,
                "title": doc.title,
                "content": content[:65536],
                "summary": doc.summary[:2000],
                "author": doc.author,
            }
        )
        count += 1
    insert_sql = (
        "INSERT INTO {table}(rowid, title, content, summary, author) VALUES (:id, :title, :content, :summary, :author)"
    )
    for table in ("documents_fts", "documents_fts_tri"):
        for params in params_list:
            db.execute(text(insert_sql.format(table=table)), params)
    db.commit()
    return count


__all__ = [
    "FtsConsistencyReport",
    "ensure_fts_schema",
    "escape_query",
    "rebuild_fts_index",
    "reset_fts_schema_cache",
    "search_documents",
    "verify_fts_index",
]
