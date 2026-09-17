#include "cli.h"
#include "apply.h"
#include "context.h"
#include "dag.h"
#include "git.h"
#include "util.h"
#include "verify.h"
#include "yaml.h"
#include <iostream>
#include <sstream>
#include <unistd.h>

static const int OK = 0, USAGE = 1, VERIFY_FAIL = 2, DIRTY = 3, UNSUPPORTED = 4, CONFLICT = 5;

static std::string find_root(int argc, char** argv) {
  for (int i = 1; i < argc - 1; ++i)
    if (std::string(argv[i]) == "--root") return argv[i + 1];
  char buf[4096];
  if (getcwd(buf, sizeof(buf))) return std::string(buf);
  return ".";
}

static std::string cmd_of(int argc, char** argv) {
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--root" || a == "--format") {
      i++;
      continue;
    }
    if (a.rfind("--", 0) == 0) continue;
    return a;
  }
  return "help";
}

static std::vector<std::string> rest_args(int argc, char** argv) {
  std::vector<std::string> out;
  bool seen = false;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--root" || a == "--format") {
      i++;
      continue;
    }
    if (a.rfind("--", 0) == 0) {
      if (seen) out.push_back(a);
      continue;
    }
    if (!seen) {
      seen = true;
      continue;
    }
    out.push_back(a);
  }
  // flags after command: include --foo bar pairs from argv after cmd
  seen = false;
  out.clear();
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--root" || a == "--format") {
      i++;
      continue;
    }
    if (!seen) {
      if (a.rfind("--", 0) != 0) seen = true;
      continue;
    }
    out.push_back(a);
  }
  return out;
}

static bool has_flag(const std::vector<std::string>& a, const std::string& f) {
  for (auto& x : a)
    if (x == f) return true;
  return false;
}

static std::string flag_val(const std::vector<std::string>& a, const std::string& f) {
  for (size_t i = 0; i + 1 < a.size(); ++i)
    if (a[i] == f) return a[i + 1];
  return "";
}

static void emit(const std::string& cmd, const std::string& data, bool ok = true, const std::string& err = "") {
  std::cout << "{\n  \"ok\": " << (ok ? "true" : "false") << ",\n  \"command\": " << jstr(cmd);
  if (!err.empty()) std::cout << ",\n  \"error\": " << jstr(err);
  if (!data.empty()) std::cout << ",\n  \"data\": " << data;
  std::cout << "\n}\n";
}

static std::string store_dir(const std::string& root) { return join_path(root, ".rfg"); }
static std::string roadmap_path(const std::string& root) { return join_path(store_dir(root), "roadmap.yaml"); }
static std::string state_path(const std::string& root) { return join_path(store_dir(root), "state.json"); }

static std::string step_json(const Roadmap& rm, const State& st, const Step* step) {
  std::ostringstream o;
  o << "{\n";
  if (!step) {
    o << "    \"id\": null,\n    \"engine\": \"\",\n    \"from\": \"\",\n    \"to\": \"\",\n";
    o << "    \"path\": [],\n    \"depends\": [],\n    \"verify\": " << jstr(rm.verify) << ",\n";
    o << "    \"next\": null,\n    \"blocked_reason\": \"no free step\",\n";
    o << "    \"claim_step\": " << jstr(st.claim_step) << ",\n";
    o << "    \"claim_agent\": " << jstr(st.claim_agent) << ",\n";
    o << "    \"applies_used\": " << st.applies_used << ",\n";
    o << "    \"budget\": {\"max_applies\": " << rm.max_applies << "}\n  }";
    return o.str();
  }
  std::string eng = step->engine.empty() ? "replace" : step->engine;
  o << "    \"id\": " << jstr(step->id) << ",\n";
  o << "    \"engine\": " << jstr(eng) << ",\n";
  o << "    \"goal\": " << jstr(step->goal.empty() ? step->title : step->goal) << ",\n";
  o << "    \"from\": " << jstr(step->replace.from) << ",\n";
  o << "    \"to\": " << jstr(step->replace.to) << ",\n";
  o << "    \"path\": " << jarr(step->replace.paths) << ",\n";
  o << "    \"depends\": " << jarr(step->depends_on) << ",\n";
  o << "    \"verify\": " << jstr(step->verify.empty() ? rm.verify : step->verify) << ",\n";
  o << "    \"oracle\": " << jstr(step->oracle.empty() ? "test" : step->oracle) << ",\n";
  o << "    \"edge\": " << jstr(step->edge) << ",\n";
  o << "    \"blocked_reason\": \"\",\n";
  o << "    \"next\": " << jstr(step->id) << ",\n";
  o << "    \"title\": " << jstr(step->title) << ",\n";
  o << "    \"claim_step\": " << jstr(st.claim_step) << ",\n";
  o << "    \"claim_agent\": " << jstr(st.claim_agent) << ",\n";
  o << "    \"applies_used\": " << st.applies_used << ",\n";
  o << "    \"budget\": {\"max_applies\": " << rm.max_applies << "}\n  }";
  return o.str();
}

