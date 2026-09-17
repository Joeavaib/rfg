#pragma once
#include <string>
#include <vector>

bool git_is_repo(const std::string& dir);
bool git_dirty(const std::string& dir);
bool git_dirty_tracked(const std::string& dir);
std::string git_head(const std::string& dir);
std::string git_ensure_worktree(const std::string& root);
int git_reset_hard(const std::string& dir, const std::string& commit);
std::string git_snapshot(const std::string& dir, const std::string& msg);
int git_land(const std::string& root, const std::string& wt, std::vector<std::string>& files,
             std::vector<std::string>& deleted);
void git_revert_land(const std::string& root, const std::vector<std::string>& files,
                     const std::vector<std::string>& olds, const std::vector<int>& existed);
