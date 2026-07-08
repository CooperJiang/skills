#!/usr/bin/env node
'use strict';
/*
 * claude-skills —— 把本仓库里的 skill 装进 Claude Code(~/.claude/skills)与 Codex(~/.codex/skills)。
 * 二者用同一套 SKILL.md 格式,所以一个 skill 文件夹可同时喂两个工具。零依赖(只用 Node 内置)。
 * 默认软链接(便于多机 git pull 即时同步);--copy 复制安装。
 *
 *   claude-skills list                              列出仓库 skill 及在各工具的安装状态
 *   claude-skills install <name|--all> [选项]        安装
 *   claude-skills uninstall <name|--all> [--target]  卸载
 *   claude-skills doctor                            环境自检
 *
 * 选项:--target claude|codex|both(默认 both)  --copy 复制  --force 覆盖已存在
 * 某个 skill 若只适用单平台,可在 SKILL.md frontmatter 写 `targets: claude`(或 codex)来限制。
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const REPO_SKILLS = path.join(__dirname, '..', 'skills');
const ROOTS = {
  claude: { toolDir: path.join(os.homedir(), '.claude'), skillsDir: path.join(os.homedir(), '.claude', 'skills') },
  codex:  { toolDir: path.join(os.homedir(), '.codex'),  skillsDir: path.join(os.homedir(), '.codex', 'skills') },
};
const C = { dim: s => `\x1b[2m${s}\x1b[0m`, g: s => `\x1b[32m${s}\x1b[0m`,
            y: s => `\x1b[33m${s}\x1b[0m`, r: s => `\x1b[31m${s}\x1b[0m`, b: s => `\x1b[1m${s}\x1b[0m` };

function discover() {
  if (!fs.existsSync(REPO_SKILLS)) return [];
  return fs.readdirSync(REPO_SKILLS)
    .filter(n => fs.existsSync(path.join(REPO_SKILLS, n, 'SKILL.md')))
    .map(n => ({ name: n, src: path.join(REPO_SKILLS, n), meta: readMeta(path.join(REPO_SKILLS, n, 'SKILL.md')) }));
}

function readMeta(skillMd) {
  const txt = fs.readFileSync(skillMd, 'utf8');
  const m = txt.match(/^---\s*([\s\S]*?)\s*---/);
  const out = {};
  if (m) for (const line of m[1].split('\n')) {
    const kv = line.match(/^(\w[\w-]*):\s*(.*)$/);
    if (kv) out[kv[1]] = kv[2].replace(/^["']|["']$/g, '');
  }
  return out;
}

// skill 声明适用哪些工具:frontmatter `targets: claude, codex`;缺省=全部
function skillTargets(sk) {
  const raw = sk.meta.targets;
  if (!raw) return Object.keys(ROOTS);
  return raw.split(/[,\s]+/).map(s => s.trim().toLowerCase()).filter(t => ROOTS[t]);
}
function toolAvailable(t) { return fs.existsSync(ROOTS[t].toolDir); }

function isSymlink(p) { try { return fs.lstatSync(p).isSymbolicLink(); } catch { return false; } }
function rmrf(p) { fs.rmSync(p, { recursive: true, force: true }); }

function stateAt(root, name) {
  const dest = path.join(root, name);
  if (!fs.existsSync(dest) && !isSymlink(dest)) return 'none';
  if (isSymlink(dest)) {
    const resolved = path.resolve(path.dirname(dest), fs.readlinkSync(dest));
    return resolved === path.join(REPO_SKILLS, name) ? 'linked' : 'linked-other';
  }
  return 'copied';
}

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (e.name === '__pycache__' || e.name.startsWith('._')) continue;
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) copyDir(s, d); else fs.copyFileSync(s, d);
  }
}

function installInto(target, sk, { copy, force }) {
  const root = ROOTS[target].skillsDir;
  const dest = path.join(root, sk.name);
  fs.mkdirSync(root, { recursive: true });
  if (fs.existsSync(dest) || isSymlink(dest)) {
    const st = stateAt(root, sk.name);
    if (st === 'linked' && !copy) { console.log(C.dim(`  [${target}] 已链接,跳过`)); return; }
    if (!force) { console.log(C.y(`  [${target}] 目标已存在(${st}),加 --force 覆盖`)); return; }
    if (!isSymlink(dest) && fs.statSync(dest).isDirectory()) {
      const bak = `${dest}.bak-${process.pid}`; fs.renameSync(dest, bak);
      console.log(C.dim(`  [${target}] 备份原目录 → ${bak}`));
    } else rmrf(dest);
  }
  if (copy) { copyDir(sk.src, dest); console.log(C.g(`  [${target}] ✓ 复制 ${sk.name}`)); }
  else { fs.symlinkSync(sk.src, dest, 'dir'); console.log(C.g(`  [${target}] ✓ 链接 ${sk.name}`)); }
}

function install(name, opts, targetFilter) {
  const sk = discover().find(s => s.name === name);
  if (!sk) { console.log(C.r(`✗ 仓库里没有 skill: ${name}`)); return; }
  const want = targetFilter === 'both' ? Object.keys(ROOTS) : [targetFilter];
  const targets = skillTargets(sk).filter(t => want.includes(t));
  console.log(C.b(name) + C.dim(`  (适用: ${skillTargets(sk).join('/')})`));
  let any = false;
  for (const t of targets) {
    if (!toolAvailable(t)) { console.log(C.dim(`  [${t}] 未安装该工具,跳过`)); continue; }
    installInto(t, sk, opts); any = true;
  }
  if (!any) console.log(C.y('  无可安装目标'));
}

function uninstall(name, targetFilter) {
  const targets = targetFilter === 'both' ? Object.keys(ROOTS) : [targetFilter];
  for (const t of targets) {
    const dest = path.join(ROOTS[t].skillsDir, name);
    const st = stateAt(ROOTS[t].skillsDir, name);
    if (st === 'none') { console.log(C.dim(`  [${t}] 未安装`)); continue; }
    if (isSymlink(dest)) { fs.unlinkSync(dest); console.log(C.g(`  [${t}] ✓ 移除链接 ${name}`)); }
    else console.log(C.y(`  [${t}] 是复制目录,未自动删。如确认: rm -rf ${dest}`));
  }
}

function cmdList() {
  const skills = discover();
  if (!skills.length) { console.log('(仓库里还没有 skill)'); return; }
  console.log(C.b(`仓库 skill(共 ${skills.length}):\n`));
  for (const s of skills) {
    const badges = Object.keys(ROOTS).map(t => {
      const st = stateAt(ROOTS[t].skillsDir, s.name);
      const sym = { linked: C.g('●'), copied: C.g('◆'), 'linked-other': C.y('◐'), none: C.dim('○') }[st];
      return `${t}:${sym}`;
    }).join('  ');
    console.log(`  ${C.b(s.name)}  ${badges}  ${C.dim('适用:' + skillTargets(s).join('/'))}`);
    if (s.meta.description) console.log(`      ${C.dim(s.meta.description.slice(0, 84))}`);
  }
  console.log(C.dim('\n●已链接 ◆已复制 ◐链到别处 ○未装'));
}

function cmdDoctor() {
  const { execSync } = require('child_process');
  let py = ''; try { py = execSync('python3 --version').toString().trim(); } catch {}
  console.log(C.b('环境自检:'));
  console.log(`  python3 : ${py ? C.g(py) : C.r('未找到(recall 需要)')}`);
  console.log(`  node    : ${C.g(process.version)}`);
  for (const t of Object.keys(ROOTS))
    console.log(`  ${t.padEnd(7)}: ${toolAvailable(t) ? C.g('已装 ' + ROOTS[t].skillsDir) : C.dim('未装此工具')}`);
  console.log('');
  cmdList();
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const flags = new Set(rest.filter(a => a.startsWith('--') && !a.startsWith('--target')));
  const targetArg = (rest.find(a => a.startsWith('--target')) || '').split('=')[1]
    || (rest.includes('--target') ? rest[rest.indexOf('--target') + 1] : '') || 'both';
  const args = rest.filter(a => !a.startsWith('--') && a !== targetArg);
  const opts = { copy: flags.has('--copy'), force: flags.has('--force') };
  const target = ['claude', 'codex', 'both'].includes(targetArg) ? targetArg : 'both';
  const all = flags.has('--all') || args[0] === 'all';

  switch (cmd) {
    case 'list': cmdList(); break;
    case 'doctor': cmdDoctor(); break;
    case 'install':
      if (all) discover().forEach(s => install(s.name, opts, target));
      else if (args[0]) install(args[0], opts, target);
      else { console.log('用法: claude-skills install <name|--all> [--target claude|codex|both] [--copy] [--force]'); break; }
      console.log(C.dim('\n新开对话即可用;已开着的会话需重启才能发现新 skill。'));
      break;
    case 'uninstall':
      if (all) discover().forEach(s => uninstall(s.name, target));
      else if (args[0]) uninstall(args[0], target);
      else console.log('用法: claude-skills uninstall <name|--all> [--target ...]');
      break;
    default:
      console.log(`claude-skills —— 个人 Claude Code / Codex skill 管理器

  claude-skills list                              列出 skill 及在各工具的安装状态
  claude-skills install <name|--all> [选项]        安装(默认两个工具都装)
  claude-skills uninstall <name|--all> [--target]  卸载
  claude-skills doctor                            环境自检

  选项: --target claude|codex|both(默认 both)  --copy 复制  --force 覆盖`);
  }
}
main();
