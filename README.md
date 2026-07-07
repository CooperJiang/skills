# claude-skills

个人 [Claude Code](https://claude.com/claude-code) skills 集合,一键安装进 `~/.claude/skills/`。
每个 skill 一个子目录(含 `SKILL.md`),加新 skill = 丢个新文件夹,零配置。

## 安装

### 方式一:克隆 + CLI(推荐,多机 git pull 即时同步)
```bash
git clone <这个仓库> ~/code/claude-skills   # 位置随意
cd ~/code/claude-skills
node bin/claude-skills.js install --all      # 默认软链接进 ~/.claude/skills/
```
之后每台机器 `git pull` 就同步(软链接指向仓库,改动即时生效,无需重装)。

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

## 现有 skill

| skill | 说明 |
|---|---|
| **recall** | Claude 的记忆/上下文管家:在对话里复刻 `claude -r`,找回历史会话、按分层深度读取(含自动压缩的“全局记忆”)、跨对话合并、归档/删除老会话、沉淀持久 digest。需 `python3`。 |

## 加一个新 skill
1. 在 `skills/` 下建目录 `skills/<你的skill>/`,放 `SKILL.md`(带 frontmatter:`name` / `description`)+ 需要的脚本。
2. `claude-skills install <你的skill>`(或 `--all`)。
3. 提交推送,其他机器 `git pull` 后 `claude-skills install <你的skill>`。
