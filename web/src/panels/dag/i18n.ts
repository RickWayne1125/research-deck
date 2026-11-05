// Strings of the Research DAG panel (prefix dag.). Status / freshness / kind / stage / lens words are shared and live in
// dag/encoding.tsx (dagx.*); the impact preview's own words live in dag/ImpactView.tsx (dagx.impact.*).
import { registerStrings } from '../../i18n';

registerStrings({
  zh: {
    'dag.subtitle2': '{n} 个节点',
    'dag.view.list': '列表', 'dag.view.graph': '关系图',
    'dag.filter.aria': '筛选',
    'dag.filter.all': '全部', 'dag.filter.all.hint': '所有还在用的节点',
    'dag.filter.proposed': '待审', 'dag.filter.proposed.hint': 'Agent 起草、还没生效的节点',
    'dag.filter.attention': '要处理', 'dag.filter.attention.hint': '要复核、要运行或重跑、或在等上游的节点',
    'dag.filter.confirmed': '已确认', 'dag.filter.confirmed.hint': '已确认或锁定的结论',
    'dag.filter.dead': '已放弃', 'dag.filter.dead.hint': '被证伪、放弃或取代的路线，以及各自的理由',
    'dag.list.empty': '这个筛选下没有节点。',
    'dag.list.none': '这一阶段还没有节点',
    'dag.list.keys': 'J / K 上下移动 · Y 接受草稿 · N 驳回草稿 · ↵ 详情 · Esc 收起',
    'dag.list.undecided': '未决定',
    'dag.list.options': '候选方案',
    'dag.list.choose': '选这个',
    'dag.list.chosen': '已选',
    'dag.list.chooseHint': '选定前会先在右侧显示影响：哪些节点要复核、哪些实验要重跑。',
    'dag.list.chooseTitle': '为「{decision}」选定「{option}」',
    'dag.list.upstream': '依据',
    'dag.list.downstream': '被依赖',
    'dag.list.accept': '接受',
    'dag.list.reject': '驳回',
    'dag.list.details': '详情',
    'dag.list.accepted': '已接受「{title}」',
    'dag.list.askPrompt': '看一下 {id}：它说的成立吗？依据够不够？接下来该做什么？',
    'dag.subtitleEmpty': '把研究过程当作一张构建图：每个结论都知道自己依赖什么、何时需要复核或重跑',
    'dag.view.aria': '视图', 
    
    'dag.resetLayout': '重置布局（清除手动拖动的位置）',
    'dag.map.aria': '研究地图：按阶段排列的节点与依赖',
    'dag.rail.title': '文献与数据集', 'dag.rail.counts': '{refs} 篇文献 · {data} 个数据集',

    
    
    

    'dag.node.stack': '取代了 {n} 个', 'dag.node.stackHint': '被它取代的旧版本折叠在这张卡片后面；打开“显示负面结果”可展开',
    'dag.node.runsHint': '运行记录数',
    'dag.group.count': '{tried} 个尝试，{chosen} 个选定', 'dag.group.openHint': '在“尝试过什么”中查看这组备选方案',
    'dag.gate.open': '打开 {gate} 检查清单',
    'dag.gate.state.open': '未通过', 'dag.gate.state.passed': '已通过', 'dag.gate.state.passed_degraded': '已通过·退化', 'dag.gate.state.failing': '不满足',
    'dag.gate.after': '在「{stage}」之后', 'dag.gate.checks': '{ok}/{n} 项满足',
    'dag.gate.value': '当前 {v} · 要求 {target}',
    'dag.gate.pass': '通过门禁', 'dag.gate.passHint': '通过 {gate} 会记录一次决定并创建快照 gate-{gate}，之后可以随时回到这个状态。',
    'dag.gate.note': '备注', 'dag.gate.notePh': '例如：基线复现误差在 6% 以内，可以继续',
    'dag.gate.passed': '{gate} 已通过，快照 {snap}', 'dag.gate.passedBy': '{who} 于 {at} 通过 · 快照 {snap}',

    'dag.flag.drift': '证据数值有变化，但谓词仍成立', 'dag.flag.shaky': '依赖的上游待复核：{via}',
    'dag.flag.impl_lag': '结果对应的代码已与设计不符：先实现，再重跑', 'dag.flag.reused': '沿用较早的有效运行',
    'dag.flag.cutoff': '重跑结果在容差内，指纹未变', 'dag.flag.lock_alert': '已锁定的节点不再成立',
    'dag.flag.unsealed': 'YAML 在 API 之外被改动过', 'dag.flag.behind_head': '有边固定在旧版本上',
    'dag.flag.conflict': '合并后历史分叉，需要你来裁决', 'dag.flag.trace_quality': '运行追踪不完整',
    'dag.flagShort.drift': '漂移', 'dag.flagShort.shaky': '根基不稳', 'dag.flagShort.impl_lag': '先实现', 'dag.flagShort.reused': '复用',
    'dag.flagShort.cutoff': '≈ 截断', 'dag.flagShort.lock_alert': '锁定告警', 'dag.flagShort.unsealed': '手动改动',
    'dag.flagShort.behind_head': '固定旧版', 'dag.flagShort.conflict': '历史冲突', 'dag.flagShort.trace_quality': '追踪粗糙',

    'dag.edge.input': '输入', 'dag.edge.evidence': '证据', 'dag.edge.basis': '依据', 'dag.edge.implements': '实现',
    'dag.edge.describes': '描述', 'dag.edge.cites': '引用', 'dag.edge.supports': '支持', 'dag.edge.refutes': '反驳',

    'dag.legend.title': '图例', 'dag.legend.status': '状态（填充与边框）', 'dag.legend.fresh': '时效（外圈与标记）',
    'dag.legend.edges': '边', 'dag.legend.moved': '上游已变（标出变化的方面）', 'dag.legend.shapes': '形状',
    'dag.legend.shapesBody': '圆角卡片：问题、发现、差距、方案 · 胶囊：文献 · 圆柱：数据集 · 切角卡片带格子：实验与脚本图 · 尖头：决策 · 方角：设计与模块 · 折角：论点与章节',

    'dag.inspector.aria': '节点详情：{id}', 'dag.inspector.missing': '图中没有节点 {id}（可能已被删除或改名）。',
    'dag.side.resize': '侧栏宽度',
    'dag.tab.overview': '概览', 'dag.tab.edges': '依赖', 'dag.tab.cells': '实验格', 'dag.tab.history': '历史', 'dag.tab.why': '原因', 'dag.tab.agent': 'Agent',
    'dag.overview.reasons': '为什么不是最新', 'dag.overview.shaky': '它依赖的这些节点待复核：',
    'dag.overview.locked': '{by} 于 {at} 锁定', 'dag.overview.supersededBy': '已被取代，继任：', 'dag.overview.altGroup': '备选方案组：',
    'dag.overview.facets': '内容', 'dag.overview.noFacets': '没有内容字段。',
    'dag.overview.created': '创建', 'dag.overview.updated': '最近修改', 'dag.overview.vid': '版本',
    'dag.facet.unresolved': '（未解析：配置文件或键不存在）',

    'dag.status.activate': '开始推进', 'dag.status.confirm': '确认', 'dag.status.reopen': '重新打开', 'dag.status.lock': '锁定',
    'dag.status.unlock': '解锁', 'dag.status.refute': '证伪', 'dag.status.abandon': '放弃', 'dag.status.supersede': '被取代', 'dag.status.revive': '复活',
    'dag.status.activateHint': '从提议转为进行中。',
    'dag.status.confirmHint': '确认要求节点当前是最新的，并满足其类型的条件（例如论点至少有一条成立的支持证据）。',
    'dag.status.reopenHint': '退回进行中，以便继续修改。',
    'dag.status.lockHint': '锁定后任何修改都要先解锁；会记录锁定版本并打 git 标签。只有你能锁定。',
    'dag.status.unlockHint': '解锁会记录原因，锁定记录保留在历史里。',
    'dag.status.refuteHint': '证伪需要原因和至少一条证据；应用时 node: 证据会冻结为具体的 run: 运行，负面结果永久保留。',
    'dag.status.abandonHint': '放弃不删除节点：它留在“尝试过什么”里，连同原因。',
    'dag.status.supersedeHint': '指定继任节点；依赖它的节点会提示重新链接。',
    'dag.status.reviveHint': '把已证伪、放弃或取代的节点重新变为进行中。',
    'dag.status.dialogTitle': '{action}：{id}', 'dag.status.doneTitle': '{action} {id}',
    'dag.status.reason': '原因（记入决定日志）', 'dag.status.note': '补充说明',
    'dag.status.abandonReason': '放弃原因', 'dag.status.successor': '继任节点', 'dag.status.pickSuccessor': '选择继任节点…',
    'dag.status.evidence': '证据（至少一条）', 'dag.status.evidencePh': '其他证据地址，如 run:r-20261101-2307-9e4d#out.tpot_ratio',
    'dag.status.freezeHint': '应用时，node: 证据会冻结为当前选中的运行，之后不会再变。',
    'dag.status.reasonPh.activate': '为什么现在开始做', 'dag.status.reasonPh.confirm': '依据是什么',
    'dag.status.reasonPh.reopen': '为什么要重新打开', 'dag.status.reasonPh.lock': '例如：设计冻结，开始评估',
    'dag.status.reasonPh.unlock': '例如：需要加入解码抢占', 'dag.status.reasonPh.refute': '例如：LMSYS 16 req/s 下 TPOT p99 是 vLLM 的 1.21×',
    'dag.status.reasonPh.abandon': '具体情况', 'dag.status.reasonPh.supersede': '为什么由它取代',
    'dag.status.reasonPh.revive': '例如：新硬件上瓶颈变了，值得再试',
    'dag.abandon.infeasible': '不可行', 'dag.abandon.dominated': '被其他方案全面超越', 'dag.abandon.no_headroom': '没有提升空间',
    'dag.abandon.competitor_closed_gap': '竞品已经解决', 'dag.abandon.out_of_scope': '超出范围', 'dag.abandon.cost': '代价太高',
    'dag.abandon.time': '时间不够', 'dag.abandon.other': '其他',

    'dag.edit.title': '修改 {id}#{facet}', 'dag.edit.typeToPreview': '输入修改后会自动预览影响（停止输入 0.3 秒后计算）。',
    'dag.edit.badJson': 'JSON 格式错误：{msg}', 'dag.edit.boundHint': '这是绑定到 {file} 的配置键：修改会写入该配置文件，影响是精确计算的。',
    'dag.edit.editorial': '仅措辞修改', 'dag.edit.editorialHint': '应用后自动复核直接依赖它的描述类节点；从不影响实验结果',
    'dag.edit.lockedHint': '该节点已锁定：可以先预览影响，应用时需要勾选解锁。',
    'dag.edit.demoteHint': '修改已确认的节点会把它退回进行中（勾选“仅措辞修改”则不会）。',

    'dag.edges.out': '它依赖的（{n}）', 'dag.edges.in': '依赖它的（{n}）', 'dag.edges.none': '没有依赖边。',
    'dag.edges.seen': '记录', 'dag.edges.current': '当前', 'dag.edges.same': '一致', 'dag.edges.pinned': '固定',
    'dag.edges.attest': '复核通过', 'dag.edges.attestAll': '全部复核通过（{n}）',

    'dag.cells.none': '这个节点没有实验格。', 'dag.cells.summary': '{n} 个格 · 选中运行共 {h} GPU·h',
    'dag.cells.cell': '格', 'dag.cells.level': '时效', 'dag.cells.selected': '选中运行', 'dag.cells.newest': '最新运行', 'dag.cells.newer': '有更新的',
    'dag.cells.trace': '追踪', 'dag.cells.platform': '平台',
    'dag.cells.reused': '复用', 'dag.cells.reusedHint': '最新运行无效，沿用了更早的有效运行',
    'dag.cells.cutoffHint': '重跑结果落在容差内，下游不必变化',
    'dag.cells.mismatch': '与运行时不一致的输入（{n}）', 'dag.cells.runs': '运行（{n}）', 'dag.cells.noRuns': '还没有运行。',
    'dag.cells.select': '选用', 'dag.cells.selectHint': '固定使用这次运行（默认用最新的有效运行）', 'dag.cells.unpin': '取消固定',
    'dag.cells.exclude': '排除', 'dag.cells.excluded': '已排除', 'dag.cells.openDiff': '看代码差异',
    'dag.cells.excludeTitle': '排除运行 {id}', 'dag.cells.excludeBody': '被排除的运行不再参与复用（例如测量时 GPU 降频）。记录保留，可以随时查看。',
    'dag.cells.excludePh': '例如：GPU 83°C 降频',
    'dag.trace.traced': '完整追踪', 'dag.trace.declared': '按声明', 'dag.trace.coarse': '粗粒度',
    'dag.run.queued': '排队中', 'dag.run.running': '运行中', 'dag.run.succeeded': '成功', 'dag.run.failed': '失败', 'dag.run.cancelled': '已取消', 'dag.run.lost': '失联',

    'dag.history.head': '当前', 'dag.history.reverts': '回滚自 {vid}', 'dag.history.rollback': '回滚到 r{rev}',
    'dag.history.rollbackTitle': '把 {id} 回滚到 r{rev}', 'dag.history.withEdges': '同时恢复该版本的依赖边',
    'dag.history.withEdgesHint': '默认只恢复内容；指纹相同的旧证据会自动复活',

    'dag.why.cell': '实验格', 'dag.why.allCells': '全部', 'dag.why.fresh': '这个节点是最新的，没有需要解释的。',
    'dag.why.noChain': '没有找到可追溯的原因链。',

    'dag.agent.intro': '把这个节点交给项目会话里的 Agent（Claude 或 Codex），它会通过 DAG 工具读取细节并预览影响；任何改动都以提案形式回到这里。',
    'dag.agent.explain': '解释为什么过期', 'dag.agent.fix': '提出修复方案', 'dag.agent.ask': '问点别的',
    'dag.agent.askPh': '关于 {id} 想问什么？', 'dag.agent.send': '发送到 Agent',
    'dag.agent.note': '提示会预填到右侧 Agent 面板，你可以先修改再发送。',
    'dag.agent.explainPrompt': '请解释研究 DAG 中节点 {id}（{title}）为什么处于「{level}」状态：按因果顺序说明是哪一处改动（代码、配置、上游节点或实验结果）引起的，以及这对依赖它的结论意味着什么。可以用 rd_node / rd_explain 查看细节。\n\n当前评估给出的原因：\n{reasons}',
    'dag.agent.fixPrompt': '请为研究 DAG 中的节点 {id}（{title}，当前「{level}」）提出修复方案：在复核、修改、回滚、重新链接、重跑、证伪或放弃之间选最合适的做法并说明理由。先用 rd_impact 预览影响；不要直接应用，需要改动时用 rd_propose 提交提案。\n\n当前原因：\n{reasons}',

    'dag.preview.title': '影响预览', 'dag.preview.mode': '影响预览中', 'dag.preview.exit': '退出',
    'dag.preview.computing': '正在计算影响…',
    'dag.preview.source.edit': '假设修改', 'dag.preview.source.rollback': '回滚', 'dag.preview.source.relink': '重新链接',
    'dag.preview.source.restore': '恢复快照', 'dag.preview.source.other': '改动',
    'dag.preview.closure': '一并恢复（回滚闭包）',
    'dag.preview.reason': '理由（可选，记入日志）', 'dag.preview.reasonRequired': '理由（解锁需要）', 'dag.preview.reasonPh': '为什么做这个改动',
    'dag.preview.apply': '应用', 'dag.preview.approve': '批准', 'dag.preview.discard': '放弃',
    'dag.preview.applyQueue': '应用并安排重跑', 'dag.preview.applyQueueHint': '应用后打开“需重跑”，挑选平台排队',
    'dag.preview.fork': '另开一个尝试', 'dag.preview.forkHint': '不改现有设计：用这组配置新建一个并列实验，只跑受影响的格',
    'dag.preview.rebased': '图在预览之后有变化，这是重新计算的影响，请再确认一次。',
    'dag.preview.conflict': '图已经变了，需要重新预览：{msg}',

    'dag.revise.attestHint': '确认上游的变化不影响这个节点：把当前指纹记为已看过',
    'dag.revise.attestTitle': '复核 {id}', 
    
    
    

    
    
    

    'dag.empty.title': '这个项目还没有研究 DAG',
    'dag.empty.body': '从问题节点开始：写下要解决的问题、衡量成功的指标和阈值，以及事先定好的放弃标准。之后的文献、实验、方案和论点都会挂在它下面。',
    'dag.empty.starter': '创建问题节点',
    'dag.new.button': '新建节点', 'dag.new.title': '新建节点', 'dag.new.starterTitle': '创建问题节点',
    'dag.new.starterBody': '问题节点是整张图的起点（S0 问题定义）。放弃标准要在做任何工作之前写下，以免事后合理化。',
    'dag.new.kind': '类型', 'dag.new.stage': '阶段', 'dag.new.status': '状态',
    'dag.new.titleZh': '中文标题', 'dag.new.titleEn': '英文标题', 'dag.new.id': '节点 ID',
    'dag.new.idTaken': '{id} 已存在', 'dag.new.create': '创建', 'dag.new.createdTitle': '创建 {id}',
    'dag.new.problemPhZh': '例如：长上下文推理的尾部首 token 延迟', 'dag.new.problemPhEn': 'e.g. Tail TTFT in long-context serving',
    'dag.new.statementPh': '一两句话：在什么负载、模型和硬件上，什么问题，为什么重要',
    'dag.new.facet.statement': '陈述', 'dag.new.facet.mechanism': '机制', 'dag.new.facet.question': '要回答的问题',
    'dag.new.facet.takeaway': '要点', 'dag.new.facet.text': '论点文本', 'dag.new.facet.overview': '概述',
    'dag.new.metric': '目标指标', 'dag.new.threshold': '阈值', 'dag.new.direction': '方向', 'dag.new.lower': '越低越好', 'dag.new.higher': '越高越好',
    'dag.new.kill': '放弃标准', 'dag.new.killPh': '例如：oracle 研究显示提升空间不足 1.3×，或已有工作解决了这个问题',
    'dag.new.killHint': '事先写下何时停止，比事后判断更诚实。',
    'dag.new.altGroup': '备选方案组（回答同一个问题的并列方案）',

    
    

    

    
    
    
    
    

    'dag.toast.applied': '已应用：{title}', 'dag.toast.proposal': '已作为提案 {id} 送到收件箱：{title}', 'dag.toast.openInbox': '打开收件箱',
    'dag.toast.failed': '没有成功：{msg}', 
  },
  en: {
    'dag.subtitle2': '{n} nodes',
    'dag.view.list': 'List', 'dag.view.graph': 'Graph',
    'dag.filter.aria': 'Filter',
    'dag.filter.all': 'All', 'dag.filter.all.hint': 'Every node still in use',
    'dag.filter.proposed': 'To review', 'dag.filter.proposed.hint': 'Nodes an agent drafted that are not in effect yet',
    'dag.filter.attention': 'Needs attention', 'dag.filter.attention.hint': 'Nodes to review, to run or rerun, or waiting upstream',
    'dag.filter.confirmed': 'Confirmed', 'dag.filter.confirmed.hint': 'Confirmed or locked results',
    'dag.filter.dead': 'Abandoned', 'dag.filter.dead.hint': 'Routes refuted, abandoned or superseded, with their reasons',
    'dag.list.empty': 'No node matches this filter.',
    'dag.list.none': 'No node in this stage yet',
    'dag.list.keys': 'J / K to move · Y accepts a draft · N rejects it · ↵ details · Esc closes',
    'dag.list.undecided': 'Undecided',
    'dag.list.options': 'Options',
    'dag.list.choose': 'Choose',
    'dag.list.chosen': 'Chosen',
    'dag.list.chooseHint': 'Before anything changes, the side panel shows the impact: which nodes need a review, which experiments a rerun.',
    'dag.list.chooseTitle': 'Choose "{option}" for "{decision}"',
    'dag.list.upstream': 'Rests on',
    'dag.list.downstream': 'Used by',
    'dag.list.accept': 'Accept',
    'dag.list.reject': 'Reject',
    'dag.list.details': 'Details',
    'dag.list.accepted': 'Accepted "{title}"',
    'dag.list.askPrompt': 'Look at {id}: does it hold? Is its basis enough? What should happen next?',
    'dag.subtitleEmpty': 'Research as a build graph: every result knows what it rests on and when it needs a review or a rerun',
    'dag.view.aria': 'View', 
    
    'dag.resetLayout': 'Reset layout (forget dragged positions)',
    'dag.map.aria': 'Research map: nodes and dependencies by stage',
    'dag.rail.title': 'References and datasets', 'dag.rail.counts': '{refs} references · {data} datasets',

    
    
    

    'dag.node.stack': 'supersedes {n}', 'dag.node.stackHint': 'The versions it superseded are folded behind this card; "Show negative results" unfolds them',
    'dag.node.runsHint': 'Runs recorded',
    'dag.group.count': '{tried} tried, {chosen} chosen', 'dag.group.openHint': 'See these alternatives in the Tried lens',
    'dag.gate.open': 'Open the {gate} checklist',
    'dag.gate.state.open': 'Open', 'dag.gate.state.passed': 'Passed', 'dag.gate.state.passed_degraded': 'Passed, degraded', 'dag.gate.state.failing': 'Failing',
    'dag.gate.after': 'after {stage}', 'dag.gate.checks': '{ok}/{n} checks hold',
    'dag.gate.value': 'now {v} · needs {target}',
    'dag.gate.pass': 'Pass gate', 'dag.gate.passHint': 'Passing {gate} logs a decision and creates the snapshot gate-{gate}, so you can always come back to this state.',
    'dag.gate.note': 'Note', 'dag.gate.notePh': 'e.g. baselines reproduce within 6%, go ahead',
    'dag.gate.passed': '{gate} passed, snapshot {snap}', 'dag.gate.passedBy': 'Passed by {who} {at} · snapshot {snap}',

    'dag.flag.drift': 'Evidence values moved, but the predicate still holds', 'dag.flag.shaky': 'Rests on something under review: {via}',
    'dag.flag.impl_lag': 'Results reflect code that no longer matches the design: implement first, then rerun', 'dag.flag.reused': 'Valid through an older run',
    'dag.flag.cutoff': 'The rerun landed within tolerance; fingerprint kept', 'dag.flag.lock_alert': 'A locked node no longer holds',
    'dag.flag.unsealed': 'The YAML was edited outside the API', 'dag.flag.behind_head': 'An edge is pinned to an older version',
    'dag.flag.conflict': 'History forked in a merge; needs your call', 'dag.flag.trace_quality': 'Run trace is incomplete',
    'dag.flagShort.drift': 'drift', 'dag.flagShort.shaky': 'shaky', 'dag.flagShort.impl_lag': 'implement first', 'dag.flagShort.reused': 'reused',
    'dag.flagShort.cutoff': '≈ cutoff', 'dag.flagShort.lock_alert': 'lock alert', 'dag.flagShort.unsealed': 'unsealed',
    'dag.flagShort.behind_head': 'pinned', 'dag.flagShort.conflict': 'conflict', 'dag.flagShort.trace_quality': 'coarse trace',

    'dag.edge.input': 'input', 'dag.edge.evidence': 'evidence', 'dag.edge.basis': 'basis', 'dag.edge.implements': 'implements',
    'dag.edge.describes': 'describes', 'dag.edge.cites': 'cites', 'dag.edge.supports': 'supports', 'dag.edge.refutes': 'refutes',

    'dag.legend.title': 'Legend', 'dag.legend.status': 'Status (fill and border)', 'dag.legend.fresh': 'Freshness (ring and mark)',
    'dag.legend.edges': 'Edges', 'dag.legend.moved': 'upstream changed (facet labelled)', 'dag.legend.shapes': 'Shapes',
    'dag.legend.shapesBody': 'Rounded card: problem, finding, gap, solution · pill: reference · cylinder: dataset · cut-corner card with cells: experiment and scripted figure · pointed: decision · square: design and module · folded corner: claim and section',

    'dag.inspector.aria': 'Node details: {id}', 'dag.inspector.missing': 'The graph has no node {id} (it may have been deleted or renamed).',
    'dag.side.resize': 'Side panel width',
    'dag.tab.overview': 'Overview', 'dag.tab.edges': 'Edges', 'dag.tab.cells': 'Cells', 'dag.tab.history': 'History', 'dag.tab.why': 'Why', 'dag.tab.agent': 'Agent',
    'dag.overview.reasons': 'Why it is not fresh', 'dag.overview.shaky': 'It rests on these nodes under review:',
    'dag.overview.locked': 'Locked by {by} {at}', 'dag.overview.supersededBy': 'Superseded by', 'dag.overview.altGroup': 'Alternative of',
    'dag.overview.facets': 'Content', 'dag.overview.noFacets': 'No facets.',
    'dag.overview.created': 'Created', 'dag.overview.updated': 'Updated', 'dag.overview.vid': 'Version',
    'dag.facet.unresolved': '(unresolved: config file or key missing)',

    'dag.status.activate': 'Start', 'dag.status.confirm': 'Confirm', 'dag.status.reopen': 'Reopen', 'dag.status.lock': 'Lock',
    'dag.status.unlock': 'Unlock', 'dag.status.refute': 'Refute', 'dag.status.abandon': 'Abandon', 'dag.status.supersede': 'Supersede', 'dag.status.revive': 'Revive',
    'dag.status.activateHint': 'Move from proposed to active.',
    'dag.status.confirmHint': 'Confirming needs the node to be fresh and meet its kind\'s rule (e.g. a claim needs at least one supporting edge whose predicate holds).',
    'dag.status.reopenHint': 'Back to active so it can be changed.',
    'dag.status.lockHint': 'Any change to a locked node needs an unlock first; the locked version is recorded and tagged. Only you can lock.',
    'dag.status.unlockHint': 'The reason is logged; the lock record stays in history.',
    'dag.status.refuteHint': 'Refuting needs a reason and at least one evidence edge; on apply, node: evidence is frozen to the selected run: records, so the negative result is kept for good.',
    'dag.status.abandonHint': 'Abandoning never deletes: the node stays in the Tried lens with its reason.',
    'dag.status.supersedeHint': 'Name the successor; dependents are offered a relink.',
    'dag.status.reviveHint': 'Bring a refuted, abandoned or superseded node back to active.',
    'dag.status.dialogTitle': '{action}: {id}', 'dag.status.doneTitle': '{action} {id}',
    'dag.status.reason': 'Reason (logged with the decision)', 'dag.status.note': 'Note',
    'dag.status.abandonReason': 'Why abandon', 'dag.status.successor': 'Successor', 'dag.status.pickSuccessor': 'Pick the successor…',
    'dag.status.evidence': 'Evidence (at least one)', 'dag.status.evidencePh': 'More evidence addresses, e.g. run:r-20261101-2307-9e4d#out.tpot_ratio',
    'dag.status.freezeHint': 'On apply, node: evidence is frozen to the currently selected runs and never changes again.',
    'dag.status.reasonPh.activate': 'Why start now', 'dag.status.reasonPh.confirm': 'What it rests on',
    'dag.status.reasonPh.reopen': 'Why reopen', 'dag.status.reasonPh.lock': 'e.g. design freeze, starting evaluation',
    'dag.status.reasonPh.unlock': 'e.g. adding decode preemption', 'dag.status.reasonPh.refute': 'e.g. TPOT p99 1.21× vs vLLM on LMSYS @16 req/s',
    'dag.status.reasonPh.abandon': 'Details', 'dag.status.reasonPh.supersede': 'Why it replaces this one',
    'dag.status.reasonPh.revive': 'e.g. the bottleneck moved on new hardware',
    'dag.abandon.infeasible': 'Infeasible', 'dag.abandon.dominated': 'Dominated by another option', 'dag.abandon.no_headroom': 'No headroom',
    'dag.abandon.competitor_closed_gap': 'A competitor closed the gap', 'dag.abandon.out_of_scope': 'Out of scope', 'dag.abandon.cost': 'Too costly',
    'dag.abandon.time': 'Out of time', 'dag.abandon.other': 'Other',

    'dag.edit.title': 'Edit {id}#{facet}', 'dag.edit.typeToPreview': 'The impact previews as you type (0.3 s after you stop).',
    'dag.edit.badJson': 'Invalid JSON: {msg}', 'dag.edit.boundHint': 'A config key bound to {file}: the change is written to that file and its impact is exact.',
    'dag.edit.editorial': 'Wording only', 'dag.edit.editorialHint': 'auto-attests the direct describing nodes after apply; never touches results',
    'dag.edit.lockedHint': 'This node is locked: preview freely; applying needs the unlock box ticked.',
    'dag.edit.demoteHint': 'Editing a confirmed node moves it back to active (unless "wording only").',

    'dag.edges.out': 'It depends on ({n})', 'dag.edges.in': 'Depends on it ({n})', 'dag.edges.none': 'No edges.',
    'dag.edges.seen': 'seen', 'dag.edges.current': 'now', 'dag.edges.same': 'same', 'dag.edges.pinned': 'pinned',
    'dag.edges.attest': 'Attest', 'dag.edges.attestAll': 'Attest all ({n})',

    'dag.cells.none': 'This node has no cells.', 'dag.cells.summary': '{n} cells · {h} GPU-h in the selected runs',
    'dag.cells.cell': 'Cell', 'dag.cells.level': 'Freshness', 'dag.cells.selected': 'Selected', 'dag.cells.newest': 'Newest', 'dag.cells.newer': 'newer exists',
    'dag.cells.trace': 'Trace', 'dag.cells.platform': 'Platform',
    'dag.cells.reused': 'reused', 'dag.cells.reusedHint': 'The newest run is not valid; an older valid run is used',
    'dag.cells.cutoffHint': 'The rerun landed within tolerance; downstream need not change',
    'dag.cells.mismatch': 'Inputs that differ from the run ({n})', 'dag.cells.runs': 'Runs ({n})', 'dag.cells.noRuns': 'No runs yet.',
    'dag.cells.select': 'Select', 'dag.cells.selectHint': 'Pin this run (default: the newest valid run)', 'dag.cells.unpin': 'Unpin',
    'dag.cells.exclude': 'Exclude', 'dag.cells.excluded': 'excluded', 'dag.cells.openDiff': 'Code diff',
    'dag.cells.excludeTitle': 'Exclude run {id}', 'dag.cells.excludeBody': 'An excluded run no longer takes part in reuse (e.g. the GPU throttled). The record stays.',
    'dag.cells.excludePh': 'e.g. GPU throttled at 83°C',
    'dag.trace.traced': 'traced', 'dag.trace.declared': 'declared', 'dag.trace.coarse': 'coarse',
    'dag.run.queued': 'queued', 'dag.run.running': 'running', 'dag.run.succeeded': 'succeeded', 'dag.run.failed': 'failed', 'dag.run.cancelled': 'cancelled', 'dag.run.lost': 'lost',

    'dag.history.head': 'head', 'dag.history.reverts': 'reverts {vid}', 'dag.history.rollback': 'Roll back to r{rev}',
    'dag.history.rollbackTitle': 'Roll {id} back to r{rev}', 'dag.history.withEdges': 'Also restore that version\'s edges',
    'dag.history.withEdgesHint': 'By default only the content is restored; old evidence with the same fingerprint revives by itself',

    'dag.why.cell': 'Cell', 'dag.why.allCells': 'All', 'dag.why.fresh': 'This node is fresh; nothing to explain.',
    'dag.why.noChain': 'No traceable root cause found.',

    'dag.agent.intro': 'Hand this node to the agent of the project session (Claude or Codex). It reads the details and previews the impact through the DAG tools; any change comes back here as a proposal.',
    'dag.agent.explain': 'Explain this staleness', 'dag.agent.fix': 'Propose a fix', 'dag.agent.ask': 'Ask something else',
    'dag.agent.askPh': 'What do you want to know about {id}?', 'dag.agent.send': 'Send to agent',
    'dag.agent.note': 'The prompt is prefilled in the agent dock; edit it before sending if you like.',
    'dag.agent.explainPrompt': 'Explain why node {id} ({title}) of the research DAG is "{level}": in causal order, which change (code, config, an upstream node or an experiment result) caused it, and what it means for the results that depend on it. Use rd_node / rd_explain for details.\n\nReasons from the current evaluation:\n{reasons}',
    'dag.agent.fixPrompt': 'Propose a fix for node {id} ({title}, now "{level}") of the research DAG: choose between attest, edit, roll back, relink, rerun, refute or abandon, and say why. Preview the impact with rd_impact first; do not apply directly — submit any change with rd_propose.\n\nCurrent reasons:\n{reasons}',

    'dag.preview.title': 'Impact preview', 'dag.preview.mode': 'Impact preview', 'dag.preview.exit': 'Exit',
    'dag.preview.computing': 'Computing impact…',
    'dag.preview.source.edit': 'What-if edit', 'dag.preview.source.rollback': 'Rollback', 'dag.preview.source.relink': 'Relink',
    'dag.preview.source.restore': 'Snapshot restore', 'dag.preview.source.other': 'Change',
    'dag.preview.closure': 'Also restore (rollback closure)',
    'dag.preview.reason': 'Reason (optional, logged)', 'dag.preview.reasonRequired': 'Reason (needed to unlock)', 'dag.preview.reasonPh': 'Why this change',
    'dag.preview.apply': 'Apply', 'dag.preview.approve': 'Approve', 'dag.preview.discard': 'Discard',
    'dag.preview.applyQueue': 'Apply and plan reruns', 'dag.preview.applyQueueHint': 'Apply, then open the Rerun lens to pick a platform and queue',
    'dag.preview.fork': 'Fork as attempt instead', 'dag.preview.forkHint': 'Leave the design alone: create a sibling experiment with this config that runs only the affected cells',
    'dag.preview.rebased': 'The graph changed after the preview; this is the recomputed impact, please check again.',
    'dag.preview.conflict': 'The graph changed; preview again: {msg}',

    'dag.revise.attestHint': 'The upstream change does not affect this node: record the current fingerprint as seen',
    'dag.revise.attestTitle': 'Attest {id}', 
    
    
    

    
    
    

    'dag.empty.title': 'This project has no research DAG yet',
    'dag.empty.body': 'Start with the problem: what you want to solve, the metric and threshold that define success, and the kill criteria fixed before any work. References, experiments, solutions and claims hang off it later.',
    'dag.empty.starter': 'Create the problem node',
    'dag.new.button': 'New node', 'dag.new.title': 'New node', 'dag.new.starterTitle': 'Create the problem node',
    'dag.new.starterBody': 'The problem node is where the graph starts (S0 Frame). Write the kill criteria before any work, so they cannot be rationalized later.',
    'dag.new.kind': 'Kind', 'dag.new.stage': 'Stage', 'dag.new.status': 'Status',
    'dag.new.titleZh': 'Chinese title', 'dag.new.titleEn': 'English title', 'dag.new.id': 'Node id',
    'dag.new.idTaken': '{id} already exists', 'dag.new.create': 'Create', 'dag.new.createdTitle': 'Create {id}',
    'dag.new.problemPhZh': '例如：长上下文推理的尾部首 token 延迟', 'dag.new.problemPhEn': 'e.g. Tail TTFT in long-context serving',
    'dag.new.statementPh': 'One or two sentences: which problem, on which workloads, models and hardware, and why it matters',
    'dag.new.facet.statement': 'Statement', 'dag.new.facet.mechanism': 'Mechanism', 'dag.new.facet.question': 'Question',
    'dag.new.facet.takeaway': 'Takeaway', 'dag.new.facet.text': 'Claim text', 'dag.new.facet.overview': 'Overview',
    'dag.new.metric': 'Target metric', 'dag.new.threshold': 'Threshold', 'dag.new.direction': 'Direction', 'dag.new.lower': 'lower is better', 'dag.new.higher': 'higher is better',
    'dag.new.kill': 'Kill criteria', 'dag.new.killPh': 'e.g. the oracle study shows < 1.3× headroom, or published work already closes the gap',
    'dag.new.killHint': 'Deciding in advance when to stop is more honest than deciding afterwards.',
    'dag.new.altGroup': 'Alternative group (siblings answering the same question)',

    
    

    

    
    
    
    
    

    'dag.toast.applied': 'Applied: {title}', 'dag.toast.proposal': 'Sent to the Inbox as proposal {id}: {title}', 'dag.toast.openInbox': 'Open Inbox',
    'dag.toast.failed': 'Did not go through: {msg}', 
  },
});
