import { Collapse, Typography } from 'antd'

export interface SyntaxExample {
  /** 标题（简短说明） */
  title: string
  /** 示例代码（可直接插入编辑器） */
  code: string
  /** 注释说明 */
  description?: string
}

export interface SyntaxSection {
  key: string
  label: string
  examples: SyntaxExample[]
}

/** Jinja2 常用语法示例 — 与后端 SandboxedEnvironment 保持一致 */
export const SYNTAX_SECTIONS: SyntaxSection[] = [
  {
    key: 'variables',
    label: '变量引用',
    examples: [
      { title: '引用字段值', code: '{{ records[0].name }}', description: '主表首行的字段值；循环内请用 row.name' },
      { title: '遍历行访问', code: '{{ row.name }}', description: 'for row in records 循环内访问字段' },
      { title: '表名变量', code: '{{ table_name }}', description: '当前模板关联的表名' },
      { title: '用户参数', code: '{{ params.start_date }}', description: '运行时传入的用户参数字典' },
      { title: '生成日期', code: '{{ generated_at }}', description: '报告生成时间（YYYY-MM-DD HH:mm），每次渲染自动更新' },
      { title: '默认值过滤器', code: '{{ records[0].name | default("未填写") }}', description: '字段为空时显示默认值' },
    ],
  },
  {
    key: 'control',
    label: '控制结构',
    examples: [
      {
        title: '遍历全部行',
        code: '{% for row in records %}\n{{ row.name }}: {{ row.value }}\n{% endfor %}',
        description: '最常用结构，遍历数据源所有行',
      },
      {
        title: '条件判断',
        code: '{% if row.amount > 1000 %}\n大额订单\n{% else %}\n普通订单\n{% endif %}',
        description: '根据字段值输出不同内容',
      },
      {
        title: '循环计数',
        code: '{% for row in records %}\n{{ loop.index }}. {{ row.name }}\n{% endfor %}',
        description: 'loop.index 从 1 开始，loop.length 总行数',
      },
      {
        title: '空记录处理',
        code: '{% for row in records %}\n{{ row.name }}\n{% else %}\n暂无数据\n{% endfor %}',
        description: 'records 为空时输出 else 分支',
      },
    ],
  },
  {
    key: 'filters',
    label: '常用过滤器',
    examples: [
      { title: '转大写', code: '{{ records[0].name | upper }}' },
      { title: '转小写', code: '{{ records[0].name | lower }}' },
      { title: '取长度', code: '{{ records | length }}', description: '行数或列表长度' },
      { title: '字符串截断', code: '{{ records[0].content | truncate(50) }}' },
      { title: '列表拼接', code: '{{ records[0].tags | join(", ") }}' },
      { title: '数值格式化', code: '{{ records[0].amount | round(2) }}' },
      { title: '日期格式化', code: '{{ records[0].date | date("%Y-%m-%d") }}', description: '后端 Jinja2 需 date 过滤器可用' },
    ],
  },
  {
    key: 'functions',
    label: '统计函数',
    examples: [
      { title: '单列统计', code: "{{ stats(records, '金额').sum }}", description: '返回 {count, sum, avg, min, max, non_empty}，用 .sum/.avg 访问' },
      { title: '计数', code: "{{ stats(records, '金额').count }}", description: '该字段有值的行数' },
      { title: '分组统计', code: "{% for g in group_stats(records, '类别', '金额') %}\n{{ g.key }}: {{ g.sum }}\n{% endfor %}", description: '按类别分组对金额做聚合，g 含 {key, count, sum, avg, min, max}' },
      { title: '跨表统计', code: "{{ stats(records_by_table['经费表'], '预算').sum }}", description: '对额外引用表数据做统计' },
    ],
  },
  {
    key: 'multitable',
    label: '跨表引用',
    examples: [
      { title: '访问额外表数据', code: "{{ records_by_table['员工表'] }}", description: '渲染时额外传入的表数据，dict 结构，key 为表名' },
      { title: '遍历额外表', code: "{% for r in records_by_table['员工表'] %}\n{{ r.name }}\n{% endfor %}", description: '遍历 extra 表中的全部记录' },
      { title: '取额外表行数', code: "{{ records_by_table['员工表'] | length }}", description: '统计额外表的记录总数' },
      { title: '主表 + 额外表联合', code: "{{ records | length }} + {{ records_by_table['员工表'] | length }} 行", description: '同时使用主表和额外表' },
    ],
  },
  {
    key: 'markdown',
    label: 'Markdown 输出标记',
    examples: [
      { title: '一级标题', code: '# 月度报告', description: 'DOCX → Heading 1，PDF → 大标题' },
      { title: '二级标题', code: '## 销售明细', description: 'DOCX → Heading 2，PDF → 中标题' },
      { title: '加粗文本', code: '**重要数据**', description: '输出为粗体（DOCX/PDF）' },
      { title: '代码样式', code: '`code here`', description: '输出为等宽代码字体（DOCX）' },
      { title: '表格（Markdown 风格）', code: '| 姓名 | 金额 |\n| --- | --- |\n| 张三 | 1000 |', description: 'DOCX/PDF 自动解析为表格对象' },
      { title: '换页标记', code: '---PAGE---', description: 'PDF/DOCX 强制分页' },
    ],
  },
  {
    key: 'builtins',
    label: '内置变量',
    examples: [
      { title: '全部行数据', code: 'records', description: 'list[dict]，模板最核心的数据源' },
      { title: '表名', code: 'table_name', description: 'str，模板关联的数据表名称' },
      { title: '用户参数', code: 'params', description: 'dict，运行时用户输入的动态参数' },
      { title: '额外表数据', code: 'records_by_table', description: 'dict[str, list[dict]]，跨表引用容器' },
      { title: '生成日期', code: 'generated_at', description: 'str，报告生成时间（YYYY-MM-DD HH:mm）' },
    ],
  },
]

export interface SyntaxHelpPanelProps {
  onInsert: (code: string) => void
}

export default function SyntaxHelpPanel({ onInsert }: SyntaxHelpPanelProps) {
  return (
    <div className="report-syntax-panel">
      <Typography.Title level={5} style={{ margin: '0 0 8px 0' }}>
        Jinja2 语法帮助
      </Typography.Title>
      <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
        点击代码块右侧「插入」即可填入编辑器。注意：预览与后端均使用 Jinja2 兼容语法，个别后端独有写法（如 for 循环内 if 过滤）以 Word/PDF 实际输出为准。
      </Typography.Text>

      <Collapse
        defaultActiveKey={['variables', 'control']}
        size="small"
        ghost
        items={SYNTAX_SECTIONS.map(section => ({
          key: section.key,
          label: <span style={{ fontWeight: 500 }}>{section.label}</span>,
          children: (
            <div className="report-syntax-section">
              {section.examples.map((ex, idx) => (
                <div key={idx} className="report-syntax-example">
                  <div className="report-syntax-example-title">{ex.title}</div>
                  <div className="report-syntax-example-code">
                    <pre><code>{ex.code}</code></pre>
                    <button
                      type="button"
                      className="report-syntax-insert-btn"
                      onClick={() => onInsert(ex.code)}
                    >
                      插入
                    </button>
                  </div>
                  {ex.description && (
                    <div className="report-syntax-example-desc">{ex.description}</div>
                  )}
                </div>
              ))}
            </div>
          ),
        }))}
      />
    </div>
  )
}
