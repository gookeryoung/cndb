/**
 * 文档协作者弹窗测试 —— 把草稿开放给指定同事（viewer 只读 / editor 可直编未发布内容）。
 *
 * 覆盖：名单展示（用户名 + 角色）/ 添加（viewer、editor）/ 移除 / 无可管理权限时只读。
 * 说明：multipart 与 antd Select 交互按仓库既有做法（mouseDown + findByTitle）处理。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import DocumentCollaboratorsModal from './DocumentCollaboratorsModal'
import { renderProviders } from '@/test/render-providers'
import { documentsApi } from '@/api/documents'
import { workspaceApi } from '@/api/workspaces'

const WID = 10
const DOC_ID = 2

function setup(props: Partial<React.ComponentProps<typeof DocumentCollaboratorsModal>> = {}) {
    return renderProviders(
        <DocumentCollaboratorsModal
            open
            onClose={() => {}}
            workspaceId={WID}
            documentId={DOC_ID}
            canManage
            createdById={1}
            currentUserId={1}
            {...props}
        />,
    )
}

beforeEach(() => {
    vi.spyOn(documentsApi, 'listPermissions').mockResolvedValue([
        { document_id: DOC_ID, user_id: 7, role: 'viewer', username: 'bob', nickname: '小明' },
    ])
    vi.spyOn(workspaceApi, 'members').mockResolvedValue([
        { id: 1, workspace_id: WID, user_id: 1, role: 'owner', user: { id: 1, username: 'owner', nickname: '所有者' } },
        { id: 2, workspace_id: WID, user_id: 9, role: 'viewer', user: { id: 9, username: 'carol', nickname: '小卡' } },
    ] as never)
})

describe('文档协作者弹窗', () => {
    it('展示已有协作者及其角色', async () => {
        setup()
        // 「只读」在角色下拉里也会出现，故限定在协作者条目内断言
        const item = await screen.findByTestId('doc-collaborator-7')
        expect(within(item).getByText('小明')).toBeInTheDocument()
        expect(within(item).getByText('只读')).toBeInTheDocument()
    })

    it('添加 viewer 协作者：调用授予接口', async () => {
        const grantSpy = vi
            .spyOn(documentsApi, 'grantPermission')
            .mockResolvedValue({ document_id: DOC_ID, user_id: 9, role: 'viewer' })
        setup()

        // 等成员列表就绪后选择成员（排除创建者与自己）
        const select = await screen.findByTestId('doc-collaborator-select')
        fireEvent.mouseDown(select.querySelector('.ant-select-selector') ?? select)
        fireEvent.click(await screen.findByTitle('小卡'))
        fireEvent.click(screen.getByRole('button', { name: /添\s*加/ }))

        await waitFor(() => expect(grantSpy).toHaveBeenCalledWith(WID, DOC_ID, { user_id: 9, role: 'viewer' }))
    })

    it('切换为可编辑后添加：角色随选择变化', async () => {
        const grantSpy = vi
            .spyOn(documentsApi, 'grantPermission')
            .mockResolvedValue({ document_id: DOC_ID, user_id: 9, role: 'editor' })
        setup()

        // 角色下拉：切到「可编辑」
        const roleSelects = screen.getAllByRole('combobox')
        fireEvent.mouseDown(roleSelects[roleSelects.length - 1])
        fireEvent.click(await screen.findByTitle('可编辑'))

        const select = await screen.findByTestId('doc-collaborator-select')
        fireEvent.mouseDown(select.querySelector('.ant-select-selector') ?? select)
        fireEvent.click(await screen.findByTitle('小卡'))
        fireEvent.click(screen.getByRole('button', { name: /添\s*加/ }))

        await waitFor(() => expect(grantSpy).toHaveBeenCalledWith(WID, DOC_ID, { user_id: 9, role: 'editor' }))
    })

    it('移除协作者：调用撤销接口', async () => {
        const revokeSpy = vi.spyOn(documentsApi, 'revokePermission').mockResolvedValue(undefined as never)
        setup()

        fireEvent.click(await screen.findByTestId('doc-collaborator-revoke-7'))
        await waitFor(() => expect(revokeSpy).toHaveBeenCalledWith(WID, DOC_ID, 7))
    })

    it('无管理权限时只读：不显示添加表单与移除按钮', async () => {
        setup({ canManage: false })
        expect(await screen.findByText('小明')).toBeInTheDocument()
        expect(screen.queryByTestId('doc-collaborator-select')).toBeNull()
        expect(screen.queryByTestId('doc-collaborator-revoke-7')).toBeNull()
    })
})
