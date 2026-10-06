# V2 文献近邻与贡献边界

检索日期：2026-10-06（香港时间）。这是针对项目研究问题的一手文献核验，不是穷尽检索，也不构成新颖性认证。预印本状态与期刊年份分开记录。以下内容来自论文摘要和所注明的方法段，不表示已经逐篇完整复现。

## L01 Using a Financial Training Criterion Rather than a Prediction Criterion

Yoshua Bengio，1997。[原始来源](https://doi.org/10.1142/S0129065797000422)；[作者或机构全文](https://www.iro.umontreal.ca/~lisa/pointeurs/bengioy_TR1019.pdf)。



- 已有工作：将模型直接按金融决策损益（包含交易成本）训练，而不是只按预测误差训练，已有早期实证先例。
- 对本项目的含义：不得将金融目标优于纯预测目标的思想称为本项目首创；此文是一般决策导向动机，不是当前期权协议的同一方法。
- 核验范围：核验作者版搜索索引与出版信息；作者PDF直接打开有访问保护。

## L02 An Asymptotic Analysis of an Optimal Hedging Model for Option Pricing with Transaction Costs

A. Elizabeth Whalley、Paul Wilmott，1997。[原始来源](https://doi.org/10.1111/1467-9965.00034)。



- 已有工作：通过小交易成本渐近分析研究效用对冲，得到涉及gamma的近似策略与无交易区间。
- 对本项目的含义：gamma相关带宽并非原创。项目constant-width band是强执行基线，不是该文最优渐近带宽的完整复现。
- 核验范围：出版社摘要与正式卷期年份核验；页面online date不替代1997卷期。

## L03 Optimal Hedging of Options with Small but Arbitrary Transaction Cost Structure

A. Elizabeth Whalley、Paul Wilmott，1999。[原始来源](https://users.ox.ac.uk/~ofrcinfo/file_links/mf_papers/1999mf09.pdf)。



- 已有工作：比例成本下越过无交易区间后交易到边界；固定成本下可能交易到区间内部。
- 对本项目的含义：V2新增trade-to-boundary，明确区别于V1超过阈值回到目标delta；该结构属于文献基础，不是新算法。
- 核验范围：Oxford机构托管原文，摘要检索可读，部分全文字体编码不利于文字提取。

## L04 The Economic Value of Using Realized Volatility in Forecasting Future Implied Volatility

Wing Hong Chan、Ranjini Jha，2009。[原始来源](https://doi.org/10.1111/j.1475-6803.2009.01249.x)。



- 已有工作：预测和期权定价方面的改善，在交易成本存在时没有自动转化为显著交易及对冲经济收益。
- 对本项目的含义：预测准确不保证对冲改善有直接先例；本项目应回答有限样本、期限对齐与选择规则具体何时失效。
- 核验范围：出版社原始摘要与文章信息。

## L05 Deep Hedging

Hans Bühler、Lukas Gonon、Josef Teichmann、Ben Wood，2018。[原始来源](https://arxiv.org/abs/1802.03042)。

2018作者预印本；文献常以2019期刊版本引用。

- 已有工作：在交易成本等市场摩擦下学习对冲策略，优化凸风险度量，并给出Heston合成市场实验。
- 对本项目的含义：神经网络、CVaR、Heston或摩擦下直接对冲均不能单独作为本项目创新声明。当前V2没有声称复现完整deep hedging。
- 核验范围：作者arXiv摘要与版本记录。

## L06 No-Transaction Band Network: A Neural Network Architecture for Efficient Deep Hedging

Shota Imaki、Kentaro Imajo、Katsuya Ito、Kentaro Minami、Kei Nakagawa，2021。[原始来源](https://arxiv.org/abs/2103.01775)。

2021预印本，arXiv链接期刊DOI 10.3905/jfds.2023.1.125。

- 已有工作：学习无交易区间的网络结构，研究欧洲及回望期权，并给出相应理论和数值表现。
- 对本项目的含义：学习区间、使用clamp或减少交易并非新颖贡献。constant-width band是其中思想的简单基线，不等价于论文网络。
- 核验范围：作者arXiv摘要与关联DOI。

## L07 Smart “Predict, then Optimize”

Adam N. Elmachtoub、Paul Grigas，2017。[原始来源](https://arxiv.org/abs/1710.08005)。

2017初稿，2020 arXiv修订；引用此处的作者版本。

- 已有工作：用下游优化问题定义SPO损失，提出SPO+凸替代，分析一致性并展示优化应用。
- 对本项目的含义：本项目借鉴预测与决策目标不同这一动机。路径对冲不直接满足文中线性目标框架，不能套用其理论保证或称当前网格选择为SPO+训练。
- 核验范围：作者arXiv摘要与版本记录。

## L08 Robust Hedging GANs

Yannick Limmer、Blanka Horvath，2023。[原始来源](https://arxiv.org/abs/2307.02310)。

原预印本标题；关联期刊版本为Robust Hedging GANs: Towards Automated Robustification of Hedging Strategies。

- 已有工作：将深度对冲与对抗模型生成结合，针对数据生成机制误设和估计误差处理模型风险。
- 对本项目的含义：模型不确定性下对冲有直接先例。V2压力测试没有训练对抗生成器，也不应称为实现该论文。
- 核验范围：作者arXiv摘要与关联出版DOI。

## L09 Bridging Stochastic Control and Deep Hedging: Structural Priors for No-Transaction Band Networks

Jules Arzel、Noureddine Lehdili，2026。[原始来源](https://arxiv.org/abs/2603.29994)。

2026-03-31预印本，不据此宣称已经同行评审。

- 已有工作：研究delta居中、Whalley–Wilmott带宽先验及soft clamp，比较跨交易成本条件的泛化。
- 对本项目的含义：即使以后加入gamma/cost-aware神经带宽，也必须对照此直接近邻，不能因新增该模块就声称原创架构。
- 核验范围：arXiv原文摘要与提交记录。

## L10 Rethinking Synthetic Scenario Realism: Compatibility, Not Fidelity, Drives Hedging Performance

Ryuji Hashimoto、Masanori Hirano、Ryota Ozaki、Kentaro Imajo，2026。[原始来源](https://arxiv.org/abs/2608.20842)。

2026-08-21初稿，2026-09-04修订预印本。

- 已有工作：提出生成器与对冲任务的compatibility，讨论统计逼真与下游对冲质量的分离，给出学习误差与compatibility gap分解。
- 对本项目的含义：统计模型好不等于决策好及生成分布偏移本身已有近邻；V2贡献边界在特定有限样本选模与期限对齐的可重复经验研究。
- 核验范围：arXiv原文摘要与提交记录。

## L11 A Comparison of Biased Simulation Schemes for Stochastic Volatility Models

Roger Lord、Remmert Koekkoek、Dick van Dijk，2010。[原始来源](https://doi.org/10.1080/14697680802392496)；[作者或机构全文](https://papers.tinbergen.nl/06046.pdf)。

2010期刊版本；机构工作论文页面内容标明2008-02-06修订。

- 已有工作：比较随机波动率Euler修正方案；full truncation对漂移和扩散中的方差取正部，但保留内部原始负方差状态，并明确讨论离散偏差。
- 对本项目的含义：V2 Heston模拟遵循此full-truncation结构加log-Euler spot；通过细网格敏感性诊断离散误差，不能称exact Heston simulator。
- 核验范围：Tinbergen机构原文方法段及Erasmus作者机构书目。

## 可申明的研究定位

V1 是有完整代码、账本与实验的课程延伸计算项目，其基础组件和“预测更好不保证对冲更好”的一般命题已有明确先例。V2 收窄为期限对齐、有限样本选择目标及分布偏移的可重复经验研究，并提供可解释CVaR对冲比较器。它不声称发明期权对冲、无交易区间、CVaR线性规划、SPO+或鲁棒深度对冲。

最有价值的问题是：当验证数据有限时，按下游损失联合选择模型和执行策略是否比先按预测损失选模可靠；收益是否随数据量、成本与分布偏移而变化；期限匹配是否影响结论。这些问题必须由真实结果回答，不能预设复杂方法获胜。

V2 模拟使用每场景24次独立校准／验证／测试重复；主比较只有一项，其他区间是探索性点对点结果。参考最优来自独立大样本但仍有Monte Carlo误差，且仅限同一有限候选集合。历史2021–2025结果已在V1被查看，因此回溯评价不再被称作从未接触的确认性测试。

## 尚未解决的发表条件

论文机会取决于相对最近邻文献的具体新增认识、结果稳定性、论证质量及外部技术评审。更多算法、更多代码或整洁网页不会自动形成学术贡献。当前工作适合作为研究稿与复现材料；不得写成已发表、已被录用或保证达到某会议／期刊门槛。

