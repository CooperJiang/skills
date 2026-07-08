#!/usr/bin/env python3
"""
recall.py —— 在对话里复刻 `claude -r` / `codex resume`:列出历史会话、按分层深度找回上下文、
跨对话合并、归档/删除老会话、沉淀持久 digest。**单引擎双后端**:自动识别自己是被
Claude Code 还是 Codex 调用,读对应工具的会话历史。

  recall.py list  [--provider auto|claude|codex] [--all] [--archived] [--json]
  recall.py show  <序号|shortid|id ...> [--provider ...] [--depth 简读|标准|详读|超详读]
  recall.py prune <id ...> [--provider ...] [--delete --force]
  recall.py restore <id ...> [--provider ...]
  recall.py memory [--provider ...]           (仅 claude:定位持久记忆库 memory/)

设计:脚本只做确定性解析/抽取/搬移;总结与写记忆由调用它的 AI 完成。只用标准库。
"""
import sys, os, json, time, glob, argparse, shutil, re

HOME = os.path.expanduser("~")
CLAUDE_DIR = os.path.join(HOME, ".claude")
CLAUDE_PROJECTS = os.path.join(CLAUDE_DIR, "projects")
CLAUDE_HISTORY = os.path.join(CLAUDE_DIR, "history.jsonl")
CODEX_DIR = os.path.join(HOME, ".codex")
CODEX_SESSIONS = os.path.join(CODEX_DIR, "sessions")

# 读取细致程度:不是“读几轮”,而是“读哪些结构化信号”。
DEPTHS = {
    "quick":  {"turns": 6,  "files": 12, "summaries": 0,  "sumcap": 3000, "users": 0},
    "normal": {"turns": 12, "files": 25, "summaries": -1, "sumcap": 0,    "users": 0},
    "deep":   {"turns": 24, "files": 50, "summaries": -1, "sumcap": 0,    "users": 40},
    "full":   {"turns": 50, "files": 0,  "summaries": -1, "sumcap": 0,    "users": -1},
}
DEPTH_CN = {"简读": "quick", "标准": "normal", "详读": "deep", "超详读": "full",
            "简单": "quick", "详细": "deep", "全部": "full", "超详": "full"}


# ---------------------------------------------------------------- provider 识别
def detect_provider(explicit=None):
    if explicit and explicit != "auto":
        return explicit
    e = os.environ
    if e.get("CLAUDECODE") or any(k.startswith("CLAUDE_CODE") for k in e):
        return "claude"
    if any(k.startswith("CODEX") for k in e):
        return "codex"
    if os.path.isdir(CLAUDE_PROJECTS):
        return "claude"
    if os.path.isdir(CODEX_SESSIONS):
        return "codex"
    return "claude"


def current_session_id():
    return (os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CODEX_SESSION_ID")
            or os.environ.get("CLAUDE_SESSION_ID") or "")


def archive_root(provider):
    return os.path.join(CLAUDE_DIR if provider == "claude" else CODEX_DIR, "recall-archive")


def digest_dir(provider):
    return os.path.join(CLAUDE_DIR if provider == "claude" else CODEX_DIR, "recall-digests")


def digest_path(provider, sid):
    return os.path.join(digest_dir(provider), sid + ".md")


# ---------------------------------------------------------------- 通用小工具
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


def human_ago(ts):
    d = time.time() - ts
    if d < 60:   return f"{int(d)}秒前"
    if d < 3600: return f"{int(d/60)}分钟前"
    if d < 86400: return f"{int(d/3600)}小时前"
    return f"{int(d/86400)}天前"


def human_size(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f}{u}" if u == "B" else f"{b:.1f}{u}"
        b /= 1024
    return f"{b:.1f}TB"


def print_meta_head(sid, name, first_user, branch, cwd, extra=""):
    print(f"# 会话接手材料")
    print(f"sessionId : {sid}")
    if name:
        print(f"别名/标题 : {name}")
    print(f"首条消息  : {first_user[:200]}")
    print(f"git 分支  : {branch or '未知'}")
    print(f"工作目录  : {cwd or '未知'}")
    if extra:
        print(extra)
    print()


def print_files(edited, cwd, files_cap):
    if files_cap and len(edited) > files_cap:
        print(f"## 最近改动的文件(最后 {files_cap} 个,全程共 {len(edited)} 个)")
        show = edited[-files_cap:]
    else:
        print(f"## 本会话改动过的文件({len(edited)})")
        show = edited
    for fp in show:
        rel = fp[len(cwd) + 1:] if cwd and fp.startswith(cwd + "/") else fp
        print(f"  - {rel}")
    if not edited:
        print("  (未能抽出改动文件)")
    print()


