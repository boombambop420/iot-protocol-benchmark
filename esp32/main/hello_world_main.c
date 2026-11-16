#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "esp_http_client.h"
#include "mqtt_client.h"
#include "coap_config.h"
#include "coap3/coap.h"
#include <sys/socket.h>
#include <arpa/inet.h>
#define WIFI_SSID       "YOUR_WIFI_SSID"
#define WIFI_PASSWORD   "YOUR_WIFI_PASSWORD"
#define SERVER_IP       "192.168.20.2"
#define MQTT_BROKER     "mqtt://192.168.20.2:1883"
#define TIMEOUT_MS      10000
#define PAYLOAD_SIZE    64
#define WIFI_CONNECTED_BIT BIT0
#define MQTT_CONNECTED_BIT BIT1
#define MQTT_SUBSCRIBED_BIT BIT2
static const char *TAG = "IOT_BENCH";
static EventGroupHandle_t wifi_events;
static EventGroupHandle_t mqtt_events;
static SemaphoreHandle_t mqtt_response_sem;
static char mqtt_response[PAYLOAD_SIZE + 1];
static int mqtt_response_len = 0;
static int mqtt_active_qos = 0;
static bool wifi_ready = false;
/* =====================================================
   WIFI
   ===================================================== */
static void wifi_event_handler(
    void *arg,
    esp_event_base_t base,
    int32_t id,
    void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    }
  if (base == WIFI_EVENT &&
    id == WIFI_EVENT_STA_DISCONNECTED) {
    wifi_event_sta_disconnected_t *event = data;
    ESP_LOGW(TAG,
        "Wi-Fi disconnected! Reason code: %d",
        event->reason);
    xEventGroupClearBits(wifi_events, WIFI_CONNECTED_BIT);
    esp_wifi_connect();
}
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "Wi-Fi connected!");
        ESP_LOGI(TAG, "ESP32 IP: " IPSTR,
                 IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(wifi_events, WIFI_CONNECTED_BIT);
    }
}
static void wifi_init(void)
{
    wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_event_handler_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID,
        wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP,
        wifi_event_handler, NULL));
    wifi_config_t config = {0};
    strcpy((char *)config.sta.ssid, WIFI_SSID);
    strcpy((char *)config.sta.password, WIFI_PASSWORD);
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(
        WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    xEventGroupWaitBits(
        wifi_events,
        WIFI_CONNECTED_BIT,
        pdFALSE,
        pdTRUE,
        portMAX_DELAY
    );
    wifi_ready = true;
}
/* =====================================================
   HTTP
   ===================================================== */
typedef struct {
    uint8_t response[PAYLOAD_SIZE];
    int response_len;
} http_context_t;
static esp_err_t http_event_handler(
    esp_http_client_event_t *event)
{
    http_context_t *ctx = event->user_data;
    if (event->event_id == HTTP_EVENT_ON_DATA &&
        ctx != NULL) {
        int available = PAYLOAD_SIZE - ctx->response_len;
        int copy_len = event->data_len;
        if (copy_len > available) {
            copy_len = available;
        }
        if (copy_len > 0) {
            memcpy(
                ctx->response + ctx->response_len,
                event->data,
                copy_len
            );
            ctx->response_len += copy_len;
        }
    }
    return ESP_OK;
}
static bool http_request(
    esp_http_client_handle_t client,
    const uint8_t *payload,
    size_t len)
{
    http_context_t ctx = {0};
    esp_http_client_set_user_data(client, &ctx);
    esp_http_client_set_post_field(
        client,
        (const char *)payload,
        len
    );
    esp_err_t err = esp_http_client_perform(client);
    if (err != ESP_OK) {
        return false;
    }
    int status = esp_http_client_get_status_code(client);
    return (
        status == 200 &&
        ctx.response_len == len &&
        memcmp(ctx.response, payload, len) == 0
    );
}
static bool http_new_request(
    const uint8_t *payload,
    size_t len)
{
    esp_http_client_config_t config = {
        .url = "http://" SERVER_IP ":8080/echo",
        .method = HTTP_METHOD_POST,
        .timeout_ms = TIMEOUT_MS,
        .event_handler = http_event_handler,
    };
    esp_http_client_handle_t client =
        esp_http_client_init(&config);
    if (client == NULL) {
        return false;
    }
    bool result = http_request(client, payload, len);
    esp_http_client_cleanup(client);
    return result;
}
static bool http_keep_request(
    esp_http_client_handle_t client,
    const uint8_t *payload,
    size_t len)
{
    return http_request(client, payload, len);
}
/* =====================================================
   MQTT
   ===================================================== */
