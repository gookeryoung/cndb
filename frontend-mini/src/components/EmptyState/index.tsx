/** 组件: EmptyState */
import { View, Text, Button } from '@tarojs/components'

export default function EmptyState({ text, action, onAction }: {
  text: string; action?: string; onAction?: () => void
}) {
  return (
    <View className='empty-wrap'>
      <View className='empty-icon'>📭</View>
      <Text className='empty-text'>{text}</Text>
      {action && onAction && (
        <Button className='empty-action' onClick={onAction}>{action}</Button>
      )}
    </View>
  )
}
