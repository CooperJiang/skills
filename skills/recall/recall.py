#!/usr/bin/env python3
"""
recall.py — 在对话里复刻 `claude -r`:列出本项目历史会话(带 /rename 别名),
并把选中会话的「改动文件 / 最新 TODO / 结尾若干轮」机械抽出来,供 AI 合成接手简报。

用法:
  recall.py list [--project DIR] [--all] [--archived]   列出会话(默认当前项目)
  recall.py show <序号|shortid|sessionId> [...] [--turns N]
                                                抽取一或多段会话的接手材料(可多 id 合并)
  recall.py prune <id> [<id>...] [--delete]     归档(默认)或删除(--delete)会话
  recall.py restore <id> [<id>...]              把归档的会话拉回,重新出现在 claude -r
  recall.py memory [--project DIR]              定位并打印本项目持久记忆库(memory/)

设计:脚本只做确定性的解析/抽取/搬移,不做“总结/判断”。总结、决定什么该沉淀进
持久记忆、写 memory 文件,都由调用它的 AI 完成。只用标准库。
"""
import sys, os, json, time, glob, argparse, shutil

CLAUDE_DIR = os.path.expanduser("~/.claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
HISTORY = os.path.join(CLAUDE_DIR, "history.jsonl")
ARCHIVE_DIR = os.path.join(CLAUDE_DIR, "recall-archive")

# 读取细致程度:不是“读几轮”,而是“读哪些结构化信号”。
#   turns   = 结尾对话轮数
#   files   = 最近改动文件数(0=全部)
#   summaries = 全局记忆(isCompactSummary 自动压缩摘要)取几段:0=最近1段(截断) / -1=全部
#   sumcap  = 每段全局记忆截断字数(0=不截断)
#   users   = 用户意图主线取几条:0=不取 / N=最近N条 / -1=全部
DEPTHS = {
    "quick":  {"turns": 6,  "files": 12, "summaries": 0,  "sumcap": 3000, "users": 0},
    "normal": {"turns": 12, "files": 25, "summaries": -1, "sumcap": 0,    "users": 0},
    "deep":   {"turns": 24, "files": 50, "summaries": -1, "sumcap": 0,    "users": 40},
    "full":   {"turns": 50, "files": 0,  "summaries": -1, "sumcap": 0,    "users": -1},
}
DEPTH_CN = {"简读": "quick", "标准": "normal", "详读": "deep", "超详读": "full",
            "简单": "quick", "详细": "deep", "全部": "full", "超详": "full"}

DIGEST_DIR = os.path.join(CLAUDE_DIR, "recall-digests")


def digest_path(sid):
    return os.path.join(DIGEST_DIR, sid + ".md")


def current_session_id():
    """尽量识别“当前正在运行”的会话,prune 时保护它不被误删。"""
    return os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_SESSION") or ""


def encode_project(path):
    """把项目绝对路径编码成 projects/ 下的目录名(/ 和 . 都换成 -)。"""
    p = os.path.abspath(path)
    return p.replace("/", "-").replace(".", "-")


def project_dir_for(path):
    return os.path.join(PROJECTS_DIR, encode_project(path))


def load_renames():
    """扫 history.jsonl,返回 {sessionId: 最新的 /rename 名}。"""
    names = {}
    if not os.path.exists(HISTORY):
        return names
    with open(HISTORY, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or '"/rename' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            disp = (o.get("display") or "").strip()
            sid = o.get("sessionId")
            if sid and disp.startswith("/rename "):
                nm = disp[len("/rename "):].strip()
                if nm:
                    names[sid] = nm  # 后出现的覆盖先前的 => 取最新
    return names


def iter_jsonl(path):
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def text_of(msg):
    """把一条 message 的 content 压成纯文本(工具调用用占位符标注)。"""
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if not isinstance(c, list):
        return ""
    parts = []
    for x in c:
        if not isinstance(x, dict):
            continue
        t = x.get("type")
        if t == "text":
            parts.append(x.get("text", ""))
        elif t == "tool_use":
            parts.append(f"[tool:{x.get('name')}]")
        elif t == "tool_result":
            r = x.get("content", "")
            if isinstance(r, list):
                r = " ".join(y.get("text", "") for y in r if isinstance(y, dict))
            parts.append("[result] " + str(r)[:160])
    return "\n".join(p for p in parts if p)


def real_text(msg):
    """只取自然语言 text 段(不含工具占位/结果),用于筛「有话说」的轮次。"""
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c.strip()
    if not isinstance(c, list):
        return ""
    parts = [x.get("text", "") for x in c
             if isinstance(x, dict) and x.get("type") == "text"]
    return "\n".join(p for p in parts if p.strip()).strip()


def scan_head(path, max_lines=60):
    """读文件前若干行,取首条真实用户消息 + git 分支。"""
    first_user = ""
    branch = ""
    n = 0
    with open(path, "r", errors="replace") as f:
        for line in f:
            n += 1
            if n > max_lines and first_user and branch:
                break
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not branch and o.get("gitBranch"):
                branch = o.get("gitBranch")
            if not first_user and o.get("type") == "user":
                txt = text_of(o.get("message", {}))
                # 跳过工具结果那种 user 行
                if txt and not txt.startswith("[result]") and "tool_result" not in txt:
                    first_user = txt.replace("\n", " ").strip()
    return first_user, branch


def human_ago(ts):
    d = time.time() - ts
    if d < 60:
        return f"{int(d)}秒前"
    if d < 3600:
        return f"{int(d/60)}分钟前"
    if d < 86400:
        return f"{int(d/3600)}小时前"
    return f"{int(d/86400)}天前"


def human_size(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f}{u}" if u == "B" else f"{b:.1f}{u}"
        b /= 1024
    return f"{b:.1f}TB"


def active_dirs(project, show_all):
    if show_all:
        return [d for d in glob.glob(os.path.join(PROJECTS_DIR, "*")) if os.path.isdir(d)]
    return [project_dir_for(project)]


def archive_dirs(project, show_all):
    if show_all:
        return [d for d in glob.glob(os.path.join(ARCHIVE_DIR, "*")) if os.path.isdir(d)]
    return [os.path.join(ARCHIVE_DIR, encode_project(project))]


def list_sessions(project, show_all, include_archived=False):
    renames = load_renames()
    rows = []
    scopes = [(d, False) for d in active_dirs(project, show_all)]
    if include_archived:
        scopes += [(d, True) for d in archive_dirs(project, show_all)]
    for d, arch in scopes:
        for path in glob.glob(os.path.join(d, "*.jsonl")):
            sid = os.path.basename(path)[:-6]
            st = os.stat(path)
            rows.append({"sid": sid, "path": path, "mtime": st.st_mtime, "size": st.st_size,
                         "projdir": os.path.basename(d), "archived": arch})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    out = []
    for i, r in enumerate(rows, 1):
        first_user, branch = scan_head(r["path"])
        name = renames.get(r["sid"]) or (first_user[:48] if first_user else "(无标题)")
        renamed = r["sid"] in renames
        out.append({
            "idx": i, "short": r["sid"][:8], "sid": r["sid"], "name": name,
            "renamed": renamed, "ago": human_ago(r["mtime"]), "branch": branch,
            "size": human_size(r["size"]), "first_user": first_user[:80],
            "projdir": r["projdir"], "archived": r["archived"], "path": r["path"],
        })
    return out


def resolve(project, key, show_all=False):
    """把 序号 / shortid / 完整 sessionId 解析成 jsonl 路径(含归档区)。"""
    dirs = active_dirs(project, show_all) + archive_dirs(project, show_all)
    if not key.isdigit() or len(key) >= 8:
        for d in dirs:
            for path in glob.glob(os.path.join(d, "*.jsonl")):
                sid = os.path.basename(path)[:-6]
                if sid == key or sid.startswith(key):
                    return path
    if key.isdigit():
        rows = list_sessions(project, show_all, include_archived=True)
        for r in rows:
            if r["idx"] == int(key):
                return r["path"]
    return None


def msg_text(msg):
    """把 message.content 抽成纯文本(含 str 或 list 两种形态)。"""
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c
                         if isinstance(x, dict) and x.get("type") == "text")
    return ""


def show_session(path, cfg, show_digest=True):
    """单遍流式扫描,按分层信号抽取:全局记忆(压缩摘要)/意图主线/改动文件/TODO/尾轮。"""
    turns = cfg["turns"]
    files_cap = cfg["files"]
    renames = load_renames()
    sid = os.path.basename(path)[:-6]
    edited, edited_seen = [], set()
    last_todos = None
    branch = cwd = first_user = ""
    ring = []            # 结尾文本轮
    compacts = []        # 全局记忆:isCompactSummary 正文
    aways = []           # 阶段小结:away_summary
    users_all = []       # 用户意图主线
    total = 0
    for o in iter_jsonl(path):
        total += 1
        if not branch and o.get("gitBranch"):
            branch = o.get("gitBranch")
        if not cwd and o.get("cwd"):
            cwd = o.get("cwd")
        # 全局记忆:Claude 上下文满时自动压缩出的摘要(整段对话的“数字记忆”)
        if o.get("isCompactSummary"):
            t = msg_text(o.get("message", {}))
            if t.strip():
                compacts.append(t.strip())
            continue
        if o.get("subtype") == "away_summary":
            c = o.get("content")
            if isinstance(c, str) and c.strip():
                aways.append(c.strip())
            continue
        typ = o.get("type")
        msg = o.get("message", {})
        if typ in ("user", "assistant") and isinstance(msg, dict):
            c = msg.get("content")
            if isinstance(c, list):
                for x in c:
                    if not isinstance(x, dict):
                        continue
                    if x.get("type") == "tool_use":
                        nm = x.get("name")
                        inp = x.get("input", {}) or {}
                        if nm in ("Edit", "Write", "NotebookEdit"):
                            fp = inp.get("file_path") or inp.get("notebook_path")
                            if fp and fp not in edited_seen:
                                edited_seen.add(fp)
                                edited.append(fp)
                        elif nm == "TodoWrite":
                            last_todos = inp.get("todos")
            rtext = real_text(msg)
            if rtext:
                if typ == "user":
                    if not first_user:
                        first_user = rtext.replace("\n", " ").strip()
                    users_all.append(rtext.strip())
                ring.append((typ, rtext))
                if len(ring) > turns:
                    ring.pop(0)

    name = renames.get(sid)
    print(f"# 会话接手材料")
    print(f"sessionId : {sid}")
    if name:
        print(f"别名(/rename): {name}")
    print(f"首条消息  : {first_user[:200]}")
    print(f"git 分支  : {branch or '未知'}")
    print(f"工作目录  : {cwd or '未知'}")
    print(f"总条目    : {total} · 全局记忆 {len(compacts)} 段 · 阶段小结 {len(aways)} 条 · 用户消息 {len(users_all)} 条")
    print()

    # 0) 上次沉淀的“持久全局记忆”(若有),秒读优先
    dp = digest_path(sid)
    if show_digest and os.path.exists(dp):
        print("## 💾 已有持久全局记忆(上次接手时沉淀,可直接用)")
        with open(dp, "r", errors="replace") as f:
            print(f.read().strip())
        print()

    # 1) 全局记忆:整段对话的骨架(比“尾巴 N 轮”重要得多)
    if compacts:
        sel = compacts if cfg["summaries"] == -1 else compacts[-1:]
        note = "全部" if cfg["summaries"] == -1 else f"最近 {len(sel)}/{len(compacts)} 段"
        print(f"## 🧠 全局记忆:Claude 自动压缩摘要({note})")
        for i, s in enumerate(sel, 1):
            body = s if not cfg["sumcap"] else s[:cfg["sumcap"]]
            print(f"\n--- 摘要段 {i} ---\n{body}")
            if cfg["sumcap"] and len(s) > cfg["sumcap"]:
                print(f"...(截断,完整 {len(s)} 字,用更高深度看全)")
        print()
    if aways and cfg["summaries"] == -1:
        print(f"## 阶段小结(最近 {min(8, len(aways))} 条)")
        for c in aways[-8:]:
            print(f"  · {c[:280]}")
        print()

    # 2) 改动文件
    if files_cap and len(edited) > files_cap:
        print(f"## 最近改动的文件(最后 {files_cap} 个,全程共 {len(edited)} 个)")
        show_files = edited[-files_cap:]
    else:
        print(f"## 本会话改动过的文件({len(edited)})")
        show_files = edited
    for fp in show_files:
        rel = fp[len(cwd) + 1:] if cwd and fp.startswith(cwd + "/") else fp
        print(f"  - {rel}")
    if not edited:
        print("  (无 Edit/Write 记录)")
    print()

    # 3) 最后一次 TODO
    if last_todos:
        print(f"## 最后一次 TODO 状态")
        for t in last_todos:
            if isinstance(t, dict):
                st = t.get("status", "?")
                mark = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}.get(st, "[?]")
                print(f"  {mark} {t.get('content', t.get('activeForm', ''))}")
        print()

    # 4) 用户意图主线(deep/full 才给;用户消息少而精,是任务弧线)
    if cfg["users"]:
        sel = users_all if cfg["users"] == -1 else users_all[-cfg["users"]:]
        print(f"## 用户意图主线({'全部' if cfg['users'] == -1 else '最近'} {len(sel)} 条用户消息)")
        for u in sel:
            print(f"  ▸ {u[:400].replace(chr(10), ' ')}")
        print()

    # 5) 结尾若干轮原文
    print(f"## 结尾 {len(ring)} 轮对话原文(去工具噪音)")
    for role, txt in ring:
        print(f"\n=== {role} ===")
        print(txt[:1500])
    print()
    print(f"---\n💾 接手后可把简报沉淀为该会话的持久全局记忆:写入 {dp}")