static void mqtt_event_handler(
    void *args,
    esp_event_base_t base,
    int32_t event_id,
    void *event_data)
{
    esp_mqtt_event_handle_t event = event_data;
    switch (event_id) {
        case MQTT_EVENT_CONNECTED:
{
    ESP_LOGI(TAG, "MQTT connected");

    xEventGroupClearBits(
        mqtt_events,
        MQTT_SUBSCRIBED_BIT
    );

    char topic[32];
    snprintf(
        topic,
        sizeof(topic),
        "lab/resp/%d",
        mqtt_active_qos
    );

    int msg_id = esp_mqtt_client_subscribe(
        event->client,
        topic,
        mqtt_active_qos
    );

    if (msg_id < 0) {
        ESP_LOGE(TAG, "MQTT subscribe failed");
    }

    xEventGroupSetBits(
        mqtt_events,
        MQTT_CONNECTED_BIT
    );
    break;
}
        case MQTT_EVENT_DISCONNECTED:
    xEventGroupClearBits(
        mqtt_events,
        MQTT_CONNECTED_BIT | MQTT_SUBSCRIBED_BIT
    );
    break;
        case MQTT_EVENT_SUBSCRIBED:
            xEventGroupSetBits(
                mqtt_events,
                MQTT_SUBSCRIBED_BIT
            );
            break;
        case MQTT_EVENT_DATA:
            if (event->topic_len > 0 &&
                event->data_len <= PAYLOAD_SIZE) {
                memcpy(
                    mqtt_response,
                    event->data,
                    event->data_len
                );
                mqtt_response_len = event->data_len;
                xSemaphoreGive(mqtt_response_sem);
            }
            break;
        default:
            break;
    }
}
static bool mqtt_request(
    esp_mqtt_client_handle_t client,
    int qos,
    const uint8_t *payload,
    size_t len)
{
    char topic[32];
    snprintf(topic, sizeof(topic),
             "lab/req/%d", qos);
    while (xSemaphoreTake(mqtt_response_sem, 0) == pdTRUE) {
    }
    mqtt_response_len = 0;
    int id = esp_mqtt_client_publish(
        client,
        topic,
        (const char *)payload,
        len,
        qos,
        0
    );
    if (id < 0) {
        return false;
    }
    if (xSemaphoreTake(
            mqtt_response_sem,
            pdMS_TO_TICKS(TIMEOUT_MS)) != pdTRUE) {
        return false;
    }
    return (
        mqtt_response_len == len &&
        memcmp(mqtt_response, payload, len) == 0
    );
}
/* =====================================================
   MQTT CLIENT SETUP
   ===================================================== */
static esp_mqtt_client_handle_t mqtt_start(int qos)
{
    mqtt_active_qos = qos;
    mqtt_events = xEventGroupCreate();
    mqtt_response_sem = xSemaphoreCreateBinary();
    esp_mqtt_client_config_t config = {
        .broker.address.uri = MQTT_BROKER,
        .session.message_retransmit_timeout = 5000,
    };
    esp_mqtt_client_handle_t client =
        esp_mqtt_client_init(&config);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(
        client,
        ESP_EVENT_ANY_ID,
        mqtt_event_handler,
        NULL
    ));
    ESP_ERROR_CHECK(esp_mqtt_client_start(client));
xEventGroupWaitBits(
    mqtt_events,
    MQTT_CONNECTED_BIT,
    pdFALSE,
    pdTRUE,
    portMAX_DELAY
);

xEventGroupWaitBits(
    mqtt_events,
    MQTT_SUBSCRIBED_BIT,
    pdFALSE,
    pdTRUE,
    pdMS_TO_TICKS(TIMEOUT_MS)
);

return client;
}
/* =====================================================
   COAP: one UDP session per run, unique token per request
   ===================================================== */
