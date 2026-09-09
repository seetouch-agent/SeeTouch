---
name: technical-decisions
description: OPEN 启动策略、视觉兜底机制、坐标体系、模型配置等关键技术决策
metadata:
  type: project
---

# 关键技术决策

更新时间：2026-09-09

---

## OPEN 启动策略：应用名一等公民（2026-07-05 重构，当前方案）

### 背景：为什么推翻旧的五级 fallback

VLM 对应用名有可靠知识，对 Android 包名没有（经常写错/瞎编）。
旧方案围绕"模型输出包名"设计（静态表/alias/包名直通），治标不治本。
现在 helper/on-device 都能拿到本机"显示名→包名"索引，直接让 VLM 输出应用名。

### 当前解析顺序（app_launcher.py + app_index.py）

```
open_app(name):
  ① learned cache   ~/.seetouch/learned_apps.json（持久化）
  ② 索引精确匹配    显示名归一化(casefold+去空白/分隔符)后相等
  ③ 索引强模糊      唯一子串命中("哔哩"→"哔哩哔哩")直接启动，verify 后回写 learned
  ④ 候选反馈        歧义/未命中 → raise OpenAppNotFound(suggestions)，
                    Runner 把候选写进 notes，VLM 下一步重选或换关键词
  ⑤ package 直通    仅内部调用兼容，prompt 已禁止 VLM 输出包名
  ⑥ 视觉兜底        索引不可用(PC 无 applist.json)直接触发；
                    或 Runner 累计 max_open_misses(默认3)次未命中后升级
```

**索引源抽象（AppIndexSource）：** on-device = `DeviceBridge.launchableApps()`
（"package\tlabel" 行）；PC = `~/.seetouch/applist.json`（pull_applist.py 自动同步，
可用 `SEETOUCH_APPLIST_PATH` 覆盖）；测试 = StaticAppIndexSource。

**两种 OPEN 失败 note 语义不同（prompt 已区分）：**
- `OPEN 'x' 未匹配到应用`：允许且应该重新 OPEN（挑候选/换关键词）
- `OPEN 'x' 失败(视觉兜底)`：禁止再 OPEN，必须 CLICK 桌面图标

**learned 回写时机：** 视觉兜底成功（原有）+ 强模糊命中且 verify_launch 确认前台（新增）。
精确命中不写（索引已是权威映射）。

**验证（模拟器 e2e）：** "打开时钟"→VLM 输出"时钟"→精确命中 2 步完成；
"打开哔哩哔哩"(未安装)→反馈→VLM 换关键词"哔哩"→再反馈→3 次后升级视觉兜底，全链路符合预期。

---

## ［已废弃 2026-07-05］旧 OPEN 五级 fallback（包名导向）

### 设计目标

- 不维护"全量"中文名→包名映射表（用户明确反对硬编码）
- 高频 app 秒开（静态表）
- 冷门 app 自动兜底（视觉识别）
- 海外模型输出兼容（alias 表）

### 五级 fallback 最终方案

```
open_app(name_or_package):
  ① learned cache  ~/.seetouch/learned_apps.json (视觉学到的)
  ② L1 静态表      app_table.lookup() (17 高频 app: 抖音/B站/微信/QQ...)
  ③ L1' alias      PACKAGE_ALIASES (TikTok→抖音, Twitter→微博...)
  ④ L2 直通        re.match(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$') && installed
  ⑤ L4 视觉兜底    go_home() + raise OpenAppNeedsVisual
```

**关键：learned cache 只在视觉兜底成功后写入，不在 L1/L2/alias 启动后自动学习。**

**Why：** L1/L2 已是权威映射，学了是冗余；只有视觉兜底是"模型+用户+设备"三方验证过的新映射，值得持久化。

**废弃原因：** 依赖 VLM 输出包名，而 VLM 没有包名知识；静态表/alias 覆盖面永远不够。
`app_table.py` 文件保留但已不被引用。下节"fuzzy 移除"针对的是旧方案对**包名**做模糊匹配的 bug；
新方案的模糊匹配是对**应用显示名**，且歧义时不猜、反馈给模型，不存在同类假阳性风险。

---

## fuzzy 模糊匹配为何移除（2026-05-21 起）

### 原方案（已废弃）

```python
def fuzzy_match(query, candidates):
    # 剥前缀 com./cn./tv. ...
    # difflib.SequenceMatcher 相似度 > 0.75
    # 长度门槛 >= 4 字符
    # 黑名单 {app, main, lite, pro, mobile, ...}
```

