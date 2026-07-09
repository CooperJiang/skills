# recall 使用文档(场景化)

> recall 是「会话 / 上下文 / 记忆管家」。核心解决:**走中转的人,老会话账号过期后 `claude -r` / `codex resume` 恢复不了,只能新开对话**——recall 直接读本地 transcript 把上下文捞回来。同时支持跨对话合并、跨目录携带、跨工具(Claude ↔ Codex)读取、归档清理、持久记忆沉淀。

---

## 0. 两种用法:对 AI 说 vs 直接敲命令

recall 有两层皮:

- **对 AI 说话(推荐,日常这样用)**:直接说「找回上次那个对话」「打包当前记忆」「跨工具看看这个项目」,AI 会替你跑命令、整理成简报。**两个工具的触发入口不同**:
  - **Claude Code**:斜杠命令 `/recall`(会自动补全)。
  - **Codex**:**没有** `/recall`(斜杠是 Codex 内置命令)。用美元符 **`$recall`** 显式调用,或直接说人话(如"用 recall 找回上次对话")让 Codex 自动触发。Codex 里技能出现在技能列表/chips 里,不是斜杠。
- **直接命令行(想手动/写脚本时)**:`python3 ~/.claude/skills/recall/recall.py <子命令> ...`。下文每个场景都给了对应命令。

> 命令里的路径 `~/.claude/skills/recall/recall.py` 是安装后的软链;从仓库直接跑也行:`python3 <仓库>/skills/recall/recall.py`。

**几个通用概念**(先扫一眼,后面场景会用到):

| 概念 | 说明 |
|---|---|
| **provider** | 读哪个工具的历史:`auto`(默认,自动判断当前工具)/ `claude` / `codex` / `both`(两个都读) |
| **读取深度** | `简读` / `标准` / `详读` / `超详读`,决定读多少结构化信号(见 §2) |
| **全局记忆** | Claude 上下文满时自动压缩出的整段摘要(`isCompactSummary`),比"读几轮尾巴"值钱得多 |
| **digest** | 你接手后 AI 沉淀的持久简报,存 `~/.<tool>/recall-digests/`,下次秒读 |
| **pack(记忆包)** | 把一段对话导出成自包含 md,存 `~/.recall-packs/`,可跨目录/跨机/给别人 |

---

## 1. 场景:新开对话,找回上一段(最常用)

**你说**:`/recall`  或「帮我找回上次那个对话,接着干」

**发生什么**:
1. AI 跑 `recall list`,列出本项目历史会话(和 `claude -r` 一样,带你 `/rename` 的别名、时间、分支、大小)。
2. AI 把列表给你,你**报序号或别名**(可多个),并说**读取深度**。
3. AI 跑 `recall show <序号> --depth <深度>`,抽出全局记忆 / 意图主线 / 改动文件 / TODO / 结尾轮,合成「任务 + 进度 + 待办」简报,接着干。

**手动命令**:
```bash
python3 ~/.claude/skills/recall/recall.py list
python3 ~/.claude/skills/recall/recall.py show 4 --depth 标准
```

---

## 2. 场景:选择读取的详细程度

深度不是"读几轮尾巴",而是"读哪些信号"。按需选:

| 深度 | 全局记忆 | 用户意图主线 | 结尾轮 | 改动文件 | 什么时候用 |
|---|---|---|---|---|---|
| **简读** | 最近1段(截断) | — | 6 | 12 | 只想快速知道"停在哪" |
| **标准**(默认) | 全部 | — | 12 | 25 | 一般接手 |
| **详读** | 全部 | 最近40条 | 24 | 50 | 需要更多来龙去脉 |
| **超详读** | 全部 | 全部 | 50 | 全部 | 长会话、要彻底吃透 |

**你说**:「用**详读**接手第 2 段」

**手动命令**:
```bash
python3 ~/.claude/skills/recall/recall.py show 2 --depth 详读
# 还能手动微调:
python3 ~/.claude/skills/recall/recall.py show 2 --turns 40 --files 0   # 结尾40轮 + 全部改动文件
```

