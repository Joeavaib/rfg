#pragma once
#include "types.h"
#include <string>

std::string context_json(const std::string& root, const Roadmap& rm, const State& st, const Step* step);
