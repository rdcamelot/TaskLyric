add_executable(tasklyric_launcher WIN32
  src/winmain.cpp
)

target_compile_definitions(tasklyric_launcher
  PRIVATE
    UNICODE
    _UNICODE
)

target_link_libraries(tasklyric_launcher
  PRIVATE
    shell32
    user32
)

set_target_properties(tasklyric_launcher PROPERTIES
  OUTPUT_NAME "tasklyric_launcher"
)
