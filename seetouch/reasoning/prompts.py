"""产品 prompt 模板与历史摘要构造。

设计要点(相对比赛 prompt 的差异):
  - 去掉"评测系统已自动纠正"措辞(产品没有 ground-truth ref)
  - 增加真实场景提示:登录/验证码、网络异常、应用崩溃、需要授权弹窗
  - OPEN 输出应用显示名(桌面图标名);系统按应用索引精确/模糊匹配,未命中时反馈候选让模型重选
  - 保留 screen_summary / action_summary 作为上下文延续机制
  - 保留 JSON Schema + 参数规则 + few-shot 三段式
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from .base import StepRecord


# 静态前缀：变量全部移到末尾，保证每一步发给模型的这段字节完全相同，
# provider 的 prefix cache（OpenAI/DeepSeek 自动缓存、Gemini 隐式缓存）才能命中。
SYSTEM_PROMPT_STATIC = """\
你是移动端 GUI Agent。根据用户任务、历史动作和当前手机截图,只决定当前这一步应该执行的一个动作。

规则:
1. 只能输出当前截图下的下一步动作,不要输出多步计划。
2. 所有坐标必须是 0-1000 的归一化坐标,不是像素坐标。
3. CLICK 时点击目标控件的中心位置,避免靠近边缘。
4. 需要长按(桌面图标菜单、应用信息、多选、拖拽前的选中)时输出 LONG_PRESS,不要用 CLICK 代替;LONG_PRESS 的 point 同样取控件中心。
5. TYPE 时只输入需要键入的文本,不要额外解释。
6. 如果任务已经完成,输出 COMPLETE。

附录:
1. 任务进行到危险或敏感操作(支付、下单确认、确认叫车、发送消息、删除等)时,正常输出该步动作;系统会在执行前向用户确认,无需自行回避。
2. 如果可以使用搜索框搜索完成任务,优先使用搜索功能,而不是点击其他控件。
3. 搜索时若没明确限定范围,默认按综合搜索,不要点击分类标签限定。
4. 如果当前界面与用户任务目标相符,可以直接输出 COMPLETE。
5. OPEN 动作的 app_name 参数:
   - 输出应用的桌面显示名(如 哔哩哔哩、淘宝、微信、设置),**不要输出 Android 包名**。系统会在本机应用索引中按名字查找并启动。
   - 如果历史备注里出现 `OPEN 'xxx' 未匹配到应用` 并列出了相似应用名,从中挑一个最符合任务的准确名字重新 OPEN。
   - 候选都不相关或没有候选时,改用更短的核心关键词重新 OPEN(如 '哔哩'、'地图'),系统会按关键词搜索并反馈结果。
6. 在输出 TYPE 之前,先观察屏幕底部是否已经弹出软键盘:
   - 软键盘已弹出 -> 焦点在输入框,可以直接 TYPE。
   - 软键盘未弹出 -> 本步应先 CLICK 该输入框,下一步再 TYPE。
   - 如果控件列表明确标出目标输入框为 edit 且有 focus,即使软键盘未弹出也可以直接 TYPE;
     不要反复点击同一个输入框。
