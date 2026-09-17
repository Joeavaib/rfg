#include "context.h"
#include "util.h"
#include <algorithm>
#include <dirent.h>
#include <set>
#include <sstream>

static const int MAX_FILES = 8;
static const int MAX_LINES = 40;

static std::string dir_of(const std::string& rel) {
  auto s = rel.rfind('/');
  if (s == std::string::npos) return ".";
  return rel.substr(0, s);
}

static void add_related(const std::string& root, const std::string& rel, std::vector<std::string>& extra,
                        const std::set<std::string>& already) {
  std::string parent = join_path(root, dir_of(rel));
  auto consider = [&](const std::string& r) {
    if (already.count(r) || std::find(extra.begin(), extra.end(), r) != extra.end()) return;
    if (file_exists(join_path(root, r))) extra.push_back(r);
  };
  std::string prefix = dir_of(rel);
  if (prefix == ".") prefix.clear();
  auto relname = [&](const std::string& name) {
    return prefix.empty() ? name : prefix + "/" + name;
  };
  consider(relname("Makefile"));
  consider(relname("CMakeLists.txt"));
  consider(relname("compile_commands.json"));
  consider("Makefile");
  DIR* d = opendir(parent.c_str());
  if (!d) return;
  auto stem = rel;
  auto sl = rel.rfind('/');
  std::string base = sl == std::string::npos ? rel : rel.substr(sl + 1);
  auto dot = base.rfind('.');
  std::string stemonly = dot == std::string::npos ? base : base.substr(0, dot);
  while (auto* ent = readdir(d)) {
    std::string n = ent->d_name;
    if (n.empty() || n[0] == '.') continue;
    auto d2 = n.rfind('.');
    std::string st = d2 == std::string::npos ? n : n.substr(0, d2);
    std::string suf = d2 == std::string::npos ? "" : n.substr(d2);
    bool cpp = suf == ".cc" || suf == ".cpp" || suf == ".h" || suf == ".hpp" || suf == ".c" || suf == ".hh";
    if (st == stemonly || cpp) consider(relname(n));
  }
  closedir(d);
}

static std::string snippet_obj(const std::string& rel, const std::string& text, const std::string& frm) {
  std::istringstream in(text);
  std::vector<std::string> lines;
  std::string line;
  while (std::getline(in, line)) lines.push_back(line);
  std::vector<int> pick;
  if (!frm.empty()) {
    std::set<int> show;
    int hits = 0;
    for (int i = 0; i < (int)lines.size() && hits < 8; ++i) {
      if (lines[i].find(frm) == std::string::npos) continue;
      hits++;
      for (int j = std::max(0, i - 2); j < std::min((int)lines.size(), i + 3); ++j) show.insert(j);
    }
    pick.assign(show.begin(), show.end());
    if ((int)pick.size() > MAX_LINES) pick.resize(MAX_LINES);
  }
  if (pick.empty()) {
    int n = std::min(MAX_LINES, (int)lines.size());
    for (int i = 0; i < n; ++i) pick.push_back(i);
  }
  std::ostringstream o;
  o << "{\n      \"path\": " << jstr(rel) << ",\n      \"lines\": [\n";
  for (size_t i = 0; i < pick.size(); ++i) {
    int n = pick[i];
    std::string t = n < (int)lines.size() ? lines[n] : "";
    if (t.size() > 200) t = t.substr(0, 200);
    if (i) o << ",\n";
    o << "        {\"n\": " << (n + 1) << ", \"text\": " << jstr(t) << "}";
  }
  o << "\n      ]\n    }";
  return o.str();
}

std::string context_json(const std::string& root, const Roadmap& rm, const State& st, const Step* step) {
  std::ostringstream o;
  o << "{\n";
  if (!step) {
    o << "    \"id\": null,\n    \"engine\": \"\",\n    \"path\": [],\n    \"snippets\": [],\n";
    o << "    \"tick\": \"done\",\n    \"verify\": " << jstr(rm.verify) << "\n  }";
    return o.str();
  }
  std::string eng = step->engine.empty() ? "replace" : step->engine;
  std::vector<std::string> paths = step->replace.paths;
  std::set<std::string> already(paths.begin(), paths.end());
  std::vector<std::string> extra;
  bool contract = eng == "implement";
  if (!contract) {
    for (auto& rel : paths) {
      if (!file_exists(join_path(root, rel))) add_related(root, rel, extra, already);
    }
  }
  std::vector<std::string> ordered;
  std::set<std::string> seen;
  for (auto& rel : paths) {
    if (seen.insert(rel).second) ordered.push_back(rel);
    if ((int)ordered.size() >= MAX_FILES) break;
  }
  for (auto& rel : extra) {
    if ((int)ordered.size() >= MAX_FILES) break;
    if (seen.insert(rel).second) ordered.push_back(rel);
  }
  o << "    \"id\": " << jstr(step->id) << ",\n";
  o << "    \"title\": " << jstr(step->title) << ",\n";
  o << "    \"engine\": " << jstr(eng) << ",\n";
  o << "    \"goal\": " << jstr(step->goal.empty() ? step->title : step->goal) << ",\n";
  o << "    \"from\": " << jstr(step->replace.from) << ",\n";
  o << "    \"to\": " << jstr(step->replace.to) << ",\n";
  o << "    \"path\": " << jarr(paths) << ",\n";
  std::vector<std::string> missing, exists;
  for (auto& rel : paths) {
    if (file_exists(join_path(root, rel))) exists.push_back(rel);
    else missing.push_back(rel);
  }
  o << "    \"exists\": " << jarr(exists) << ",\n";
  o << "    \"missing\": " << jarr(missing) << ",\n";
  o << "    \"depends\": " << jarr(step->depends_on) << ",\n";
  o << "    \"verify\": " << jstr(step->verify.empty() ? rm.verify : step->verify) << ",\n";
  o << "    \"tick\": " << jstr((eng == "manual" || eng == "implement") ? "stop" : "apply") << ",\n";
  o << "    \"claim_step\": " << jstr(st.claim_step) << ",\n";
  o << "    \"snippets\": [\n";
  bool first = true;
  for (auto& rel : ordered) {
    auto full = join_path(root, rel);
    if (!file_exists(full)) {
      if (contract) continue;
      if (!first) o << ",\n";
      first = false;
      o << "    {\"path\": " << jstr(rel) << ", \"error\": \"missing\", \"lines\": []}";
      continue;
    }
    if (!first) o << ",\n";
    first = false;
    o << "    " << snippet_obj(rel, read_file(full), step->replace.from);
  }
  o << "\n    ]\n  }";
  return o.str();
}
