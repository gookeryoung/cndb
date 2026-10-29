import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * `?create=1` URL 触发新建弹窗（需求 0067 C3）——命令面板的「新建」命令
 * 经 URL 打开对应页面并触发与页内新建按钮相同的弹窗。
 *
 * 幂等：命中后立即移除该参数（replace，不留历史记录），刷新 / 回退不会重复弹出；
 * 页面已挂载时再次导航带参（如重复执行命令）也会重新触发（依赖 searchParams 变化）。
 */
export function useCreateParam(onCreate: () => void) {
  const [searchParams, setSearchParams] = useSearchParams()
  // 回调经 ref 转发：避免 onCreate 身份变化引发 effect 重跑
  const onCreateRef = useRef(onCreate)
  onCreateRef.current = onCreate

  useEffect(() => {
    if (searchParams.get('create') !== '1') return
    onCreateRef.current()
    const next = new URLSearchParams(searchParams)
    next.delete('create')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])
}
