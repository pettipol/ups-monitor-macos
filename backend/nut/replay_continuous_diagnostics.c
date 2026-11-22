/* Fake-only whole-driver replay host. Never linked into a native candidate. */
#include "apcmicrolink-hidapi-native.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <errno.h>

typedef struct replay_host {
	int64_t now_ms;
	unsigned int init_calls;
	unsigned int select_calls;
	unsigned int open_calls;
	unsigned int close_calls;
	unsigned int dispose_calls;
	unsigned int read_calls;
	unsigned int wait_calls;
	unsigned int clock_calls;
	unsigned int stop_writes;
	unsigned int init_writes;
	unsigned int next_writes;
	unsigned int other_writes;
	int close_fails;
	int report_pending;
	int corrupt_sent;
	unsigned char report[64];
	char operation_trace[262144];
	size_t operation_trace_len;
	int trace_truncated;
	const char *trace_pending;
	unsigned int trace_pending_count;
} replay_host_t;

static replay_host_t host;

static void trace_flush(void)
{
	int count;
	if (host.trace_pending == NULL) return;
	if (host.operation_trace_len >= sizeof(host.operation_trace)) {
		host.trace_truncated = 1;
		return;
	}
	count = snprintf(host.operation_trace + host.operation_trace_len,
		sizeof(host.operation_trace) - host.operation_trace_len,
		"%s%s*%u", host.operation_trace_len == 0U ? "" : ",",
		host.trace_pending, host.trace_pending_count);
	if (count > 0 && (size_t)count < sizeof(host.operation_trace) - host.operation_trace_len)
		host.operation_trace_len += (size_t)count;
	else host.trace_truncated = 1;
}

static void trace_operation(const char *token)
{
	/* Lossless run-length encoding, not event filtering: every consecutive
	 * event is represented by its exact multiplicity, and tests validate it. */
	if (host.trace_pending != NULL && strcmp(host.trace_pending, token) == 0) {
		if (host.trace_pending_count == ~0U) host.trace_truncated = 1;
		else host.trace_pending_count++;
		return;
	}
	trace_flush();
	host.trace_pending = token;
	host.trace_pending_count = 1U;
}

/* Fake-only wall clock: the real driver uses time(NULL) for idle detection,
 * while the scripted monotonic host advances without sleeping. No production
 * translation unit is modified, and no real wall timestamp is exported. */
time_t time(time_t *output)
{
	time_t result = (time_t)1700000000 + (time_t)(host.now_ms / 1000);
	if (output != NULL) *output = result;
	return result;
}

/* state_get_timestamp in the admitted H03 archive uses CLOCK_MONOTONIC
 * (both HAVE_CLOCK_* defines are 1). Share the scripted time with its real
 * receive-timeout arithmetic instead of spinning against the OS clock. */
int clock_gettime(clockid_t clock_id, struct timespec *output)
{
	int64_t milliseconds = host.now_ms;
	if (clock_id == CLOCK_REALTIME) milliseconds += INT64_C(1700000000000);
	else if (clock_id != CLOCK_MONOTONIC) { errno = EINVAL; return -1; }
	trace_operation("SYSTEM_CLOCK");
	output->tv_sec = (time_t)(milliseconds / 1000);
	output->tv_nsec = (long)((milliseconds % 1000) * 1000000);
	return 0;
}

static void report_counters(void)
{
	trace_flush();
	fprintf(stderr,
		"FAKE_COUNTERS init=%u select=%u open=%u close=%u dispose=%u "
			"read=%u wait=%u clock=%u trace_truncated=%d stop=%u init_byte=%u next=%u other_write=%u now_ms=%lld\n",
		host.init_calls, host.select_calls, host.open_calls, host.close_calls,
		host.dispose_calls, host.read_calls, host.wait_calls, host.clock_calls,
		host.trace_truncated, host.stop_writes, host.init_writes,
		host.next_writes, host.other_writes, (long long)host.now_ms);
	fprintf(stderr, "FAKE_TRACE %s\n", host.operation_trace);
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
	trace_operation("INIT");
	return 0;
}

static int fake_select_unique(void *user, unsigned int *selected_count)
{
	replay_host_t *state = (replay_host_t *)user;
	state->select_calls++;
	trace_operation("SELECT");
	*selected_count = 1U;
	return 0;
}

