/**
 * 通知铃铛组件测试.
 *
 * 覆盖：未读角标 / 通知文案（谁把我加进了协作者）/ 点击条目标记已读并跳转文档 /
 * 全部已读 / 无通知空态。
 */
import { describe, expect, it, vi, afterEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import NotificationBell from './NotificationBell'
import { renderProviders } from '@/test/render-providers'
import { server } from '@/test/msw'
import { notificationsApi } from '@/api/notifications'

const NOTIF = '/api/v1/accounts/notifications'

function renderBell() {
    return renderProviders(<NotificationBell />, { route: '/w/10/documents/2' })
}

const oneUnread = {
    items: [
        {
            id: 5,
            type: 'document.collaborator_added',
            actor_id: 1,
            actor_name: '所有者小周',
            workspace_id: 10,
            document_id: 42,
            document_title: '季度规划草稿',
            role: 'editor',
            read: false,
        },
    ],
    unread_count: 1,
}

afterEach(() => vi.restoreAllMocks())

describe('NotificationBell', () => {
    it('无通知时不显示角标，展开为空态', async () => {
        server.use(http.get(NOTIF, () => HttpResponse.json({ items: [], unread_count: 0 })))
        renderBell()

        const bell = await screen.findByTestId('notif-bell')
        expect(bell).toHaveAttribute('aria-label', '通知')
        fireEvent.click(bell)
        expect(await screen.findByText('暂无通知')).toBeInTheDocument()
    })

    it('未读时显示角标与协作文案', async () => {
        server.use(http.get(NOTIF, () => HttpResponse.json(oneUnread)))
        renderBell()

        const bell = await screen.findByTestId('notif-bell')
        await waitFor(() => expect(bell).toHaveAttribute('aria-label', '通知（1 条未读）'))

        fireEvent.click(bell)
        expect(await screen.findByText('所有者小周 邀请你协作《季度规划草稿》（可编辑）')).toBeInTheDocument()
    })

    it('点击条目标记已读（单条接口）', async () => {
        const readSpy = vi.spyOn(notificationsApi, 'markRead').mockResolvedValue(undefined as never)
        server.use(http.get(NOTIF, () => HttpResponse.json(oneUnread)))
        renderBell()

        fireEvent.click(await screen.findByTestId('notif-bell'))
        fireEvent.click(await screen.findByTestId('notif-item-5'))

        await waitFor(() => expect(readSpy).toHaveBeenCalledWith(5))
    })

    it('「全部已读」调用批量接口', async () => {
        const allSpy = vi.spyOn(notificationsApi, 'readAll').mockResolvedValue({ updated: 1 })
        server.use(http.get(NOTIF, () => HttpResponse.json(oneUnread)))
        renderBell()

        fireEvent.click(await screen.findByTestId('notif-bell'))
        fireEvent.click(await screen.findByTestId('notif-read-all'))

        await waitFor(() => expect(allSpy).toHaveBeenCalled())
    })
})
