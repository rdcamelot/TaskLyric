add_library(tasklyric_host SHARED
  src/dllmain.cpp
  src/host_context.cpp
  src/exports.cpp
)

target_include_directories(tasklyric_host
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${PROJECT_SOURCE_DIR}/native/include
)

target_link_libraries(tasklyric_host
  PRIVATE
    tasklyric_native
)

target_compile_definitions(tasklyric_host
  PRIVATE
    UNICODE
    _UNICODE
)

set_target_properties(tasklyric_host PROPERTIES
  OUTPUT_NAME "tasklyric_host"
  PREFIX ""
)
