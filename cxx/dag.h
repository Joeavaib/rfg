#pragma once
#include "types.h"
#include <string>

std::string next_id(const Roadmap& rm, const State& st);
const Step* step_by_id(const Roadmap& rm, const std::string& id);
Step* step_by_id_mut(Roadmap& rm, const std::string& id);
void mark_applied(State& st, const std::string& sid);
void mark_verified(State& st, const std::string& sid);
std::string step_status(const Roadmap& rm, const State& st, const Step& s);
int count_status(const Roadmap& rm, const State& st, const std::string& want);
