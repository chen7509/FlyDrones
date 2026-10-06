// Read-only installed SDK selection. Never construct a Server or load a plugin.
#include <filesystem>
#include <iostream>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <gz/common/SystemPaths.hh>
#include <gz/sim/InstallationDirectories.hh>
#include <gz/sim/SystemLoader.hh>
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

int main(int argc, char **argv)
{
  try
  {
    if (argc < 2) throw std::runtime_error("operation required");
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
