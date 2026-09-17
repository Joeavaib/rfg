#pragma once
#include "types.h"
#include <string>

Roadmap load_roadmap(const std::string& path);
State load_state(const std::string& path);
bool save_state(const std::string& path, const State& st);
bool save_roadmap(const std::string& path, const Roadmap& rm);
Roadmap default_roadmap();
