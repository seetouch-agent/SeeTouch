# Harness 设计（v2）

> 本文记录 SeeTouch 主循环之外那一层"运行支撑"的设计：观测、动作协议、进度记账、
> 预算与策略。代码在 `seetouch/harness/`。
>
> 参考对象是 [nanoMuse](https://github.com/nano-muse/nanoMuse)（GPL-3.0-or-later）
> 公开的 harness 文档与手机端 operator 实现。SeeTouch 是 Apache-2.0：这里只借鉴设计
> 思路，实现与接口都是独立编写的，没有复制其源码。

## 1. 为什么要重做

升级前，`Runner._step_once` 一个函数里同时做七件事：截图、降采样、取 UI 文本、算
界面签名、拼 prompt、调模型、执行动作、判终止。能跑，但五个问题一直存在：

| 问题 | 具体表现 |
|---|---|
| 观测是"三份数据" | 界面文本给 prompt，像素/文本哈希给"变没变"，坐标直接交给设备层，三者互不校验 |
| 模型坐标没人管 | 点偏几十个单位就落空，落空又表现为"界面没变"，被当成模型乱点 |
| 重复动作判定有边界 bug | 把坐标向下取整到 20 的桶里再比字符串，299 与 301 只差 2 却分属两桶，漏判 |
| 反馈只有一档 | 界面连续不变只给一句固定提示，到阈值直接杀，中间没有"换策略"这一档 |
| 预算分散 | `max_steps` 在 Task 上、超时在 Runner 上、token 只统计不设限 |
| 失败不可追溯 | "点了哪、实际点了哪、命中了什么控件"没进 trace，事后只能猜 |

## 2. 新架构

```
             ┌──────────────────────────────┐
 设备层 ───► │ Observation                  │  一帧：nodes + signature + screen
 屏幕/树     │  · render() 给 prompt        │
             │  · ground() 校准落点         │
             └───────────┬──────────────────┘
                         │
             ┌───────────▼──────────────────┐
             │ protocol.ground_action()     │  CLICK 吸附到真实控件中心
             │ protocol.validate_action()   │  诊断：点空、越界、缺参
             └───────────┬──────────────────┘
                         │ 修正后的 Action
             ┌───────────▼──────────────────┐
             │ ProgressLedger               │  每步一条：动作/结果/签名
             │  · repeated_streak() 容差去重│
             │  · unchanged_streak()        │
             │  · render() 回灌 prompt      │
             └───────────┬──────────────────┘
                         │
             ┌───────────▼──────────────────┐
             │ LoopPolicy                   │  nudge → escalate → abort
             │ + RunBudget                  │  步数 / 时间 / token
             └──────────────────────────────┘
```

模块分工：

| 模块 | 职责 | 关键导出 |
|---|---|---|
| `harness/nodes.py` | 节点模型与多来源归一化 | `UiNode`、`nodes_from_xml/rows/elements`、`render_nodes`、`nodes_signature` |
| `harness/observation.py` | 一帧观测、签名、落点校准 | `Observation`、`build_observation` |
| `harness/protocol.py` | 动作与观测对齐（CLICK / LONG_PRESS 落点吸附、诊断） | `ground_action`、`validate_action` |
| `harness/ledger.py` | 进度账本、容差去重 | `ProgressLedger`、`StepEntry`、`same_action` |
| `harness/budget.py` | 三维预算 | `RunBudget` |
| `harness/policy.py` | 提醒/升级/终止阶梯 | `LoopPolicy`、`LoopHint` |

## 3. 五个关键机制

### 3.1 节点归一化：一份数据，三处复用

`AndroidController.ui_elements()` 与 `NativeAndroidController.ui_elements()` 现在直接
返回结构化控件，`ui_context()` 变成前者 + `render_nodes()` 的薄封装。于是同一帧数据
同时供 prompt、trace 和点击校准使用，不再重复 `dump_hierarchy`。

文本在归一化时压平空白、把双引号换成单引号、截断 80 字符——这是原来散落在
`controller._clean` 里的规则，现在收敛到 `nodes._clean_text`。

### 3.2 观测签名：判断"界面到底变没变"

签名优先用结构（节点的 text/desc/resource/bounds 拼接后 SHA-1），忽略焦点这类瞬时
抖动；没有结构信息时退回界面文本哈希或截图像素摘要，与升级前一致。

这样"点击后界面没变"的判定不再依赖 OCR 文本或全屏像素差异，减少了动画/光标闪烁造成
的假"有变化"。

### 3.3 落点校准：把"差一点点"的点击拉回控件

`Observation.ground(point, radius=60)` 的规则：

1. 点已经落在某个可点控件矩形内 → 不改；
2. 否则找半径 60（归一化网格，约屏宽 6%）内最近的可点控件中心 → 改到中心；
3. 半径内没有可点控件 → 不改，只记诊断 `click_off_target`。

修改留痕：trace 里写 `click_grounded` 事件（from/to/命中控件），步骤备注里也带一行，
所以"模型想点哪、实际点了哪"永远可查。可用 `SEETOUCH_CLICK_GROUNDING=0` 关闭。

边界：只对 `CLICK` / `LONG_PRESS` 生效（两者都作用于一个点，打空的方式一样）；
`SCROLL` 的起止点不吸附——滑动方向是意图的一部分，不该被改。

### 3.4 容差去重：距离比较而不是分桶

`same_action(a, b, tolerance=40)` 按"类型 + 关键参数 + 各坐标分量差值 ≤ 容差"判断。
相对把坐标取整到桶再比字符串，距离比较不会在桶边界上漏判。

`Session.consecutive_identical_actions()` 也改用它，于是 `stuck_loop` 判定与账本共用
一套规则，不再有两份实现。

### 3.5 策略阶梯：不再只有"继续"和"杀"

```
unchanged ≥ 2   → nudge     温和提醒，拼进下一轮指令
unchanged ≥ 4   → escalate  明确要求换路径（BACK / 回桌面 / ASK_USER）
unchanged ≥ 8   → abort     idle_exhausted
repeated  ≥ 2   → nudge     "同样动作已经 N 次"
预算耗尽        → abort     max_steps / task_timeout / token_budget
```

默认阈值刻意对齐升级前行为：`unchanged_nudge_at=2` 与旧文案一致，`max_idle_steps=8`
放在原有的"连续 5 次相同动作"之后，避免升级本身改变已有任务的结局。

## 4. 兼容性

- 没有 `ui_elements()` 的设备（或返回空）→ 观测为空，落点校准自动跳过，行为与升级前
  完全一致；
- 所有新参数都有默认值，`Runner(...)` 的既有调用方无需改动；
- 新增环境变量（CLI）：
  `SEETOUCH_MAX_IDLE_STEPS`、`SEETOUCH_CLICK_GROUNDING`、
  `SEETOUCH_CLICK_GROUNDING_RADIUS`、`SEETOUCH_MAX_TOKENS`。

## 5. 验证

- 新增单元测试 59 项，覆盖节点归一化、观测、落点校准、账本容差、预算、策略阶梯与
  Runner 集成（吸附生效 / 关闭吸附 / 无结构信息回退 / 空转终止）；
- 全量测试：`284 passed, 1 skipped`（升级前基线 225 passed）；
- 已知未覆盖：真机上的端到端收益（需要 Android 环境），本轮改动没有跑设备回归。

## 6. 与 nanoMuse 的对应关系

| nanoMuse 的做法 | SeeTouch 的对应实现 | 差异 |
|---|---|---|
| 画面优先，节点表在后（"the picture decides"） | prompt 仍以截图为第一输入，节点表附在指令末尾 | 一致 |
| `_same_action` 像素容差 + 6 步空转预算 | `same_action` 距离容差 + `LoopPolicy` 空转阶梯 | 增加了中间档 escalation |
| `Outcome` 状态与模型文本分离 | 已有 R6 的 `premature_completion`；本轮加 `idle_exhausted` | 一致 |
| 解析失败把原回复回灌重试 | 已有 R5 的 `parse_error` 回灌 | 一致 |
| 密码框聚焦时转 hand_over | 未实现（设备层还没有 password 标志） | 待办 |

## 7. 下一步

1. 设备层暴露 password/focus 语义 → 补"秘敏输入框不代填"的硬保护；
2. 真机回归，量化吸附对点击成功率的影响（对比开启/关闭）；
3. 把 `ProgressLedger` 接进 `summary.json`，让评测脚本能按终止原因聚合；
4. 工具调用协议化（把 JSON action 换成显式 tool call），需要先改三个 reasoning adapter。

---

## 8. 上下文与成本（R8）

### 8.1 前缀缓存

每条请求现在是两条消息：

```
messages[0] = system  ← SYSTEM_PROMPT_STATIC，逐字节稳定（规则/schema/few-shot）
messages[1] = user    ← 任务 + 用户补充 + 历史 + 观测 + 截图
```

只要静态串不掺变量，provider 的 prefix cache（OpenAI / DeepSeek 自动缓存、Gemini 隐式
缓存）就能命中第一段。适配器把命中量写进 `usage.cached_tokens`，`Session` 累计成
`total_cached_tokens` 并写进 `summary.json`——所以"缓存有没有生效"是可测的，不靠感觉。

### 8.2 64k 预算压缩

`history_window=8` 的固定窗口被替换成预算驱动：

| 参数 | 默认 | 含义 |
|---|---|---|
| `SEETOUCH_CONTEXT_TOKENS` | 64000 | 上下文总预算 |
| 输出预留 | 2048 | 给模型回复留的额度 |
| 压缩触发 | 60% | 超过预算 60% 开始压缩 |
| 最近保留 | 12 步 | 更早的步骤压成摘要 |
| 最小保留 | 4 步 | 无论如何保留的最近步数 |

压缩是确定性的（不调模型）：动作分布、到过的界面、失败记录。同样的历史永远得到
同样的摘要，方便复现和 diff。

### 8.3 用户输入保真

`PinnedInputs` 单独维护"用户明确说过的话"（ASK_USER 的回答等），渲染成
「用户明确要求（必须遵守）」块，位置在进度和当前界面之前。它**不进入历史**，因此
压缩逻辑永远碰不到它。

### 8.4 成本相关的默认值

- 截图默认 JPEG q=85（原 PNG）；
- 思考模式默认关闭（`SEETOUCH_THINKING_MODE=disabled`）；
- 观测与 prompt 共用一帧数据（R7 起）。

> 注意：以上改动的收益（token 下降、缓存命中率）**尚未在真机任务上量化**，需要跑一轮
> 对比 E2E 才能写进结论。