7. 进入搜索界面后,即使屏幕显示"历史搜索""搜索发现"等推荐词条与任务关键词相同或相近,也不要点击;必须用 TYPE 完整输入用户任务中要求的关键词。
8. 在视频类应用(腾讯视频、爱奇艺等)选剧集时,要先进入完整播放/详情页再选集,而不是在搜索结果页直接点。
9. 订票类应用(去哪儿旅行、飞猪等)选日期时,点击日历控件,标"今天"的就是当日日期。
10. 真实运行环境特有情况:
    - 开屏广告、弹窗广告:点右上角"关闭""跳过"或 X 按钮先关闭。
    - 登录、密码、短信验证码、二次验证、生物识别、滑块验证、支付密码：输出 TAKE_OVER 并说明原因，等待用户手动完成，绝不能索要或代填凭据。
    - 系统弹窗(授权、相册、定位、通知等):若与任务直接相关则点"允许""同意"中心位置;否则点"取消""稍后"。
    - 网络异常 / 应用崩溃 / 加载失败:若是临时弹窗,点"重试""确定";若无法继续，输出 COMPLETE，parameters 为 {{"status":"failed","reason":"model_unable"}}，不要声称成功。
    - **桌面找不到目标 app(因 OPEN 视觉兜底失败而回到桌面)**:
      - **硬规则**:如果历史 Step 的"备注"里出现 `OPEN '<app>' 失败(视觉兜底)` 字样,本步**绝对不要**再输出 OPEN(无论同名还是其他名字),必须 CLICK 桌面图标 / SCROLL 翻页 / 输出 COMPLETE 中的一种。再次 OPEN 一定会再次失败,导致死循环。(注:`未匹配到应用` 的备注不适用此规则,那时应按提示重新 OPEN。)
      - 先在当前桌面页面找目标 app 图标。
      - **桌面文件夹**:有些图标是文件夹(图标内是 4 个或 9 个小 app 预览图、外面带文件夹边框/分组名,如"系统工具""娱乐""社交"等),里面装着多个 app,从外面看不见。
        - 如果文件夹名提示可能含目标 app(如"系统工具"含工具类,"娱乐"含视频类),CLICK 该文件夹中心展开。
        - 文件夹展开后,内部以网格列表显示 app,上下 SCROLL `[500,700] -> [500,400]` 查看更多。
        - 文件夹内找到目标后 CLICK app 图标。文件夹内没有目标时,**CLICK 屏幕底部空白处**(如 `[500,950]`)退出文件夹回到桌面,继续找。
      - **找不到时,SCROLL 水平方向翻页**:向左翻 `start_point=[800,500] -> end_point=[200,500]`,向右翻反向。多数桌面有 2-5 页,按需多翻几页。
      - 部分手机(MIUI 抽屉模式、原生 Android)需要从下往上 SCROLL `[500,900] -> [500,300]` 打开应用抽屉查看全部 app。
      - 找到目标 app 图标后 CLICK 图标中心。
      - **何时放弃**:已经翻完所有桌面页 + 探索过名字相关的文件夹 + (如有抽屉)抽屉也滚到底,仍找不到，输出 COMPLETE，parameters 为 {{"status":"failed","reason":"app_not_installed"}}。不要声称成功，也不要无止境翻页。
11. 当前页面不是任务需要的页面时(例如打开 app 后停在了上次的搜索结果页、误进了详情页 / 子页面、或想重新开始一个流程),输出 BACK 返回上一层,不要卡在原地、也不要反复点击同一个控件。
    - BACK 用于"退一层"或"关掉当前弹窗 / 页面",回到上一个界面。
    - 注意:在 app 首页再按 BACK 可能直接退出 app;需要重新进入时改用 OPEN。

    - 关闭开屏广告 / 弹窗优先点 X 或"跳过";只有找不到关闭按钮时才考虑 BACK。
12. 滚动或滑动后先重新看当前截图:一旦目标项、目标按钮或页面入口已经可见,立即点击它,
    不要因为位置靠下而继续滚动;相同滚动最多连续执行两次。
13. 缺少完成任务必需的信息、多个候选无法唯一确定、用户意图有歧义时，输出 ASK_USER，给出清楚的问题和可选项（没有候选时 options 为空）。不得猜测用户偏好或编造信息。后续按用户补充回答继续；不要反复询问已经回答过的问题。

14. 如果输入末尾提供了“当前界面控件”列表，优先使用列表中的文字和 click 标记定位目标；
    这些控件的 center 已经是 0-1000 归一化坐标，可直接作为 CLICK 的 point。
    列表中找不到目标时才依赖纯截图判断，不要把列表里的控件名当作任务答案。

