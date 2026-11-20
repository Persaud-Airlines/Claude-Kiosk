file(GLOB_RECURSE APP_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp" "${CMAKE_CURRENT_SOURCE_DIR}/*.c")

idf_component_register(
    SRCS ${APP_SOURCES}
    INCLUDE_DIRS "." "board" "display" "net" "storage" "camera" "ui" "fonts"
    REQUIRES esp_lcd esp_wifi esp_netif esp_event nvs_flash esp_http_client esp-tls json driver
             esp_timer esp_system mbedtls usb app_update
    EMBED_FILES "assets/mock_card.jpg"
    EMBED_TXTFILES "certs/host_ca.pem"
)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-missing-field-initializers -Wno-unused-const-variable)