### 真机死循环 bug 复盘（2026-05-20）

**症状：** "打开抖音" 连续 12+ 步重复 OPEN，直到用户打断。

**根因链：**
1. 模型输出 `com.zhiliaoapp.musically`（TikTok 海外版）
2. 设备未安装，fuzzy_match 在 447 个包里误匹配到 `com.biquge.ebook.app`（笔趣阁）
   - `com.` 公共前缀让相似度虚高
   - `app` 末尾段仅 3 字符未被黑名单化
3. 错误结果立即写入 cache，后续重试始终用错的
4. 模型识别出"这是笔趣阁不是抖音"，再次 OPEN，Runner 无死循环检测 → 无止境

**修复措施（全部已上线）：**
- **移除 fuzzy_match 整段代码**（从 L3 直接跳到 L4 视觉兜底）
- 新增 PACKAGE_ALIASES 表（TikTok → 抖音、Twitter → 微博等）
- AppLauncher 改为 verify-then-learn（启动后轮询 `current_app()`，通过才写 cache）
- Runner 加 `consecutive_identical_actions=3`，3 步同动作即 abort("stuck_loop")
- Prompt 强调"必须用国内大陆版 package，不要 TikTok"

**Why：** Android 包名公共部分（com./cn./tv./org.）太多，字符串相似度假阳性极高。learned cache 在执行前写入是危险的——一旦误学，永久错误。

**How to apply：** 后续如果再考虑"自动发现 app 映射"，必须：
- 在真机验证成功后才写 cache（verify-then-learn）
- 多步确认前台稳定（不要刚误点别的 app 就学了）
- 或按任务完成度回写（任务 COMPLETE 才认为映射正确）

---

## 视觉兜底机制

### 触发条件

`OpenAppNeedsVisual` 异常 → Runner 捕获后标记 `pending_visual_request` 和 `visual_baseline_app`（当前桌面 package）。

### 学习触发

每步执行后，如果：
- `pending_visual_request` 非空
- 当前动作不是 OPEN
- `current_app()` 切换到非 baseline 的真实 app

则调用 `device.learn_app_from_visual(request, current)` 写入 cache。

### Prompt 引导（三轮迭代）

**Iteration 1（无引导）：** 模型重复 OPEN 同名 app → 死循环。

**Iteration 2（硬规则）：** 
- note 激进措辞："❗ OPEN 'xxx' 失败，本步绝对不要再 OPEN 同名 app，必须 CLICK 桌面图标"
- prompt 加硬规则：历史里看到 `OPEN '<app>' 失败` 字样，本步绝对不能再 OPEN
- 效果：不再死循环，正确 SCROLL 翻页 + 上滑抽屉，但找不到文件夹内的 app

**Iteration 3（桌面文件夹支持）：**
- 桌面文件夹识别：图标内 4/9 个 app 预览 + 外框 + 分组名
- 展开方式：CLICK 文件夹中心
- 退出方式：CLICK 屏幕底部空白（如 `[500,950]`）
- 何时放弃：翻完所有页 + 探索过名字相关的文件夹 + 抽屉滚到底

**Why：** 桌面文件夹是 Android 设备非常普遍的 UI 元素，产品 prompt 不能假设 app 一定有顶层图标。

---

## WAIT 动作协议（2026-06-01 新增）

### 设计初衷

真机测试"在哔哩哔哩搜索采莲曲"时，B 站启动后还在加载页，模型输出：
```json
{"action": "WAIT", "parameters": {}}
```
但协议不支持 WAIT，parser 失败兜底返回 `Action(COMPLETE)`，任务被"假完成"提前终止。

### 实现

- `Action` 新增 `ACTION_WAIT`，参数 `{"seconds": float}` 可选，默认 1.5s
- `Runner._execute(WAIT)` = `time.sleep(clip(seconds, 0.5, 5.0))`
- parser 失败的 fallback **从 COMPLETE 改成 WAIT**（不要让 parse 错误静默"假完成"）
- Prompt 说明：只在"界面加载中 / 动画即将结束 / 弹窗即将消失"场景使用，不要当 fallback

**Why：** 模型有"等一下"的合理需求。静默 fallback 到 COMPLETE 极其危险——任何 parser bug 都会被伪装成"任务完成"，后续无从排查。

