# 报表模板增强设计（模板多样化 / PDF 中文 / HTML 输出 / 示例模板丰富化）

需求来源：`.trae/req/` 报表完善需求——1) 种子模板配置多样化；2) PDF 输出乱码修复；3) 员工名册等示例模板内容丰富化；4) 输出格式覆盖 html、字段类型多样化、示例数据贴近真实业务。涉及文件：`src/cndb/plugins/reports/routers/reports.py`、`src/cndb/plugins/reports/models.py`、`src/cndb/cli/seed.py`、`frontend/src/pages/reports/ReportsPage.tsx`、`tests/test_reports_renderers.py`、`tests/test_seed_report_examples.py`、`tests/test_backup_seed_roundtrip.py`。

## 0. HTML 输出格式

- `OutputFormat` 新增 `HTML = "html"`；`_FORMAT_RENDERERS` 注册 `_render_html`；`_CONTENT_TYPES` 映射 `text/html; charset=utf-8`。
- `_render_html(rendered_text, ctx, theme)`：Markdown 风格标题/表格/`**粗体**`/`` `代码` ``/引用块转自包含 HTML 文档；`---PAGE---` 转 `page-break-after: always` 打印分页符；文本先经 `_html_escape` 转义再加标签（`_html_rich_text`），防注入。
- 主题应用：`get_theme_preset(theme)` 的 `heading_colors[0]` 作标题色、`table_header_bg/table_header_color` 作表头配色，内联 CSS 无外部依赖。
- 前端 `ReportsPage.tsx` FORMAT_OPTIONS 新增 `{ value: 'html', label: 'HTML (.html)' }`；`api/types.ts` 的 `output_format` 为 string 无需改类型。

## 1. 模板配置多样化（seed 数据驱动）

REPORT_TEMPLATE_SPECS 每项新增可选键（缺省保持旧行为）：

- `output_format: str`（docx/xlsx/pdf/html，缺省 docx）
- `theme: str`（business/minimal/modern/engineering/academic，缺省 minimal）
- `parameters: list[dict]`（ParameterDef 形状：name/type/default/required/label）
- `cross_workspace_tables: list[tuple[str, str]]`（跨工作区引用：(工作区名, 表名)，从 tables_map 全局解析后并入 extra_table_ids）

分配矩阵（8 个模板，覆盖 4 种输出格式 / 5 种主题 / 参数化 / 跨工作区）：

| 模板 | 格式 | 主题 | 参数 | 跨工作区 |
| --- | --- | --- | --- | --- |
| 科研项目季度汇报 | docx | business | - | - |
| 电商销售月报 | xlsx | minimal | - | - |
| 产品开发交付进度报告 | docx | modern | - | - |
| WBS任务进度周报 | docx | engineering | - | - |
| 城市气温天气月报 | pdf | academic | 城市（string，默认"全部"） | - |
| 数据质量体检报告 | docx | academic | - | (某地区数据, 气温天气) |
| 日常待办任务清单 | html | modern | - | - |
| 营销活动效果报告 | html | business | - | - |
| 员工名册 | pdf | business | 在职状态（string，默认"在职"） | - |

- 新增数据集 `examples/datasets/工作区-某企业销售管理/营销活动.csv`（14 行）：字段类型覆盖 text/select/number/float/date/email/url/phone/boolean（是否重点 是/否），演示 CSV 导入类型推断多样性。
- 日常待办任务清单：任务概览（按状态计数 + 高优先级数）、按优先级统计（含占比）、按任务类型统计（已完成数）、高优先级任务明细表。
- 营销活动效果报告：总体概览（预算/实际花费/线索/平均转化率）、按渠道类型分组（嵌套 selectattr 匹配线索合计）、按活动状态分组、重点活动明细表（含邮箱/活动页面字段）。

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

## 3. 员工表与员工名册模板

员工表（`_seed_sales_tables` 硬编码）扩展为 12 行真实规模数据，字段类型覆盖 text/link/lookup/select/date/number/phone/email：

- 字段：工号(text, required)、姓名(text, required)、部门(link→部门表 单选)、职位(select：总监/经理/工程师/专员/会计/出纳)、入职日期(date)、薪资(number)、手机号(phone)、邮箱(email)、是否在职(select 是/否)、负责人(lookup 经部门解析)。
- 行数据：12 名员工分布 4 部门（技术 4 / 市场 3 / 人事 2 / 财务 3），在职 9 人、离职 3 人（赵六/郑一/褚四），薪资 8000~18000。

records 为员工扁平 dict（link/lookup 已由 `_flatten_for_report` 展开为字符串），EMPLOYEE_ROSTER_TEMPLATE：

