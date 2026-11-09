// Strings of the Settings view (prefix st.). Product names, commands and paths stay as they are.
import { registerStrings } from '../../i18n';

registerStrings({
  zh: {
    'st.subtitle': '新项目、资源池、本机集成、外观和文件位置',
    
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
    'st.app.lead': 'Radix Themes 的主题：配色、圆角和背景，整个界面一起变。',
    'st.app.themes': '主题',
    'st.app.themesHint': '配色和背景取自 radix-ui.com',
    'st.app.theme.radix-red': 'Radix 红',
    'st.app.theme.radix-indigo': 'Radix 靛蓝',
    'st.app.theme.radix-teal': 'Radix 青绿',
    'st.app.theme.custom': '自定义',
    'st.app.mode': '明暗',
    'st.app.modeHint': '只对这个浏览器生效；其余外观所有浏览器共用。',
    'st.app.accent': '强调色',
    'st.app.radius': '圆角',
    'st.app.radius.none': '无',
    'st.app.radius.small': '小',
    'st.app.radius.medium': '中',
    'st.app.radius.large': '大',
    'st.app.radius.full': '全圆',
    'st.app.bg': '背景',
    'st.app.bgHint': '点一个试试',
    'st.app.bg.radix': 'Radix 图案',
    'st.app.bg.ribbons': '丝带',
    'st.app.bg.gradient': '渐变',
    'st.app.bg.glow': '柔光',
    'st.app.bg.plain': '纯色',
    'st.app.bg.image': '图片',
    'st.app.upload': '上传图片…',
    'st.app.replace': '换一张图片…',
    'st.app.uploading': '正在上传…',
    'st.app.removeImage': '移除图片',
    'st.app.reset': '恢复默认',
    'st.app.blur': '图片模糊',
    'st.app.imageNote': '上传的图片只存在这台电脑的 Research Deck 设置里，换背景不会改动项目文件。',
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
    'st.subtitle': 'New projects, resource pools, local integrations, appearance and where files live',
    
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
    'st.app.lead': 'The Radix Themes theme: colors, radius and background, for the whole interface.',
    'st.app.themes': 'Theme',
    'st.app.themesHint': 'Colors and backgrounds from radix-ui.com',
    'st.app.theme.radix-red': 'Radix red',
    'st.app.theme.radix-indigo': 'Radix indigo',
    'st.app.theme.radix-teal': 'Radix teal',
    'st.app.theme.custom': 'Custom',
    'st.app.mode': 'Light or dark',
    'st.app.modeHint': 'For this browser only; the rest of the appearance is the same in all your browsers.',
    'st.app.accent': 'Accent',
    'st.app.radius': 'Radius',
    'st.app.radius.none': 'None',
    'st.app.radius.small': 'Small',
    'st.app.radius.medium': 'Medium',
    'st.app.radius.large': 'Large',
    'st.app.radius.full': 'Full',
    'st.app.bg': 'Background',
    'st.app.bgHint': 'Click one to try it',
    'st.app.bg.radix': 'Radix art',
    'st.app.bg.ribbons': 'Ribbons',
    'st.app.bg.gradient': 'Gradient',
    'st.app.bg.glow': 'Glow',
    'st.app.bg.plain': 'Plain',
    'st.app.bg.image': 'Picture',
    'st.app.upload': 'Upload a picture…',
    'st.app.replace': 'Another picture…',
    'st.app.uploading': 'Uploading…',
    'st.app.removeImage': 'Remove the picture',
    'st.app.reset': 'Reset to default',
    'st.app.blur': 'Picture blur',
    'st.app.imageNote': "An uploaded picture stays in this computer's Research Deck settings; changing the background never touches project files.",
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
