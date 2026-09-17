#include "dag.h"
#include <algorithm>

static bool contains(const std::vector<std::string>& v, const std::string& x) {
  return std::find(v.begin(), v.end(), x) != v.end();
}

const Step* step_by_id(const Roadmap& rm, const std::string& id) {
  for (auto& s : rm.steps)
    if (s.id == id) return &s;
  return nullptr;
}

Step* step_by_id_mut(Roadmap& rm, const std::string& id) {
  for (auto& s : rm.steps)
    if (s.id == id) return &s;
  return nullptr;
}

static bool dep_done(const Roadmap& rm, const State& st, const std::string& d) {
  auto* dep = step_by_id(rm, d);
  if (dep && dep->engine == "implement") return contains(st.verified, d);
  return contains(st.verified, d) || contains(st.applied, d);
}

std::string next_id(const Roadmap& rm, const State& st) {
  for (auto& s : rm.steps) {
    if (contains(st.verified, s.id) || contains(st.applied, s.id)) continue;
    if (contains(st.failed, s.id)) continue;
    bool ready = true;
    for (auto& d : s.depends_on) {
      if (!dep_done(rm, st, d)) {
        ready = false;
        break;
      }
    }
    if (ready) return s.id;
  }
  return "";
}

void mark_applied(State& st, const std::string& sid) {
  if (!contains(st.applied, sid)) st.applied.push_back(sid);
}

void mark_verified(State& st, const std::string& sid) {
  if (!contains(st.verified, sid)) st.verified.push_back(sid);
}

std::string step_status(const Roadmap& rm, const State& st, const Step& s) {
  if (contains(st.failed, s.id)) return "failed";
  if (contains(st.verified, s.id)) return "verified";
  if (contains(st.applied, s.id)) return s.engine == "implement" ? "implemented" : "applied";
  for (auto& d : s.depends_on) {
    if (!dep_done(rm, st, d)) return "blocked";
  }
  if (st.claim_step == s.id) return "in_progress";
  return "ready";
}

int count_status(const Roadmap& rm, const State& st, const std::string& want) {
  int n = 0;
  for (auto& s : rm.steps)
    if (step_status(rm, st, s) == want) n++;
  return n;
}
