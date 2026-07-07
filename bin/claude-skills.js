#!/usr/bin/env node
'use strict';
/*
 * claude-skills —— 把本仓库里的 skill 装进 ~/.claude/skills/
 * 零依赖(只用 Node 内置)。默认软链接(symlink),便于多机 git pull 即时同步;
 * 也可 --copy 复制安装(适合 npm 全局装、node_modules 会变动的场景)。
 *
 *   claude-skills list                     列出仓库里的 skill 及安装状态
 *   claude-skills install <name|--all>     安装(默认 symlink;--copy 复制;--force 覆盖已存在)
 *   claude-skills uninstall <name|--all>   卸载(只删链接/我们装的副本)
 *   claude-skills doctor                   环境自检
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const REPO_SKILLS = path.join(__dirname, '..', 'skills');
const DEST_ROOT = path.join(os.homedir(), '.claude', 'skills');

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

function installState(name) {
  const dest = path.join(DEST_ROOT, name);
  if (!fs.existsSync(dest) && !isSymlink(dest)) return 'none';
  if (isSymlink(dest)) {
    const target = fs.readlinkSync(dest);
    const resolved = path.resolve(path.dirname(dest), target);
    return resolved === path.join(REPO_SKILLS, name) ? 'linked' : 'linked-other';
  }
  return 'copied-or-dir';
}

function isSymlink(p) { try { return fs.lstatSync(p).isSymbolicLink(); } catch { return false; } }

function rmrf(p) { fs.rmSync(p, { recursive: true, force: true }); }

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (e.name === '__pycache__' || e.name.startsWith('._')) continue;
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function install(name, { copy, force }) {
  const skills = discover();
  const sk = skills.find(s => s.name === name);
  if (!sk) { console.log(C.r(`✗ 仓库里没有 skill: ${name}`)); return false; }
  const dest = path.join(DEST_ROOT, name);
  fs.mkdirSync(DEST_ROOT, { recursive: true });

  if (fs.existsSync(dest) || isSymlink(dest)) {
    const st = installState(name);
    if (st === 'linked' && !copy) { console.log(C.dim(`= ${name} 已链接,跳过`)); return true; }
    if (!force) {
      console.log(C.y(`! ${name} 目标已存在(${st})。加 --force 覆盖(会先备份真实目录到 .bak)。`));
      return false;
    }
    if (!isSymlink(dest) && fs.statSync(dest).isDirectory()) {
      const bak = `${dest}.bak-${Date.now()}`;
      fs.renameSync(dest, bak);
      console.log(C.dim(`  已备份原目录 → ${bak}`));
    } else { rmrf(dest); }
  }

  if (copy) { copyDir(sk.src, dest); console.log(C.g(`✓ 复制安装 ${name}`)); }
  else { fs.symlinkSync(sk.src, dest, 'dir'); console.log(C.g(`✓ 链接安装 ${name}`) + C.dim(`  → ${sk.src}`)); }
  return true;
}

function uninstall(name) {
  const dest = path.join(DEST_ROOT, name);
  const st = installState(name);
  if (st === 'none') { console.log(C.dim(`= ${name} 未安装`)); return; }
  if (st === 'linked' || isSymlink(dest)) { fs.unlinkSync(dest); console.log(C.g(`✓ 已移除链接 ${name}`)); return; }
  console.log(C.y(`! ${name} 是复制/真实目录,未自动删除(避免误删)。如确认: rm -rf ${dest}`));
}

function cmdList() {
  const skills = discover();
  if (!skills.length) { console.log('(仓库里还没有 skill)'); return; }
  console.log(C.b(`仓库 skill(共 ${skills.length}):\n`));
  for (const s of skills) {
    const st = installState(s.name);
    const badge = { linked: C.g('● 已链接'), 'copied-or-dir': C.g('● 已复制'),
                    'linked-other': C.y('● 链到别处'), none: C.dim('○ 未装') }[st];
    console.log(`  ${badge}  ${C.b(s.name)}`);
    if (s.meta.description) console.log(`         ${C.dim(s.meta.description.slice(0, 90))}`);
  }
  console.log(C.dim(`\n目标目录: ${DEST_ROOT}`));
}

function cmdDoctor() {
  console.log(C.b('环境自检:'));
  const { execSync } = require('child_process');
  let py = ''; try { py = execSync('python3 --version').toString().trim(); } catch {}
  console.log(`  python3 : ${py ? C.g(py) : C.r('未找到(recall 需要)')}`);
  console.log(`  node    : ${C.g(process.version)}`);
  console.log(`  目标目录: ${fs.existsSync(DEST_ROOT) ? C.g(DEST_ROOT) : C.y(DEST_ROOT + ' (将自动创建)')}`);
  cmdList();
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const flags = new Set(rest.filter(a => a.startsWith('--')));
  const args = rest.filter(a => !a.startsWith('--'));
  const opts = { copy: flags.has('--copy'), force: flags.has('--force') };
  const all = flags.has('--all') || args[0] === 'all';

  switch (cmd) {
    case 'list': cmdList(); break;
    case 'doctor': cmdDoctor(); break;
    case 'install':
      if (all) discover().forEach(s => install(s.name, opts));
      else if (args[0]) install(args[0], opts);
      else console.log('用法: claude-skills install <name|--all> [--copy] [--force]');
      console.log(C.dim('\n新开对话即可用;已开着的会话需重启才能发现新 skill。'));
      break;
    case 'uninstall':
      if (all) discover().forEach(s => uninstall(s.name));
      else if (args[0]) uninstall(args[0]);
      else console.log('用法: claude-skills uninstall <name|--all>');
      break;
    default:
      console.log(`claude-skills —— 个人 Claude Code skill 管理器

  claude-skills list                    列出仓库 skill 与安装状态
  claude-skills install <name|--all>    安装(默认 symlink;--copy 复制;--force 覆盖)
  claude-skills uninstall <name|--all>  卸载
  claude-skills doctor                  环境自检`);
  }
}
main();
