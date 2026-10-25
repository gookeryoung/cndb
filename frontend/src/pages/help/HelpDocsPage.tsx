/** 帮助文档页（ADR 0029 P0）：独立路由 + 两级侧边栏 + URL 驱动选中态。
 *
 * - `/help` 与未知主题都会被纠正到首个主题（replace，不污染历史）。
 * - 桌面常驻两级侧栏；窄屏收进左侧抽屉，选中主题后自动关闭。
 */

import { MenuOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Drawer, Menu, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useResponsive } from '@/hooks/useResponsive'
import { useOnboardingStore } from '@/store/onboarding'
import { HELP_DOCS_TITLE, HELP_SECTIONS, findTopic, topicPath } from './helpNav'

const { Text } = Typography

export default function HelpDocsPage() {
    const { isMobile } = useResponsive()
    const navigate = useNavigate()
    const location = useLocation()
    const { sectionKey, topicKey } = useParams<{ sectionKey: string; topicKey: string }>()
    const requestTour = useOnboardingStore((s) => s.requestTour)
    const [navOpen, setNavOpen] = useState(false)
    const [openKeys, setOpenKeys] = useState<string[]>(() => HELP_SECTIONS.map((item) => item.key))

    const { section, topic } = findTopic(sectionKey, topicKey)
    const canonical = topicPath(section.key, topic.key)

    // URL 与导航不一致（缺参数 / 未知 key / 多余段）时纠正到规范地址。
    useEffect(() => {
        if (location.pathname !== canonical) navigate(canonical, { replace: true })
    }, [location.pathname, canonical, navigate])

    // 深链到已收起的部分时展开它，确保当前主题可见。
    useEffect(() => {
        setOpenKeys((keys) => (keys.includes(section.key) ? keys : [...keys, section.key]))
    }, [section.key])

    const menuItems: MenuProps['items'] = HELP_SECTIONS.map((item) => ({
        key: item.key,
        icon: item.icon,
        label: item.label,
        children: item.topics.map((t) => ({ key: topicPath(item.key, t.key), label: t.label })),
    }))

    const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
        if (key.startsWith('/help/')) navigate(key)
        setNavOpen(false)
    }

    const menu = (
        <Menu
            mode="inline"
            items={menuItems}
            selectedKeys={[canonical]}
            openKeys={openKeys}
            onOpenChange={(keys) => setOpenKeys(keys as string[])}
            onClick={handleMenuClick}
            style={{ borderInlineEnd: 'none' }}
        />
    )

    return (
        <div className="cn-help-docs" data-testid="help-docs-page">
            {!isMobile && (
                <aside className="cn-help-docs-aside" data-testid="help-docs-aside">
                    <div className="cn-help-docs-brand">{HELP_DOCS_TITLE}</div>
                    {menu}
                </aside>
            )}

            {isMobile && (
                <Drawer
                    open={navOpen}
                    onClose={() => setNavOpen(false)}
                    placement="left"
                    width={280}
                    title={HELP_DOCS_TITLE}
                    styles={{ body: { padding: 0 } }}
                    data-testid="help-docs-nav-drawer"
                >
                    {menu}
                </Drawer>
            )}

            <main className="cn-help-docs-main">
                <div className="cn-help-docs-toolbar">
                    {isMobile && (
                        <Button icon={<MenuOutlined />} onClick={() => setNavOpen(true)} data-testid="help-docs-menu-btn">
                            目录
                        </Button>
                    )}
                    <Text type="secondary" className="cn-help-docs-breadcrumb">
                        {isMobile ? HELP_DOCS_TITLE : section.label}
                    </Text>
                    <Button
                        type="text"
                        size="small"
                        icon={<PlayCircleOutlined />}
                        onClick={() => requestTour()}
                        data-testid="help-docs-replay-tour"
                    >
                        重新播放新手引导
                    </Button>
                </div>

                <article className="cn-help-docs-body">
                    <h1 className="cn-help-docs-heading">{topic.label}</h1>
                    {topic.content}
                </article>
            </main>
        </div>
    )
}
