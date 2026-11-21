/* Fake-only whole-driver replay host. Never linked into a native candidate. */
#include "apcmicrolink-hidapi-native.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct replay_host {
	int64_t now_ms;
	unsigned int init_calls;
	unsigned int select_calls;
	unsigned int open_calls;
	unsigned int close_calls;
	unsigned int dispose_calls;
	unsigned int read_calls;
	unsigned int wait_calls;
	unsigned int stop_writes;
	unsigned int init_writes;
	unsigned int next_writes;
	unsigned int other_writes;
	int close_fails;
	int report_pending;
	unsigned char report[64];
} replay_host_t;

static replay_host_t host;

static void report_counters(void)
{
	fprintf(stderr,
		"FAKE_COUNTERS init=%u select=%u open=%u close=%u dispose=%u "
			"read=%u wait=%u stop=%u init_byte=%u next=%u other_write=%u now_ms=%lld\n",
		host.init_calls, host.select_calls, host.open_calls, host.close_calls,
		host.dispose_calls, host.read_calls, host.wait_calls, host.stop_writes, host.init_writes,
		host.next_writes, host.other_writes, (long long)host.now_ms);
}

static int fake_ok(void *user)
{
	(void)user;
	return 0;
}

static int fake_init(void *user)
{
	replay_host_t *state = (replay_host_t *)user;
	state->init_calls++;
	return 0;
}

static int fake_select_unique(void *user, unsigned int *selected_count)
{
	replay_host_t *state = (replay_host_t *)user;
	state->select_calls++;
	*selected_count = 1U;
	return 0;
}

static int fake_open(void *user)
{
	replay_host_t *state = (replay_host_t *)user;
	state->open_calls++;
	return 0;
}

static int fake_layout(void *user, mlink_shared_layout_t *layout)
{
	(void)user;
	memset(layout, 0, sizeof(*layout));
	layout->selected_count = 1U;
	layout->input_report_id = 1U;
	layout->output_report_id = 2U;
	layout->input_direction = MLINK_SHARED_INPUT;
	layout->output_direction = MLINK_SHARED_OUTPUT;
	layout->input_report_length = 64U;
	layout->output_report_length = 64U;
	return 0;
}

static void queue_page(replay_host_t *state, unsigned char id,
	const unsigned char data[48])
{
	unsigned char frame[51] = {0};
	unsigned int c0 = 0, c1 = 0;
	size_t i;
	frame[0] = id;
	memcpy(frame + 1U, data, 48U);
	for (i = 0; i < 49U; i++) {
		c0 = (c0 + frame[i]) % 255U;
		c1 = (c1 + c0) % 255U;
	}
	frame[49] = (unsigned char)(255U - ((c0 + c1) % 255U));
	frame[50] = (unsigned char)(255U - ((c0 + frame[49]) % 255U));
	memset(state->report, 0, sizeof(state->report));
	state->report[0] = 1U; /* input report ID */
	memcpy(state->report + 1U, frame, sizeof(frame));
	state->report_pending = 1;
}

static void queue_protocol_page(replay_host_t *state, unsigned char flags)
{
	unsigned char data[48] = {0};
	const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
	data[0] = 1U;  /* protocol version */
	data[1] = 48U; /* data width */
	data[2] = 3U;  /* page count */
	data[3] = 0U;
	data[4] = 1U;  /* series ID */
	data[5] = 1U;  /* series data version */
	data[6] = flags; /* descriptor present, no authentication */
	data[8] = 1U;  /* descriptor version */
	data[10] = 1U; /* descriptor data pointer: page 1, offset 0 */
	data[11] = 0U;
	{
		static const unsigned char definition[] = {
			0xF8U, 2U, 0xFEU, 4U, 0x0AU, 0xFEU, 5U,
			0x20U, 0x9FU, 0x21U, 0x22U, 0xFFU, 0xFEU, 6U,
			0x25U, 0x27U, 0xFFU, 0xFEU, 7U, 0x25U, 0x26U, 0x27U,
			0x28U, 0x2AU, 0x2BU, 0x49U, 0xFFU, 0xFFU, 0xFFU, 0xFFU
		};
		memcpy(data + 12U, definition, sizeof(definition));
	}
	if (scenario != NULL && strcmp(scenario, "bad-descriptor") == 0)
		data[12U] = 0U;
	queue_page(state, 0U, data);
}

