cmake_minimum_required(VERSION 3.16)
project(flydrones_xrce_typed_probe C)

find_package(microxrcedds_client REQUIRED)
add_executable(flydrones_xrce_typed_probe client.c)
set_target_properties(flydrones_xrce_typed_probe PROPERTIES
    C_STANDARD 99
    C_STANDARD_REQUIRED YES)
target_compile_options(flydrones_xrce_typed_probe PRIVATE
    -Wall -Wextra -Werror)
target_link_libraries(flydrones_xrce_typed_probe PRIVATE microxrcedds_client)