def prune_sessions(project, keys, do_delete, show_all, force=False):
    """归档(默认)或删除(--delete)指定会话。绝不动当前会话。"""
    if do_delete and not force:
        print("⚠️ 硬删除不可逆。默认策略=软删除(归档,可恢复)。")
        print("   如确实要永久删除,请二次确认后加 --force;否则去掉 --delete 走归档。")
        return
    cur = current_session_id()
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    done = []
    for key in keys:
        path = resolve(project, key, show_all)
        if not path:
            print(f"  跳过 {key}:没找到")
            continue
        sid = os.path.basename(path)[:-6]
        if cur and (sid == cur or sid.startswith(cur) or cur.startswith(sid)):
            print(f"  跳过 {sid[:8]}:这是当前会话,保护不动")
            continue
        if os.path.dirname(path).startswith(ARCHIVE_DIR):
            print(f"  跳过 {sid[:8]}:已在归档区")
            continue
        if do_delete:
            os.remove(path)
            print(f"  已删除 {sid[:8]}  ({path})")
            done.append(sid)
        else:
            projdir = os.path.basename(os.path.dirname(path))
            dest_dir = os.path.join(ARCHIVE_DIR, projdir)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, sid + ".jsonl")
            shutil.move(path, dest)
            print(f"  已归档 {sid[:8]}  → {dest}")
            done.append(sid)
    verb = "删除" if do_delete else "归档"
    print(f"\n共{verb} {len(done)} 段。" + ("" if do_delete else " 用 `restore <id>` 可拉回。"))


