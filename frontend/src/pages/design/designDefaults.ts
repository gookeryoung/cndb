/** 设计新建起步模板（ADR 0084 §9 / ADR 0086 C1 / C5）
 *
 * 侧栏产品列表与设计根页共用：抽出独立模块，避免侧栏（主包）反向依赖页面 lazy chunk。
 */

/** 新建设计的起步模板：复杂系统（system）→ 组件（module）→ 零件（图元）三级装配示例 */
export const DEFAULT_DESIGN_CONTENT = `// 四轮小车（rover）：复杂系统 → 组件 → 零件三级装配示例
param body_len = 120
param body_w = 60
param body_t = 8
param wheel_d = 40
param wheel_w = 16
param axle_d = 10

// 组件级：module 可复用 / 可实例化 / 可嵌套（子装配）
module wheel(d, w) {
  rotate([90, 0, 0])
    difference {
      cyl(d = d, h = w)
      translate([0, 0, -1]) cyl(d = d * 0.35, h = w + 2)
    }
}

module axle(d, len) {
  rotate([90, 0, 0]) tube(od = d, id = d * 0.6, h = len)
}

module chassis(len, w, t) {
  difference {
    box(size = [len, w, t])
    translate([0, 0, -1]) cyl(d = 14, h = t + 2)
  }
}

// 系统级：复杂系统装配声明（顶层根，不可实例化）
system rover {
  chassis(body_len, body_w, body_t)

  translate([body_len / 2 - 18, 0, 0]) axle(axle_d, body_w + 2 * wheel_w)
  translate([body_len / 2 - 18, body_w / 2 + wheel_w / 2, 0]) wheel(wheel_d, wheel_w)
  translate([body_len / 2 - 18, -body_w / 2 - wheel_w / 2, 0]) wheel(wheel_d, wheel_w)

  translate([-body_len / 2 + 18, 0, 0]) axle(axle_d, body_w + 2 * wheel_w)
  translate([-body_len / 2 + 18, body_w / 2 + wheel_w / 2, 0]) wheel(wheel_d, wheel_w)
  translate([-body_len / 2 + 18, -body_w / 2 - wheel_w / 2, 0]) wheel(wheel_d, wheel_w)

  translate([0, 0, body_t + 42]) sphere(r = 14)   // 零件级细节：传感器球头
}
`

/** 新建零件文件的起步模板：顶层 param 即公开参数，顶层实例即零件几何（ADR 0086 C1） */
export const DEFAULT_PART_CONTENT = `// 零件文件：顶层 param = 公开参数，顶层实例 = 零件几何
param width = 80
param depth = 40
param height = 12

// 顶层实例：零件几何（禁止 system 声明）
difference {
  box(size = [width, depth, height])
  translate([0, 0, -1]) cyl(d = 8, h = height + 2)
}
`

/** 新建装配文件的起步模板：use 引用 part 文件 + 组件级约束（ADR 0086 C5）
 *  注意：模板中的 "plate" 需替换为实际零件 file_key 才能编译通过 */
export const DEFAULT_ASSEMBLY_CONTENT = DEFAULT_DESIGN_CONTENT
