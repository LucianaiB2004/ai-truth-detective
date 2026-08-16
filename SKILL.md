---
name: ai-truth-detective
description: AI 打假侦探——调用腾讯云 AI 生成识别能力，检测图片/视频/文本是否由 AI 生成、是否 AI 换脸，输出「人机验真报告」。当用户想辨别"这是真人/实拍还是 AI 生成"、检测 AI 换脸或深度伪造、鉴别 AI 代写文本、给数字内容做真实性核验时使用。基于腾讯云图片/视频/文本 AI 生成识别 + AI 人脸防护盾 + VITA 多模态交叉验证。
---

# AI 打假侦探（ai-truth-detective）

调用腾讯云真实 AI 生成识别接口，对任意图片 / 视频 / 文本判断"是人做的，还是 AI 生成的"，并输出结构化验真报告。

## 能力与防线

| 层 | 能力 | 腾讯云 API |
|----|------|-----------|
| 模态分流 | 自动识别输入是图/视频/文本 | 本地逻辑 |
| 图片检测 | AI 生成图片识别 + 可选人脸换脸防护 | ims ImageModeration(IMAGE_AIGC) + faceid DetectAIFakeFaces |
| 视频检测 | AI 生成视频识别（异步两段式） | vm CreateVideoModerationTask / DescribeTaskDetail |
| 文本检测 | AI 生成文本识别 | tms TextModeration(TEXT_AIGC) |
| 交叉验证 | VITA 多模态找"物理破绽"（手指/光影/透视/文字乱码） | VITA youtu-vita |

## 使用方式

先进入本 skill 的 scripts 目录，再按模态调用：

```bash
# 图片（本地或 URL），--face 追加人脸换脸检测，--vita 追加交叉验证
python detect.py image ./photo.jpg --face --vita

# 文本（直接文本或 txt 文件路径）
python detect.py text "今天天气不错，我们出去走走。"

# 视频（URL，云端异步两段式）
python detect.py video "https://example.com/v.mp4"

# 自动分流
python detect.py auto ./anything.jpg

# 检查配置就绪状态
python detect.py check
```

## 前置要求

所有检测都走腾讯云真实 API，需要先配置密钥。把 `.env.example` 复制为 `.env` 并填入，或直接设置环境变量：

```bash
export TENCENTCLOUD_SECRET_ID="your_secret_id"
export TENCENTCLOUD_SECRET_KEY="your_secret_key"
export TENCENTCLOUD_AIGC_RECOG_IMAGE_BIZ_TYPE="..."   # 图片识别策略号
export TENCENTCLOUD_AIGC_RECOG_VIDEO_BIZ_TYPE="..."   # 视频识别策略号
export TENCENTCLOUD_AIGC_RECOG_TEXT_BIZ_TYPE="..."    # 文本识别策略号
export TENCENTCLOUD_VITA_API_KEY="..."                # VITA 交叉验证（可选）
```

## 文件结构

```
ai-truth-detective/
├── SKILL.md
├── .env.example      # 密钥环境变量模板
├── scripts/
│   ├── detect.py       # 编排器：模态分流 + 真实云端检测 + 综合判定
│   └── tc_api.py       # 纯标准库 TC3-HMAC-SHA256 客户端（零 SDK 依赖）
├── examples/
│   └── real_JPEG_example_flower.jpg   # 真实照片样本
└── references/
    └── api_docs.md     # 各 API 端点、Action、参数速查
```

## 已知边界

- 视频检测是异步两段式（创建任务→轮询），需公网可访问的视频 URL。
- 人脸防护盾只对「含人脸」的内容有意义，风景/物体图应跳过。
- 图片 AI 识别建议分辨率不低于 256x256；文本识别建议 350 字以上，过短影响准召率。
