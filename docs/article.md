# 眼见不为实：我用腾讯云 4 个 AI Skill 在 WorkBuddy 里造了一个「AI 打假侦探」

> 朋友圈的"精修图"、群里转的"换脸视频"、网上的"深度好文"——到底是不是 AI 做的？本文记录我如何把腾讯云图片/视频/文本 AI 生成识别 + AI 人脸防护盾四个 Skill 串成一个「内容验真」智能体，在 WorkBuddy 里跑通**真实的云端检测全链路**。

## 前言：一次"反着来"的尝试

研究腾讯云这批 AI Skills 的时候，我注意到官方推荐的方向几乎都是"正向识别"——OCR 帮你读懂文档、ASR 帮你听懂声音、人脸核身帮你确认"这是本人"。

但我更想做一个"反向"的东西：**识假**。

"是不是 AI 生成"这件事，在 2026 年已经不是技术圈的自嗨。AI 换脸诈骗上过无数次新闻，电商平台开始强制要求 AI 内容打标。可普通人手里没有工具——他们只能靠肉眼猜。

于是我决定：用腾讯云现成的 AI Skills，造一个能真实调用的"AI 打假侦探"。输入一张图、一段视频、一篇文章，它真实地调腾讯云 API，告诉你：**这是人做的，还是 AI 做的，证据是什么。**

## 一、我为什么选这几个 Skill

活动给的 Skills 矩阵里有五个大类，我盯上了其中最冷门、最少人碰的一组：

- `tencentcloud-aigc-recog-image`：检测图片是不是 SD / Midjourney / GPT-4o 生成的
- `tencentcloud-aigc-recog-video`：检测视频是不是 Veo3 / 混元 / 即梦 / 海螺生成的
- `tencentcloud-aigc-recog-text`：鉴别文本是不是 AI 代写
- `tencentcloud-faceid-detectaifakefaces`：AI 人脸防护盾，识别 AIGC 换脸、高清翻拍

选它们的理由很朴素：**这几个能力恰好覆盖了一个人"看到的内容"的全部形态**。图片、视频、文本是三种输入，换脸是人脸这个子集里最危险的一类——四个 Skill 拼起来就是一张完整的"验真网"。而且这个方向几乎没有人在做，"内容验真"是空着的，对想拿"角度新颖"分的作品来说是个好位置。

## 二、技术底座：Skill 负责感知，WorkBuddy 负责编排

感知层是四个腾讯云能力：

| Skill | API | 作用 |
|-------|-----|------|
| aigc-recog-image | ims ImageModeration (IMAGE_AIGC) | 图片是否 AI 生成 |
| aigc-recog-video | vm CreateVideoModerationTask / DescribeTaskDetail | 视频是否 AI 生成（异步两段式） |
| aigc-recog-text | tms TextModeration (TEXT_AIGC) | 文本是否 AI 生成 |
| detectaifakefaces | faceid DetectAIFakeFaces | 人脸是否换脸/翻拍 |

执行层落在 WorkBuddy。它作为智能体运行时，负责接收用户丢进来的内容、按模态分流、调度检测脚本、把各层结果汇总成统一的「人机验真报告」。

一个值得专门说明的设计决策：这些官方 Skill 都依赖 `tencentcloud-sdk-python`（几十兆的 SDK）。而我想要一个**零依赖**的包，所以用 Python 标准库手写了 TC3-HMAC-SHA256 签名，直接调腾讯云 API，`pip install` 都不用。代价是我得自己抠签名的每一步（下面有踩坑），好处是任何一台有 Python 的机器都能跑。

## 三、链路设计：四层防线，而不是堆四个 API

把四个 Skill 拼起来不难，难的是拼得"有道理"：

```
输入（图片/视频/文本）
  → ① 模态分流：自动判断是图、视频还是文本
  → ② 云端检测：图片走 ims、视频走 vm（异步两段式）、文本走 tms
        └─ 图片含人脸时，追加 faceid 换脸检测
  → ③ VITA 交叉验证（可选）：多模态模型找"物理破绽"（手指/光影/透视/文字乱码）
  → ④ 透传结果：原样返回腾讯云的 suggestion/label/score 等原始字段，不做二次加工
```

每个环节都是**真实的云端 API 调用**。没有本地启发式、没有 mock——要测就真刀真枪地测。