static int fake_open(void *user)
{
	replay_host_t *state = (replay_host_t *)user;
	state->open_calls++;
	trace_operation("OPEN");
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

static void queue_implausible_page0(replay_host_t *state)
{
	unsigned char *frame;
	unsigned int c0 = 0U, c1 = 0U;
	size_t i;
	queue_protocol_page(state, 0x08U);
	frame = state->report + 1U;
	frame[2] = 247U; /* impossible announced width, but checksum remains valid */
	for (i = 0U; i < 49U; i++) {
		c0 = (c0 + frame[i]) % 255U;
		c1 = (c1 + c0) % 255U;
	}
	frame[49] = (unsigned char)(255U - ((c0 + c1) % 255U));
	frame[50] = (unsigned char)(255U - ((c0 + frame[49]) % 255U));
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
	state->read_calls++;
	trace_operation("READ");
	if (!state->report_pending) {
		/* An empty read consumes the exact timeout requested by the shared
		 * backend; it neither returns an I/O error nor invents a frame. */
		state->now_ms += (int64_t)timeout_ms;
		return 0;
	}
	if (capacity < sizeof(state->report)) return -1;
	{
		const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
		if (scenario != NULL && strcmp(scenario, "late-page") == 0
		 && state->read_calls == 4U) {
			state->now_ms += 120000;
		}
		if (scenario != NULL && strcmp(scenario, "corrupt-recovery") == 0
		 && state->next_writes == 3U && !state->corrupt_sent) {
			state->report[50U] ^= 0x01U;
			state->corrupt_sent = 1;
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
	case 0xF7U:
		state->stop_writes++;
		trace_operation("STOP");
		if (getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO") != NULL
		 && strcmp(getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO"), "stop-fails") == 0
		 && state->stop_writes > 1U)
			return -1;
		break;
	case 0xFDU:
		state->init_writes++;
		trace_operation("INIT_BYTE");
		if (getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO") == NULL
		 || strcmp(getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO"), "no-handshake-success") != 0)
			queue_protocol_page(state, 0x08U);
		break;
	case 0xFEU:
		state->next_writes++;
		trace_operation("NEXT");
		if (state->next_writes == 1U) {
			queue_measurement_page(state);
		} else if (state->next_writes == 2U) {
			queue_unrelated_page(state);
		} else if (getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO") != NULL
		 && (strcmp(getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO"), "handshake-then-silent") == 0
	  || strcmp(getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO"), "idle-timeout") == 0
	  || strcmp(getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO"), "silent-close-fails") == 0)) {
			/* Startup includes successful polls; then no further report. */
		} else if (getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO") != NULL
		 && strcmp(getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO"), "implausible-page0") == 0
		 && state->next_writes == 3U) {
			queue_implausible_page0(state);
		} else {
			const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
			if (scenario != NULL && strcmp(scenario, "mutate-geometry") == 0
			 && state->next_writes == 3U)
				queue_protocol_page(state, 0U);
			else if (scenario != NULL && strcmp(scenario, "unrelated-refresh") == 0)
				queue_unrelated_page(state);
			else if (scenario != NULL
			 && (strcmp(scenario, "same-payload") == 0
			  || strcmp(scenario, "corrupt-recovery") == 0
			  || strcmp(scenario, "stop-fails") == 0
			  || strcmp(scenario, "duration-cleanup-fails") == 0)
			 && state->next_writes % 2U == 0U)
				queue_unrelated_page(state);
			else
				/* Default and cache-no-rebuild deliberately repeat page 1. */
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
	trace_operation("CLOSE");
	state->close_fails = scenario != NULL
		&& (strcmp(scenario, "close-fails") == 0
		 || strcmp(scenario, "silent-close-fails") == 0
		 || strcmp(scenario, "duration-cleanup-fails") == 0);
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
	const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
	state->clock_calls++;
	trace_operation("CLOCK");
	if (scenario != NULL && strcmp(scenario, "clock-guard") == 0
	 && state->wait_calls > 0U) {
		*now_ms = -1;
		return 0;
	}
	*now_ms = state->now_ms;
	return 0;
}

int mlink_hidapi_native_post_finish_clock_ms(int64_t *now_ms)
{
	if (now_ms == NULL) return -1;
	return fake_clock(&host, now_ms);
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
	trace_operation("DISPOSE");
	memset(binding, 0, sizeof(*binding));
	return 0;
}

int mlink_continuous_replay_wait(unsigned int wait_ms)
{
	const char *scenario = getenv("MLINK_CONTINUOUS_REPLAY_SCENARIO");
	if (wait_ms > 100U) return 0;
	host.wait_calls++;
	trace_operation("WAIT");
	if (scenario != NULL && strcmp(scenario, "cancelled") == 0
	 && host.wait_calls == 1U) {
		/* NUT's existing handler latches the stop flag in this fake process,
		 * after startup and the first sample. Never signal another process. */
		(void)raise(SIGTERM);
	}
	if (scenario != NULL && strcmp(scenario, "missed-slots") == 0
	 && host.wait_calls == 1U) {
		host.now_ms += 15000;
		return 1;
	}
	host.now_ms += (int64_t)wait_ms;
	return 1;
}