def restore_sessions(project, keys, show_all):
    restored = 0
    for key in keys:
        path = resolve(project, key, show_all)
        if not path or not os.path.dirname(path).startswith(ARCHIVE_DIR):
            print(f"  跳过 {key}:不在归档区(或没找到)")
            continue
        sid = os.path.basename(path)[:-6]
        projdir = os.path.basename(os.path.dirname(path))
        dest_dir = os.path.join(PROJECTS_DIR, projdir)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, sid + ".jsonl")
        shutil.move(path, dest)
        print(f"  已恢复 {sid[:8]}  → 重新出现在 claude -r")
        restored += 1
    print(f"\n共恢复 {restored} 段。")


def show_memory(project):
    """定位并打印本项目的持久记忆库(memory/),给 AI 沉淀记忆时锚定位置。"""
    mem_dir = os.path.join(project_dir_for(project), "memory")
    index = os.path.join(mem_dir, "MEMORY.md")
    print(f"记忆库目录: {mem_dir}")
    print(f"索引文件  : {index}")
    if not os.path.isdir(mem_dir):
        print("(该项目还没有记忆库;要沉淀记忆就在上面这个目录新建 *.md + 更新 MEMORY.md)")
        return
    files = sorted(glob.glob(os.path.join(mem_dir, "*.md")))
    print(f"现有记忆文件({len(files)}):")
    for fp in files:
        print(f"  - {os.path.basename(fp)}")
    if os.path.exists(index):
        print("\n---- MEMORY.md 索引 ----")
        with open(index, "r", errors="replace") as f:
            print(f.read())