def print_todos(todos, title="最后一次 TODO 状态"):
    if not todos:
        return
    print(f"## {title}")
    for t in todos:
        if isinstance(t, dict):
            st = t.get("status", "?")
            mark = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}.get(st, "[?]")
            print(f"  {mark} {t.get('content', t.get('step', t.get('activeForm', '')))}")
    print()


def print_users(users_all, users_cfg):
    if not users_cfg:
        return
    sel = users_all if users_cfg == -1 else users_all[-users_cfg:]
    print(f"## 用户意图主线({'全部' if users_cfg == -1 else '最近'} {len(sel)} 条用户消息)")
    for u in sel:
        print(f"  ▸ {u[:400].replace(chr(10), ' ')}")
    print()


def print_tail(ring):
    print(f"## 结尾 {len(ring)} 轮对话原文(去工具噪音)")
    for role, txt in ring:
        print(f"\n=== {role} ===")
        print(txt[:1500])
    print()


def maybe_print_digest(provider, sid, show_digest):
    dp = digest_path(provider, sid)
    if show_digest and os.path.exists(dp):
        print("## 💾 已有持久全局记忆(上次接手时沉淀,可直接用)")
        with open(dp, "r", errors="replace") as f:
            print(f.read().strip())
        print()
    return dp


# ================================================================ Claude 后端
def claude_load_renames():
    names = {}
    if not os.path.exists(CLAUDE_HISTORY):
        return names
    for o in iter_jsonl(CLAUDE_HISTORY):
        disp = (o.get("display") or "").strip()
        sid = o.get("sessionId")
        if sid and disp.startswith("/rename "):
            nm = disp[len("/rename "):].strip()
            if nm:
                names[sid] = nm
    return names


def _cl_text(msg):
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
        return "\n".join(p for p in out if p)
    return ""


def _cl_real(msg):
    return _cl_text(msg).strip()


def claude_encode(path):
    return os.path.abspath(path).replace("/", "-").replace(".", "-")


def claude_active_dirs(project, show_all):
    if show_all:
        return [d for d in glob.glob(os.path.join(CLAUDE_PROJECTS, "*")) if os.path.isdir(d)]
    return [os.path.join(CLAUDE_PROJECTS, claude_encode(project))]


def claude_scan_head(path, max_lines=60):
    first_user = branch = ""
    n = 0
    for o in iter_jsonl(path):
        n += 1
        if n > max_lines and first_user and branch:
            break
        if not branch and o.get("gitBranch"):
            branch = o.get("gitBranch")
        if not first_user and o.get("type") == "user" and not o.get("isCompactSummary"):
            txt = _cl_real(o.get("message", {}))
            if txt:
                first_user = txt.replace("\n", " ").strip()
    return first_user, branch


def claude_list_rows(project, show_all, include_archived):
    renames = claude_load_renames()
    scopes = [(d, False) for d in claude_active_dirs(project, show_all)]
    if include_archived:
        ar = archive_root("claude")
        cand = glob.glob(os.path.join(ar, "*")) if show_all else [os.path.join(ar, claude_encode(project))]
        scopes += [(d, True) for d in cand if os.path.isdir(d)]
    rows = []
    for d, arch in scopes:
        for path in glob.glob(os.path.join(d, "*.jsonl")):
            sid = os.path.basename(path)[:-6]
            st = os.stat(path)
            fu, br = claude_scan_head(path)
            name = renames.get(sid) or (fu[:48] if fu else "(无标题)")
            rows.append({"sid": sid, "path": path, "mtime": st.st_mtime, "size": st.st_size,
                         "name": name, "first_user": fu[:80], "branch": br,
                         "renamed": sid in renames, "archived": arch})
    return rows


