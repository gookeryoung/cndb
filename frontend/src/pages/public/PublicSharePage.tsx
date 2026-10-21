/** 公开分享访问页（免登录只读）——ADR 0017.
 *
 * 独立于工作区与登录态：不挂 ProtectedRoute、不请求任何工作区鉴权接口，
 * 只凭 URL 里的 token 读取单篇已发布文档。三态：加载 / 需要密码 / 不存在或已失效。
 */

import { useMemo, useState } from 'react'
import { Alert, Button, Input, Result, Space, Spin, Typography } from 'antd'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import MarkdownPreview from '@/components/Document/MarkdownPreview'
import publicShareApi, { type PublicShareDocument } from '@/api/publicShare'

/** axios 错误 → HTTP 状态码（公开页据此区分「已失效」与「加载失败」） */
function statusOf(err: unknown): number | undefined {
  return (err as { response?: { status?: number } })?.response?.status
}

function formatUpdatedAt(value?: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString()
}

export default function PublicSharePage() {
  const { token = '' } = useParams<{ token: string }>()
  const [unlocked, setUnlocked] = useState<PublicShareDocument | null>(null)
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)

  const metaQuery = useQuery({
    queryKey: ['public-share-meta', token],
    queryFn: () => publicShareApi.meta(token),
    enabled: Boolean(token),
    retry: false,
  })

  const needsPassword = metaQuery.data?.has_password === true

  const contentQuery = useQuery({
    queryKey: ['public-share-content', token],
    queryFn: () => publicShareApi.content(token),
    enabled: Boolean(token) && metaQuery.isSuccess && !needsPassword,
    retry: false,
  })

  const unlockMutation = useMutation({
    mutationFn: (pwd: string) => publicShareApi.contentWithPassword(token, pwd),
    onSuccess: data => {
      setUnlocked(data)
      setPasswordError(null)
    },
    onError: (err: unknown) => {
      setPasswordError(
        statusOf(err) === 403 ? '密码错误，请重新输入' : '访问失败，请稍后重试',
      )
    },
  })

  const doc = unlocked ?? contentQuery.data ?? null
  const updatedAt = useMemo(() => formatUpdatedAt(doc?.updated_at), [doc?.updated_at])

  if (!token) {
    return <Result status="404" title="链接不存在或已失效" subTitle="请向分享者确认链接是否仍然有效。" />
  }

  if (metaQuery.isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 96 }} data-testid="public-share-loading">
        <Spin size="large" />
      </div>
    )
  }

  if (metaQuery.isError) {
    if (statusOf(metaQuery.error) === 404) {
      return (
        <div data-testid="public-share-gone">
          <Result
            status="404"
            title="链接不存在或已失效"
            subTitle="请向分享者确认链接是否仍然有效。"
          />
        </div>
      )
    }
    return <Result status="warning" title="分享加载失败" subTitle="请稍后重试。" />
  }

  const title = doc?.title ?? metaQuery.data?.title ?? ''
  const passwordPanel = needsPassword && !doc

  let body: React.ReactNode
  if (passwordPanel) {
    body = (
      <Space direction="vertical" size={12} style={{ maxWidth: 320 }}>
        <Typography.Text type="secondary">该分享需要密码访问</Typography.Text>
        <Input.Password
          value={password}
          placeholder="请输入访问密码"
          data-testid="public-share-password"
          onChange={e => {
            setPassword(e.target.value)
            setPasswordError(null)
          }}
          onPressEnter={() => password && unlockMutation.mutate(password)}
        />
        {passwordError && <Alert type="error" showIcon message={passwordError} data-testid="public-share-password-error" />}
        <Button
          type="primary"
          loading={unlockMutation.isPending}
          disabled={!password}
          data-testid="public-share-unlock"
          onClick={() => unlockMutation.mutate(password)}
        >
          查看文档
        </Button>
      </Space>
    )
  } else if (contentQuery.isError && !unlocked) {
    body =
      statusOf(contentQuery.error) === 404 ? (
        <Result status="404" title="链接不存在或已失效" subTitle="请向分享者确认链接是否仍然有效。" />
      ) : (
        <Result status="warning" title="分享加载失败" subTitle="请稍后重试。" />
      )
  } else if (!doc) {
    body = (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }} data-testid="public-share-content-loading">
        <Spin />
      </div>
    )
  } else {
    body = (
      <article data-testid="public-share-content">
        <MarkdownPreview content={doc.content ?? ''} publicFileBase={publicShareApi.fileUrl(token)} />
      </article>
    )
  }

  return (
    <main
      data-testid="public-share-page"
      style={{
        minHeight: '100vh',
        background: 'var(--cn-bg-layout, #f5f6f8)',
        padding: '40px 16px 64px',
      }}
    >
      <div
        style={{
          maxWidth: 880,
          margin: '0 auto',
          background: 'var(--cn-bg-container, #fff)',
          border: '1px solid var(--cn-border, #e8e8e8)',
          borderRadius: 10,
          padding: '32px 40px 48px',
        }}
      >
        <header style={{ marginBottom: 24, borderBottom: '1px solid var(--cn-border, #e8e8e8)', paddingBottom: 16 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          <Space size={8} style={{ marginTop: 6 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              只读分享
            </Typography.Text>
            {updatedAt && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                更新于 {updatedAt}
              </Typography.Text>
            )}
          </Space>
        </header>
        {body}
      </div>
    </main>
  )
}