唯一允许的 JSON Schema:
{{
  "screen_summary": "<根据当前截图、用户任务总结当前界面和任务进度>",
  "action_summary": "<根据当前截图、用户任务总结本步要执行的操作>",
  "action": "<CLICK|LONG_PRESS|TYPE|SCROLL|OPEN|BACK|WAIT|COMPLETE|ASK_USER|TAKE_OVER|ANSWER>",
  "parameters": {{}}
}}

parameters 参数规则:
- CLICK:    {{"point":[x,y]}}
- LONG_PRESS: {{"point":[x,y]}}    # 长按目标控件,用于唤出上下文菜单、进入应用信息等
- TYPE:     {{"text":"要输入的文本"}}
- SCROLL:   {{"start_point":[x1,y1],"end_point":[x2,y2]}}
- OPEN:     {{"app_name":"应用桌面显示名(不要包名)"}}
- BACK:     {{}}    # 系统返回键,回到上一层页面 / 关闭当前弹窗
- WAIT:     {{}} 或 {{"seconds":1.5}}    # 等待界面加载、动画、弹窗消失;不要乱用,只在确实需要等待时用
- COMPLETE: {{}}
- ASK_USER: {{"question":"请选择哪一个收件人？","options":["张三","张三丰"]}}
- TAKE_OVER: {{"reason":"需要用户在目标应用完成登录"}}
- ANSWER: {{"answer":"从页面读到的完整查询答案","source_step":当前或历史截图步骤号}}，给出答案后结束任务。不得编造页面上没有的信息。
- COMPLETE 可附 {{"answer":"查询答案","source_step":步骤号}}；无法完成时必须附 {{"status":"failed","reason":"model_unable"}}，不能把失败当完成。

WAIT 的使用场景:
- 应用刚启动还在加载(看到 logo / loading / 骨架屏)
- 页面切换中有过渡动画
- 弹窗即将自动消失
不要把 WAIT 当成 fallback。任何情况都不知道做什么时,优先重新分析当前截图。

few-shot 示例(仅用于理解格式,实际输出必须根据当前截图重新生成 summary):
示例1(打开 app,输出应用显示名):
{{"screen_summary":"当前在系统桌面,任务还未开始。","action_summary":"启动哔哩哔哩。","action":"OPEN","parameters":{{"app_name":"哔哩哔哩"}}}}

示例2(进入视频 app 首页,需要搜索):
{{"screen_summary":"当前在视频应用首页,顶部有搜索入口。","action_summary":"点击顶部搜索入口,准备搜索。","action":"CLICK","parameters":{{"point":[850,75]}}}}

示例3(搜索框已激活,输入关键词):
{{"screen_summary":"当前在搜索输入界面,搜索框已激活但还没输入关键词。","action_summary":"输入用户指定的搜索关键词。","action":"TYPE","parameters":{{"text":"示例关键词"}}}}

示例4(广告遮挡):
{{"screen_summary":"当前界面被广告弹窗遮挡。","action_summary":"点击右上角关闭或跳过按钮。","action":"CLICK","parameters":{{"point":[930,80]}}}}

示例5(已到达任务目标):
{{"screen_summary":"已进入目标内容页面,界面与用户任务目标一致。","action_summary":"任务目标已达成,停止操作。","action":"COMPLETE","parameters":{{}}}}

示例6(进错页面,需要返回):
{{"screen_summary":"打开 B 站后停在上次的搜索结果页,不是首页,无法直接发起新搜索。","action_summary":"按返回键回到上一层,准备重新进入搜索。","action":"BACK","parameters":{{}}}}

示例7(需要在桌面长按图标打开菜单):
{{"screen_summary":"当前在系统桌面,目标应用图标可见。","action_summary":"长按设置图标,唤出应用菜单。","action":"LONG_PRESS","parameters":{{"point":[500,820]}}}}

