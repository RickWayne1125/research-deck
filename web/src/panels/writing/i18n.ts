// Strings of the Writing panel (prefix wr.). The paper's own text is never translated.
import { registerStrings } from '../../i18n';

registerStrings({
  zh: {
    'wr.tab.text': '正文',
    'wr.tab.figures': '图',
    'wr.proofread': 'AI 校对',
    'wr.proofreadSel': '校对选中部分',
    'wr.review.running': '正在校对：{pass}',
    'wr.review.open': '{n} 条建议',
    'wr.review.prev': '上一条建议',
    'wr.review.next': '下一条建议',
    'wr.all': '接受全部',
    'wr.all.hint': '把所有还没处理的建议一次改进正文，可以撤销（⌥⌘K）',
    'wr.all.none': '没有可以直接接受的建议',
    'wr.all.done': '已接受 {n} 条建议',
    'wr.docs': '文稿',
    'wr.docs.filter': '筛选文稿…',
    'wr.docs.empty': '论文目录、docs/ 和 notes/ 下还没有 .tex 或 .md 文件。',
    'wr.docs.words': '{n} 词',
    'wr.docs.stale': '{n} 条论点需复核',
    'wr.docs.claims': '{n} 条论点，均为最新',
    'wr.docs.toggle': '收起或展开文稿列表',
    'wr.docs.resize': '文稿列表宽度',
    'wr.docs.refresh': '刷新文稿列表',
    'wr.noDoc.title': '选择一篇文稿',
    'wr.noDoc.body': '左侧列出论文目录、docs/ 与 notes/ 下的 LaTeX 和 Markdown 文件。',
    'wr.loadError': '无法打开文稿：{msg}',

    'wr.status.saved': '已保存',
    'wr.status.dirty': '未保存',
    'wr.status.saving': '正在保存…',
    'wr.status.error': '保存失败',
    'wr.status.conflict': '磁盘上的文件已变',
    'wr.status.restored': '已恢复旧版本，尚未保存',
    'wr.words': '{n} 词',
    'wr.save': '保存',
    'wr.mode.edit': '编辑',
    'wr.mode.preview': '预览',
    'wr.preview.note': '轻量预览，不是完整的 LaTeX 排版：引用显示为 [key]，交叉引用显示为 ?',
    'wr.pv.abstract': '摘要',
    'wr.pv.figure': '图',
    'wr.pv.table': '表',
    'wr.pv.algorithm': '算法',
    'wr.pv.input': '引入文件',
    'wr.pv.references': '参考文献',
    'wr.pv.code': '代码',

    'wr.check': '检查',
    'wr.check.hint': '按固定顺序运行选中的检查（{key}）',
    
    
    
    'wr.check.cancel': '停止检查',
    'wr.check.failed': '检查失败：{msg}',
    'wr.pass.typo': '错字',
    'wr.pass.terminology': '术语',
    'wr.pass.wording': '措辞',
    'wr.pass.consistency': '一致性',
    'wr.pass.logic': '逻辑',
    
    
    
    
    
    
    

    
    
    
    'wr.fix.undo': '撤销',
    'wr.fix.undone': '已恢复 {n} 处原文。',

    
    
    
    
    
    

    'wr.finding.accept': '接受',
    'wr.finding.reject': '拒绝',
    'wr.finding.ack': '已处理',
    'wr.finding.notIssue': '不是问题',
    'wr.finding.advisory': '没有可直接替换的文字，需要你来判断',
    'wr.finding.delete': '删除这段文字',
    'wr.finding.related': '参照',
    'wr.finding.line': '第 {n} 行',
    'wr.finding.lessCertain': '把握较小',
    'wr.finding.stale': '所在文字已改动，此条不再适用。',
    'wr.finding.accepted': '已接受',
    'wr.finding.rejected': '已拒绝',
    'wr.finding.reopen': '撤回',
    'wr.why.ask': '为什么拒绝？（可选，理由会记成一条规则）',
    'wr.why.skip': '跳过',
    'wr.why.other': '其他原因，回车确认',
    'wr.why.1': '此处有意为之',
    'wr.why.2': '不是同一个东西',
    'wr.why.3': '过于挑剔',
    'wr.why.4': '判断有误',
    'wr.why.learned': '已记成规则：{text}',

    'wr.kind.typo': '错字', 'wr.kind.grammar': '语法', 'wr.kind.punctuation': '标点', 'wr.kind.latex': 'LaTeX', 'wr.kind.math': '公式',
    'wr.kind.term': '术语', 'wr.kind.acronym': '缩写', 'wr.kind.wording': '措辞', 'wr.kind.number': '数字', 'wr.kind.notation': '记号',
    'wr.kind.claim': '论断', 'wr.kind.reference': '引用', 'wr.kind.unsupported': '缺少支撑', 'wr.kind.leap': '推理跳跃',
    'wr.kind.gap': '缺环', 'wr.kind.order': '顺序', 'wr.kind.overclaim': '言过其实',

    
    
    
    
    
    
    
    
    

    'wr.versions': '版本',
    'wr.versions.snapshot': '立即快照',
    'wr.versions.label': '快照说明（可选）',
    'wr.versions.snapshots': '快照',
    'wr.versions.git': 'Git 历史',
    'wr.versions.empty': '还没有快照或 Git 记录。',
    'wr.versions.pick': '选择一个版本，与当前文本对比。',
    'wr.versions.restore': '恢复到编辑器',
    'wr.versions.restored': '已把“{label}”恢复到编辑器，尚未保存：{save} 保留，⌘Z 撤销。',
    'wr.versions.this': '该版本',
    'wr.versions.current': '当前文本',
    'wr.versions.auto': '自动',
    'wr.versions.same': '与当前文本相同。',
    'wr.versions.words': '{n} 词',

    'wr.conflict.title': '这个文件在磁盘上被改动了',
    'wr.conflict.body': '你编辑期间，别的程序或 Agent 改写了它。自动保存已暂停。',
    'wr.conflict.reload': '载入磁盘版本',
    'wr.conflict.merge': '对比并合并',
    'wr.conflict.keep': '用我的版本覆盖',
    'wr.conflict.disk': '磁盘上的版本',
    'wr.conflict.mine': '我的版本（可编辑）',
    'wr.conflict.saveMerged': '保存合并结果',
    'wr.conflict.hint': '点中间的箭头，把磁盘上的改动搬到右侧；右侧就是将要保存的文本。',
    'wr.external': '磁盘上的文件已更新，已重新载入。',

    'wr.ask.hint': '把选中的文字（或整篇文稿）交给写作面板的 Agent',
    'wr.ask.selection': '请看选中的这段文字：哪里可以写得更清楚、更紧凑？保持数字、引用、记号和限定语不变。',
    'wr.ask.doc': '请通读这篇文稿，指出最需要修改的三处，并说明理由。',

    'wr.claims.open': '在 DAG 中打开',
    'wr.claims.evidence': '证据',
    'wr.claims.values': '数值',
    'wr.claims.section': '章节锚点',
    'wr.card.close': '关闭',
  },
  en: {
    'wr.tab.text': 'Text',
    'wr.tab.figures': 'Figures',
    'wr.proofread': 'AI proofread',
    'wr.proofreadSel': 'Proofread selection',
    'wr.review.running': 'Proofreading: {pass}',
    'wr.review.open': '{n} suggestions',
    'wr.review.prev': 'Previous suggestion',
    'wr.review.next': 'Next suggestion',
    'wr.all': 'Accept all',
    'wr.all.hint': 'Apply every open suggestion as one edit; it can be undone (⌥⌘K)',
    'wr.all.none': 'No suggestion can be applied directly',
    'wr.all.done': 'Accepted {n} suggestions',
    'wr.docs': 'Documents',
    'wr.docs.filter': 'Filter documents…',
    'wr.docs.empty': 'No .tex or .md files under the paper dir, docs/ or notes/ yet.',
    'wr.docs.words': '{n} words',
    'wr.docs.stale': '{n} claims need review',
    'wr.docs.claims': '{n} claims, all fresh',
    'wr.docs.toggle': 'Collapse or expand the document list',
    'wr.docs.resize': 'Document list width',
    'wr.docs.refresh': 'Refresh the document list',
    'wr.noDoc.title': 'Pick a document',
    'wr.noDoc.body': 'The list holds the LaTeX and Markdown files under the paper dir, docs/ and notes/.',
    'wr.loadError': 'Could not open the document: {msg}',

    'wr.status.saved': 'Saved',
    'wr.status.dirty': 'Unsaved',
    'wr.status.saving': 'Saving…',
    'wr.status.error': 'Save failed',
    'wr.status.conflict': 'Changed on disk',
    'wr.status.restored': 'Restored, not saved',
    'wr.words': '{n} words',
    'wr.save': 'Save',
    'wr.mode.edit': 'Edit',
    'wr.mode.preview': 'Preview',
    'wr.preview.note': 'A light preview, not full LaTeX typesetting: citations show as [key], cross-references as ?',
    'wr.pv.abstract': 'Abstract',
    'wr.pv.figure': 'Figure',
    'wr.pv.table': 'Table',
    'wr.pv.algorithm': 'Algorithm',
    'wr.pv.input': 'Input file',
    'wr.pv.references': 'References',
    'wr.pv.code': 'Code',

    'wr.check': 'Check',
    'wr.check.hint': 'Run the chosen checks in their fixed order ({key})',
    
    
    
    'wr.check.cancel': 'Stop the check',
    'wr.check.failed': 'The check failed: {msg}',
    'wr.pass.typo': 'Typos',
    'wr.pass.terminology': 'Terminology',
    'wr.pass.wording': 'Wording',
    'wr.pass.consistency': 'Consistency',
    'wr.pass.logic': 'Logic',
    
    
    
    
    
    
    

    
    
    
    'wr.fix.undo': 'Undo',
    'wr.fix.undone': 'Put back {n} original(s).',

    
    
    
    
    
    

    'wr.finding.accept': 'Accept',
    'wr.finding.reject': 'Reject',
    'wr.finding.ack': 'Done',
    'wr.finding.notIssue': 'Not an issue',
    'wr.finding.advisory': 'No drop-in replacement; this needs your judgment',
    'wr.finding.delete': 'Delete this text',
    'wr.finding.related': 'See',
    'wr.finding.line': 'line {n}',
    'wr.finding.lessCertain': 'Less certain',
    'wr.finding.stale': 'The text has changed; this finding no longer applies.',
    'wr.finding.accepted': 'Accepted',
    'wr.finding.rejected': 'Rejected',
    'wr.finding.reopen': 'Reopen',
    'wr.why.ask': 'Why reject it? (optional; the reason becomes a rule)',
    'wr.why.skip': 'Skip',
    'wr.why.other': 'Other reason, then ↵',
    'wr.why.1': 'Deliberate here',
    'wr.why.2': 'Not the same thing',
    'wr.why.3': 'Too picky',
    'wr.why.4': 'The finding is wrong',
    'wr.why.learned': 'Learned a rule: {text}',

    'wr.kind.typo': 'Typo', 'wr.kind.grammar': 'Grammar', 'wr.kind.punctuation': 'Punctuation', 'wr.kind.latex': 'LaTeX', 'wr.kind.math': 'Math',
    'wr.kind.term': 'Term', 'wr.kind.acronym': 'Acronym', 'wr.kind.wording': 'Wording', 'wr.kind.number': 'Number', 'wr.kind.notation': 'Notation',
    'wr.kind.claim': 'Claim', 'wr.kind.reference': 'Reference', 'wr.kind.unsupported': 'Unsupported', 'wr.kind.leap': 'Leap',
    'wr.kind.gap': 'Gap', 'wr.kind.order': 'Order', 'wr.kind.overclaim': 'Overclaim',

    
    
    
    
    
    
    
    
    

    'wr.versions': 'Versions',
    'wr.versions.snapshot': 'Snapshot now',
    'wr.versions.label': 'Label (optional)',
    'wr.versions.snapshots': 'Snapshots',
    'wr.versions.git': 'Git history',
    'wr.versions.empty': 'No snapshots or git history yet.',
    'wr.versions.pick': 'Pick a version to compare with the current text.',
    'wr.versions.restore': 'Restore into the editor',
    'wr.versions.restored': 'Restored “{label}” into the editor, not saved yet: {save} keeps it, ⌘Z undoes it.',
    'wr.versions.this': 'This version',
    'wr.versions.current': 'Current text',
    'wr.versions.auto': 'auto',
    'wr.versions.same': 'Same as the current text.',
    'wr.versions.words': '{n} words',

    'wr.conflict.title': 'This file changed on disk',
    'wr.conflict.body': 'Another program or an agent rewrote it while you were editing. Autosave is paused.',
    'wr.conflict.reload': 'Load the disk version',
    'wr.conflict.merge': 'Compare and merge',
    'wr.conflict.keep': 'Overwrite with mine',
    'wr.conflict.disk': 'On disk',
    'wr.conflict.mine': 'Mine (editable)',
    'wr.conflict.saveMerged': 'Save the merge',
    'wr.conflict.hint': 'Use the arrows between the sides to bring changes from disk into yours; the right side is what gets saved.',
    'wr.external': 'The file changed on disk and was reloaded.',

    'wr.ask.hint': 'Send the selection (or the whole document) to the writing panel’s agent',
    'wr.ask.selection': 'Look at the selected text: where could it be clearer or tighter? Keep the numbers, citations, notation and hedges as they are.',
    'wr.ask.doc': 'Read this document and point out the three places that most need revision, with reasons.',

    'wr.claims.open': 'Open in the DAG',
    'wr.claims.evidence': 'Evidence',
    'wr.claims.values': 'Values',
    'wr.claims.section': 'Section anchor',
    'wr.card.close': 'Close',
  },
});