def claude_extract(path, cfg, provider, show_digest):
    turns, files_cap = cfg["turns"], cfg["files"]
    renames = claude_load_renames()
    sid = os.path.basename(path)[:-6]
    edited, seen = [], set()
    last_todos = None
    branch = cwd = first_user = ""
    ring, compacts, aways, users_all = [], [], [], []
    total = 0
    for o in iter_jsonl(path):
        total += 1
        if not branch and o.get("gitBranch"):
            branch = o.get("gitBranch")
        if not cwd and o.get("cwd"):
            cwd = o.get("cwd")
        if o.get("isCompactSummary"):
            t = _cl_text(o.get("message", {}))
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
                            if fp and fp not in seen:
                                seen.add(fp)
                                edited.append(fp)
                        elif nm == "TodoWrite":
                            last_todos = inp.get("todos")
            rtext = _cl_real(msg)
            if rtext:
                if typ == "user":
                    if not first_user:
                        first_user = rtext.replace("\n", " ").strip()
                    users_all.append(rtext.strip())
                ring.append((typ, rtext))
                if len(ring) > turns:
                    ring.pop(0)

    name = renames.get(sid)
    extra = (f"总条目    : {total} · 全局记忆 {len(compacts)} 段 · 阶段小结 {len(aways)} 条 · "
             f"用户消息 {len(users_all)} 条")
    print_meta_head(sid, name, first_user, branch, cwd, extra)
    dp = maybe_print_digest(provider, sid, show_digest)

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

    print_files(edited, cwd, files_cap)
    print_todos(last_todos)
    print_users(users_all, cfg["users"])
    print_tail(ring)
    print(f"---\n💾 接手后可把简报沉淀为该会话的持久全局记忆:写入 {dp}")


# ================================================================ Codex 后端
CODEX_FILE_RE = re.compile(r"\*\*\*\s+(?:Add|Update|Delete) File:\s+(.+)")


def codex_sid(path):
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path).replace(".jsonl", "")


def codex_active_files():
    return glob.glob(os.path.join(CODEX_SESSIONS, "**", "rollout-*.jsonl"), recursive=True)


def codex_head(path, max_lines=400):
    cwd = sid = first_user = ""
    n = 0
    for o in iter_jsonl(path):
        n += 1
        if n > max_lines:
            break
        p = o.get("payload", {})
        if o.get("type") == "session_meta":
            cwd = p.get("cwd", "")
            sid = p.get("id", "") or codex_sid(path)
        elif not first_user and o.get("type") == "event_msg" and p.get("type") == "user_message":
            msg = p.get("message", "")
            if isinstance(msg, str) and msg.strip():
                first_user = msg.replace("\n", " ").strip()
    if not sid:
        sid = codex_sid(path)
    return cwd, sid, first_user


def codex_list_rows(project, show_all, include_archived):
    proj = os.path.abspath(project)
    files = codex_active_files()
    arch = []
    if include_archived:
        arch = glob.glob(os.path.join(archive_root("codex"), "**", "rollout-*.jsonl"), recursive=True)
    rows = []
    for path in files + arch:
        cwd, sid, fu = codex_head(path)
        if not show_all and (not cwd or os.path.abspath(cwd) != proj):
            continue
        st = os.stat(path)
        rows.append({"sid": sid, "path": path, "mtime": st.st_mtime, "size": st.st_size,
                     "name": fu[:48] if fu else "(无标题)", "first_user": fu[:80], "branch": "",
                     "renamed": False, "archived": path in arch})
    return rows


def codex_extract(path, cfg, provider, show_digest):
    turns, files_cap = cfg["turns"], cfg["files"]
    sid = cwd = first_user = cli = ""
    edited, seen = [], set()
    last_plan = None
    ring, users_all = [], []
    total = 0
    for o in iter_jsonl(path):
        total += 1
        p = o.get("payload", {})
        t = o.get("type")
        if t == "session_meta":
            cwd = p.get("cwd", cwd)
            sid = p.get("id", sid) or sid
            cli = p.get("cli_version", "")
            continue
        if t == "event_msg":
            pt = p.get("type")
            if pt == "user_message":
                msg = p.get("message", "")
                if isinstance(msg, str) and msg.strip():
                    if not first_user:
                        first_user = msg.replace("\n", " ").strip()
                    users_all.append(msg.strip())
                    ring.append(("user", msg.strip()))
                    if len(ring) > turns:
                        ring.pop(0)
            elif pt == "agent_message":
                msg = p.get("message", "")
                if isinstance(msg, str) and msg.strip():
                    ring.append(("assistant", msg.strip()))
                    if len(ring) > turns:
                        ring.pop(0)
        elif t == "response_item" and p.get("type") == "function_call":
            nm = p.get("name")
            args = p.get("arguments", "")
            if nm == "update_plan":
                try:
                    parsed = json.loads(args) if isinstance(args, str) else args
                    last_plan = parsed.get("plan")
                except Exception:
                    pass
            elif isinstance(args, str) and "*** " in args:
                for fp in CODEX_FILE_RE.findall(args):
                    fp = fp.strip()
                    if fp and fp not in seen:
                        seen.add(fp)
                        edited.append(fp)
    if not sid:
        sid = codex_sid(path)

    extra = f"总条目    : {total} · 用户消息 {len(users_all)} 条 · CLI {cli or '?'}"
    print_meta_head(sid, None, first_user, "", cwd, extra)
    dp = maybe_print_digest(provider, sid, show_digest)
    print("## 🧠 全局记忆:Codex 无自动压缩摘要,靠「用户意图主线 + 结尾轮」还原\n")
    print_files(edited, cwd, files_cap)
    print_todos(last_plan, title="最后一次 update_plan(Codex 的 TODO)")
    print_users(users_all, cfg["users"])
    print_tail(ring)
    print(f"---\n💾 接手后可把简报沉淀为该会话的持久全局记忆:写入 {dp}")


