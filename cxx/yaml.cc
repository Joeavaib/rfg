#include "yaml.h"
#include "util.h"
#include <fstream>
#include <sstream>

static std::string unquote(std::string s) {
  while (!s.empty() && (s.front() == ' ' || s.front() == '\t')) s.erase(s.begin());
  while (!s.empty() && (s.back() == ' ' || s.back() == '\r')) s.pop_back();
  if (s.size() >= 2 && s.front() == '"' && s.back() == '"') return s.substr(1, s.size() - 2);
  return s;
}

static bool kv(const std::string& line, std::string& k, std::string& v) {
  auto i = line.find(':');
  if (i == std::string::npos) return false;
  k = unquote(line.substr(0, i));
  v = unquote(line.substr(i + 1));
  return true;
}

static int indent_of(const std::string& line) {
  int n = 0;
  while (n < (int)line.size() && line[n] == ' ') n++;
  return n;
}

Roadmap load_roadmap(const std::string& path) {
  Roadmap r;
  std::ifstream in(path);
  if (!in) return r;
  std::string line, section, sub;
  Step* cur = nullptr;
  bool in_replace = false, in_paths = false, in_depends = false;
  auto flush = [&]() { cur = nullptr; in_replace = in_paths = in_depends = false; };
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    int ind = indent_of(line);
    std::string trim = unquote(line);
    if (ind == 0) {
      flush();
      std::string k, v;
      if (!kv(trim, k, v)) continue;
      section = k;
      sub.clear();
      if (k == "version") r.version = v.empty() ? 0 : std::stoi(v);
      else if (k == "id") r.id = v;
      else if (k == "verify") r.verify = v;
      continue;
    }
    if (section == "goal" && ind == 2) {
      std::string k, v;
      if (!kv(trim, k, v)) continue;
      if (k == "id") r.goal.id = v;
      else if (k == "statement") r.goal.statement = v;
      else if (k == "profile") r.goal.profile = v;
      continue;
    }
    if (section == "hypothesis" && ind == 2) {
      std::string k, v;
      if (!kv(trim, k, v)) continue;
      if (k == "id") r.hypothesis.id = v;
      else if (k == "statement") r.hypothesis.statement = v;
      else if (k == "symbol") r.hypothesis.symbol = v;
      else if (k == "from" || k == "from_pat") r.hypothesis.from = v;
      else if (k == "to") r.hypothesis.to = v;
      continue;
    }
    if (section == "budget" && ind == 2) {
      std::string k, v;
      if (!kv(trim, k, v)) continue;
      if (k == "max_applies" && !v.empty()) r.max_applies = std::stoi(v);
      continue;
    }
    if (section != "steps") continue;
    if (ind == 2 && trim.rfind("- ", 0) == 0) {
      r.steps.push_back(Step{});
      cur = &r.steps.back();
      std::string rest = trim.substr(2);
      std::string k, v;
      if (kv(rest, k, v) && k == "id") cur->id = v;
      in_replace = in_paths = in_depends = false;
      continue;
    }
    if (!cur) continue;
    if (ind == 4) {
      std::string k, v;
      if (!kv(trim, k, v)) continue;
      if (k == "replace") {
        in_replace = true;
        in_depends = in_paths = false;
        cur->has_replace = true;
        continue;
      }
      if (k == "depends_on") {
        in_depends = true;
        in_replace = in_paths = false;
        continue;
      }
      in_replace = in_depends = in_paths = false;
      if (k == "id") cur->id = v;
      else if (k == "title") cur->title = v;
      else if (k == "verify") cur->verify = v;
      else if (k == "engine") cur->engine = v;
      else if (k == "goal") cur->goal = v;
      else if (k == "edge") cur->edge = v;
      else if (k == "oracle") cur->oracle = v;
      else if (k == "diff_budget" && !v.empty()) cur->diff_budget = std::stoi(v);
      continue;
    }
    if (ind == 6 && in_replace) {
      std::string k, v;
      if (!kv(trim, k, v)) continue;
      if (k == "paths") {
        in_paths = true;
        continue;
      }
      if (k == "from") cur->replace.from = v;
      else if (k == "to") cur->replace.to = v;
      continue;
    }
    if (ind >= 6 && in_depends && trim.rfind("- ", 0) == 0)
      cur->depends_on.push_back(unquote(trim.substr(2)));
    if (ind >= 8 && in_paths && trim.rfind("- ", 0) == 0)
      cur->replace.paths.push_back(unquote(trim.substr(2)));
  }
  return r;
}

