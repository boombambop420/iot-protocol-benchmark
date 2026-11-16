idf_component_register(
    SRCS "hello_world_main.c"
    PRIV_REQUIRES
        esp_wifi
        esp_event
        esp_netif
        nvs_flash
        esp_timer
        esp_http_client
        mqtt
        coap
    INCLUDE_DIRS ""
)