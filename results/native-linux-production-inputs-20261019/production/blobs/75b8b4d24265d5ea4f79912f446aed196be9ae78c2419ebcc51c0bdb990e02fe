# New target only. Configuration/build requires a separately admitted source/tool closure.
cmake_minimum_required(VERSION 3.20)
project(flydrones_openvins_offset_reset_v2 LANGUAGES CXX)
# exclusive_probe_output.h uses std::filesystem; this adapter needs C++17.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT IS_ABSOLUTE "${OPENVINS_SOURCE_DIR}" OR
   NOT OPENVINS_FIXED_SOURCES STREQUAL "${CMAKE_BINARY_DIR}/openvins-fixed-sources.cmake")
  message(FATAL_ERROR "Fixed admitted source and exclusive generated selection required")
endif()
if(DEFINED OV_MSCKF OR DEFINED OPENVINS_LIBRARY_DIR)
  message(FATAL_ERROR "Existing OpenVINS libraries are forbidden")
endif()
find_package(Eigen3 REQUIRED NO_MODULE)
find_package(OpenCV 4 REQUIRED COMPONENTS core imgproc video calib3d features2d imgcodecs highgui)
find_package(Boost REQUIRED COMPONENTS filesystem system thread date_time chrono)
find_package(Ceres REQUIRED)
# Explicit frozen 34-TU selection; do not run upstream's ROS discovery, glob or O3/g3 recipe.
include("${OPENVINS_FIXED_SOURCES}")
list(LENGTH FIXED_OPENVINS_SOURCES fixed_count)
if(NOT fixed_count EQUAL 34)
  message(FATAL_ERROR "Expected exactly 34 fixed OpenVINS translation units")
endif()
add_library(ov_msckf_lib SHARED ${FIXED_OPENVINS_SOURCES})
set_target_properties(ov_msckf_lib PROPERTIES LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}")
target_compile_definitions(ov_msckf_lib PUBLIC ROS_AVAILABLE=0 ENABLE_ARUCO_TAGS=0)
target_include_directories(ov_msckf_lib PUBLIC
  "${OPENVINS_SOURCE_DIR}/ov_msckf/src" "${OPENVINS_SOURCE_DIR}/ov_core/src"
  "${OPENVINS_SOURCE_DIR}/ov_init/src" ${OpenCV_INCLUDE_DIRS} ${CERES_INCLUDE_DIRS})
target_link_libraries(ov_msckf_lib PUBLIC Eigen3::Eigen ${OpenCV_LIBS} ${CERES_LIBRARIES}
  Boost::filesystem Boost::system Boost::thread Boost::date_time Boost::chrono)
add_executable(openvins_offset_reset_v2 ../openvins_online_probe_v2.cpp)
set_target_properties(openvins_offset_reset_v2 PROPERTIES BUILD_RPATH "$ORIGIN")
target_include_directories(openvins_offset_reset_v2 PRIVATE
  "${OPENVINS_SOURCE_DIR}/ov_msckf/src" "${OPENVINS_SOURCE_DIR}/ov_core/src"
  "${OPENVINS_SOURCE_DIR}/ov_init/src" ${OpenCV_INCLUDE_DIRS} ${CERES_INCLUDE_DIRS})
target_link_libraries(openvins_offset_reset_v2 PRIVATE
  ov_msckf_lib Eigen3::Eigen ${OpenCV_LIBS} ${CERES_LIBRARIES}
  Boost::filesystem Boost::system Boost::thread Boost::date_time Boost::chrono)