#define COAP_SERVER_PORT 5683
static bool coap_reply_received = false;
static bool coap_reply_valid = false;
static uint8_t coap_expected[PAYLOAD_SIZE];
static uint8_t coap_token[8];
static size_t coap_token_len = 0;
static int64_t coap_rtt_us = -1;
static int64_t coap_start_us = 0;
static coap_response_t coap_response_handler(
    coap_session_t *session,
    const coap_pdu_t *sent,
    const coap_pdu_t *received,
    const coap_mid_t mid)
{
    (void)session;
    (void)sent;
    (void)mid;
    coap_bin_const_t token = coap_pdu_get_token(received);
    if (token.length != coap_token_len ||
        memcmp(token.s, coap_token, coap_token_len) != 0) {
        /* Late reply from an earlier request: ignore it. */
        return COAP_RESPONSE_OK;
    }
    const uint8_t *data = NULL;
    size_t len = 0, offset = 0, total = 0;
    coap_pdu_code_t code = coap_pdu_get_code(received);
    coap_reply_valid =
        COAP_RESPONSE_CLASS(code) == 2 &&
        coap_get_data_large(received, &len, &data, &offset, &total) &&
        offset == 0 && len == PAYLOAD_SIZE && total == PAYLOAD_SIZE &&
        memcmp(data, coap_expected, PAYLOAD_SIZE) == 0;
    coap_rtt_us = esp_timer_get_time() - coap_start_us;
    coap_reply_received = true;
    return COAP_RESPONSE_OK;
}
static bool coap_open(coap_context_t **ctx, coap_session_t **session)
{
    *ctx = NULL;
    *session = NULL;
    coap_startup();
    *ctx = coap_new_context(NULL);
    if (!*ctx) {
        coap_cleanup();
        return false;
    }
    coap_register_response_handler(*ctx, coap_response_handler);
    coap_address_t destination;
    coap_address_init(&destination);
    destination.addr.sin.sin_family = AF_INET;
    destination.addr.sin.sin_port = htons(COAP_SERVER_PORT);
    if (inet_pton(AF_INET, SERVER_IP,
                  &destination.addr.sin.sin_addr) != 1) {
        coap_free_context(*ctx);
        *ctx = NULL;
        coap_cleanup();
        return false;
    }
    destination.size = sizeof(struct sockaddr_in);
    *session = coap_new_client_session(
        *ctx, NULL, &destination, COAP_PROTO_UDP);
    if (!*session) {
        coap_free_context(*ctx);
        *ctx = NULL;
        coap_cleanup();
        return false;
    }
    return true;
}
static bool coap_request(coap_context_t *ctx,
                         coap_session_t *session,
                         coap_pdu_type_t type,
                         const uint8_t *payload, size_t length)
{
    if (length != PAYLOAD_SIZE) return false;
    coap_reply_received = false;
    coap_reply_valid = false;
    coap_rtt_us = -1;
    memcpy(coap_expected, payload, PAYLOAD_SIZE);
    coap_pdu_t *pdu = coap_new_pdu(type, COAP_REQUEST_CODE_POST, session);
    if (!pdu) return false;
    coap_session_new_token(session, &coap_token_len, coap_token);
    if (!coap_add_token(pdu, coap_token_len, coap_token) ||
        !coap_add_option(pdu, COAP_OPTION_URI_PATH, 4,
                         (const uint8_t *)"echo") ||
        !coap_add_data(pdu, length, payload)) {
        coap_delete_pdu(pdu);
        return false;
    }
    coap_start_us = esp_timer_get_time();
    if (coap_send(session, pdu) == COAP_INVALID_MID) return false;
    const int64_t deadline = coap_start_us + TIMEOUT_MS * 1000LL;
    while (!coap_reply_received && esp_timer_get_time() < deadline) {
        int64_t remaining_ms = (deadline - esp_timer_get_time() + 999) / 1000;
        if (remaining_ms <= 0) break;
        int wait_ms = remaining_ms > 100 ? 100 : (int)remaining_ms;
        if (coap_io_process(ctx, wait_ms) < 0) break;
    }
    return coap_reply_received && coap_reply_valid;
}
static void coap_close(coap_context_t *ctx, coap_session_t *session)
{
    if (session) coap_session_release(session);
    if (ctx) coap_free_context(ctx);
    coap_cleanup();
}
/* =====================================================
   BENCHMARK RUNNER
   ===================================================== */