**How to apply：** 之后再发现模型输出协议外的 action，优先**加协议**（如 LONG_PRESS、PINCH），不要再让 parser 兜底到 WAIT 之外。已落地一例见下节 [[#BACK 返回键动作（2026-06-19 新增）]]。

---

## BACK 返回键动作（2026-06-19 新增）

### 设计初衷

真机"在哔哩哔哩搜索采莲曲"时，打开 B 站后停在了**上次的搜索结果页**（不是首页）。正常应按系统返回键退回首页再重新点搜索框，但协议没有返回动作，模型只能反复点搜索框 / 卡死。Android 的返回是系统级硬件/手势键，**不是屏幕可点击控件，CLICK 任何坐标都点不到**，必须新增独立动作。

### 实现（全链路 6 处）

- `core/action.py`：`ACTION_BACK="BACK"` 加入 `ActionType` / `VALID_ACTIONS`；无参数，`validate()` 走 fall-through（同 COMPLETE）。
- `device/base.py`：Protocol 新增 `back()`。
- `device/android/controller.py`：`back()` = `self._d.press("back")`（与 `go_home` 的 `press("home")` 对称）。
- `core/runner.py`：`_execute` 加 `elif ACTION_BACK: self.device.back()`，不加 sleep（同 CLICK，press 同步）。
- `reasoning/parser.py`：JSON 路径 + 文本兜底正则都加 BACK 分支，无参数返回 `Action(BACK, {})`。
- `reasoning/prompts.py`：Schema 枚举、参数表、附录规则 11（进错页/子页面/重开流程时 BACK 退一层，别卡原地或反复点）、few-shot 示例6。

### 关键点

- **死循环检测自动覆盖**：连按 3 次 BACK 触发 `stuck_loop` abort，正好兜住"狂按返回把 app 退出"的失控，无需额外逻辑。
- **prompt 提醒副作用**：在 app 首页再 BACK 可能直接退出 app，需重新进入时改用 OPEN；关广告/弹窗优先点 X / 跳过，找不到关闭按钮才用 BACK。
- 调试器无需改：BACK 是无坐标动作，`drawActionOverlay` 只对 CLICK/SCROLL 画覆盖层，其余（WAIT/OPEN/COMPLETE/BACK）直接显示动作名文字。

**Why：** 兑现了 WAIT 节"优先加协议"的约定——返回是真机高频刚需，缺它会直接卡死任务。

**How to apply：** 后续若再加 HOME / LONG_PRESS / 切换 app 等系统级动作，照这条 6 处链路改（action→base→controller→runner→parser→prompts + 测试），并确认死循环检测与调试器渲染是否需要适配。

---

## 坐标体系（沿用比赛协议）

- **归一化坐标**：0-1000 区间，与设备分辨率无关
- **perception 层负责转换**：`normalize(pixel_x, pixel_y, width, height)` / `denormalize(x, y, width, height)`
- **Why：** 模型已在比赛数据上训练，习惯 0-1000 体系；跨设备泛化能力强

---

## 截图工作分辨率：统一降到 720P（2026-06-19）

### 决策

`device.screenshot()` 拿到的全分辨率截图，在 `Runner.step()` **源头**立刻 `downscale()` 到宽 720（如 1440×3200 → 720×1600）。之后**上传 VLM、落盘日志、parser 尺寸基准三者共用这一张 720P 图**，不再各自处理。

### Why

- **上传带宽**：全尺寸 PNG 每步传给 Doubao API 是 `reasoning_time` 里的上传大头；降到 720P 像素量约降 4 倍（4.6M → 1.15M px），直接缩短上传段。
- **日志体积**：`runs/<task>/step_*.png` 之前存全尺寸，日志目录膨胀快；同一张 720P 同步瘦身。

### 为什么对点击零影响（关键，非显然）

坐标全程走 0-1000 归一化：模型输出归一化 → parser 保持归一化（`image_size` 仅在模型误输出像素值时当兜底换算）→ `AndroidController.click` 用 `self.screen_size()`（u2 `window_size()`，**真实设备分辨率**）换算像素。**截图分辨率从不参与点击坐标计算**，所以可随意缩放。参见 [[#坐标体系沿用比赛协议]]。

### How to apply

- 缩放统一走 `perception/screen.py` 的 `downscale(image, max_width=WORK_MAX_WIDTH=720)`，不要在多处各缩各的。
- 调试器前端 `_image_to_b64(max_width=720)` 现在是 no-op（源头已 720），不会二次缩放。
- 还想再压上传体积：下一个杠杆是上传转 JPEG（当前仍 PNG，720P PNG ~几百 KB，JPEG ~几十 KB）。

### thinking 开关不在此次优化范围

thinking 慢主要在**服务端推理**，不在上传。成熟产品里 thinking 开不开**由用户指定**，不能为省时间强制关——这次只优化上传链路，不动 thinking。见下节性能对比。

---

## OpenAI 兼容 API 作为默认推理后端（2026-09-09）

### 当前方案

- `OpenAICompatibleReasoner` 使用 OpenAI Chat Completions 多模态消息格式：文本 prompt +
  `image_url` data URL。
- API key、Base URL、模型 ID 分别由 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、
  `OPENAI_MODEL_ID` 配置；`VLM_API_KEY` 作为 API key 兼容变量保留。
- CLI、调试器、统一配置和 Android on-device 入口默认选择 `openai`；Doubao 和 Gemini
  仍可显式选择。
- OpenAI 兼容服务共用一个 reasoner，不为服务商维护硬编码映射或分支。

### 思考强度

`OPENAI_REASONING_EFFORT` 接受 `minimal` / `low` / `medium` / `high` / `xhigh`。
未设置或设为 `default` 时不发送该字段，让模型使用默认行为。

Android 内嵌的 OpenAI SDK 版本较旧，因此 `reasoning_effort` 通过 `extra_body` 发送，
避免依赖新 SDK 的显式方法参数。兼容协议不保证每个模型支持全部档位，调用方应按模型
能力选择；不支持时使用模型默认。

### Why / How to apply

OpenAI Chat Completions 已成为多家视觉模型服务的共同接口。将地址和模型参数化，可以
在不改代码的情况下切换服务商，同时保留 `Reasoner` Protocol 作为非兼容协议的扩展点。
新增兼容服务时只配置环境变量，不新增 provider 类；只有请求/响应协议确实不同才新增后端。

---

## Doubao thinking 模式演化

### 比赛阶段（已结束）
- 强制 `disabled`（BaseAgent 硬编码 `extra_body={"thinking": {"type": "disabled"}}`）
- 原因：比赛规则约束

### 产品阶段（2026-05-21 起）
- 默认 `auto`（模型按需启动 VisualCoT）
- 配置：`SEETOUCH_THINKING_MODE` 环境变量
- 成本监控：`_extract_usage` 带 `reasoning_tokens`

### 真机发现（2026-05-31）
- API 报 400：`Unsupported thinking type for the current model: auto`
- doubao-seed-1-6-vision-250815 只支持 `enabled` / `disabled`
- 改默认为 `enabled`（准确率优先）

### 性能对比（Xiaomi rubens / Android 12）

| thinking_mode | 步均耗时 | 准确率 | 适用场景 |
|---|---|---|---|
| disabled | 3-5s | 中 | 简单任务、成本敏感 |
| enabled | 7-12s | 高 | 复杂场景（小控件、广告识别） |
| auto | - | - | vision 模型不支持 |

**Why：** thinking=enabled 慢 2-3 倍，但识别准确率明显提高（B 站开屏广告自动跳过、复杂搜索场景不再瞎点）。

**How to apply：** 显式使用 Doubao 后端时默认 `enabled`（准确率优先）；成本敏感场景可切
`disabled`；添加新模型时先探测支持的 thinking 模式集合。**成熟产品里 thinking 开关由
终端用户指定，系统不强制关**——优化耗时优先动上传/网络等链路，不要替用户关 thinking。

---

## 思维链在 reasoning_content 独立字段（2026-06-26）

**关键事实：** thinking=enabled 时，Doubao 把 VisualCoT 思维链放在 `response.choices[0].message.reasoning_content`，**不在** `message.content`。只读 content 会完全丢掉思维链。

**已落地：** `DoubaoReasoner._extract_reasoning_content()` 提取该字段 → 经 `ActionOutput.reasoning_content` → `StepResult` → 调试器「🧠 思维链」折叠区（详见 [[development_history.md]] 2026-06-26 复盘）。

**Why / How to apply：** OpenAI 兼容 API 的扩展能力常挂在 message 的非标准字段（reasoning_content / tool_calls 等），content 只是最小公共子集。接新模型或新能力时先打印整个 response 看字段，别假设都在 content 里。

---

## EventBus 事件总线（2026-06-27 新增）

### 设计初衷

调试器每步执行 5-12 秒（80% 在等 VLM API），前端完全无反馈。需要在 Runner 执行过程中向外广播中间状态（截图完成、推理中、推理完成等），同时还需要把 Python logging 日志实时流到前端。

### 为什么不用简单回调

- 回调只能挂一个消费者，加第二个就要改接口
- 进度流和日志流是两类不同的消费者，都监听同一套事件
- 未来加 metrics 收集、远程推送等零改动

### 实现

```
core/event_bus.py  — 发布-订阅，线程安全(RLock)，handler 异常不影响其他
core/log_bridge.py — logging.Handler → EventBus 桥接，生命周期 install/uninstall 幂等
```

**事件类型：**
- `step.screenshot_taken` — 截图 + 降分辨率完成（含 PIL Image）
- `step.reasoning_started` — 开始调用 VLM API
- `step.reasoning_done` — VLM 返回，含 action + reasoning_time
- `step.executing` — 开始执行设备动作
- `log` — 日志记录（由 LogBridge 发射）

**组装层（app.py）：**
```
EventBus() → Runner(event_bus=bus) + DebugSession(runner, event_bus=bus)
           → LogBridge(bus).install()
           → DebugSession 订阅事件 → socketio.emit("step_progress" / "log")
```

**How to apply：** 后续如需新增可观测数据（如 token 流式输出、设备状态变化），在 `event_bus.py` 定义新事件常量，Runner 或其他模块 emit，消费者 subscribe 即可，不改现有接口。CLI 路径不传 event_bus，零开销。

---

## 死循环检测（2026-05-21 新增）

### 机制

`Runner` 维护 `consecutive_identical_actions` 计数器：
- 连续 3 步相同 action + parameters → abort("stuck_loop")
- 不同动作时重置计数器

### 覆盖场景

- OPEN 失败后重复 OPEN（视觉兜底前的死循环）
- WAIT 无限等待
- CLICK 同一位置无响应

**Why：** 首次真机跑遇到 12+ 步 OPEN 死循环，用户手动打断。产品不能依赖人工监控。

---

## 动作后 settle delay（2026-06-30 新增）

### 设计初衷

真机测试发现模型"保险性重复点击"（如 B 站搜索时 step 4-5 反复点搜索框），根因不是模型保守，而是 **Runner 执行动作后立刻截图，拿到的是旧画面**——模型看到界面没变化，合理地判断"上一步没生效"。

u2 的 `click()`/`swipe()`/`press()` 等调用完成即返回（设备层操作是同步的），但 **Android 界面响应需要时间**：页面跳转、动画播放、内容加载、惯性滚动都不是瞬时的。

### 实现

Runner 新增 `action_settle_seconds` 参数（默认 1.0s），在 `_execute()` 成功后、下一轮截图前 sleep：

```python
if success and out.action.type not in (ACTION_WAIT, ACTION_COMPLETE):
    time.sleep(self.action_settle_seconds)
```

**条件守卫：**
- WAIT：本身就是 sleep，不再加
- COMPLETE：不执行设备动作（且 COMPLETE 在 step() 前面已经 return）
- success=False：设备报错了，等也没意义

**统一等待逻辑：** 同时移除 `controller.py` 中 `open_app()` 的硬编码 `time.sleep(1.0)`，等待逻辑收到 Runner 层统一管理。device 层只负责执行操作本身，不管"等多久给模型截图"。

**计时归属：** settle delay 不算进 `execution_time`——sleep 加在 `execution_time = time.perf_counter() - t1` 之后，保持 `execution_time` 反映设备动作真实耗时。

### 默认值选择

1.0 秒。理由：与 OPEN 原来硬编码的值一致且验证过够用；真正需要等久的场景由模型自行输出 WAIT。可通过构造参数调整。

**Why：** 操作后截图拿到旧画面是系统性 bug——每一步都可能浪费一次推理调用，直接拉低任务效率和成功率。

**How to apply：** 后续如果发现特定动作需要更长/更短的 settle 时间，可按动作类型做差异化（如 SCROLL 等惯性滚动结束可能需要更长），但先用统一值验证。

---

## 相关记忆

- [[product_overview.md]] — 产品定位、核心能力
- [[development_history.md]] — 死循环 bug 详细复盘、MIUI 踩坑
- [[future_roadmap.md]] — on-device APP 迁移计划、PackageManager 方案