## 四、制作过程：从 SKILL.md 到能跑的包

整个 skill 的结构如下：

```
ai-truth-detective/
├── SKILL.md              # 技能说明书：触发词、防线说明、用法
├── .env.example          # 密钥环境变量模板
├── scripts/
│   ├── detect.py         # 编排器：模态分流 + 真实云端检测 + 综合判定
│   └── tc_api.py         # 纯标准库 TC3-HMAC-SHA256 客户端（零 SDK）
├── examples/
│   └── real_JPEG_example_flower.jpg   # 真实照片样本
└── references/
    └── api_docs.md       # 各 API 端点、Action、参数速查
```

第一步是写 `SKILL.md`，frontmatter 里的 `description` 尤其重要——WorkBuddy 靠它决定"什么时候触发这个 skill"。

第二步是落地代码。`tc_api.py` 里我对着腾讯云签名 v3 规范一步步实现：规范请求串 → 待签字符串 → 派生密钥 → Authorization 头。这里有个真实的坑——**签名里的服务名（service）必须用产品代号**，图片是 `ims`、文本是 `tms`、视频是 `vm`、人脸是 `faceid`，写错一个字母，返回的就是 HTTP 200 但业务码完全对不上。

第三步是让 `check` 命令不仅能查"变量配没配"，还能**真实地验一次密钥**（下面第七节会讲为什么这一步是必须的）。

## 五、在 WorkBuddy 中安装与调用

把 `ai-truth-detective/` 放进 WorkBuddy 的技能目录（`~/.workbuddy-ai/skills/`），agent 扫到 `SKILL.md` 后就会把它纳入可用技能。然后在对话里说一句：

```
用 ai-truth-detective 检测 ai-truth-detective/examples/real_JPEG_example_flower.jpg 这张照片是不是 AI 生成的
```

agent 就会匹配到 skill，读取 SKILL.md，执行 `detect.py image`，真实调用腾讯云 API。

> 【截图占位 1：在 WorkBuddy 对话中输入检测指令，agent 开始处理】

## 六、真实运行验证：agent 的完整回答

下面是我在 WorkBuddy 里让 agent 跑的一次真实检测，agent 的完整验真结论：

> **`real_JPEG_example_flower.jpg` 是真实照片（实拍/人工），不是 AI 生成的。**
>
> | 项目 | 结果 |
> |------|------|
> | 模态 | 图片 |
> | 识别结果 Suggestion | `Pass`（未检测出明显 AI 生成特征，判定为真实拍摄） |
> | 机审标签 Label | `Normal` |
> | 置信度评分 Score | 9（0-100，分数越高越可能 AI 生成；9 分很低，判为真实） |
> | 各维度命中 | 色情/暴恐/违法/未成年 全部 `HitFlag=0`、`Suggestion=Pass` |
> | 人脸换脸 | 未检测（风景花卉图，无人脸，按 skill 规则跳过） |

腾讯云 AIGC 识别所有场景均未命中 AI 生成痕迹，判定为正常真实内容，与文件名 `real_...` 一致。

> 【截图占位 2：agent 的完整验真报告】
> 【截图占位 3：终端 `detect.py check` 的真实鉴权校验输出】

**更可贵的是，agent 在第一次运行时还替我抓出了一个环境问题**（第七节第 5、6 条），这正是"让 agent 真跑一遍"比"自己看代码"多出来的价值——它是在真实调用里把坑踩出来的。

### 不止图片：图片 / 文本 / 视频三种模态都支持

这个 skill 不只是能看图片，它把「一个人能看到的内容」的三种形态都覆盖了，而且**每种都是真实调用腾讯云 API**：

| 模态 | 命令 | 真实调用的腾讯云接口 |
|------|------|----------------------|
| 图片 | `detect.py image <图>` | ims ImageModeration (IMAGE_AIGC) + 可选 faceid 换脸检测 |
| 文本 | `detect.py text <文字或txt文件>` | tms TextModeration (TEXT_AIGC) |
| 视频 | `detect.py video <视频URL>` | vm CreateVideoModerationTask → DescribeTaskDetail（异步两段式） |

在 WorkBuddy 里，对应三种提示词：

```
# 图片
用 ai-truth-detective 检测 ai-truth-detective/examples/xxx.jpg 这张照片是不是 AI 生成的
# 文本
用 ai-truth-detective 检测 ai-truth-detective/examples/xxx.txt 这段文字是不是 AI 生成的
# 视频
用 ai-truth-detective 检测 https://example.com/video.mp4 这个视频是不是 AI 生成的
```