> 提示:只有长到触发过自动压缩的会话才有"全局记忆";短会话没有,靠"意图主线 + 尾轮"即全部,属正常。

---

## 3. 场景:跨对话合并(把好几段的上下文一起拉进来)

**你说**:「把第 2 段和第 5 段一起读进来,我要合着干」

**发生什么**:AI 一次 `show` 多个序号,合并两段材料。

**手动命令**:
```bash
python3 ~/.claude/skills/recall/recall.py show 2 5 --depth 详读
```

---

## 4. 场景:换目录 / 换电脑 / 给别人 —— 打包携带记忆

**痛点**:recall 按当前目录(cwd)过滤会话,**一换目录就扫不到旧对话**。用记忆包解决。

**你说**:
- 在旧对话里:「**打包这段记忆**」→ AI 跑 `pack`,生成一个自包含 md(存 `~/.recall-packs/`),把文件名给你。
- 到**新目录 / 新对话**:「**加载我打包的记忆**」或「`load <包名>`」→ AI 跑 `load`,读回全部上下文接着干。

**手动命令**:
```bash
# 打包(不给 id = 打包"当前对话";默认 full 深度)
python3 ~/.claude/skills/recall/recall.py pack
python3 ~/.claude/skills/recall/recall.py pack 4                    # 打包第4段
python3 ~/.claude/skills/recall/recall.py pack 4 --out ./记忆.md    # 导到指定路径(如直接丢进新项目)

python3 ~/.claude/skills/recall/recall.py packs                    # 看有哪些记忆包
python3 ~/.claude/skills/recall/recall.py load pucoding主对话-201a2641.md   # 任意目录读回
```

- 记忆包是**纯文本 md**,可以拷给别人、塞进项目仓库、跨机同步。
- 跨工具通用:Claude 打的包,Codex 里也能 `load`。

---

## 5. 场景:跨工具读取(Claude ↔ Codex)

同一个项目 Claude 和 Codex 都干过活时,**从任一工具读另一个工具在本项目的记忆**。

**你说**:「**跨工具看看这个项目**」/「读一下 Codex 在这项目干了啥」

**发生什么**:AI 跑 `list --provider both`,合并两边会话(🔵Claude / 🟠Codex 标记);选中后 `show ... --provider both` 自动用对应工具的后端解析。

**手动命令**:
```bash
python3 ~/.claude/skills/recall/recall.py list --provider both
python3 ~/.claude/skills/recall/recall.py show <id> --provider both --depth 标准
```

- `both` 下 `pack` / `prune` / `restore` 都会按每段所属工具自动处理,不会串。
- 只强制读某一边:`--provider codex`(或 `claude`)。

> 边界:这里跨读的是**会话历史**(两边都是 jsonl,已打通)。两个工具各自的"持久记忆库"是不同存储(Claude `memory/*.md` vs Codex sqlite),不互通;但"读到对方在这项目做了什么"已被会话跨读 + 记忆包完全覆盖。

---

## 6. 场景:给会话列表瘦身(归档 / 删除)

`claude -r` 越堆越多时清理。**默认软删(归档,可恢复),不硬删。**

**你说**:「**归档第 3 段**」/「把第 3、5、7 段归档」

**发生什么**:AI 先 `list` 把要处理的列给你确认,再 `prune`(默认归档)。

**手动命令**:
```bash
python3 ~/.claude/skills/recall/recall.py prune 3          # 软删=归档(移到 recall-archive,可恢复)
python3 ~/.claude/skills/recall/recall.py restore 3        # 从归档拉回,重新出现在 claude -r
python3 ~/.claude/skills/recall/recall.py list --archived  # 连归档区一起列

# 硬删(永久,受双重保护):单独 --delete 会被拒绝,必须再加 --force
python3 ~/.claude/skills/recall/recall.py prune 3 --delete --force
```

