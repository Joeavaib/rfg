#include "apply.h"
#include "util.h"
#include <cctype>
#include <tuple>
#include <vector>

using Span = std::tuple<std::string, size_t, size_t>;

static std::vector<Span> skip_spans(const std::string& src, const std::string& suffix) {
  std::vector<Span> spans;
  size_t n = src.size(), i = 0;
  bool py = suffix == ".py";
  bool ticks = suffix == ".go" || suffix == ".ts" || suffix == ".js" || suffix == ".tsx" || suffix == ".jsx";
  while (i < n) {
    if (i + 1 < n && src[i] == '/' && src[i + 1] == '*') {
      auto j = src.find("*/", i + 2);
      j = j == std::string::npos ? n : j + 2;
      spans.emplace_back("comment", i, j);
      i = j;
      continue;
    }
    if (i + 1 < n && src[i] == '/' && src[i + 1] == '/') {
      auto j = src.find('\n', i);
      j = j == std::string::npos ? n : j;
      spans.emplace_back("comment", i, j);
      i = j;
      continue;
    }
    if (py && src[i] == '#') {
      auto j = src.find('\n', i);
      j = j == std::string::npos ? n : j;
      spans.emplace_back("comment", i, j);
      i = j;
      continue;
    }
    if (src[i] == '"' || src[i] == '\'') {
      char q = src[i];
      size_t j = i + 1;
      while (j < n) {
        if (src[j] == '\\') {
          j += 2;
          continue;
        }
        if (src[j] == q) {
          j++;
          break;
        }
        j++;
      }
      spans.emplace_back("string_literal", i, j);
      i = j;
      continue;
    }
    if (ticks && src[i] == '`') {
      auto j = src.find('`', i + 1);
      j = j == std::string::npos ? n : j + 1;
      spans.emplace_back("string_literal", i, j);
      i = j;
      continue;
    }
    i++;
  }
  return spans;
}

static std::string kind_at(size_t pos, const std::vector<Span>& spans) {
  for (auto& sp : spans) {
    if (std::get<1>(sp) <= pos && pos < std::get<2>(sp)) return std::get<0>(sp);
  }
  return "";
}

static std::pair<std::string, int> replace_preserving(const std::string& src, const std::string& frm,
                                                      const std::string& to, const std::string& suffix,
                                                      std::vector<std::string>& skipped) {
  if (frm.empty()) return {src, 0};
  auto spans = skip_spans(src, suffix);
  std::string out;
  int hits = 0;
  size_t i = 0, n = src.size();
  while (i < n) {
    auto j = src.find(frm, i);
    if (j == std::string::npos) {
      out += src.substr(i);
      break;
    }
    out += src.substr(i, j - i);
    auto kind = kind_at(j, spans);
    if (kind == "string_literal" || kind == "comment") {
      skipped.push_back(kind);
      out += frm;
      i = j + frm.size();
      continue;
    }
    auto ident = [](char c) { return std::isalnum(static_cast<unsigned char>(c)) || c == '_'; };
    char prev = j ? src[j - 1] : '\0';
    char nxt = (j + frm.size() < n) ? src[j + frm.size()] : '\0';
    if ((prev && ident(prev)) || (nxt && ident(nxt))) {
      out += frm;
      i = j + frm.size();
      continue;
    }
    hits++;
    out += to;
    i = j + frm.size();
  }
  return {out, hits};
}

ApplyOut apply_replace(const std::string& root, const Step& step, bool dry) {
  ApplyOut o;
  if (!step.has_replace || step.replace.from.empty()) return o;
  for (auto& rel : step.replace.paths) {
    auto full = join_path(root, rel);
    if (!file_exists(full)) {
      o.skipped.push_back("missing:" + rel);
      continue;
    }
    auto src = read_file(full);
    if (src.find(step.replace.from) == std::string::npos) continue;
    std::vector<std::string> sk;
    auto neu = replace_preserving(src, step.replace.from, step.replace.to, suffix_of(rel), sk);
    for (auto& s : sk) o.skipped.push_back(s);
    if (neu.second) {
      o.hits += neu.second;
      o.files.push_back({rel, neu.second});
      if (!dry) write_file(full, neu.first);
    }
  }
  return o;
}
