/**
 * ThemeProvider 的 Chromium 81 样式降级（ADR 0026 P0 + ADR 0074 P1）。
 *
 * antd 默认用 :where() 包裹选择器，并把 paddingInline / inset 等逻辑属性写进运行时样式；
 * Chrome 81 前者整条丢弃、后者直接忽略。这里断言 StyleProvider 的降级真实生效。
 *
 * ADR 0074 D4：antd 6 部分组件样式使用 :has() / @container（Chrome 105+，无法 polyfill），
 * 按「规则级降级」白名单放行；其余现代 CSS 特性（oklch / @layer / light-dark 等）一经
 * 注入即判失败——静态扫描看不到 CSS-in-JS 产物，本测试渲染代表性组件样本、审计
 * 实际注入的运行时 CSS，是 Chrome 81 真机冒烟之外最接近产出的门禁。
 */

import { render, screen } from '@testing-library/react'
import { Button, DatePicker, Form, Input, Modal, Select, Space, Table, Tabs } from 'antd'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider } from './ThemeProvider'

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.removeAttribute('style')
  document.documentElement.removeAttribute('style')
})

function injectedCss(): string {
  return Array.from(document.querySelectorAll('style'))
    .map((node) => node.textContent ?? '')
    .join('\n')
}

function renderAntdSample() {
  render(
    <ThemeProvider>
      <Space>
        <Button type="primary">兼容按钮</Button>
      </Space>
    </ThemeProvider>,
  )
  expect(screen.getByText('兼容按钮')).toBeInTheDocument()
}

/** 覆盖 :has() 高发组件（form/tabs/input/select/card/pagination/date-picker/tooltip 等）的代表样本 */
function renderAntdFullSample() {
  render(
    <ThemeProvider>
      <Form>
        <Form.Item label="名称" name="name">
          <Input placeholder="p" />
        </Form.Item>
        <Form.Item label="类型" name="type">
          <Select options={[{ value: 1, label: '一' }]} />
        </Form.Item>
        <Form.Item>
          <DatePicker />
        </Form.Item>
      </Form>
      <Tabs
        items={[{ key: 'a', label: 'A', children: <div>内容</div> }]}
      />
      <Table
        columns={[{ title: '列', dataIndex: 'c' }]}
        dataSource={[{ key: 1, c: 1 }]}
        pagination={{ pageSize: 1 }}
      />
      <Modal open title="m" cancelText="关闭">
        <div>弹层内容</div>
      </Modal>
      <Button>另一个按钮</Button>
    </ThemeProvider>,
  )
  expect(screen.getByText('弹层内容')).toBeInTheDocument()
}

describe('ThemeProvider 的 Chromium 81 样式降级', () => {
  it('antd 注入的样式不含 :where()', () => {
    renderAntdSample()
    expect(injectedCss()).not.toContain(':where(')
  })

  it('逻辑属性被转换为物理属性', () => {
    renderAntdSample()
    const css = injectedCss()
    expect(css).toContain('padding-left')
    // cssVar 模式下存在 --ant-*-padding-inline 等变量名，只断言「逻辑属性声明」而非子串
    expect(css).not.toMatch(/(^|[^-\w])padding-inline\s*:/)
    expect(css).not.toMatch(/(^|[^-\w])margin-inline\s*:/)
  })

  it('旧内核首帧前写入 --cn-mix-* 兜底变量', () => {
    vi.stubGlobal('CSS', { supports: () => false })
    document.body.style.setProperty('--cn-brand-color', '#1677ff')
    document.body.style.setProperty('--cn-bg-container', '#ffffff')

    renderAntdSample()

    expect(document.documentElement.style.getPropertyValue('--cn-mix-brand-color-12-bg-container'))
      .toBe('rgb(227, 239, 255)')
  })

  it('运行时注入样式的现代 CSS 特性不超出 ADR 0074 D4 白名单', () => {
    renderAntdFullSample()
    const css = injectedCss()
    // 白名单（允许降级，Chrome 81 上单条规则丢弃）：:has()（antd 6 十余个组件的
    // 校验/联动增强样式）、@container（Steps 渐进增强）。二者无法 polyfill，
    // 视觉影响由 Chromium 81 真机冒烟逐项核对（chrome81-smoke.mjs）。
    // 白名单之外一旦出现即判失败：强制评估新增特性的降级影响后再登记。
    const forbidden = [
      'oklch(', 'oklab(', 'lab(', 'lch(', 'light-dark(', '@layer',
      'rgb(from', 'hsl(from', 'hwb(from', 'color(from', 'dvh', 'svh', 'lvh',
      'text-wrap: balance', ':is(', ':where(', 'inset:', 'color-mix(',
    ]
    for (const token of forbidden) {
      expect(css).not.toContain(token)
    }
  })
})
