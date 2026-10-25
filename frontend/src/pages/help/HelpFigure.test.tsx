/** 帮助图示组件（ADR 0030）—— 清单驱动、指纹缓存、内联渲染与失败降级. */

import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import HelpFigure from './HelpFigure'

describe('HelpFigure', () => {
    it('按指纹拉取 SVG 并内联渲染，同时显示图注与更新时间', async () => {
        renderProviders(<HelpFigure id="field-types" />)

        const canvas = await screen.findByTestId('help-figure-canvas-field-types')
        expect(canvas.querySelector('svg')).not.toBeNull()
        expect(screen.getByText('图示说明 field-types')).toBeVisible()
        expect(screen.getByText(/图示更新于/)).toBeVisible()
    })

    it('正文传入的 caption 覆盖后端登记的图注', async () => {
        renderProviders(<HelpFigure id="quick-start-flow" caption="自定义图注" />)

        expect(await screen.findByText('自定义图注')).toBeVisible()
        expect(screen.queryByText('图示说明 quick-start-flow')).toBeNull()
    })

    it('清洗 SVG 里的 script 与行内事件属性', async () => {
        server.use(
            http.get('/api/v1/help/figures/:key', () =>
                new HttpResponse(
                    '<svg xmlns="http://www.w3.org/2000/svg" data-help-figure="1" onload="alert(1)">' +
                        '<script>alert(1)</script><text>安全图示</text></svg>',
                    { status: 200, headers: { 'Content-Type': 'image/svg+xml; charset=utf-8' } },
                )),
        )

        renderProviders(<HelpFigure id="field-types" />)

        const canvas = await screen.findByTestId('help-figure-canvas-field-types')
        expect(canvas.innerHTML).toContain('安全图示')
        expect(canvas.innerHTML).not.toContain('<script')
        expect(canvas.innerHTML).not.toContain('onload')
    })

    it('SVG 拉取失败时降级为提示，不影响其余正文', async () => {
        server.use(
            http.get('/api/v1/help/figures/:key', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
        )

        renderProviders(<HelpFigure id="permission-model" />)

        expect(await screen.findByTestId('help-figure-error-permission-model')).toBeVisible()
        expect(screen.getByText('图示暂不可用')).toBeVisible()
    })

    it('内容引用了未登记的图示时提示「图示未登记」', async () => {
        renderProviders(<HelpFigure id="not-registered" />)

        expect(await screen.findByTestId('help-figure-error-not-registered')).toBeVisible()
        expect(screen.getByText('图示未登记')).toBeVisible()
    })

    it('清单接口失败时同样降级，不留骨架屏', async () => {
        server.use(
            http.get('/api/v1/help/figures', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
        )

        renderProviders(<HelpFigure id="import-flow" />)

        await waitFor(() => expect(screen.getByTestId('help-figure-error-import-flow')).toBeVisible())
    })
})
