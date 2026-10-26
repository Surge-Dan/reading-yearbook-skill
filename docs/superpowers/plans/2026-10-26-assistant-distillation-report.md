# 年年阅解耦实施计划

批准设计：`docs/superpowers/specs/2026-10-26-assistant-distillation-report-design.md`。基线 `844a49d`。按两项顺序实现、独立复核，最终集成并推送 main。

## Global Constraints

- 助手负责输入与执行；网页负责年度报告、书籍精华和导出，不再要求网页/聊天接力。
- 至少一份有效蒸馏结果才能生成新的真实报告；已有报告仍可打开和导出。书名和正文模式均可计入，示例/失败/只有身份确认不能计入真实门槛。
- 不伪造来源、人物、作者意图、用户亲历、原文金句或年度阅读统计；公开资料与全文覆盖不能混淆。
- 保留原有字体家族、插画、图表主体和缺封面占位；去除彩色背景渐变，统一控件圆角，不新建模型 API。
- 不访问/修改全局模型配置，不重跑私人整书或额外真实模型评测，不提交私人材料、令牌、临时报告或任务缓存。
- Windows PowerShell；文件修改 apply_patch；先写失败测试再实现；每项提交只暂存自己的文件，不 push；root 最终复核后统一 push main。

## Task 1: 助手输入、联合提取与可复用结果包

实现范围：`scripts/ebook_agent.py`, `serve_ebook.py` 的助手私有创建/选择/范围/重试接口，`ebook_pipeline.py`, `ebook_title.py`, 新 `scripts/distillation_result.py`，相应 focused 测试。不得修改读者端 assets、报告 builder/generator、SKILL/README/发布清单；后续 Task 2 负责这些集成。

先读批准设计。允许沿现有 loopback AgentRunner 做私有阶段通道，不新增一套常驻文件worker。助手应通过 CLI 直接创建书名/本地电子书任务，并在聊天中完成同名选择、范围批准、取消/重试；private agent token 不暴露给网页，无任意网页可调用本地路径读取。复用现有身份、路径/符号链接限制、大小、Host/Origin 和租约契约。不强制用户安装新的模型工具。

上传从每批1次理解+5类全文提取改为1次理解+1次联合提取；五类候选均保留类别、扫描覆盖和独立ID，空类需有明确扫描结果。相同 source/rules 身份缓存正确复用，改变提取规则不误用旧五类缓存。现有批量核验、全局覆盖、方法边界/任务演练和 current-agent needs_review 上限保留。预算估算反映实际新阶段，后续动态批次仍需确认；不虚报固定整体节省比例。

新增接口 `make_bundle(analysis, document, digest='')`, `validate_bundle(bundle)`, `load_bundle(path)`，输出包格式遵循设计。make_bundle 在原文/公开资料元素上核验基础内容、可追溯来源和新阅读字段；不接受空分析、只有书籍身份、错误引用或不匹配source_hash。可用结果不等于独立语义验证，needs_review 可保留；上传与书名分别保留覆盖界限。validate_bundle/load_bundle 对已发布包验证结构和完整性；拒绝无效/篡改包，不能只看一个 ready 布尔值。

所有通过的正式 title/upload 管线原子发布 distillation.json，旧失败/取消/重试不能遗留 active 成功包。包不包含整书、令牌或私有审计。保留现有 analysis 兼容字段；可选新增 reading_lenses:[{id,kind:values|tone|tension|connections,title,text,sources}]、memorable_passages:[{text,why_it_matters,sources}]。这些字段要在分析请求、确定性来源检查、Markdown输出中真正使用，不只是 schema 声明。金句 text 逐字来自对应原文元素；书名模式的 secondary/source_notes 不冒充原书金句。文学书不凑方法，价值观/底色是有依据的解读，不能臆测意图。

TDD：联合提取扫描/类别/跨批ID、坏引用/漏块、动态预算、旧缓存兼容、两模式成功包/失败归档、包篡改/模式/身份、阅读视角和金句来源、助手创建/选择/批准不借助网页。只用短篇受控fixture/fake runner，不做真实模型调用。

测试后自查并提交自己的实现与测试；报告写 `.superpowers/sdd/20261026-task-1-report.md`，包含先红后绿命令/结果、接口、文件清单和风险。更新报告后返回简短状态与commit；不得 push 或修 unrelated tests。

