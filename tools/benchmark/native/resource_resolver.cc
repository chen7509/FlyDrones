// Installed SDK lookup only: never construct a Server or load a plugin.
// SystemPaths construction may create its configured/default log directory.
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <gz/common/SystemPaths.hh>
#include <gz/common/Material.hh>
#include <gz/common/Util.hh>
#include <gz/sim/InstallationDirectories.hh>
#include <gz/sim/SystemLoader.hh>
#include <gz/sim/Util.hh>
#include <sdf/ParserConfig.hh>
#include <sdf/InstallationDirectories.hh>
#include <sdf/SDFImpl.hh>
#include <sdf/parser.hh>

namespace fs = std::filesystem;

std::string json(const std::string &s)
{
  std::ostringstream o;
  o << '"';
  const char *hex = "0123456789abcdef";
  for (unsigned char c : s)
  {
    if (c == '"' || c == '\\') o << '\\' << c;
    else if (c < 32) o << "\\u00" << hex[c >> 4] << hex[c & 15];
    else o << c;
  }
  o << '"';
  return o.str();
}

std::string regular(const std::string &s)
{
  if (s.empty() || !fs::is_regular_file(s))
    throw std::runtime_error("selected resource is missing or nonregular");
  return fs::canonical(s).string();
}

std::string lookupEnvironment()
{
  std::ostringstream o;
  o << '{';
  bool first = true;
  for (const char *key : {"GZ_SIM_RESOURCE_PATH", "SDF_PATH", "GZ_FILE_PATH",
       "GZ_PLUGIN_PATH", "GZ_SIM_SYSTEM_PLUGIN_PATH", "HOME", "GZ_HOMEDIR",
       "GZ_MESH_FORCE_ASSIMP", "IGN_PLUGIN_PATH", "IGN_FILE_PATH",
       "IGN_GAZEBO_RESOURCE_PATH", "IGN_GAZEBO_SYSTEM_PLUGIN_PATH",
       "GZ_LOG_PATH", "IGN_LOG_PATH"})
  {
    if (!first) o << ',';
    first = false;
    const char *value = std::getenv(key);
    o << json(key) << ':' << (value ? json(value) : "null");
  }
  o << '}';
  return o.str();
}

template <class Container>
std::string strings(const Container &values)
{
  std::ostringstream out;
  out << '[';
  bool first = true;
  for (const auto &value : values)
  {
    if (!first) out << ',';
    first = false;
    out << json(value);
  }
  out << ']';
  return out.str();
}

// Spelling expansion adapted from Gazebo Common SystemPaths.cc at
// 442a7ab4f213e435c3ca93947004216f26ec728d, Copyright 2016 OSRF,
// Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0).
// The installed SDK still selects the winner. This diagnostic mirrors the
// fixed source's alternatives; it does not establish installed patch parity.
std::vector<std::string> librarySpellings(const std::string &name)
{
  auto lower = name;
  std::transform(lower.begin(), lower.end(), lower.begin(),
      [](unsigned char c) { return std::tolower(c); });
  auto ends = [&](const std::string &suffix)
  { return lower.size() >= suffix.size() &&
      lower.compare(lower.size() - suffix.size(), suffix.size(), suffix) == 0; };
  std::vector<std::string> initial{name};
  const bool hasLib = name.rfind("lib", 0) == 0;
  if (hasLib && ends(".so")) initial.push_back(name.substr(3, name.size() - 6));
  if (ends(".dll")) initial.push_back(name.substr(0, name.size() - 4));
  if (hasLib && ends(".dylib")) initial.push_back(name.substr(3, name.size() - 9));
  std::vector<std::string> result;
  for (const auto &n : initial)
    for (const auto &spelling : {n, "lib" + n + ".so", n + ".so", n + ".dll",
        "Release/" + n + ".dll", "Debug/" + n + ".dll", n + ".dll",
        "lib" + n + ".dylib", n + ".dylib", "lib" + n + ".SO", n + ".SO",
        n + ".DLL", "Release/" + n + ".DLL", "Debug/" + n + ".DLL",
        "lib" + n + ".DYLIB", n + ".DYLIB"})
      result.push_back(spelling);
  return result;
}

