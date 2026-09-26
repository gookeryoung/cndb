# 报表模板增强设计（模板多样化 / PDF 中文 / 示例模板丰富化）

需求来源：`.trae/req/` 报表完善需求——1) 种子模板配置多样化；2) PDF 输出乱码修复；3) 员工名册等示例模板内容丰富化。涉及文件：`src/cndb/plugins/reports/routers/reports.py`、`src/cndb/cli/seed.py`、`tests/test_reports_renderers.py`、`tests/test_seed_report_examples.py`。

## 1. 模板配置多样化（seed 数据驱动）

REPORT_TEMPLATE_SPECS 每项新增可选键（缺省保持旧行为）：

- `output_format: str`（docx/xlsx/pdf，缺省 docx）
- `theme: str`（business/minimal/modern/engineering/academic，缺省 minimal）
- `parameters: list[dict]`（ParameterDef 形状：name/type/default/required/label）
- `cross_workspace_tables: list[tuple[str, str]]`（跨工作区引用：(工作区名, 表名)，从 tables_map 全局解析后并入 extra_table_ids）

分配矩阵（7 个模板，覆盖 3 种输出格式 / 5 种主题 / 参数化 / 跨工作区）：

| 模板 | 格式 | 主题 | 参数 | 跨工作区 |
| --- | --- | --- | --- | --- |
| 科研项目季度汇报 | docx | business | - | - |
| 电商销售月报 | xlsx | minimal | - | - |
| 产品开发交付进度报告 | docx | modern | - | - |
| WBS任务进度周报 | docx | engineering | - | - |
| 城市气温天气月报 | pdf | academic | 城市（string，默认"全部"） | - |
| 数据质量体检报告 | docx | academic | - | (某地区数据, 气温天气) |
| 员工名册 | pdf | business | 在职状态（string，默认"在职"） | - |

- `_seed_report_templates` 读取上述键创建 ReportTemplate；`_generate_sample_reports` 输出扩展名改为按 `tpl.output_format`（`{模板名}-示例报告.{ext}`）。
- 带参数的模板在 Jinja 中用 `params.get('参数名', 默认值)` 取值（沙箱允许 dict.get），默认值与 parameters.default 一致，保证 `params={}` 渲染结果与既有测试断言兼容。
- 城市气温天气月报新增"附录"节：按 `城市` 参数过滤明细（默认全部，取前 10 条），不改动既有统计节的表达式。
- 数据质量体检报告新增"跨工作区抽检"节：对 `records_by_table['气温天气']` 的 城市/天气/最高温_℃/最低温_℃ 做非空计数与完整率检查。
- 员工名册模板内容提取为模块级常量 `EMPLOYEE_ROSTER_TEMPLATE`（`_seed_sales_tables` 引用），便于单测直接渲染。

## 2. PDF 中文乱码修复（reports.py）

根因：`_render_pdf` 全部样式硬编码 Helvetica，`_ensure_pdf_font` 注册结果从未被使用；且候选字体文件在 Windows 上不存在导致注册静默失败。

- `_ensure_pdf_font` 改为返回"已注册字体名或 None"，`_pdf_font_state: list[str | None]` 缓存。
- 字体候选（按序尝试，`os.path.isfile` 探测）：Windows 优先 `C:/Windows/Fonts/simhei.ttf` → `msyh.ttc`(subfontIndex=0) → `msjh.ttc`(0) → `simsun.ttc`(0)；Linux 保留 NotoSansSC/WenQuanYi 原候选。TTC 用 `TTFont(name, path, subfontIndex=0)`。
- 注册成功后 `registerFontFamily(font, normal=font, bold=font, italic=font, boldItalic=font)`，使 RML `<b>/<i>` 标签不因缺粗体变体而崩溃。
- `_render_pdf`：`cjk = _ensure_pdf_font() or "Helvetica"`；Body/Heading 段落样式、表格样式命令（`_pdf_table_style_cmds(preset, cjk)` 的 FONTNAME 两行）、页眉/页脚 `canvas.setFont(cjk, ...)`、页眉标题 drawString 全部改用 cjk 字体；`_pdf_markdown_to_rml(text, cjk)` 的行内代码 `<font name>` 同步改用 cjk（Courier 无中文字形）。
- `_pdf_table_style_cmds` 新增可选参数 `cjk_font="Helvetica"`（默认值保持既有单参调用兼容）。

## 3. 员工名册模板内容（EMPLOYEE_ROSTER_TEMPLATE）

records 为员工扁平 dict（姓名/部门/部门负责人/入职日期/薪资/是否在职，link/lookup 已由 `_flatten_for_report` 展开为字符串）：

- 头部：生成日期 + 统计范围（params 在职状态，默认"在职"）。
- 一、人员概览：员工总数 / 在职人数 / 覆盖部门数 / 平均薪资 / 薪资区间（min~max，空数据用 `or 0` 兜底）。
- 二、员工名册：全字段表格，按在职状态参数过滤（在职/离职/全部）。
- 三、按部门统计：group_stats 人数/平均薪资/薪资合计。
- 四、离职人员名单：rejectattr 过滤，空列表输出"无"。
- 尾部：`---PAGE---` + 落款。

## 异常与兼容

- 字体注册全失败时回退 Helvetica 并 warning（旧行为，中文仍可能乱码但不崩溃）。
- `_generate_sample_reports` 渲染失败仅告警不中断 seed（既有约定不变）。
- API schema 无变化，前端类型无需同步。