# ================================================================ backend 分发
def get_backend(provider):
    if provider == "codex":
        return {"list": codex_list_rows, "extract": codex_extract,
                "active_root": CODEX_SESSIONS, "glob": "**/rollout-*.jsonl",
                "sid_of": codex_sid}
    return {"list": claude_list_rows, "extract": claude_extract,
            "active_root": CLAUDE_PROJECTS, "glob": "**/*.jsonl",
            "sid_of": lambda p: os.path.basename(p)[:-6]}


def list_sessions(provider, project, show_all, include_archived=False):
    rows = get_backend(provider)["list"](project, show_all, include_archived)
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["idx"] = i
        r["short"] = r["sid"][:8]
        r["ago"] = human_ago(r["mtime"])
        r["size_h"] = human_size(r["size"])
    return rows


def resolve(provider, project, key, show_all=False):
    be = get_backend(provider)
    if key.isdigit() and len(key) < 8:
        for r in list_sessions(provider, project, show_all, include_archived=True):
            if r["idx"] == int(key):
                return r["path"]
        return None
    for root in [be["active_root"], archive_root(provider)]:
        for path in glob.glob(os.path.join(root, be["glob"]), recursive=True):
            if be["sid_of"](path).startswith(key) or key in os.path.basename(path):
                return path
    return None


