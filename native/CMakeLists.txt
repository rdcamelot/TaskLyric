add_library(tasklyric_native STATIC
  src/native_bridge.cpp
)

target_include_directories(tasklyric_native
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_definitions(tasklyric_native
  PRIVATE
    UNICODE
    _UNICODE
)
