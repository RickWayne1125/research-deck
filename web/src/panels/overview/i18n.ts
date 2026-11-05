// Strings of the Overview panel (prefix ov.). DAG states, kinds, stages and lens names come from dag/encoding.tsx (dagx.*).
// Agent prompts (ov.step.*.ask, ov.ask.*) are what the researcher would type; they are sent in the UI language.
import { registerStrings } from '../../i18n';

registerStrings({
  zh: {
    'td.steps': '研究阶段',
    'td.next.missing': '进入下一阶段还差 {n} 项',
    'td.next.ready': '可以进入下一阶段',
    'td.next.missingLast': '离投稿还差 {n} 项',
    'td.next.readyLast': '检查都已满足',
    'td.next.title': '进入「{step}」',
    'td.next.titleLast': '投稿前的检查',
    'td.next.go': '进入「{step}」',
    'td.next.goLast': '标记为可以投稿',
    'td.next.anyway': '仍然进入（记下没满足的检查）',
    'td.next.allOk': '这一阶段的检查都满足了。进入下一阶段时会存一个快照，之后可以对照。',
    'td.next.blocking': '还差 {n} 项。这个项目的检查是硬性的，满足之后才能进入下一阶段。',
    'td.next.advisory': '还差 {n} 项。检查只是提醒，你可以先进入下一阶段，没满足的会记下来。',
    'td.next.checks': '{ok}/{n} 项满足',
    'td.next.note': '从「今天」进入下一阶段',
    'td.decide': '需要你决定',
    'td.waiting': '等证据',
    'td.keys': 'J / K 上下移动 · Y 执行第一个按钮 · N 执行第二个',
    'td.nothing': '现在没有要你决定的事。',
    'td.sep': '、',
    'td.andMore': ' 等 {n} 个',
    'td.open': '打开',
    'td.askAgent': '问 Agent',
    'td.approve': '接受',
    'td.reject': '驳回',
    'td.impact': '接受后会影响什么',
    'td.tag.proposal': '提议',
    'td.tag.drafted': '草稿',
    'td.tag.fix': '要复核',
    'td.tag.run': '要运行',
    'td.tag.failed': '失败',
    'td.tag.noEvidence': '无证据',
    'td.tag.blocked': '受阻',
    'td.review.title': 'Agent 起草了 {n} 个节点，还没生效',
    'td.review.body': '包括 {kinds}。逐个看过、接受或驳回后，它们才会进入研究地图。',
    'td.review.one': '逐个审阅',
    'td.review.all': '全部接受',
    'td.review.allTitle': '接受全部 {n} 个草稿节点？',
    'td.review.allBody': '它们会从「提议」变成「进行中」。之后仍然可以在地图里逐个驳回或修改。',
    'td.review.allGo': '接受 {n} 个',
    'td.review.rationale': '在「今天」里一并接受草稿',
    'td.decision.go': '去决定',
    'td.decision.ask': '帮我比较「{title}」的几个候选方案：各自的代价、风险，以及选定后要改哪些东西。',
    'td.fix.title': '{n} 个节点要复核',
    'td.fix.go': '去复核',
    'td.rerun.title': '{n} 个实验要运行或重跑',
    'td.rerun.titleH': '{n} 个实验要运行或重跑（约 {h} GPU·h）',
    'td.rerun.go': '看运行计划',
    'td.failed.title': '{n} 个实验运行失败',
    'td.failed.go': '看日志',
    'td.evidence.title': '{n} 个发现或论点还没有证据',
    'td.evidence.one': '这个{kind}还没有支持它的证据。',
    'td.evidence.ask': '这些节点还没有证据：{ids}。哪些已有实验能支持它们？还缺什么实验？',
    'td.blocked.title': '{n} 个实验在等代码或上游结果',
    // header
    'ov.noSummary': '还没有一句话概述：可以在项目状态文件夹的 project.yaml 里填写 summary。',
    
    
    
    
    

    // DAG availability and the empty state
    'ov.dag.unavailable': '研究 DAG 暂不可用',
    'ov.dag.unavailableBody': '后端没有返回 DAG（{msg}）。下面的流程看板先按空项目显示。',
    'ov.start.title': '从定义问题开始',
    'ov.start.body': '这个项目还没有研究 DAG。先写下要解决的问题：它是整条研究流程的根，之后的文献、现象、方案、设计和论点都从它展开。',
    'ov.start.titleField': '问题（一句话标题）',
    'ov.start.titlePh': '例如：长上下文推理中 KV cache 的分层放置',
    'ov.start.statement': '问题陈述',
    'ov.start.statementPh': '在什么工作负载、模型和硬件上，哪个指标不够好，为什么值得解决。',
    'ov.start.id': '节点 id',
    'ov.start.idInvalid': 'slug 只能包含小写字母、数字、连字符和点',
    'ov.start.create': '创建问题节点',
    'ov.start.ask': '让 Agent 起草',
    'ov.start.askPrompt': '帮我把这个项目的研究问题写成 DAG 里的 problem 节点：一句话问题陈述、范围（工作负载、模型、硬件）、目标指标和成功阈值，以及开工前就写下的止损条件。先读项目里的 README 和笔记，缺什么信息就问我。',
    'ov.start.failed': '没有创建成功：{msg}',
    'ov.start.proposed': '已作为提议提交，批准后生效。',

    // lens tiles
    
    
    
    
    

    // panel summaries
    
    
    
    
    
    'ov.sum.figures.stale': '{n} 张需重新渲染',
    
    
    
    'ov.sum.na': '暂不可用',
    'ov.sum.open': '打开{panel}',

    // engineering projects (EngineeringOverview.tsx)
    'ov.eng.badge': '工程项目',
    'ov.eng.badgeTitle': '工程项目：代码、文档、运行和图；不显示研究 DAG 和阶段条',
    'ov.eng.repos': '代码仓库',
    'ov.eng.repos.open': '在代码面板中打开 {repo}',
    'ov.eng.repos.current': '代码面板当前显示这个仓库',
    'ov.eng.repos.empty': '还没有 git 仓库。项目文件夹本身是仓库时会列在这里；多仓库工作区请在 project.yaml 的 code.repos 里列出各个文件夹。',
    'ov.eng.repos.clean': '干净',
    'ov.eng.repos.dirty': '{n} 个未提交改动',
    'ov.eng.repos.slow': '响应慢',
    'ov.eng.repos.error': '读取失败',
    'ov.eng.repos.notRepo': '不是 git 仓库',
    'ov.eng.repos.detached': '分离的 HEAD',
    'ov.eng.commits': '最近提交',
    'ov.eng.commits.repo': '仓库',
    'ov.eng.commits.empty': '这个仓库还没有提交。',
    'ov.eng.commits.open': '在代码面板中查看',
    'ov.eng.docs': '文档',
    'ov.eng.docs.empty': '还没有文档：paper 目录以及 docs/、notes/ 下的 .md 和 .tex 会出现在这里。',
    'ov.eng.docs.words': '{n} 字',
    'ov.eng.exps': '实验与运行',
    'ov.eng.exps.empty': '还没有实验记录。',
    'ov.eng.exps.more': '还有 {n} 个',
    'ov.eng.exps.status.planned': '计划中',
    'ov.eng.exps.status.queued': '排队中',
    'ov.eng.exps.status.running': '运行中',
    'ov.eng.exps.status.succeeded': '成功',
    'ov.eng.exps.status.failed': '失败',
    'ov.eng.exps.status.cancelled': '已取消',
    'ov.eng.exps.status.unknown': '未知',
    'ov.eng.figs': '图',
    'ov.eng.figs.empty': '还没有图。',
    'ov.eng.figs.noPreview': '无预览',
    'ov.eng.figs.more': '还有 {n} 张',
    'ov.eng.figs.status.stale': '需重新渲染',
    'ov.eng.figs.status.error': '渲染失败',
    'ov.eng.figs.status.unrendered': '未渲染',

    // pipeline board
    
    
    
    
    
    

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    

    // gates
    
    
    
    
    
    
    
    
    
    
    
    

    // attention
    
    
    
    
    

    // inbox
    
    'ov.inbox.ops': '{n} 项操作',
    
    'ov.inbox.confirmUnlock': '我确认解锁 {ids}，并应用这项改动',
    
    'ov.inbox.rejectPh': '驳回理由（会反馈给提出者）',
    'ov.inbox.rebase': '提议所基于的 DAG 已经变化。下面是重新计算的影响，请复核后再批准。',
    

    // activity
    'ov.act.title': '最近动态',
    'ov.act.empty': '还没有记录。',
    'ov.op.create': '新建',
    'ov.op.edit': '修改',
    'ov.op.link': '连接',
    'ov.op.unlink': '断开',
    'ov.op.set_status': '改状态',
    'ov.op.attest': '复核确认',
    'ov.op.rollback': '回滚',
    'ov.op.restore_snapshot': '恢复快照',
    'ov.op.lock': '锁定',
    'ov.op.unlock': '解锁',
    'ov.op.select_run': '选定运行',
    'ov.op.exclude_run': '排除运行',
    'ov.op.config_edit': '修改配置',
    'ov.op.run_recorded': '记录运行',
    'ov.op.decision': '裁决',
    'ov.op.gate_passed': '通过关卡',
    'ov.op.propose': '提议',
    'ov.op.proposal': '提议',
    'ov.op.approve': '批准',
    'ov.op.reject': '驳回',
    'ov.op.snapshot': '创建快照',
    'ov.op.paper_sync': '同步论文',
    'ov.op.render': '渲染',
    'ov.decision.confirm': '确认',
    'ov.decision.refute': '证伪',
    'ov.decision.abandon': '放弃',
    'ov.decision.supersede': '取代',
    'ov.decision.revive': '恢复',
    'ov.decision.lock': '锁定',
    'ov.decision.unlock': '解锁',
    'ov.decision.gate_pass': '通过关卡',
    'ov.decision.rollback': '回滚',
  },
  en: {
    'td.steps': 'Research stage',
    'td.next.missing': '{n} to go before the next stage',
    'td.next.ready': 'Ready for the next stage',
    'td.next.missingLast': '{n} to go before submission',
    'td.next.readyLast': 'Every check holds',
    'td.next.title': 'Move on to {step}',
    'td.next.titleLast': 'Checks before submission',
    'td.next.go': 'Move on to {step}',
    'td.next.goLast': 'Mark ready to submit',
    'td.next.anyway': 'Move on anyway (record the open checks)',
    'td.next.allOk': 'Every check of this stage holds. Moving on saves a snapshot to compare against later.',
    'td.next.blocking': '{n} to go. This project\'s checks are binding: they must hold before the next stage.',
    'td.next.advisory': '{n} to go. The checks are advisory: you may move on now and the open ones are recorded.',
    'td.next.checks': '{ok}/{n} hold',
    'td.next.note': 'Moved on from Today',
    'td.decide': 'Needs your decision',
    'td.waiting': 'Waiting for evidence',
    'td.keys': 'J / K to move · Y runs the first button · N the second',
    'td.nothing': 'Nothing needs your decision right now.',
    'td.sep': ', ',
    'td.andMore': ' and {n} more',
    'td.open': 'Open',
    'td.askAgent': 'Ask the agent',
    'td.approve': 'Accept',
    'td.reject': 'Reject',
    'td.impact': 'What accepting changes',
    'td.tag.proposal': 'Proposal',
    'td.tag.drafted': 'Draft',
    'td.tag.fix': 'Review',
    'td.tag.run': 'To run',
    'td.tag.failed': 'Failed',
    'td.tag.noEvidence': 'No evidence',
    'td.tag.blocked': 'Blocked',
    'td.review.title': 'An agent drafted {n} nodes; none is in effect yet',
    'td.review.body': 'They include {kinds}. Once you accept or reject them, they join the research map.',
    'td.review.one': 'Review one by one',
    'td.review.all': 'Accept all',
    'td.review.allTitle': 'Accept all {n} drafted nodes?',
    'td.review.allBody': 'They go from Proposed to Active. You can still reject or edit any of them on the map.',
    'td.review.allGo': 'Accept {n}',
    'td.review.rationale': 'Accepted the drafts together from Today',
    'td.decision.go': 'Decide',
    'td.decision.ask': 'Compare the options for "{title}": their cost, their risks, and what has to change once one is chosen.',
    'td.fix.title': '{n} nodes to review',
    'td.fix.go': 'Review',
    'td.rerun.title': '{n} experiments to run or rerun',
    'td.rerun.titleH': '{n} experiments to run or rerun (about {h} GPU-h)',
    'td.rerun.go': 'See the run plan',
    'td.failed.title': '{n} runs failed',
    'td.failed.go': 'See the log',
    'td.evidence.title': '{n} findings or claims have no evidence yet',
    'td.evidence.one': 'This {kind} has no supporting evidence yet.',
    'td.evidence.ask': 'These nodes have no evidence yet: {ids}. Which existing experiments could support them, and what is missing?',
    'td.blocked.title': '{n} experiments wait for code or an upstream result',
    'ov.noSummary': 'No one-line summary yet: set summary in project.yaml in the project\'s state folder.',
    
    
    
    
    

    'ov.dag.unavailable': 'The research DAG is not available',
    'ov.dag.unavailableBody': 'The backend returned no DAG ({msg}). The pipeline below shows an empty project for now.',
    'ov.start.title': 'Start by framing the problem',
    'ov.start.body': 'This project has no research DAG yet. Write down the problem first: it is the root of the pipeline, and the references, findings, solutions, design and claims all grow from it.',
    'ov.start.titleField': 'Problem (short title)',
    'ov.start.titlePh': 'e.g. Tiered KV-cache placement for long-context inference',
    'ov.start.statement': 'Statement',
    'ov.start.statementPh': 'On which workloads, models and hardware which metric falls short, and why it is worth solving.',
    'ov.start.id': 'Node id',
    'ov.start.idInvalid': 'The slug may use lowercase letters, digits, hyphens and dots',
    'ov.start.create': 'Create the problem node',
    'ov.start.ask': 'Draft it with the agent',
    'ov.start.askPrompt': 'Help me write this project\'s research problem as a problem node in the DAG: a one-sentence statement, the scope (workloads, models, hardware), the target metric and success threshold, and kill criteria written down before any work. Read the README and notes in the project first, and ask me for anything missing.',
    'ov.start.failed': 'Could not create it: {msg}',
    'ov.start.proposed': 'Submitted as a proposal; it applies once approved.',

    
    
    
    
    

    
    
    
    
    
    'ov.sum.figures.stale': '{n} need a re-render',
    
    
    
    'ov.sum.na': 'Unavailable',
    'ov.sum.open': 'Open {panel}',

    // engineering projects (EngineeringOverview.tsx)
    'ov.eng.badge': 'Engineering',
    'ov.eng.badgeTitle': 'Engineering project: code, documents, runs and figures; no research DAG or stage strip',
    'ov.eng.repos': 'Repositories',
    'ov.eng.repos.open': 'Open {repo} in Coding',
    'ov.eng.repos.current': 'The Coding panel shows this repository',
    'ov.eng.repos.empty': 'No git repository yet. The project folder is listed here when it is one; for a workspace of several repositories, list their folders in code.repos in project.yaml.',
    'ov.eng.repos.clean': 'clean',
    'ov.eng.repos.dirty': '{n} uncommitted',
    'ov.eng.repos.slow': 'slow',
    'ov.eng.repos.error': 'error',
    'ov.eng.repos.notRepo': 'not a git repository',
    'ov.eng.repos.detached': 'detached HEAD',
    'ov.eng.commits': 'Recent commits',
    'ov.eng.commits.repo': 'Repository',
    'ov.eng.commits.empty': 'No commits in this repository yet.',
    'ov.eng.commits.open': 'Open in Coding',
    'ov.eng.docs': 'Documents',
    'ov.eng.docs.empty': 'No documents yet: .md and .tex files under the paper folder, docs/ and notes/ show up here.',
    'ov.eng.docs.words': '{n} words',
    'ov.eng.exps': 'Experiments and runs',
    'ov.eng.exps.empty': 'No experiment records yet.',
    'ov.eng.exps.more': '{n} more',
    'ov.eng.exps.status.planned': 'planned',
    'ov.eng.exps.status.queued': 'queued',
    'ov.eng.exps.status.running': 'running',
    'ov.eng.exps.status.succeeded': 'succeeded',
    'ov.eng.exps.status.failed': 'failed',
    'ov.eng.exps.status.cancelled': 'cancelled',
    'ov.eng.exps.status.unknown': 'unknown',
    'ov.eng.figs': 'Figures',
    'ov.eng.figs.empty': 'No figures yet.',
    'ov.eng.figs.noPreview': 'No preview',
    'ov.eng.figs.more': '{n} more',
    'ov.eng.figs.status.stale': 'stale',
    'ov.eng.figs.status.error': 'render failed',
    'ov.eng.figs.status.unrendered': 'not rendered',

    
    
    
    
    
    

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    

    
    
    
    
    
    
    
    
    
    
    
    

    
    
    
    
    

    
    'ov.inbox.ops': '{n} ops',
    
    'ov.inbox.confirmUnlock': 'I confirm unlocking {ids} and applying this change',
    
    'ov.inbox.rejectPh': 'Reason (sent back to the proposer)',
    'ov.inbox.rebase': 'The DAG this proposal was based on has changed. The impact below was recomputed; review it before approving.',
    

    'ov.act.title': 'Recent activity',
    'ov.act.empty': 'Nothing recorded yet.',
    'ov.op.create': 'created',
    'ov.op.edit': 'edited',
    'ov.op.link': 'linked',
    'ov.op.unlink': 'unlinked',
    'ov.op.set_status': 'changed status of',
    'ov.op.attest': 'attested',
    'ov.op.rollback': 'rolled back',
    'ov.op.restore_snapshot': 'restored snapshot',
    'ov.op.lock': 'locked',
    'ov.op.unlock': 'unlocked',
    'ov.op.select_run': 'selected a run of',
    'ov.op.exclude_run': 'excluded a run of',
    'ov.op.config_edit': 'edited config',
    'ov.op.run_recorded': 'recorded a run of',
    'ov.op.decision': 'decided on',
    'ov.op.gate_passed': 'passed gate',
    'ov.op.propose': 'proposed',
    'ov.op.proposal': 'proposed',
    'ov.op.approve': 'approved',
    'ov.op.reject': 'rejected',
    'ov.op.snapshot': 'took snapshot',
    'ov.op.paper_sync': 'synced the paper',
    'ov.op.render': 'rendered',
    'ov.decision.confirm': 'confirmed',
    'ov.decision.refute': 'refuted',
    'ov.decision.abandon': 'abandoned',
    'ov.decision.supersede': 'superseded',
    'ov.decision.revive': 'revived',
    'ov.decision.lock': 'locked',
    'ov.decision.unlock': 'unlocked',
    'ov.decision.gate_pass': 'passed gate',
    'ov.decision.rollback': 'rolled back',

    // English singulars (usePlural picks "<key>.one" when n is 1)
    
    
    
    
    'ov.sum.figures.stale.one': '1 needs a re-render',
    'ov.eng.docs.words.one': '1 word',
    'ov.inbox.ops.one': '1 op',
  },
});
