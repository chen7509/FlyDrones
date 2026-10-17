# Fixed Fast-DDS gitlink objects: source audit design

## Purpose and boundary

Continue the [direct XRCE Agent dependency audit](../../PX4_AGENT_DEPENDENCY_OBJECTS_REPORT.md) by checking the four exact gitlinks in fixed Fast-DDS commit `575d045b55c16be1074ccd9eebf95e3e4274fe61`. This is an isolated source-object study. It must not start CMake, Docker builds, PX4, Gazebo or training while host memory is low. Its success does not mean the Agent's transitive dependency graph or binary is qualified.

## Fixed inputs and method

Read the parent's raw `.gitmodules` and tree with replacement refs disabled, then bind each path, URL and object ID before fetch. The four paths and IDs are `thirdparty/android-ifaddrs` `7b1ce82817226e481d3cda0a5d06b66ebcc211f8`, `thirdparty/asio` `ed6aa8a13d51dfc6c00ae453fc9fb7df5d6ea963`, `thirdparty/fastcdr` `1bc9c919311ffce555b445560bf7ae062a4e1c72`, and `thirdparty/tinyxml2` `8c8293ba8969a46947606a93ff0cb5a083aab47a`. Their URLs come from that same `.gitmodules`, not a guessed checkout. Fetch each exact ID into a separate new bare Git store; retain fetch failures, do not replace a missing object with a moving branch. Verify the requested object is a commit, read tree and all modes, source license bytes/path, nested gitlinks and build-time fetch declarations. Use an independent read-back audit before any claim.

The root license filename can differ by repository. Accept only a previously inventoried, fixed regular Git blob path, and retain unknown/missing license as unresolved; do not silently infer a license from GitHub's current default branch. Record current GitHub metadata separately from the historical commit and state any license conclusion as source-file evidence plus explicit interpretation.

## Build-selection question

Fixed [Fast DDS 2.14 CMake options](https://fast-dds.docs.eprosima.com/en/2.14.x/installation/configuration/cmake_options.html) permit installed packages or internal Asio/TinyXML2/Fast-CDR sources. Read the fixed Fast-DDS CMake logic and the Agent superbuild defaults to enumerate selection conditions, including Android-only `android-ifaddrs`, `THIRDPARTY_UPDATE`, and system packages. Record the pinned Fast-CDR gitlink's difference from the Agent's direct Fast-CDR ID. A static source scan cannot prove an actual CMake selection, installed package ABI, compiler flags or runtime library closure; these fields stay false until a separately frozen configuration/build proves them.

## Verification and evidence

Use synthetic RED/GREEN rejection tests for wrong parent path/URL/ID, wrong fetched object or absent pinned ref, nonregular license path, unmapped nested gitlink and incomplete inventory. Preserve every failure and exact command; seal the four stores, manifest, current-source metadata, checks, report and provenance limits with member hashes. Keep old evidence untouched. No attempt to build an Agent unless memory and all source/system dependencies are independently qualified.
