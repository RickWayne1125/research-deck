// Strings of the agent dock and the top-bar agent chip (prefix ag.). The core agent.* strings live in i18n/core.ts.
// Product names (Claude Code, Codex) and model ids stay as they are.
import { registerStrings } from '../i18n';

registerStrings({
  zh: {
    'ag.provider.claude': 'Claude Code',
    'ag.provider.codex': 'Codex',
    'ag.provider.fake': '模拟 Agent',
    'ag.switching': '正在把对话交给 {agent}…',
    'ag.switchHint': '换后端时，对话要点会自动交给另一个 Agent；之后两边都能看到这段对话。',
    'ag.newChat': '新对话',
    'ag.copyResume': '复制在终端继续的命令',
    'ag.copiedResume': '已复制：在终端里粘贴即可接着这个会话',
    'ag.perm.readFoot': '只读 · 地图改动先变成提议',
    'ag.perm.writeFoot': '可以直接改项目文件',
    
    
    
    'ag.closeDock': '收起 Agent 面板',
    'ag.fastNone': '这个模型没有 Fast 档位',
    'ag.perm.read': '只读',
    'ag.perm.write': '可写',
    'ag.perm.readHint': '只能读取项目文件和 DAG',
    'ag.perm.writeHint': '可以直接修改项目文件',
    
    
    
    
    'ag.handoff.failed': '交接失败：{error}',
    'ag.handoff.line': '{from} → {to}，上下文已交接',
    
    'ag.handoff.note': '{from} 给 {to} 留了备注',
    'ag.handoff.file': '交接记录：{file}',
    'ag.session.none': '尚无会话',
    
    'ag.session.newDone': '已开新会话，下一条消息会创建它',
    
    'ag.bind.title': '绑定已有会话',
    'ag.bind.hint': '在这个项目文件夹里开过的 Claude Code 和 Codex 会话。绑定后，项目对话接着这个会话往下聊。',
    'ag.bind.all': '全部',
    'ag.bind.empty': '没有找到工作目录是本项目的会话。',
    'ag.bind.turns': '{n} 轮',
    'ag.bind.current': '当前会话',
    'ag.bind.bind': '绑定',
    'ag.bind.untitled': '（无标题）',
    'ag.log.showImported': '显示会话日志里的对话',
    'ag.log.imported': '会话日志',
    'ag.log.importedHint': '在仪表盘之外（终端或 Codex Desktop）与这个会话的对话，只读',
    'ag.log.loadError': '对话记录加载失败：{error}',
    
    'ag.cancelled': '已停止',
    'ag.usage': '{input} 输入 · {output} 输出',
    'ag.usageCached': '缓存 {n}',
    'ag.cost': '${cost}',
    'ag.duration': '{s} 秒',
    'ag.tools': '{n} 次工具调用',
    'ag.ctx.node': '节点',
    'ag.ctx.file': '文件',
    'ag.ctx.selection': '选中内容',
    'ag.ctx.lines': '第 {a}–{b} 行',
    'ag.ctx.extra': '附加说明',
    'ag.ctx.remove': '移除这项上下文',
    'ag.ctx.fromRoute': '当前位置',
    'ag.sendHint': '⌘↵ 发送',
    'ag.fakeMode': '模拟模式（RD_FAKE_AGENT=1）：回答由离线的假 Agent 生成，不会调用 CLI。',
    'ag.chip.running': '运行中',
  },
  en: {
    'ag.provider.claude': 'Claude Code',
    'ag.provider.codex': 'Codex',
    'ag.provider.fake': 'Fake agent',
    'ag.switching': 'Handing the conversation to {agent}…',
    'ag.switchHint': 'Switching backend hands the gist to the other agent; both then see this conversation.',
    'ag.newChat': 'New conversation',
    'ag.copyResume': 'Copy the command to continue in a terminal',
    'ag.copiedResume': 'Copied: paste it in a terminal to continue this session',
    'ag.perm.readFoot': 'Read only · map changes become proposals',
    'ag.perm.writeFoot': 'May edit project files',
    
    
    
    'ag.closeDock': 'Close the agent dock',
    'ag.fastNone': 'This model has no fast tier',
    'ag.perm.read': 'Read',
    'ag.perm.write': 'Write',
    'ag.perm.readHint': 'Reads project files and the DAG only',
    'ag.perm.writeHint': 'May edit project files directly',
    
    
    
    
    'ag.handoff.failed': 'Handoff failed: {error}',
    'ag.handoff.line': '{from} → {to}, context handed off',
    
    'ag.handoff.note': '{from} left a note for {to}',
    'ag.handoff.file': 'Handoff note: {file}',
    'ag.session.none': 'no session yet',
    
    'ag.session.newDone': 'New session; the next message creates it',
    
    'ag.bind.title': 'Bind an existing session',
    'ag.bind.hint': 'Claude Code and Codex sessions started in this project folder. Once bound, the project conversation continues that session.',
    'ag.bind.all': 'All',
    'ag.bind.empty': 'No session has this project as its working folder.',
    'ag.bind.turns': '{n} turns',
    'ag.bind.current': 'current',
    'ag.bind.bind': 'Bind',
    'ag.bind.untitled': '(untitled)',
    'ag.log.showImported': 'Show messages from the session log',
    'ag.log.imported': 'session log',
    'ag.log.importedHint': 'Exchanged with this session outside the dashboard (terminal, Codex Desktop); read-only',
    'ag.log.loadError': 'Could not load the transcript: {error}',
    
    'ag.cancelled': 'Stopped',
    'ag.usage': '{input} in · {output} out',
    'ag.usageCached': '{n} cached',
    'ag.cost': '${cost}',
    'ag.duration': '{s} s',
    'ag.tools': '{n} tool calls',
    'ag.ctx.node': 'Node',
    'ag.ctx.file': 'File',
    'ag.ctx.selection': 'Selection',
    'ag.ctx.lines': 'lines {a}–{b}',
    'ag.ctx.extra': 'Note',
    'ag.ctx.remove': 'Remove this context',
    'ag.ctx.fromRoute': 'where you are',
    'ag.sendHint': '⌘↵ to send',
    'ag.fakeMode': 'Fake mode (RD_FAKE_AGENT=1): answers come from the offline fake agent; no CLI is called.',
    'ag.chip.running': 'running',
  },
});
