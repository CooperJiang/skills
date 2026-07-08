# claude-skills

个人 skills 集合,一键安装进 **[Claude Code](https://claude.com/claude-code)**(`~/.claude/skills/`)**与 Codex**(`~/.codex/skills/`)——两者用同一套 `SKILL.md` 格式,一个 skill 同时喂两个工具。每个 skill 一个子目录(含 `SKILL.md`),加新 skill = 丢个新文件夹,零配置。

> skill 若只适用单平台,在其 `SKILL.md` frontmatter 写 `targets: claude`(或 `codex`)即可限制;缺省两边都装。

## 安装

### 方式一:克隆 + CLI(推荐,多机 git pull 即时同步)
```bash
git clone <这个仓库> ~/code/claude-skills   # 位置随意
cd ~/code/claude-skills
node bin/claude-skills.js list               # 先看有哪些 skill
node bin/claude-skills.js install --all      # 全装;或只装某个 ↓
node bin/claude-skills.js install recall     # 只装 recall(按需挑)
```
之后每台机器 `git pull` 就同步(软链接指向仓库,改动即时生效,无需重装)。
> **给别人用**:把这个仓库地址发给他即可,照着本 README 跑上面三行就行。`list` 会列出所有 skill 和各自说明,他挑要的 `install <名字>`。

### 方式二:npm(发布后)
```bash
npm i -g @xiaojiu/claude-skills
claude-skills install --all
```
> 发布前把 `package.json` 的 `name` 换成你自己的 npm 用户名/scope。本地可先 `npm link` 试用。

### 方式三:无 Node 兜底
```bash
bash scripts/install.sh all
```

## CLI

```
claude-skills list                    列出仓库 skill 与安装状态
claude-skills install <name|--all>    安装(默认 symlink;--copy 复制;--force 覆盖已存在)
claude-skills uninstall <name|--all>  卸载(只删链接)
claude-skills doctor                  环境自检(python3 / node / 目标目录)
```

- **默认 symlink**:`~/.claude/skills/<name>` → 仓库里的 skill,`git pull` 即更新。
- **`--copy`**:复制安装(适合 npm 全局装、不想依赖仓库常驻的场景)。
- **`--force`**:目标已存在时覆盖;若是真实目录会先备份成 `.bak-<时间戳>`。

安装后**新开一个对话**即可用(已开着的会话需重启才发现新 skill)。

## Skill 目录

> 一览表(装哪个心里有数),下面每个 skill 有单独一节讲清用途和装法。

| skill | 适用工具 | 依赖 | 一句话 |
|---|---|---|---|
| [recall](#recall) | Claude · Codex | python3 | 会话/上下文/记忆管家:找回历史对话、按深度读取、跨对话合并、归档、沉淀记忆 |

<!-- 新增 skill:在上表加一行,并在下面照 recall 的格式补一节 -->

### recall
**装:** `claude-skills install recall` ·  **触发:** 在对话里输入 `/recall`

走中转的人常遇到:老会话账号过期后 `claude -r` / `codex resume` 恢复不了,只能新开对话。recall 直接读本地 transcript 把上下文捞回来,绕开这个限制。能力:

- **找回并接手**:复刻 `claude -r` 列表让你挑,按 **简读/标准/详读/超详读** 分层读取(含 Claude 自动压缩的“全局记忆”),合成「任务+进度+待办」简报接着干。
- **跨对话合并**:一次拉多段会话上下文。
- **归档/删除**:给会话列表瘦身(默认软删可恢复,硬删需二次确认)。
- **持久记忆**:把接手简报沉淀成每段对话的 digest,下次秒读。
- **打包/携带记忆**:`pack` 把某段对话导出成自包含文件(存 `~/.recall-packs/`),换目录/换机器/给别人后 `load` 即还原——解决「换目录就扫不到旧对话」。
- **双工具自适应**:自动识别被 Claude 还是 Codex 调用,读对应历史(`~/.claude/projects` / `~/.codex/sessions`)。
- **跨工具读取**:`--provider both` 一屏合并两边、按工具标记;在 Claude 里能接手 Codex 在本项目的活,反之亦然(同项目按 cwd 归属)。

## 加一个新 skill
1. 在 `skills/` 下建目录 `skills/<你的skill>/`,放 `SKILL.md`(带 frontmatter:`name` / `description`;只想装单平台就加 `targets: claude` 或 `codex`)+ 需要的脚本。
2. 在上面 **Skill 目录** 的表格加一行,并照 `recall` 的格式补一节说明。
3. `claude-skills install <你的skill>`,提交推送;其他机器 `git pull` 后 `claude-skills install <你的skill>`。