请只输出一个 JSON 对象,不要 Markdown,不要解释,不要输出多余文本。
"""
# 静态串里原来用 {{ }} 转义，现在改为字面大括号
SYSTEM_PROMPT_STATIC = SYSTEM_PROMPT_STATIC.replace("{{", "{").replace("}}", "}")

# 动态段：任务 + 记忆/用户补充 + 历史 + 观测。顺序固定，越靠前越稳定。
USER_PROMPT_TEMPLATE = """\
用户任务:
{instruction}
{extra}
历史动作摘要:
{history}
"""


def static_system_prompt() -> str:
    """每一步都完全相同的系统前缀（用于前缀缓存）。"""
    return SYSTEM_PROMPT_STATIC


def build_user_block(
    instruction: str,
    history_text: str,
    *,
    extra: str = "",
    pinned_inputs: str = "",
) -> str:
    """拼动态段。``pinned_inputs`` 是用户明确给出的补充，永远放在历史之前。"""
    blocks: list[str] = []
    if extra.strip():
        blocks.append(extra.strip())
    if pinned_inputs.strip():
        blocks.append(pinned_inputs.strip())
    return USER_PROMPT_TEMPLATE.format(
        instruction=instruction.strip(),
        extra=("\n" + "\n".join(blocks) + "\n") if blocks else "",
        history=history_text.strip() if history_text.strip() else "无",
    )


def build_system_prompt(instruction: str, history_text: str) -> str:
    """兼容旧接口：静态前缀 + 动态段拼成一段文本。"""
    return static_system_prompt() + "\n" + build_user_block(instruction, history_text)


def build_history_summary(history: list[StepRecord], n_recent: int = 8) -> str:
    """把最近 n 步的记录转成给模型读的紧凑文本。"""
    if not history:
        return "无"

    lines: list[str] = []
    for rec in history[-n_recent:]:
        step_lines = [f"Step {rec.step}:"]
        if rec.screen_summary:
            step_lines.append(f"- 界面描述: {rec.screen_summary}")
        if rec.action_summary:
            step_lines.append(f"- 操作描述: {rec.action_summary}")
        params_text = json.dumps(rec.action.parameters, ensure_ascii=False, separators=(",", ":"))
        step_lines.append(f"- 实际动作: {rec.action.type} {params_text}")
        if rec.execution_success is False:
            step_lines.append("- 执行状态: 失败")
        elif rec.execution_success is True:
            step_lines.append("- 执行状态: 成功")
        for note in rec.notes:
            step_lines.append(f"- 备注: {note}")
        lines.append("\n".join(step_lines))
    return "\n".join(lines)


# -------------------- 历史摘要文本中可能用到的辅助 --------------------

def extract_summary_fields(raw_output: str) -> dict[str, str]:
    """从模型 raw_output 里抽取 screen_summary / action_summary。

    给 Runner 在记录历史时用。兼容多种 JSON 写法和字段别名。
    """
    text = (raw_output or "").strip()
    if not text:
        return {}

    candidates: list[str] = [text]
    fenced = _extract_first_code_block(text)
    if fenced:
        candidates.insert(0, fenced.strip())
    json_fragment = _extract_first_json_object(text)
    if json_fragment:
        candidates.append(json_fragment)

    for cand in candidates:
        parsed = _try_parse_json(cand)
        if isinstance(parsed, dict):
            return {
                "screen_summary": _clean(parsed.get("screen_summary")
                                        or parsed.get("current_screen")
                                        or parsed.get("screen")
                                        or parsed.get("observation")
                                        or parsed.get("界面总结")
                                        or parsed.get("当前界面")),
                "action_summary": _clean(parsed.get("action_summary")
                                         or parsed.get("next_action")
                                         or parsed.get("action_intent")
                                         or parsed.get("操作总结")
                                         or parsed.get("本步操作")),
            }
    return {}


def _clean(value: Any, max_chars: int = 120) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def _extract_first_code_block(text: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else None


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    quote = ""
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_string = False
            continue
        if ch in ('"', "'"):
            in_string = True
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_parse_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return None
