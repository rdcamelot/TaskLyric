add_library(tasklyric_native STATIC
  src/native_bridge.cpp
  src/taskbar_window.cpp
  src/taskbar_dcomp_renderer.cpp
  src/taskbar_locator.cpp
)

target_include_directories(tasklyric_native
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(tasklyric_native
  PRIVATE
    d2d1
    d3d11
    dcomp
    dwrite
    dxgi
    gdi32
    ole32
    oleaut32
    user32
)

target_compile_definitions(tasklyric_native
  PRIVATE
    UNICODE
    _UNICODE
)