def prune_sessions(provider, project, keys, do_delete, show_all, force=False):
    if do_delete and not force:
        print("⚠️ 硬删除不可逆。默认策略=软删除(归档,可恢复)。")
        print("   如确实要永久删除,请二次确认后加 --force;否则去掉 --delete 走归档。")
        return
    be = get_backend(provider)
    active_root, ar = be["active_root"], archive_root(provider)
    cur = current_session_id()
    done = 0
    for key in keys:
        path = resolve(provider, project, key, show_all)
        if not path:
            print(f"  跳过 {key}:没找到")
            continue
        sid = be["sid_of"](path)
        if cur and (sid == cur or sid.startswith(cur) or cur.startswith(sid)):
            print(f"  跳过 {sid[:8]}:这是当前会话,保护不动")
            continue
        if os.path.abspath(path).startswith(os.path.abspath(ar)):
            print(f"  跳过 {sid[:8]}:已在归档区")
            continue
        if do_delete:
            os.remove(path)
            print(f"  已删除 {sid[:8]}")
            done += 1
        else:
            rel = os.path.relpath(path, active_root)
            dest = os.path.join(ar, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(path, dest)
            print(f"  已归档 {sid[:8]}  → {dest}")
            done += 1
    verb = "删除" if do_delete else "归档"
    print(f"\n共{verb} {done} 段。" + ("" if do_delete else " 用 `restore <id>` 可拉回。"))


def restore_sessions(provider, project, keys, show_all):
    be = get_backend(provider)
    active_root, ar = be["active_root"], archive_root(provider)
    n = 0
    for key in keys:
        path = resolve(provider, project, key, show_all)
        if not path or not os.path.abspath(path).startswith(os.path.abspath(ar)):
            print(f"  跳过 {key}:不在归档区(或没找到)")
            continue
        rel = os.path.relpath(path, ar)
        dest = os.path.join(active_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(path, dest)
        print(f"  已恢复 {be['sid_of'](path)[:8]}")
        n += 1
    print(f"\n共恢复 {n} 段。")


def show_memory(project):
    mem_dir = os.path.join(CLAUDE_PROJECTS, claude_encode(project), "memory")
    index = os.path.join(mem_dir, "MEMORY.md")
    print(f"记忆库目录: {mem_dir}")
    print(f"索引文件  : {index}")
    if not os.path.isdir(mem_dir):
        print("(该项目还没有记忆库;要沉淀就在上面这个目录新建 *.md + 更新 MEMORY.md)")
        return
    files = sorted(glob.glob(os.path.join(mem_dir, "*.md")))
    print(f"现有记忆文件({len(files)}):")
    for fp in files:
        print(f"  - {os.path.basename(fp)}")
    if os.path.exists(index):
        print("\n---- MEMORY.md 索引 ----")
        with open(index, "r", errors="replace") as f:
            print(f.read())


def print_list(rows, provider):
    if not rows:
        print("(没找到会话记录)")
        return
    tool = "Claude" if provider == "claude" else "Codex"
    print(f"[{tool}] 历史会话(共 {len(rows)} 段,按最近活跃排序):\n")
    for r in rows:
        tag = "✎" if r["renamed"] else " "
        arch = " 📦归档" if r.get("archived") else ""
        print(f"[{r['idx']:>2}] {tag} {r['name']}{arch}")
        print(f"      {r['ago']} · {r['branch'] or '?'} · {r['size_h']} · {r['short']}")
        if r["renamed"] and r["first_user"]:
            print(f"      ↳ 首句: {r['first_user']}")
        print()
    print("接手:报序号/别名(可多个),并说读取深度(简读/标准/详读/超详读)。")
    print("清理:说『归档 N』给列表瘦身(软删,可 restore 恢复);默认不硬删除。")


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    for name in ("list", "show", "prune", "restore", "memory"):
        sp = sub.add_parser(name)
        sp.add_argument("--provider", default="auto", choices=["auto", "claude", "codex"])
        sp.add_argument("--project", default=os.getcwd())
        if name == "list":
            sp.add_argument("--all", action="store_true")
            sp.add_argument("--archived", action="store_true")
            sp.add_argument("--json", action="store_true")
        if name == "show":
            sp.add_argument("key", nargs="+")
            sp.add_argument("--all", action="store_true")
            sp.add_argument("--depth", default="normal")
            sp.add_argument("--turns", type=int, default=None)
            sp.add_argument("--files", type=int, default=None)
        if name in ("prune", "restore"):
            sp.add_argument("key", nargs="+")
            sp.add_argument("--all", action="store_true")
        if name == "prune":
            sp.add_argument("--delete", action="store_true")
            sp.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return
    provider = detect_provider(getattr(args, "provider", "auto"))

    if args.cmd == "list":
        rows = list_sessions(provider, args.project, args.all, include_archived=args.archived)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
            return
        print_list(rows, provider)
    elif args.cmd == "show":
        depth = DEPTH_CN.get(args.depth, args.depth)
        if depth not in DEPTHS:
            depth = "normal"
        cfg = dict(DEPTHS[depth])
        if args.turns is not None:
            cfg["turns"] = args.turns
        if args.files is not None:
            cfg["files"] = args.files
        be = get_backend(provider)
        sumnote = "全部" if cfg["summaries"] == -1 else "最近1段"
        print(f"[{provider}] 读取深度: {depth} · 全局记忆 {sumnote} · 意图主线 "
              f"{'全部' if cfg['users']==-1 else ('无' if cfg['users']==0 else cfg['users'])} · "
              f"结尾 {cfg['turns']} 轮 · 文件 {'全部' if cfg['files']==0 else cfg['files']}\n")
        for i, key in enumerate(args.key):
            path = resolve(provider, args.project, key, args.all)
            if not path:
                print(f"没找到会话: {key}(试试先 list)")
                continue
            if len(args.key) > 1:
                print("\n" + "=" * 70 + f"\n# 第 {i+1}/{len(args.key)} 段\n" + "=" * 70)
            be["extract"](path, cfg, provider, True)
    elif args.cmd == "prune":
        prune_sessions(provider, args.project, args.key, args.delete, args.all, args.force)
    elif args.cmd == "restore":
        restore_sessions(provider, args.project, args.key, args.all)
    elif args.cmd == "memory":
        if provider != "claude":
            print("memory 子命令目前仅 Claude(Codex 记忆在 ~/.codex/memories,机制不同)。")
            return
        show_memory(args.project)


if __name__ == "__main__":
    main()
