#include "git.h"
#include "util.h"
#include <climits>
#include <cstdio>
#include <cstdlib>
#include <sstream>

static std::string abspath(const std::string& p) {
  char buf[PATH_MAX];
  if (!realpath(p.c_str(), buf)) return p;
  return buf;
}

static std::pair<int, std::string> git(const std::string& dir, const std::string& args) {
  return run_cmd(dir, "git " + args);
}

bool git_is_repo(const std::string& dir) {
  auto r = git(dir, "rev-parse --is-inside-work-tree");
  return r.first == 0;
}

bool git_dirty(const std::string& dir) {
  auto top = git(dir, "rev-parse --show-toplevel");
  if (top.first != 0) return false;
  std::string t = top.second;
  while (!t.empty() && (t.back() == '\n' || t.back() == '\r')) t.pop_back();
  if (abspath(dir) != t) return false;
  auto st = git(dir, "status --porcelain");
  if (st.first != 0) return false;
  std::istringstream in(st.second);
  std::string line;
  while (std::getline(in, line)) {
    if (line.size() < 4) continue;
    std::string path = line.substr(3);
    while (!path.empty() && (path.front() == ' ' || path.front() == '"')) path.erase(path.begin());
    if (!path.empty() && path.back() == '"') path.pop_back();
    if (path.rfind(".rfg/", 0) == 0 || path == ".rfg") continue;
    if (!path.empty()) return true;
  }
  return false;
}

std::string git_head(const std::string& dir) {
  auto r = git(dir, "rev-parse HEAD");
  std::string s = r.second;
  while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
  return r.first == 0 ? s : "";
}

std::string git_ensure_worktree(const std::string& root) {
  std::string wt = join_path(join_path(root, ".rfg"), "worktree");
  if (file_exists(join_path(wt, ".git"))) return wt;
  git(root, std::string("worktree remove --force \"") + wt + "\"");
  run_cmd(root, std::string("rm -rf \"") + wt + "\"");
  git(root, std::string("worktree add --detach \"") + wt + "\" HEAD");
  return wt;
}

int git_reset_hard(const std::string& dir, const std::string& commit) {
  return git(dir, "reset --hard " + commit).first;
}

std::string git_snapshot(const std::string& dir, const std::string& msg) {
  git(dir, "add -A");
  git(dir, std::string("commit -m \"") + msg + "\" --allow-empty");
  return git_head(dir);
}

bool git_dirty_tracked(const std::string& dir) {
  auto top = git(dir, "rev-parse --show-toplevel");
  if (top.first != 0) return false;
  std::string t = top.second;
  while (!t.empty() && (t.back() == '\n' || t.back() == '\r')) t.pop_back();
  if (abspath(dir) != t) return false;
  auto st = git(dir, "status --porcelain");
  if (st.first != 0) return false;
  std::istringstream in(st.second);
  std::string line;
  while (std::getline(in, line)) {
    if (line.size() < 4) continue;
    if (line.compare(0, 2, "??") == 0) continue;
    std::string path = line.substr(3);
    while (!path.empty() && (path.front() == ' ' || path.front() == '"')) path.erase(path.begin());
    if (!path.empty() && path.back() == '"') path.pop_back();
    if (path.rfind(".rfg/", 0) == 0 || path == ".rfg") continue;
    if (!path.empty()) return true;
  }
  return false;
}

static std::string parent_of(const std::string& p) {
  auto n = p.find_last_of('/');
  if (n == std::string::npos) return ".";
  return p.substr(0, n);
}

int git_land(const std::string& root, const std::string& wt, std::vector<std::string>& files,
             std::vector<std::string>& deleted) {
  files.clear();
  deleted.clear();
  std::string base = git_head(root);
  auto diff = git(wt, std::string("diff --name-status ") + base);
  std::istringstream in(diff.first == 0 ? diff.second : "");
  std::string line;
  std::vector<std::pair<std::string, bool>> kinds;
  auto add = [&](const std::string& rel, bool del) {
    if (rel.empty() || rel.rfind(".rfg", 0) == 0 || rel.find("..") != std::string::npos) return;
    for (auto& k : kinds)
      if (k.first == rel) {
        k.second = del;
        return;
      }
    kinds.push_back({rel, del});
  };
  while (std::getline(in, line)) {
    if (line.size() < 3) continue;
    auto tab = line.find('\t');
    if (tab == std::string::npos) continue;
    std::string st = line.substr(0, tab);
    std::string rel = line.substr(line.rfind('\t') + 1);
    add(rel, st[0] == 'D');
  }
  auto un = git(wt, "status --porcelain -uall");
  std::istringstream in2(un.first == 0 ? un.second : "");
  while (std::getline(in2, line)) {
    if (line.size() < 4) continue;
    std::string rel = line.substr(3);
    while (!rel.empty() && (rel.front() == ' ' || rel.front() == '"')) rel.erase(rel.begin());
    if (!rel.empty() && rel.back() == '"') rel.pop_back();
    auto arrow = rel.find(" -> ");
    if (arrow != std::string::npos) rel = rel.substr(arrow + 4);
    add(rel, line.compare(0, 2, " D") == 0 || line.compare(0, 2, "D ") == 0);
  }
  for (auto& k : kinds) {
    std::string src = join_path(wt, k.first);
    std::string dst = join_path(root, k.first);
    if (k.second || !file_exists(src)) {
      if (file_exists(dst)) {
        std::remove(dst.c_str());
        deleted.push_back(k.first);
      }
      continue;
    }
    mkdir_p(parent_of(dst));
    write_file(dst, read_file(src));
    files.push_back(k.first);
  }
  return static_cast<int>(files.size() + deleted.size());
}

void git_revert_land(const std::string& root, const std::vector<std::string>& files,
                     const std::vector<std::string>& olds, const std::vector<int>& existed) {
  for (size_t i = 0; i < files.size(); ++i) {
    std::string dst = join_path(root, files[i]);
    if (i < existed.size() && existed[i])
      write_file(dst, i < olds.size() ? olds[i] : "");
    else
      std::remove(dst.c_str());
  }
}
