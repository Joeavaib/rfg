#include "verify.h"
#include "util.h"
#include <algorithm>
#include <cctype>

bool is_trivial(const std::string& cmd) {
  std::string s;
  for (char c : cmd) {
    if (!std::isspace(static_cast<unsigned char>(c))) s.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
  }
  return s.empty() || s == "true";
}

std::pair<int, std::string> run_verify(const std::string& dir, const std::string& cmd) {
  if (is_trivial(cmd)) return {4, "unsupported: trivial verify (need a real command, not true/empty)"};
  return run_cmd(dir, cmd);
}