- 参数 `在职状态`：`EMPLOYEE_ROSTER_PARAMETER` 声明 `options: ["在职", "离职", "全部"]`、default "在职"；前端渲染参数弹窗对含 options 的参数渲染下拉菜单，渲染端点校验取值（非法值 400，空值/缺省放行由模板 default 兜底）。
- 头部：生成日期 + 统计范围（params 在职状态，默认"在职"）。
- 模板顶部按参数计算 `shown` 集合（离职=rejectattr 在职=是；全部=全量；否则=rejectattr 否），以下各节统一基于 `shown`。
- 头部引言后新增「摘要」节：一句数据驱动导语（收录人数/统计范围/覆盖部门数/在职与离职人数/月度薪资总成本/人均月薪，全部基于 `shown` 插值）。
- 一、人员概览：员工总数 / 在职人数 / 离职人数 / 覆盖部门数 / 平均薪资 / 薪资区间 / 月度薪资总成本（基于 `shown`，空数据用 `or 0` 兜底）。
- 二、员工名册：工号|姓名|职位|部门|部门负责人|入职日期|薪资|手机号|是否在职 全字段表格，遍历 `shown`；表后附一段口径说明（关联字段解析、薪资月度口径）。
- 三、按部门统计：group_stats(shown) 人数/平均薪资/薪资合计；表后附人才密度解读。
- 四、按职位统计：group_stats(shown) 人数/平均薪资/最高薪资；表后附薪资带宽解读。
- 五、离职人员名单：固定基于全量 records（语义为"全公司离职人员"），rejectattr 过滤，含手机号，空列表输出"无"。
- 尾部：结论与建议节（编制管理/薪酬校准/口径说明三条，口径说明固定提示"名册范围由参数控制、离职名单固定全量"）+ `---PAGE---` + 落款。

## 模板正文叙述结构（摘要/分析与结论建议）

- 适用范围：REPORT_TEMPLATE_SPECS 全部 8 组模板与 EMPLOYEE_ROSTER_TEMPLATE 统一遵循"标题 → 摘要 → 数据统计 → 结论与建议"结构。
- 「摘要」为标题引言后的无编号二级标题节，1-2 段数据驱动叙述；「结论与建议」为落款（`---PAGE---`）前的无编号二级标题节，3 条编号建议；城市月报的「结论与建议」置于附录之前，附录保持收尾位置。
- 各主要统计节表格后按需附一段分析段落（类别集中度/风险提示/口径说明等），每份模板叙述性正文（非标题/表格/引用/列表行）不少于 200 字符。
- 叙述均为数据驱动插值而非固定文案：基于 `stats`/`group_stats` 计算后用 `{% set %}` 存变量，再用 `{{ var | round }}`/`'%.1f%%' | format(...)` 插值；极值/头部分组用 `sort(attribute=..., reverse=true) | first` 选取，对 `min/max` 可能为 None 的分组先 `rejectattr('字段', 'none')` 再排序。
- 除法（占比/执行率/完成率）沿用既有守卫写法 `{{ '%.1f%%' | format(a / b * 100) if b else 'N/A' }}`；空数据场景仅减少叙述细节，不产生渲染错误。
- 测试锚定（`tests/test_seed_report_examples.py`）：`test_all_specs_contain_narrative_sections`（全部 spec 含两叙述节且叙述量达标）、`test_narrative_interpolates_seed_data`（电商月报摘要插值订单数与销售额）、`test_employee_roster_contains_narrative`（名册摘要随参数口径插值 9 人/3 人）；夹具 REQUIRED_TABLES 已扩至全部 8 组工作区，幂等测试期望模板数 7 → 8。
- 负责人名录的 `是否PI` 列为布尔值（CSV 导入推断），渲染改为 `{{ '是' if r['是否PI'] else '否' }}`，避免输出 `True/False`。
- 已知边界：xlsx 渲染器为数据导向、不输出模板文本，电商销售月报的叙述仅存在于模板内容与预览，不落入 xlsx 文件（既有行为不变）。

## 模板参数 options（前后端契约）

- 后端 `ParameterDef.options: list[str]`（默认空列表），随 TemplateCreate/Update 持久化到 `reports_template.parameters` JSON。
- 渲染端点（`POST /api/v1/reports/{id}/render`）：对声明了 options 的参数，若请求 params 携带该参数且取值不在 `options`（放行 None/空串），返回 400 + "参数 X 取值无效，可选值：a/b/c"。
- 前端 `ReportParameter.options?: string[]`：
  - 渲染参数弹窗（RenderParamsModal）：`options` 非空渲染 antd Select 下拉（`virtual={false}`），否则按 type 渲染 Input。
  - 模板编辑器参数区：新增「选项(逗号分隔)」输入（中英文逗号均支持），提交时转换为 `options` 数组；编辑回显时 `options` 数组转为逗号分隔文本。

## 异常与兼容

- 字体注册全失败时回退 Helvetica 并 warning（旧行为，中文仍可能乱码但不崩溃）。
- HTML 转义：所有渲染文本先 `_html_escape` 再加标签，`<script>` 等内容不生效。
- `_generate_sample_reports` 渲染失败仅告警不中断 seed（既有约定不变）。
- seed 生成的示例报告产物（`examples/datasets/**/*-示例报告.*`）已加入 .gitignore，不入库，每次 seed 覆盖重写。
- API schema 无变化（output_format 为 string 枚举校验在服务端），前端仅新增格式选项。
- 员工表字段/行数扩展同步影响 `test_backup_seed_roundtrip.py`（字段集/16 行还原断言）与 `test_seed_report_examples.py`（名册 12 行期望值）。
- 参数 options 校验仅约束"携带了该参数"的请求，`params={}` 兼容既有语义；五、离职人员名单保持全量口径不受参数影响。