static void run_variant(
    const char *variant,
    int n)
{
    if (!wifi_ready || n < 1 || n > 1000) {
        printf("Invalid run parameters\n");
        return;
    }
    int qos = -1;
    bool is_http_new = strcmp(variant, "http_new") == 0;
    bool is_http_keep = strcmp(variant, "http_keep") == 0;
    bool is_mqtt =
        strcmp(variant, "mqtt0") == 0 ||
        strcmp(variant, "mqtt1") == 0 ||
        strcmp(variant, "mqtt2") == 0;
    if (is_mqtt) {
        qos = variant[4] - '0';
    }
    bool is_coap_con = strcmp(variant, "coap_con") == 0;
    bool is_coap_non = strcmp(variant, "coap_non") == 0;
    bool is_coap = is_coap_con || is_coap_non;
    if (!is_http_new && !is_http_keep && !is_mqtt && !is_coap) {
        printf("Unknown variant: %s\n", variant);
        return;
    }
    esp_http_client_handle_t http_client = NULL;
    esp_mqtt_client_handle_t mqtt_client = NULL;
    coap_context_t *coap_ctx = NULL;
    coap_session_t *coap_session = NULL;
    if (is_http_keep) {
        esp_http_client_config_t config = {
            .url = "http://" SERVER_IP ":8080/echo",
            .method = HTTP_METHOD_POST,
            .timeout_ms = TIMEOUT_MS,
            .event_handler = http_event_handler,
            .keep_alive_enable = true,
        };
        http_client = esp_http_client_init(&config);
    }
    if (is_mqtt) {
        mqtt_client = mqtt_start(qos);
    }
    if (is_coap && !coap_open(&coap_ctx, &coap_session)) {
        printf("CoAP initialization failed\n");
        return;
    }
    printf("\nStarting %s with %d requests\n", variant, n);
    uint8_t payload[PAYLOAD_SIZE];
    memset(payload, 'x', sizeof(payload));
    for (int i = 0; i < n; i++) {
        char sequence[12];
        snprintf(sequence, sizeof(sequence), "%d", i);
        memcpy(payload, sequence, strlen(sequence));
        int64_t t0 = esp_timer_get_time();
        bool ok = false;
        if (is_http_new) {
            ok = http_new_request(payload, sizeof(payload));
        }
        else if (is_http_keep) {
            ok = http_keep_request(
                http_client,
                payload,
                sizeof(payload)
            );
        }
        else if (is_mqtt) {
            ok = mqtt_request(
                mqtt_client,
                qos,
                payload,
                sizeof(payload)
            );
        }
        else if (is_coap) {
            ok = coap_request(coap_ctx, coap_session,
                              is_coap_con ? COAP_MESSAGE_CON : COAP_MESSAGE_NON,
                              payload, sizeof(payload));
        }
        int64_t rtt = esp_timer_get_time() - t0;
        if (is_coap) rtt = coap_rtt_us;
        printf("%d,%lld,%d\n",
               i,
               ok ? (long long)rtt : -1LL,
               ok ? 1 : 0);
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    if (http_client != NULL) {
        esp_http_client_cleanup(http_client);
    }
    if (mqtt_client != NULL) {
        esp_mqtt_client_stop(mqtt_client);
        esp_mqtt_client_destroy(mqtt_client);
        vEventGroupDelete(mqtt_events);
        vSemaphoreDelete(mqtt_response_sem);
    }
    if (is_coap) coap_close(coap_ctx, coap_session);
    printf("DONE\n");
}
/* =====================================================
   MAIN
   ===================================================== */
void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    } else {
        ESP_ERROR_CHECK(ret);
    }
    wifi_init();
    printf("\n====================================\n");
    printf(" ESP32 IoT Protocol Benchmark\n");
    printf("====================================\n");
    printf("Available commands:\n");
    printf("RUN http_new N\n");
    printf("RUN http_keep N\n");
    printf("RUN mqtt0 N\n");
    printf("RUN mqtt1 N\n");
    printf("RUN mqtt2 N\n");
    printf("RUN coap_con N\n");
    printf("RUN coap_non N\n");
    printf("====================================\n");
    char line[64];
    char variant[32];
    int n;
    size_t pos = 0;

    while (1) {
        int ch = getchar();

        if (ch == EOF) {
            clearerr(stdin);
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        if (ch == '\r') {
            continue;
        }

        if (ch == '\n') {
            line[pos] = '\0';

            if (pos > 0) {
                if (sscanf(line, "RUN %31s %d", variant, &n) == 2
                    && n > 0) {
                    run_variant(variant, n);
                } else {
                    printf("Invalid command. Use RUN variant N\n");
                }
            }

            pos = 0;
            continue;
        }

        if (pos < sizeof(line) - 1) {
            line[pos++] = (char)ch;
        } else {
            pos = 0;
        }
    }
}