## Task 2: 报告前置门、静态阅读区与文档

依赖 Task 1 的 `distillation_result` 接口及结果包实际实现，先读其接口说明和批准设计。范围：`scripts/build_reading_html.py`, `generate_reading_html.py`, `serve_ebook.py` 的读者页面组装（不要改 Task1 私有API契约）, assets/ebook-app.js/css/section.html、reading-app.css/reading-art.css 必要局部、新可复用report reader模块、SKILL.md及相关references/README、focused tests。发布清单由root集成时更新。

真实 build_html/deliver/main 生成报告前必须调用共享验证器确认 data.distillations 至少有一份有效真实包；CLI 提供可重复 --distillation <distillation.json> 输入，不仅靠文字引导。无有效包在采集或写目标文件前返回可操作的“先蒸馏至少一本”，不覆盖已有正式报告，不创建空报告；样例 source_mode=sample 可独立构建但不得给真实结果增加示例入口。测试fixture以真实 make_bundle 生成有效受控包，不关闭校验逃避回归。

报告实际内嵌 validated bundles 的公开analysis/digest数据，HTML script按现有安全转义，不能带全文/私有路径/token；年度阅读统计不受蒸馏书目增加影响。底部书籍精华支持多本选择，默认展示第一本；复制、Markdown、独立HTML及PNG/ZIP使用当前所选同一结果。不能只有数量通过门却不展示结果。旧报告可继续打开，legacy 工作台开发模式可保留但不能再是默认用户路径。

读者入口无上传、执行入口、复制启动指令、任务轮询或模型连接提示。复用现有 renderer 而非重写分享算法；新增只读模式初始化和多书切换，保证离线报告没有 /api/jobs 或 /api/state 请求，无任务控件空节点报错。serve_ebook --yearbook 默认展示只读页面且不触发处理；助手私有服务仍可经 Task1 CLI创建，读者页面不获取 agent token。

新 reading_lenses 和 memorable_passages 在网页/复制/导出同样呈现，有内容才出现。自然表达如“这本书在意什么”“书中透露出的底色”“值得保留的金句”“读完想试的一件事”，不机械改写所有书籍成同一套标题。原文金句不加作者未说过的话，页尾保留来源边界。已生成原结果兼容阅读，不伪造新内容。

UI仅去掉body和paper的彩色渐变，单一纸色/中性外背景；输入/按钮约8px、卡片约12px，去任务/上下文的引用式左边线；保留原始引文内容表达、原字体家族和图表插画。不要重新设计全年年报或换字体。

更新 SKILL 路由、distillation-method、html-yearbook、book-reading-writing 与 README，默认顺序为“助手蒸馏一本→再加一本或生成报告→网页阅读导出”；给足宿主能力、书名资料边界、高成本确认、身份和失败恢复的操作说明。增加短小方法/质量比较说明，按批准设计说明优化和未验证项，不宣称已超过上游。老设计文档保留历史，不让新主路由继续指向网页提交。

TDD：0包/坏包/示例混入真实/单包/多包报告、无覆盖旧文件、CLI前置门无采集、JSON注入、legacy可读、新只读页面无网络、双书切换/复制/分享、375px布局。更新受影响旧测试，不降低安全、来源和统计口径断言。fixture验证不称真实书籍效果评测。先focused后相关回归。

提交自己的实现/测试/文档，报告 `.superpowers/sdd/20261026-task-2-report.md`；不得 push/private数据或重跑私人整书。

## 最终集成（root）

各任务独立复核通过后，检查全局接口、资源和隐私；更新发布清单。运行受影响Python回归及浏览器只读/多书/导出测试，做一份明确标记的短篇受控内容展示，不伪装用户书籍。已有私人年报只复用并打开，不为预览而绕过新报告门，也不拿未完成的《深度关系》凑成功结果。若无真实有效包，保留旧年报，只提供明确标记的功能测试预览。

只要用户许可的质量/费用边界未改变就持续推进。最终检查 git fetch/ancestor、explicit staging、diff check、密钥扫描、commit/push origin HEAD:main，并核对远端SHA。结束时准确说明工程测试、真实内容测评和长书任务的区别。
