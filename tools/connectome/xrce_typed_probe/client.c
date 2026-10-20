/* Synthetic XRCE transport diagnostic, following fixed PX4 binary-entity QoS.
 * This is not a PX4 client or a vehicle telemetry source. */

#include <uxr/client/client.h>
#include <ucdr/microcdr.h>

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>

#define BODY_BYTES 116U
#define STREAM_HISTORY 8U
#define BUFFER_BYTES (UXR_CONFIG_UDP_TRANSPORT_MTU * STREAM_HISTORY)
#define TEST_CLIENT_KEY 0xF1D0D017U

static const char *TOPIC = "rt/fmu/out/vehicle_odometry";
static const char *DDS_TYPE = "px4_msgs::msg::dds_::VehicleOdometry_";

static int statuses_ok(const uint8_t statuses[4])
{
    for (size_t i = 0; i < 4; ++i) {
        if (statuses[i] != UXR_STATUS_OK && statuses[i] != UXR_STATUS_OK_MATCHED) {
            return 0;
        }
    }
    return 1;
}

static int read_body(const char *path, uint8_t body[BODY_BYTES])
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        fprintf(stderr, "body_open_failed\n");
        return 1;
    }
    size_t received = fread(body, 1, BODY_BYTES, file);
    int tail = fgetc(file);
    int failed = ferror(file);
    int closed = fclose(file);
    if (received != BODY_BYTES || tail != EOF || failed || closed != 0) {
        fprintf(stderr, "body_length_or_io_refused\n");
        return 1;
    }
    return 0;
}

/* 0 means the observer has not written the marker; -1 is a hard refusal. */
static int ready_status(const char *path)
{
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        return errno == ENOENT ? 0 : -1;
    }
    char marker[6];
    size_t count = fread(marker, 1, sizeof(marker), file);
    int tail = fgetc(file);
    int failed = ferror(file);
    int closed = fclose(file);
    if (count != sizeof(marker) || memcmp(marker, "ready\n", sizeof(marker)) != 0
            || tail != EOF || failed || closed != 0) {
        return -1;
    }
    return 1;
}

static int wait_ready(const char *path)
{
    for (int i = 0; i < 8; ++i) {
        int status = ready_status(path);
        if (status == 1) {
            return 1;
        }
        if (status < 0) {
            return 0;
        }
        sleep(1);
    }
    return 0;
}

