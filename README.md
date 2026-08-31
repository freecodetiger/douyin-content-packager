# Douyin Content Packager

一个面向中文知识、技术和观点类视频的 Codex Agent Skill。

它会读取完整字幕或文字稿，把同一条视频分别包装成适合 **YouTube、B站、小红书、抖音、视频号** 的发布文案，并在用户确认方案后生成 **3:4 竖版**与 **16:9 横版**人物封面。

这个 Skill 最看重两件事：

- 文案不是简单地“一稿五发”，而是根据不同平台的标题长度、用户语境和内容结构分别改写；
- 图片生成有明确门禁，先选方案、再消耗额度，未经确认不会擅自出图或自动重试。

## 主要能力

- 固定生成五个平台的标题、正文与标签；
- 每个平台使用独立的标题策略和文案表达；
- YouTube 自动整理章节时间戳；
- B站额外生成粉丝动态；
- 小红书、抖音、视频号按各自长度和标签规则适配；
- 输出一份可直接使用的 Markdown 发布方案；
- 提供 A/B/C 三套人物封面方向；
- 分别为 3:4 和 16:9 重新构图，不做机械裁切；
- 用户授权后，并发发起两个独立的首轮成图请求；
- 单张生成或 QA 失败后，必须再次获得用户授权才能重试。

## 为什么要设置输入门禁

高质量包装依赖完整内容和可靠的人物参考，因此每次任务必须提供：

1. 一份可读取的字幕或文字稿文件；
2. 至少一张清晰正面的主人公自拍照。

推荐额外提供 1～2 张不同角度、表情或手势的照片，但它们不能代替正面照。

如果任一必需输入缺失，Skill 会直接返回待补清单，不会先猜测内容、生成标题或消耗图片额度。

### 支持的字幕格式

`.srt`、`.vtt`、`.ass`、`.ssa`、`.lrc`、`.txt`、`.md`、`.json`

### 支持的图片格式

`.jpg`、`.jpeg`、`.png`、`.webp`、`.heic`、`.heif`、`.avif`

图片仍需经过实际查看和质量判断；扩展名受支持不代表一定能通过正面照门禁。

## 安装

将仓库克隆到 Codex Skills 目录：

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/freecodetiger/douyin-content-packager.git \
  ~/.codex/skills/douyin-content-packager
```

如果你已经安装过，可以在本地 Skill 目录更新：

```bash
git -C ~/.codex/skills/douyin-content-packager pull
```

## 使用方式

在 Codex 中附上字幕文件和主人公自拍，然后直接调用：

```text
使用 $douyin-content-packager 包装这条视频。
字幕文件是：/path/to/video.srt
正面自拍是：/path/to/front.jpg
```

频道名和个人网站链接是可选信息：

```text
频道名：硬核AI实验室
个人网站：https://example.com
```

提供后，它们会自然出现在对应平台的正文或标签中；没有提供时会被彻底省略，不会留下 `{频道名}`、`{个人网站链接}` 或“待补充”之类的占位符。

## 输出内容

默认生成：

```text
outputs/<字幕文件名>-全平台发布方案.md
```

如果文件已经存在，会自动创建 `-v2`、`-v3` 等新版本，不覆盖原文件。

Markdown 包含：

| 平台 | 输出内容 |
|---|---|
| YouTube | 3 个标题、首选建议、描述、时间戳、标签 |
| B站 | 3 个标题、首选建议、简介、9 个标签、粉丝动态 |
| 小红书 | 3 个标题、首选建议、正文、标签 |
| 抖音 | 3 个标题、首选建议、简介、话题标签 |
| 视频号 | 短标题、标题＋描述、标签 |

为了保持成品聚焦，默认不生成发布时间建议、Newsletter、网站同步、数据追踪或下期选题。

## 严格 Pipeline

这个 Skill 不只依赖提示词约束，`scripts/pipeline.py` 会实际记录并检查每个阶段：

```text
字幕与自拍通过
  → 完整内容理解
  → 五平台文案逐项校验
  → 写入 Markdown
  → 展示 A/B/C 封面方案
  → 等待用户明确授权
  → 并发生成 3:4 与 16:9
  → 双图 QA
```

任何门禁失败都会阻止 Pipeline 继续推进。详细命令和状态说明见 [references/pipeline.md](references/pipeline.md)。

## 封面生成原则

- 用户自拍只用于主人公身份和人物特征；
- 内置参考图只用于版式、配色、文字层级和信息密度；
- 3:4 与 16:9 使用同一设计语言，但分别重新构图；
- 展示 A/B/C 方案不等于获得生成许可；
- 首次授权只覆盖两个比例各一次首轮生成；
- 图片失败或文字、身份、构图不合格时，不会自动补发。

只有当前 Codex 环境具备 built-in 图像生成能力时，才会执行实际成图。

## 本地验证

运行 Pipeline 测试：

```bash
python3 scripts/test_pipeline.py
```

当前测试覆盖输入缺失、五平台 Markdown、可选品牌信息、文件防覆盖、双图授权、失败重试门禁和图片宽高比检查。

## 项目结构

```text
douyin-content-packager/
├── SKILL.md
├── agents/openai.yaml
├── assets/
│   └── creator-cover-style-reference.png
├── references/
│   ├── cover-playbook.md
│   ├── input-handling.md
│   ├── packaging-playbook.md
│   └── pipeline.md
└── scripts/
    ├── pipeline.py
    └── test_pipeline.py
```

## 反馈与共建

如果你在实际使用中发现平台规则变化、标题风格不够自然、Pipeline 存在漏网路径，欢迎提交 Issue 或 Pull Request。最好同时附上脱敏后的输入类型、预期行为和实际结果，方便复现和改进。

也欢迎分享你跑出来的发布方案与封面效果，让这个 Skill 更贴近真实的中文创作场景。
