/** 组件: Loading */
import { View, Text } from '@tarojs/components'

export default function Loading({ text = '加载中...', small = false }: {
  text?: string; small?: boolean
}) {
  return (
    <View className='loading-wrap'>
      <Text className={small ? 'loading-text small' : 'loading-text'}>{text}</Text>
    </View>
  )
}
