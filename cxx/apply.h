#pragma once
#include "types.h"
#include <string>
#include <vector>

struct ApplyHit {
  std::string path;
  int hits = 0;
};

struct ApplyOut {
  int hits = 0;
  std::vector<ApplyHit> files;
  std::vector<std::string> skipped;
  int code = 0;
  std::string error;
};

ApplyOut apply_replace(const std::string& root, const Step& step, bool dry);
