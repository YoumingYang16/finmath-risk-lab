"""Build the explicit UNION of relevant competencies; keep external requirements visible."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROGRAMS=[
('CUHK_DSBS','香港中文大学 DSBS','https://dsbs.cuhk.edu.hk/programme-details/',
 ['统计推断','金融时间序列','Monte Carlo','Python金融风险分析','研究报告'],
 '课程含 STAT5101/5106、STAT6104、RMSC6007；培养内容不是全部入学硬门槛。'),
('CMU_BIDA','CMU MISM BIDA','https://www.heinz.cmu.edu/programs/information-systems-management-master/bida',
 ['计量与统计','不确定性决策','数据库与软件','金融分析','沟通与管理'],
 '数学、统计、编程的正式先修及学分成绩需独立核验；项目不能替代。'),
('HKU_FC','香港大学 CS Financial Computing','https://master.cds.hku.hk/msccs/msc-in-computer-science-stream-financial-computing/',
 ['衍生品计算','金融数学','定量软件设计'],
 'FITE7405/7406为具体课程连接；课程先修不等于整个项目统一招生要求。'),
('BERKELEY','UC Berkeley Master of Analytics','https://graduate.catalog.berkeley.edu/programs/162G4ANLTG',
 ['统计','优化','仿真','风险管理','业务决策'],
 '本科概率或统计、线代和编程准备需成绩等证明；额外写作样本不审阅。'),
('PENN_SE','Penn MSE Systems Engineering','https://www.ese.upenn.edu/academics/masters/systems-engineering-program/mse-in-se-degree-requirements/',
 ['系统建模','仿真','概率计算','优化','金融应用'],
 '课程分数据科学、系统建模、系统设计与优化；应用领域有金融。'),
('PENN_DSAI','Penn MSE Data Science and Artificial Intelligence','https://dsai.engineering.upenn.edu/curriculum/',
 ['统计','机器学习','算法','数据系统','负责地使用模型'],
 '外部申请要求相当于CS辅修的课程与数学统计能力；未将4+1校内GPA要求套用外部申请。'),
('NTU_DS','NTU MSc Data Science','https://www.ntu.edu.sg/spms/admissions/grad/detail/master-of-science-in-data-science-%28msds%29',
 ['数学准备','数据准备','建模','解释与可视化','跨学科应用'],
 '官方背景为相关计算学科及扎实数学训练；全数据流程与Capstone是培养重点。'),
('IMPERIAL','Imperial Applied Computational Science and Engineering','https://www.imperial.ac.uk/study/courses/postgraduate-taught/applied-computational-science/',
 ['数值方法','计算数学','软件验证','并行计算','技术报告'],
 '数值计算和项目方法可迁移；本研究不构成大型集群或自然科学领域经验。'),
('HARVARD','Harvard SM Health Data Science','https://hsph.harvard.edu/program/sm-health-data-science/',
 ['统计推断','计算与机器学习','模型评价','健康科学兴趣','结果沟通'],
 '当前SM-80；多元积分、线代和R/Python等准备及健康兴趣须独立证明。'),
('YALE','Yale MPH Biostatistics','https://ysph.yale.edu/school-of-public-health/graduate-programs/master-of-public-health-mph-degree/biostatistics/',
 ['概率统计','应用研究','生物统计','公共卫生实践','合作沟通'],
 '此处是MPH不是MS；多元微积分和线代B以上、公共卫生动机等须独立证据。'),
]
ALL=[p[0] for p in PROGRAMS]
ITEMS=[
('C01','问题定义与研究设计','提出一个可检验的研究问题，事先确定目标和对照。',ALL,
 ['docs/simulation_protocol.json','docs/historical_method.md'],'implemented_pending_validation'),
('C02','数学与概率建模','解释无套利定价、风险中性与历史概率的区别、自融资账本和假设。',ALL,
 ['risklab/pricing.py','risklab/paths.py','risklab/hedging.py'],'implemented_pending_validation'),
('C03','统计推断与不确定性','成对独立模拟CI、相关历史数据的分块bootstrap与敏感性。',ALL,
 ['risklab/statistics.py','risklab/historical.py','results/simulation_comparisons.csv'],'implemented_pending_validation'),
('C04','真实数据处理','公开来源、缺失处理、单位、时间边界、数据字典及hash。',ALL,
 ['data','scripts/fetch_ecb.py','results/historical_summary.json'],'implemented_pending_validation'),
('C05','机器学习与泛化评价','真正训练的正则回归、训练期预处理、validation选择及锁定测试。',
 ['PENN_DSAI','NTU_DS','HARVARD','CMU_BIDA','CUHK_DSBS','PENN_SE'],
 ['risklab/historical.py','results/historical_forecasts.csv'],'implemented_pending_validation'),
('C06','数值算法与动态规划','解析式、二叉树倒推与美式提前行权扩展、Monte Carlo、Greeks和IV。',
 ['HKU_FC','IMPERIAL','PENN_SE','PENN_DSAI','CUHK_DSBS'],
 ['risklab/pricing.py','results/numerical_benchmarks.csv'],'implemented_pending_validation'),
('C07','约束决策与优化','有限候选策略上的成本约束选择，验证选择并独立评价，不宣称全局最优。',
 ['CMU_BIDA','BERKELEY','PENN_SE','CUHK_DSBS','HKU_FC'],
 ['scripts/run_simulations.py','results/simulation_selection.csv'],'implemented_pending_validation'),
('C08','软件系统与可靠性','模块化API、SQL证据库、输入约束、账本核对、异常反馈与回归测试。',ALL,
 ['risklab/server.py','scripts/build_research_store.py','tests','docs/api.md'],'implemented_pending_validation'),
('C09','可复现计算与数据治理','配置、随机种子、原始快照、环境、校验清单和一键复现。',ALL,
 ['scripts','data','results','docs/reproducibility.md'],'implemented_pending_validation'),
('C10','批判性评估与风险意识','区分数值/估计/结构/执行误差，记录失效条件、负结果和测试集限制。',ALL,
 ['results/simulation_summary.json','results/historical_summary.json','report'],'implemented_pending_validation'),
('C11','可视化与研究表达','中文交互工作台，带来源的图表，论文式报告和英文摘要。',ALL,
 ['web','figures','report'],'implemented_pending_validation'),
('C12','金融业务与经济解释','区分预测损失、复制损失和费用；参考汇率不当成可交易报价。',
 ['CMU_BIDA','CUHK_DSBS','HKU_FC','BERKELEY','PENN_SE'],
 ['docs/historical_method.md','risklab/hedging.py','report'],'implemented_pending_validation'),
('C13','并行与大规模计算','已实测等量分块串行与2/4进程Monte Carlo，保留并行更慢的结果；未验证MPI/GPU集群或超大规模数据系统。',
 ['IMPERIAL','PENN_DSAI','CMU_BIDA','HARVARD'],
 ['scripts/benchmark_parallel.py','results/parallel_benchmark.json'],'partial'),
('C14','隐私 公平性与负责的研究','公开非个人数据、来源许可与AI贡献透明；未进行人群公平性或患者隐私实证。',
 ['PENN_DSAI','HARVARD','YALE','NTU_DS','CMU_BIDA'],
 ['docs/data_governance.md','docs/contribution_record.md'],'partial'),
('C15','健康领域 生物统计与公共卫生','金融方法只提供可迁移的定量准备；医疗数据、临床或人群问题、流行病学及公共卫生动机需其他证据。',
 ['HARVARD','YALE'],[],'external_evidence_required'),
('C16','团队合作 管理与真实用户沟通','单人AI协作项目不证明真人团队领导、企业部署或用户研究；仅提供交接文档。',
 ['CMU_BIDA','BERKELEY','IMPERIAL','YALE','HARVARD','NTU_DS'],
 ['docs/contribution_record.md'],'external_evidence_required'),
('C17','正式学术先修与语言准备','学位、数学统计课程学分成绩、编程课程及英语要求须逐校核验，代码和短课证书不能自动替代。',ALL,[],'external_evidence_required'),
('C18','本人掌握与研究贡献','能够亲自解释假设、复现实验、回答失败案例；工具生成成果不能自动认定本人掌握。',ALL,
 ['docs/contribution_record.md','docs/research_defense.md'],'external_evidence_required'),
]
REFERENCES=[
('R1','Black F and Scholes M (1973). The Pricing of Options and Corporate Liabilities. Journal of Political Economy 81(3), 637–654.',
 'https://doi.org/10.1086/260062','Analytic pricing baseline under stated assumptions, not executable FX valuation.'),
('R2','Cox JC, Ross SA and Rubinstein M (1979). Option pricing A simplified approach. Journal of Financial Economics 7, 229–263.',
 'https://doi.org/10.1016/0304-405X(79)90015-1','Recombining tree and backward induction.'),
('R3','Leland HE (1985). Option Pricing and Replication with Transactions Costs. Journal of Finance 40, 1283–1301.',
 'https://doi.org/10.1111/j.1540-6261.1985.tb02383.x','Literature motivation for discrete hedging with costs; this project does not implement or claim Leland asymptotic theorem.'),
('R4','Patton AJ (2011). Volatility forecast comparison using imperfect volatility proxies. Journal of Econometrics 160(1), 246–256.',
 'https://scholars.duke.edu/publication/792433','Variance forecast loss and noisy proxy caveats; squared reference returns are not directly observed latent variance.'),
('R5','Künsch HR (1989). The Jackknife and the Bootstrap for General Stationary Observations. Annals of Statistics 17(3), 1217–1241.',
 'https://doi.org/10.1214/aos/1176347265','Moving-block bootstrap motivation; stationarity and dependence assumptions remain limitations.'),
('R6','scikit-learn documentation. Ridge and temporal evaluation.',
 'https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html','Regularized linear learner, preprocessing learned using training data only.'),
('R7','scikit-learn documentation. TimeSeriesSplit.',
 'https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html','Motivation for temporal rather than random evaluation; implementation uses explicit date cutoffs.'),
('D1','European Central Bank. Euro foreign exchange reference rates.',
 'https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html','Reference observations for information, not intended for market transaction purposes.'),
('D2','European Central Bank. Disclaimer and copyright.',
 'https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html','Source acknowledgement and statistical reuse terms; preserve transformation notices.'),
]

def main():
    (ROOT/'docs').mkdir(exist_ok=True)
    validation_path=ROOT/'results/validation.json'
    verified=validation_path.exists() and json.loads(validation_path.read_text(encoding='utf-8')).get('status')=='passed'
    items=[]
    for i,n,d,p,e,s in ITEMS:
        exists=all((ROOT/path).exists() for path in e)
        status='implemented_validated' if s=='implemented_pending_validation' and verified and exists else s
        items.append({'id':i,'name':n,'description':d,'programs':p,'evidence':e,'status':status})
    obj={'title':'十项目相关能力并集','review_date':'2026-10-05','scope':'Union of relevant competency emphases from the ten official program pages; not an exhaustive admissions checklist or claim of meeting all curricula.',
         'operation':'union','programs':[{'id':i,'name':n,'url':u,'emphases':e,'note':note} for i,n,u,e,note in PROGRAMS],
         'competencies':items,
         'boundaries':['Formal prerequisites require academic documents.', 'Health interest and biomedical expertise require separate evidence.',
                       'Individual mastery and real teamwork cannot be inferred from generated artifacts.',
                       'Pending evidence is not a passed check; machine-verifiable status is finalized after execution.']}
    (ROOT/'docs/competency_union.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    refs=[{'id':i,'citation':t,'url':u,'use':use,'access_date':'2026-10-05'} for i,t,u,use in REFERENCES]
    refs += [{'id':f'P{k+1}','citation':n,'url':u,'use':note,'access_date':'2026-10-05'} for k,(_,n,u,_,note) in enumerate(PROGRAMS)]
    (ROOT/'docs/references.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(PROGRAMS)} programs, {len(ITEMS)} union dimensions, {len(refs)} reference entries')

if __name__=='__main__':main()
