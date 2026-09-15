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
      { title: '引用字段值', code: '{{ name }}', description: 'records 中的字段名，渲染该行的字段值' },
      { title: '遍历行访问', code: '{{ row.name }}', description: 'for row in records 循环内访问字段' },
      { title: '表名变量', code: '{{ table_name }}', description: '当前模板关联的表名' },
      { title: '用户参数', code: '{{ params.start_date }}', description: '运行时传入的用户参数字典' },
      { title: '默认值过滤器', code: '{{ name | default("未填写") }}', description: '字段为空时显示默认值' },
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
      { title: '转大写', code: '{{ name | upper }}' },
      { title: '转小写', code: '{{ name | lower }}' },
      { title: '取长度', code: '{{ records | length }}', description: '行数或列表长度' },
      { title: '字符串截断', code: '{{ content | truncate(50) }}' },
      { title: '列表拼接', code: '{{ tags | join(", ") }}' },
      { title: '数值格式化', code: '{{ amount | round(2) }}' },
      { title: '日期格式化', code: '{{ row.date | date("%Y-%m-%d") }}', description: '后端 Jinja2 需 date 过滤器可用' },
    ],
  },
  {
    key: 'builtins',
    label: '内置变量',
    examples: [
      { title: '全部行数据', code: 'records', description: 'list[dict]，模板最核心的数据源' },
      { title: '表名', code: 'table_name', description: 'str，模板关联的数据表名称' },
      { title: '用户参数', code: 'params', description: 'dict，运行时用户输入的动态参数' },
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
        点击代码块右侧「插入」即可填入编辑器
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
