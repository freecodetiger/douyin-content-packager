# 可执行 Pipeline

`scripts/pipeline.py` 是状态机与图片授权的唯一来源。将 `PIPELINE` 指向当前 Skill 内脚本的绝对路径。所有命令输出 JSON；保留同一次运行返回的 `state` 绝对路径，后续命令只使用该文件，不手工编辑状态 JSON。

## G0–G1：输入门禁

无论输入是否完整都先运行：

```bash
python3 "$PIPELINE" start \
  --transcript <字幕文件> \
  --photo <正面自拍> \
  [--photo <辅助自拍> ...] \
  [--channel-name <频道名>] \
  [--website <以 http:// 或 https:// 开头的链接>]
```

`--channel-name` 与 `--website` 均可省略。省略后不得在任何文案中自造值或留下占位符。

脚本检查字幕存在、格式受支持、有效文本足够，以及照片存在、格式可读、短边至少 640、长边至少 1024。退出码 2 且 `gate` 为 `G0`/`G1` 时，向用户列出错误后停止。

成功后用当前图像查看能力逐张检查照片。至少一张确为清晰正面照后登记：

```bash
python3 "$PIPELINE" approve-photo \
  --state <state> \
  --front-photo <已查看通过且来自 start 的照片>
```

只有返回 `G2_READY_FOR_ANALYSIS` 才能读取并分析字幕。

## G2：全文理解

覆盖完整字幕，确定统一传播命题：

```bash
python3 "$PIPELINE" record-analysis \
  --state <state> \
  --core-thesis <一句话核心> \
  --hook <点击动机> \
  --evidence <字幕中的最强依据>
```

成功后进入 `G3_READY_FOR_PLATFORM_PACKAGE`。

## G3：五平台逐项校验

按照 [packaging-playbook.md](packaging-playbook.md) 生成实际文案。每个平台单独执行一次 `record-platform`，失败时只修正该平台再重试。

### YouTube

```bash
python3 "$PIPELINE" record-platform --state <state> --platform youtube \
  --title <A> --title <B> --title <C> \
  --preferred <1|2|3> --reason <首选理由> \
  --body <完整描述> \
  --timestamp <MM:SS 模块> [--timestamp <MM:SS 模块> ...] \
  --tag <标签> --tag <标签> [--tag <标签> ...]
```

### B站

```bash
python3 "$PIPELINE" record-platform --state <state> --platform bilibili \
  --title <A> --title <B> --title <C> \
  --preferred <1|2|3> --reason <首选理由> \
  --body <简介> --dynamic <粉丝动态> \
  --tag <标签1> --tag <标签2> ... --tag <标签9>
```

### 小红书与抖音

```bash
python3 "$PIPELINE" record-platform --state <state> --platform <xiaohongshu|douyin> \
  --title <A> --title <B> --title <C> \
  --preferred <1|2|3> --reason <首选理由> \
  --body <正文或简介> \
  --tag <#标签> --tag <#标签> [--tag <#标签> ...]
```

### 视频号

```bash
python3 "$PIPELINE" record-platform --state <state> --platform weixin \
  --short-title <1–16字符> \
  --body <标题＋描述> \
  --tag <#标签> --tag <#标签> [--tag <#标签> ...]
```

脚本机械验证平台字段、标题数与长度、正文长度、标签格式与数量、YouTube 时间戳、B站粉丝动态、首选理由、不重复和无占位符。若 `start` 提供了频道名，则各平台标签必须包含它；若提供了网站，则每个平台正文必须包含完整链接。

五个平台全部通过后状态为 `G3_READY_FOR_MARKDOWN`。写出 Markdown：

```bash
python3 "$PIPELINE" write-markdown --state <state> [--output <目标.md>]
```

默认写入当前工作区 `outputs/<字幕文件名>-全平台发布方案.md`。相对 `--output` 也以本次运行的工作区为基准。同名文件已存在时自动使用 `-v2`、`-v3`，不覆盖。

## G4：封面方案门禁

只有 Markdown 成功写入后才能设计并登记 A/B/C：

```bash
python3 "$PIPELINE" record-plans \
  --state <state> --plan A --plan B --plan C
```

返回 `G4_AWAITING_USER_APPROVAL` 后，在对话中展示三套方案并结束回合。每套包含封面文字、人物、背景、主题对象、配色、3:4 构图和 16:9 构图。此阶段不调用任何成图工具。

用户明确选择并确认生成时才登记：

```bash
python3 "$PIPELINE" approve-plan \
  --state <state> --plan <A|B|C> --confirm
```

方案修改但未明确确认生成时继续停在 G4。

## G5：双比例并发首轮生成

首次成图只做一次双比例原子预检：

```bash
python3 "$PIPELINE" can-generate-pair --state <state>
```

只有退出码 0、`allowed: true` 且 `dispatch: concurrent-independent-calls` 才能成图。预先准备两份提示词：共同使用选定方案、人物身份和设计语言，但分别写明 3:4 与 16:9 的独立构图。随后用当前宿主支持的并发工具调用机制，在同一批次同时发起两个 built-in 图像生成请求；不要等待一张返回后才发第二张。

两个请求都结束后，再分别登记成功产出的实际文件：

```bash
python3 "$PIPELINE" record-generation \
  --state <state> --ratio 3:4 --image <竖版图片>

python3 "$PIPELINE" record-generation \
  --state <state> --ratio 16:9 --image <横版图片>
```

脚本检查文件存在和宽高比。单个请求在派发、生成或返回阶段失败时，立即把已消耗的尝试登记为失败：

```bash
python3 "$PIPELINE" record-generation-failure \
  --state <state> --ratio <3:4|16:9> --issue <具体失败原因>
```

登记后该比例被锁定，不自动补发；先向用户说明该比例未产出，并取得新的重试许可。若 `record-generation` 因文件或比例不合格而失败，也应再用 `record-generation-failure` 记录这次已消耗的成图尝试。

## G6：QA 与重试

查看两张原图并逐张登记：

```bash
python3 "$PIPELINE" record-qa \
  --state <state> --ratio <3:4|16:9> --status pass
```

失败时必须写具体问题：

```bash
python3 "$PIPELINE" record-qa \
  --state <state> --ratio <3:4|16:9> --status fail \
  --issue <问题> [--issue <问题> ...]
```

用户明确同意为失败比例再消耗一次额度后：

```bash
python3 "$PIPELINE" authorize-retry \
  --state <state> --ratio <3:4|16:9> --confirm

python3 "$PIPELINE" can-generate \
  --state <state> --ratio <3:4|16:9>
```

只有单比例 `can-generate` 再次返回 `allowed: true` 才能重试。两个比例 QA 均为 `pass` 后，`python3 "$PIPELINE" status --state <state>` 返回 `COMPLETE`。

## 不可绕过条件

- 每一步只以脚本成功返回为准；非零退出就是阻塞。
- 首轮生成使用 `can-generate-pair`，失败比例重试使用 `can-generate`。
- `approve-photo`、`approve-plan --confirm` 与用户重试授权均不能由 Agent 代替用户意图。
- 首轮授权只覆盖 3:4、16:9 各一次；所有补发都需要新的用户授权。
