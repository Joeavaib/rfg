#pragma once
#include <string>
#include <utility>

bool is_trivial(const std::string& cmd);
std::pair<int, std::string> run_verify(const std::string& dir, const std::string& cmd);