void searchContext()
{
  const auto before = lookupEnvironment();
  gz::sim::addResourcePaths();
  gz::sim::SystemLoader loader;
  gz::common::SystemPaths plugins;
  for (const auto &path : loader.PluginPaths()) plugins.AddPluginPaths(path);
  const auto &config = sdf::ParserConfig::GlobalConfig();
  std::ostringstream mappings;
  mappings << '{';
  bool first = true;
  for (const auto &[scheme, paths] : config.URIPathMap())
  {
    if (!first) mappings << ',';
    first = false;
    mappings << json(scheme) << ':' << strings(paths);
  }
  mappings << '}';
  std::cout << "{\"before_environment\":" << before
      << ",\"after_environment\":" << lookupEnvironment()
      << ",\"cwd\":" << json(fs::current_path().string())
      << ",\"file_paths\":" << strings(gz::common::systemPaths()->FilePaths())
      << ",\"plugin_paths\":" << strings(plugins.PluginPaths())
      << ",\"sdf_share_path\":" << json(sdf::getSharePath())
      << ",\"sdf_version\":" << json(sdf::SDF::Version())
      << ",\"sdf_uri_paths\":" << mappings.str()
      << ",\"sdf_callback_present\":" << (config.FindFileCallback() ? "true" : "false")
      << ",\"common_file_callbacks_present\":null,\"common_uri_callbacks_present\":null"
      << ",\"common_callback_observation\":\"unavailable: SDK has no callback inspection API\""
      << ",\"search_context_qualified\":false,\"runtime_closure_qualified\":false}\n";
}

int uriLookup(int argc, char **argv)
{
  const auto before = lookupEnvironment();
  const auto cwd = fs::current_path().string();
  std::string source, kind, uri, transformed, lookupSelected, selected, configFile, error;
  try
  {
    if (argc != 5) throw std::runtime_error("uri KIND SOURCE URI required");
    kind = argv[2]; source = argv[3]; uri = argv[4];
    for (int i = 2; i < argc; ++i)
      for (unsigned char c : std::string(argv[i]))
        if (c < 32 || c == 127) throw std::runtime_error("control character in URI arguments");
    if (!fs::path(source).is_absolute()) throw std::runtime_error("absolute source required");
    regular(source);  // Preserve lexical source for asFullPath, do not replace with canonical.
    if (uri.empty() || std::isspace(static_cast<unsigned char>(uri.front())) ||
        std::isspace(static_cast<unsigned char>(uri.back())))
      throw std::runtime_error("empty or surrounding whitespace URI");
    // A URI scheme does not require '//'. Never let a same-named local file
    // turn an unknown scheme (e.g. http:example) into an accepted query.
    auto colon = uri.find(':');
    auto slash = uri.find('/');
    if (colon != std::string::npos && (slash == std::string::npos || colon < slash) &&
        uri.rfind("file://", 0) != 0 && uri.rfind("model://", 0) != 0)
      throw std::runtime_error("remote or unsupported URI scheme");
    if (kind != "include" && kind != "texture" && kind != "mesh-path" && kind != "collada-image")
      throw std::runtime_error("unsupported URI kind");
    gz::sim::addResourcePaths();
    if (kind == "include")
    {
      sdf::ParserConfig config;
      config.SetFindCallback([](const std::string &) { return std::string(); });
      sdf::Errors errors;
      transformed = uri;
      lookupSelected = sdf::findFile(errors, uri, true, true, config);
      if (!errors.empty()) throw std::runtime_error("SDFormat include lookup error");
      if (!lookupSelected.empty() && fs::is_directory(lookupSelected))
      {
        configFile = regular((fs::path(lookupSelected) / "model.config").string());
        lookupSelected = sdf::getModelFilePath(errors, lookupSelected);
        if (!errors.empty()) throw std::runtime_error("SDFormat model selection error");
      }
    }
    else if (kind == "collada-image")
    {
      const char *force = std::getenv("GZ_MESH_FORCE_ASSIMP");
      if (force && std::string(force) == "true")
        throw std::runtime_error("forced Assimp outside COLLADA lookup profile");
      transformed = fs::path(source).parent_path().string();
      gz::common::Material material;
      material.SetTextureImage(uri, transformed);
      lookupSelected = material.TextureImage();
    }
    else
    {
      transformed = gz::sim::asFullPath(uri, source);
      lookupSelected = gz::common::findFile(transformed);
    }
    selected = regular(lookupSelected);
  }
  catch (const std::exception &e) { error = e.what(); }
  std::cout << "{\"ok\":" << (error.empty() ? "true" : "false")
            << ",\"kind\":" << json(kind) << ",\"source\":" << json(source)
            << ",\"uri\":" << json(uri) << ",\"transformed\":" << json(transformed)
            << ",\"lookup_selected\":" << json(lookupSelected)
            << ",\"selected\":" << json(selected) << ",\"model_config\":" << json(configFile)
            << ",\"cwd\":" << json(cwd) << ",\"before_environment\":" << before
            << ",\"after_environment\":" << lookupEnvironment()
            << ",\"error\":" << json(error)
            << ",\"ambiguity_qualified\":false,\"runtime_closure_qualified\":false}\n";
  if (!error.empty()) std::cerr << error << '\n';
  return error.empty() ? 0 : 2;
}

