/** 登录页 —— 微信一键登录 + 账号密码登录. */
import { useState } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Input, Button } from '@tarojs/components'
import { useAuth } from '@/store/auth'
import './index.scss'

export default function LoginPage() {
  const { loginWithPassword, loginWithWechat, isLoading: restoring } = useAuth()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [tab, setTab] = useState<'wechat' | 'password'>('wechat')
  const [submitting, setSubmitting] = useState(false)

  async function handleWechat() {
    setSubmitting(true)
    try {
      await loginWithWechat()
      Taro.reLaunch({ url: '/pages/workspaces/index' })
    } catch (err) {
      Taro.showToast({
        title: err instanceof Error ? err.message : '微信登录失败',
        icon: 'none',
      })
    } finally {
      setSubmitting(false)
    }
  }

  async function handlePassword() {
    if (!login || !password) {
      Taro.showToast({ title: '请填写账号和密码', icon: 'none' })
      return
    }
    setSubmitting(true)
    try {
      await loginWithPassword(login, password)
      Taro.reLaunch({ url: '/pages/workspaces/index' })
    } catch (err) {
      Taro.showToast({
        title: err instanceof Error ? err.message : '登录失败',
        icon: 'none',
      })
    } finally {
      setSubmitting(false)
    }
  }

  if (restoring) {
    return (
      <View className='login-page'>
        <Text>加载中...</Text>
      </View>
    )
  }

  return (
    <View className='login-page'>
      <View className='login-header'>
        <Text className='login-title'>cndb</Text>
        <Text className='login-subtitle'>通用数据管理平台</Text>
      </View>

      {/* Tab 切换 */}
      <View className='login-tabs'>
        <View
          className={`login-tab ${tab === 'wechat' ? 'active' : ''}`}
          onClick={() => setTab('wechat')}
        >微信登录</View>
        <View
          className={`login-tab ${tab === 'password' ? 'active' : ''}`}
          onClick={() => setTab('password')}
        >账号密码</View>
      </View>

      {tab === 'wechat' ? (
        <View className='login-section'>
          <Button
            className='btn-wechat'
            type='primary'
            loading={submitting}
            onClick={handleWechat}
          >
            微信一键登录
          </Button>
          <Text className='login-tip'>首次使用将自动创建账号</Text>
        </View>
      ) : (
        <View className='login-section'>
          <Input
            className='login-input'
            placeholder='用户名或邮箱'
            value={login}
            onInput={(e) => setLogin(e.detail.value)}
          />
          <Input
            className='login-input'
            placeholder='密码'
            password
            value={password}
            onInput={(e) => setPassword(e.detail.value)}
          />
          <Button
            className='btn-primary'
            type='primary'
            loading={submitting}
            onClick={handlePassword}
          >登录</Button>
        </View>
      )}
    </View>
  )
}
