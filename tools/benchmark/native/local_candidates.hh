// Local candidate diagnostics derived from Apache-2 Gazebo Common442a7ab
// SystemPaths/Material and SDFormat97d9b0 SDF.cc. OSRF copyright2012/2016.
// https://www.apache.org/licenses/LICENSE-2.0
// No selection ordering is emulated: the installed SDK remains the winner.
#include <regex>
#include <gz/common/URI.hh>
#include <gz/common/StringUtils.hh>
#include <sdf/Filesystem.hh>
#include <sdf/sdf_config.h>

struct LocalCandidates
{
  std::vector<std::string> examined;
  std::set<std::string> choices;
  std::set<std::string> dependencies;
  bool qualified = false;
};

void localLexicalProfile(const std::string &kind, const std::string &uri)
{
  auto value = uri;
  if (value.rfind("model://", 0) == 0) value = value.substr(8);
  else if (value.rfind("file://", 0) == 0) value = value.substr(7);
  if (value.empty() || !std::regex_match(value, std::regex("[A-Za-z0-9_./-]+")))
    throw std::runtime_error("URI outside bounded local lexical profile");
  for (const auto &part : fs::path(value))
    if (part == ".." || part == ".")
      throw std::runtime_error("relative traversal outside bounded local profile");
  if (kind == "include" && fs::path(value).is_absolute())
    throw std::runtime_error("absolute include outside bounded profile");
  if (kind == "collada-image" && value != uri)
    throw std::runtime_error("COLLADA URI scheme outside bounded profile");
}

void localCandidateCheck(LocalCandidates &out, const std::string &kind,
    const std::string &source, const std::string &uri,
    const std::string &transformed, const std::string &selected)
{
  auto add = [&](const std::string &path) { out.examined.push_back(path); };
  auto commonLocations = [&](std::string value)
  {
    if (gz::common::URI::Valid(value))
    {
      const gz::common::URI parsed(value);
      if (parsed.Authority())
        value = parsed.Authority()->Str().substr(2) + parsed.Path().Str();
      else
      {
        value = parsed.Path().Str();
        if (parsed.Path().IsAbsolute() && parsed.Scheme() != "file") value = value.substr(1);
      }
    }
    if (fs::path(value).is_absolute()) add(value);
    else
    {
      add(gz::common::joinPaths(gz::common::cwd(), value));
      for (const auto &path : gz::common::systemPaths()->FilePaths())
        add(gz::common::SystemPaths::NormalizeDirectoryPath(path) + value);
    }
  };
  if (kind == "include")
  {
    const sdf::ParserConfig config;
    if (!config.URIPathMap().empty())
      throw std::runtime_error("uncovered SDFormat URI mapping");
    auto value = uri;
    auto scheme = value.find("://");
    if (scheme != std::string::npos) value = value.substr(scheme + 3);
    auto share = sdf::getSharePath();
    if (share == "/") share = "";
    add(sdf::filesystem::append(sdf::filesystem::current_path(), value));
    add(sdf::filesystem::append(share, value));
    add(sdf::filesystem::append(share, "sdformat" + std::string(SDF_MAJOR_VERSION_STR),
                                sdf::SDF::Version(), value));
    add(value);
    if (const char *paths = std::getenv("SDF_PATH"))
      for (const auto &path : gz::common::Split(paths, ':'))
        add(sdf::filesystem::append(path, value));
  }
  else if (kind == "collada-image")
  {
    const auto parent = fs::path(source).parent_path().string();
    add(gz::common::joinPaths(parent, uri));
    commonLocations(uri);
    add(gz::common::joinPaths(parent, "..", "materials", "textures", uri));
  }
  else commonLocations(transformed);
  for (const auto &path : out.examined)
  {
    if (!fs::exists(path) && !fs::is_symlink(fs::symlink_status(path))) continue;
    if (kind == "include" && fs::is_directory(path))
    {
      out.dependencies.insert(regular((fs::path(path) / "model.config").string()));
      sdf::Errors errors;
      const auto file = sdf::getModelFilePath(errors, path);
      if (!errors.empty()) throw std::runtime_error("candidate model.config selection failed");
      out.choices.insert(regular(file));
    }
    else out.choices.insert(regular(path));
  }
  if (out.choices.size() != 1 || *out.choices.begin() != selected)
    throw std::runtime_error("ambiguous or uncovered local URI candidates");
  out.qualified = true;
}