static int cmd_next(const std::string& root) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  auto* step = nid.empty() ? nullptr : step_by_id(rm, nid);
  emit("next", step_json(rm, st, step));
  return OK;
}

static int cmd_status(const std::string& root) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  std::ostringstream o;
  o << "{\n    \"roadmap_id\": " << jstr(rm.id) << ",\n";
  o << "    \"next\": " << (nid.empty() ? "null" : jstr(nid)) << ",\n";
  o << "    \"dirty\": " << (git_is_repo(root) && git_dirty(root) ? "true" : "false") << ",\n";
  o << "    \"claim_step\": " << jstr(st.claim_step) << ",\n";
  o << "    \"applies_used\": " << st.applies_used << ",\n";
  o << "    \"steps\": [\n";
  for (size_t i = 0; i < rm.steps.size(); ++i) {
    if (i) o << ",\n";
    o << "      {\"id\": " << jstr(rm.steps[i].id) << ", \"status\": " << jstr(step_status(rm, st, rm.steps[i]))
      << "}";
  }
  o << "\n    ]\n  }";
  emit("status", o.str());
  return OK;
}

static int cmd_progress(const std::string& root) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  bool dirty = false;
  if (git_is_repo(root)) {
    for (auto& s : rm.steps) {
      auto e = s.engine.empty() ? "replace" : s.engine;
      bool pending = false;
      for (auto& a : st.applied)
        if (a == s.id) pending = true;
      for (auto& v : st.verified)
        if (v == s.id) pending = false;
      if (pending && (e == "replace" || e == "ast-grep" || e == "scaffold")) {
        dirty = git_dirty_tracked(root);
        break;
      }
    }
  }
  int failed = count_status(rm, st, "failed");
  std::ostringstream o;
  o << "{\n    \"goal\": {\n      \"id\": " << jstr(rm.goal.id) << ",\n";
  o << "      \"statement\": " << jstr(rm.goal.statement) << ",\n";
  o << "      \"profile\": " << jstr(rm.goal.profile) << "\n    },\n";
  o << "    \"counts\": {\n";
  o << "      \"total\": " << rm.steps.size() << ",\n";
  o << "      \"verified\": " << count_status(rm, st, "verified") << ",\n";
  o << "      \"failed\": " << failed << ",\n";
  o << "      \"blocked\": " << count_status(rm, st, "blocked") << ",\n";
  o << "      \"ready\": " << count_status(rm, st, "ready") << "\n    },\n";
  o << "    \"next\": " << (nid.empty() ? "null" : jstr(nid)) << ",\n";
  o << "    \"exceptions\": [";
  if (dirty)
    o << "{\"kind\": \"dirty\", \"step\": \"\", \"detail\": \"mechanical apply left tracked files dirty\"}";
  o << "],\n    \"ok\": " << (!failed && !dirty ? "true" : "false") << "\n  }";
  emit("progress", o.str(), !failed && !dirty);
  return OK;
}

static int cmd_context(const std::string& root, const std::vector<std::string>& args) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  for (auto& a : args)
    if (a.rfind("-", 0) != 0) nid = a;
  auto* step = nid.empty() ? nullptr : step_by_id(rm, nid);
  emit("context", context_json(root, rm, st, step));
  return OK;
}

