#include "util.h"
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <sstream>
#include <sys/stat.h>
#include <sys/wait.h>

std::string jesc(const std::string& s) {
  std::string o;
  o.reserve(s.size());
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') {
      o.push_back('\\');
      o.push_back(static_cast<char>(c));
      continue;
    }
    if (c == '\n') {
      o += "\\n";
      continue;
    }
    if (c == '\r') {
      o += "\\r";
      continue;
    }
    if (c == '\t') {
      o += "\\t";
      continue;
    }
    if (c < 0x20) continue;
    o.push_back(static_cast<char>(c));
  }
  return o;
}

std::string jstr(const std::string& s) { return "\"" + jesc(s) + "\""; }

std::string jarr(const std::vector<std::string>& v) {
  std::string o = "[";
  for (size_t i = 0; i < v.size(); ++i) {
    if (i) o += ", ";
    o += jstr(v[i]);
  }
  o += "]";
  return o;
}

std::string read_file(const std::string& path) {
  std::ifstream in(path);
  if (!in) return "";
  return std::string((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

bool write_file(const std::string& path, const std::string& body) {
  std::ofstream out(path);
  if (!out) return false;
  out << body;
  return true;
}

bool mkdir_p(const std::string& path) {
  if (path.empty()) return false;
  std::string cur;
  for (size_t i = 0; i < path.size(); ++i) {
    cur.push_back(path[i]);
    if (path[i] == '/' || i + 1 == path.size()) {
      if (cur == "/" || cur.empty()) continue;
      mkdir(cur.c_str(), 0755);
    }
  }
  return true;
}

bool file_exists(const std::string& p) {
  struct stat st;
  return stat(p.c_str(), &st) == 0 && S_ISREG(st.st_mode);
}

std::string join_path(const std::string& a, const std::string& b) {
  if (a.empty()) return b;
  if (a.back() == '/') return a + b;
  return a + "/" + b;
}

std::string suffix_of(const std::string& p) {
  auto s = p.rfind('/');
  std::string n = s == std::string::npos ? p : p.substr(s + 1);
  auto d = n.rfind('.');
  if (d == std::string::npos) return "";
  return n.substr(d);
}

std::pair<int, std::string> run_cmd(const std::string& dir, const std::string& cmd) {
  std::string shell = "cd \"" + dir + "\" && " + cmd + " 2>&1";
  FILE* fp = popen(shell.c_str(), "r");
  if (!fp) return {1, "popen failed"};
  std::string out;
  char buf[4096];
  while (fgets(buf, sizeof(buf), fp)) out += buf;
  int st = pclose(fp);
  int code = WIFEXITED(st) ? WEXITSTATUS(st) : 1;
  return {code, out};
}

std::string json_get_string(const std::string& all, const std::string& key) {
  auto p = all.find("\"" + key + "\"");
  if (p == std::string::npos) return "";
  auto c = all.find(':', p);
  if (c == std::string::npos) return "";
  auto q = all.find('"', c);
  if (q == std::string::npos) return "";
  if (all.compare(c + 1, 4, "null") == 0 || all.find("null", c) < q) {
    auto n = all.find_first_not_of(" \t\n", c + 1);
    if (n != std::string::npos && all.compare(n, 4, "null") == 0) return "";
  }
  std::string o;
  for (size_t i = q + 1; i < all.size(); ++i) {
    if (all[i] == '\\' && i + 1 < all.size()) {
      o.push_back(all[i + 1]);
      ++i;
      continue;
    }
    if (all[i] == '"') break;
    o.push_back(all[i]);
  }
  return o;
}

int json_get_int(const std::string& all, const std::string& key, int def) {
  auto p = all.find("\"" + key + "\"");
  if (p == std::string::npos) return def;
  auto c = all.find(':', p);
  if (c == std::string::npos) return def;
  try {
    return std::stoi(all.substr(c + 1));
  } catch (...) {
    return def;
  }
}

void json_get_array(const std::string& all, const std::string& key, std::vector<std::string>& out) {
  auto p = all.find("\"" + key + "\"");
  if (p == std::string::npos) return;
  auto lb = all.find('[', p);
  auto rb = all.find(']', lb);
  if (lb == std::string::npos || rb == std::string::npos) return;
  std::string body = all.substr(lb + 1, rb - lb - 1);
  std::string cur;
  bool inq = false;
  for (size_t i = 0; i < body.size(); ++i) {
    char c = body[i];
    if (c == '"' && (i == 0 || body[i - 1] != '\\')) {
      if (inq) {
        out.push_back(cur);
        cur.clear();
        inq = false;
      } else
        inq = true;
    } else if (inq)
      cur.push_back(c);
  }
}

std::string env_or(const char* name, const std::string& fallback) {
  const char* v = std::getenv(name);
  return v && *v ? std::string(v) : fallback;
}
