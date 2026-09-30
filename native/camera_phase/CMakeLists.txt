cmake_minimum_required(VERSION 3.16)
project(flydrones_camera_phase_native LANGUAGES CXX)

find_package(gz-transport13 REQUIRED)
find_package(gz-msgs10 REQUIRED)
find_package(Threads REQUIRED)

add_library(flydrones_camera_phase_core
  src/camera_phase_native.cc
)
file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/include/flydrones/camera_phase_native.hpp" header_hash)
file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/src/camera_phase_native.cc" core_hash)
file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/src/main.cc" main_hash)
file(SHA256 "${CMAKE_CURRENT_SOURCE_DIR}/CMakeLists.txt" cmake_hash)
string(SHA256 camera_phase_source_hash
  "${header_hash}${core_hash}${main_hash}${cmake_hash}")
target_include_directories(flydrones_camera_phase_core PUBLIC include)
target_compile_features(flydrones_camera_phase_core PUBLIC cxx_std_17)
target_compile_definitions(flydrones_camera_phase_core PRIVATE
  FLYDRONES_CAMERA_PHASE_SOURCE_SHA256="${camera_phase_source_hash}"
)
set_target_properties(flydrones_camera_phase_core PROPERTIES
  CXX_STANDARD 17
  CXX_STANDARD_REQUIRED ON
  CXX_EXTENSIONS OFF
)
target_link_libraries(flydrones_camera_phase_core
  PUBLIC
    gz-transport13::core
    gz-msgs10::core
    Threads::Threads
)

add_executable(flydrones_camera_phase_native src/main.cc)
target_link_libraries(flydrones_camera_phase_native PRIVATE flydrones_camera_phase_core)
set_target_properties(flydrones_camera_phase_native PROPERTIES
  CXX_STANDARD 17
  CXX_STANDARD_REQUIRED ON
  CXX_EXTENSIONS OFF
)

include(CTest)
if(BUILD_TESTING)
  add_executable(camera_phase_native_test tests/camera_phase_native_test.cc)
  target_link_libraries(camera_phase_native_test PRIVATE flydrones_camera_phase_core)
  target_compile_definitions(camera_phase_native_test PRIVATE
    CAMERA_PHASE_VECTOR_PATH="${CMAKE_CURRENT_SOURCE_DIR}/../../tests/fixtures/camera_phase_vectors.json"
  )
  set_target_properties(camera_phase_native_test PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
  )
  add_test(NAME camera_phase_native_test COMMAND camera_phase_native_test)
endif()