static int do_apply(const std::string& root, const std::vector<std::string>& args, bool dry) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  for (auto& a : args)
    if (a != "--dry-run" && a.rfind("-", 0) != 0) nid = a;
  if (nid.empty()) {
    emit("apply", "{}", false, "no free step");
    return OK;
  }
  auto* step = step_by_id(rm, nid);
  if (!step) {
    emit("apply", "{}", false, "unknown step " + nid);
    return USAGE;
  }
  std::string eng = step->engine.empty() ? "replace" : step->engine;
  if (eng != "replace" && eng != "manual" && eng != "implement") {
    emit("apply", "{}", false, "unsupported engine: " + eng);
    return UNSUPPORTED;
  }
  if (rm.max_applies && st.applies_used >= rm.max_applies) {
    emit("apply", "{}", false, "conflict: apply budget exhausted");
    return CONFLICT;
  }
  std::string agent = env_or("RFG_AGENT");
  if (!st.claim_agent.empty() && (agent.empty() || agent != st.claim_agent)) {
    emit("apply", "{}", false, "conflict: claimed by " + st.claim_agent);
    return CONFLICT;
  }
  std::string target = root;
  if (!dry) {
    if (!git_is_repo(root)) {
      emit("apply", "{}", false, "not a git repository");
      return USAGE;
    }
    bool dirty = git_dirty(root) && st.worktree.empty();
    if (eng == "implement") {
      target = root;
    } else if (dirty && eng != "manual") {
      emit("apply", "{}", false, "working tree dirty");
      return DIRTY;
    } else if (dirty && eng == "manual") {
      target = root;
    } else if (!(dirty && eng == "manual")) {
      target = git_ensure_worktree(root);
      st.worktree = target;
      auto snap = git_snapshot(target, "rfg checkpoint before " + nid);
      st.last_checkpoint = {"cp-" + nid, nid, snap, target};
      st.has_checkpoint = !snap.empty();
    }
  }
  ApplyOut ao;
  if (eng != "manual" && eng != "implement") ao = apply_replace(target, *step, dry);
  if (dry) {
    std::ostringstream o;
    o << "{\n    \"step\": " << jstr(nid) << ",\n    \"dry_run\": true,\n    \"hits\": " << ao.hits
      << ",\n    \"manual\": " << (eng == "manual" ? "true" : "false") << "\n  }";
    emit("apply", o.str());
    return OK;
  }
  mark_applied(st, nid);
  if (eng != "implement") st.applies_used++;
  save_state(state_path(root), st);
  std::ostringstream o;
  o << "{\n    \"step\": " << jstr(nid) << ",\n    \"hits\": " << ao.hits << ",\n    \"worktree\": "
    << jstr(target) << ",\n    \"manual\": " << (eng == "manual" ? "true" : "false") << "\n  }";
  emit("apply", o.str());
  return OK;
}

static int cmd_verify(const std::string& root, const std::vector<std::string>& args) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  std::string sid = st.applied.empty() ? "" : st.applied.back();
  for (auto& a : args)
    if (a.rfind("-", 0) != 0) sid = a;
  if (sid.empty()) {
    auto nid = next_id(rm, st);
    auto* nxt = nid.empty() ? nullptr : step_by_id(rm, nid);
    if (nxt && nxt->engine == "implement") sid = nid;
  }
  if (sid.empty()) {
    emit("verify", "{}", false, "no applied step");
    return USAGE;
  }
  auto* step = step_by_id(rm, sid);
  if (!step) {
    emit("verify", "{}", false, "unknown step");
    return USAGE;
  }
  if (step->engine == "implement") {
    bool have = false;
    for (auto& a : st.applied)
      if (a == sid) have = true;
    if (!have) {
      mark_applied(st, sid);
      save_state(state_path(root), st);
    }
  }
  std::string cmd = step->verify.empty() ? rm.verify : step->verify;
  std::string dir = st.worktree.empty() ? root : st.worktree;
  auto r = run_verify(dir, cmd);
  if (r.first == 4) {
    emit("verify", "{}", false, r.second);
    return UNSUPPORTED;
  }
  if (r.first != 0) {
    emit("verify", "{}", false, r.second + " verify failed");
    return VERIFY_FAIL;
  }
  mark_verified(st, sid);
  save_state(state_path(root), st);
  std::ostringstream o;
  o << "{\n    \"step\": " << jstr(sid) << ",\n    \"command\": " << jstr(cmd) << ",\n    \"output\": "
    << jstr(r.second) << "\n  }";
  emit("verify", o.str());
  return OK;
}

static int cmd_tick(const std::string& root, const std::vector<std::string>& args) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  auto* step = nid.empty() ? nullptr : step_by_id(rm, nid);
  if (!step) {
    emit("tick", std::string("{\"action\": \"done\", \"context\": ") + context_json(root, rm, st, step) + "}");
    return OK;
  }
  std::string eng = step->engine.empty() ? "replace" : step->engine;
  if (eng == "manual" || eng == "implement") {
    emit("tick", std::string("{\"action\": \"stop\", \"reason\": \"") + eng + "\", \"context\": " +
                     context_json(root, rm, st, step) + "}");
    return OK;
  }
  int code = do_apply(root, args, false);
  if (code == 0) code = cmd_verify(root, {});
  auto rm2 = load_roadmap(roadmap_path(root));
  auto st2 = load_state(state_path(root));
  auto* step2 = step_by_id(rm2, nid);
  std::ostringstream o;
  o << "{\"action\": " << jstr(code == 0 ? "applied" : "failed") << ", \"code\": " << code
    << ", \"context\": " << context_json(root, rm2, st2, step2) << "}";
  emit("tick", o.str(), code == 0);
  return code;
}

