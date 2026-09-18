/** slow-test.ts — E2E 性能回归告警 reporter.
 *
 * 背景：A1 已把硬编码 `waitForTimeout` 收敛到 `settle()` 信号化等待。此 reporter 在每个
 * 用例结束时采样时长，超阈值即告警，供人识别疑似重新引入的固定 sleep。
 *
 * 默认**仅告警、不阻断**：本套件 test timeout=30s，重交互用例（字段引入/权限成员/表复制/
 * 视图筛选等）本身即需 20~30s，按绝对时长一刀切必然误伤已通过用例。故超阈值只打印清单，
 * 观察期先收集基线数据。
 *
 * 需要收紧为门禁时（CI 稳定后）设 `E2E_SLOW_ENFORCE=1`，超阈值将置退出码 1。
 * 阈值默认 20s，可用 `E2E_SLOW_THRESHOLD_MS` 覆盖。
 *
 * 用法（playwright.config.ts reporter 数组）：
 *   reporter: ["list", "./tests/e2e/reporters/slow-test.ts"]
 */
import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";

const SLOW_MS = Number(process.env.E2E_SLOW_THRESHOLD_MS ?? 20_000);
const ENFORCE = process.env.E2E_SLOW_ENFORCE === "1";

class SlowTestReporter implements Reporter {
  private slow: Array<{ title: string; ms: number }> = [];

  onTestEnd(test: TestCase, result: TestResult): void {
    const ms = result.duration;
    if (ms > SLOW_MS) {
      this.slow.push({ title: test.titlePath().join(" › "), ms });
    }
  }

  onEnd(): void {
    if (this.slow.length === 0) return;
    console.error(
      `\n[slow-test] ${this.slow.length} 条用例超过慢测阈值 ${SLOW_MS}ms${ENFORCE ? "（门禁模式，以下视为回归）" : "（告警，观察期不阻断）"}：`,
    );
    for (const s of this.slow) {
      console.error(`  ${s.ms}ms  ${s.title}`);
    }
    if (ENFORCE) {
      process.exitCode = 1;
    }
  }
}

export default SlowTestReporter;