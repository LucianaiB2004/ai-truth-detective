# 腾讯云 AI 生成内容识别 API 速查

本 skill 的云端检测层全部用**纯标准库 TC3-HMAC-SHA256 签名**直接调用，
不依赖 tencentcloud-sdk-python。下面是各接口的端点 / Action / 版本 / 关键参数。

## 通用凭证

- `TENCENTCLOUD_SECRET_ID` / `TENCENTCLOUD_SECRET_KEY`（内容安全 + 人脸防护盾共用）
- `TENCENTCLOUD_TOKEN`（可选，临时密钥 STS）
- 图片/视频/文本识别还需要各自的**审核策略号 BizType**（内容安全控制台获取）
- VITA 需要独立 API Key：`TENCENTCLOUD_VITA_API_KEY`

## 图片 AI 生成识别

- 端点：`ims.tencentcloudapi.com`（服务名 ims）
- Action：`ImageModeration`，Version `2020-12-29`
- 关键参数：`Type=IMAGE_AIGC`，`FileUrl`（URL）或 `FileContent`（base64），`BizType`
- 返回：`Suggestion`(Pass/Review/Block)、`Label`、`Score`、`LabelResults`
- 限制：图片 ≤ 5MB，支持 png/jpg/jpeg/bmp/gif/webp

## 文本 AI 生成识别

- 端点：`tms.tencentcloudapi.com`（服务名 tms）
- Action：`TextModeration`，Version `2020-12-29`
- 关键参数：`Type=TEXT_AIGC`，`Content`（UTF-8 base64），`BizType`
- 返回：`Suggestion`、`Label`、`Score`、`Keywords`、`DetailResults`
- 限制：≤ 10000 个 Unicode 字符

## 视频 AI 生成识别（异步两段式）

- 端点：`vm.tencentcloudapi.com`（服务名 vm）
- 第一步 Action：`CreateVideoModerationTask`，Version `2021-09-22`
  - 参数：`Type=VIDEO_AIGC`、`Tasks[].Input={Url, Type:"URL"}`、`BizType`
  - 返回：`Results[].TaskId`
- 第二步 Action：`DescribeTaskDetail`，Version `2021-09-22`
  - 参数：`TaskId`
  - 返回：`Status`(PENDING/RUNNING/FINISH/ERROR/CANCELLED)、`Suggestion`、`ImageSegments`（抽帧结果）

## AI 人脸防护盾

- 端点：`faceid.tencentcloudapi.com`（服务名 faceid）
- Action：`DetectAIFakeFaces`，Version `2018-03-01`
- 关键参数：`FaceInput`（base64）、`FaceInputType`（1=图片 / 2=视频）
- 返回：`AttackRiskLevel`(Low/Mid/High)、`AttackRiskDetailInfos`、`FaceDetailInfos`
- 限制：图片建议 ≤ 3MB（最大 10MB），视频建议 ≤ 8MB（最大 10MB）

## VITA 多模态理解（交叉验证）

- Base URL：`https://api.vita.cloud.tencent.com/v1/video2text`
- 模型：`youtu-vita`，OpenAI 兼容协议
- 独立 Key：`TENCENTCLOUD_VITA_API_KEY`
- 用途：把图片交给 VITA，让它找"物理破绽"（手指数量、光影方向、透视、文字乱码）

## 签名要点（TC3-HMAC-SHA256）

1. 规范请求串：`POST\n/\n\ncontent-type:...\nhost:...\nx-tc-action:...\ncontent-type;host;x-tc-action\n{payload_sha256}`
2. 待签串：`TC3-HMAC-SHA256\n{timestamp}\n{date}/{service}/tc3_request\n{canonical_sha256}`
3. 派生密钥：`TC3{secretKey}` → HMAC(date) → HMAC(service) → HMAC(tc3_request)
4. 请求头：Authorization / Content-Type / Host / X-TC-Action / X-TC-Timestamp / X-TC-Version（/ X-TC-Region）
