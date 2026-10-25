/** 帮助文档页（ADR 0029 P0 / ADR 0035）：独立路由 + 两级侧栏 + 页内三级目录。
 *
 * - `/help` 与未知主题都会被纠正到首个主题（replace，不污染历史）。
 * - 桌面常驻两级侧栏；窄屏收进左侧抽屉，选中主题后自动关闭。
 * - 正文按 L3 小节 / L4 条目渲染，右侧「本页目录」直接由同一份 `subsections`
 *   生成，点小节或条目会滚动并写入 `#锚点`，因此任意一条文档都可分享。
 */

import { MenuOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Drawer, Menu, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useResponsive } from '@/hooks/useResponsive'
import { useOnboardingStore } from '@/store/onboarding'
import HelpDoc from './content/HelpDoc'
import { HELP_DOCS_TITLE, HELP_SECTIONS, findTopic, itemAnchor, subsectionAnchor, topicPath } from './helpNav'

const { Text } = Typography

/** 锚点滚动：带 hash 进入时直接定位，点击目录时平滑滚动并写回地址栏。 */
function scrollToAnchor(anchor: string, smooth: boolean) {
    const element = document.getElementById(anchor)
    // jsdom 等环境没有实现 scrollIntoView：定位失败不影响阅读与地址栏
    if (!element || typeof element.scrollIntoView !== 'function') return false
    element.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' })
    return true
}

export default function HelpDocsPage() {
    const { isMobile } = useResponsive()
    const navigate = useNavigate()
    const location = useLocation()
    const { sectionKey, topicKey } = useParams<{ sectionKey: string; topicKey: string }>()
    const requestTour = useOnboardingStore((s) => s.requestTour)
    const [navOpen, setNavOpen] = useState(false)
    const [openKeys, setOpenKeys] = useState<string[]>(() => HELP_SECTIONS.map((item) => item.key))
    const [activeAnchor, setActiveAnchor] = useState<string>('')

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

    // 换主题时重置页内选中态，并按 hash 定位（`#help-<小节>` / `#help-<小节>--<条目>`）。
    useEffect(() => {
        const hash = location.hash.replace(/^#/, '')
        setActiveAnchor(hash)
        if (!hash) return
        // 内容渲染完成后再定位：主题切换后 DOM 才存在。
        const timer = window.setTimeout(() => scrollToAnchor(hash, false), 0)
        return () => window.clearTimeout(timer)
    }, [canonical, location.hash])

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

    const goAnchor = (anchor: string) => {
        setActiveAnchor(anchor)
        scrollToAnchor(anchor, true)
        navigate({ pathname: canonical, hash: `#${anchor}` }, { replace: true })
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

    const toc = (
        <nav className="cn-help-docs-toc" aria-label="本页目录" data-testid="help-docs-toc">
            <div className="cn-help-docs-toc-title">本页目录</div>
            <ol className="cn-help-docs-toc-list">
                {topic.subsections.map((subsection) => {
                    const anchor = subsectionAnchor(subsection.key)
                    return (
                        <li key={subsection.key}>
                            <button
                                type="button"
                                className={`cn-help-docs-toc-link${activeAnchor === anchor ? ' is-active' : ''}`}
                                onClick={() => goAnchor(anchor)}
                                data-testid={`help-toc-${subsection.key}`}
                            >
                                {subsection.label}
                            </button>
                            {(subsection.items ?? []).length > 1 && (
                                <ol className="cn-help-docs-toc-list cn-help-docs-toc-sub">
                                    {(subsection.items ?? []).map((item) => {
                                        const itemHref = itemAnchor(subsection.key, item.key)
                                        return (
                                            <li key={item.key}>
                                                <button
                                                    type="button"
                                                    className={`cn-help-docs-toc-link${activeAnchor === itemHref ? ' is-active' : ''}`}
                                                    onClick={() => goAnchor(itemHref)}
                                                >
                                                    {item.label}
                                                </button>
                                            </li>
                                        )
                                    })}
                                </ol>
                            )}
                        </li>
                    )
                })}
            </ol>
        </nav>
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

                <div className="cn-help-docs-content">
                    <article className="cn-help-docs-body">
                        <h1 className="cn-help-docs-heading">{topic.label}</h1>
                        <HelpDoc topic={topic} />
                    </article>
                    {!isMobile && toc}
                </div>
            </main>
        </div>
    )
}