static void queue_measurement_page(replay_host_t *state)
{
	unsigned char data[48] = {0};
	static const unsigned char values[] = {
		0x00U, 0x02U, /* ups.status OL */
		0x64U, 0x00U, /* battery.charge = 50 percent */
		0x0EU, 0x10U, /* battery.runtime = 3600 seconds */
		0x01U, 0x80U, /* battery.voltage = 12 V */
		0x0CU, 0x80U, /* temperature = 25 C */
		0x1EU, 0x00U, /* input.voltage = 120 V */
		0x1EU, 0x00U, /* input.frequency = 60 Hz */
		0x1EU, 0x00U, /* output.voltage = 120 V */
		0x00U, 0xA0U, /* output.current = 5 A */
		0x1EU, 0x00U, /* output.frequency = 60 Hz */
		0x12U, 0xCCU, /* ups.load = 18.796875 percent */
		0x03U, 0x84U, /* real power nominal = 900 W */
		0x04U, 0xB0U, /* power nominal = 1200 VA */
		0x16U, 0x39U  /* apparent load = 22.22265625 percent */
	};
	memcpy(data, values, sizeof(values));
	queue_page(state, 1U, data);
}

static void queue_unrelated_page(replay_host_t *state)
{
	unsigned char data[48] = {0};
	memset(data, 0x5a, sizeof(data));
	queue_page(state, 2U, data);
}

static ssize_t fake_read(void *user, unsigned char *dst, size_t capacity,
	unsigned int timeout_ms)
{
	replay_host_t *state = (replay_host_t *)user;
	(void)timeout_ms;
	state->read_calls++;
	if (!state->report_pending) return 0;
	if (capacity < sizeof(state->report)) return -1;
	{
		const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
		if (scenario != NULL && strcmp(scenario, "late-page") == 0
		 && state->read_calls == 4U) {
			state->now_ms += 120000;
		}
	}
	memcpy(dst, state->report, sizeof(state->report));
	state->report_pending = 0;
	return (ssize_t)sizeof(state->report);
}

static ssize_t fake_write(void *user, const unsigned char *src, size_t length)
{
	replay_host_t *state = (replay_host_t *)user;
	unsigned char command;
	if (length != 64U || src[0] != 2U) return -1;
	command = src[1];
	switch (command) {
	case 0xF7U: state->stop_writes++; break;
	case 0xFDU: state->init_writes++; queue_protocol_page(state, 0x08U); break;
	case 0xFEU:
		state->next_writes++;
		if (state->next_writes == 1U) {
			queue_measurement_page(state);
		} else if (state->next_writes == 2U) {
			queue_unrelated_page(state);
		} else {
			const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
			if (scenario != NULL && strcmp(scenario, "mutate-geometry") == 0
			 && state->next_writes == 3U)
				queue_protocol_page(state, 0U);
			else if (scenario != NULL && strcmp(scenario, "unrelated-refresh") == 0)
				queue_unrelated_page(state);
			else
				queue_measurement_page(state);
		}
		break;
	default: state->other_writes++; break;
	}
	return (ssize_t)length;
}

static int fake_close(void *user)
{
	replay_host_t *state = (replay_host_t *)user;
	const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
	state->close_calls++;
	state->close_fails = scenario != NULL && strcmp(scenario, "close-fails") == 0;
	return state->close_fails ? -1 : 0;
}

static int fake_stopped(void *user)
{
	(void)user;
	return 0;
}

static int fake_clock(void *user, int64_t *now_ms)
{
	replay_host_t *state = (replay_host_t *)user;
	*now_ms = state->now_ms;
	return 0;
}

static const mlink_shared_host_ops_t fake_ops = {
	fake_init, fake_ok, fake_select_unique, fake_open, fake_layout,
	fake_read, fake_write, fake_close, fake_stopped, fake_clock, NULL
};

int mlink_hidapi_native_create(const mlink_hidapi_native_config_t *config,
	mlink_hidapi_native_binding_t *binding)
{
	if (config == NULL || binding == NULL || binding->ops != NULL) return -1;
	if (atexit(report_counters) != 0) return -1;
	binding->ops = &fake_ops;
	binding->user = &host;
	return 0;
}

int mlink_hidapi_native_dispose(mlink_hidapi_native_binding_t *binding)
{
	if (binding == NULL || binding->ops != &fake_ops || binding->user != &host
	 || host.close_fails) return -1;
	host.dispose_calls++;
	memset(binding, 0, sizeof(*binding));
	return 0;
}

int mlink_continuous_replay_wait(unsigned int wait_ms)
{
	const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
	if (wait_ms > 100U) return 0;
	host.wait_calls++;
	if (scenario != NULL && strcmp(scenario, "missed-slots") == 0
	 && host.wait_calls == 1U) {
		host.now_ms += 15000;
		return 1;
	}
	host.now_ms += (int64_t)wait_ms;
	return 1;
}
