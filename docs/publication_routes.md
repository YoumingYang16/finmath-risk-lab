# FinMath Risk Lab 论文与会议路线核验

核验基准：2026 年 10 月 6 日，香港时区。截止时间保留官网原时区；没有替用户投稿或联系主办方。

**判断：有发展成论文的可能，但 V1 还不能因为代码完整、测试较多就认定已有充分发表贡献。** 它目前是可复现的课程延伸研究。V2 应围绕一个可证伪的问题形成方法评估或基准研究，例如：“波动预测改善何时不能转化为扣费后的对冲改善，估计误差与分布变化如何影响预算约束下的策略选择？”

这只是拟研究问题，不是已经证明的创新。需要文献定位、强基线、独立评价、消融、区间和失败情形来支撑。ECB 参考汇率加假设期权可以研究方法，不能证明真实期权市场上的利润。

| 渠道 | 2026-10-06 状态与主要要求 | 适配判断 |
|---|---|---|
| [SIAM FM27](https://www.siam.org/conferences-events/siam-conferences/fm27/submissions/) | 摘要截止 **2026-12-15 23:59 美东时间**；提交题目与摘要，摘要不超过 1,500 字符（含空格）；需注册并线下展示。会议于 2027-06-15 至 18 在美国 Arlington 举行。 | 优先考虑 poster 或 contributed talk，主题直接覆盖定价、对冲与模型风险。这里申请的是会议展示，不能写成正式会议论文发表。 |
| [IEEE SSCI / CIFEr 2027](https://attend.ieee.org/ssci-2027/submissions/call-for-papers/) | 正式 full/short 截止 9 月 10 日，已过。**Late-breaking / poster 截止 2026-11-01**，页面未注明时区；分别不超过 2 页（含参考）或 250 词。2027-02-14 至 17 在澳洲 Gold Coast 举行。 | 与计算金融、时序与衍生品定价相符。Late-breaking 与 poster **明确不进入 proceedings**；不要把名称里的 paper 当成正式发表。 |
| [ACM ICAIF 主会](https://icaif2026.org/call-for-papers.html) | 2026 主会截止 **2026-08-09 AoE**，已过；8 页总长、双盲、不收附录或补充材料。尚未核验到 2027 官方征稿。 | 升级后若出现明确方法或基准贡献，可作为未来目标。主会录用论文无论 oral/poster 都进入 ACM proceedings，与摘要海报不同。不能预测录用率。 |
| [RAIOps4Fin 2026](https://raiops4fin2026.github.io/ICAIF/) | ICAIF 下属 workshop，截止 **2026-10-12 23:59 AoE**；正文最多 6 页，不含参考和附录；双盲并需出席。至少 5 页的录用论文，经作者同意后可能考虑 CEUR 收录。 | 模型风险验证、审计与实证流程方向有条件适配。不能包装成生产部署案例，也不能把 CEUR 可能收录说成 ICAIF 主会发表。截止很近，不建议为赶时间削弱研究。 |
| [JOSS](https://joss.readthedocs.io/en/latest/submitting.html) | 期刊软件路线，常规接收投稿；当前要求 **超过六个月活跃公开开发历史**、实际研究用途、开放源码和维护实践。 | 本项目目前不满足公开历史门槛。长期维护成可复用研究库后再评估；不能用一次性堆代码或补造提交记录替代。 |
| [SIURO](https://www.siam.org/publications/siam-journals/siam-undergraduate-research-online-siuro/instructions-for-authors/) | 本科研究期刊，英文 PDF 通常约 20 页、3 MB，摘要不超过 250 词。真实项目指导函须证明本科期间研究与学生重要贡献、评估独立工作，并推荐 3 名审稿人。 | 窄而清楚的计算数学研究可以考虑。指导人可来自高校、非学术机构或政府实验室，但必须实际指导研究；当前未核验具备此条件，不能由 AI 充当指导人或补造贡献证明。 |

SSCI 官网的旧 instructions 仍写旧主稿日期，以上延期日期来自新版 CFP；其 2027 short paper 也被标为不进入 proceedings。RAIOps workshop 与主会总页的通知日期有差异，因此此处不承诺通知时间。官网需在实际投稿前再次核验。

**AI 使用与人的贡献必须如实描述。** 本项目的 AI 协助包括研究设计、实现和实验，因此不应写成“仅语言润色”。

- [ACM 当前政策](https://www.acm.org/publications/policies/new-acm-policy-on-authorship)区分研究与写作帮助：影响研究的 AI 使用须在方法中详述，单纯写作帮助不再由一般政策强制披露。其现行文字也见[官方 ACM ISS 作者页](https://iss.acm.org/2026/authors/papers/)。作者仍对内容负责。
- [IEEE](https://open.ieee.org/author-guidelines-for-artificial-intelligence-ai-generated-text/)要求披露生成内容的工具、范围和受影响部分；[SSCI 投稿说明](https://attend.ieee.org/ssci-2027/submissions/instructions/)也明确 AI 文本披露与人类作者实际贡献。
- [JOSS](https://joss.readthedocs.io/en/latest/submitting.html)要求 AI disclosure、真实的人类审核与设计贡献；除翻译外，不允许用 AI 代替作者和编辑/审稿人的对话。
- [SIAM 出版政策](https://epubs.siam.org/artificial-intelligence)要求人类作者能够为研究辩护并承担责任；未找到 FM27 摘要另设的 AI 细则，不能把期刊条款擅自说成它的专属摘要规则。

推荐顺序是：完成有清楚贡献边界的 V2 → 由本人理解、复核并能答辩 → 选择一个适配的 poster / research-in-progress 路径获得反馈 → 再决定正式论文投稿。**会议论文也是论文；期刊没准备好，并不意味着会议一定更容易。** 负结果也可有研究价值，但必须回答一个非显然问题并说明适用范围。

同一研究不要未经核对同时投多个会：SSCI 的 late-breaking、poster 也有并行提交/展示限制；ICAIF 主会禁止同时投其他 archival venues。软件文章与实证文章若分开，应各有明确不同贡献并披露相关稿件。

SIURO 要求不存在另一期刊的同时审理；若有先前会议论文初稿，需要在投稿函及首页脚注说明。真实指导与学生贡献核验完成后，再决定是否缩写为符合该期刊范围的英文稿，不因“本科期刊”标签预测录用。

本文件为只读核验后的咨询记录。官方网页取证中，SSCI 页面由只读 HTTPS 请求取得；ACM 总政策直连被拒绝，采用其索引内容及官方 ACM 会场作者页交叉核对。没有使用第三方截止日期推算表。
