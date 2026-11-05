// Strings of the Settings view (prefix st.). Product names, commands and paths stay as they are.
import { registerStrings } from '../../i18n';

registerStrings({
  zh: {
    'st.subtitle': '本机集成、外观和文件位置',
    
    'st.sec.integrations': '集成',
    'st.sec.appearance': '外观',
    'st.sec.about': '关于',
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    'st.int.clis': 'Agent CLI',
    'st.int.found': '已找到',
    'st.int.missing': '未找到',
    'st.int.cliHint': '找不到时可用环境变量 RD_CLAUDE_CLI / RD_CODEX_CLI 指定路径，然后重启 Research Deck。',
    'st.int.apps': '绘图应用',
    'st.int.installed': '已安装',
    'st.int.notInstalled': '未安装',
                'st.int.present': '已就绪',
    'st.int.absent': '没有',
        'st.int.fakeAgent': '模拟 Agent 模式已开启（RD_FAKE_AGENT=1）：所有回答来自离线的假 Agent。',
    'st.app.lang': '界面语言',
    'st.app.langHint': '论文正文、代码和图里的文字不随界面语言翻译。',
    'st.app.theme': '主题',
    'st.about.version': '版本',
    'st.about.server': '后端地址',
    'st.about.app': '程序目录',
    'st.about.local': '本机状态（不进 git）',
    'st.about.project': '项目目录',
    'st.about.research': '项目状态 .research',
    'st.about.docs': '文档',
    'st.about.docsHint': '架构约定、HTTP 接口与磁盘格式、研究 DAG 规范',
  },
  en: {
    'st.subtitle': 'Local integrations, appearance and where files live',
    
    'st.sec.integrations': 'Integrations',
    'st.sec.appearance': 'Appearance',
    'st.sec.about': 'About',
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    'st.int.clis': 'Agent CLIs',
    'st.int.found': 'found',
    'st.int.missing': 'not found',
    'st.int.cliHint': 'If one is missing, set RD_CLAUDE_CLI / RD_CODEX_CLI to its path and restart Research Deck.',
    'st.int.apps': 'Figure apps',
    'st.int.installed': 'installed',
    'st.int.notInstalled': 'not installed',
                'st.int.present': 'present',
    'st.int.absent': 'none',
        'st.int.fakeAgent': 'Fake agent mode is on (RD_FAKE_AGENT=1): every answer comes from the offline fake agent.',
    'st.app.lang': 'Interface language',
    'st.app.langHint': 'Paper text, code and the labels inside figures are never translated by the UI.',
    'st.app.theme': 'Theme',
    'st.about.version': 'Version',
    'st.about.server': 'Server',
    'st.about.app': 'Application',
    'st.about.local': 'Machine-local state (not in git)',
    'st.about.project': 'Project folder',
    'st.about.research': 'Project state, .research',
    'st.about.docs': 'Documentation',
    'st.about.docsHint': 'Conventions, the HTTP API and on-disk formats, the research DAG spec',
  },
});
