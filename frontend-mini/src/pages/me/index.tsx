/** 我的页面. */
import Taro from '@tarojs/taro'
import { View, Text, Button } from '@tarojs/components'
import { useAuth } from '@/store/auth'
import './index.scss'

export default function MePage() {
  const { user, isAuthenticated, logout } = useAuth()

  async function handleLogout() {
    Taro.showModal({
      title: '确认退出？',
      success: async (res) => {
        if (res.confirm) {
          await logout()
          Taro.reLaunch({ url: '/pages/login/index' })
        }
      },
    })
  }

  if (!isAuthenticated || !user) {
    return (
      <View className='me-page'>
        <View className='me-card'>
          <Text className='me-text'>未登录</Text>
          <Button className='btn-login' type='primary'
            onClick={() => Taro.reLaunch({ url: '/pages/login/index' })}>
            去登录
          </Button>
        </View>
      </View>
    )
  }

  return (
    <View className='me-page'>
      {/* 用户信息卡片 */}
      <View className='me-user-card'>
        <View className='me-avatar'>
          <Text className='me-avatar-text'>{(user.nickname || user.username).charAt(0).toUpperCase()}</Text>
        </View>
        <View className='me-user-info'>
          <Text className='me-nickname'>{user.nickname || user.username}</Text>
          <Text className='me-username'>@{user.username}</Text>
          <Text className='me-role-tag'>{roleLabel(user.role)}</Text>
        </View>
      </View>

      {/* 设置列表 */}
      <View className='me-menu'>
        <View className='me-menu-item' onClick={() => {
          Taro.showModal({
            title: '提示',
            content: '设置功能请在 PC 端完成',
            showCancel: false,
          })
        }}>
          <Text className='me-menu-label'>偏好设置</Text>
          <Text className='me-menu-arrow'>›</Text>
        </View>
        <View className='me-menu-item' onClick={() => {
          Taro.showModal({
            title: '关于 cndb',
            content: '通用数据管理平台\nv0.1.0',
            showCancel: false,
          })
        }}>
          <Text className='me-menu-label'>关于</Text>
          <Text className='me-menu-arrow'>›</Text>
        </View>
      </View>

      {/* 退出登录 */}
      <View className='me-actions'>
        <Button className='btn-logout' onClick={handleLogout}>退出登录</Button>
      </View>
    </View>
  )
}

function roleLabel(role: string): string {
  const map: Record<string, string> = {
    system_admin: '系统管理员',
    security_admin: '安全管理员',
    audit_admin: '审计管理员',
    user: '普通用户',
  }
  return map[role] || role
}