State load_state(const std::string& path) {
  State s;
  std::string all = read_file(path);
  if (all.empty()) return s;
  json_get_array(all, "applied", s.applied);
  json_get_array(all, "verified", s.verified);
  json_get_array(all, "failed", s.failed);
  s.worktree = json_get_string(all, "worktree");
  s.claim_step = json_get_string(all, "claim_step");
  s.claim_agent = json_get_string(all, "claim_agent");
  s.applies_used = json_get_int(all, "applies_used", 0);
  s.last_checkpoint.commit = json_get_string(all, "commit");
  s.last_checkpoint.step_id = json_get_string(all, "step_id");
  s.has_checkpoint = !s.last_checkpoint.commit.empty();
  return s;
}

bool save_state(const std::string& path, const State& st) {
  std::ostringstream o;
  o << "{\n";
  o << "  \"applied\": " << jarr(st.applied) << ",\n";
  o << "  \"verified\": " << jarr(st.verified) << ",\n";
  o << "  \"failed\": " << jarr(st.failed) << ",\n";
  o << "  \"worktree\": " << jstr(st.worktree) << ",\n";
  if (st.has_checkpoint) {
    o << "  \"last_checkpoint\": {\n";
    o << "    \"id\": " << jstr(st.last_checkpoint.id) << ",\n";
    o << "    \"step_id\": " << jstr(st.last_checkpoint.step_id) << ",\n";
    o << "    \"commit\": " << jstr(st.last_checkpoint.commit) << ",\n";
    o << "    \"worktree\": " << jstr(st.last_checkpoint.worktree) << "\n";
    o << "  },\n";
  } else {
    o << "  \"last_checkpoint\": null,\n";
  }
  o << "  \"checkpoints\": [],\n";
  o << "  \"claim_step\": " << jstr(st.claim_step) << ",\n";
  o << "  \"claim_agent\": " << jstr(st.claim_agent) << ",\n";
  o << "  \"applies_used\": " << st.applies_used << "\n";
  o << "}\n";
  auto slash = path.rfind('/');
  if (slash != std::string::npos) mkdir_p(path.substr(0, slash));
  return write_file(path, o.str());
}

static void dump_list(std::ostringstream& o, const std::string& indent, const std::vector<std::string>& v) {
  for (auto& x : v) o << indent << "- " << x << "\n";
}

bool save_roadmap(const std::string& path, const Roadmap& rm) {
  std::ostringstream o;
  o << "version: " << rm.version << "\n";
  o << "id: " << rm.id << "\n";
  o << "hypothesis:\n";
  o << "  id: " << rm.hypothesis.id << "\n";
  o << "  statement: " << rm.hypothesis.statement << "\n";
  o << "  symbol: " << rm.hypothesis.symbol << "\n";
  o << "goal:\n";
  o << "  id: " << rm.goal.id << "\n";
  o << "  statement: " << rm.goal.statement << "\n";
  o << "  profile: " << rm.goal.profile << "\n";
  o << "verify: " << rm.verify << "\n";
  o << "budget:\n  max_applies: " << rm.max_applies << "\n";
  o << "steps:\n";
  for (auto& s : rm.steps) {
    o << "  - id: " << s.id << "\n";
    if (!s.title.empty()) o << "    title: " << s.title << "\n";
    if (!s.depends_on.empty()) {
      o << "    depends_on:\n";
      dump_list(o, "      ", s.depends_on);
    }
    if (!s.engine.empty()) o << "    engine: " << s.engine << "\n";
    if (!s.goal.empty()) o << "    goal: " << s.goal << "\n";
    if (!s.verify.empty()) o << "    verify: " << s.verify << "\n";
    if (!s.edge.empty()) o << "    edge: " << s.edge << "\n";
    if (!s.oracle.empty()) o << "    oracle: " << s.oracle << "\n";
    o << "    replace:\n";
    o << "      from: \"" << s.replace.from << "\"\n";
    o << "      to: \"" << s.replace.to << "\"\n";
    if (!s.replace.paths.empty()) {
      o << "      paths:\n";
      dump_list(o, "        ", s.replace.paths);
    }
  }
  auto slash = path.rfind('/');
  if (slash != std::string::npos) mkdir_p(path.substr(0, slash));
  return write_file(path, o.str());
}

Roadmap default_roadmap() {
  Roadmap r;
  r.version = 3;
  r.id = "roadmap-1";
  r.verify = "test -n ok";
  r.goal.statement = "";
  r.hypothesis.statement = "";
  r.hypothesis.symbol = "";
  return r;
}
