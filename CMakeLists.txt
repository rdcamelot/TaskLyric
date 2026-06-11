cmake_minimum_required(VERSION 3.21)

project(TaskLyric LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_subdirectory(native)
add_subdirectory(host)
add_subdirectory(launcher)
