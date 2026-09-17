#pragma once
#include <string>
#include <utility>
#include <vector>

std::string jesc(const std::string& s);
std::string jstr(const std::string& s);
std::string jarr(const std::vector<std::string>& v);
std::string read_file(const std::string& path);
bool write_file(const std::string& path, const std::string& body);
bool mkdir_p(const std::string& path);
bool file_exists(const std::string& p);
std::string join_path(const std::string& a, const std::string& b);
std::string suffix_of(const std::string& p);
std::pair<int, std::string> run_cmd(const std::string& dir, const std::string& cmd);
std::string json_get_string(const std::string& all, const std::string& key);
int json_get_int(const std::string& all, const std::string& key, int def = 0);
void json_get_array(const std::string& all, const std::string& key, std::vector<std::string>& out);
std::string env_or(const char* name, const std::string& fallback = "");