static int cmd_init(const std::string& root) {
  if (file_exists(roadmap_path(root))) {
    emit("init", "{}", false, "roadmap already exists");
    return CONFLICT;
  }
  auto rm = default_roadmap();
  save_roadmap(roadmap_path(root), rm);
  save_state(state_path(root), State{});
  std::ostringstream o;
  o << "{\"roadmap\": " << jstr(roadmap_path(root)) << ", \"state\": " << jstr(state_path(root)) << "}";
  emit("init", o.str());
  return OK;
}

static int cmd_plan(const std::string& root, const std::vector<std::string>& args) {
  Roadmap rm = file_exists(roadmap_path(root)) ? load_roadmap(roadmap_path(root)) : default_roadmap();
  Step step;
  bool have = false;
  std::string goal_arg;
  for (size_t i = 0; i < args.size(); ++i) {
    auto val = [&]() -> std::string {
      if (i + 1 < args.size()) return args[++i];
      return "";
    };
    if (args[i] == "--step") {
      step.id = val();
      have = true;
    } else if (args[i] == "--title") {
      step.title = val();
      have = true;
    } else if (args[i] == "--from") {
      step.replace.from = val();
      step.has_replace = true;
      have = true;
    } else if (args[i] == "--to") {
      step.replace.to = val();
      step.has_replace = true;
      have = true;
    } else if (args[i] == "--path") {
      step.replace.paths.push_back(val());
      step.has_replace = true;
      have = true;
    } else if (args[i] == "--engine") {
      step.engine = val();
      have = true;
    } else if (args[i] == "--verify") {
      auto v = val();
      if (have) step.verify = v;
      else rm.verify = v;
    } else if (args[i] == "--depends") {
      std::string d = val();
      std::string cur;
      for (char c : d + ",") {
        if (c == ',') {
          if (!cur.empty()) step.depends_on.push_back(cur);
          cur.clear();
        } else
          cur.push_back(c);
      }
    } else if (args[i] == "--goal")
      goal_arg = val();
    else if (args[i] == "--symbol") {
      rm.hypothesis.symbol = val();
      rm.hypothesis.from = val();
    } else if (args[i] == "--hypothesis")
      rm.hypothesis.statement = val();
  }
  if (!goal_arg.empty()) {
    if (have && !step.id.empty())
      step.goal = goal_arg;
    else
      rm.goal.statement = goal_arg;
  }
  if (have && !step.id.empty()) {
    auto* found = step_by_id_mut(rm, step.id);
    if (found) {
      if (!step.title.empty()) found->title = step.title;
      if (step.has_replace) found->replace = step.replace, found->has_replace = true;
      if (!step.depends_on.empty()) found->depends_on = step.depends_on;
      if (!step.verify.empty()) found->verify = step.verify;
      if (!step.engine.empty()) found->engine = step.engine;
      if (!step.goal.empty()) found->goal = step.goal;
    } else {
      if (step.title.empty()) step.title = step.id;
      rm.steps.push_back(step);
    }
  }
  save_roadmap(roadmap_path(root), rm);
  auto st = load_state(state_path(root));
  if (!file_exists(state_path(root))) save_state(state_path(root), st);
  emit("plan", std::string("{\"next\": ") +
                   (next_id(rm, st).empty() ? std::string("null") : jstr(next_id(rm, st))) + "}");
  return OK;
}

static int cmd_claim(const std::string& root, const std::vector<std::string>& args) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  auto nid = next_id(rm, st);
  std::string agent = flag_val(args, "--agent");
  if (agent.empty()) agent = env_or("RFG_AGENT", "agent");
  for (auto& a : args)
    if (a.rfind("-", 0) != 0) nid = a;
  if (nid.empty()) {
    emit("claim", "{}", false, "no free step");
    return OK;
  }
  st.claim_step = nid;
  st.claim_agent = agent;
  save_state(state_path(root), st);
  emit("claim", std::string("{\"step\": ") + jstr(nid) + ", \"agent\": " + jstr(agent) + "}");
  return OK;
}

