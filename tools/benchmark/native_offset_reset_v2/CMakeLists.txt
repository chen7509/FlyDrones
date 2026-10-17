# New target only. Configuration/build requires a separately admitted source/tool closure.
cmake_minimum_required(VERSION 3.20)
project(flydrones_openvins_offset_reset_v2 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT IS_ABSOLUTE "${OPENVINS_SOURCE_DIR}" OR NOT IS_ABSOLUTE "${OPENVINS_LIBRARY_DIR}")
  message(FATAL_ERROR "Explicit admitted OpenVINS source and library directories required")
endif()
find_package(Eigen3 REQUIRED NO_MODULE)
find_package(OpenCV 4 REQUIRED COMPONENTS core imgproc)
find_package(Boost REQUIRED COMPONENTS filesystem system thread date_time chrono)
find_package(Ceres REQUIRED)
# Pinned upstream's NO_ROS ov_msckf_lib includes core/init sources itself.
find_library(OV_MSCKF NAMES ov_msckf_lib PATHS "${OPENVINS_LIBRARY_DIR}" NO_DEFAULT_PATH REQUIRED)
add_executable(openvins_offset_reset_v2 ../openvins_online_probe_v2.cpp)
target_compile_definitions(openvins_offset_reset_v2 PRIVATE ROS_AVAILABLE=0)
target_include_directories(openvins_offset_reset_v2 PRIVATE
  "${OPENVINS_SOURCE_DIR}/ov_msckf/src" "${OPENVINS_SOURCE_DIR}/ov_core/src"
  "${OPENVINS_SOURCE_DIR}/ov_init/src" ${OpenCV_INCLUDE_DIRS} ${CERES_INCLUDE_DIRS})
target_link_libraries(openvins_offset_reset_v2 PRIVATE
  ${OV_MSCKF} Eigen3::Eigen ${OpenCV_LIBS} ${CERES_LIBRARIES}
  Boost::filesystem Boost::system Boost::thread Boost::date_time Boost::chrono)