def print_list(rows):
    if not rows:
        print("(没找到会话记录)")
        return
    print(f"历史会话(共 {len(rows)} 段,按最近活跃排序):\n")
    for r in rows:
        tag = "✎" if r["renamed"] else " "
        arch = " 📦归档" if r.get("archived") else ""
        print(f"[{r['idx']:>2}] {tag} {r['name']}{arch}")
        print(f"      {r['ago']} · {r['branch'] or '?'} · {r['size']} · {r['short']}")
        if r["renamed"] and r["first_user"]:
            print(f"      ↳ 首句: {r['first_user']}")
        print()
    print("接手:报序号/别名(可多个),并说读取深度(简读/标准/详读/超详读)。")
    print("清理:说『归档 N』给 claude -r 瘦身(软删,可 restore 恢复);默认不硬删除。")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    lp = sub.add_parser("list")
    lp.add_argument("--project", default=os.getcwd())
    lp.add_argument("--all", action="store_true")
    lp.add_argument("--archived", action="store_true", help="连同归档区一起列出")
    lp.add_argument("--json", action="store_true")
    sp = sub.add_parser("show")
    sp.add_argument("key", nargs="+", help="一或多个 序号/shortid/sessionId(多个=合并多段)")
    sp.add_argument("--project", default=os.getcwd())
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--depth", default="normal",
                    help="读取细致程度: quick/normal/deep/full 或 简读/标准/详读/超详读")
    sp.add_argument("--turns", type=int, default=None, help="手动覆盖结尾轮数")
    sp.add_argument("--files", type=int, default=None, help="手动覆盖改动文件数(0=全部)")
    pp = sub.add_parser("prune")
    pp.add_argument("key", nargs="+")
    pp.add_argument("--project", default=os.getcwd())
    pp.add_argument("--all", action="store_true")
    pp.add_argument("--delete", action="store_true", help="永久删除(默认只归档)")
    pp.add_argument("--force", action="store_true", help="配合 --delete,二次确认后才真删")
    rp = sub.add_parser("restore")
    rp.add_argument("key", nargs="+")
    rp.add_argument("--project", default=os.getcwd())
    rp.add_argument("--all", action="store_true")
    mp = sub.add_parser("memory")
    mp.add_argument("--project", default=os.getcwd())
    args = ap.parse_args()

    if args.cmd == "list":
        rows = list_sessions(args.project, args.all, include_archived=args.archived)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return
        print_list(rows)
    elif args.cmd == "show":
        depth = DEPTH_CN.get(args.depth, args.depth)
        if depth not in DEPTHS:
            depth = "normal"
        cfg = dict(DEPTHS[depth])   # 拷贝一份,允许手动覆盖
        if args.turns is not None:
            cfg["turns"] = args.turns
        if args.files is not None:
            cfg["files"] = args.files
        keys = args.key
        sumnote = "全部" if cfg["summaries"] == -1 else "最近1段"
        print(f"(读取深度: {depth} · 全局记忆 {sumnote} · 意图主线 "
              f"{'全部' if cfg['users']==-1 else ('无' if cfg['users']==0 else cfg['users'])} · "
              f"结尾 {cfg['turns']} 轮 · 文件 {'全部' if cfg['files']==0 else cfg['files']})\n")
        for i, key in enumerate(keys):
            path = resolve(args.project, key, args.all)
            if not path:
                print(f"没找到会话: {key}(试试先 list)")
                continue
            if len(keys) > 1:
                print("\n" + "=" * 70)
                print(f"# 第 {i+1}/{len(keys)} 段")
                print("=" * 70)
            show_session(path, cfg)
    elif args.cmd == "prune":
        prune_sessions(args.project, args.key, args.delete, args.all, args.force)
    elif args.cmd == "restore":
        restore_sessions(args.project, args.key, args.all)
    elif args.cmd == "memory":
        show_memory(args.project)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