int main(int argc, char **argv)
{
  try
  {
    if (argc < 2) throw std::runtime_error("operation required");
    if (std::string(argv[1]) == "uri") return uriLookup(argc, argv);
    for (int i = 1; i < argc; ++i)
      for (unsigned char c : std::string(argv[i]))
        if (c < 32 || c == 127) throw std::runtime_error("control character in argument");
    const std::string op = argv[1];
    if (op == "context" && argc == 2)
      searchContext();
    else if (op == "installation" && argc == 2)
    {
      const auto media = gz::sim::getMediaInstallDir();
      std::cout << "{\"media\":" << json(media)
                << ",\"plugins\":" << json(gz::sim::getPluginInstallDir())
                << ",\"classic_material\":" << json(regular(media + "/gazebo.material")) << "}\n";
    }
    else if (op == "model" && argc == 3)
    {
      fs::path dir(argv[2]);
      if (!dir.is_absolute() || !fs::is_directory(dir))
        throw std::runtime_error("absolute existing model directory required");
      sdf::Errors errors;
      auto selected = sdf::getModelFilePath(errors, dir.string());
      if (!errors.empty())
      {
        for (const auto &e : errors) std::cerr << e.Message() << '\n';
        throw std::runtime_error("SDFormat model selection errors");
      }
      std::cout << "{\"selected\":" << json(regular(selected)) << "}\n";
    }
    else if (op == "plugin" && argc == 3)
    {
      std::string name(argv[2]);
      if (name.empty()) throw std::runtime_error("empty plugin filename");
      if (!fs::path(name).is_absolute() &&
          (name.find('/') != std::string::npos || name.find('\\') != std::string::npos ||
           name.find(':') != std::string::npos || name == "." || name == ".."))
        throw std::runtime_error("relative plugin path outside declared profile");
      auto pos = name.find("ignition-gazebo");
      if (pos != std::string::npos) name.replace(pos, 15, "gz-sim");
      gz::sim::SystemLoader loader;
      auto paths = loader.PluginPaths();
      gz::common::SystemPaths resolver;
      for (const auto &p : paths) resolver.AddPluginPaths(p);
      auto selected = regular(resolver.FindSharedLibrary(name));
      // Include default SystemPaths paths as well, matching the real resolver.
      auto allPaths = resolver.PluginPaths();
      std::set<std::string> candidates;
      std::string candidateError;
      std::vector<std::string> examined;
      if (fs::path(name).is_absolute()) examined.push_back(name);
      else
        for (const auto &p : allPaths)
          for (const auto &spelling : librarySpellings(name))
            examined.push_back(p + spelling);
      for (const auto &path : examined)
      {
        // A dangling symlink is an unresolved candidate, not silently missing.
        try
        {
          if (fs::is_symlink(fs::symlink_status(path)) || fs::exists(path))
            candidates.insert(regular(path));
        }
        catch (const std::exception &e)
        { candidateError += path + ": " + e.what() + "; "; }
      }
      if (candidates.size() != 1 || *candidates.begin() != selected)
        candidateError += "ambiguous or uncovered plugin candidates";
      std::cout << "{\"ok\":" << (candidateError.empty() ? "true" : "false")
                << ",\"error\":" << json(candidateError)
                << ",\"selected\":" << json(selected) << ",\"normalized\":" << json(name)
                << ",\"paths\":[";
      bool first = true;
      for (const auto &p : allPaths) { if (!first) std::cout << ','; first = false; std::cout << json(p); }
      std::cout << "],\"candidates\":[";
      first = true;
      for (const auto &p : candidates) { if (!first) std::cout << ','; first = false; std::cout << json(p); }
      std::cout << "],\"examined_paths\":" << strings(examined)
                << ",\"candidate_profile\":\"common-442a7ab-spellings\""
                << ",\"runtime_closure_qualified\":false}\n";
      if (!candidateError.empty()) throw std::runtime_error(candidateError);
    }
    else throw std::runtime_error("unknown operation or wrong argument count");
    return 0;
  }
  catch (const std::exception &e)
  {
    std::cerr << e.what() << '\n';
    return 2;
  }
}
