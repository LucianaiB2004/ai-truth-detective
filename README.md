# AI 打假侦探（ai-truth-detective）

> 眼见不一定为实。调用腾讯云 AI 生成识别能力，检测图片 / 文本 / 视频「是人做的，还是 AI 做的」，输出结构化的验真报告。

一个基于腾讯云 AI Skills 的**多模态内容验真**工具：把腾讯云「图片 / 文本 / 视频 AI 生成识别 + AI 人脸防护盾」串成一条可复现的检测链路，既可作为独立 CLI 使用，也可作为 Skill 接入 WorkBuddy / CodeBuddy 等智能体平台。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-green.svg)](https://www.python.org/)

---

## 功能特性

| 模态 | 能力 | 真实调用的腾讯云接口 |
|------|------|----------------------|
| 🖼️ 图片 | 检测图片是否由 SD / Midjourney / GPT-4o 等生成；含人脸时追加换脸检测 | `ims` ImageModeration (IMAGE_AIGC) + `faceid` DetectAIFakeFaces |
| 📝 文本 | 鉴别文本是否 AI 代写 | `tms` TextModeration (TEXT_AIGC) |
| 🎬 视频 | 检测视频是否由 Veo3 / 混元 / 即梦等生成（异步两段式） | `vm` CreateVideoModerationTask → DescribeTaskDetail |
| 🔍 交叉验证 | VITA 多模态找"物理破绽"（手指 / 光影 / 透视 / 文字乱码） | VITA `youtu-vita`（可选） |

**核心特点：零 SDK 依赖** —— 不依赖 `tencentcloud-sdk-python`，用 Python 标准库手写 TC3-HMAC-SHA256 签名直接调腾讯云 API（签名已与官方 SDK 做字节级比对验证）。

## 架构

```
输入（图片 / 文本 / 视频）
  → ① 模态分流：按扩展名自动识别输入类型
  → ② 云端检测：图片→ims / 文本→tms / 视频→vm（异步两段式）
        └─ 图片含人脸时，追加 faceid 换脸检测
  → ③ VITA 交叉验证（可选）：多模态模型找物理破绽
  → ④ 透传结果：原样返回腾讯云的 suggestion/label/score 等原始字段，不做二次加工
```

## 快速开始

### 前置要求

- Python 3.8+
- 腾讯云账号，并已开通「AI 生成内容识别」服务
- 腾讯云 API 密钥（SecretId / SecretKey）

### 安装

```bash
git clone <仓库地址>
cd ai-truth-detective
```

无需 `pip install`，零第三方依赖（可选 VITA 交叉验证需要 `openai` 包）。

### 配置

复制密钥模板并填入你的腾讯云密钥：

```bash
cp .env.example .env
# 编辑 .env，填入 SecretId / SecretKey / 三个 BizType
```

`check` 命令会**真实调用一次 API 校验密钥有效性**（而非只检查变量非空）：

```bash
python scripts/detect.py check
```

### 使用

```bash
# 图片检测（本地文件或 URL；--face 追加人脸换脸检测）
python scripts/detect.py image ./examples/real_JPEG_example_flower.jpg --face

# 文本检测（直接文字或 txt 文件）
python scripts/detect.py text "今天天气不错，我们出去走走。"
python scripts/detect.py text ./examples/sample_ai_text.txt

# 视频检测（需公网 URL，异步两段式）
python scripts/detect.py video "https://example.com/video.mp4"

# 自动分流（按扩展名自动判断图/文/视频）
python scripts/detect.py auto ./anything.jpg
```

输出示例（图片）——直接透传腾讯云原始字段，无二次加工：

```json
{
  "modality": "image",
  "input": "./examples/real_JPEG_example_flower.jpg",
  "suggestion": "Pass",
  "label": "Normal",
  "score": 9,
  "detail_results": [ "...腾讯云原始各维度详情..." ],
  "request_id": "..."
}
```

字段说明（腾讯云原始定义）：

| 字段 | 含义 |
|------|------|
| `suggestion` | 识别结果：`Block`（大概率 AI 生成）/ `Review`（存疑）/ `Pass`（真实） |
| `label` | 机审标签：`Normal`（正常）/ `GeneratedContentRisk`（AI 生成内容风险）等 |
| `score` | 置信度评分 0-100，分数越高越可能 AI 生成 |

### 作为 Skill 接入智能体

把整个目录放进 WorkBuddy / CodeBuddy 的技能目录（如 `~/.workbuddy-ai/skills/`），agent 会读取 `SKILL.md` 并在对话中触发：

```
用 ai-truth-detective 检测 ./examples/real_JPEG_example_flower.jpg 这张照片是不是 AI 生成的
```

## 目录结构

```
ai-truth-detective/
├── README.md                # 本文件
├── LICENSE                  # MIT 许可证
├── .gitignore               # 忽略 .env / __pycache__ 等
├── .env.example             # 密钥模板（复制为 .env 使用）
├── SKILL.md                 # Skill 说明书（供智能体读取）
├── scripts/
│   ├── detect.py            # 编排器：模态分流 + 云端检测 + 综合判定
│   └── tc_api.py            # 纯标准库 TC3-HMAC-SHA256 客户端 + 真实鉴权校验
├── examples/
│   ├── real_JPEG_example_flower.jpg   # 真实照片示例
│   └── sample_ai_text.txt             # 文本检测示例
├── references/
│   └── api_docs.md          # 各 API 端点、Action、参数速查
└── docs/
    └── screenshots/         # 运行截图
```

## 文档

- [API 速查](references/api_docs.md)：各接口端点、参数、错误码

## 已知边界

- 视频检测是异步两段式，需公网可访问的视频 URL。
- 人脸防护盾只对「含人脸」的内容有意义，风景 / 物体图应跳过。
- 图片建议分辨率 ≥256x256，文本建议 350 字以上，过短影响准召率。

## License

[MIT](LICENSE)

---

## 作者

**LucianaiB**：专注 AI 应用落地与 AI App 设计开发的开发者，代表作品有 DocPilot Qwen、LifeTrace、GeoMind 等。更多项目与联系方式见个人主页 <https://lucianaib2004.github.io>。
