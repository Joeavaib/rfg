#pragma once
#include <string>
#include <vector>

struct Replace {
  std::string from;
  std::string to;
  std::vector<std::string> paths;
};

struct Step {
  std::string id;
  std::string title;
  std::vector<std::string> depends_on;
  Replace replace;
  bool has_replace = false;
  std::string verify;
  std::string engine;
  std::string edge;
  std::string oracle;
  std::string goal;
  int diff_budget = 0;
};

struct Goal {
  std::string id = "g1";
  std::string statement;
  std::string profile = "refactor";
  std::vector<std::string> acceptance;
};

struct Hypothesis {
  std::string id = "h1";
  std::string statement;
  std::string symbol;
  std::string from;
  std::string to;
};

struct Roadmap {
  int version = 0;
  std::string id;
  std::string verify;
  Goal goal;
  Hypothesis hypothesis;
  std::vector<Step> steps;
  int max_applies = 0;
};

struct Checkpoint {
  std::string id;
  std::string step_id;
  std::string commit;
  std::string worktree;
};

struct State {
  std::vector<std::string> applied;
  std::vector<std::string> verified;
  std::vector<std::string> failed;
  std::string worktree;
  std::string claim_step;
  std::string claim_agent;
  int applies_used = 0;
  Checkpoint last_checkpoint;
  bool has_checkpoint = false;
};