**护栏**:脚本**绝不动当前会话**;硬删前 AI 会说明"不可逆、无法 restore"并二次确认。

---

## 7. 场景:沉淀持久记忆

两层:

**A. 每段对话的 digest(接手简报持久化)**
接手后 AI 把简报写进 `~/.<tool>/recall-digests/<sid>.md`。下次 `show` 会在最前面直接秀出「💾 已有持久全局记忆」,秒读、不必重扫大文件。你说「**把这次接手沉淀下来**」即可。

**B. 项目级持久记忆库(仅 Claude)**
跨会话长期该记的事实(架构决定、运维铁律、踩坑),写进项目的 `memory/*.md`。
```bash
python3 ~/.claude/skills/recall/recall.py memory   # 定位记忆库目录 + 打印 MEMORY.md 索引
```
AI 据此在 `memory/` 下按规范新建/更新 `*.md` 并更新 `MEMORY.md`。

---

## 8. 场景:跨项目找某段对话

不确定在哪个项目,或想全局搜:

```bash
python3 ~/.claude/skills/recall/recall.py list --all              # 跨所有项目列出
python3 ~/.claude/skills/recall/recall.py show <短id> --all       # 按 id 跨项目取(不受当前目录限制)
```

---

## 9. 命令速查表

```
recall list    [--provider auto|claude|codex|both] [--all] [--archived] [--json]
recall show    <序号|短id|id ...> [--provider ...] [--depth 简读|标准|详读|超详读] [--turns N] [--files N] [--all]
recall pack    [序号|id] [--provider ...] [--out PATH] [--depth 超详读]     # 缺省=当前会话
recall packs
recall load    <包文件名|路径>
recall prune   <序号|id ...> [--provider ...] [--delete --force] [--all]
recall restore <序号|id ...> [--provider ...] [--all]
recall memory  [--project DIR]                                             # 仅 Claude
```

**通用参数**:`--project DIR`(默认当前目录)、`--provider`(默认 auto)。
**深度别名**:`简读=quick` `标准=normal` `详读=deep` `超详读=full`。

---

## 10. 文件都放哪

| 用途 | 位置 |
|---|---|
| Claude 会话原文 | `~/.claude/projects/<编码项目路径>/*.jsonl` |
| Codex 会话原文 | `~/.codex/sessions/年/月/日/rollout-*.jsonl` |
| 归档区 | `~/.claude/recall-archive/` · `~/.codex/recall-archive/` |
| 每段 digest | `~/.claude/recall-digests/` · `~/.codex/recall-digests/` |
| 记忆包(可移植) | `~/.recall-packs/` |
| 别名来源 | `~/.claude/history.jsonl` 里的 `/rename` 记录 |

---

## 11. FAQ / 边界

- **为什么它能绕开中转 resume 失效?** 因为它读的是**本地文件**,和账号/token 有没有过期无关。
- **`list` 没列出某个对话?** 默认按当前目录过滤——换目录了就 `--all`,或用记忆包(§4)。
- **Codex 的"改动文件"经常是 0?** Codex 改文件走 shell/`apply_patch`,抽取不如 Claude 的 Edit/Write 干净,可能为空,属正常;它靠"意图主线 + TODO(update_plan) + 尾轮"还原。
- **依赖?** 只需 `python3`(Mac/Linux 自带),纯标准库,只读不改会话文件(归档只是移动)。
- **自动识别当前工具靠什么?** 环境变量 `CLAUDECODE` / `CODEX_*`;识别不了就看哪个会话目录存在。

---

## 12. 一分钟上手

```bash
# 新开对话,找回上一段(标准深度)
/recall            # 然后报个序号 + 说"标准"

# 换目录带记忆走
recall pack        # 旧对话里打包当前会话 → 记下文件名
recall load <包>   # 新目录里读回

# 跨工具看这个项目
recall list --provider both
```
日常记住一句就够:**"帮我找回/打包/跨工具看"**,剩下的交给 AI。
```
