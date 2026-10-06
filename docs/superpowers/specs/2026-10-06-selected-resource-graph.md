# Selected resource graph: static discovery and native selection

The user has authorized continuous execution and all plans. This stage implements a read-only preflight tool, never starts a simulator, estimator or flight process, and does not change the existing capture entry point until its coverage is established.

Use installed Gazebo Sim 8.15.0 / Common 5.9.0 / SDFormat 14.9.0 C++ APIs for plugin search paths, plugin library selection, media installation directory and model.config selection. Do not instantiate plugins or a Server. Prefer this small executable to reproducing native filename/version search rules in Python. Retain compiler arguments, package versions, binary and direct dependency hashes. These Apache-2.0 libraries are already installed; no new dependency is needed. Fixed gz-sim source 446a443 describes the selection paths, but lookup results are not runtime loading evidence.

Parse original SDF and COLLADA XML without serializing it back. Record each resource reference with its structural position and original text, including include/mesh/script/PBR texture/plugin and COLLADA image init_from. Surface unsupported URI locations instead of silently dropping them. Preserve repeated edges. Reject malformed XML, DTD/entity declarations, empty resource fields and missing plugin filenames. Internal COLLADA effect references are not external image files.

Native tool modes: installation directories; plugin lookup with exact installed SystemLoader.PluginPaths and SystemPaths.FindSharedLibrary; model directory selection using sdf::getModelFilePath with errors retained. Output a strict JSON object; bad operation/argument/control characters/missing resources exit nonzero. Plugin mode records all per-root native candidates and rejects multiple distinct canonical candidates. Never LoadPlugin/dlopen a selected plugin. Relative model paths are refused. Classic material path is obtained from the installed media API, not a guessed prefix.

This stage must run against original selected models and frozen PR48 world input, recording unresolved edges and scope gaps. Model roots and URI-to-local selection must be separately evidenced before complete graph qualification; a list of parsed references or installed candidates is not a selected full graph. Runtime closure, VIO fusion and physical verification remain false. Existing failures are not overwritten.

Reference `text` means the XML-parsed value (entity expansion of built-in entities and newline normalization), not an exact lexical substring. The original bytes and hashes remain the lexical evidence. External COLLADA url/source/href and instance_material target attributes produce unsupported markers; local fragment-only references are internal.

Native candidate ambiguity is checked across per-root native winners. Different filename aliases within a single root retain upstream priority and are not exhaustively enumerated. This limitation must travel with the result and cannot establish full alias uniqueness.

Remaining integration: authoritative URI/source-context resolution for meshes/textures/includes, actual graph-to-binding linkage, lazy render/sensor and owned child mapping lifecycle, then prospective trajectory/gauge contract. No new physical run until these are designed. No load or safety threshold changes.
