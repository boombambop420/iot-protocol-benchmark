# IoT Communication Protocol Benchmark

## Project Overview

This project compares the reliability, latency, and communication overhead of HTTP, MQTT, and CoAP in an ESP32–Raspberry Pi IoT testbed under varying network conditions.

## Hardware and Software

- ESP32 microcontroller running ESP-IDF 5.5.2
- Raspberry Pi 1: experiment controller and Wi-Fi access point
- Raspberry Pi 2: protocol echo servers and Mosquitto broker
- Ethernet connection between the Raspberry Pis
- Python-based benchmarking and network impairment scripts
- Packet capture analysis using Wireshark

## Protocol Configurations

Seven configurations were evaluated:

1. HTTP with a new TCP connection
2. HTTP with persistent TCP (Keep-Alive)
3. MQTT QoS 0
4. MQTT QoS 1
5. MQTT QoS 2
6. CoAP Confirmable (CON)
7. CoAP Non-confirmable (NON)

## Network Conditions

| Condition | Delay | Packet Loss |
|-----------|-------|-------------|
| C1 | 0 ms | 0% |
| C2 | 50 ms | 0% |
| C3 | 0 ms | 2% |
| C4 | 0 ms | 5% |
| C5 | 50 ms | 5% |
| C6 | 200 ms | 10% |

Network impairments were introduced using Linux traffic control (netem).

## Experimental Method

Each protocol was tested under all six conditions using 100 sequential request/echo transactions per configuration.

- Application payload: 64 bytes
- Per-request timeout: 10 seconds
- Total original configurations: 42
- Primary measurements: success rate and round-trip latency
- Additional analysis: goodput, captured-byte overhead, and packet behavior

## Corrections and Retests

### HTTP Keep-Alive

The initial HTTP server did not maintain persistent TCP connections as intended. The server was changed to Waitress, and HTTP Keep-Alive was retested under all six conditions.

### MQTT QoS 2

The original ESP-IDF MQTT configuration used a 1-second message retransmission timeout. Packet captures and broker logs revealed duplicate QoS 2 PUBLISH messages and broker protocol-error disconnects.

The retransmission timeout was increased to 5 seconds, and MQTT QoS 2 was retested across all six network conditions.

Original success: 476/600 (79.3%)

Updated success: 585/600 (97.5%)

The revised configuration improved observed reliability but did not eliminate all failures under C6.

## Repository Structure

- `esp32/` — ESP32 firmware source and CMake configuration
- `pi1/scripts/` — benchmark and network-condition scripts
- `pi2/scripts/` — HTTP, MQTT, and CoAP server scripts
- `pi2/mosquitto/` — MQTT broker configuration
- `data/original_results/` — original measurements and packet captures, plus consolidated summary files
- `data/corrected_retests/` — corrected HTTP and MQTT measurements
- `figures/` — comparison graphs

The consolidated corrected summary is located at:
`data/original_results/benchmark_summary_corrected.csv`

The original summary is retained separately.

## Reproducibility Notes

The ESP32 firmware contains placeholder Wi-Fi credentials. Users must supply credentials for their own network.

The Mosquitto configuration permits anonymous connections for this experimental setup. This setting is not recommended for production deployments.

The corrected MQTT QoS 2 configuration differs from the original configuration. Results should therefore be interpreted with that distinction in mind.

Measurements were obtained from individual benchmark runs. Latency statistics describe successful transactions and exclude failed requests.

## Results and Interpretation

The figures illustrate how different application-layer protocols respond to artificial network delay and packet loss.

These results characterize the tested implementations and network setup rather than establishing universal performance rankings for HTTP, MQTT, or CoAP.

## Reproducing the Corrected HTTP Keep-Alive Server

The corrected HTTP Keep-Alive experiments used Waitress 3.0.2
instead of Flask's development server.

On Raspberry Pi 2, install Flask and Waitress:

    python3 -m pip install flask==3.1.3 waitress==3.0.2

Start the corrected HTTP echo server:

    bash pi2/scripts/start_http_waitress.sh

The server listens on port 8080 and provides the /echo endpoint.

This launcher reproduces the intended corrected server configuration.
The exact historical startup command was not retained.

## Verified Firmware and Network Settings

- ESP32 Wi-Fi power saving disabled using esp_wifi_set_ps(WIFI_PS_NONE).
- MQTT QoS 2 retransmission timeout: 5000 milliseconds.
- Network jitter: max(1, delay // 5) milliseconds.
- C2 and C5: 50 ms delay with 10 ms jitter.
- C6: 200 ms delay with 40 ms jitter.
- Network impairments configured using Linux tc netem.

Original measurements and corrected retests are retained separately.
