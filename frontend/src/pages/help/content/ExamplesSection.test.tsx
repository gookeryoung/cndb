/** 典型示例区（ADR 0029 P1）—— 清单渲染、CSV 下载、失败重试与缺省场景. */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import ExamplesSection from './ExamplesSection'

afterEach(() => {
    vi.restoreAllMocks()
})

describe('ExamplesSection', () => {
    it('按清单渲染场景说明、数据表、亮点与导入步骤', async () => {
        renderProviders(<ExamplesSection scenarioKey="sales" />)

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

        renderProviders(<ExamplesSection scenarioKey="research" />)

        fireEvent.click(await screen.findByTestId('help-example-download-科研项目.csv'))
        await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1))
    })

    it('清单加载失败显示错误与重试，重试后恢复', async () => {
        server.use(
            http.get('/api/v1/help/examples', () =>
                HttpResponse.json({ detail: '示例清单暂不可用' }, { status: 500 }), { once: true }),
        )

        renderProviders(<ExamplesSection scenarioKey="sales" />)

        expect(await screen.findByTestId('help-examples-error')).toBeVisible()
        expect(screen.getByText('示例清单暂不可用')).toBeVisible()

        fireEvent.click(screen.getByRole('button', { name: /重试/ }))
        expect(await screen.findByTestId('help-examples-section')).toBeVisible()
    })

    it('场景不在清单中时给出提示而不是空白', async () => {
        renderProviders(<ExamplesSection scenarioKey="nope" />)

        expect(await screen.findByTestId('help-examples-missing')).toBeVisible()
    })
})
