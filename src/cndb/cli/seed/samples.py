"""示例报告模板定义与落盘生成。

`REPORT_TEMPLATE_SPECS` 描述 8 组典型示例，覆盖各工作区、输出格式与主题风格。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _generate_sample_reports(
    db: Any, tables_map: dict[str, dict[str, Any]], owner: Any, datasets_dir: Path | None
) -> None:
    """渲染 REPORT_TEMPLATE_SPECS 中的全部示例模板，按模板输出格式（docx/xlsx/pdf）落盘到对应工作区数据集目录.

    复用渲染端点的沙箱环境 / 统计函数 / docx 渲染器，端到端验证模板可渲染；
    固定文件名（不带时间戳，避免 git 反复变更），每次 seed 覆盖重写。
    渲染失败仅告警不中断 seed（模板/数据问题不应阻塞演示数据注入）。
    """
    import datetime as dt

    from cndb.plugins.reports.models import ReportTemplate
    from cndb.plugins.reports.routers.reports import (
        _FORMAT_RENDERERS,
        _jinja_env,
        _load_table_records,
        _render_with_timeout,
    )
    from cndb.plugins.tables.models import DataTable

    if datasets_dir is None:
        print("[seed-示例报告] 跳过：datasets 目录不可用")
        return

    for spec in REPORT_TEMPLATE_SPECS:
        ws_tables = tables_map.get(spec["workspace"]) or {}
        main_tbl = ws_tables.get(spec["table"])
        if main_tbl is None:
            print(f"[seed-示例报告] 跳过：未找到 {spec['workspace']}/{spec['table']}（{spec['name']}）")
            continue
        tpl = (
            db.query(ReportTemplate)
            .filter(ReportTemplate.table_id == main_tbl.id, ReportTemplate.name == spec["name"])
            .first()
        )
        if tpl is None:
            print(f"[seed-示例报告] 跳过：模板未创建（{spec['name']}）")
            continue

        # 构建渲染上下文（与渲染端点 render_report 一致：主表 + extra 表 + generated_at）
        table, records = _load_table_records(db, main_tbl.id, owner)
        records_by_table: dict[str, list[dict[str, Any]]] = {}
        for etid in tpl.extra_table_ids:
            etable = db.get(DataTable, etid)
            if etable is None:
                continue
            _, erecords = _load_table_records(db, etid, owner)
            records_by_table[etable.name] = erecords
        ctx: dict[str, Any] = {
            "records": records,
            "table_name": table.name,
            "params": {},
            "records_by_table": records_by_table,
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        try:
            jinja_tmpl = _jinja_env.from_string(tpl.template_content)
            rendered = _render_with_timeout(jinja_tmpl, ctx)
            renderer = _FORMAT_RENDERERS.get(tpl.output_format)
            if renderer is None:
                print(f"[seed-示例报告] 跳过：不支持的输出格式 {tpl.output_format}（{spec['name']}）")
                continue
            file_bytes = renderer(rendered, ctx)
        except Exception as exc:  # 模板/数据问题不应阻塞 seed
            print(f"[seed-示例报告] {spec['name']} 渲染失败（请检查模板与数据集字段匹配）: {exc}")
            continue

        out_dir = datasets_dir / f"工作区-{spec['workspace']}"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{spec['name']}-示例报告.{tpl.output_format}"
            out_path.write_bytes(file_bytes)
        except OSError as exc:
            print(f"[seed-示例报告] 写入失败（{spec['name']}）: {exc}")
            continue
        print(f"[seed-示例报告] 生成: {out_path} ({len(file_bytes)} bytes)")


# ── 示例报告模板定义 ────────────────────────────────────
# 8 组典型示例（含既有科研项目季度汇报），覆盖 datasets 各工作区的代表性场景，
# 并在输出格式（docx/xlsx/pdf/html）、主题风格、参数化、跨工作区引用上保持配置多样性。
# 所有模板统一遵循"标题 → 摘要 → 数据统计 → 结论与建议"的正文结构：
# 摘要与各节分析段落均为数据驱动叙述（基于 stats/group_stats/set 计算插值），落款前附结论与建议。
# 1. 科研项目季度汇报 —— 跨表引用 + selectattr 匹配分组（科研项目管理，docx/business）
# 2. 电商销售月报 —— 单表分组聚合（某企业销售管理/电商销售，xlsx 数据导出）
# 3. 产品开发交付进度报告 —— non_empty 空值统计 + 分页（某企业销售管理/产品开发，docx/modern）
# 4. WBS 任务进度周报 —— selectattr 过滤 + 多维统计（项目管理，docx/engineering）
# 5. 城市气温天气月报 —— min/max 极值 + 嵌套分组 + 城市参数明细（某地区数据，pdf/academic）
# 6. 数据质量体检报告 —— 脏数据完整性边界 + 跨工作区抽检（低质量数据，docx/academic）
# 7. 日常待办任务清单 —— 任务状态/优先级/类型多维统计 + 高优先级明细（某企业销售管理/日常待办，html/modern）
# 8. 营销活动效果报告 —— 预算/线索/转化率聚合 + 渠道分组 + 活动明细（某企业销售管理/营销活动，html/business）
REPORT_TEMPLATE_SPECS: list[dict[str, Any]] = [
    {
        "workspace": "科研项目管理",
        "table": "科研项目",
        "extra_tables": ["科研经费", "项目进展", "课题负责人"],
        "name": "科研项目季度汇报",
        "description": "汇总科研项目概览、按类别/状态分组统计、经费拨付、研究进展与负责人名录",
        "output_format": "docx",
        "theme": "business",
        "content": (
            "# 科研项目季度汇报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set total_funding = stats(records, '经费总额_万元').sum %}\n"
            "{% set ongoing = records | selectattr('项目状态', 'equalto', '在研') | list | length %}\n"
            "本季度共梳理科研课题 {{ records | length }} 项，其中在研 {{ ongoing }} 项；经费总额合计 {{ total_funding | round(2) }} 万元，平均单课题经费 {{ stats(records, '经费总额_万元').avg | round(2) }} 万元。\n"
            "{% set cat_stats = group_stats(records, '项目类别', '经费总额_万元') %}\n"
            "{% if cat_stats %}\n"
            "{% set top_cat = cat_stats | sort(attribute='sum', reverse=true) | first %}\n"
            "经费主要投向「{{ top_cat.key }}」方向（{{ top_cat.count }} 项课题，合计 {{ top_cat.sum | round(2) }} 万元），经费结构详见下文分项统计。\n"
            "{% endif %}\n"
            "\n"
            "## 一、项目概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 项目总数 | {{ records | length }} |\n"
            "| 在研项目数 | {{ records | selectattr('项目状态', 'equalto', '在研') | list | length }} |\n"
            "| 有进展记录的课题数 | {{ stats(records_by_table['项目进展'], '课题编号').non_empty }} |\n"
            "| 经费总额（万元） | {{ stats(records, '经费总额_万元').sum | round(2) }} |\n"
            "| 经费平均值（万元） | {{ stats(records, '经费总额_万元').avg | round(2) }} |\n"
            "\n"
            "## 二、按项目类别统计\n"
            "\n"
            "| 项目类别 | 数量 | 经费合计（万元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '项目类别', '经费总额_万元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "{% if cat_stats %}"
            "从类别结构看，「{{ top_cat.key }}」以 {{ top_cat.count }} 项课题、{{ top_cat.sum | round(2) }} 万元经费居各方向首位；建议后续保持重点方向的资源倾斜，并关注薄弱类别的培育。\n"
            "{% endif %}"
            "\n"
            "## 三、按项目状态统计\n"
            "\n"
            "| 项目状态 | 数量 | 经费合计（万元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '项目状态', '经费总额_万元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "已登记结题日期的课题 {{ stats(records, '结题日期').non_empty }} 项，其余课题仍在推进中；建议对照计划周期跟踪各课题里程碑，对明显滞后的课题提前协调资源。\n"
            "\n"
            "## 四、经费拨付汇总\n"
            "\n"
            "{% if records_by_table['科研经费'] %}"
            "| 预算科目 | 预算金额（万元） | 已拨金额（万元） | 拨付率 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for g in group_stats(records_by_table['科研经费'], '预算科目', '预算金额_万元') %}"
            "{% set g2 = group_stats(records_by_table['科研经费'], '预算科目', '已拨金额_万元') %}"
            "{% set matched = g2 | selectattr('key', 'equalto', g.key) | list %}"
            "{% set disbursed = matched[0].sum if matched else 0 %}"
            "| {{ g.key }} | {{ g.sum | round(2) }} | {{ disbursed | round(2) }} | {{ '%.1f%%' | format(disbursed / g.sum * 100) if g.sum > 0 else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "经费状态统计：\n"
            "{% for g in group_stats(records_by_table['科研经费'], '经费状态', '已拨金额_万元') %}"
            "- **{{ g.key }}**：{{ g.count }} 笔，已拨 {{ g.sum | round(2) }} 万元\n"
            "{% endfor %}"
            "{% set fund_all = records_by_table['科研经费'] %}"
            "拨付进度方面，已拨金额合计 {{ stats(fund_all, '已拨金额_万元').sum | round(2) }} 万元，占预算合计 {{ stats(fund_all, '预算金额_万元').sum | round(2) }} 万元的 {{ '%.1f%%' | format(stats(fund_all, '已拨金额_万元').sum / stats(fund_all, '预算金额_万元').sum * 100) if stats(fund_all, '预算金额_万元').sum else 'N/A' }}；未拨付部分建议按科目逐项核对堵点，避免影响课题支出。\n"
            "{% endif %}"
            "\n"
            "## 五、研究进展汇总\n"
            "\n"
            "{% if records_by_table['项目进展'] %}"
            "| 进展阶段 | 条目数 | 平均进度 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records_by_table['项目进展'], '进展阶段', '进度百分比') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(1) }}% |\n"
            "{% endfor %}"
            "\n"
            "按季度分布：\n"
            "{% for g in group_stats(records_by_table['项目进展'], '报告季度', '进度百分比') %}"
            "- **{{ g.key }}**：{{ g.count }} 条进展记录\n"
            "{% endfor %}"
            "本季度进展记录共 {{ records_by_table['项目进展'] | length }} 条，平均进度 {{ stats(records_by_table['项目进展'], '进度百分比').avg | round(1) }}%；对平均进度明显偏低的阶段建议安排专项督导，并在下一季度跟踪整改效果。\n"
            "{% endif %}"
            "\n"
            "## 六、负责人名录\n"
            "\n"
            "{% if records_by_table['课题负责人'] %}"
            "| 姓名 | 职称 | 是否 PI | 研究方向 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for r in records_by_table['课题负责人'] %}"
            "| {{ r['姓名'] }} | {{ r['职称'] }} | {{ '是' if r['是否PI'] else '否' }} | {{ r['研究方向'] }} |\n"
            "{% endfor %}"
            "{% endif %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 经费管理：对照拨付率梳理未拨付科目，优先保障设备费与人员费等刚性支出，确保课题执行不受资金影响。\n"
            "2. 进度督导：对进度滞后的在研课题建立月度跟踪机制，必要时调整阶段计划并同步至项目进展表。\n"
            "3. 成果规划：临近结题的课题应提前规划论文、专利、软件著作权等成果形式，避免结题前集中补齐材料。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "电商销售",
        "extra_tables": [],
        "name": "电商销售月报",
        "description": "按商品类别与支付方式分组汇总销售额、客单价与评分（xlsx 数据导出）",
        "output_format": "xlsx",
        "content": (
            "# 电商销售月报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set sales_sum = stats(records, '销售额').sum %}\n"
            "本期共录入 {{ records | length }} 笔订单，销售额合计 {{ sales_sum | round(2) }} 元，平均客单价 {{ stats(records, '销售额').avg | round(2) }} 元，平均评分 {{ stats(records, '评分').avg | round(1) }} 分。\n"
            "{% set cat_stats = group_stats(records, '商品类别', '销售额') %}\n"
            "{% if cat_stats %}\n"
            "{% set top_cat = cat_stats | sort(attribute='sum', reverse=true) | first %}\n"
            "「{{ top_cat.key }}」为销售额最高类目（{{ top_cat.count }} 笔订单，合计 {{ top_cat.sum | round(2) }} 元），类目贡献详见第二节。\n"
            "{% endif %}\n"
            "\n"
            "## 一、销售概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 订单总数 | {{ records | length }} |\n"
            "| 销售额合计（元） | {{ stats(records, '销售额').sum | round(2) }} |\n"
            "| 平均客单价（元） | {{ stats(records, '销售额').avg | round(2) }} |\n"
            "| 平均评分 | {{ stats(records, '评分').avg | round(1) }} |\n"
            "| 商品类别数 | {{ group_stats(records, '商品类别', '销售额') | length }} |\n"
            "\n"
            "## 二、按商品类别汇总\n"
            "\n"
            "| 商品类别 | 订单数 | 销售额（元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '商品类别', '销售额') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "类目销售额集中度较高，头部类目贡献了主要业绩；建议结合库存与毛利数据评估促销资源投放结构，避免过度依赖单一类目。\n"
            "\n"
            "## 三、按支付方式汇总\n"
            "\n"
            "| 支付方式 | 订单数 | 销售额（元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '支付方式', '销售额') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 类目运营：对销售额最高的类目维持当前投入，同时为第二梯队类目设计组合促销，提升整体抗波动能力。\n"
            "2. 支付体验：关注各支付方式的订单分布变化，若单一渠道占比持续上升，建议评估其手续费成本与结算周期。\n"
            "3. 客单价提升：可通过满减、套装组合等方式拉升平均客单价，并持续跟踪评分反馈定位体验短板。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "产品开发",
        "extra_tables": [],
        "name": "产品开发交付进度报告",
        "description": "项目交付状态概览（含未交付空值统计）、按状态与片区分组汇总",
        "output_format": "docx",
        "theme": "modern",
        "content": (
            "# 产品开发交付进度报告\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set delivered = stats(records, '实际交付日期').non_empty %}\n"
            "本期共跟踪项目 {{ records | length }} 个，已交付 {{ delivered }} 个、未交付 {{ records | length - delivered }} 个，整体平均进度 {{ stats(records, '进度百分比').avg | round(1) }}%；合同总额合计 {{ stats(records, '合同金额_万元').sum | round(2) }} 万元。\n"
            "{% set doing = records | selectattr('项目状态', 'equalto', '进行中') | list %}\n"
            "进行中项目 {{ doing | length }} 个，是下一阶段交付管理的主要对象，风险项与资源需求详见下文分析。\n"
            "\n"
            "## 一、项目概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 项目总数 | {{ records | length }} |\n"
            "| 已交付项目数 | {{ stats(records, '实际交付日期').non_empty }} |\n"
            "| 未交付项目数 | {{ records | length - stats(records, '实际交付日期').non_empty }} |\n"
            "| 合同总额（万元） | {{ stats(records, '合同金额_万元').sum | round(2) }} |\n"
            "| 平均进度 | {{ stats(records, '进度百分比').avg | round(1) }}% |\n"
            "\n"
            "## 二、按项目状态统计\n"
            "\n"
            "| 项目状态 | 项目数 | 平均进度 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '项目状态', '进度百分比') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(1) }}% |\n"
            "{% endfor %}"
            "\n"
            "对进行中且进度偏低的项目，应结合备注列的原因说明逐项确认恢复时间；涉及客户方变更的项目建议升级沟通并固化变更流程，避免逾期交付。\n"
            "\n"
            "## 三、按片区汇总\n"
            "\n"
            "| 片区 | 项目数 | 合同金额（万元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '片区', '合同金额_万元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(2) }} |\n"
            "{% endfor %}"
            "\n"
            "片区维度上，合同金额与项目数量分布并不均衡；资源投入应向项目集中、交付压力大的片区倾斜。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 交付风险：对未交付且进度低于 50% 的项目建立风险清单，明确责任人与恢复计划，每周更新状态。\n"
            "2. 客户协同：备注中涉及客户需求变更或组织调整的项目，建议升级至客户高层沟通，并固化变更流程。\n"
            "3. 资源调配：结合片区合同金额与项目阶段分布动态调整实施人力，优先保障临近计划交付日期的项目。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "项目管理",
        "table": "WBS任务分解",
        "extra_tables": [],
        "name": "WBS任务进度周报",
        "description": "顶层/子任务结构概览，按任务状态与优先级多维统计进度与工期",
        "output_format": "docx",
        "theme": "engineering",
        "content": (
            "# WBS 任务进度周报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set root_tasks = records | selectattr('父任务ID', 'equalto', 'ROOT') | list %}\n"
            "{% set done_count = records | selectattr('任务状态', 'equalto', '已完成') | list | length %}\n"
            "本期跟踪 WBS 任务共 {{ records | length }} 项，其中顶层任务 {{ root_tasks | length }} 项；总工期 {{ stats(records, '工期_天').sum }} 天，整体平均进度 {{ stats(records, '进度百分比').avg | round(1) }}%。\n"
            "已完成任务 {{ done_count }} 项，完成率 {{ '%.1f%%' | format(done_count / records | length * 100) if records else 'N/A' }}；进度结构详见下文分组统计。\n"
            "\n"
            "## 一、任务概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 任务总数 | {{ records | length }} |\n"
            "| 顶层任务数 | {{ records | selectattr('父任务ID', 'equalto', 'ROOT') | list | length }} |\n"
            "| 总工期（天） | {{ stats(records, '工期_天').sum }} |\n"
            "| 平均进度 | {{ stats(records, '进度百分比').avg | round(1) }}% |\n"
            "\n"
            "## 二、按任务状态统计\n"
            "\n"
            "| 任务状态 | 任务数 | 平均进度 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '任务状态', '进度百分比') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.avg | round(1) }}% |\n"
            "{% endfor %}"
            "\n"
            "建议对进行中任务按周核对进度偏差；对尚未启动的任务确认前置条件与依赖关系是否就绪，避免关键路径出现断点。\n"
            "\n"
            "## 三、按优先级统计\n"
            "\n"
            "| 优先级 | 任务数 | 工期合计（天） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '优先级', '工期_天') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum }} |\n"
            "{% endfor %}"
            "\n"
            "高优先级任务的工期占比直接影响关键路径；建议将资源优先投向高优先级与长工期任务，降低整体延期风险。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 关键路径：围绕高优先级顶层任务复核关键路径，工期偏差超过一周的任务需说明原因并给出赶工方案。\n"
            "2. 任务闭环：已完成任务及时归档经验，进行中任务保持周度进度刷新，避免进度数据失真。\n"
            "3. 依赖管理：跨任务依赖较多时，在周例会上对齐上下游交付物，减少等待与返工。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某地区数据",
        "table": "气温天气",
        "extra_tables": [],
        "name": "城市气温天气月报",
        "description": "全局极值与分城市最高/最低气温、平均湿度嵌套分组统计，附城市明细",
        "output_format": "pdf",
        "theme": "academic",
        "parameters": [
            {"name": "城市", "type": "string", "default": "全部", "required": False, "label": "明细筛选城市"}
        ],
        "content": (
            "# 城市气温天气月报\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set city_groups = group_stats(records, '城市', '最高温_℃') %}\n"
            "本月共收录 {{ records | length }} 条城市气温观测记录，覆盖 {{ city_groups | length }} 个城市；全局最高气温 {{ stats(records, '最高温_℃').max }}℃，最低气温 {{ stats(records, '最低温_℃').min }}℃，平均湿度 {{ stats(records, '湿度_%').avg | round(1) }}%。\n"
            "{% if city_groups %}\n"
            "{% set hot_city = city_groups | rejectattr('max', 'none') | sort(attribute='max', reverse=true) | first %}\n"
            "{% set cold_city = city_groups | rejectattr('min', 'none') | sort(attribute='min') | first %}\n"
            "分城市看，「{{ hot_city.key }}」观测到全月最高气温 {{ hot_city.max }}℃，「{{ cold_city.key }}」最低气温低至 {{ cold_city.min }}℃；城市间差异详见第二节。\n"
            "{% endif %}\n"
            "\n"
            "## 一、总体概况\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 记录条数 | {{ records | length }} |\n"
            "| 覆盖城市数 | {{ group_stats(records, '城市', '最高温_℃') | length }} |\n"
            "| 全局最高气温（℃） | {{ stats(records, '最高温_℃').max }} |\n"
            "| 全局最低气温（℃） | {{ stats(records, '最低温_℃').min }} |\n"
            "| 平均湿度（%） | {{ stats(records, '湿度_%').avg | round(1) }} |\n"
            "\n"
            "## 二、分城市统计\n"
            "\n"
            "| 城市 | 记录数 | 最高气温（℃） | 最低气温（℃） | 平均湿度（%） |\n"
            "| --- | --- | --- | --- | --- |\n"
            "{% for g in group_stats(records, '城市', '最高温_℃') %}"
            "{% set g_low = group_stats(records, '城市', '最低温_℃') | selectattr('key', 'equalto', g.key) | list %}"
            "{% set g_hum = group_stats(records, '城市', '湿度_%') | selectattr('key', 'equalto', g.key) | list %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.max }} | {{ g_low[0].min if g_low else 'N/A' }} | {{ g_hum[0].avg | round(1) if g_hum else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "城市间气温与湿度差异显著，跨区域业务安排（物流、出行、用能）应参考城市级数据而非全局均值；对极值城市建议补充风速与湿度交叉分析。\n"
            "\n"
            "## 三、天气类型分布\n"
            "\n"
            "| 天气 | 天数 |\n"
            "| --- | --- |\n"
            "{% for g in group_stats(records, '天气', '最高温_℃') %}"
            "| {{ g.key }} | {{ g.count }} |\n"
            "{% endfor %}"
            "\n"
            "天气类型统计可与气温极值交叉验证：极端天气对应日期的观测值建议复核原始记录，确保月度统计口径一致。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 极值监测：全月气温极值均可在附录明细中定位到具体日期，建议对极值日记录做原始数据复核。\n"
            "2. 城市对比：分城市温差显著，区域运营决策应基于城市级统计，避免全局均值掩盖局部特征。\n"
            "3. 数据质量：发现单日观测值异常偏高或偏低时，应回溯原始记录并在下期报告中标注修正情况。\n"
            "\n"
            "## 附录：城市明细（前 10 条）\n"
            "\n"
            "{% set city = params.get('城市', '全部') %}\n"
            "{% if city == '全部' %}{% set scoped = records %}"
            "{% else %}{% set scoped = records | selectattr('城市', 'equalto', city) | list %}{% endif %}\n"
            "统计范围：{{ city }}\n"
            "\n"
            "| 城市 | 天气 | 最高温_℃ | 最低温_℃ | 湿度_% |\n"
            "| --- | --- | --- | --- | --- |\n"
            "{% for r in scoped[:10] %}"
            "| {{ r['城市'] }} | {{ r['天气'] }} | {{ r['最高温_℃'] }} | {{ r['最低温_℃'] }} | {{ r['湿度_%'] }} |\n"
            "{% endfor %}"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "低质量数据",
        "table": "19-特殊值杂项",
        "extra_tables": ["17-数字格式大全"],
        "name": "数据质量体检报告",
        "description": "按字段统计非空条数与完整率，覆盖 JSON/长号等特殊值、跨工作区抽检与多表附加检查",
        "output_format": "docx",
        "theme": "academic",
        "cross_workspace_tables": [("某地区数据", "气温天气")],
        "content": (
            "# 数据质量体检报告\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "本次体检覆盖主表「特殊值杂项」（{{ records | length }} 条记录）与附加表「数字格式大全」，并对跨工作区表「气温天气」进行了抽检；重点核查 JSON、邮箱、手机号、长文本与混合数值等字段的完整率。\n"
            "总体来看，邮箱、手机号等结构化字段完整率保持在较高水平，空值主要集中于文本类可选字段；完整率明细与改进建议见下文。\n"
            "\n"
            "## 一、主表完整性检查（特殊值杂项）\n"
            "\n"
            "| 字段 | 非空条数 | 记录总数 | 完整率 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for f in ['JSON对象', '邮箱', '手机号', '客户备注', '混合数值'] %}"
            "{% set s = stats(records, f) %}"
            "| {{ f }} | {{ s.non_empty }} | {{ records | length }} | {{ '%.1f%%' | format(s.non_empty / records | length * 100) if records else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "混合数值合计：{{ stats(records, '混合数值').sum | round(2) }}\n"
            "\n"
            "从完整率分布看，结构化字段（邮箱/手机号）完整率普遍高于自由文本字段，符合录入习惯特征；空值集中的字段建议在字段定义层面区分必填与选填，减少无意义空值。\n"
            "\n"
            "## 二、附加表完整性检查（数字格式大全）\n"
            "\n"
            "{% if records_by_table['17-数字格式大全'] %}"
            "{% set extra_records = records_by_table['17-数字格式大全'] %}"
            "| 字段 | 非空条数 | 记录总数 |\n"
            "| --- | --- | --- |\n"
            "{% for f in ['千分位整数', '科学计数法', '前导零编号', '十五位长号'] %}"
            "{% set s = stats(extra_records, f) %}"
            "| {{ f }} | {{ s.non_empty }} | {{ extra_records | length }} |\n"
            "{% endfor %}"
            "数字格式类字段完整率良好，说明导入端对千分位、科学计数法等格式的解析稳定；后续新增格式时应同步补充本节检查项。\n"
            "{% else %}附加表无数据{% endif %}\n"
            "\n"
            "## 三、跨工作区抽检（某地区数据/气温天气）\n"
            "\n"
            "{% if records_by_table['气温天气'] %}"
            "{% set wx = records_by_table['气温天气'] %}"
            "| 字段 | 非空条数 | 记录总数 | 完整率 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for f in ['城市', '天气', '最高温_℃', '最低温_℃'] %}"
            "{% set s = stats(wx, f) %}"
            "| {{ f }} | {{ s.non_empty }} | {{ wx | length }} | {{ '%.1f%%' | format(s.non_empty / wx | length * 100) if wx else 'N/A' }} |\n"
            "{% endfor %}"
            "跨工作区抽检与主表使用同一套统计口径，结果可直接比较；若抽检完整率明显低于主表，应优先排查导入映射环节。\n"
            "{% else %}跨工作区数据不可用{% endif %}\n"
            "\n"
            "## 四、检查说明\n"
            "\n"
            "- 完整率 100% 表示该字段全部记录非空；\n"
            "- 非空计数按原始值统计（None 与空串视为空），与前端报表统计口径一致；\n"
            "- 数字格式类字段仅检查存在性，不校验格式合法性。\n"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 完整率治理：对完整率低于 100% 的字段建立补录清单，明确责任人与时限，避免长期积累。\n"
            "2. 录入规范：在录入与导入模板中区分必填与选填字段，并对邮箱、手机号等结构化字段开启格式校验。\n"
            "3. 巡检机制：将本报告纳入数据治理例行巡检，按周生成并跟踪完整率变化趋势。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "日常待办",
        "extra_tables": [],
        "name": "日常待办任务清单",
        "description": "按状态/优先级/类型多维统计销售团队待办任务，附高优先级任务明细（html 输出）",
        "output_format": "html",
        "theme": "modern",
        "content": (
            "# 日常待办任务清单\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set done_count = records | selectattr('状态', 'equalto', '已完成') | list | length %}\n"
            "本期清单共 {{ records | length }} 项任务，其中已完成 {{ done_count }} 项、进行中 {{ records | selectattr('状态', 'equalto', '进行中') | list | length }} 项、待办 {{ records | selectattr('状态', 'equalto', '待办') | list | length }} 项、已取消 {{ records | selectattr('状态', 'equalto', '已取消') | list | length }} 项，整体完成率 {{ '%.1f%%' | format(done_count / records | length * 100) if records else 'N/A' }}。\n"
            "高优先级任务共 {{ records | selectattr('优先级', 'equalto', '高') | list | length }} 项，是本期资源投入的重点，明细见第四节。\n"
            "\n"
            "## 一、任务概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 任务总数 | {{ records | length }} |\n"
            "| 已完成 | {{ records | selectattr('状态', 'equalto', '已完成') | list | length }} |\n"
            "| 进行中 | {{ records | selectattr('状态', 'equalto', '进行中') | list | length }} |\n"
            "| 待办 | {{ records | selectattr('状态', 'equalto', '待办') | list | length }} |\n"
            "| 已取消 | {{ records | selectattr('状态', 'equalto', '已取消') | list | length }} |\n"
            "| 高优先级任务数 | {{ records | selectattr('优先级', 'equalto', '高') | list | length }} |\n"
            "\n"
            "## 二、按优先级统计\n"
            "\n"
            "| 优先级 | 任务数 | 占比 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '优先级', '优先级') %}"
            "| {{ g.key }} | {{ g.count }} | {{ '%.1f%%' | format(g.count / records | length * 100) if records else 'N/A' }} |\n"
            "{% endfor %}"
            "\n"
            "优先级分布反映了团队精力投放结构；若高优先级占比持续偏高，建议评估任务分级标准是否过松，避免「全都紧急」导致优先级失效。\n"
            "\n"
            "## 三、按任务类型统计\n"
            "\n"
            "| 任务类型 | 任务数 | 已完成数 |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '待办类型', '优先级') %}"
            "{% set done = records | selectattr('待办类型', 'equalto', g.key) | selectattr('状态', 'equalto', '已完成') | list | length %}"
            "| {{ g.key }} | {{ g.count }} | {{ done }} |\n"
            "{% endfor %}"
            "\n"
            "任务类型的完成率差异能暴露流程堵点：完成率明显偏低的类型通常是资源或依赖不足的环节，应优先安排对接与跟进。\n"
            "\n"
            "## 四、高优先级任务明细\n"
            "\n"
            "{% set high = records | selectattr('优先级', 'equalto', '高') | list %}\n"
            "| 待办编号 | 待办标题 | 待办类型 | 状态 | 截止日期 | 备注 |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "{% for r in high %}"
            "| {{ r['待办编号'] }} | {{ r['待办标题'] }} | {{ r['待办类型'] }} | {{ r['状态'] }} | {{ r['截止日期'] }} | {{ r['备注'] or '-' }} |\n"
            "{% endfor %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 重点保障：高优先级任务按截止日期倒排计划，明确每日跟进人，避免临近截止集中突击。\n"
            "2. 状态维护：任务完成后及时更新状态与完成日期，保持清单与实际进展一致，便于复盘。\n"
            "3. 类型均衡：对完成率偏低的任务类型复盘原因（依赖、资源或流程），必要时拆分为更小的可执行任务。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
    {
        "workspace": "某企业销售管理",
        "table": "营销活动",
        "extra_tables": [],
        "name": "营销活动效果报告",
        "description": "汇总营销活动预算/线索/转化率，按渠道与状态分组，附重点活动明细（html 输出）",
        "output_format": "html",
        "theme": "business",
        "content": (
            "# 营销活动效果报告\n"
            "\n"
            "> 生成日期：{{ generated_at }}\n"
            "\n"
            "## 摘要\n"
            "\n"
            "{% set budget_sum = stats(records, '预算_元').sum %}\n"
            "{% set spend_sum = stats(records, '实际花费_元').sum %}\n"
            "{% set leads_sum = stats(records, '线索数').sum %}\n"
            "本期共复盘营销活动 {{ records | length }} 场（其中重点活动 {{ records | selectattr('是否重点', 'equalto', '是') | list | length }} 场），预算合计 {{ budget_sum | round(0) | int }} 元、实际花费 {{ spend_sum | round(0) | int }} 元，预算执行率 {{ '%.1f%%' | format(spend_sum / budget_sum * 100) if budget_sum else 'N/A' }}；累计获取线索 {{ leads_sum | round(0) | int }} 条，平均转化率 {{ stats(records, '转化率_%').avg | round(2) }}%。\n"
            "{% if leads_sum %}\n"
            "平均单线索成本约 {{ (spend_sum / leads_sum) | round(2) }} 元，可结合各渠道转化率评估投放结构的优化空间。\n"
            "{% endif %}\n"
            "\n"
            "## 一、总体效果概览\n"
            "\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 活动总数 | {{ records | length }} |\n"
            "| 重点活动数 | {{ records | selectattr('是否重点', 'equalto', '是') | list | length }} |\n"
            "| 预算合计（元） | {{ stats(records, '预算_元').sum | round(0) | int }} |\n"
            "| 实际花费合计（元） | {{ stats(records, '实际花费_元').sum | round(0) | int }} |\n"
            "| 线索总数 | {{ stats(records, '线索数').sum | round(0) | int }} |\n"
            "| 平均转化率（%） | {{ stats(records, '转化率_%').avg | round(2) }} |\n"
            "\n"
            "## 二、按渠道类型统计\n"
            "\n"
            "| 渠道类型 | 活动数 | 预算合计（元） | 线索合计 |\n"
            "| --- | --- | --- | --- |\n"
            "{% for g in group_stats(records, '渠道类型', '预算_元') %}"
            "{% set gl = group_stats(records, '渠道类型', '线索数') | selectattr('key', 'equalto', g.key) | list %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(0) | int }} | {{ gl[0].sum | int if gl else 0 }} |\n"
            "{% endfor %}"
            "\n"
            "渠道评估应同时看线索量与单线索成本：线索量大的渠道若成本同步走高，需关注线索质量；小渠道转化率突出时可考虑加大测试预算。\n"
            "\n"
            "## 三、按活动状态统计\n"
            "\n"
            "| 活动状态 | 活动数 | 预算合计（元） |\n"
            "| --- | --- | --- |\n"
            "{% for g in group_stats(records, '活动状态', '预算_元') %}"
            "| {{ g.key }} | {{ g.count }} | {{ g.sum | round(0) | int }} |\n"
            "{% endfor %}"
            "\n"
            "进行中与已排期的活动需按周同步进展，避免预算沉淀在低效活动上；已结束活动应及时沉淀复盘结论并归档素材。\n"
            "\n"
            "## 四、重点活动明细\n"
            "\n"
            "{% set key_acts = records | selectattr('是否重点', 'equalto', '是') | list %}\n"
            "| 活动编号 | 活动名称 | 渠道类型 | 负责人 | 联系邮箱 | 活动页面 | 预算（元） | 线索数 | 转化率（%） |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "{% for r in key_acts %}"
            "| {{ r['活动编号'] }} | {{ r['活动名称'] }} | {{ r['渠道类型'] }} | {{ r['负责人'] }} "
            "| {{ r['负责人邮箱'] }} | {{ r['活动页面'] }} | {{ r['预算_元'] }} | {{ r['线索数'] }} | {{ r['转化率_%'] }} |\n"
            "{% endfor %}"
            "\n"
            "## 结论与建议\n"
            "\n"
            "1. 投放结构：以单线索成本与转化率双指标评估各渠道，向「低成本、高转化」渠道倾斜预算，收缩长期低效渠道。\n"
            "2. 活动复盘：已结束活动在两周内完成复盘并归档素材，沉淀可复用的活动模板与话术。\n"
            "3. 线索承接：高线索量活动应提前准备销售承接方案，明确响应时限，避免线索流失。\n"
            "\n"
            "---PAGE---\n"
            "*本报告由 cndb 自动生成，数据截止 {{ generated_at }}*"
        ),
    },
]