static int send_one(const char *ip, const char *port,
                    const uint8_t body[BODY_BYTES], const char *ready_path)
{
    uxrUDPTransport transport;
    if (!uxr_init_udp_transport(&transport, UXR_IPv4, ip, port)) {
        fprintf(stderr, "transport_failed\n");
        return 2;
    }
    uxrSession session;
    uxr_init_session(&session, &transport.comm, TEST_CLIENT_KEY);
    if (!uxr_create_session(&session)) {
        fprintf(stderr, "session_failed\n");
        uxr_close_udp_transport(&transport);
        return 3;
    }

    uint8_t reliable_out_buffer[BUFFER_BYTES];
    uint8_t reliable_in_buffer[BUFFER_BYTES];
    uint8_t best_effort_buffer[UXR_CONFIG_UDP_TRANSPORT_MTU];
    uxrStreamId reliable_out = uxr_create_output_reliable_stream(
        &session, reliable_out_buffer, BUFFER_BYTES, STREAM_HISTORY);
    uxr_create_input_reliable_stream(&session, reliable_in_buffer, BUFFER_BYTES, STREAM_HISTORY);
    uxrStreamId best_effort_out = uxr_create_output_best_effort_stream(
        &session, best_effort_buffer, sizeof(best_effort_buffer));

    uxrObjectId participant = uxr_object_id(1, UXR_PARTICIPANT_ID);
    uxrObjectId topic = uxr_object_id(1, UXR_TOPIC_ID);
    uxrObjectId publisher = uxr_object_id(1, UXR_PUBLISHER_ID);
    uxrObjectId writer = uxr_object_id(1, UXR_DATAWRITER_ID);
    uxrQoS_t qos = {
        .durability = UXR_DURABILITY_TRANSIENT_LOCAL,
        .reliability = UXR_RELIABILITY_BEST_EFFORT,
        .history = UXR_HISTORY_KEEP_LAST,
        .depth = 0,
    };
    uint16_t requests[4] = {
        uxr_buffer_create_participant_bin(&session, reliable_out, participant, 0,
                                          "flydrones_synthetic_diagnostic", UXR_REPLACE),
        uxr_buffer_create_topic_bin(&session, reliable_out, topic, participant,
                                    TOPIC, DDS_TYPE, UXR_REPLACE),
        uxr_buffer_create_publisher_bin(&session, reliable_out, publisher,
                                        participant, UXR_REPLACE),
        uxr_buffer_create_datawriter_bin(&session, reliable_out, writer,
                                         publisher, topic, qos, UXR_REPLACE),
    };
    uint8_t statuses[4] = {255, 255, 255, 255};
    int received = uxr_run_session_until_all_status(&session, 2000, requests, statuses, 4);
    if (!received || !statuses_ok(statuses)) {
        fprintf(stderr, "entity_failed:%u,%u,%u,%u\n", statuses[0], statuses[1],
                statuses[2], statuses[3]);
        uxr_delete_session(&session);
        uxr_close_udp_transport(&transport);
        return 4;
    }

    if (!wait_ready(ready_path)) {
        fprintf(stderr, "graph_ready_failed\n");
        uxr_delete_session(&session);
        uxr_close_udp_transport(&transport);
        return 6;
    }
    /* The observer has seen the collector and Agent endpoints; send once. */
    ucdrBuffer output;
    if (uxr_prepare_output_stream(&session, best_effort_out, writer, &output,
                                  BODY_BYTES) == UXR_INVALID_REQUEST_ID
            || !ucdr_serialize_array_uint8_t(&output, body, BODY_BYTES)
            || output.error) {
        fprintf(stderr, "serialize_failed\n");
        uxr_delete_session(&session);
        uxr_close_udp_transport(&transport);
        return 5;
    }
    uxr_flash_output_streams(&session);
    (void)uxr_run_session_time(&session, 1000);
    puts("{\"session\":true,\"entities\":true,\"synthetic_sent\":1,"
         "\"px4_source_authenticated\":false}");
    uxr_delete_session(&session);
    uxr_close_udp_transport(&transport);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc == 6 && strcmp(argv[1], "--check-statuses") == 0) {
        uint8_t statuses[4];
        for (size_t i = 0; i < 4; ++i) {
            char *end = NULL;
            unsigned long value = strtoul(argv[i + 2], &end, 10);
            if (end == argv[i + 2] || *end != '\0' || value > 255) {
                return 1;
            }
            statuses[i] = (uint8_t)value;
        }
        return statuses_ok(statuses) ? 0 : 1;
    }
    if (argc == 2 && strcmp(argv[1], "--describe") == 0) {
        printf("{\"topic\":\"%s\",\"type\":\"%s\",\"message_version\":0,"
               "\"client_key\":%u,\"synthetic_only\":true}\n",
               TOPIC, DDS_TYPE, TEST_CLIENT_KEY);
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "--check-ready") == 0) {
        return ready_status(argv[2]) == 1 ? 0 : 1;
    }
    if (argc == 3 && strcmp(argv[1], "--self-test") == 0) {
        uint8_t body[BODY_BYTES];
        if (read_body(argv[2], body) != 0) {
            return 1;
        }
        puts("{\"body_bytes\":116,\"synthetic_only\":true}");
        return 0;
    }
    if (argc == 6 && strcmp(argv[1], "--send") == 0
            && strcmp(argv[2], "127.0.0.1") == 0
            && strcmp(argv[3], "18893") == 0) {
        uint8_t body[BODY_BYTES];
        if (read_body(argv[4], body) != 0) {
            return 1;
        }
        return send_one(argv[2], argv[3], body, argv[5]);
    }
    fprintf(stderr, "usage: client --describe | --self-test BODY | --check-ready FILE | --send 127.0.0.1 18893 BODY READYFILE\n");
    return 1;
}
