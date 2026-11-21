# Desktop simulator for the kiosk UI (Linux / macOS). See firmware/sim/README.md.
cmake_minimum_required(VERSION 3.16)
project(kiosk_sim C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

include(FetchContent)
FetchContent_Declare(lvgl GIT_REPOSITORY https://github.com/lvgl/lvgl.git GIT_TAG v8.3.11 GIT_SHALLOW TRUE)
FetchContent_GetProperties(lvgl)
if(NOT lvgl_POPULATED)
  FetchContent_Populate(lvgl)  # sources only; LVGL's own CMake is not used
endif()

set(FW ${CMAKE_CURRENT_SOURCE_DIR}/../main)
file(GLOB_RECURSE LVGL_SRC ${lvgl_SOURCE_DIR}/src/*.c)
file(GLOB FONT_SRC ${FW}/fonts/*.c)
add_library(lvgl_sim STATIC ${LVGL_SRC})
target_include_directories(lvgl_sim PUBLIC ${lvgl_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(lvgl_sim PUBLIC LV_CONF_INCLUDE_SIMPLE LV_LVGL_H_INCLUDE_SIMPLE)
if(MSVC)
  target_compile_options(lvgl_sim PRIVATE /W0)
else()
  target_compile_options(lvgl_sim PRIVATE -O2 -w)
endif()

add_executable(kiosk_sim sim_main.cpp ${FW}/ui/kiosk_app.cpp ${FW}/ui/i18n.cpp ${FONT_SRC})
target_include_directories(kiosk_sim PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/stubs ${FW} ${FW}/ui ${FW}/net ${FW}/storage
                           ${FW}/camera ${FW}/board ${FW}/display)
target_link_libraries(kiosk_sim PRIVATE lvgl_sim)
if(MSVC)
  target_compile_options(kiosk_sim PRIVATE /W3 /wd4244 /wd4267)
else()
  target_compile_options(kiosk_sim PRIVATE -Wall -Wextra -Wno-missing-field-initializers -Wno-unused-parameter)
endif()
# Windows: silence MSVC deprecation warnings for the standard C string/stdio functions the simulator uses.
if(WIN32)
  target_compile_definitions(kiosk_sim PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
endif()
