/** 典型示例（ADR 0029 P1 / ADR 0036 / 需求 0106）—— 五个 L3 小节渲染、创建示例工作区、CSV 下载、失败重试与缺省场景. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import {
    ExampleCreateWorkspace,
    ExamplePractice,
    ExamplePreviews,
    ExampleSummary,
    ExampleTables,
} from './ExamplesSection'

afterEach(() => {
    vi.restoreAllMocks()
})

/** 五个小节在真实页面里由 `HelpDoc` 拆开渲染，这里拼回同一页便于断言。 */
function Scenario({ scenarioKey }: { scenarioKey: string }) {
    return (
        <div>
            <ExampleSummary scenarioKey={scenarioKey} />
            <ExampleCreateWorkspace scenarioKey={scenarioKey} />
            <ExampleTables scenarioKey={scenarioKey} />
            <ExamplePreviews scenarioKey={scenarioKey} />
            <ExamplePractice scenarioKey={scenarioKey} />
        </div>
    )
}

describe('ExamplesSection', () => {
    it('按清单渲染场景说明、数据表、亮点与导入步骤', async () => {
        renderProviders(<Scenario scenarioKey="sales" />)

        expect(await screen.findByTestId('help-examples-section')).toBeVisible()
        expect(screen.getByText('从销售明细、客户流失到营销活动与日常待办的完整销售运营示例。')).toBeVisible()
        expect(screen.getByText('电商销售')).toBeVisible()
        expect(screen.getByText('电商销售.csv')).toBeVisible()
        expect(screen.getByText('图表视图看月度销售额')).toBeVisible()
        expect(screen.getByText('1. 下载 CSV')).toBeVisible()
        expect(screen.getByTestId('help-example-download-电商销售.csv')).toBeVisible()
    })

    it('点击「下载 CSV」走鉴权 blob 并触发浏览器下载', async () => {
        const createObjectURL = vi.fn(() => 'blob:mock-csv')
        Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })

        renderProviders(<Scenario scenarioKey="research" />)

        fireEvent.click(await screen.findByTestId('help-example-download-科研项目.csv'))
        await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
    })

    it('清单加载失败显示错误与重试，重试后恢复', async () => {
        server.use(
            http.get('/api/v1/help/examples', () =>
                HttpResponse.json({ detail: '示例清单暂不可用' }, { status: 500 }), { once: true }),
        )

        renderProviders(<Scenario scenarioKey="sales" />)

        expect(await screen.findByTestId('help-examples-error')).toBeVisible()
        expect(screen.getByText('示例清单暂不可用')).toBeVisible()

        fireEvent.click(screen.getByRole('button', { name: /重试/ }))
        expect(await screen.findByTestId('help-examples-section')).toBeVisible()
    })

    it('点击「创建示例工作区」调用接口并提示成功', async () => {
        renderProviders(<Scenario scenarioKey="sales" />)

        fireEvent.click(await screen.findByTestId('help-example-create-sales'))

        expect(await screen.findByText(/已创建示例工作区/)).toBeInTheDocument()
    })

    it('创建失败时提示错误而不是跳转', async () => {
        server.use(
            http.post('/api/v1/help/examples/:scenario/workspace', () =>
                HttpResponse.json({ detail: '示例工作区包暂不可用' }, { status: 404 }), { once: true }),
        )

        renderProviders(<Scenario scenarioKey="research" />)

        fireEvent.click(await screen.findByTestId('help-example-create-research'))

        expect(await screen.findByText('示例工作区包暂不可用')).toBeInTheDocument()
    })

    it('场景不在清单中时给出提示而不是空白', async () => {
        renderProviders(<ExampleSummary scenarioKey="nope" />)

        expect(await screen.findByTestId('help-examples-missing')).toBeVisible()
    })
})