static int cmd_land(const std::string& root) {
  auto rm = load_roadmap(roadmap_path(root));
  auto st = load_state(state_path(root));
  if (!git_is_repo(root)) {
    emit("land", "{}", false, "not a git repository");
    return USAGE;
  }
  if (!next_id(rm, st).empty() || !st.failed.empty()) {
    emit("land", "{}", false, "conflict: roadmap unfinished (next or failed steps)");
    return CONFLICT;
  }
  for (auto& a : st.applied) {
    bool ok = false;
    for (auto& v : st.verified)
      if (v == a) ok = true;
    if (!ok) {
      emit("land", "{}", false, "conflict: applied but not verified: " + a);
      return CONFLICT;
    }
  }
  if (git_dirty_tracked(root)) {
    emit("land", "{}", false, "working tree dirty");
    return DIRTY;
  }
  if (st.worktree.empty() || st.worktree == root) {
    emit("land", "{\"files\": [], \"deleted\": [], \"noop\": true, \"verify\": \"\"}");
    return OK;
  }
  std::vector<std::string> files, deleted;
  git_land(root, st.worktree, files, deleted);
  std::string sid = st.verified.empty() ? "" : st.verified.back();
  auto* step = sid.empty() ? nullptr : step_by_id(rm, sid);
  std::string cmd = (step && !step->verify.empty()) ? step->verify : rm.verify;
  if (files.empty() && deleted.empty()) {
    emit("land", std::string("{\"files\": [], \"deleted\": [], \"noop\": true, \"verify\": ") + jstr(cmd) + "}");
    return OK;
  }
  auto r = run_verify(root, cmd);
  if (r.first != 0) {
    run_cmd(root, "git checkout -- .");
    emit("land", "{}", false, r.second + " land verify failed");
    return r.first == 4 ? UNSUPPORTED : VERIFY_FAIL;
  }
  std::ostringstream o;
  o << "{\n    \"files\": " << jarr(files) << ",\n    \"deleted\": " << jarr(deleted)
    << ",\n    \"noop\": false,\n    \"verify\": " << jstr(cmd) << ",\n    \"output\": " << jstr(r.second)
    << "\n  }";
  emit("land", o.str());
  return OK;
}

static int cmd_rollback(const std::string& root) {
  auto st = load_state(state_path(root));
  if (!st.has_checkpoint) {
    emit("rollback", "{}", false, "no checkpoint");
    return USAGE;
  }
  std::string target = st.worktree.empty() ? root : st.worktree;
  git_reset_hard(target, st.last_checkpoint.commit);
  save_state(state_path(root), st);
  emit("rollback", std::string("{\"commit\": ") + jstr(st.last_checkpoint.commit) + "}");
  return OK;
}

static int cmd_doctor(const std::string& root) {
  bool git = git_is_repo(root);
  bool cc = file_exists(join_path(root, "compile_commands.json")) ||
            file_exists(join_path(join_path(root, "cxx"), "compile_commands.json"));
  bool rm = file_exists(roadmap_path(root));
  std::ostringstream o;
  o << "{\"ok\": true, \"checks\": {\"git\": {\"ok\": " << (git ? "true" : "false")
    << "}, \"roadmap\": {\"ok\": " << (rm ? "true" : "false")
    << "}, \"compile_commands\": {\"ok\": true, \"detail\": " << (cc ? "true" : "false") << "}}}";
  emit("doctor", o.str());
  return OK;
}

int run_cli(int argc, char** argv) {
  std::string cmd = cmd_of(argc, argv);
  std::string root = find_root(argc, argv);
  auto args = rest_args(argc, argv);
  bool dry = has_flag(args, "--dry-run");
  if (cmd == "help" || cmd == "-h") {
    std::cout << "rfg (C++): init plan next status progress context tick apply verify land rollback claim doctor\n";
    return 0;
  }
  if (cmd == "next") return cmd_next(root);
  if (cmd == "status") return cmd_status(root);
  if (cmd == "progress") return cmd_progress(root);
  if (cmd == "context") return cmd_context(root, args);
  if (cmd == "apply") return do_apply(root, args, dry);
  if (cmd == "verify") return cmd_verify(root, args);
  if (cmd == "land") return cmd_land(root);
  if (cmd == "tick") return cmd_tick(root, args);
  if (cmd == "init") return cmd_init(root);
  if (cmd == "plan") return cmd_plan(root, args);
  if (cmd == "claim") return cmd_claim(root, args);
  if (cmd == "rollback") return cmd_rollback(root);
  if (cmd == "doctor") return cmd_doctor(root);
  emit(cmd, "{}", false, "unsupported command: " + cmd);
  return UNSUPPORTED;
}
