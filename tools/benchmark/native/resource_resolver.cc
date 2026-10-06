// Read-only installed SDK selection. Never construct a Server or load a plugin.
#include <filesystem>
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
       "GZ_MESH_FORCE_ASSIMP"})
  {
    if (!first) o << ',';
    first = false;
    const char *value = std::getenv(key);
    o << json(key) << ':' << (value ? json(value) : "null");
  }
  o << '}';
  return o.str();
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
    if (op == "installation" && argc == 2)
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
      for (const auto &p : allPaths)
      {
        gz::common::SystemPaths isolated;
        isolated.ClearPluginPaths();
        isolated.AddPluginPaths(p);
        auto found = isolated.FindSharedLibrary(name);
        if (!found.empty()) candidates.insert(regular(found));
      }
      if (candidates.size() != 1 || *candidates.begin() != selected)
        throw std::runtime_error("ambiguous or uncovered plugin candidates");
      std::cout << "{\"selected\":" << json(selected) << ",\"normalized\":" << json(name)
                << ",\"paths\":[";
      bool first = true;
      for (const auto &p : allPaths) { if (!first) std::cout << ','; first = false; std::cout << json(p); }
      std::cout << "],\"candidates\":[";
      first = true;
      for (const auto &p : candidates) { if (!first) std::cout << ','; first = false; std::cout << json(p); }
      std::cout << "]}\n";
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