> 【待补充：三种模态的正例实测——①AI 生成图（混元生图/即梦生成）应判 `AI_GENERATED`；②AI 生成文本（如 AI 代写的文章）应判 `AI_GENERATED`；③AI 生成视频应判 `AI_GENERATED`。与上面真实照片的 `REAL` 形成对照】

## 七、踩过的坑与取舍

1. **手写签名，怎么自证没写错？** 我为了零依赖自己实现 TC3-HMAC-SHA256 签名。第一次连云端报 `AuthFailure.SignatureFailure`，第一反应是"我签名写错了"。但我没瞎猜，而是**装官方 SDK 用同一对密钥做同一次调用**——结果 SDK 也报一模一样的错，这就把"我的签名"和"密钥本身"两个变量分开了。最后定位到是密钥错了。为了彻底杜绝"是不是我签名不标准"的怀疑，我又把签名头和 canonical_request 改成与官方 SDK 完全一致，直接调 SDK 的 `Sign.sign_tc3` 做**字节级比对**，两边 Signature 一模一样。教训：**排错第一步不是改代码，是先把"谁的锅"用最小实验分清楚。**

2. **SecretKey 只有 32 位，还只能"创建时看一次"**。我第一版的 SecretKey 复制成了 33 位（把 `0/O`、`1/l/I` 看混了），签名一直过不了。更坑的是腾讯云从 2023 年 11 月 30 日起**关闭了查询 SecretKey 的功能**，SecretKey 只在新建密钥那一刻显示一次，事后永远无法回看——最后只能新建一个密钥、下载 `SecretKey.csv` 才拿到正确值。教训：**新建密钥时当场保存好（最好下载 CSV），别指望事后能查。**

3. **云端服务要"单独开通"**。图片 AI 识别服务不主动开通，直接报 `UnauthorizedOperation`（未开通权限/无有效套餐包）。开通后才正常返回结果。

4. **签名通过 ≠ 检测命中有意义**。图片识别建议分辨率 ≥256x256，文本识别建议 350 字以上，过短影响准召率。拿玩具样本去测，得到的就是玩具结论。

5. **`.env` 和系统环境变量会打架**。这一条是 agent 在真实运行里发现的：我的脚本一开始写的是"环境变量已存在就不读 .env"，结果**系统环境变量里恰好有一组已失效的腾讯云密钥**，把 .env 里那组有效密钥给覆盖了，第一次调用直接报 `AuthFailure.SecretIdNotFound`。agent 手动用 .env 的值覆盖才跑通。我后来把加载逻辑改成了「**.env 优先**」——skill 的 .env 是显式配置，用户写了就该生效。教训：**配置文件和环境变量的优先级要想清楚，别让一个陈旧的全局变量悄悄坑掉你。**

6. **`check` 命令的"假阳性"**。原来的 `check` 只检查变量"非空"就报 ready，并不真验证密钥有效性——所以上面第 5 条那种情况，`check` 明明显示就绪，实际一调就失败。我后来给 `check` 加了一条**真实鉴权校验**：用一张 1x1 最小图片真实调一次 ims，能区分"鉴权失败"（`AuthFailure*`）和"鉴权通过但业务另有问题"（如 `InvalidParameter`）。教训：**"配好了"和"能用了"是两件事，前者是静态检查，后者必须真调一次。**

## 八、写在最后

回看这个「AI 打假侦探」，它没有发明任何新算法，用的全是腾讯云现成的 Skill。它的价值在于把"识假"这个反直觉的需求，落成了一个真实可调用的多 Skill 协同链路，并且把签名、密钥、服务开通、环境变量优先级这些真实世界里的坑一个个踩平了。

对普通用户来说，它是一把"眼见不一定为实"的尺子；对开发者来说，它是一个范式样本——**当腾讯云 AI Skills 提供感知、WorkBuddy 提供编排，两者之间的缝隙，正好是创新最值得下针的地方。**

而对我自己来说，这次最大的收获是一个朴素的判断：**技术的"最佳实践"，不在于堆了多少能力，而在于敢不敢真调一次 API、真踩一遍坑，然后把踩坑的过程诚实地写下来。**
